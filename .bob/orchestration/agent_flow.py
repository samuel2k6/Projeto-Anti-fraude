"""
orchestration/agent_flow.py
============================
Fluxo de agente de orquestração para análise de risco de fraude.

Comportamento configurado — Gestor de Fronteiras entre Humanos e IA:

  1. Quando uma transação entra no pipeline, executa ``analisar_risco_transacao``.
  2. Se score ≤ 70 (risco BAIXO / MÉDIO) → APROVAÇÃO automática pela IA.
  3. Se score > 70 (CRÍTICO) →
       a. Pausa o fluxo de liquidação financeira.
       b. Aciona ``explicar_risco_fraude`` e armazena o texto gerado.
       c. Constrói e "envia" a notificação push com texto dinâmico:
          "Sicredi Informa: Detectamos uma compra suspeita de [Valor] em [Local].
           Foi você?" + explicação humanizada + botões [Sim, fui eu] / [Não, bloquear]
       d. Entra em estado de AWAIT — suspende o fluxo aguardando a decisão humana.
       e. Ao receber a resposta (ou timeout de 120s), aplica a ação final:
            SIM_FUI_EU   → APROVADA (libera liquidação)
            NAO_BLOQUEAR → BLOQUEADA (mantém pausa + abre investigação)
            TIMEOUT      → BLOQUEADA_TIMEOUT (alerta ao associado para contato com agência)

Classes principais:
  - LiquidacaoFinanceira : representa o fluxo de liquidação pausável
  - AgenteAntiFraude     : orquestrador síncrono (score ≤ 70) ou assíncrono (score > 70)
  - ExplicabilidadeStore : armazenamento em memória das explicações geradas
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from orchestration.skills import registry
from orchestration.notificacao_push import NotificacaoPush, BotaoResposta
from orchestration.human_in_the_loop import (
    GestorHITL,
    DecisaoHumana,
    RespostaHumana,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agente-anti-fraude")


# ---------------------------------------------------------------------------
# Enums de estado do fluxo
# ---------------------------------------------------------------------------

class DecisaoTransacao(str, Enum):
    APROVADA              = "APROVADA"               # IA aprovou automaticamente
    APROVADA_PELO_HUMANO  = "APROVADA_PELO_HUMANO"   # associado confirmou
    BLOQUEADA             = "BLOQUEADA"               # associado negou
    BLOQUEADA_TIMEOUT     = "BLOQUEADA_TIMEOUT"       # timeout sem resposta
    PENDENTE_REVISAO      = "PENDENTE_REVISAO"        # aguardando resposta (estado transitório)


class StatusLiquidacao(str, Enum):
    ATIVA   = "ATIVA"
    PAUSADA = "PAUSADA"


# ---------------------------------------------------------------------------
# Resultado completo do pipeline para uma transação
# ---------------------------------------------------------------------------

@dataclass
class ResultadoPipeline:
    transacao_id:      str
    associado_id:      str
    score_risco:       int
    nivel_risco:       str
    decisao:           DecisaoTransacao
    status_liquidacao: StatusLiquidacao
    regras_violadas:   list[dict[str, str]]
    explicacao:        dict[str, Any] | None    = None   # preenchido se score > 70
    notificacao_push:  NotificacaoPush | None   = None   # payload enviado ao associado
    resposta_humana:   RespostaHumana | None    = None   # resposta do associado
    timestamp_processamento: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def resumo(self) -> str:
        _label_decisao = {
            DecisaoTransacao.APROVADA:             "✅ Aprovada automaticamente",
            DecisaoTransacao.APROVADA_PELO_HUMANO: "✅ Aprovada pelo associado",
            DecisaoTransacao.BLOQUEADA:            "🚫 Bloqueada pelo associado",
            DecisaoTransacao.BLOQUEADA_TIMEOUT:    "⏱  Alerta de agência por falta de resposta",
            DecisaoTransacao.PENDENTE_REVISAO:     "⏳ Aguardando resposta do associado",
        }
        _label_liquidacao = {
            StatusLiquidacao.ATIVA:   "✅ Liberada",
            StatusLiquidacao.PAUSADA: "🔒 Pausada",
        }
        _label_botao = {
            "SIM_FUI_EU":   "Confirmou: sou eu",
            "NAO_BLOQUEAR": "Negou: não fui eu",
            "TIMEOUT":      "Não respondeu (expirou)",
        }
        _label_nivel = {
            "BAIXO":   "Baixo",
            "MEDIO":   "Médio",
            "ALTO":    "Alto",
            "CRITICO": "Crítico",
        }

        linhas = [
            f"{'─'*62}",
            f"  Transação  : {self.transacao_id}",
            f"  Associado  : {self.associado_id}",
            f"  Risco      : {self.score_risco}/100  (nível {_label_nivel.get(self.nivel_risco, self.nivel_risco)})",
            f"  Resultado  : {_label_decisao.get(self.decisao, self.decisao.value)}",
            f"  Pagamento  : {_label_liquidacao.get(self.status_liquidacao, self.status_liquidacao.value)}",
        ]
        if self.regras_violadas:
            linhas.append("  Motivos de alerta:")
            for r in self.regras_violadas:
                linhas.append(f"    • {r['descricao']}")
        if self.explicacao:
            linhas.append(f"  Mensagem enviada: {self.explicacao.get('titulo', '')}")
        if self.resposta_humana:
            botao_val = self.resposta_humana.botao_pressionado.value
            linhas.append(
                f"  Resposta   : {_label_botao.get(botao_val, botao_val)}"
            )
        linhas.append(f"{'─'*62}")
        return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Armazenamento das explicações geradas (score > 70)
# ---------------------------------------------------------------------------

class ExplicabilidadeStore:
    """
    Persiste em memória as explicações geradas pela skill ``explicar_risco_fraude``.
    Em produção substituir por Redis / PostgreSQL / objeto S3.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def salvar(self, resultado_pipeline: ResultadoPipeline) -> None:
        if resultado_pipeline.explicacao is None:
            return
        self._store[resultado_pipeline.transacao_id] = {
            "transacao_id":       resultado_pipeline.transacao_id,
            "associado_id":       resultado_pipeline.associado_id,
            "score_risco":        resultado_pipeline.score_risco,
            "nivel_risco":        resultado_pipeline.nivel_risco,
            "titulo":             resultado_pipeline.explicacao.get("titulo"),
            "mensagem_associado": resultado_pipeline.explicacao.get("mensagem_associado"),
            "orientacao":         resultado_pipeline.explicacao.get("orientacao"),
            "regras_violadas":    resultado_pipeline.regras_violadas,
            "decisao_final":      resultado_pipeline.decisao.value,
            "timestamp":          resultado_pipeline.timestamp_processamento,
        }
        log.info(
            "[STORE] Explicação armazenada para transação %s",
            resultado_pipeline.transacao_id,
        )

    def buscar(self, transacao_id: str) -> dict[str, Any] | None:
        return self._store.get(transacao_id)

    def listar_pendentes(self) -> list[dict[str, Any]]:
        return list(self._store.values())


