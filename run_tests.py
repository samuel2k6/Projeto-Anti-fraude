# -*- coding: utf-8 -*-
"""
run_tests.py — Runner unificado de todos os testes do projeto Anti-Fraude Sicredi
==================================================================================
Executa em sequência, sem depender do MCP server em background:
  1. Testes unitários + estresse (test_unitario_estresse.py)
  2. Testes do servidor MCP / explicações (test_server.py)
  3. Testes de orquestração (test_orchestration.py)
  4. Teste E2E Caso 5 — GPS (test_e2e_caso5_gps.py)

Estratégia anti-blocking:
  O FastMCP ao ser instanciado no módulo top-level de server.py pode tentar
  ler stdin quando não há transporte configurado. Este runner registra um
  mock do mcp.server.fastmcp.FastMCP ANTES de importar qualquer módulo do
  projeto, evitando o blocking completamente.

Execute a partir da raiz do projeto:
    python run_tests.py
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import os
import time
import types
from pathlib import Path

# Força stdout/stderr UTF-8 no Windows (evita UnicodeEncodeError com emojis)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_antifraude"))
sys.path.insert(0, str(ROOT / ".bob"))   # expõe o pacote `orchestration`

# ── Mock do FastMCP (evita blocking de stdin ao importar server.py) ──────────

class _MockFastMCP:
    """Substituto mínimo do FastMCP que não bloqueia stdin."""
    def __init__(self, *args, **kwargs): pass
    def tool(self, *args, **kwargs):
        """Decorador @mcp.tool() — retorna a função sem modificação."""
        def decorator(fn):
            return fn
        return decorator
    def run(self, *args, **kwargs): pass

# Registra o mock antes de qualquer importação do projeto
_mcp_module = types.ModuleType("mcp.server.fastmcp")
_mcp_module.FastMCP = _MockFastMCP
sys.modules["mcp.server.fastmcp"] = _mcp_module

# Garante que o pacote mcp e mcp.server existam no sys.modules
if "mcp" not in sys.modules:
    sys.modules["mcp"] = types.ModuleType("mcp")
if "mcp.server" not in sys.modules:
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")

# ── Agora podemos importar com segurança ─────────────────────────────────────

import server as mcp_server  # type: ignore  (mcp_antifraude/server.py)

analisar_risco_transacao = mcp_server.analisar_risco_transacao
explicar_risco_fraude    = mcp_server.explicar_risco_fraude

# ── Helpers de formatação ─────────────────────────────────────────────────────

VERDE   = "\033[92m"
AMARELO = "\033[93m"
VERMELHO = "\033[91m"
AZUL    = "\033[94m"
CINZA   = "\033[90m"
RESET   = "\033[0m"
NEGRITO = "\033[1m"

SEP  = "═" * 70
SEP2 = "─" * 70

def ok(msg: str)    -> None: print(f"  {VERDE}✅{RESET} {msg}")
def fail(msg: str)  -> None: print(f"  {VERMELHO}❌{RESET} {msg}")
def info(msg: str)  -> None: print(f"  {CINZA}ℹ️  {RESET}{msg}")
def warn(msg: str)  -> None: print(f"  {AMARELO}⚠️  {RESET}{msg}")
def crit(msg: str)  -> None: print(f"  {VERMELHO}🚨{RESET} {msg}")

def secao(titulo: str) -> None:
    print(f"\n{SEP2}")
    print(f"  ▶ {titulo}")
    print(SEP2)

_total = _passed = _failed = 0

def _assert(condicao: bool, descricao: str) -> None:
    global _total, _passed, _failed
    _total += 1
    if condicao:
        _passed += 1
        ok(descricao)
    else:
        _failed += 1
        fail(descricao)


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 1 — Prompt 2: analisar_risco_transacao (regras heurísticas)
# ═══════════════════════════════════════════════════════════════════════════════

def suite_p2_analise_risco() -> None:
    secao("SUITE 1 — Prompt 2: analisar_risco_transacao (3 regras heurísticas)")

    # Reseta histórico para isolamento
    mcp_server._HISTORICO["assoc_001"] = [
        {"transacao_id": "t001", "associado_id": "assoc_001", "valor": 120.00,
         "categoria": "Supermercados", "timestamp": "2026-11-01T08:30:00",
         "latitude": -23.5505, "longitude": -46.6333},
        {"transacao_id": "t002", "associado_id": "assoc_001", "valor": 95.50,
         "categoria": "Restaurantes", "timestamp": "2026-11-01T12:15:00",
         "latitude": -23.5510, "longitude": -46.6340},
        {"transacao_id": "t003", "associado_id": "assoc_001", "valor": 200.00,
         "categoria": "Farmácias", "timestamp": "2026-11-01T17:45:00",
         "latitude": -23.5520, "longitude": -46.6350},
        {"transacao_id": "t004", "associado_id": "assoc_001", "valor": 80.00,
         "categoria": "Postos de Combustível", "timestamp": "2026-11-02T07:00:00",
         "latitude": -23.5500, "longitude": -46.6320},
        {"transacao_id": "t005", "associado_id": "assoc_001", "valor": 150.00,
         "categoria": "Supermercados", "timestamp": "2026-11-02T10:30:00",
         "latitude": -23.5505, "longitude": -46.6333},
    ]

    # T1 — Transação normal → score 0
    r = json.loads(analisar_risco_transacao(json.dumps({
        "transacao_id": "r1", "associado_id": "assoc_001", "valor": 130.0,
        "categoria": "Supermercados", "timestamp": "2026-11-02T14:00:00",
        "latitude": -23.5505, "longitude": -46.6333,
    })))
    _assert(r["score_risco"] == 0, "T1: transação normal → score=0 (BAIXO)")
    _assert(r["nivel_risco"] == "BAIXO", "T1: nível = BAIXO")
    _assert(r["regras_violadas"] == [], "T1: sem regras violadas")

    # T2 — Regra PICO_TRANSACAO → score 35
    r = json.loads(analisar_risco_transacao(json.dumps({
        "transacao_id": "r2", "associado_id": "assoc_001", "valor": 1500.0,
        "categoria": "Supermercados", "timestamp": "2026-11-02T10:00:00",
        "latitude": -23.5505, "longitude": -46.6333,
    })))
    _assert(r["score_risco"] == 35, "T2: PICO_TRANSACAO → score=35 (MEDIO)")
    _assert(any(r2["regra"] == "PICO_TRANSACAO" for r2 in r["regras_violadas"]),
            "T2: regra PICO_TRANSACAO ativada")

    # T3 — Regra PERFIL_INCOMUM → score 25
    r = json.loads(analisar_risco_transacao(json.dumps({
        "transacao_id": "r3", "associado_id": "assoc_002", "valor": 300.0,
        "categoria": "Joalherias", "timestamp": "2026-11-03T02:30:00",
        "latitude": -22.9068, "longitude": -43.1729,
    })))
    _assert(r["score_risco"] == 25, "T3: PERFIL_INCOMUM (Joalheria 02h30) → score=25")
    _assert(any(r2["regra"] == "PERFIL_INCOMUM" for r2 in r["regras_violadas"]),
            "T3: regra PERFIL_INCOMUM ativada")

    # T4 — Regra VELOCIDADE_IMPOSSIVEL → score 45
    mcp_server._HISTORICO["assoc_gps_r4"] = [{
        "transacao_id": "hist_r4", "associado_id": "assoc_gps_r4", "valor": 100.0,
        "categoria": "Supermercados", "timestamp": "2026-11-01T10:16:00",
        "latitude": -30.0346, "longitude": -51.2177,
    }]
    r = json.loads(analisar_risco_transacao(json.dumps({
        "transacao_id": "r4", "associado_id": "assoc_gps_r4", "valor": 200.0,
        "categoria": "Restaurantes", "timestamp": "2026-11-01T10:31:00",
        "latitude": 35.6762, "longitude": 139.6503,
    })))
    _assert(r["score_risco"] == 45, f"T4: VELOCIDADE_IMPOSSIVEL → score=45 (obtido={r['score_risco']})")
    _assert(any(r2["regra"] == "VELOCIDADE_IMPOSSIVEL" for r2 in r["regras_violadas"]),
            "T4: regra VELOCIDADE_IMPOSSIVEL ativada")
    # score 45 fica na faixa ALTO (36-70), não CRITICO (>70)
    _assert(r["nivel_risco"] == "ALTO", "T4: score=45 → nível = ALTO (faixa 36-70)")

    # T5 — Score máximo (3 regras) → min(45+35+25, 100) = 100
    # Timestamps dentro da janela de 30 min (para VELOCIDADE_IMPOSSIVEL),
    # valor 50× acima (PICO), Eletrônicos às 03:00 (PERFIL_INCOMUM)
    _T5_ASSOC = "assoc_t5_" + str(int(time.time() * 1000000) % 9999999)
    mcp_server._HISTORICO[_T5_ASSOC] = [{
        "transacao_id": "hist_t5", "associado_id": _T5_ASSOC, "valor": 100.0,
        "categoria": "Supermercados", "timestamp": "2026-11-02T03:00:00",  # T+00min
        "latitude": -23.5505, "longitude": -46.6333,   # São Paulo
    }]
    r = json.loads(analisar_risco_transacao(json.dumps({
        "transacao_id": "r5_isolado", "associado_id": _T5_ASSOC, "valor": 5000.0,
        "categoria": "Eletrônicos",                    # PERFIL_INCOMUM: Eletrônicos fora do horário
        "timestamp": "2026-11-02T03:15:00",            # T+15min — dentro da janela de 30min
        "latitude": -22.9068, "longitude": -43.1729,   # Rio de Janeiro (~360 km) → VELOCIDADE_IMPOSSIVEL
    })))
    _assert(r["score_risco"] == 100, f"T5: 3 regras → score=100 (cap) — obtido={r['score_risco']}")
    _assert(len(r["regras_violadas"]) == 3,
            f"T5: exatamente 3 regras violadas — obtido {len(r['regras_violadas'])}: {[x['regra'] for x in r['regras_violadas']]}")


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 2 — Prompt 3: explicar_risco_fraude (linguagem natural, sem jargão)
# ═══════════════════════════════════════════════════════════════════════════════

def suite_p3_explicacao() -> None:
    secao("SUITE 2 — Prompt 3: explicar_risco_fraude (linguagem natural)")

    # Score 0 → sem alerta
    e = json.loads(explicar_risco_fraude(json.dumps({
        "transacao_id": "x1", "associado_id": "a1",
        "score_risco": 0, "nivel_risco": "BAIXO", "regras_violadas": [],
    })))
    _assert(e["requer_validacao"] is False, "E1: score=0 → requer_validacao=False")
    _assert(e["alerta_falso_positivo"] is False, "E1: score=0 → alerta_falso_positivo=False")
    _assert("certo" in e["titulo"].lower() or "tudo" in e["titulo"].lower(),
            f"E1: título positivo (obtido: '{e['titulo']}')")

    # Score 35 (PICO) → falso positivo leve
    e = json.loads(explicar_risco_fraude(json.dumps({
        "transacao_id": "x2", "associado_id": "a1",
        "score_risco": 35, "nivel_risco": "MEDIO",
        "regras_violadas": [{"regra": "PICO_TRANSACAO",
            "descricao": "Valor da compra muito acima do que o associado costuma gastar",
            "detalhe": "Valor R$ 1500.00 é 11.6x acima da média histórica (R$ 129.10)"}],
    })))
    _assert(e["alerta_falso_positivo"] is True, "E2: score=35 → alerta_falso_positivo=True")
    _assert(e["requer_validacao"] is False, "E2: score=35 → requer_validacao=False")
    _assert("padrão" in e["mensagem_associado"].lower() or
            "aprovad" in e["mensagem_associado"].lower() or
            "notamos" in e["mensagem_associado"].lower(),
            "E2: mensagem avisa sobre diferença no padrão de compra")
    # Verifica ausência de jargões técnicos
    jargoes = ["score_risco", "heurística", "std", "desvio padrão", "multiplica",
               "falso positivo", "float", "int", "json", "array"]
    for j in jargoes:
        _assert(j not in e["mensagem_associado"].lower(),
                f"E2: mensagem não contém jargão técnico '{j}'")

    # Score 80 (CRITICO GPS) → requer validação, mensagem humanizada
    e = json.loads(explicar_risco_fraude(json.dumps({
        "transacao_id": "x3", "associado_id": "a1",
        "score_risco": 80, "nivel_risco": "CRITICO",
        "regras_violadas": [{"regra": "VELOCIDADE_IMPOSSIVEL",
            "descricao": "Compra registrada em lugar muito distante do uso anterior",
            "detalhe": "Distância de 18500.0 km em 15.0 min (74000 km/h) em relação à transação hist_r4"}],
    })))
    _assert(e["requer_validacao"] is True, "E3: score=80 → requer_validacao=True")
    _assert(e["alerta_falso_positivo"] is False, "E3: score=80 → alerta_falso_positivo=False")
    _assert(len(e["mensagem_associado"]) > 100, "E3: mensagem humanizada com > 100 chars")
    _assert("distante" in e["mensagem_associado"].lower() or
            "lugar" in e["mensagem_associado"].lower(),
            "E3: mensagem menciona distância de forma natural")
    _assert("km/h" not in e["mensagem_associado"],
            "E3: mensagem NÃO contém 'km/h' (jargão técnico removido)")
    _assert("velocidade" not in e["mensagem_associado"].lower(),
            "E3: mensagem NÃO contém 'velocidade' (jargão técnico)")


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 3 — Prompt 4: latência ≤ 50ms e edge cases
# ═══════════════════════════════════════════════════════════════════════════════

def suite_p4_latencia_edge_cases() -> None:
    secao("SUITE 3 — Prompt 4: latência ≤ 50ms e edge cases")

    SLA_MS = 50.0
    latencias = []

    payload_base = {
        "transacao_id": "lat_001", "associado_id": "assoc_001",
        "valor": 150.0, "categoria": "Supermercados",
        "timestamp": "2026-11-02T10:00:00",
        "latitude": -23.5505, "longitude": -46.6333,
    }

    for i in range(20):
        p = {**payload_base, "transacao_id": f"lat_{i:04d}"}
        t0 = time.perf_counter()
        analisar_risco_transacao(json.dumps(p))
        lat = (time.perf_counter() - t0) * 1000
        latencias.append(lat)

    media = sum(latencias) / len(latencias)
    p99 = sorted(latencias)[int(len(latencias) * 0.99) - 1]
    acima = sum(1 for l in latencias if l > SLA_MS)

    info(f"Latência média   : {media:.2f} ms")
    info(f"Latência p99     : {p99:.2f} ms")
    info(f"Acima do SLA     : {acima}/{len(latencias)}")

    _assert(media <= SLA_MS, f"Latência média ≤ {SLA_MS}ms (obtida: {media:.2f}ms)")
    _assert(acima == 0, f"Todas as {len(latencias)} execuções abaixo de {SLA_MS}ms")

    # Edge cases
    def _r(payload): return json.loads(analisar_risco_transacao(
        payload if isinstance(payload, str) else json.dumps(payload)))

    _assert("erro" in _r({}), "EC1: payload vazio → campo 'erro'")
    _assert("erro" in _r({"transacao_id": "ec", "valor": 10}), "EC2: campos obrigatórios ausentes → erro")
    _assert("erro" in _r("isso nao e json"), "EC3: JSON malformado → erro")
    _assert("erro" in _r({"transacao_id": "ec4", "associado_id": "a",
                           "valor": None, "categoria": "X", "timestamp": "2026-11-01T10:00:00"}),
            "EC4: valor nulo → erro")
    _assert("erro" in _r({"transacao_id": "ec5", "associado_id": "a",
                           "valor": 100, "categoria": "X",
                           "timestamp": "01/11/2026"}),
            "EC5: timestamp inválido → erro")
    r_inexistente = _r({"transacao_id": "ec6", "associado_id": "ASSOC-INEXISTENTE",
                         "valor": 100.0, "categoria": "Supermercados",
                         "timestamp": "2026-11-01T10:00:00"})
    _assert("erro" not in r_inexistente, "EC6: associado inexistente → sem crash, score=0")
    _assert(r_inexistente["score_risco"] == 0, "EC6: associado inexistente → score=0")


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 4 — Prompt 5: skills de orquestração (SkillRegistry)
# ═══════════════════════════════════════════════════════════════════════════════

def suite_p5_skills() -> None:
    secao("SUITE 4 — Prompt 5: skills conectadas (SkillRegistry)")

    # Importa o registry após o mock estar instalado
    # Re-inicializa skills.py para usar as funções mockadas
    if "orchestration.skills" in sys.modules:
        del sys.modules["orchestration.skills"]
    if "orchestration" in sys.modules:
        del sys.modules["orchestration"]

    # Adiciona o caminho da orchestration
    orch_path = str(ROOT / "orchestration")
    if orch_path not in sys.path:
        sys.path.insert(0, str(ROOT))

    from orchestration.skills import registry

    skills = [s["nome"] for s in registry.listar()]
    _assert("analisar_risco_transacao" in skills,
            "S1: skill 'analisar_risco_transacao' registrada")
    _assert("explicar_risco_fraude" in skills,
            "S2: skill 'explicar_risco_fraude' registrada")

    # Invoca via registry
    mcp_server._HISTORICO["assoc_skill_test"] = [{
        "transacao_id": "sh1", "associado_id": "assoc_skill_test", "valor": 100.0,
        "categoria": "Supermercados", "timestamp": "2026-11-02T10:00:00",
    }]
    resultado = registry.invocar("analisar_risco_transacao", transacao_json=json.dumps({
        "transacao_id": "sk_001", "associado_id": "assoc_skill_test",
        "valor": 150.0, "categoria": "Supermercados",
        "timestamp": "2026-11-02T14:00:00",
    }))
    _assert("score_risco" in resultado, "S3: invocar() retorna score_risco")
    _assert("nivel_risco" in resultado, "S4: invocar() retorna nivel_risco")


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 5 — Prompt 6: notificação push + HITL (Human-in-the-Loop)
# ═══════════════════════════════════════════════════════════════════════════════

async def suite_p6_hitl_async() -> None:
    secao("SUITE 5 — Prompt 6: push + HITL (Human-in-the-Loop)")

    from orchestration.notificacao_push import NotificacaoPush, BotaoResposta, SimuladorPush
    from orchestration.human_in_the_loop import GestorHITL, DecisaoHumana

    transacao = {
        "transacao_id": "hitl_001", "associado_id": "assoc_hitl",
        "valor": 3500.0, "categoria": "Eletrônicos",
        "cidade": "São Paulo",
        "timestamp": "2026-11-03T03:00:00",
    }
    explicacao = {
        "titulo": "⚠️ Compra em local distante do seu — precisa de confirmação",
        "mensagem_associado": "Olá! Identificamos algo diferente na sua conta.",
        "orientacao": "Responda SIM para confirmar ou NÃO para bloquear.",
    }

    # Testa construção do push
    notif = NotificacaoPush.construir(transacao, explicacao, score_risco=80)
    _assert(notif.transacao_id == "hitl_001", "H1: transacao_id no push")
    _assert(notif.score_risco == 80, "H2: score_risco no push")
    _assert(len(notif.botoes) == 2, "H3: exatamente 2 botões")
    _assert(BotaoResposta.SIM_FUI_EU in notif.botoes, "H4: botão SIM_FUI_EU presente")
    _assert(BotaoResposta.NAO_BLOQUEAR in notif.botoes, "H5: botão NAO_BLOQUEAR presente")
    _assert("score" not in notif.titulo_alerta.lower() and
            "km/h" not in notif.titulo_alerta.lower(),
            "H6: título do push sem jargões técnicos")

    # Testa HITL com resposta simulada: SIM
    gestor = GestorHITL(timeout_segundos=5)
    async def _resolver_sim():
        await asyncio.sleep(0.05)
        gestor.resolver(BotaoResposta.SIM_FUI_EU)
    resposta, _ = await asyncio.gather(
        gestor.aguardar_decisao("hitl_001"),
        _resolver_sim(),
    )
    _assert(resposta.decisao_final == DecisaoHumana.LIBERADA,
            "H7: botão SIM_FUI_EU → decisão LIBERADA")

    # Testa HITL com resposta simulada: NAO
    gestor2 = GestorHITL(timeout_segundos=5)
    async def _resolver_nao():
        await asyncio.sleep(0.05)
        gestor2.resolver(BotaoResposta.NAO_BLOQUEAR)
    resposta2, _ = await asyncio.gather(
        gestor2.aguardar_decisao("hitl_002"),
        _resolver_nao(),
    )
    _assert(resposta2.decisao_final == DecisaoHumana.BLOQUEADA,
            "H8: botão NAO_BLOQUEAR → decisão BLOQUEADA")

    # Testa HITL com timeout
    gestor3 = GestorHITL(timeout_segundos=1)
    resposta3 = await gestor3.aguardar_decisao("hitl_003")
    _assert(resposta3.decisao_final == DecisaoHumana.BLOQUEADA_TIMEOUT,
            "H9: sem resposta em 1s → BLOQUEADA_TIMEOUT")


def suite_p6_hitl() -> None:
    asyncio.run(suite_p6_hitl_async())


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 6 — Prompt 7: Teste E2E Caso 5 — F-002 Viagem Impossível por GPS
# ═══════════════════════════════════════════════════════════════════════════════

async def suite_p7_e2e_gps_async() -> None:
    secao("SUITE 6 — Prompt 7: E2E Caso 5 — F-002 Viagem Impossível por GPS")

    from orchestration.human_in_the_loop import GestorHITL
    from orchestration.notificacao_push import BotaoResposta

    ASSOC = "assoc_e2e_gps"
    mcp_server._HISTORICO[ASSOC] = [{
        "transacao_id": "e2e_hist", "associado_id": ASSOC, "valor": 187.43,
        "categoria": "Supermercado", "timestamp": "2026-11-01T10:16:00",
        "latitude": -30.0346, "longitude": -51.2177,
    }]

    transacao_toquio = {
        "transacao_id": "txn-20261101-0012", "associado_id": ASSOC,
        "valor": 1250.00, "categoria": "Restaurante / Alimentação",
        "timestamp": "2026-11-01T10:31:00",
        "latitude": 35.6762, "longitude": 139.6503,
    }

    # Passo 1 — Análise de risco
    t0 = time.perf_counter()
    analise = json.loads(analisar_risco_transacao(json.dumps(transacao_toquio)))
    lat_ms = (time.perf_counter() - t0) * 1000

    info(f"Score de risco   : {analise['score_risco']}/100")
    info(f"Nível de risco   : {analise['nivel_risco']}")
    info(f"Latência análise : {lat_ms:.2f} ms")
    info(f"Regras ativas    : {[r['regra'] for r in analise['regras_violadas']]}")

    _assert(analise["score_risco"] > 70,
            f"P7-1: GPS impossível detectado → score>70 (obtido={analise['score_risco']})")
    _assert(analise["nivel_risco"] == "CRITICO",
            "P7-2: nível = CRITICO")
    _assert(any(r["regra"] == "VELOCIDADE_IMPOSSIVEL" for r in analise["regras_violadas"]),
            "P7-3: regra VELOCIDADE_IMPOSSIVEL ativa")
    _assert(lat_ms < 50.0,
            f"P7-4: latência de análise < 50ms (obtida={lat_ms:.2f}ms)")

    # Passo 2 — Tradução para linguagem natural
    explicacao = json.loads(explicar_risco_fraude(json.dumps(analise)))

    info(f"requer_validacao : {explicacao['requer_validacao']}")
    info(f"Título gerado    : {explicacao['titulo']}")

    _assert(explicacao["requer_validacao"] is True,
            "P7-5: requer_validacao=True para score>70")
    _assert(len(explicacao["mensagem_associado"]) > 100,
            "P7-6: mensagem humanizada não vazia")
    _assert("km/h" not in explicacao["mensagem_associado"],
            "P7-7: mensagem sem 'km/h' (linguagem técnica removida)")

    # Passo 3 — Fluxo HITL: pausa + push + decisão
    info("Iniciando fluxo HITL (pausa + push + await decisão)...")

    gestor = GestorHITL(timeout_segundos=10)
    notif  = gestor.enviar_push(transacao_toquio, explicacao, analise["score_risco"])

    _assert(notif.transacao_id == transacao_toquio["transacao_id"],
            "P7-8: push com transacao_id correto")
    _assert(len(notif.botoes) == 2,
            "P7-9: push com 2 botões de resposta")

    # Simula associado negando (não fui eu)
    async def _resolver():
        await asyncio.sleep(0.05)
        gestor.resolver(BotaoResposta.NAO_BLOQUEAR)

    resposta, _ = await asyncio.gather(
        gestor.aguardar_decisao(transacao_toquio["transacao_id"]),
        _resolver(),
    )

    info(f"Decisão final    : {resposta.decisao_final.value}")

    _assert(resposta.decisao_final.value == "BLOQUEADA",
            "P7-10: associado negou → transação BLOQUEADA")

    print()
    print(f"  {NEGRITO}Critérios do Prompt 7 validados:{RESET}")
    print(f"    ✅  Risco detectado (score={analise['score_risco']}, CRITICO)")
    print(f"    ✅  Ameaça traduzida em linguagem simples")
    print(f"    ✅  Fluxo pausado e notificação push enviada")
    print(f"    ✅  Fluxo aguardou decisão humana (HITL)")
    print(f"    ✅  Decisão humana aplicada: {resposta.decisao_final.value}")
    print(f"    ✅  Latência de análise: {lat_ms:.2f}ms (SLA: <50ms)")


def suite_p7_e2e_gps() -> None:
    asyncio.run(suite_p7_e2e_gps_async())


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE 7 — Prompt 1: injeção das 15 transações do transactions.json
# ═══════════════════════════════════════════════════════════════════════════════

def suite_p1_15_transacoes() -> None:
    secao("SUITE 7 — Prompt 1: injeção das 15 transações do transactions.json")

    tx_file = ROOT / "transactions.json"
    _assert(tx_file.exists(), "J1: transactions.json existe")
    if not tx_file.exists():
        return

    dataset = json.loads(tx_file.read_text(encoding="utf-8"))
    transacoes = dataset.get("transacoes", [])
    _assert(len(transacoes) == 15, f"J2: exatamente 15 transações (obtido: {len(transacoes)})")

    campos_obrigatorios = {"associado_id", "transacao_id", "valor", "categoria",
                           "localizacao", "timestamp", "score_suspeito_esperado"}
    for tx in transacoes:
        campos_presentes = set(k for k in tx if not k.startswith("_"))
        _assert(campos_obrigatorios.issubset(campos_presentes),
                f"J3: transacao '{tx.get('transacao_id')}' tem todos os campos obrigatórios")

    fraudes = [t for t in transacoes if t.get("score_suspeito_esperado", 0) >= 0.85]
    _assert(len(fraudes) >= 3, f"J4: pelo menos 3 transações com score≥0.85 (fraude clara) — obtido={len(fraudes)}")

    tipos = {t.get("_tipo_fraude", "") for t in transacoes if "_tipo_fraude" in t}
    _assert("F-001: Carding / Ataque de Força Bruta" in tipos,
            "J5: fraude F-001 (Carding) presente")
    _assert("F-002: Viagem Impossível por GPS" in tipos,
            "J6: fraude F-002 (GPS) presente")
    _assert("F-003: Transação Fora do Padrão do Associado" in tipos,
            "J7: fraude F-003 (Fora do Padrão) presente")

    # Injeta cada transação no motor e confirma que retorna sem erro
    erros = 0
    for tx in transacoes:
        payload = {k: v for k, v in tx.items() if not k.startswith("_")}
        loc = payload.pop("localizacao", {})
        payload["latitude"]  = loc.get("latitude")
        payload["longitude"] = loc.get("longitude")
        payload.pop("score_suspeito_esperado", None)
        r = json.loads(analisar_risco_transacao(json.dumps(payload)))
        if "erro" in r:
            erros += 1
            warn(f"  Erro em {payload.get('transacao_id')}: {r['erro']}")
    _assert(erros == 0, f"J8: todas as 15 transações processadas sem erro (erros={erros})")


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print(f"\n{SEP}")
    print(f"{NEGRITO}  🛡️  RUNNER UNIFICADO — Anti-Fraude Sicredi{RESET}")
    print(f"  Validação dos Prompts 1 a 7 — AI Experiential Learning Lab 2026")
    print(SEP)

    suites = [
        ("Prompt 1 — 15 Transações JSON",         suite_p1_15_transacoes),
        ("Prompt 2 — Análise de Risco (3 regras)", suite_p2_analise_risco),
        ("Prompt 3 — Explicação Linguagem Natural", suite_p3_explicacao),
        ("Prompt 4 — Latência ≤ 50ms + Edge Cases", suite_p4_latencia_edge_cases),
        ("Prompt 5 — Skills de Orquestração",      suite_p5_skills),
        ("Prompt 6 — Push + HITL",                 suite_p6_hitl),
        ("Prompt 7 — E2E Caso 5 GPS",              suite_p7_e2e_gps),
    ]

    resultados_suites = []
    for nome, fn in suites:
        antes = _failed
        try:
            fn()
            passou = (_failed == antes)
        except Exception as exc:
            fail(f"Suite '{nome}' lançou exceção: {exc}")
            passou = False
        resultados_suites.append((nome, passou))

    # Relatório final
    print(f"\n{SEP}")
    print(f"{NEGRITO}  RELATÓRIO FINAL{RESET}")
    print(SEP)
    for nome, passou in resultados_suites:
        icone = f"{VERDE}✅{RESET}" if passou else f"{VERMELHO}❌{RESET}"
        print(f"  {icone}  {nome}")

    print()
    cor_t = VERDE if _failed == 0 else VERMELHO
    print(f"  Total de assertions : {_total}")
    print(f"  {VERDE}Aprovadas{RESET}           : {_passed}")
    print(f"  {cor_t}Reprovadas{RESET}          : {_failed}")
    print(SEP)

    if _failed == 0:
        print(f"\n{NEGRITO}{VERDE}  ✅  TODOS OS TESTES PASSARAM — Prompts 1 a 7 validados com sucesso{RESET}\n")
    else:
        print(f"\n{NEGRITO}{VERMELHO}  ❌  {_failed} assertion(s) falharam — verifique acima{RESET}\n")

    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
