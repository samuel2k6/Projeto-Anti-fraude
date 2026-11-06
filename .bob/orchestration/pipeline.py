"""
orchestration/pipeline.py
==========================
Entry point do pipeline de transações anti-fraude.

Uso direto:
    python -m orchestration.pipeline

Uso como módulo:
    from orchestration.pipeline import executar_pipeline

O pipeline completo:
  1. Recebe um lote de transações.
  2. Para cada transação, delega ao ``AgenteAntiFraude``:
       - Score ≤ 70 → aprovação automática (síncrono)
       - Score > 70 → fluxo HITL assíncrono:
           • Pausa liquidação
           • Gera explicação humanizada
           • Exibe notificação push simulada no terminal
           • Entra em AWAIT aguardando decisão do operador (stdin)
           • Aplica ação final (aprovar / bloquear / timeout)
  3. Exibe o relatório consolidado ao final.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestration.agent_flow import (
    AgenteAntiFraude,
    DecisaoTransacao,
    ResultadoPipeline,
    StatusLiquidacao,
)

log = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Casos de teste embutidos (cobrem baixo, médio e alto risco)
# ---------------------------------------------------------------------------

_TRANSACOES_DEMO: list[dict[str, Any]] = [
    # ── Caso 1: risco BAIXO — transação normal dentro do padrão ──────────
    {
        "transacao_id": "demo_001",
        "associado_id": "assoc_001",
        "valor": 130.00,
        "categoria": "Supermercados",
        "timestamp": "2026-11-03T09:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
    # ── Caso 2: risco MÉDIO — pico de valor (score ~35, ≤ 70) ────────────
    {
        "transacao_id": "demo_002",
        "associado_id": "assoc_001",
        "valor": 1500.00,          # muito acima da média (~129 R$) → score 35
        "categoria": "Supermercados",
        "timestamp": "2026-11-03T10:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
    # ── Caso 3: risco CRÍTICO — pico + perfil incomum (score > 70) ───────
    # → Dispara HITL: push + await decisão humana
    {
        "transacao_id": "demo_003",
        "associado_id": "assoc_001",
        "valor": 2000.00,           # pico extremo → +35
        "categoria": "Eletrônicos", # alto risco em madrugada → +25  total: 60
        # OBS: assoc_001 já tem demo_002 no histórico (1500), então a média sobe
        # e o pico se mantém. Eletrônicos às 02h30 = PERFIL_INCOMUM.
        "timestamp": "2026-11-03T02:30:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
    # ── Caso 4: risco CRÍTICO — velocidade impossível (score > 70) ───────
    # → Dispara HITL: push + await decisão humana
    {
        "transacao_id": "demo_004",
        "associado_id": "assoc_002",
        "valor": 800.00,
        "categoria": "Joalherias",
        "timestamp": "2026-11-01T09:15:00",  # 15 min após t101 em Rio de Janeiro
        "latitude": -3.7327,                 # Fortaleza-CE (3000+ km do Rio)
        "longitude": -38.5270,
    },
]


# ---------------------------------------------------------------------------
# Execução do pipeline (assíncrona)
# ---------------------------------------------------------------------------

async def executar_pipeline_async(
    transacoes: list[dict[str, Any]],
    agente: AgenteAntiFraude | None = None,
    modo_demo: bool = True,
) -> list[ResultadoPipeline]:
    """
    Processa um lote de transações pelo agente e retorna os resultados.

    Em modo_demo=True (padrão), transações críticas coletam a resposta
    humana via stdin (terminal).  Em modo_demo=False, esperam um
    webhook/event externo chamar ``gestor.resolver()``.

    Parâmetros
    ----------
    transacoes : list[dict]
    agente     : instância do agente (cria nova se None)
    modo_demo  : se True, usa stdin como canal de resposta humana

    Retorna
    -------
    Lista de ResultadoPipeline na mesma ordem das transações de entrada.
    """
    if agente is None:
        agente = AgenteAntiFraude()

    resultados: list[ResultadoPipeline] = []

    print("\n" + "═" * 62)
    print("  PIPELINE ANTI-FRAUDE — INÍCIO DO PROCESSAMENTO")
    print("═" * 62)

    for i, transacao in enumerate(transacoes, start=1):
        tid = transacao.get("transacao_id", f"tx-{i}")
        print(f"\n[{i}/{len(transacoes)}] Processando transação: {tid}")
        try:
            resultado = await agente.processar_async(transacao, modo_demo=modo_demo)
            resultados.append(resultado)
            print(resultado.resumo())
        except Exception as exc:
            log.error("Erro ao processar transação %s: %s", tid, exc, exc_info=True)
            print(f"  ❌ ERRO: {exc}\n")

    _imprimir_relatorio(resultados, agente)
    return resultados


def executar_pipeline(
    transacoes: list[dict[str, Any]],
    agente: AgenteAntiFraude | None = None,
) -> list[ResultadoPipeline]:
    """
    Wrapper síncrono de ``executar_pipeline_async``.
    Executa o loop de eventos asyncio internamente.

    Uso programático:
        from orchestration.pipeline import executar_pipeline
        resultados = executar_pipeline(lista_de_transacoes)
    """
    return asyncio.run(
        executar_pipeline_async(transacoes, agente, modo_demo=True)
    )


# ---------------------------------------------------------------------------
# Relatório consolidado
# ---------------------------------------------------------------------------

def _imprimir_relatorio(
    resultados: list[ResultadoPipeline],
    agente: AgenteAntiFraude,
) -> None:
    aprovadas  = [r for r in resultados if r.decisao in (
        DecisaoTransacao.APROVADA,
        DecisaoTransacao.APROVADA_PELO_HUMANO,
    )]
    bloqueadas = [r for r in resultados if r.decisao in (
        DecisaoTransacao.BLOQUEADA,
        DecisaoTransacao.BLOQUEADA_TIMEOUT,
    )]
    pendentes  = [r for r in resultados if r.decisao == DecisaoTransacao.PENDENTE_REVISAO]

    print("\n" + "═" * 62)
    print("  RELATÓRIO CONSOLIDADO")
    print("═" * 62)
    print(f"  Total processadas      : {len(resultados)}")
    print(f"  ✅ Aprovadas (IA)       : {sum(1 for r in aprovadas if r.decisao == DecisaoTransacao.APROVADA)}")
    print(f"  ✅ Aprovadas (humano)   : {sum(1 for r in aprovadas if r.decisao == DecisaoTransacao.APROVADA_PELO_HUMANO)}")
    print(f"  🚫 Bloqueadas (humano)  : {sum(1 for r in bloqueadas if r.decisao == DecisaoTransacao.BLOQUEADA)}")
    print(f"  ⏱  Bloqueadas (timeout) : {sum(1 for r in bloqueadas if r.decisao == DecisaoTransacao.BLOQUEADA_TIMEOUT)}")
    if pendentes:
        print(f"  ⏳ Pendentes revisão    : {len(pendentes)}")

    if bloqueadas or pendentes:
        print("\n  Transações com liquidação PAUSADA:")
        for r in bloqueadas + pendentes:
            liq_icon = "🚫" if r.status_liquidacao == StatusLiquidacao.PAUSADA else "✅"
            print(
                f"    {liq_icon} {r.transacao_id}  score={r.score_risco}  "
                f"nivel={r.nivel_risco}  decisao={r.decisao.value}"
            )

    explicacoes = agente.store.listar_pendentes()
    if explicacoes:
        print(f"\n  📋 Explicações armazenadas no store ({len(explicacoes)}):")
        for e in explicacoes:
            print(f"\n  [{e['transacao_id']}]  decisao={e.get('decisao_final','?')}")
            print(f"    Título    : {e['titulo']}")
            print(f"    Orientação: {e['orientacao']}")

    print("\n" + "═" * 62 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(executar_pipeline_async(_TRANSACOES_DEMO, modo_demo=True))
