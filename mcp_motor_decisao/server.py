"""
MCP — Motor de Decisão
=======================
Aplica os thresholds definidos no fraud_rules.json, orquestra a ação correta
(APROVAR / ALERTA / CONFIRMAR / BLOQUEAR) e registra cada decisão para auditoria
obrigatória (LGPD / PCI-DSS).

Ferramentas expostas:
  - decidir_transacao   → aplica thresholds e retorna a decisão
  - aplicar_acao        → executa e persiste a ação no autorizador (simulado)
  - registrar_decisao   → log de auditoria imutável
  - consultar_decisao   → recupera a decisão registrada para uma transação
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="motor-decisao",
    instructions=(
        "Aplica os thresholds do sistema anti-fraude e executa a ação correspondente. "
        "Fluxo correto: 1) chame decidir_transacao com o score consolidado; "
        "2) chame aplicar_acao para executar; 3) chame registrar_decisao para auditoria. "
        "Thresholds alinhados ao mcp_antifraude: "
        "Score 0 → APROVAR (BAIXO) | 1–35 → APROVAR_COM_ALERTA (MEDIO) | "
        "36–70 → SOLICITAR_CONFIRMACAO (ALTO) | 71–100 → BLOQUEAR (CRITICO)."
    ),
)

# ---------------------------------------------------------------------------
# Thresholds (alinhados ao mcp_antifraude/server.py — fonte de verdade do score)
# ---------------------------------------------------------------------------
THRESHOLDS = [
    {"min": 0,  "max": 0,   "decisao": "APROVAR",               "nivel": "BAIXO",   "cor": "verde"},
    {"min": 1,  "max": 35,  "decisao": "APROVAR_COM_ALERTA",     "nivel": "MEDIO",   "cor": "amarelo"},
    {"min": 36, "max": 70,  "decisao": "SOLICITAR_CONFIRMACAO",  "nivel": "ALTO",    "cor": "laranja"},
    {"min": 71, "max": 100, "decisao": "BLOQUEAR",               "nivel": "CRITICO", "cor": "vermelho"},
]

# ---------------------------------------------------------------------------
# Log de auditoria em memória  {transacao_id: registro}
# ---------------------------------------------------------------------------
_LOG_AUDITORIA: dict[str, dict[str, Any]] = {}

# Estado das transações pendentes de confirmação
_PENDENTES: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agora_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _threshold_para_score(score: int) -> dict[str, Any]:
    score = max(0, min(100, score))
    for t in THRESHOLDS:
        if t["min"] <= score <= t["max"]:
            return t
    return THRESHOLDS[-1]


def _descricao_acao(decisao: str) -> str:
    mapa = {
        "APROVAR": "Transação aprovada automaticamente — risco baixo.",
        "APROVAR_COM_ALERTA": "Transação aprovada com alerta silencioso para analista — risco moderado.",
        "SOLICITAR_CONFIRMACAO": "Aguardando confirmação do associado via push/SMS — risco elevado.",
        "BLOQUEAR": "Transação bloqueada imediatamente — risco crítico. Caso aberto para analista sênior.",
    }
    return mapa.get(decisao, "Ação desconhecida.")


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

@mcp.tool()
def decidir_transacao(
    transacao_id: str,
    associado_id: str,
    score_risco: int,
    regras_violadas_json: str = "[]",
) -> str:
    """
    Determina a ação a ser tomada com base no score de risco consolidado.
    Aplica os thresholds definidos em fraud_rules.json.

    Parâmetros
    ----------
    transacao_id         : str  — identificador da transação
    associado_id         : str  — identificador do associado
    score_risco          : int  — score consolidado de 0 a 100
    regras_violadas_json : str  — JSON array das regras violadas (opcional, para log)

    Retorna JSON com:
      - transacao_id      : str
      - associado_id      : str
      - score_risco       : int
      - decisao           : str  (APROVAR | APROVAR_COM_ALERTA | SOLICITAR_CONFIRMACAO | BLOQUEAR)
      - nivel_risco       : str  (BAIXO | MEDIO | ALTO | CRITICO)
      - cor               : str  (verde | amarelo | laranja | vermelho)
      - descricao_acao    : str
      - timeout_segundos  : int | null  (120 se SOLICITAR_CONFIRMACAO, null caso contrário)
      - decidido_em       : str  (ISO-8601)
    """
    # Garante que score_risco é inteiro — pode vir como string via LLM
    try:
        score_risco = int(score_risco)
    except (ValueError, TypeError):
        return json.dumps({
            "erro": f"score_risco deve ser um número inteiro entre 0 e 100, recebido: {score_risco!r}",
        }, ensure_ascii=False, indent=2)

    try:
        regras = json.loads(regras_violadas_json)
    except json.JSONDecodeError:
        regras = []

    if not isinstance(regras, list):
        regras = []

    t = _threshold_para_score(score_risco)
    decisao = t["decisao"]
    timeout = 120 if decisao == "SOLICITAR_CONFIRMACAO" else None

    resultado = {
        "transacao_id": transacao_id,
        "associado_id": associado_id,
        "score_risco": score_risco,
        "decisao": decisao,
        "nivel_risco": t["nivel"],
        "cor": t["cor"],
        "descricao_acao": _descricao_acao(decisao),
        "timeout_segundos": timeout,
        "regras_violadas": regras,
        "decidido_em": _agora_iso(),
    }

    # Registra pendência de confirmação
    if decisao == "SOLICITAR_CONFIRMACAO":
        _PENDENTES[transacao_id] = {
            **resultado,
            "resposta_associado": None,
        }

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def aplicar_acao(transacao_id: str, decisao: str, motivo: str = "") -> str:
    """
    Executa e persiste a ação de decisão no sistema autorizador (simulado).
    Deve ser chamada após decidir_transacao.

    Parâmetros
    ----------
    transacao_id : str — identificador da transação
    decisao      : str — ação a executar: APROVAR | APROVAR_COM_ALERTA |
                         SOLICITAR_CONFIRMACAO | BLOQUEAR
    motivo       : str — motivo complementar (opcional, para log)

    Retorna JSON com:
      - transacao_id   : str
      - decisao        : str
      - executada      : bool
      - status_pos     : str  — status resultante no sistema POS simulado
      - aplicado_em    : str  (ISO-8601)
    """
    decisoes_validas = {"APROVAR", "APROVAR_COM_ALERTA", "SOLICITAR_CONFIRMACAO", "BLOQUEAR"}
    if decisao not in decisoes_validas:
        return json.dumps({
            "executada": False,
            "erro": f"Decisão inválida '{decisao}'. Válidas: {sorted(decisoes_validas)}",
        }, ensure_ascii=False, indent=2)

    # Simula o status que seria enviado de volta ao terminal POS
    status_pos_map = {
        "APROVAR": "APROVADA",
        "APROVAR_COM_ALERTA": "APROVADA",
        "SOLICITAR_CONFIRMACAO": "PENDENTE_CONFIRMACAO",
        "BLOQUEAR": "RECUSADA",
    }

    aplicado_em = _agora_iso()
    resultado = {
        "transacao_id": transacao_id,
        "decisao": decisao,
        "executada": True,
        "status_pos": status_pos_map[decisao],
        "motivo": motivo,
        "aplicado_em": aplicado_em,
    }

    # Atualiza pendência se existir
    if transacao_id in _PENDENTES:
        _PENDENTES[transacao_id]["status_pos"] = status_pos_map[decisao]

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def registrar_decisao(
    transacao_id: str,
    associado_id: str,
    decisao: str,
    score_risco: int,
    latencia_ms: int,
    fatores_risco_json: str = "[]",
    observacoes: str = "",
) -> str:
    """
    Registra a decisão no log de auditoria imutável (obrigatório por LGPD e PCI-DSS).
    Cada decisão de bloqueio deve ter registro auditável com todos os fatores de risco.

    Parâmetros
    ----------
    transacao_id       : str — identificador da transação
    associado_id       : str — identificador do associado
    decisao            : str — decisão tomada
    score_risco        : int — score final (0–100)
    latencia_ms        : int — latência total do processamento em ms
    fatores_risco_json : str — JSON array dos fatores de risco explicativos
    observacoes        : str — notas adicionais do analista (opcional)

    Retorna JSON com:
      - auditoria_id   : str  — ID único do registro de auditoria
      - transacao_id   : str
      - registrado_em  : str  (ISO-8601)
      - sucesso        : bool
    """
    try:
        fatores = json.loads(fatores_risco_json)
    except json.JSONDecodeError:
        fatores = []

    registrado_em = _agora_iso()
    auditoria_id = f"AUD-{transacao_id}-{registrado_em[:10]}"

    registro = {
        "auditoria_id": auditoria_id,
        "transacao_id": transacao_id,
        "associado_id": associado_id,
        "decisao": decisao,
        "score_risco": score_risco,
        "latencia_ms": latencia_ms,
        "fatores_risco": fatores,
        "observacoes": observacoes,
        "registrado_em": registrado_em,
    }

    _LOG_AUDITORIA[transacao_id] = registro

    return json.dumps({
        "sucesso": True,
        "auditoria_id": auditoria_id,
        "transacao_id": transacao_id,
        "registrado_em": registrado_em,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def consultar_decisao(transacao_id: str) -> str:
    """
    Recupera o registro de auditoria de uma transação específica.
    Útil para analistas verificarem o histórico de decisões.

    Parâmetros
    ----------
    transacao_id : str — identificador da transação

    Retorna JSON com o registro completo de auditoria ou erro se não encontrado.
    """
    registro = _LOG_AUDITORIA.get(transacao_id)
    if not registro:
        return json.dumps({
            "encontrado": False,
            "transacao_id": transacao_id,
            "erro": "Registro de auditoria não encontrado para esta transação.",
        }, ensure_ascii=False, indent=2)

    return json.dumps({"encontrado": True, **registro}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
