"""
MCP — Detector de Carding / Força Bruta (F-001)
================================================
Detecta ataques de carding: sequências de micropagamentos (< R$ 10) realizados
em intervalo curto para testar a validade de um cartão antes de uma compra maior.

Ferramentas expostas:
  - detectar_carding                   → analisa a janela recente de transações
  - verificar_sequencia_micropagamentos → conta txns de baixo valor no período
  - bloquear_cartao_temporariamente     → registra bloqueio temporário do cartão
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="carding-detector",
    instructions=(
        "Detecta ataques de carding (F-001): micropagamentos sequenciais usados para testar "
        "validade de cartão. Use detectar_carding antes de aprovar qualquer transação de baixo "
        "valor em categoria digital/streaming. Use bloquear_cartao_temporariamente quando "
        "confirmado o ataque."
    ),
)

# ---------------------------------------------------------------------------
# Parâmetros da regra F-001 (alinhados ao fraud_rules.json)
# ---------------------------------------------------------------------------
VALOR_MAXIMO_MICROPAGAMENTO = 10.00    # R$ — transações abaixo disso são suspeitas
QUANTIDADE_MINIMA = 3                   # nº mínimo de micropagamentos para disparar
JANELA_MINUTOS = 5                      # janela de tempo analisada
SUB_SCORE_CARDING = 0.95               # sub_score quando regra é ativada

# ---------------------------------------------------------------------------
# Estado em memória
# ---------------------------------------------------------------------------
# Histórico de transações por associado para análise de janela deslizante
_JANELA: dict[str, list[dict[str, Any]]] = defaultdict(list)

# Cartões bloqueados temporariamente: {associado_id: {motivo, bloqueado_em, liberado_em}}
_BLOQUEIOS: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(ts: str) -> datetime:
    """Converte timestamp ISO-8601 para datetime. Lança ValueError para formatos inválidos."""
    if not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"Timestamp inválido: {ts!r}")
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _agora() -> datetime:
    return datetime.now(tz=timezone.utc)


def _esta_bloqueado(associado_id: str) -> bool:
    bloqueio = _BLOQUEIOS.get(associado_id)
    if not bloqueio:
        return False
    liberado_em = _parse_ts(bloqueio["liberado_em"])
    return _agora() < liberado_em


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

@mcp.tool()
def detectar_carding(associado_id: str, transacao_json: str) -> str:
    """
    Analisa se a transação atual faz parte de um ataque de carding,
    verificando a janela dos últimos JANELA_MINUTOS minutos do associado.

    Parâmetros
    ----------
    associado_id   : str — identificador do associado
    transacao_json : str — JSON da transação atual (campos: transacao_id, valor,
                           categoria, timestamp e opcionalmente estabelecimento_id)

    Retorna JSON com:
      - associado_id       : str
      - carding_detectado  : bool
      - sub_score          : float (0.0 se não detectado, 0.95 se confirmado)
      - micropagamentos_encontrados : int — qtd de txns < R$10 na janela
      - janela_minutos     : int
      - cartao_ja_bloqueado: bool
      - detalhes           : str
    """
    try:
        tx: dict[str, Any] = json.loads(transacao_json)
    except json.JSONDecodeError as e:
        return json.dumps({"erro": f"JSON inválido: {e}"}, ensure_ascii=False)

    # Verifica se já está bloqueado
    if _esta_bloqueado(associado_id):
        b = _BLOQUEIOS[associado_id]
        return json.dumps({
            "associado_id": associado_id,
            "carding_detectado": True,
            "sub_score": SUB_SCORE_CARDING,
            "micropagamentos_encontrados": 0,
            "janela_minutos": JANELA_MINUTOS,
            "cartao_ja_bloqueado": True,
            "detalhes": f"Cartão já bloqueado por '{b['motivo']}' até {b['liberado_em']}.",
        }, ensure_ascii=False, indent=2)

    try:
        ts_atual = _parse_ts(tx.get("timestamp", _agora().isoformat()))
    except (ValueError, TypeError):
        return json.dumps({
            "erro": "Campo 'timestamp' ausente ou em formato inválido na transação. Use ISO-8601.",
        }, ensure_ascii=False)

    valor_atual = tx.get("valor", 0.0)
    if not isinstance(valor_atual, (int, float)):
        valor_atual = 0.0

    janela_inicio = ts_atual - timedelta(minutes=JANELA_MINUTOS)

    # Filtra transações da janela para este associado (ignora entradas com timestamp inválido)
    historico_janela = []
    for t in _JANELA[associado_id]:
        try:
            if _parse_ts(t["timestamp"]) >= janela_inicio:
                historico_janela.append(t)
        except (ValueError, TypeError, KeyError):
            continue

    # Conta micropagamentos (incluindo a transação atual se for baixo valor)
    micropagamentos = [t for t in historico_janela if isinstance(t.get("valor"), (int, float)) and t.get("valor", 0) < VALOR_MAXIMO_MICROPAGAMENTO]
    if valor_atual < VALOR_MAXIMO_MICROPAGAMENTO:
        micropagamentos.append(tx)

    detectado = len(micropagamentos) >= QUANTIDADE_MINIMA

    # Registra a transação atual na janela para análise futura
    _JANELA[associado_id].append(tx)
    # Mantém apenas os últimos 60 min para não crescer indefinidamente
    cutoff = ts_atual - timedelta(minutes=60)
    janela_filtrada = []
    for t in _JANELA[associado_id]:
        try:
            if _parse_ts(t["timestamp"]) >= cutoff:
                janela_filtrada.append(t)
        except (ValueError, TypeError, KeyError):
            continue
    _JANELA[associado_id] = janela_filtrada

    if detectado:
        detalhes = (
            f"Detectados {len(micropagamentos)} micropagamentos (< R$ {VALOR_MAXIMO_MICROPAGAMENTO:.2f}) "
            f"nos últimos {JANELA_MINUTOS} minutos — padrão típico de carding/força bruta."
        )
    else:
        detalhes = (
            f"Apenas {len(micropagamentos)} micropagamento(s) na janela de {JANELA_MINUTOS} min "
            f"(limiar: {QUANTIDADE_MINIMA}). Nenhuma ação necessária."
        )

    return json.dumps({
        "associado_id": associado_id,
        "carding_detectado": detectado,
        "sub_score": SUB_SCORE_CARDING if detectado else 0.0,
        "micropagamentos_encontrados": len(micropagamentos),
        "janela_minutos": JANELA_MINUTOS,
        "cartao_ja_bloqueado": False,
        "detalhes": detalhes,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def verificar_sequencia_micropagamentos(associado_id: str, janela_minutos: int = 5) -> str:
    """
    Consulta o número de micropagamentos (< R$ 10) realizados pelo associado
    no intervalo especificado, sem registrar nenhuma nova transação.
    Útil para auditoria e investigação sem efeitos colaterais.

    Parâmetros
    ----------
    associado_id   : str — identificador do associado
    janela_minutos : int — janela de tempo em minutos (padrão: 5, máx: 60)

    Retorna JSON com:
      - associado_id             : str
      - janela_minutos           : int
      - micropagamentos          : int — contagem de txns < R$10 na janela
      - limiar_alerta            : int — quantidade que dispara alerta (3)
      - alerta                   : bool
      - transacoes_na_janela     : list — detalhes das transações encontradas
    """
    janela_minutos = max(1, min(janela_minutos, 60))
    agora = _agora()
    cutoff = agora - timedelta(minutes=janela_minutos)

    historico = _JANELA.get(associado_id, [])
    na_janela = []
    for t in historico:
        try:
            if _parse_ts(t["timestamp"]) >= cutoff:
                na_janela.append(t)
        except (ValueError, TypeError, KeyError):
            continue
    micropagamentos = [t for t in na_janela if t.get("valor", 0) < VALOR_MAXIMO_MICROPAGAMENTO]

    return json.dumps({
        "associado_id": associado_id,
        "janela_minutos": janela_minutos,
        "micropagamentos": len(micropagamentos),
        "limiar_alerta": QUANTIDADE_MINIMA,
        "alerta": len(micropagamentos) >= QUANTIDADE_MINIMA,
        "transacoes_na_janela": micropagamentos,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def bloquear_cartao_temporariamente(
    associado_id: str,
    motivo: str,
    duracao_minutos: int = 30,
) -> str:
    """
    Registra um bloqueio temporário do cartão do associado.
    Após `duracao_minutos`, o bloqueio expira automaticamente.
    Chamadas futuras a detectar_carding retornarão cartao_ja_bloqueado=true
    enquanto o bloqueio estiver ativo.

    Parâmetros
    ----------
    associado_id     : str — identificador do associado
    motivo           : str — descrição do motivo (ex: "carding confirmado F-001")
    duracao_minutos  : int — duração do bloqueio em minutos (padrão: 30, máx: 1440)

    Retorna JSON com:
      - associado_id  : str
      - bloqueado     : bool
      - bloqueado_em  : str (ISO-8601)
      - liberado_em   : str (ISO-8601)
      - motivo        : str
    """
    duracao_minutos = max(1, min(duracao_minutos, 1440))
    agora = _agora()
    liberado_em = agora + timedelta(minutes=duracao_minutos)

    _BLOQUEIOS[associado_id] = {
        "motivo": motivo,
        "bloqueado_em": agora.isoformat(),
        "liberado_em": liberado_em.isoformat(),
    }

    return json.dumps({
        "associado_id": associado_id,
        "bloqueado": True,
        "bloqueado_em": agora.isoformat(),
        "liberado_em": liberado_em.isoformat(),
        "motivo": motivo,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
