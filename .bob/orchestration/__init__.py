"""
orchestration
=============
Pacote de orquestração do pipeline anti-fraude.

Módulos
-------
skills              : Skills conectadas ao servidor MCP local (SkillRegistry).
notificacao_push    : Payload da notificação push + SimuladorPush.
human_in_the_loop   : GestorHITL — await da decisão humana com timeout.
agent_flow          : AgenteAntiFraude — Gestor de Fronteiras Humano-IA.
pipeline            : Entry point com relatório consolidado.
"""

from orchestration.skills import registry, SKILL_ANALISAR_RISCO, SKILL_EXPLICAR_RISCO
from orchestration.notificacao_push import NotificacaoPush, BotaoResposta, SimuladorPush
from orchestration.human_in_the_loop import GestorHITL, DecisaoHumana, RespostaHumana
from orchestration.agent_flow import (
    AgenteAntiFraude,
    DecisaoTransacao,
    StatusLiquidacao,
    ResultadoPipeline,
)
from orchestration.pipeline import executar_pipeline, executar_pipeline_async

__all__ = [
    # skills
    "registry",
    "SKILL_ANALISAR_RISCO",
    "SKILL_EXPLICAR_RISCO",
    # notificacao
    "NotificacaoPush",
    "BotaoResposta",
    "SimuladorPush",
    # hitl
    "GestorHITL",
    "DecisaoHumana",
    "RespostaHumana",
    # agente
    "AgenteAntiFraude",
    "DecisaoTransacao",
    "StatusLiquidacao",
    "ResultadoPipeline",
    # pipeline
    "executar_pipeline",
    "executar_pipeline_async",
]
