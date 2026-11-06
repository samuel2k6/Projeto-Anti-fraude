"""
orchestration/human_in_the_loop.py
====================================
Gestor de Fronteiras entre Humanos e IA (Human-in-the-Loop — HITL).

Responsabilidade
----------------
Quando o risco é CRÍTICO (score > 70), o agente NÃO toma a decisão final
sozinho. Em vez disso:

  1. Constrói e "envia" (simula) a notificação push para o associado.
  2. Entra em estado de ``await`` — suspende o fluxo de liquidação e aguarda
     a resposta humana dentro de um timeout configurável.
  3. Ao receber a resposta (ou ao atingir o timeout), resolve o fluxo:
       - SIM_FUI_EU   → libera a liquidação → APROVADA
       - NAO_BLOQUEAR → mantém bloqueio → BLOQUEADA + abre investigação
       - TIMEOUT      → bloqueio automático por segurança

Este módulo usa ``asyncio`` para implementar o await real:
  - ``GestorHITL.aguardar_decisao()`` é uma coroutine que suspende com
    ``asyncio.wait_for`` e resume quando a resposta chega via ``resolver()``.
  - No modo CLI (terminal), a entrada é coletada com ``asyncio.to_thread``
    para não bloquear o loop de eventos.

Classes
-------
DecisaoHumana   : enum com o resultado final após a resposta do associado
EstadoHITL      : enum dos estados internos do gestor
RespostaHumana  : dataclass com a decisão recebida e metadados
GestorHITL      : coordenador assíncrono do fluxo humano-IA
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from orchestration.notificacao_push import BotaoResposta, NotificacaoPush, SimuladorPush

log = logging.getLogger("hitl")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DecisaoHumana(str, Enum):
    LIBERADA      = "LIBERADA"       # associado confirmou — liquidação aprovada
    BLOQUEADA     = "BLOQUEADA"      # associado negou — cartão bloqueado
    BLOQUEADA_TIMEOUT = "BLOQUEADA_TIMEOUT"  # timeout sem resposta


class EstadoHITL(str, Enum):
    AGUARDANDO    = "AGUARDANDO"     # notificação enviada, aguardando resposta
    RESOLVIDO     = "RESOLVIDO"      # resposta recebida


# ---------------------------------------------------------------------------
# Resultado da interação humana
# ---------------------------------------------------------------------------

@dataclass
class RespostaHumana:
    transacao_id:    str
    botao_pressionado: BotaoResposta
    decisao_final:   DecisaoHumana
    timestamp:       str = field(default_factory=lambda: datetime.utcnow().isoformat())
    origem:          str = "associado_mobile"   # "associado_mobile" | "timeout" | "analista"

    def resumo(self) -> str:
        icone = "✅" if self.decisao_final == DecisaoHumana.LIBERADA else "🚫"
        return (
            f"{icone} Resposta humana recebida\n"
            f"   Transação : {self.transacao_id}\n"
            f"   Botão     : {self.botao_pressionado.value}\n"
            f"   Decisão   : {self.decisao_final.value}\n"
            f"   Origem    : {self.origem}\n"
            f"   Timestamp : {self.timestamp}"
        )


# ---------------------------------------------------------------------------
# Gestor de Fronteiras Humano-IA (HITL)
# ---------------------------------------------------------------------------

class GestorHITL:
    """
    Coordena o fluxo de espera pela decisão humana (Human-in-the-Loop).

    Uso típico
    ----------
    gestor = GestorHITL(timeout_segundos=120)

    # 1. Envia a notificação push
    gestor.enviar_push(transacao, explicacao, score_risco)

    # 2. Aguarda a decisão (coroutine — usa await no loop de eventos)
    resposta = await gestor.aguardar_decisao(transacao_id)

    # 3. Aplica a ação final baseada na resposta humana
    """

    def __init__(self, timeout_segundos: int = 120) -> None:
        self.timeout_segundos = timeout_segundos
        self._estado:    EstadoHITL = EstadoHITL.AGUARDANDO
        self._notif:     NotificacaoPush | None = None
        # Future que será resolvido quando o associado responder
        self._future:    asyncio.Future[BotaoResposta] | None = None

    # ------------------------------------------------------------------
    # Passo 1: construir e enviar a notificação push
    # ------------------------------------------------------------------

    def enviar_push(
        self,
        transacao:   dict[str, Any],
        explicacao:  dict[str, Any],
        score_risco: int,
    ) -> NotificacaoPush:
        """
        Constrói o payload da notificação push e simula o envio para o
        aplicativo mobile do associado.

        Retorna o objeto NotificacaoPush para auditoria.
        """
        self._notif = NotificacaoPush.construir(transacao, explicacao, score_risco)
        SimuladorPush.enviar(self._notif)
        log.info(
            "[HITL] 📤 Push enviado  transacao=%s  timeout=%ds",
            self._notif.transacao_id,
            self._notif.timeout_segundos,
        )
        return self._notif

    # ------------------------------------------------------------------
    # Passo 2: await da decisão humana
    # ------------------------------------------------------------------

    async def aguardar_decisao(self, transacao_id: str) -> RespostaHumana:
        """
        Coroutine que suspende o fluxo agêntico e aguarda a resposta do
        associado dentro do timeout configurado.

        Internamente cria um ``asyncio.Future`` que pode ser resolvido por:
          - ``resolver()`` — chamado pelo canal de resposta do app/SMS
          - timeout automático → BotaoResposta.TIMEOUT

        Retorna RespostaHumana com a decisão final.
        """
        loop = asyncio.get_event_loop()
        self._future = loop.create_future()
        self._estado = EstadoHITL.AGUARDANDO

        log.info(
            "[HITL] ⏳ AWAIT iniciado  transacao=%s  timeout=%ds",
            transacao_id, self.timeout_segundos,
        )

        try:
            botao = await asyncio.wait_for(
                asyncio.shield(self._future),
                timeout=self.timeout_segundos,
            )
            decisao = _botao_para_decisao(botao)
            origem  = "associado_mobile"

        except asyncio.TimeoutError:
            log.warning(
                "[HITL] ⏱  TIMEOUT atingido  transacao=%s  — bloqueio automático",
                transacao_id,
            )
            botao   = BotaoResposta.TIMEOUT
            decisao = DecisaoHumana.BLOQUEADA_TIMEOUT
            origem  = "timeout"

        self._estado = EstadoHITL.RESOLVIDO

        resposta = RespostaHumana(
            transacao_id      = transacao_id,
            botao_pressionado = botao,
            decisao_final     = decisao,
            origem            = origem,
        )

        log.info("[HITL] %s", resposta.resumo().replace("\n", " | "))
        return resposta

    # ------------------------------------------------------------------
    # API de resolução (chamada pelo canal de resposta externo)
    # ------------------------------------------------------------------

    def resolver(self, botao: BotaoResposta) -> None:
        """
        Resolve o Future pendente com a resposta do associado.

        Deve ser chamado pelo serviço que recebe o callback do app mobile
        (webhook REST, mensagem Kafka, SMS gateway, etc.).

        Em produção:
            POST /transacoes/{id}/resposta  {"botao": "SIM_FUI_EU"}
            → chama gestor.resolver(BotaoResposta.SIM_FUI_EU)
        """
        if self._future and not self._future.done():
            self._future.set_result(botao)
            log.info("[HITL] 📩 Resposta recebida: %s", botao.value)
        else:
            log.warning("[HITL] resolver() chamado mas Future já concluído ou inexistente.")

    # ------------------------------------------------------------------
    # Modo CLI: coleta a resposta do terminal de forma assíncrona
    # ------------------------------------------------------------------

    async def coletar_resposta_terminal(self, transacao_id: str) -> None:
        """
        No modo CLI/demo, coleta a resposta do operador via stdin sem
        bloquear o event loop (usa asyncio.to_thread).

        Exibe o prompt com os dois botões e resolve o Future interno.
        """
        print("\n" + "─" * 62)
        print("  Esta compra aguarda a sua confirmação.")
        print("─" * 62)
        print(f"  Você tem {self.timeout_segundos} segundos para responder.")
        print()
        print("  [ 1 ]  ✅  Sim, fui eu — pode liberar")
        print("  [ 2 ]  🚫  Não fui eu — bloquear cartão")
        print()

        def _ler_stdin() -> str:
            while True:
                escolha = input("  Digite 1 ou 2: ").strip()
                if escolha in ("1", "2"):
                    return escolha
                print("  Por favor, escolha 1 ou 2.")

        escolha = await asyncio.to_thread(_ler_stdin)
        botao = BotaoResposta.SIM_FUI_EU if escolha == "1" else BotaoResposta.NAO_BLOQUEAR
        self.resolver(botao)


# ---------------------------------------------------------------------------
# Helper: mapeia BotaoResposta → DecisaoHumana
# ---------------------------------------------------------------------------

def _botao_para_decisao(botao: BotaoResposta) -> DecisaoHumana:
    return {
        BotaoResposta.SIM_FUI_EU:   DecisaoHumana.LIBERADA,
        BotaoResposta.NAO_BLOQUEAR: DecisaoHumana.BLOQUEADA,
        BotaoResposta.TIMEOUT:      DecisaoHumana.BLOQUEADA_TIMEOUT,
    }[botao]
