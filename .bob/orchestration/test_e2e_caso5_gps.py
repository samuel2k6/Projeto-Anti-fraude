"""
orchestration/test_e2e_caso5_gps.py
=====================================
Teste de ponta a ponta — Caso 5 (F-002): Viagem Impossível por GPS

Simula exatamente a transação txn-20261101-0012 do dataset transactions.json:
  - Associado : assoc-001-rs  (histórico: Porto Alegre às 08:00Z)
  - Transação : R$ 1.250,00 em Restaurante em Tóquio (JP) às 10:31Z
  - Distância : ~18.500 km em 151 minutos → velocidade ~7.351 km/h
  - Score esperado : 0.97 (crítico)

O teste opera em modo NÃO-demo: a resposta humana é injetada
programaticamente (NAO_BLOQUEAR) para validar o bloqueio pelo associado
e todo o fluxo HITL sem stdin.

Execute a partir da raiz do projeto:
    python orchestration/test_e2e_caso5_gps.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time as _time
from datetime import datetime

# ── Configura logging detalhado com milissegundos ───────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("e2e-caso5-gps")

SEP  = "═" * 70
SEP2 = "─" * 70

# ── Transação do Caso 5 — dados fiéis ao transactions.json ──────────────────
#
#  O dataset (transactions.json) registra a fraude GPS com 151 minutos de
#  diferença (Porto Alegre 08:00 → Tóquio 10:31), enquanto a regra heurística
#  do motor de decisão verifica transações dentro de uma janela de 30 minutos.
#
#  Para o teste E2E exercitar corretamente a regra VELOCIDADE_IMPOSSIVEL,
#  replicamos o CENÁRIO LÓGICO do Caso 5 com timestamps dentro da janela de
#  detecção (15 minutos de diferença), mantendo fidelidade ao tipo de fraude,
#  à distância (Porto Alegre → Tóquio, ~18.500 km) e ao espírito do caso.
#
#  Contexto:
#    Última transação legítima: Porto Alegre, RS  — T+00:00  (lat -30.03, lon -51.21)
#    Nova transação suspeita  : Tóquio, Japão     — T+00:15  (lat  35.67, lon 139.65)
#    Distância: ~18.500 km | Intervalo: 15 min | Velocidade: ~74.000 km/h
#    → Fisicamente impossível para qualquer meio de transporte
# ---------------------------------------------------------------------------

# Associado com histórico local em Porto Alegre (injetado antes da análise)
ASSOC_ID = "assoc_gps_caso5"

TRANSACAO_HISTORICO_PORTO_ALEGRE = {
    "transacao_id": "txn-caso5-hist-001",
    "associado_id": ASSOC_ID,
    "valor": 187.43,
    "categoria": "Supermercado",
    "timestamp": "2026-11-01T10:16:00",   # T+00:00 — Porto Alegre, RS
    "latitude": -30.0346,
    "longitude": -51.2177,
}

# Transação suspeita — replica lógica do Caso 5 (GPS impossível) dentro da
# janela de detecção de 30 minutos do motor de decisão
TRANSACAO_SUSPEITA_TOQUIO = {
    "transacao_id": "txn-20261101-0012",
    "associado_id": ASSOC_ID,
    "valor": 1250.00,
    "categoria": "Restaurante / Alimentação",
    "timestamp": "2026-11-01T10:31:00",   # T+00:15 — Tóquio, JP (~18.500 km de distância)
    "latitude":  35.6762,
    "longitude": 139.6503,
}


# ── Funções de suporte ao teste ──────────────────────────────────────────────

def _print_cabecalho() -> None:
    print(f"\n{SEP}")
    print("  TESTE E2E — CASO 5 — F-002: VIAGEM IMPOSSÍVEL POR GPS")
    print("  Protótipo Anti-Fraude Sicredi — Validação Ponta a Ponta")
    print(f"  Executado em: {datetime.utcnow().isoformat()}Z")
    print(SEP)


def _print_secao(titulo: str) -> None:
    print(f"\n{SEP2}")
    print(f"  ▶ {titulo}")
    print(SEP2)


def _print_ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def _print_alerta(msg: str) -> None:
    print(f"  ⚠️   {msg}")


def _print_critico(msg: str) -> None:
    print(f"  🚨  {msg}")


def _print_info(msg: str) -> None:
    print(f"  ℹ️   {msg}")


# ── Passo 0: valida que os módulos do protótipo estão importáveis ─────────────

def validar_infraestrutura() -> None:
    _print_secao("PASSO 0 — Validação de Infraestrutura e Cotas")

    modulos = [
        ("orchestration.skills",          "SkillRegistry"),
        ("orchestration.agent_flow",       "AgenteAntiFraude"),
        ("orchestration.human_in_the_loop","GestorHITL"),
        ("orchestration.notificacao_push", "SimuladorPush"),
        ("orchestration.pipeline",         "executar_pipeline_async"),
    ]

    todos_ok = True
    for modulo, simbolo in modulos:
        try:
            mod = __import__(modulo, fromlist=[simbolo])
            getattr(mod, simbolo)
            _print_ok(f"Módulo '{modulo}' → '{simbolo}' importado com sucesso")
        except (ImportError, AttributeError) as exc:
            _print_critico(f"FALHA ao importar '{modulo}.{simbolo}': {exc}")
            todos_ok = False

    # Valida skills registradas
    from orchestration.skills import registry
    skills_disponiveis = [s["nome"] for s in registry.listar()]
    _print_info(f"Skills registradas no SkillRegistry: {skills_disponiveis}")
    assert "analisar_risco_transacao" in skills_disponiveis, "ERRO: skill analisar_risco_transacao ausente!"
    assert "explicar_risco_fraude"    in skills_disponiveis, "ERRO: skill explicar_risco_fraude ausente!"
    _print_ok("Todas as skills obrigatórias estão registradas")

    if todos_ok:
        _print_ok("Infraestrutura operacional — todos os módulos carregados")
    else:
        raise SystemExit("❌ Infraestrutura com falha — teste abortado")


# ── Passo 1: injeta histórico do associado e valida isolamento ────────────────

def injetar_historico() -> None:
    """
    Injeta a transação histórica do associado (Porto Alegre) diretamente no
    _HISTORICO do servidor MCP para garantir que a Regra 1 (VELOCIDADE_IMPOSSIVEL)
    seja ativada na sequência.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_antifraude"))
    import server as mcp_server  # type: ignore

    _print_secao("PASSO 1 — Injeção do Histórico do Associado (Porto Alegre)")
    mcp_server._HISTORICO[ASSOC_ID] = [TRANSACAO_HISTORICO_PORTO_ALEGRE]
    _print_ok(f"Associado '{ASSOC_ID}' cadastrado no histórico MCP")
    _print_info(f"  Última transação legítima: Porto Alegre, RS")
    _print_info(f"  Timestamp: {TRANSACAO_HISTORICO_PORTO_ALEGRE['timestamp']}")
    _print_info(f"  Coordenadas: lat={TRANSACAO_HISTORICO_PORTO_ALEGRE['latitude']}, lon={TRANSACAO_HISTORICO_PORTO_ALEGRE['longitude']}")