# ---------------------------------------------------------------------------
# Fluxo de Liquidação Financeira
# ---------------------------------------------------------------------------

class LiquidacaoFinanceira:
    """
    Representa o fluxo de liquidação de uma transação.

    Em produção, ``pausar()`` emitiria um evento de back-pressure ao sistema
    autorizador (ex.: Kafka tombstone / REST callback) para manter a transação
    em estado PENDENTE até resolução pelo humano.
    """

    def __init__(self) -> None:
        self._status = StatusLiquidacao.ATIVA

    @property
    def status(self) -> StatusLiquidacao:
        return self._status

    def pausar(self, transacao_id: str, motivo: str) -> None:
        self._status = StatusLiquidacao.PAUSADA
        log.warning(
            "[LIQUIDAÇÃO] 🚫 PAUSADA  transacao=%s  motivo=%s",
            transacao_id, motivo,
        )

    def aprovar(self, transacao_id: str) -> None:
        self._status = StatusLiquidacao.ATIVA
        log.info("[LIQUIDAÇÃO] ✅ APROVADA  transacao=%s", transacao_id)

    def bloquear(self, transacao_id: str, motivo: str) -> None:
        self._status = StatusLiquidacao.PAUSADA
        log.warning(
            "[LIQUIDAÇÃO] 🔒 BLOQUEADA  transacao=%s  motivo=%s",
            transacao_id, motivo,
        )

    def reset(self) -> None:
        self._status = StatusLiquidacao.ATIVA


