"""
orchestration/test_orchestration.py
====================================
Testes diretos do fluxo de orquestração sem dependência do subprocess.
Importa as funções MCP diretamente (mesmo padrão de test_server.py).

Execute a partir da raiz do projeto:
    python orchestration/test_orchestration.py
"""
from __future__ import annotations

import json
import sys
import os

# Garante que mcp_antifraude esteja no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_antifraude"))

from server import analisar_risco_transacao, explicar_risco_fraude  # type: ignore

SEP = "─" * 62


def _analisar(titulo: str, transacao: dict) -> dict:
    print(f"\n{SEP}")
    print(f"  {titulo}")
    print(SEP)
    resultado = json.loads(analisar_risco_transacao(json.dumps(transacao)))
    score = resultado["score_risco"]
    nivel = resultado["nivel_risco"]
    regras = [r["regra"] for r in resultado.get("regras_violadas", [])]
    print(f"  score_risco    : {score}")
    print(f"  nivel_risco    : {nivel}")
    print(f"  regras_violadas: {regras}")
    return resultado


def _fluxo_orquestrador(titulo: str, transacao: dict) -> None:
    """Replica a lógica do AgenteAntiFraude sem importar o pacote orchestration."""
    resultado = _analisar(titulo, transacao)
    score = resultado["score_risco"]

    LIMIAR = 70

    if score <= LIMIAR:
        print(f"\n  → DECISÃO: ✅ APROVADA automaticamente (score={score} ≤ {LIMIAR})")
        print(f"  → LIQUIDAÇÃO: ATIVA")
    else:
        print(f"\n  → DECISÃO: 🚫 LIQUIDAÇÃO PAUSADA (score={score} > {LIMIAR})")
        print(f"  → Acionando skill: explicar_risco_fraude ...")
        explicacao = json.loads(explicar_risco_fraude(json.dumps(resultado)))
        print(f"\n  [STORE] Explicação armazenada:")
        print(f"    titulo     : {explicacao.get('titulo')}")
        print(f"    orientacao : {explicacao.get('orientacao')}")
        msg = explicacao.get("mensagem_associado", "")
        print(f"    mensagem   : {msg[:120]}...")


# ── Caso 1: risco BAIXO — transação normal ────────────────────────────────
_fluxo_orquestrador(
    "CASO 1 — Risco BAIXO: transação normal (espera APROVADA)",
    {
        "transacao_id": "orch_001",
        "associado_id": "assoc_001",
        "valor": 130.00,
        "categoria": "Supermercados",
        "timestamp": "2026-11-03T09:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
)

# ── Caso 2: risco MÉDIO — pico moderado (score 35) ───────────────────────
_fluxo_orquestrador(
    "CASO 2 — Risco MÉDIO: pico de valor (espera APROVADA)",
    {
        "transacao_id": "orch_002",
        "associado_id": "assoc_001",
        "valor": 600.00,           # ~4.6× média → score 35
        "categoria": "Supermercados",
        "timestamp": "2026-11-03T11:00:00",
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
)

# ── Caso 3: risco CRÍTICO — pico extremo + perfil incomum ────────────────
_fluxo_orquestrador(
    "CASO 3 — Risco CRÍTICO: pico + perfil incomum (espera LIQUIDAÇÃO PAUSADA)",
    {
        "transacao_id": "orch_003",
        "associado_id": "assoc_001",
        "valor": 5000.00,          # pico extremo → +35
        "categoria": "Eletrônicos", # alto risco fora do horário → +25 → total 60... + velocidade?
        "timestamp": "2026-11-03T02:30:00",  # madrugada
        "latitude": -23.5505,
        "longitude": -46.6333,
    },
)

# ── Caso 4: risco CRÍTICO — velocidade impossível + pico ─────────────────
_fluxo_orquestrador(
    "CASO 4 — Risco CRÍTICO: velocidade impossível (espera LIQUIDAÇÃO PAUSADA)",
    {
        "transacao_id": "orch_004",
        "associado_id": "assoc_002",
        "valor": 800.00,
        "categoria": "Joalherias",
        "timestamp": "2026-11-01T09:15:00",  # 15 min após t101 em local distante
        "latitude": -3.7327,                  # Fortaleza (~3000 km do Rio)
        "longitude": -38.5270,
    },
)

print(f"\n{SEP}")
print("  Todos os testes de orquestração concluídos.")
print(SEP)