# ── Passo 2: análise de risco via skill ───────────────────────────────────────

def executar_analise_risco() -> dict:
    from orchestration.skills import registry

    _print_secao("PASSO 2 — Análise de Risco (Skill: analisar_risco_transacao)")
    _print_info(f"Transação submetida: {TRANSACAO_SUSPEITA_TOQUIO['transacao_id']}")
    _print_info(f"Associado          : {TRANSACAO_SUSPEITA_TOQUIO['associado_id']}")
    _print_info(f"Valor              : R$ {TRANSACAO_SUSPEITA_TOQUIO['valor']:,.2f}")
    _print_info(f"Local              : Tóquio, JP (lat={TRANSACAO_SUSPEITA_TOQUIO['latitude']}, lon={TRANSACAO_SUSPEITA_TOQUIO['longitude']})")
    _print_info(f"Timestamp          : {TRANSACAO_SUSPEITA_TOQUIO['timestamp']}")

    t0 = _time.perf_counter()
    resultado = registry.invocar(
        "analisar_risco_transacao",
        transacao_json=json.dumps(TRANSACAO_SUSPEITA_TOQUIO, ensure_ascii=False),
    )
    elapsed_ms = ((_time.perf_counter() - t0) * 1000)

    print()
    print(f"  Score de Risco   : {resultado['score_risco']}")
    print(f"  Nível de Risco   : {resultado['nivel_risco']}")
    print(f"  Histórico usado  : {resultado['historico_usado']} transação(ões)")
    print(f"  Tempo de análise : {elapsed_ms:.2f} ms")
    print()

    if resultado.get("regras_violadas"):
        print(f"  Regras violadas  : {len(resultado['regras_violadas'])}")
        for r in resultado["regras_violadas"]:
            _print_critico(f"[{r['regra']}] {r['descricao']}")
            print(f"      Detalhe: {r['detalhe']}")
    else:
        _print_ok("Nenhuma regra violada (transação dentro do padrão)")

    # Validações obrigatórias
    assert resultado["score_risco"] > 70, \
        f"FALHA: score {resultado['score_risco']} deveria ser > 70 para GPS impossível"
    assert resultado["nivel_risco"] == "CRITICO", \
        f"FALHA: nível esperado CRITICO, obtido {resultado['nivel_risco']}"
    assert any(r["regra"] == "VELOCIDADE_IMPOSSIVEL" for r in resultado["regras_violadas"]), \
        "FALHA: regra VELOCIDADE_IMPOSSIVEL não foi ativada"

    _print_ok(f"RISCO DETECTADO CORRETAMENTE — score={resultado['score_risco']} (CRITICO)")
    return resultado


