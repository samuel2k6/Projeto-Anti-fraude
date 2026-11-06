"""
MCP — Lista Negra (F-004)
==========================
Verifica estabelecimentos, BINs e países contra listas de alto risco.
É o único gatilho de bloqueio imediato (sub_score = 1.0) sem necessidade
de confirmação do associado, conforme fraud_rules.json.

Ferramentas expostas:
  - verificar_estabelecimento → verifica MCC e CNPJ contra blacklists
  - verificar_bin             → verifica se o BIN do cartão está comprometido
  - verificar_pais            → verifica se o país da transação é de alto risco
  - adicionar_a_blacklist     → adiciona novo registro às listas (uso pelos analistas)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="lista-negra",
    instructions=(
        "Verifica BINs, MCCs, CNPJs e países contra listas de alto risco de fraude (F-004). "
        "Sempre consulte verificar_estabelecimento e verificar_pais antes de aprovar "
        "transações internacionais ou em categorias sensíveis. "
        "Um match em blacklist_critica retorna sub_score=1.0 → bloqueio imediato."
    ),
)

# ---------------------------------------------------------------------------
# Listas negras em memória (seed baseado no fraud_rules.json)
# ---------------------------------------------------------------------------

# MCCs de alto risco (Merchant Category Codes)
_BLACKLIST_MCC: dict[str, dict[str, str]] = {
    "7995": {"descricao": "Apostas / Cassinos / Jogos de Azar", "nivel": "critica"},
    "5933": {"descricao": "Penhor / Casa de Penhores", "nivel": "critica"},
    "6050": {"descricao": "Quase-Dinheiro — Instituição Financeira", "nivel": "critica"},
    "6051": {"descricao": "Quase-Dinheiro — Não-Financeira (Cripto, Câmbio)", "nivel": "critica"},
    "4829": {"descricao": "Transferência de Dinheiro / Wire Transfer", "nivel": "moderada"},
    "6010": {"descricao": "Saque Manual — Banco", "nivel": "moderada"},
    "6011": {"descricao": "Saque Automático (ATM)", "nivel": "moderada"},
    "5912": {"descricao": "Farmácias — uso em combos de fraude", "nivel": "baixa"},
}

# BINs comprometidos (primeiros 6 dígitos do cartão)
_BLACKLIST_BIN: dict[str, dict[str, str]] = {
    "411111": {"descricao": "BIN de teste — nunca deve aparecer em produção", "nivel": "critica"},
    "555555": {"descricao": "BIN clonado — lote reportado em 2026-10", "nivel": "critica"},
    "490200": {"descricao": "BIN comprometido — vazamento confirmado", "nivel": "critica"},
    "438857": {"descricao": "BIN com histórico de chargebacks elevado", "nivel": "moderada"},
    "402360": {"descricao": "BIN associado a fraude de identidade", "nivel": "moderada"},
}

# Países de alto risco (ISO 3166-1 alpha-2)
_BLACKLIST_PAIS: dict[str, dict[str, str]] = {
    "NG": {"descricao": "Nigéria — alto índice de fraude de cartão", "nivel": "critica"},
    "KP": {"descricao": "Coreia do Norte — sanções internacionais", "nivel": "critica"},
    "IR": {"descricao": "Irã — sanções internacionais", "nivel": "critica"},
    "BY": {"descricao": "Belarus — restrições regulatórias", "nivel": "moderada"},
    "MM": {"descricao": "Myanmar — alto risco pós-golpe 2021", "nivel": "moderada"},
    "VE": {"descricao": "Venezuela — instabilidade financeira elevada", "nivel": "moderada"},
    "XX": {"descricao": "País desconhecido / não mapeado", "nivel": "moderada"},
}

# CNPJs/estabelecimentos denunciados
_BLACKLIST_CNPJ: dict[str, dict[str, str]] = {
    "00.000.000/0001-91": {"descricao": "CNPJ de teste — nunca válido em produção", "nivel": "critica"},
    "12.345.678/0001-99": {"descricao": "Estabelecimento com múltiplos chargebacks", "nivel": "critica"},
    "98.765.432/0001-10": {"descricao": "Suspeito de lavagem de dinheiro — em investigação", "nivel": "moderada"},
}

# Mapeamento de sub_score por nível
_SUB_SCORE_POR_NIVEL = {
    "critica": 1.0,
    "moderada": 0.70,
    "baixa": 0.50,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agora_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _resultado_limpo(campo: str, valor: str) -> dict[str, Any]:
    return {
        "encontrado": False,
        "nivel": None,
        "sub_score": 0.0,
        "descricao": None,
        campo: valor,
        "verificado_em": _agora_iso(),
    }


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

@mcp.tool()
def verificar_estabelecimento(mcc_code: str, cnpj: str = "") -> str:
    """
    Verifica se o código MCC ou CNPJ do estabelecimento consta em listas de alto risco.

    Parâmetros
    ----------
    mcc_code : str — código MCC de 4 dígitos (ex: "7995")
    cnpj     : str — CNPJ do estabelecimento, opcional (ex: "12.345.678/0001-99")

    Retorna JSON com:
      - encontrado   : bool
      - nivel        : str | null  ("critica" | "moderada" | "baixa")
      - sub_score    : float (1.0 / 0.70 / 0.50 / 0.0)
      - descricao    : str | null
      - mcc_code     : str
      - cnpj         : str
      - verificado_em: str (ISO-8601)
    """
    # Normaliza para string segura — evita AttributeError se vier None ou outro tipo
    mcc_code = str(mcc_code).strip() if mcc_code is not None else ""
    cnpj = str(cnpj).strip() if cnpj is not None else ""

    resultado: dict[str, Any] = {
        "encontrado": False,
        "nivel": None,
        "sub_score": 0.0,
        "descricao": None,
        "mcc_code": mcc_code,
        "cnpj": cnpj,
        "verificado_em": _agora_iso(),
    }

    # Verifica MCC primeiro (prioridade sobre CNPJ)
    if mcc_code in _BLACKLIST_MCC:
        entrada = _BLACKLIST_MCC[mcc_code]
        resultado.update({
            "encontrado": True,
            "nivel": entrada["nivel"],
            "sub_score": _SUB_SCORE_POR_NIVEL[entrada["nivel"]],
            "descricao": f"MCC {mcc_code}: {entrada['descricao']}",
            "fonte": "blacklist_mcc",
        })
        return json.dumps(resultado, ensure_ascii=False, indent=2)

    # Verifica CNPJ
    if cnpj and cnpj in _BLACKLIST_CNPJ:
        entrada = _BLACKLIST_CNPJ[cnpj]
        resultado.update({
            "encontrado": True,
            "nivel": entrada["nivel"],
            "sub_score": _SUB_SCORE_POR_NIVEL[entrada["nivel"]],
            "descricao": f"CNPJ {cnpj}: {entrada['descricao']}",
            "fonte": "blacklist_cnpj",
        })

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def verificar_bin(bin_numero: str) -> str:
    """
    Verifica se o BIN (Bank Identification Number — primeiros 6 dígitos do cartão)
    consta na lista de BINs comprometidos.

    Parâmetros
    ----------
    bin_numero : str — primeiros 6 dígitos do número do cartão (ex: "411111")

    Retorna JSON com:
      - encontrado   : bool
      - nivel        : str | null
      - sub_score    : float
      - descricao    : str | null
      - bin_numero   : str
      - verificado_em: str (ISO-8601)
    """
    # Normaliza para string segura antes de qualquer operação de string
    if not isinstance(bin_numero, str):
        bin_numero = str(bin_numero) if bin_numero is not None else ""
    bin_limpo = bin_numero.replace(" ", "").replace("-", "")[:6]

    resultado: dict[str, Any] = {
        "encontrado": False,
        "nivel": None,
        "sub_score": 0.0,
        "descricao": None,
        "bin_numero": bin_limpo,
        "verificado_em": _agora_iso(),
    }

    if bin_limpo in _BLACKLIST_BIN:
        entrada = _BLACKLIST_BIN[bin_limpo]
        resultado.update({
            "encontrado": True,
            "nivel": entrada["nivel"],
            "sub_score": _SUB_SCORE_POR_NIVEL[entrada["nivel"]],
            "descricao": entrada["descricao"],
        })

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def verificar_pais(codigo_iso: str) -> str:
    """
    Verifica se o país da transação consta na lista de países de alto risco.

    Parâmetros
    ----------
    codigo_iso : str — código ISO 3166-1 alpha-2 do país (ex: "BR", "NG", "KP")

    Retorna JSON com:
      - encontrado   : bool
      - nivel        : str | null
      - sub_score    : float
      - descricao    : str | null
      - codigo_iso   : str
      - verificado_em: str (ISO-8601)
    """
    # Normaliza para string segura — evita AttributeError se vier None
    if not isinstance(codigo_iso, str):
        codigo_iso = str(codigo_iso) if codigo_iso is not None else ""
    codigo = codigo_iso.upper().strip()

    resultado: dict[str, Any] = {
        "encontrado": False,
        "nivel": None,
        "sub_score": 0.0,
        "descricao": None,
        "codigo_iso": codigo,
        "verificado_em": _agora_iso(),
    }

    if codigo in _BLACKLIST_PAIS:
        entrada = _BLACKLIST_PAIS[codigo]
        resultado.update({
            "encontrado": True,
            "nivel": entrada["nivel"],
            "sub_score": _SUB_SCORE_POR_NIVEL[entrada["nivel"]],
            "descricao": entrada["descricao"],
        })

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def adicionar_a_blacklist(tipo: str, valor: str, descricao: str, nivel: str = "moderada") -> str:
    """
    Adiciona um novo registro a uma das listas negras. Uso exclusivo por analistas
    após confirmação de fraude.

    Parâmetros
    ----------
    tipo      : str — tipo de lista: "mcc" | "bin" | "pais" | "cnpj"
    valor     : str — o valor a ser adicionado (ex: "7995", "490200", "NG", "12.345.678/0001-99")
    descricao : str — motivo ou descrição do risco
    nivel     : str — nível de risco: "critica" | "moderada" | "baixa" (padrão: "moderada")

    Retorna JSON com:
      - sucesso    : bool
      - tipo       : str
      - valor      : str
      - nivel      : str
      - adicionado_em : str (ISO-8601)
    """
    tipo = tipo.lower().strip()
    nivel = nivel.lower().strip()

    if nivel not in _SUB_SCORE_POR_NIVEL:
        return json.dumps({
            "sucesso": False,
            "erro": f"Nível inválido '{nivel}'. Use: critica, moderada ou baixa.",
        }, ensure_ascii=False, indent=2)

    entrada = {"descricao": descricao, "nivel": nivel}

    if tipo == "mcc":
        _BLACKLIST_MCC[valor] = entrada
    elif tipo == "bin":
        _BLACKLIST_BIN[valor[:6]] = entrada
    elif tipo == "pais":
        _BLACKLIST_PAIS[valor.upper()] = entrada
    elif tipo == "cnpj":
        _BLACKLIST_CNPJ[valor] = entrada
    else:
        return json.dumps({
            "sucesso": False,
            "erro": f"Tipo inválido '{tipo}'. Use: mcc, bin, pais ou cnpj.",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "sucesso": True,
        "tipo": tipo,
        "valor": valor,
        "nivel": nivel,
        "descricao": descricao,
        "adicionado_em": _agora_iso(),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
