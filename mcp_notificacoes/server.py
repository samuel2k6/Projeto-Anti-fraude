"""
MCP — Notificações e Alertas (F4)
===================================
Gerencia o ciclo completo de comunicação com o associado e com os analistas:
push/SMS para confirmação de transação suspeita, abertura de casos no CRM,
registro de feedback do associado e realimentação do loop de aprendizado.

Ferramentas expostas:
  - enviar_notificacao_associado  → push, SMS ou WhatsApp ao associado
  - aguardar_resposta_associado   → simula espera pela confirmação/negação
  - abrir_caso_analista           → cria ticket de investigação no CRM
  - registrar_feedback_associado  → persiste resposta do associado para retraining
  - listar_casos_abertos          → painel de casos pendentes para analistas
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="notificacoes",
    instructions=(
        "Gerencia notificações ao associado e casos para analistas. "
        "Thresholds alinhados ao mcp_antifraude: "
        "Para score 36–70 (ALTO): envie enviar_notificacao_associado, aguarde com aguardar_resposta_associado. "
        "Para score 71–100 (CRITICO): use abrir_caso_analista diretamente com prioridade ALTA ou CRITICA. "
        "Em caso de timeout (sem resposta), NÃO bloqueie automaticamente — oriente o associado a entrar em contato com sua agência Sicredi. "
        "Sempre chamar registrar_feedback_associado após obter a resposta — alimenta o loop de aprendizado."
    ),
)

# ---------------------------------------------------------------------------
# Estado em memória
# ---------------------------------------------------------------------------

# Notificações enviadas: {notificacao_id: registro}
_NOTIFICACOES: dict[str, dict[str, Any]] = {}

# Respostas dos associados: {transacao_id: resposta}
_RESPOSTAS: dict[str, dict[str, Any]] = {}

# Casos de investigação: {caso_id: registro}
_CASOS: dict[str, dict[str, Any]] = {}

# Feedback para retraining: [{transacao_id, confirmou, timestamp}]
_FEEDBACK_LOOP: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agora() -> datetime:
    return datetime.now(tz=timezone.utc)


def _agora_iso() -> str:
    return _agora().isoformat()


def _mensagem_padrao(transacao: dict[str, Any]) -> str:
    valor = transacao.get("valor", 0.0)
    # Garante que valor é numérico antes de formatar com :.2f
    if not isinstance(valor, (int, float)):
        valor = 0.0
    categoria = transacao.get("categoria") or "estabelecimento desconhecido"
    loc = transacao.get("localizacao")
    cidade = (loc.get("cidade") if isinstance(loc, dict) else None) or "local desconhecido"
    return (
        f"Identificamos uma compra de R$ {valor:.2f} em {categoria} ({cidade}). "
        f"Foi você? Responda SIM para confirmar ou NÃO para bloquear. "
        f"Sem resposta em 2 minutos, entre em contato com sua agência Sicredi."
    )


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

@mcp.tool()
def enviar_notificacao_associado(
    associado_id: str,
    transacao_id: str,
    mensagem: str,
    canal: str = "push",
) -> str:
    """
    Envia uma notificação ao associado solicitando confirmação de uma transação suspeita.

    Parâmetros
    ----------
    associado_id  : str — identificador do associado
    transacao_id  : str — identificador da transação que requer confirmação
    mensagem      : str — texto da notificação (linguagem clara e não-técnica)
    canal         : str — canal de envio: "push" | "sms" | "whatsapp" (padrão: "push")

    Retorna JSON com:
      - notificacao_id  : str
      - associado_id    : str
      - transacao_id    : str
      - canal           : str
      - enviado         : bool
      - enviado_em      : str (ISO-8601)
      - expira_em       : str (ISO-8601) — timeout de 2 minutos
      - mensagem        : str
    """
    canais_validos = {"push", "sms", "whatsapp"}
    canal = canal.lower().strip()
    if canal not in canais_validos:
        canal = "push"

    notificacao_id = f"NOT-{transacao_id}-{canal.upper()}"
    enviado_em = _agora()
    expira_em = enviado_em + timedelta(seconds=120)

    registro = {
        "notificacao_id": notificacao_id,
        "associado_id": associado_id,
        "transacao_id": transacao_id,
        "canal": canal,
        "mensagem": mensagem,
        "enviado": True,
        "enviado_em": enviado_em.isoformat(),
        "expira_em": expira_em.isoformat(),
        "resposta": None,
    }
    _NOTIFICACOES[notificacao_id] = registro

    return json.dumps({
        "notificacao_id": notificacao_id,
        "associado_id": associado_id,
        "transacao_id": transacao_id,
        "canal": canal,
        "enviado": True,
        "enviado_em": enviado_em.isoformat(),
        "expira_em": expira_em.isoformat(),
        "mensagem": mensagem,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def aguardar_resposta_associado(
    transacao_id: str,
    timeout_segundos: int = 120,
    simular_resposta: str = "timeout",
) -> str:
    """
    Simula a espera pela resposta do associado a uma notificação de confirmação.
    Em produção, este endpoint seria um webhook ou long-poll. Aqui simula o resultado.

    Parâmetros
    ----------
    transacao_id     : str — identificador da transação aguardando confirmação
    timeout_segundos : int — segundos de espera máxima (padrão: 120)
    simular_resposta : str — para simulação: "confirmar" | "negar" | "timeout"
                             (em produção, este campo não existe — a resposta vem do associado)

    Retorna JSON com:
      - transacao_id   : str
      - resposta       : str  ("CONFIRMADA" | "NEGADA" | "TIMEOUT")
      - confirmou      : bool | null
      - respondido_em  : str | null
      - acao_resultante: str  — decisão final após a resposta
    """
    timeout_segundos = max(1, min(timeout_segundos, 300))
    simular = simular_resposta.lower().strip()

    respondido_em = _agora_iso()

    if simular == "confirmar":
        resposta = "CONFIRMADA"
        confirmou = True
        acao = "APROVAR"
    elif simular == "negar":
        resposta = "NEGADA"
        confirmou = False
        acao = "BLOQUEAR"
    else:
        resposta = "TIMEOUT"
        confirmou = None
        acao = "ALERTAR_AGENCIA"  # sem resposta → orienta contato com a agência

    _RESPOSTAS[transacao_id] = {
        "transacao_id": transacao_id,
        "resposta": resposta,
        "confirmou": confirmou,
        "respondido_em": respondido_em if confirmou is not None else None,
        "acao_resultante": acao,
    }

    return json.dumps({
        "transacao_id": transacao_id,
        "resposta": resposta,
        "confirmou": confirmou,
        "respondido_em": respondido_em if confirmou is not None else None,
        "acao_resultante": acao,
        "descricao": (
            "Associado confirmou a transação." if confirmou is True
            else "Associado negou a transação — bloqueio executado."
            if confirmou is False
            else f"Timeout de {timeout_segundos}s atingido sem resposta — entre em contato com sua agência Sicredi."
        ),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def abrir_caso_analista(
    transacao_id: str,
    associado_id: str,
    score_risco: int,
    regras_violadas_json: str,
    prioridade: str = "ALTA",
    observacoes: str = "",
) -> str:
    """
    Cria um caso de investigação no CRM para análise humana.
    Deve ser chamada para score ≥ 36 (ALTO) ou ≥ 71 (CRITICO), ou quando associado nega/não responde.

    Parâmetros
    ----------
    transacao_id         : str — identificador da transação
    associado_id         : str — identificador do associado
    score_risco          : int — score de risco (0–100)
    regras_violadas_json : str — JSON array das regras violadas
    prioridade           : str — "BAIXA" | "MEDIA" | "ALTA" | "CRITICA" (padrão: "ALTA")
    observacoes          : str — contexto adicional para o analista (opcional)

    Retorna JSON com:
      - caso_id       : str
      - transacao_id  : str
      - prioridade    : str
      - status        : str  ("ABERTO")
      - aberto_em     : str  (ISO-8601)
      - analista_sla  : str  — prazo máximo para análise
    """
    prioridades_validas = {"BAIXA", "MEDIA", "ALTA", "CRITICA"}
    prioridade = prioridade.upper().strip()
    if prioridade not in prioridades_validas:
        prioridade = "ALTA"

    try:
        regras = json.loads(regras_violadas_json)
    except json.JSONDecodeError:
        regras = []

    sla_map = {
        "BAIXA": "72 horas",
        "MEDIA": "24 horas",
        "ALTA": "4 horas",
        "CRITICA": "30 minutos",
    }

    caso_id = f"CASO-{uuid.uuid4().hex[:8].upper()}"
    aberto_em = _agora_iso()

    registro = {
        "caso_id": caso_id,
        "transacao_id": transacao_id,
        "associado_id": associado_id,
        "score_risco": score_risco,
        "prioridade": prioridade,
        "status": "ABERTO",
        "regras_violadas": regras,
        "observacoes": observacoes,
        "aberto_em": aberto_em,
        "analista_sla": sla_map[prioridade],
        "analista_responsavel": None,
        "fechado_em": None,
        "resolucao": None,
    }
    _CASOS[caso_id] = registro

    return json.dumps({
        "caso_id": caso_id,
        "transacao_id": transacao_id,
        "associado_id": associado_id,
        "prioridade": prioridade,
        "status": "ABERTO",
        "aberto_em": aberto_em,
        "analista_sla": sla_map[prioridade],
        "mensagem": f"Caso {caso_id} aberto com prioridade {prioridade}. SLA: {sla_map[prioridade]}.",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def registrar_feedback_associado(
    transacao_id: str,
    confirmou: bool,
    canal_resposta: str = "push",
) -> str:
    """
    Persiste a resposta do associado no feedback loop para retraining do modelo.
    Deve ser chamada após toda interação de confirmação/negação do associado.

    Parâmetros
    ----------
    transacao_id  : str  — identificador da transação
    confirmou     : bool — True se o associado confirmou (legítima), False se negou (fraude)
    canal_resposta: str  — canal pelo qual o associado respondeu

    Retorna JSON com:
      - sucesso        : bool
      - transacao_id   : str
      - label          : str  ("LEGITIMA" | "FRAUDE") — label para retraining
      - registrado_em  : str  (ISO-8601)
      - total_feedbacks: int  — total acumulado de feedbacks na sessão
    """
    registrado_em = _agora_iso()
    label = "LEGITIMA" if confirmou else "FRAUDE"

    entrada = {
        "transacao_id": transacao_id,
        "confirmou": confirmou,
        "label": label,
        "canal_resposta": canal_resposta,
        "registrado_em": registrado_em,
    }
    _FEEDBACK_LOOP.append(entrada)

    return json.dumps({
        "sucesso": True,
        "transacao_id": transacao_id,
        "label": label,
        "registrado_em": registrado_em,
        "total_feedbacks": len(_FEEDBACK_LOOP),
        "mensagem": f"Feedback '{label}' registrado. Será usado no próximo ciclo de retraining.",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def listar_casos_abertos(prioridade_minima: str = "BAIXA") -> str:
    """
    Lista os casos de investigação abertos, filtrados por prioridade mínima.
    Útil para o painel do analista — ordenado por prioridade decrescente.

    Parâmetros
    ----------
    prioridade_minima : str — filtro: "BAIXA" | "MEDIA" | "ALTA" | "CRITICA"

    Retorna JSON com:
      - total_abertos : int
      - casos         : list — casos ordenados por prioridade (CRITICA primeiro)
    """
    ordem = {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAIXA": 3}
    minima = prioridade_minima.upper().strip()
    nivel_minimo = ordem.get(minima, 3)

    abertos = [
        c for c in _CASOS.values()
        if c["status"] == "ABERTO" and ordem.get(c["prioridade"], 3) <= nivel_minimo
    ]
    abertos_ord = sorted(abertos, key=lambda c: ordem.get(c["prioridade"], 3))

    return json.dumps({
        "total_abertos": len(abertos_ord),
        "prioridade_minima_filtro": minima,
        "casos": abertos_ord,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