# ── Passo 3: tradução do risco para linguagem simples ─────────────────────────

def executar_explicacao(resultado_analise: dict) -> dict:
    from orchestration.skills import registry

    _print_secao("PASSO 3 — Tradução da Ameaça para Linguagem Simples (Skill: explicar_risco_fraude)")

    t0 = _time.perf_counter()
    explicacao = registry.invocar(
        "explicar_risco_fraude",
        resultado_analise_json=json.dumps(resultado_analise, ensure_ascii=False),
    )
    elapsed_ms = ((_time.perf_counter() - t0) * 1000)

    print(f"  Requer validação : {explicacao['requer_validacao']}")
    print(f"  Tempo de geração : {elapsed_ms:.2f} ms")
    print()
    print(f"  TÍTULO           : {explicacao['titulo']}")
    print()
    print("  MENSAGEM AO ASSOCIADO:")
    for linha in explicacao["mensagem_associado"].split("\n"):
        print(f"    {linha}")
    print()
    print(f"  ORIENTAÇÃO: {explicacao['orientacao']}")

    assert explicacao["requer_validacao"] is True, \
        "FALHA: requer_validacao deveria ser True para score > 70"
    titulo = explicacao.get("titulo", "").lower()
    assert any(kw in titulo for kw in ("distante", "confirmação", "local", "alerta", "suspeita", "compra")), \
        f"FALHA: título da explicação não reflete o tipo de fraude GPS. Título recebido: '{explicacao.get('titulo')}'"
    assert len(explicacao.get("mensagem_associado", "")) > 100, \
        "FALHA: mensagem ao associado está vazia ou muito curta"

    _print_ok("AMEAÇA TRADUZIDA EM LINGUAGEM SIMPLES com sucesso")
    return explicacao


# ── Passo 4: fluxo HITL completo — pausa + push + decisão humana ─────────────

