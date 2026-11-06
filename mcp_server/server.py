"""
Servidor MCP — Motor de Análise de Risco de Transações
Implementa a ferramenta `analisar_risco_transacao` com três regras heurísticas:
  1. Velocidade Impossível (GPS)
  2. Pico de Transação (valor 3x acima da média histórica)
  3. Perfil Incomum (categoria de alto risco em horário atípico)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Inicialização do servidor
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="anti-fraude-sicredi",
    instructions=(
        "Servidor de análise de risco de transações financeiras. "
        "Use a ferramenta `analisar_risco_transacao` para avaliar o nível de risco "
        "de uma transação com base no histórico do associado."
    ),
)

# ---------------------------------------------------------------------------
# Histórico em memória  {associado_id: [lista de transações passadas]}
# Pré-populado com dados realistas para demonstração
# ---------------------------------------------------------------------------
HISTORICO: dict[str, list[dict[str, Any]]] = {
    "assoc-001-rs": [
        {
            "transacao_id": "txn-20261101-0001",
            "valor": 187.43,
            "categoria": "Supermercado",
            "localizacao": {"latitude": -30.0346, "longitude": -51.2177, "cidade": "Porto Alegre"},
            "timestamp": "2026-11-01T10:15:22Z",
        },
        {
            "transacao_id": "txn-20261101-0002",
            "valor": 312.00,
            "categoria": "Posto de Combustível",
            "localizacao": {"latitude": -30.0412, "longitude": -51.2089, "cidade": "Porto Alegre"},
            "timestamp": "2026-11-01T08:00:00Z",
        },
    ],
    "assoc-002-sc": [
        {
            "transacao_id": "txn-20261101-0003",
            "valor": 156.80,
            "categoria": "Restaurante",
            "localizacao": {"latitude": -27.5954, "longitude": -48.5480, "cidade": "Florianópolis"},
            "timestamp": "2026-11-01T20:30:05Z",
        },
        {
            "transacao_id": "txn-20261101-0005",
            "valor": 39.90,
            "categoria": "Streaming / Entretenimento Digital",
            "localizacao": {"latitude": -27.5954, "longitude": -48.5480, "cidade": "Florianópolis"},
            "timestamp": "2026-11-01T00:05:12Z",
        },
    ],
    "assoc-006-rs-rural": [
        {
            "transacao_id": "hist-001",
            "valor": 320.00,
            "categoria": "Agropecuária",
            "localizacao": {"latitude": -28.2620, "longitude": -52.4083, "cidade": "Passo Fundo"},
            "timestamp": "2026-10-28T09:00:00Z",
        },
        {
            "transacao_id": "hist-002",
            "valor": 450.00,
            "categoria": "Posto de Combustível",
            "localizacao": {"latitude": -28.2600, "longitude": -52.4100, "cidade": "Passo Fundo"},
            "timestamp": "2026-10-29T11:30:00Z",
        },
        {
            "transacao_id": "hist-003",
            "valor": 270.00,
            "categoria": "Supermercado",
            "localizacao": {"latitude": -28.2650, "longitude": -52.4050, "cidade": "Passo Fundo"},
            "timestamp": "2026-10-30T14:00:00Z",
        },
    ],
}

# ---------------------------------------------------------------------------
# Constantes das regras heurísticas (alinhadas com fraud_rules.json)
# ---------------------------------------------------------------------------
VELOCIDADE_MAXIMA_KMH = 1_200          # F-002: máximo para transporte comercial
DISTANCIA_MINIMA_GPS_KM = 50           # abaixo disso não aplica regra GPS
FATOR_PICO_TRANSACAO = 3.0             # F-003: valor 3× a média histórica
CATEGORIAS_ALTO_RISCO = {              # F-005: categorias sensíveis
    "Joalheria / Artigos de Luxo",
    "Eletrônicos",
    "E-commerce / Eletrônicos",
    "Transferência Financeira",
    "Câmbio / Moeda Estrangeira",
}
HORARIO_INCOMUM_INICIO = 2             # F-005: 02:00 UTC
HORARIO_INCOMUM_FIM = 6               # F-005: 05:59 UTC (exclusive)

# Pesos das regras no score final (soma = 1.0 neste subconjunto)
PESO_GPS = 0.40
PESO_PICO = 0.35
PESO_PERFIL = 0.25


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância geodésica entre dois pontos em km (fórmula de Haversine)."""
    R = 6_371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_ts(ts: str) -> datetime:
    """Converte timestamp ISO-8601 para datetime com timezone UTC."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _media_historica(historico: list[dict]) -> float:
    """Retorna o valor médio das transações históricas."""
    if not historico:
        return 0.0
    return sum(t["valor"] for t in historico) / len(historico)


# ---------------------------------------------------------------------------
# Regras heurísticas
# ---------------------------------------------------------------------------

def _regra_velocidade_gps(
    transacao: dict, historico: list[dict]
) -> tuple[bool, str, float]:
    """
    Regra 1 — Velocidade Impossível (GPS).
    Verifica se a distância entre a transação atual e a mais recente do histórico
    implicaria velocidade de deslocamento fisicamente impossível.
    """
    if not historico:
        return False, "", 0.0

    loc_atual = transacao.get("localizacao", {})
    lat2 = loc_atual.get("latitude")
    lon2 = loc_atual.get("longitude")
    if lat2 is None or lon2 is None:
        return False, "", 0.0

    # Ordena histórico por timestamp decrescente e pega a transação mais recente
    historico_ord = sorted(historico, key=lambda t: t["timestamp"], reverse=True)
    ultima = historico_ord[0]
    loc_ant = ultima.get("localizacao", {})
    lat1 = loc_ant.get("latitude")
    lon1 = loc_ant.get("longitude")
    if lat1 is None or lon1 is None:
        return False, "", 0.0

    distancia_km = _haversine_km(lat1, lon1, lat2, lon2)
    if distancia_km < DISTANCIA_MINIMA_GPS_KM:
        return False, "", 0.0

    try:
        ts_atual = _parse_ts(transacao["timestamp"])
        ts_ant = _parse_ts(ultima["timestamp"])
    except (KeyError, ValueError):
        return False, "", 0.0

    minutos = (ts_atual - ts_ant).total_seconds() / 60.0
    if minutos <= 0:
        return False, "", 0.0

    velocidade_kmh = distancia_km / (minutos / 60.0)

    if velocidade_kmh > VELOCIDADE_MAXIMA_KMH:
        cidade_ant = loc_ant.get("cidade", "desconhecida")
        cidade_nova = loc_atual.get("cidade", "desconhecida")
        descricao = (
            f"Deslocamento de {cidade_ant} → {cidade_nova}: "
            f"{distancia_km:.0f} km em {minutos:.0f} min "
            f"(velocidade implícita: {velocidade_kmh:.0f} km/h — impossível)."
        )
        # Sub-score proporcional à velocidade, capped em 0.97
        sub_score = min(0.97, 0.60 + (velocidade_kmh - VELOCIDADE_MAXIMA_KMH) / 10_000)
        return True, descricao, sub_score

    return False, "", 0.0


def _regra_pico_transacao(
    transacao: dict, historico: list[dict]
) -> tuple[bool, str, float]:
    """
    Regra 2 — Pico de Transação.
    Detecta quando o valor da transação é pelo menos 3× a média histórica do associado.
    """
    if not historico:
        return False, "", 0.0

    valor_atual = transacao.get("valor", 0.0)
    media = _media_historica(historico)
    if media <= 0:
        return False, "", 0.0

    fator = valor_atual / media
    if fator >= FATOR_PICO_TRANSACAO:
        descricao = (
            f"Valor R$ {valor_atual:.2f} é {fator:.1f}× a média histórica "
            f"(R$ {media:.2f}) — pico anômalo de transação."
        )
        # Sub-score cresce com o fator, capped em 0.95
        sub_score = min(0.95, 0.55 + (fator - FATOR_PICO_TRANSACAO) * 0.04)
        return True, descricao, sub_score

    return False, "", 0.0


def _regra_perfil_incomum(
    transacao: dict, _historico: list[dict]
) -> tuple[bool, str, float]:
    """
    Regra 3 — Perfil Incomum.
    Penaliza categorias de alto risco realizadas em horários atípicos (02:00–05:59 UTC).
    """
    categoria = transacao.get("categoria", "")
    if categoria not in CATEGORIAS_ALTO_RISCO:
        return False, "", 0.0

    try:
        ts = _parse_ts(transacao["timestamp"])
    except (KeyError, ValueError):
        return False, "", 0.0

    hora_utc = ts.hour
    if HORARIO_INCOMUM_INICIO <= hora_utc < HORARIO_INCOMUM_FIM:
        descricao = (
            f"Categoria de alto risco '{categoria}' realizada às "
            f"{ts.strftime('%H:%M')} UTC — faixa de horário incomum (02h–05h59)."
        )
        return True, descricao, 0.65

    return False, "", 0.0


# ---------------------------------------------------------------------------
# Ferramenta MCP principal
# ---------------------------------------------------------------------------

@mcp.tool()
def analisar_risco_transacao(transacao: dict) -> dict:
    """
    Analisa o risco de uma transação financeira aplicando três regras heurísticas
    contra o histórico em memória do associado.

    Parâmetros
    ----------
    transacao : dict
        JSON da transação atual. Campos esperados:
        - associado_id  (str)   — identificador único do associado
        - transacao_id  (str)   — identificador da transação
        - valor         (float) — valor em R$
        - categoria     (str)   — categoria do estabelecimento
        - timestamp     (str)   — ISO-8601, ex: "2026-11-01T10:15:22Z"
        - localizacao   (dict)  — {latitude, longitude, cidade}

    Retorna
    -------
    dict com:
        - associado_id     (str)
        - transacao_id     (str)
        - score_risco      (int, 0–100)
        - nivel_risco      (str: BAIXO | MEDIO | ALTO | CRITICO)
        - acao_recomendada (str)
        - regras_violadas  (list[dict]) — cada item: {regra, descricao, sub_score}
        - detalhes         (dict)       — média histórica e nº de transações no histórico
    """
    associado_id: str = transacao.get("associado_id", "desconhecido")
    transacao_id: str = transacao.get("transacao_id", "sem-id")

    historico = HISTORICO.get(associado_id, [])

    # --- Aplicação das três regras ---
    violadas: list[dict] = []
    score_ponderado = 0.0

    ativou_gps, desc_gps, ss_gps = _regra_velocidade_gps(transacao, historico)
    if ativou_gps:
        violadas.append({
            "regra": "VELOCIDADE_IMPOSSIVEL_GPS",
            "descricao": desc_gps,
            "sub_score": round(ss_gps, 2),
        })
        score_ponderado += ss_gps * PESO_GPS

    ativou_pico, desc_pico, ss_pico = _regra_pico_transacao(transacao, historico)
    if ativou_pico:
        violadas.append({
            "regra": "PICO_DE_TRANSACAO",
            "descricao": desc_pico,
            "sub_score": round(ss_pico, 2),
        })
        score_ponderado += ss_pico * PESO_PICO

    ativou_perfil, desc_perfil, ss_perfil = _regra_perfil_incomum(transacao, historico)
    if ativou_perfil:
        violadas.append({
            "regra": "PERFIL_INCOMUM",
            "descricao": desc_perfil,
            "sub_score": round(ss_perfil, 2),
        })
        score_ponderado += ss_perfil * PESO_PERFIL

    # Normaliza o score para 0–100
    score_risco = min(100, round(score_ponderado * 100))

    # Classificação por faixa (alinhada com fraud_rules.json)
    if score_risco <= 39:
        nivel = "BAIXO"
        acao = "APROVAR"
    elif score_risco <= 69:
        nivel = "MEDIO"
        acao = "APROVAR_COM_ALERTA"
    elif score_risco <= 84:
        nivel = "ALTO"
        acao = "SOLICITAR_CONFIRMACAO"
    else:
        nivel = "CRITICO"
        acao = "BLOQUEAR"

    # Persiste a transação no histórico para análises futuras nesta sessão
    HISTORICO.setdefault(associado_id, []).append(transacao)

    media_historica = _media_historica(historico) if historico else None

    return {
        "associado_id": associado_id,
        "transacao_id": transacao_id,
        "score_risco": score_risco,
        "nivel_risco": nivel,
        "acao_recomendada": acao,
        "regras_violadas": violadas,
        "detalhes": {
            "transacoes_no_historico": len(historico),
            "media_historica_brl": round(media_historica, 2) if media_historica else None,
        },
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
