"""
MCP — Histórico do Associado
=============================
Simula a camada de persistência (Redis + PostgreSQL) para perfis e histórico
transacional dos associados. Todos os dados vivem em memória durante a sessão,
partindo de um seed realista alinhado ao transactions.json do projeto.

Ferramentas expostas:
  - buscar_historico_associado  → últimas N transações do associado
  - buscar_perfil_associado     → ticket médio, desvio-padrão, categorias/cidades habituais
  - registrar_transacao         → persiste nova transação no histórico da sessão
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="historico-associado",
    instructions=(
        "Gerencia o histórico transacional e o perfil comportamental dos associados. "
        "Use buscar_historico_associado para obter as últimas transações antes de avaliar risco. "
        "Use registrar_transacao após cada decisão para manter o histórico atualizado."
    ),
)

# ---------------------------------------------------------------------------
# Seed de histórico em memória  {associado_id: [transacoes ordenadas por timestamp]}
# ---------------------------------------------------------------------------
_DB: dict[str, list[dict[str, Any]]] = {
    "assoc-001-rs": [
        {"transacao_id": "h001", "valor": 187.43, "categoria": "Supermercado",
         "localizacao": {"latitude": -30.0346, "longitude": -51.2177, "cidade": "Porto Alegre", "pais": "BR"},
         "timestamp": "2026-10-25T10:15:22Z"},
        {"transacao_id": "h002", "valor": 312.00, "categoria": "Posto de Combustível",
         "localizacao": {"latitude": -30.0412, "longitude": -51.2089, "cidade": "Porto Alegre", "pais": "BR"},
         "timestamp": "2026-10-26T08:00:00Z"},
        {"transacao_id": "h003", "valor": 210.00, "categoria": "Supermercado",
         "localizacao": {"latitude": -30.0346, "longitude": -51.2177, "cidade": "Porto Alegre", "pais": "BR"},
         "timestamp": "2026-10-28T11:30:00Z"},
        {"transacao_id": "h004", "valor": 95.00, "categoria": "Farmácia",
         "localizacao": {"latitude": -30.0380, "longitude": -51.2200, "cidade": "Porto Alegre", "pais": "BR"},
         "timestamp": "2026-10-30T09:00:00Z"},
        {"transacao_id": "h005", "valor": 280.00, "categoria": "Posto de Combustível",
         "localizacao": {"latitude": -30.0412, "longitude": -51.2089, "cidade": "Porto Alegre", "pais": "BR"},
         "timestamp": "2026-11-01T08:00:00Z"},
    ],
    "assoc-002-sc": [
        {"transacao_id": "h101", "valor": 156.80, "categoria": "Restaurante",
         "localizacao": {"latitude": -27.5954, "longitude": -48.5480, "cidade": "Florianópolis", "pais": "BR"},
         "timestamp": "2026-10-25T20:30:05Z"},
        {"transacao_id": "h102", "valor": 39.90, "categoria": "Streaming / Entretenimento Digital",
         "localizacao": {"latitude": -27.5954, "longitude": -48.5480, "cidade": "Florianópolis", "pais": "BR"},
         "timestamp": "2026-10-26T00:05:12Z"},
        {"transacao_id": "h103", "valor": 220.00, "categoria": "Restaurante",
         "localizacao": {"latitude": -27.5960, "longitude": -48.5490, "cidade": "Florianópolis", "pais": "BR"},
         "timestamp": "2026-10-29T19:45:00Z"},
        {"transacao_id": "h104", "valor": 4500.00, "categoria": "Transferência Financeira",
         "localizacao": {"latitude": -27.5954, "longitude": -48.5480, "cidade": "Florianópolis", "pais": "BR"},
         "timestamp": "2026-11-01T03:22:44Z"},
    ],
    "assoc-003-rs": [
        {"transacao_id": "h201", "valor": 89.50, "categoria": "Farmácia",
         "localizacao": {"latitude": -29.6869, "longitude": -53.8069, "cidade": "Santa Maria", "pais": "BR"},
         "timestamp": "2026-10-25T09:05:00Z"},
        {"transacao_id": "h202", "valor": 99.90, "categoria": "Academia / Fitness",
         "localizacao": {"latitude": -29.6918, "longitude": -53.8010, "cidade": "Santa Maria", "pais": "BR"},
         "timestamp": "2026-10-26T07:10:00Z"},
        {"transacao_id": "h203", "valor": 680.00, "categoria": "Educação / Ensino",
         "localizacao": {"latitude": -29.6869, "longitude": -53.8069, "cidade": "Santa Maria", "pais": "BR"},
         "timestamp": "2026-10-30T08:30:00Z"},
    ],
    "assoc-004-pr": [
        {"transacao_id": "h301", "valor": 124.70, "categoria": "Livraria / Papelaria",
         "localizacao": {"latitude": -25.4284, "longitude": -49.2733, "cidade": "Curitiba", "pais": "BR"},
         "timestamp": "2026-10-25T14:22:38Z"},
        {"transacao_id": "h302", "valor": 349.00, "categoria": "Vestuário / Moda",
         "localizacao": {"latitude": -25.4189, "longitude": -49.2781, "cidade": "Curitiba", "pais": "BR"},
         "timestamp": "2026-10-28T16:55:14Z"},
        {"transacao_id": "h303", "valor": 1890.00, "categoria": "Material de Construção / Home Center",
         "localizacao": {"latitude": -25.4230, "longitude": -49.2910, "cidade": "Curitiba", "pais": "BR"},
         "timestamp": "2026-11-01T10:05:50Z"},
    ],
    "assoc-005-rj": [
        {"transacao_id": "h401", "valor": 55.00, "categoria": "Restaurante",
         "localizacao": {"latitude": -22.9068, "longitude": -43.1729, "cidade": "Rio de Janeiro", "pais": "BR"},
         "timestamp": "2026-10-25T12:00:00Z"},
        {"transacao_id": "h402", "valor": 30.00, "categoria": "Streaming / Entretenimento Digital",
         "localizacao": {"latitude": -22.9068, "longitude": -43.1729, "cidade": "Rio de Janeiro", "pais": "BR"},
         "timestamp": "2026-10-28T18:00:00Z"},
    ],
    "assoc-006-rs-rural": [
        {"transacao_id": "h501", "valor": 320.00, "categoria": "Agropecuária",
         "localizacao": {"latitude": -28.2620, "longitude": -52.4083, "cidade": "Passo Fundo", "pais": "BR"},
         "timestamp": "2026-10-20T09:00:00Z"},
        {"transacao_id": "h502", "valor": 450.00, "categoria": "Posto de Combustível",
         "localizacao": {"latitude": -28.2600, "longitude": -52.4100, "cidade": "Passo Fundo", "pais": "BR"},
         "timestamp": "2026-10-22T11:30:00Z"},
        {"transacao_id": "h503", "valor": 270.00, "categoria": "Supermercado",
         "localizacao": {"latitude": -28.2650, "longitude": -52.4050, "cidade": "Passo Fundo", "pais": "BR"},
         "timestamp": "2026-10-25T14:00:00Z"},
        {"transacao_id": "h504", "valor": 380.00, "categoria": "Agropecuária",
         "localizacao": {"latitude": -28.2620, "longitude": -52.4083, "cidade": "Passo Fundo", "pais": "BR"},
         "timestamp": "2026-10-28T08:30:00Z"},
        {"transacao_id": "h505", "valor": 290.00, "categoria": "Posto de Combustível",
         "localizacao": {"latitude": -28.2600, "longitude": -52.4100, "cidade": "Carazinho", "pais": "BR"},
         "timestamp": "2026-10-31T10:00:00Z"},
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sorted_by_ts(txns: list[dict]) -> list[dict]:
    # Ignora entradas sem timestamp em vez de travar o sort
    return sorted(
        (t for t in txns if isinstance(t.get("timestamp"), str)),
        key=lambda t: t["timestamp"],
    )


def _calcular_perfil(historico: list[dict]) -> dict[str, Any]:
    """Calcula estatísticas comportamentais a partir do histórico."""
    if not historico:
        return {}

    # Filtra apenas entradas com valor numérico válido
    valores = [
        t["valor"] for t in historico
        if isinstance(t.get("valor"), (int, float))
    ]
    if not valores:
        return {}

    ticket_medio = statistics.mean(valores)
    ticket_dp = statistics.stdev(valores) if len(valores) > 1 else 0.0

    from collections import Counter
    # Usa .get() para não estourar em entradas sem "categoria"
    cats = Counter(t.get("categoria", "") for t in historico if t.get("categoria"))
    cidades = Counter(
        t.get("localizacao", {}).get("cidade", "")
        for t in historico
        if t.get("localizacao", {}).get("cidade")
    )

    return {
        "ticket_medio": round(ticket_medio, 2),
        "ticket_desvio_padrao": round(ticket_dp, 2),
        "ticket_max_historico": round(max(valores), 2),
        "ticket_min_historico": round(min(valores), 2),
        "total_transacoes": len(historico),
        "categorias_frequentes": [c for c, _ in cats.most_common(5)],
        "cidades_frequentes": [c for c, _ in cidades.most_common(3)],
    }


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

@mcp.tool()
def buscar_historico_associado(associado_id: str, limite: int = 30) -> str:
    """
    Retorna as últimas N transações do associado, ordenadas da mais recente para a mais antiga.

    Parâmetros
    ----------
    associado_id : str  — identificador do associado (ex: "assoc-001-rs")
    limite       : int  — número máximo de transações a retornar (padrão: 30, máx: 100)

    Retorna JSON com:
      - associado_id      : str
      - total_disponivel  : int  — total de registros no histórico
      - transacoes        : list — últimas `limite` transações (mais recente primeiro)
    """
    limite = max(1, min(limite, 100))
    historico = _sorted_by_ts(_DB.get(associado_id, []))
    recentes = list(reversed(historico))[:limite]

    return json.dumps({
        "associado_id": associado_id,
        "total_disponivel": len(historico),
        "transacoes": recentes,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_perfil_associado(associado_id: str) -> str:
    """
    Retorna o perfil comportamental do associado: ticket médio, desvio-padrão,
    categorias e cidades mais frequentes.

    Parâmetros
    ----------
    associado_id : str  — identificador do associado

    Retorna JSON com:
      - associado_id           : str
      - encontrado             : bool
      - ticket_medio           : float  (R$)
      - ticket_desvio_padrao   : float  (R$)
      - ticket_max_historico   : float
      - ticket_min_historico   : float
      - total_transacoes       : int
      - categorias_frequentes  : list[str]  (top 5)
      - cidades_frequentes     : list[str]  (top 3)
    """
    historico = _DB.get(associado_id, [])
    if not historico:
        return json.dumps({
            "associado_id": associado_id,
            "encontrado": False,
        }, ensure_ascii=False, indent=2)

    perfil = _calcular_perfil(historico)
    perfil["associado_id"] = associado_id
    perfil["encontrado"] = True

    return json.dumps(perfil, ensure_ascii=False, indent=2)


@mcp.tool()
def registrar_transacao(transacao_json: str) -> str:
    """
    Persiste uma nova transação no histórico em memória do associado.
    Deve ser chamada após cada decisão de aprovação ou bloqueio para manter
    o histórico atualizado para análises futuras.

    Parâmetros
    ----------
    transacao_json : str  — JSON com os dados da transação.
        Campos obrigatórios: associado_id, transacao_id, valor, categoria, timestamp
        Campo opcional: localizacao {latitude, longitude, cidade, pais}

    Retorna JSON com:
      - sucesso          : bool
      - associado_id     : str
      - transacao_id     : str
      - total_historico  : int  — tamanho do histórico após inserção
    """
    try:
        tx: dict[str, Any] = json.loads(transacao_json)
    except json.JSONDecodeError as e:
        return json.dumps({"sucesso": False, "erro": f"JSON inválido: {e}"}, ensure_ascii=False)

    obrigatorios = ["associado_id", "transacao_id", "valor", "categoria", "timestamp"]
    faltando = [c for c in obrigatorios if c not in tx]
    if faltando:
        return json.dumps({"sucesso": False, "erro": f"Campos obrigatórios ausentes: {faltando}"}, ensure_ascii=False)

    assoc_id = tx["associado_id"]
    _DB.setdefault(assoc_id, []).append(tx)

    return json.dumps({
        "sucesso": True,
        "associado_id": assoc_id,
        "transacao_id": tx["transacao_id"],
        "total_historico": len(_DB[assoc_id]),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