# ---------------------------------------------------------------------------
# Agente de Orquestração Principal
# ---------------------------------------------------------------------------

class AgenteAntiFraude:
    """
    Agente de orquestração — Gestor de Fronteiras entre Humanos e IA.

    Fluxo completo:
    ┌─ Entrada ──────────────────────────────────────────────────────────┐
    │  transacao (dict)                                                  │
    └────────────────────────────────────────────────────────────────────┘
                 │
                 ▼
    ┌─ Passo 1 ──────────────────────────────────────────────────────────┐
    │  Skill: analisar_risco_transacao                                   │
    │  → { score_risco, nivel_risco, regras_violadas }                  │
    └────────────────────────────────────────────────────────────────────┘
                 │
        ┌────────┴─────────┐
   score ≤ 70           score > 70
        │                   │
        ▼                   ▼
   ✅ APROVAÇÃO       🚫 PAUSA liquidação
   automática (IA)        │
                           ▼
                    Skill: explicar_risco_fraude
                    → { titulo, mensagem_associado, orientacao }
                    → Salva no ExplicabilidadeStore
                           │
                           ▼
                    📱 ENVIA notificação push:
                    "Sicredi Informa: Detectamos uma compra
                     suspeita de [Valor] em [Local]. Foi você?"
                    + explicação humanizada
                    + [ Sim, fui eu ] [ Não, bloquear cartão ]
                           │
                           ▼
                    ⏳ AWAIT decisão humana (timeout: 120s)
                           │
              ┌────────────┼────────────┐
         SIM_FUI_EU   NAO_BLOQUEAR   TIMEOUT
              │              │           │
              ▼              ▼           ▼
         ✅ APROVADA   🚫 BLOQUEADA  ⏱ BLOQUEADA
         _PELO_HUMANO               _TIMEOUT
    """

    LIMIAR_ALTO_RISCO: int = 70

    def __init__(self, timeout_hitl: int = 120) -> None:
        self._liquidacao  = LiquidacaoFinanceira()
        self._store       = ExplicabilidadeStore()
        self._timeout_hitl = timeout_hitl

    # ------------------------------------------------------------------
    # API pública — síncrona (score ≤ 70, sem interação humana)
    # ------------------------------------------------------------------

    def processar(self, transacao: dict[str, Any]) -> ResultadoPipeline:
        """
        Processa uma transação pelo fluxo completo.
        Para transações de risco CRÍTICO (score > 70), delega ao
        fluxo assíncrono via ``processar_async()``.
        """
        self._liquidacao.reset()
        transacao_id = transacao.get("transacao_id", "?")
        log.info("[AGENTE] ▶ Iniciando análise  transacao=%s", transacao_id)

        analise    = self._passo_analisar_risco(transacao)
        score: int = analise["score_risco"]
        nivel: str = analise["nivel_risco"]
        regras     = analise.get("regras_violadas", [])
        assoc_id   = analise.get("associado_id", transacao.get("associado_id", "?"))

        log.info(
            "[AGENTE] Análise concluída  transacao=%s  score=%d  nivel=%s",
            transacao_id, score, nivel,
        )

        if score <= self.LIMIAR_ALTO_RISCO:
            return self._decidir_aprovacao(transacao_id, assoc_id, score, nivel, regras)

        # Score crítico: prepara dados para o fluxo HITL síncrono
        explicacao = self._passo_explicar_risco(analise)
        resultado  = ResultadoPipeline(
            transacao_id       = transacao_id,
            associado_id       = assoc_id,
            score_risco        = score,
            nivel_risco        = nivel,
            decisao            = DecisaoTransacao.PENDENTE_REVISAO,
            status_liquidacao  = StatusLiquidacao.PAUSADA,
            regras_violadas    = regras,
            explicacao         = explicacao,
        )
        self._store.salvar(resultado)
        return resultado

    # ------------------------------------------------------------------
    # API pública — assíncrona com HITL (score > 70)
    # ------------------------------------------------------------------

    async def processar_async(
        self,
        transacao: dict[str, Any],
        modo_demo: bool = False,
    ) -> ResultadoPipeline:
        """
        Coroutine completa do fluxo agêntico com Human-in-the-Loop.

        Parâmetros
        ----------
        transacao  : dict com os campos da transação
        modo_demo  : se True, coleta resposta do terminal (stdin) em vez de
                     aguardar um webhook externo

        Retorna
        -------
        ResultadoPipeline com decisão final após a resposta humana.
        """
        self._liquidacao.reset()
        transacao_id = transacao.get("transacao_id", "?")
        log.info("[AGENTE] ▶ Iniciando análise assíncrona  transacao=%s", transacao_id)

        # ── Passo 1: análise de risco ────────────────────────────────────
        analise    = self._passo_analisar_risco(transacao)
        score: int = analise["score_risco"]
        nivel: str = analise["nivel_risco"]
        regras     = analise.get("regras_violadas", [])
        assoc_id   = analise.get("associado_id", transacao.get("associado_id", "?"))

        log.info(
            "[AGENTE] Análise concluída  transacao=%s  score=%d  nivel=%s",
            transacao_id, score, nivel,
        )

        # ── Passo 2: score ≤ 70 → aprovação automática ──────────────────
        if score <= self.LIMIAR_ALTO_RISCO:
            return self._decidir_aprovacao(transacao_id, assoc_id, score, nivel, regras)

        # ── Passo 3: score > 70 → HITL ──────────────────────────────────
        self._liquidacao.pausar(
            transacao_id,
            motivo=f"score_risco={score} ({nivel}) — aguardando decisão humana",
        )
        log.warning(
            "[AGENTE] ⚠️  CRÍTICO  transacao=%s  score=%d — iniciando HITL",
            transacao_id, score,
        )

        # Aciona a skill de explicabilidade e salva no store
        explicacao = self._passo_explicar_risco(analise)

        resultado_parcial = ResultadoPipeline(
            transacao_id       = transacao_id,
            associado_id       = assoc_id,
            score_risco        = score,
            nivel_risco        = nivel,
            decisao            = DecisaoTransacao.PENDENTE_REVISAO,
            status_liquidacao  = StatusLiquidacao.PAUSADA,
            regras_violadas    = regras,
            explicacao         = explicacao,
        )
        self._store.salvar(resultado_parcial)

        # ── Passo 4: envia notificação push ──────────────────────────────
        gestor = GestorHITL(timeout_segundos=self._timeout_hitl)
        notif  = gestor.enviar_push(transacao, explicacao, score)

        # ── Passo 5: AWAIT da decisão humana ─────────────────────────────
        if modo_demo:
            # No terminal: lança as duas coroutines em paralelo
            # (coletar input + esperar o future ser resolvido)
            resposta = await _aguardar_com_stdin(gestor, transacao_id)
        else:
            # Produção: aguarda webhook/event externo chamar gestor.resolver()
            resposta = await gestor.aguardar_decisao(transacao_id)

        # ── Passo 6: aplica a ação final ─────────────────────────────────
        return self._aplicar_decisao_humana(
            transacao_id, assoc_id, score, nivel, regras,
            explicacao, notif, resposta,
        )

    @property
    def store(self) -> ExplicabilidadeStore:
        return self._store

    # ------------------------------------------------------------------
    # Passos internos
    # ------------------------------------------------------------------

    def _passo_analisar_risco(self, transacao: dict[str, Any]) -> dict[str, Any]:
        resultado = registry.invocar(
            "analisar_risco_transacao",
            transacao_json=json.dumps(transacao, ensure_ascii=False),
        )
        if "erro" in resultado:
            raise ValueError(f"Erro na análise de risco: {resultado['erro']}")
        return resultado

    def _passo_explicar_risco(self, analise: dict[str, Any]) -> dict[str, Any]:
        resultado = registry.invocar(
            "explicar_risco_fraude",
            resultado_analise_json=json.dumps(analise, ensure_ascii=False),
        )
        if "erro" in resultado:
            raise ValueError(f"Erro na explicação: {resultado['erro']}")
        return resultado

    def _decidir_aprovacao(
        self,
        transacao_id: str,
        assoc_id:     str,
        score:        int,
        nivel:        str,
        regras:       list[dict],
    ) -> ResultadoPipeline:
        self._liquidacao.aprovar(transacao_id)
        log.info(
            "[AGENTE] ✅ APROVADO automaticamente  transacao=%s  score=%d",
            transacao_id, score,
        )
        return ResultadoPipeline(
            transacao_id      = transacao_id,
            associado_id      = assoc_id,
            score_risco       = score,
            nivel_risco       = nivel,
            decisao           = DecisaoTransacao.APROVADA,
            status_liquidacao = StatusLiquidacao.ATIVA,
            regras_violadas   = regras,
        )

    def _aplicar_decisao_humana(
        self,
        transacao_id: str,
        assoc_id:     str,
        score:        int,
        nivel:        str,
        regras:       list[dict],
        explicacao:   dict[str, Any],
        notif:        NotificacaoPush,
        resposta:     RespostaHumana,
    ) -> ResultadoPipeline:
        """Resolve o fluxo com base na resposta do associado."""

        if resposta.decisao_final == DecisaoHumana.LIBERADA:
            self._liquidacao.aprovar(transacao_id)
            decisao  = DecisaoTransacao.APROVADA_PELO_HUMANO
            liq      = StatusLiquidacao.ATIVA
            log.info("[AGENTE] ✅ Liberado pelo associado  transacao=%s", transacao_id)

        elif resposta.decisao_final == DecisaoHumana.BLOQUEADA:
            self._liquidacao.bloquear(transacao_id, motivo="associado negou a transação")
            decisao  = DecisaoTransacao.BLOQUEADA
            liq      = StatusLiquidacao.PAUSADA
            log.warning("[AGENTE] 🚫 Bloqueado pelo associado  transacao=%s", transacao_id)

        else:  # BLOQUEADA_TIMEOUT — sem resposta: alerta o associado, não bloqueia
            decisao  = DecisaoTransacao.BLOQUEADA_TIMEOUT
            liq      = StatusLiquidacao.PAUSADA
            log.warning(
                "[AGENTE] ⏱  Timeout sem resposta — associado alertado para contato com agência  transacao=%s",
                transacao_id,
            )

        resultado = ResultadoPipeline(
            transacao_id      = transacao_id,
            associado_id      = assoc_id,
            score_risco       = score,
            nivel_risco       = nivel,
            decisao           = decisao,
            status_liquidacao = liq,
            regras_violadas   = regras,
            explicacao        = explicacao,
            notificacao_push  = notif,
            resposta_humana   = resposta,
        )
        # Atualiza o store com a decisão final
        self._store.salvar(resultado)
        return resultado


# ---------------------------------------------------------------------------
# Helper assíncrono: coleta stdin e aguarda decisão em paralelo
# ---------------------------------------------------------------------------

async def _aguardar_com_stdin(
    gestor: GestorHITL,
    transacao_id: str,
) -> RespostaHumana:
    """
    Executa em paralelo:
      - ``aguardar_decisao()`` — cria o Future e aguarda com timeout
      - ``coletar_resposta_terminal()`` — lê stdin e chama gestor.resolver()

    O stdin resolve o Future interno, fazendo ``aguardar_decisao()`` retornar.
    O resultado da gather[0] é a RespostaHumana gerada por ``aguardar_decisao()``.
    """
    resultados = await asyncio.gather(
        gestor.aguardar_decisao(transacao_id),
        gestor.coletar_resposta_terminal(transacao_id),
    )
    # índice 0 → RespostaHumana de aguardar_decisao
    return resultados[0]
