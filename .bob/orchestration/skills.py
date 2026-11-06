"""
orchestration/skills.py
=======================
Conecta o servidor MCP local ``mcp_antifraude`` e expõe suas ferramentas como
Skills reutilizáveis em um ambiente de orquestração (IBM watsonx Orchestrate /
similar).

Cada Skill encapsula:
  - nome       : identificador único dentro do orquestrador
  - descricao  : metadado legível pelo LLM do orquestrador para selecionar a skill
  - parametros : esquema JSON-Schema dos parâmetros de entrada
  - executar() : chama a ferramenta MCP e retorna o resultado como dict Python

Transporte
----------
As funções MCP são importadas diretamente do módulo ``mcp_antifraude.server``
(importação Python direta, sem subprocess).  Esse é o mesmo padrão utilizado
pelos testes do projeto (``mcp_antifraude/test_server.py``).

Em produção com IBM watsonx Orchestrate, o ``SkillRegistry`` pode ser adaptado
para chamar a API REST do servidor MCP registrado no ``.bob/mcp.json``
(entrada ``anti-fraude``) — basta substituir ``executar()`` por uma chamada HTTP.

A classe ``SkillRegistry`` mantém o catálogo e oferece ``invocar(skill, params)``
para uso direto pelo agente de orquestração.
"""

from __future__ import annotations

import json
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Garante que mcp_antifraude seja importável independente de como o módulo
# é invocado (python -m orchestration.pipeline ou import direto).
# ---------------------------------------------------------------------------
_BASE_DIR = Path(__file__).resolve().parent.parent
_ANTIFRAUDE_DIR = _BASE_DIR / "mcp_antifraude"
if str(_ANTIFRAUDE_DIR) not in sys.path:
    sys.path.insert(0, str(_ANTIFRAUDE_DIR))

from server import analisar_risco_transacao as _mcp_analisar  # type: ignore
from server import explicar_risco_fraude as _mcp_explicar      # type: ignore


# ---------------------------------------------------------------------------
# Modelo de Skill
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """Representa uma skill conectada ao orquestrador."""

    nome: str
    descricao: str
    parametros: dict[str, Any]          # JSON-Schema dos parâmetros
    fn: Callable[..., str] = field(repr=False)   # função MCP subjacente

    def executar(self, **kwargs: Any) -> dict[str, Any]:
        """
        Invoca a ferramenta MCP correspondente e retorna o resultado como dict.

        Argumentos dict são automaticamente serializados para JSON string,
        conforme esperado pelas ferramentas MCP do servidor.
        """
        argumentos: dict[str, Any] = {}
        for chave, valor in kwargs.items():
            if isinstance(valor, dict):
                argumentos[chave] = json.dumps(valor, ensure_ascii=False)
            else:
                argumentos[chave] = valor

        resultado_str: str = self.fn(**argumentos)
        return json.loads(resultado_str)


# ---------------------------------------------------------------------------
# Definições das Skills
# ---------------------------------------------------------------------------

SKILL_ANALISAR_RISCO = Skill(
    nome="analisar_risco_transacao",
    descricao=textwrap.dedent("""\
        Avalia o risco de fraude de uma transação financeira em tempo real.
        Aplica três regras heurísticas: Velocidade Impossível (GPS),
        Pico de Transação (valor 3× acima da média histórica) e Perfil Incomum
        (categoria de alto risco em horário fora do comercial).
        Retorna score_risco (0–100), nivel_risco e regras_violadas.
        Use esta skill como PRIMEIRO passo do pipeline de análise.
    """),
    parametros={
        "type": "object",
        "properties": {
            "transacao_json": {
                "type": "string",
                "description": (
                    "JSON serializado da transação com campos: transacao_id, "
                    "associado_id, valor, categoria, timestamp "
                    "(+ latitude/longitude opcionais)"
                ),
            }
        },
        "required": ["transacao_json"],
    },
    fn=_mcp_analisar,
)

SKILL_EXPLICAR_RISCO = Skill(
    nome="explicar_risco_fraude",
    descricao=textwrap.dedent("""\
        Gera uma explicação em linguagem natural, sem jargões técnicos,
        sobre por que uma transação foi sinalizada como suspeita.
        Deve ser invocada SOMENTE quando score_risco > 70.
        Retorna titulo, mensagem_associado e orientacao prontos para
        envio ao associado via push/SMS.
    """),
    parametros={
        "type": "object",
        "properties": {
            "resultado_analise_json": {
                "type": "string",
                "description": "JSON retornado por analisar_risco_transacao",
            }
        },
        "required": ["resultado_analise_json"],
    },
    fn=_mcp_explicar,
)


# ---------------------------------------------------------------------------
# Registro de Skills (catálogo do orquestrador)
# ---------------------------------------------------------------------------

class SkillRegistry:
    """Catálogo de skills disponíveis para o agente de orquestração."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def registrar(self, skill: Skill) -> None:
        self._skills[skill.nome] = skill

    def listar(self) -> list[dict[str, Any]]:
        """Retorna metadados de cada skill (para o LLM do orquestrador)."""
        return [
            {"nome": s.nome, "descricao": s.descricao, "parametros": s.parametros}
            for s in self._skills.values()
        ]

    def invocar(self, nome_skill: str, **kwargs: Any) -> dict[str, Any]:
        if nome_skill not in self._skills:
            raise ValueError(
                f"Skill '{nome_skill}' não registrada. "
                f"Disponíveis: {list(self._skills)}"
            )
        return self._skills[nome_skill].executar(**kwargs)


# ---------------------------------------------------------------------------
# Instância global do registry — importada pelo agente
# ---------------------------------------------------------------------------
registry = SkillRegistry()
registry.registrar(SKILL_ANALISAR_RISCO)
registry.registrar(SKILL_EXPLICAR_RISCO)
