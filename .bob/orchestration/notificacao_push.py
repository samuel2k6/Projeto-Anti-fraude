"""
orchestration/notificacao_push.py
===================================
Modelo de notificação push preventiva para o aplicativo mobile do associado.

Responsabilidade: gerar o payload completo da notificação — título dinâmico
("Sicredi Informa: Detectamos uma compra suspeita de [Valor] em [Local]. Foi você?"),
corpo com a explicação humanizada gerada pela skill ``explicar_risco_fraude``,
e a definição dos dois botões de resposta em tempo real.

Este módulo representa a camada de **Gestor de Fronteiras entre Humanos e IA**:
a IA produz a análise de risco e a explicação, mas a decisão final (aprovar ou
bloquear) pertence ao humano — o associado.

Classes
-------
BotaoResposta   : enum dos botões disponíveis ao associado
NotificacaoPush : payload completo da notificação (texto + botões)
SimuladorPush   : renderiza e "envia" a notificação no terminal (mock)
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Botões de resposta do associado
# ---------------------------------------------------------------------------

class BotaoResposta(str, Enum):
    SIM_FUI_EU       = "SIM_FUI_EU"       # libera a transação
    NAO_BLOQUEAR     = "NAO_BLOQUEAR"     # bloqueia e abre caso de investigação
    TIMEOUT          = "TIMEOUT"           # sem resposta em 2 min → bloqueio automático


# ---------------------------------------------------------------------------
# Payload da notificação push
# ---------------------------------------------------------------------------

@dataclass
class NotificacaoPush:
    """
    Representa o payload completo de uma notificação push preventiva.

    Campos
    ------
    transacao_id       : ID da transação suspeita
    associado_id       : ID do associado destinatário
    titulo_alerta      : manchete principal — "Sicredi Informa: ..."
    explicacao_detalhada: texto humanizado gerado por explicar_risco_fraude
    orientacao         : instrução de ação do associado
    botoes             : lista de BotaoResposta disponíveis
    score_risco        : score original para auditoria
    timestamp_envio    : momento do "disparo" da notificação
    timeout_segundos   : janela de resposta antes do bloqueio automático (padrão: 120s)
    """

    transacao_id:         str
    associado_id:         str
    titulo_alerta:        str
    explicacao_detalhada: str
    orientacao:           str
    botoes:               list[BotaoResposta]
    score_risco:          int
    timestamp_envio:      str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    timeout_segundos:     int = 120

    # ------------------------------------------------------------------
    # Factory: constrói a notificação a partir dos dados da transação
    #          e da explicação gerada pela skill
    # ------------------------------------------------------------------

    @classmethod
    def construir(
        cls,
        transacao:  dict[str, Any],
        explicacao: dict[str, Any],
        score_risco: int,
    ) -> "NotificacaoPush":
        """
        Monta o payload completo da notificação push.

        Parâmetros
        ----------
        transacao  : dict com valor, categoria, latitude/longitude
        explicacao : dict retornado por explicar_risco_fraude
        score_risco: int com o score final calculado
        """
        valor    = transacao.get("valor", 0.0)
        local    = _extrair_local(transacao)
        valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        titulo = (
            f"Sicredi Informa: Detectamos uma compra suspeita "
            f"de {valor_fmt} em {local}. Foi você?"
        )

        return cls(
            transacao_id         = transacao.get("transacao_id", "?"),
            associado_id         = transacao.get("associado_id", "?"),
            titulo_alerta        = titulo,
            explicacao_detalhada = explicacao.get("mensagem_associado", ""),
            orientacao           = explicacao.get("orientacao", ""),
            botoes               = [BotaoResposta.SIM_FUI_EU, BotaoResposta.NAO_BLOQUEAR],
            score_risco          = score_risco,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dict (uso em logs, filas, APIs)."""
        return {
            "transacao_id":          self.transacao_id,
            "associado_id":          self.associado_id,
            "titulo_alerta":         self.titulo_alerta,
            "explicacao_detalhada":  self.explicacao_detalhada,
            "orientacao":            self.orientacao,
            "botoes":                [b.value for b in self.botoes],
            "score_risco":           self.score_risco,
            "timestamp_envio":       self.timestamp_envio,
            "timeout_segundos":      self.timeout_segundos,
        }


# ---------------------------------------------------------------------------
# Extração de local legível a partir dos campos da transação
# ---------------------------------------------------------------------------

def _extrair_local(transacao: dict[str, Any]) -> str:
    """
    Retorna uma string de localização legível para o texto da notificação.
    Prioriza: cidade > categoria > coordenadas > 'local desconhecido'.
    """
    if cidade := transacao.get("cidade"):
        return str(cidade)
    if categoria := transacao.get("categoria"):
        return str(categoria)
    lat = transacao.get("latitude")
    lon = transacao.get("longitude")
    if lat is not None and lon is not None:
        return f"Lat {lat:.4f}, Lon {lon:.4f}"
    return "local desconhecido"


# ---------------------------------------------------------------------------
# Simulador de envio push (mock — em produção: Firebase FCM / APNs / Kafka)
# ---------------------------------------------------------------------------

class SimuladorPush:
    """
    Simula o envio da notificação push para o app mobile do associado.

    Em produção, substituir ``enviar()`` por:
      - Firebase Cloud Messaging (FCM) para Android
      - Apple Push Notification Service (APNs) para iOS
      - Ou publicar em tópico Kafka consumido pelo serviço de notificações
    """

    # Largura da "tela" do simulador no terminal
    LARGURA = 62

    @classmethod
    def enviar(cls, notif: NotificacaoPush) -> None:
        """Imprime a notificação formatada como tela de app mobile."""
        borda   = "═" * cls.LARGURA
        borda_m = "─" * cls.LARGURA

        linhas = [
            "",
            borda,
            cls._centralizar("📱  AVISO DO APP SICREDI"),
            borda_m,
            "",
            # ── Título dinâmico ──────────────────────────────────────────
            *cls._quebrar("⚠️  " + notif.titulo_alerta),
            "",
            borda_m,
            cls._centralizar("── O que aconteceu? ──"),
            borda_m,
            "",
            # ── Explicação humanizada ─────────────────────────────────────
            *cls._quebrar(notif.explicacao_detalhada),
            "",
            borda_m,
            # ── Botões de resposta ───────────────────────────────────────
            cls._centralizar("── O que você quer fazer? ──"),
            "",
            cls._centralizar("[ ✅  Sim, fui eu ]       [ 🚫  Não, bloquear cartão ]"),
            "",
            borda_m,
            # ── Orientação + timeout ──────────────────────────────────────
            *cls._quebrar(notif.orientacao),
            "",
            cls._centralizar(
                f"⏱  Você tem {notif.timeout_segundos} segundos para responder"
            ),
            borda,
            "",
        ]

        print("\n".join(linhas))

    # ------------------------------------------------------------------
    # Helpers de formatação
    # ------------------------------------------------------------------

    @classmethod
    def _centralizar(cls, texto: str) -> str:
        return texto.center(cls.LARGURA)

    @classmethod
    def _quebrar(cls, texto: str) -> list[str]:
        """Quebra texto em linhas de até LARGURA-4 chars com margem."""
        linhas = []
        for paragrafo in texto.split("\n"):
            if not paragrafo.strip():
                linhas.append("")
                continue
            for linha in textwrap.wrap(paragrafo, width=cls.LARGURA - 4):
                linhas.append("  " + linha)
        return linhas