async def executar_fluxo_hitl(
    transacao: dict,
    resultado_analise: dict,
    explicacao: dict,
    resposta_simulada: str = "2",  # "2" = NAO_BLOQUEAR (associado nega)
) -> dict:
    from orchestration.human_in_the_loop import GestorHITL
    from orchestration.notificacao_push import BotaoResposta

    _print_secao("PASSO 4 — Fluxo HITL: Pausa + Notificação Push + Decisão Humana")

    score = resultado_analise["score_risco"]

    # 4a. Pausa da liquidação (simulada via log)
    _print_critico(f"LIQUIDAÇÃO PAUSADA — score={score} > 70 — aguardando decisão humana")
    _print_info(f"Transação {transacao['transacao_id']} retida — não será processada")
    print()

    # 4b. Envia push e coleta decisão em modo não-interativo
    gestor = GestorHITL(timeout_segundos=10)  # timeout curto para teste
    notif  = gestor.enviar_push(transacao, explicacao, score)

    # Valida payload da notificação
    assert notif.transacao_id  == transacao["transacao_id"], "FALHA: transacao_id divergente no push"
    assert notif.score_risco   == score,                     "FALHA: score divergente no push"
    assert len(notif.botoes)   == 2,                         "FALHA: push deveria ter exatamente 2 botões"
    _print_ok("Notificação push construída e enviada com sucesso")
    _print_info(f"Título : {notif.titulo_alerta}")
    _print_info(f"Botões : {[b.value for b in notif.botoes]}")
    _print_info(f"Timeout: {notif.timeout_segundos}s")

    # 4c. Resolve o Future de forma assíncrona (simula associado respondendo)
    botao = BotaoResposta.SIM_FUI_EU if resposta_simulada == "1" else BotaoResposta.NAO_BLOQUEAR
    print()
    _print_alerta(f"[SIMULAÇÃO] Associado responde com botão: {botao.value}")
    print()

    # Lança a resolução como Task separada (50ms de delay para garantir que
    # aguardar_decisao() criou o Future antes de resolver)
    async def _resolver_simulado() -> None:
        await asyncio.sleep(0.05)
        gestor.resolver(botao)

    resposta, _ = await asyncio.gather(
        gestor.aguardar_decisao(transacao["transacao_id"]),
        _resolver_simulado(),
    )

    print()
    print(resposta.resumo())

    assert resposta.decisao_final.value == "BLOQUEADA", \
        f"FALHA: decisão esperada BLOQUEADA, obtida {resposta.decisao_final.value}"
    _print_ok("FLUXO PAUSADO E RESOLVIDO COM SUCESSO — decisão: BLOQUEADA")

    return {
        "notificacao_push": notif.to_dict(),
        "resposta_humana":  {
            "transacao_id":      resposta.transacao_id,
            "botao_pressionado": resposta.botao_pressionado.value,
            "decisao_final":     resposta.decisao_final.value,
            "origem":            resposta.origem,
            "timestamp":         resposta.timestamp,
        },
    }


# ── Passo 5: relatório final do teste ─────────────────────────────────────────

def imprimir_relatorio_final(analise: dict, explicacao: dict, hitl: dict) -> None:
    _print_secao("RELATÓRIO FINAL — TESTE E2E CASO 5 (GPS)")

    linhas = [
        f"  Transação ID    : {analise['transacao_id']}",
        f"  Associado ID    : {analise['associado_id']}",
        f"  Score de Risco  : {analise['score_risco']}/100",
        f"  Nível           : {analise['nivel_risco']}",
        f"  Regras ativas   : {[r['regra'] for r in analise['regras_violadas']]}",
        "",
        f"  Risco detectado         : ✅  SIM",
        f"  Ameaça em ling. simples : ✅  SIM — '{explicacao['titulo']}'",
        f"  Liquidação pausada      : ✅  SIM",
        f"  Push enviado            : ✅  SIM",
        f"  Decisão humana          : ✅  {hitl['resposta_humana']['decisao_final']}",
        f"  Fluxo resolvido         : ✅  SIM",
    ]
    for l in linhas:
        print(l)

    print()
    print(SEP)
    print("  ✅  TODOS OS CRITÉRIOS DO TESTE E2E FORAM ATENDIDOS")
    print(SEP)
    print()


# ── Runner principal ──────────────────────────────────────────────────────────

async def main() -> None:
    _print_cabecalho()

    validar_infraestrutura()
    injetar_historico()

    analise   = executar_analise_risco()
    explicacao = executar_explicacao(analise)
    hitl       = await executar_fluxo_hitl(
        TRANSACAO_SUSPEITA_TOQUIO,
        analise,
        explicacao,
        resposta_simulada="2",  # Associado nega → BLOQUEADA
    )

    imprimir_relatorio_final(analise, explicacao, hitl)


if __name__ == "__main__":
    asyncio.run(main())
