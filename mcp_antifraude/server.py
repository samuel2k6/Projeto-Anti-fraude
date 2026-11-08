"""
Servidor MCP Anti-Fraude
========================
Expõe duas ferramentas:

  - analisar_risco_transacao : avalia uma transação e retorna score + regras violadas.
  - explicar_risco_fraude    : recebe o resultado da análise e, quando score > 70,
                               devolve uma justificativa em linguagem natural simples
                               para o associado do Sicredi entender por que sua
                               transação precisa de validação.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, time
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Instância do servidor
# ---------------------------------------------------------------------------
mcp = FastMCP("anti-fraude")

# ---------------------------------------------------------------------------
# Histórico em memória  {associado_id: [transacao, ...]}
# ---------------------------------------------------------------------------
_HISTORICO: dict[str, list[dict[str, Any]]] = {
    "assoc_001": [
        {
            "transacao_id": "t001",
            "associado_id": "assoc_001",
            "valor": 120.00,
            "categoria": "Supermercados",
            "timestamp": "2026-11-01T08:30:00",
            "latitude": -23.5505,
            "longitude": -46.6333,
        },
        {
            "transacao_id": "t002",
            "associado_id": "assoc_001",
            "valor": 95.50,
            "categoria": "Restaurantes",
            "timestamp": "2026-11-01T12:15:00",
            "latitude": -23.5510,
            "longitude": -46.6340,
        },
        {
            "transacao_id": "t003",
            "associado_id": "assoc_001",
            "valor": 200.00,
            "categoria": "Farmácias",
            "timestamp": "2026-11-01T17:45:00",
            "latitude": -23.5520,
            "longitude": -46.6350,
        },
        {
            "transacao_id": "t004",
            "associado_id": "assoc_001",
            "valor": 80.00,
            "categoria": "Postos de Combustível",
            "timestamp": "2026-11-02T07:00:00",
            "latitude": -23.5500,
            "longitude": -46.6320,
        },
        {
            "transacao_id": "t005",
            "associado_id": "assoc_001",
            "valor": 150.00,
            "categoria": "Supermercados",
            "timestamp": "2026-11-02T10:30:00",
            "latitude": -23.5505,
            "longitude": -46.6333,
        },
    ],
    "assoc_002": [
        {
            "transacao_id": "t101",
            "associado_id": "assoc_002",
            "valor": 500.00,
            "categoria": "Roupas",
            "timestamp": "2026-11-01T09:00:00",
            "latitude": -22.9068,
            "longitude": -43.1729,
        },
        {
            "transacao_id": "t102",
            "associado_id": "assoc_002",
            "valor": 450.00,
            "categoria": "Eletrônicos",
            "timestamp": "2026-11-01T15:00:00",
            "latitude": -22.9070,
            "longitude": -43.1735,
        },
        {
            "transacao_id": "t103",
            "associado_id": "assoc_002",
            "valor": 320.00,
            "categoria": "Restaurantes",
            "timestamp": "2026-11-02T12:00:00",
            "latitude": -22.9065,
            "longitude": -43.1720,
        },
    ],
}

# ---------------------------------------------------------------------------
# Categorias de alto risco
# ---------------------------------------------------------------------------
CATEGORIAS_ALTO_RISCO = {
    "Joalherias",
    "Eletrônicos",
    "Casas de Câmbio",
    "Cassinos",
    "Apostas",
    "Armas e Munições",
    "Artigos de Luxo",
}

# Horário "comercial" considerado normal: 06h às 22h
HORA_NORMAL_INICIO = time(6, 0)
HORA_NORMAL_FIM = time(22, 0)

# Velocidade física impossível (km/h) — acima disso não existe meio de transporte convencional
VELOCIDADE_IMPOSSIVEL_KM = 300.0

# Janelas de tempo para a regra de GPS (dois limiares por origem da transação):
#
#   Transação NACIONAL (pais == "BR"):
#     • < 24h (1440 min)  → alerta CRÍTICO  — deslocamento impossível em extratos nacionais
#     • 24h–48h (1440–2880 min) → alerta MÉDIO — distância suspeita mas com mais margem
#
#   Transação INTERNACIONAL (pais != "BR"):
#     • < 48h (2880 min)  → alerta CRÍTICO  — cobertura de voos internacionais
#     • 48h–96h (2880–5760 min) → alerta MÉDIO — viagem recente ainda suspeita
#
# Fora das janelas máximas a regra não é disparada.
GPS_CRITICO_BR_MIN    = 1440   # 24h — limiar crítico para nacionais
GPS_MEDIO_BR_MIN      = 2880   # 48h — limiar médio para nacionais
GPS_CRITICO_INTL_MIN  = 2880   # 48h — limiar crítico para internacionais
GPS_MEDIO_INTL_MIN    = 5760   # 96h — limiar médio para internacionais

# Multiplicador para "Pico de Transação"
MULTIPLICADOR_PICO = 3.0


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pontos geográficos (fórmula de Haversine)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_ts(ts: str) -> datetime:
    """
    Converte strings de data/hora em objetos datetime nativos do Python.
    Garante o descarte de informações de timezone/offset (.replace(tzinfo=None))
    para evitar erros do tipo 'can't subtract offset-naive and offset-aware datetimes'.
    """
    if not ts:
        return datetime.now().replace(tzinfo=None)
        
    ts_str = str(ts).strip()
    
    # Remove formatações amigáveis do chat (ex: "08/11/2026 às 22:54" ou com sufixos de fuso)
    if " às " in ts_str:
        ts_str = ts_str.replace(" às ", " ")
    if " (" in ts_str:
        ts_str = ts_str.split(" (")[0]
    if " UTC" in ts_str:
        ts_str = ts_str.replace(" UTC", "")
        
    # Tenta parsing para formato ISO padrão (com ou sem fuso horário acoplado)
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.replace(tzinfo=None)
    except ValueError:
        pass

    # Tenta parsing para o formato clássico brasileiro dd/mm/aaaa hh:mm:ss
    formatos = [
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M"
    ]
    for fmt in formatos:
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
            
    # Fallback de segurança para não travar a esteira de análise
    return datetime.now().replace(tzinfo=None)



# ---------------------------------------------------------------------------
# Helpers de enriquecimento de localização e data/hora
# ---------------------------------------------------------------------------

def _nivelar_localizacao(transacao: dict[str, Any]) -> dict[str, Any]:
    """
    Retorna uma cópia da transação com os campos de localização nivelados.

    Se existir um sub-objeto ``transacao["localizacao"]`` (formato datasets),
    seus campos (latitude, longitude, cidade, estado, pais) são promovidos ao
    nível raiz sem sobrescrever valores já presentes.
    """
    loc_aninhada: dict[str, Any] = transacao.get("localizacao") or {}
    if not loc_aninhada:
        return transacao  # já está plano — retorna sem copiar
    plana = dict(transacao)
    for campo in ("latitude", "longitude", "cidade", "estado", "pais"):
        if campo not in plana and campo in loc_aninhada:
            plana[campo] = loc_aninhada[campo]
    return plana


def _resumo_localizacao(transacao: dict[str, Any]) -> str:
    """
    Retorna uma string legível com a localização da transação,
    incluindo cidade, estado e país quando disponíveis.

    Exemplos de saída:
      "Porto Alegre, RS, BR"
      "Tóquio, JP"
      "Lat -23.5505, Lon -46.6333"
      ""   (quando nenhum dado geográfico está presente)
    """
    partes: list[str] = []
    cidade = transacao.get("cidade", "")
    estado = transacao.get("estado", "")
    pais   = transacao.get("pais", "")

    if cidade:
        partes.append(str(cidade))
    if estado:
        partes.append(str(estado))
    if pais:
        partes.append(str(pais))

    if partes:
        return ", ".join(partes)

    # Fallback para coordenadas brutas
    lat = transacao.get("latitude")
    lon = transacao.get("longitude")
    if lat is not None and lon is not None:
        try:
            return f"Lat {float(lat):.4f}, Lon {float(lon):.4f}"
        except (TypeError, ValueError):
            pass

    return ""


def _formatar_data_hora(transacao: dict[str, Any]) -> str:
    """
    Retorna a data e hora formatadas para exibição ao associado e analistas.

    Prioriza ``data_hora_local`` (hora no fuso local da transação) quando
    disponível; caso contrário usa ``timestamp`` (UTC).

    Formato de saída: "DD/MM/AAAA às HH:MM  (fuso_horario)"
    Exemplo: "01/11/2026 às 10:15  (America/Sao_Paulo)"
             "01/11/2026 às 10:15 UTC"
    """
    # Prefere o horário local ao UTC
    ts_str = transacao.get("data_hora_local") or transacao.get("timestamp", "")
    fuso   = transacao.get("fuso_horario", "")

    if not ts_str:
        return ""

    try:
        # Remove sufixo 'Z' e parseia
        ts = datetime.fromisoformat(ts_str.rstrip("Z").split("+")[0].split("-")[0]
                                    if "+" not in ts_str and ts_str.count("-") <= 2
                                    else ts_str.rstrip("Z"))
        data_formatada = ts.strftime("%d/%m/%Y às %H:%M")
    except (ValueError, TypeError):
        return ts_str  # devolve o valor bruto se não conseguir parsear

    sufixo = f"  ({fuso})" if fuso else "  (UTC)" if not transacao.get("data_hora_local") else ""
    return data_formatada + sufixo


# ---------------------------------------------------------------------------
# Regras heurísticas
# ---------------------------------------------------------------------------

def _is_brasil(transacao: dict[str, Any]) -> bool:
    """Retorna True se a transação for no Brasil (pais == 'BR' ou estado preenchido sem pais)."""
    pais = str(transacao.get("pais") or "").strip().upper()
    if pais:
        return pais == "BR"
    # Sem campo pais: considera Brasil se tiver estado ou cidade preenchidos
    return bool(transacao.get("estado") or transacao.get("cidade"))


def _regra_velocidade_impossivel(
    transacao: dict[str, Any],
    historico: list[dict[str, Any]],
) -> tuple[bool, str, str]:
    """
    Regra 1 — Velocidade Impossível (GPS)

    Janela de análise com dois níveis de severidade:

      Nacional (pais == "BR"):
        • intervalo ≤ 24h  → severidade "CRITICO"
        • 24h < intervalo ≤ 48h → severidade "MEDIO"

      Internacional (pais != "BR"):
        • intervalo ≤ 48h  → severidade "CRITICO"
        • 48h < intervalo ≤ 96h → severidade "MEDIO"

    Dispara quando a velocidade implícita entre dois pontos supera
    VELOCIDADE_IMPOSSIVEL_KM * 2 (600 km/h).

    Retorna (disparou, detalhe, severidade).
    severidade é "CRITICO" | "MEDIO" (vazio quando não disparou).
    """
    # Aplana subobjeto "localizacao" antes de acessar os campos
    transacao = _nivelar_localizacao(transacao)
    lat_atual = transacao.get("latitude")
    lon_atual = transacao.get("longitude")

    # Ignora silenciosamente se latitude/longitude ausentes ou de tipo inválido
    if lat_atual is None or lon_atual is None:
        return False, "", ""
    if not isinstance(lat_atual, (int, float)) or not isinstance(lon_atual, (int, float)):
        return False, "", ""

    try:
        ts_atual = _parse_ts(transacao["timestamp"])
    except (ValueError, TypeError):
        return False, "", ""

    nacional = _is_brasil(transacao)
    # Janela máxima para cada origem
    janela_max = GPS_MEDIO_BR_MIN if nacional else GPS_MEDIO_INTL_MIN

    for tx in historico:
        tx = _nivelar_localizacao(tx)
        if "latitude" not in tx or "longitude" not in tx:
            continue
        try:
            ts_ant = _parse_ts(tx["timestamp"])
        except (ValueError, TypeError):
            continue
        diff_min = abs((ts_atual - ts_ant).total_seconds()) / 60.0
        if diff_min > janela_max:
            continue
        dist_km = _haversine(lat_atual, lon_atual, tx["latitude"], tx["longitude"])
        # Velocidade média necessária (km/h)
        velocidade = dist_km / (diff_min / 60.0) if diff_min > 0 else float("inf")
        if velocidade > VELOCIDADE_IMPOSSIVEL_KM * 2:  # > 600 km/h → inviável
            # Determina severidade pelo limiar crítico de cada origem
            limiar_critico = GPS_CRITICO_BR_MIN if nacional else GPS_CRITICO_INTL_MIN
            severidade = "CRITICO" if diff_min <= limiar_critico else "MEDIO"

            # Monta descrição de localização anterior (cidade/estado/país quando disponível)
            loc_ant = _resumo_localizacao(tx)
            loc_ant_txt = f" ({loc_ant})" if loc_ant else ""
            # Monta descrição de localização atual
            loc_atu = _resumo_localizacao(transacao)
            loc_atu_txt = f" ({loc_atu})" if loc_atu else ""
            janela_txt = "24h" if nacional else "48h"
            detalhe = (
                f"Distância de {dist_km:.1f} km em {diff_min:.1f} min "
                f"({velocidade:.0f} km/h) entre a transação {tx['transacao_id']}"
                f"{loc_ant_txt} e esta compra{loc_atu_txt} "
                f"[janela crítica: {janela_txt} | severidade: {severidade}]"
            )
            return True, detalhe, severidade

    return False, "", ""


def _regra_pico_transacao(
    transacao: dict[str, Any],
    historico: list[dict[str, Any]],
) -> tuple[bool, str]:
    """
    Regra 2 — Pico de Transação
    Valor da transação atual é ≥ MULTIPLICADOR_PICO × média histórica.
    """
    if not historico:
        return False, ""

    valores = [tx["valor"] for tx in historico]
    media = sum(valores) / len(valores)
    if media == 0:
        return False, ""

    if transacao["valor"] >= MULTIPLICADOR_PICO * media:
        detalhe = (
            f"Valor R$ {transacao['valor']:.2f} é "
            f"{transacao['valor'] / media:.1f}x acima da média histórica "
            f"(R$ {media:.2f})"
        )
        return True, detalhe

    return False, ""


def _regra_perfil_incomum(
    transacao: dict[str, Any],
) -> tuple[bool, str]:
    """
    Regra 3 — Perfil Incomum
    Categoria de alto risco em horário fora do comercial (antes das 06h ou
    depois das 22h).
    """
    categoria = transacao.get("categoria", "")
    if categoria not in CATEGORIAS_ALTO_RISCO:
        return False, ""

    ts = _parse_ts(transacao["timestamp"])
    hora = ts.time()
    if hora < HORA_NORMAL_INICIO or hora > HORA_NORMAL_FIM:
        detalhe = (
            f"Categoria '{categoria}' em horário incomum "
            f"({ts.strftime('%H:%M')}h — fora de 06h-22h)"
        )
        return True, detalhe

    return False, ""


# ---------------------------------------------------------------------------
# Ferramenta MCP principal
# ---------------------------------------------------------------------------

@mcp.tool()
def analisar_risco_transacao(transacao_json: str) -> str:
    """
    Analisa o risco de fraude de uma transação em tempo real.

    Recebe o JSON de uma transação e compara contra o histórico em memória
    do mesmo associado_id, aplicando três regras heurísticas:

    1. **Velocidade Impossível (GPS)** — compras em localizações geograficamente
       distantes em intervalo de tempo curto.
    2. **Pico de Transação** — valor ≥ 3× a média histórica do associado.
    3. **Perfil Incomum** — categoria de alto risco (Joalherias, Eletrônicos…)
       em horário fora do comercial (antes das 06h ou após as 22h).

    Campos obrigatórios do JSON de transação:
    - transacao_id  (str)
    - associado_id  (str)
    - valor         (float)
    - categoria     (str)
    - timestamp     (str ISO-8601 em UTC, ex: "2026-11-02T23:45:00Z")

    Campos opcionais — enriquecem a análise e as mensagens ao associado:
    - latitude        (float)  — coordenada geográfica
    - longitude       (float)  — coordenada geográfica
    - cidade          (str)    — nome da cidade da transação, ex: "Porto Alegre"
    - estado          (str)    — sigla do estado/UF, ex: "RS"
    - pais            (str)    — código ISO 3166-1 alpha-2, ex: "BR" ou "JP"
    - data_hora_local (str)    — data e hora no fuso do local, ex: "2026-11-02T20:45:00-03:00"
    - fuso_horario    (str)    — fuso IANA, ex: "America/Sao_Paulo"

    Retorna um JSON com:
    - transacao_id    : identificador da transação analisada
    - associado_id    : identificador do associado
    - score_risco     : inteiro de 0 (sem risco) a 100 (altíssimo risco)
    - nivel_risco     : "BAIXO" | "MEDIO" | "ALTO" | "CRITICO"
    - regras_violadas : lista de objetos {regra, descricao, detalhe}
    - historico_usado : número de transações históricas consideradas
    - localizacao_resumo : string legível com cidade/estado/país (quando disponível)
    - data_hora_exibicao : string formatada para exibição ao associado e analistas
    """
    # --- parse ---
    try:
        transacao: dict[str, Any] = json.loads(transacao_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"erro": f"JSON inválido: {exc}"}, ensure_ascii=False)

    if not isinstance(transacao, dict):
        return json.dumps(
            {"erro": "O JSON raiz deve ser um objeto ({}), não um array ou valor primitivo."},
            ensure_ascii=False,
        )

    campos_obrigatorios = ["transacao_id", "associado_id", "valor", "categoria", "timestamp"]
    faltando = [c for c in campos_obrigatorios if c not in transacao]
    if faltando:
        return json.dumps(
            {"erro": f"Campos obrigatórios ausentes: {faltando}"},
            ensure_ascii=False,
        )

    # Valida tipos dos campos obrigatórios antes de processá-los
    nulos = [c for c in campos_obrigatorios if transacao.get(c) is None]
    if nulos:
        return json.dumps(
            {"erro": f"Campos obrigatórios com valor nulo: {nulos}"},
            ensure_ascii=False,
        )

    if not isinstance(transacao["valor"], (int, float)):
        return json.dumps(
            {"erro": f"Campo 'valor' deve ser numérico, recebido: {type(transacao['valor']).__name__}"},
            ensure_ascii=False,
        )

    try:
        _parse_ts(transacao["timestamp"])
    except (ValueError, TypeError):
        return json.dumps(
            {"erro": f"Campo 'timestamp' com formato inválido: '{transacao['timestamp']}'. Use ISO-8601 (ex: 2026-11-02T10:00:00)"},
            ensure_ascii=False,
        )

    assoc_id: str = transacao["associado_id"]
    historico = _HISTORICO.get(assoc_id, [])

    # --- aplicar regras ---
    regras_violadas: list[dict[str, str]] = []
    score = 0

    ok, detalhe, severidade_gps = _regra_velocidade_impossivel(transacao, historico)
    if ok:
        # Score adaptativo: CRITICO = +55 (garante nível CRITICO sozinho),
        # MEDIO = +30 (nível MEDIO isolado, ALTO em combinação)
        score_gps = 55 if severidade_gps == "CRITICO" else 30
        regras_violadas.append(
            {
                "regra": "VELOCIDADE_IMPOSSIVEL",
                "descricao": (
                    "Compra registrada em um lugar muito distante do uso anterior, "
                    "em tempo curto demais para ser possível"
                    if severidade_gps == "CRITICO"
                    else "Compra em localização distante do uso recente — intervalo de tempo suspeito"
                ),
                "detalhe": detalhe,
                "severidade": severidade_gps,
            }
        )
        score += score_gps

    ok, detalhe = _regra_pico_transacao(transacao, historico)
    if ok:
        regras_violadas.append(
            {
                "regra": "PICO_TRANSACAO",
                "descricao": "Valor da compra muito acima do que o associado costuma gastar",
                "detalhe": detalhe,
            }
        )
        score += 35

    ok, detalhe = _regra_perfil_incomum(transacao)
    if ok:
        regras_violadas.append(
            {
                "regra": "PERFIL_INCOMUM",
                "descricao": "Compra em tipo de estabelecimento incomum fora do horário habitual de funcionamento",
                "detalhe": detalhe,
            }
        )
        score += 25

    # cap em 100
    score = min(score, 100)

    # --- nível de risco ---
    if score == 0:
        nivel = "BAIXO"
    elif score <= 35:
        nivel = "MEDIO"
    elif score <= 70:
        nivel = "ALTO"
    else:
        nivel = "CRITICO"

    # Aplana localizacao aninhada para preencher localizacao_resumo e data_hora_exibicao
    transacao_plana = _nivelar_localizacao(transacao)

    resultado = {
        "transacao_id": transacao["transacao_id"],
        "associado_id": assoc_id,
        "score_risco": score,
        "nivel_risco": nivel,
        "regras_violadas": regras_violadas,
        "historico_usado": len(historico),
        "localizacao_resumo": _resumo_localizacao(transacao_plana),
        "data_hora_exibicao": _formatar_data_hora(transacao_plana),
    }

    # Registra a transação no histórico para análises futuras na mesma sessão
    _HISTORICO.setdefault(assoc_id, []).append(transacao)

    return json.dumps(resultado, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Ferramenta de explicação em linguagem natural
# ---------------------------------------------------------------------------

def _gerar_alerta_falso_positivo(
    score: int,
    regras: list[dict[str, str]],
) -> dict[str, str]:
    """
    Gera um alerta de suspeita de falso positivo em linguagem natural para
    scores entre 1 e 70 (níveis MÉDIO e ALTO), onde pelo menos uma regra
    foi violada mas não há certeza suficiente para bloquear a transação.

    Retorna dict com: titulo, mensagem, orientacao.
    """
    nomes_regras = {r["regra"] for r in regras}
    qtd_regras = len(nomes_regras)

    # Mapeia cada regra para uma frase explicativa amigável
    motivos: list[str] = []

    if "PICO_TRANSACAO" in nomes_regras:
        detalhe = next(
            (r["detalhe"] for r in regras if r["regra"] == "PICO_TRANSACAO"), ""
        )
        valor_txt, media_txt = "um valor acima do habitual", "o seu padrão"
        try:
            partes = detalhe.split(" ")
            valor_txt = f"R$ {partes[2]}"
            media_txt = f"R$ {partes[10].strip('()')}"
        except IndexError:
            pass
        motivos.append(
            f"o valor desta compra ({valor_txt}) está acima da sua média habitual "
            f"({media_txt}), o que pode indicar uma compra fora do padrão"
        )

    if "PERFIL_INCOMUM" in nomes_regras:
        detalhe = next(
            (r["detalhe"] for r in regras if r["regra"] == "PERFIL_INCOMUM"), ""
        )
        categoria_txt, hora_txt = "um estabelecimento incomum", "horário incomum"
        try:
            inicio = detalhe.index("'") + 1
            fim = detalhe.index("'", inicio)
            categoria_txt = detalhe[inicio:fim]
            h_inicio = detalhe.index("(") + 1
            h_fim = detalhe.index("h", h_inicio)
            hora_txt = f"{detalhe[h_inicio:h_fim]}h"
        except (ValueError, IndexError):
            pass
        motivos.append(
            f"a compra foi em {categoria_txt} às {hora_txt}, "
            f"um horário pouco comum para esse tipo de estabelecimento"
        )

    if "VELOCIDADE_IMPOSSIVEL" in nomes_regras:
        motivos.append(
            "detectamos uma movimentação geográfica que merece atenção, "
            "embora não seja conclusiva o suficiente para bloquear a transação"
        )

    # Monta o corpo da mensagem
    if not motivos:
        motivo_txt = "identificamos um sinal de alerta leve na transação"
    elif len(motivos) == 1:
        motivo_txt = motivos[0]
    else:
        motivo_txt = "; e ".join(
            [", ".join(motivos[:-1]), motivos[-1]]
        )

    # Gradua o tom conforme o score
    if score <= 35:
        grau = "leve"
        certeza = (
            "Com base no seu histórico, a chance de isso ser uma compra legítima "
            "sua é alta — por isso a transação foi aprovada normalmente."
        )
    else:
        grau = "moderado"
        certeza = (
            "A transação foi aprovada, mas nosso sistema registrou o alerta. "
            "Se você não reconhecer essa compra depois, entre em contato conosco."
        )

    mensagem = (
        f"Sua compra foi aprovada, mas queremos te deixar por dentro: "
        f"nosso sistema notou algo diferente do seu padrão habitual — "
        f"{motivo_txt}.\n\n"
        f"{certeza}\n\n"
        f"Fique tranquilo: isso não significa que sua conta foi invadida. "
        f"Muitas vezes esse aviso aparece em compras completamente normais que fogem "
        f"um pouco do padrão dos dias anteriores. "
        f"Não é necessário fazer nada agora, mas se notar algo estranho no seu extrato, "
        f"entre em contato com a gente."
    )

    if qtd_regras >= 2:
        titulo = "ℹ️ Aviso: notamos algo diferente em mais de uma característica desta compra"
    elif "PICO_TRANSACAO" in nomes_regras:
        titulo = "ℹ️ Aviso: esta compra tem um valor acima do seu padrão habitual"
    elif "PERFIL_INCOMUM" in nomes_regras:
        titulo = "ℹ️ Aviso: compra realizada em horário pouco comum para este tipo de loja"
    else:
        titulo = "ℹ️ Aviso: notamos algo levemente diferente nesta compra"

    orientacao = (
        "Sua compra foi aprovada. Nenhuma ação é necessária agora. "
        "Se você não reconhecer esta transação no seu extrato, acesse o app Sicredi "
        "ou ligue para nossa central de atendimento."
    )

    return {"titulo": titulo, "mensagem": mensagem, "orientacao": orientacao}


@mcp.tool()
def explicar_risco_fraude(resultado_analise_json: str) -> str:
    """
    Gera uma explicação em linguagem natural, sem jargões técnicos, sobre
    por que uma transação foi sinalizada como suspeita.

    Só produz explicação quando o score_risco for superior a 70.
    Para scores ≤ 70 retorna uma mensagem informando que nenhuma validação
    é necessária.

    Parâmetro
    ---------
    resultado_analise_json : str
        JSON retornado por `analisar_risco_transacao`. Campos esperados:
        - transacao_id        (str)
        - associado_id        (str)
        - score_risco         (int,  0–100)
        - nivel_risco         (str)
        - regras_violadas     (list) — cada item com "regra" e "detalhe"
        - localizacao_resumo  (str, opcional) — "Cidade, UF, País"
        - data_hora_exibicao  (str, opcional) — "DD/MM/AAAA às HH:MM (fuso)"

    Retorna JSON com:
    - transacao_id         : str
    - associado_id         : str
    - score_risco          : int
    - requer_validacao     : bool  — True se score > 70 (bloqueio ou confirmação necessária)
    - alerta_falso_positivo: bool  — True se score 1–70 (suspeita leve aprovada, aviso informativo)
    - titulo               : str   — manchete curta para o push/SMS
    - mensagem_associado   : str   — explicação completa em português simples
    - orientacao           : str   — o que o associado deve fazer agora
    """
    # ── parse ────────────────────────────────────────────────────────────────
    try:
        dados: dict[str, Any] = json.loads(resultado_analise_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"erro": f"JSON inválido: {exc}"}, ensure_ascii=False)

    campos = ["transacao_id", "associado_id", "score_risco", "regras_violadas"]
    faltando = [c for c in campos if c not in dados]
    if faltando:
        return json.dumps(
            {"erro": f"Campos ausentes no resultado da análise: {faltando}"},
            ensure_ascii=False,
        )

    score: int = int(dados["score_risco"])
    transacao_id: str = dados["transacao_id"]
    associado_id: str = dados["associado_id"]
    regras: list[dict[str, str]] = dados.get("regras_violadas", [])
    # Campos de enriquecimento de contexto (opcionais)
    localizacao_resumo: str = dados.get("localizacao_resumo", "")
    data_hora_exibicao: str = dados.get("data_hora_exibicao", "")

    # ── score = 0 → aprovado, sem nenhuma regra disparada ───────────────────
    if score == 0:
        return json.dumps({
            "transacao_id": transacao_id,
            "associado_id": associado_id,
            "score_risco": score,
            "requer_validacao": False,
            "alerta_falso_positivo": False,
            "titulo": "Tudo certo com a sua compra!",
            "mensagem_associado": (
                "Verificamos sua transação e está tudo dentro do esperado. "
                "Nenhuma ação é necessária da sua parte."
            ),
            "orientacao": "Nenhuma ação necessária.",
        }, ensure_ascii=False, indent=2)

    # ── score 1–70 → suspeita leve; checagem de possível falso positivo ─────
    if score <= 70:
        alerta = _gerar_alerta_falso_positivo(score, regras)
        return json.dumps({
            "transacao_id": transacao_id,
            "associado_id": associado_id,
            "score_risco": score,
            "requer_validacao": False,
            "alerta_falso_positivo": True,
            "titulo": alerta["titulo"],
            "mensagem_associado": alerta["mensagem"],
            "orientacao": alerta["orientacao"],
        }, ensure_ascii=False, indent=2)

    # ── score > 70 → gera explicação detalhada ───────────────────────────────
    nomes_regras = {r["regra"] for r in regras}

    # Constrói parágrafos individuais por motivo detectado
    paragrafos: list[str] = []

    if "VELOCIDADE_IMPOSSIVEL" in nomes_regras:
        detalhe = next(
            (r["detalhe"] for r in regras if r["regra"] == "VELOCIDADE_IMPOSSIVEL"), ""
        )
        # Extrai distância e tempo do detalhe técnico para humanizar
        # Formato esperado: "Distância de X km em Y min (Z km/h) entre a transação TID (Loc1) e esta compra (Loc2)"
        dist_txt, tempo_txt = "uma grande distância", "pouquíssimo tempo"
        partes = detalhe.split(" ")
        try:
            dist_txt = f"{partes[2]} km"
            tempo_txt = f"{partes[4]} minutos"
        except IndexError:
            pass

        # Contexto de localização da compra suspeita (cidade/estado/país)
        loc_prefixo = f" em {localizacao_resumo}" if localizacao_resumo else ""

        paragrafos.append(
            f"Identificamos que, há muito pouco tempo antes desta compra{loc_prefixo}, "
            f"seu cartão foi usado em um lugar bem diferente deste. "
            f"A distância entre os dois locais é de {dist_txt}, e o intervalo entre as "
            f"duas compras foi de apenas {tempo_txt}. "
            f"Fisicamente, não seria possível estar nos dois lugares nesse espaço de tempo — "
            f"o que levanta a suspeita de que alguém possa estar tentando usar seus dados "
            f"de forma indevida."
        )

    if "PICO_TRANSACAO" in nomes_regras:
        detalhe = next(
            (r["detalhe"] for r in regras if r["regra"] == "PICO_TRANSACAO"), ""
        )
        # Formato esperado: "Valor R$ X é Yx acima da média histórica (R$ Z)"
        valor_txt, media_txt, vezes_txt = "um valor muito alto", "o seu habitual", "muito"
        try:
            partes = detalhe.split(" ")
            valor_txt = f"R$ {partes[2]}"
            vezes_txt = partes[4].replace("x", " vezes")
            media_txt = f"R$ {partes[10].strip('()')}"
        except IndexError:
            pass

        paragrafos.append(
            f"O valor desta compra, de {valor_txt}, está muito acima do que você "
            f"costuma gastar normalmente. Suas compras habituais ficam em torno de "
            f"{media_txt}, e esta é {vezes_txt} maior do que isso. "
            f"Quando um valor tão diferente do padrão aparece de repente, nosso sistema "
            f"entende que pode ser uma tentativa de fraude e pede a sua confirmação "
            f"antes de liberar."
        )

    if "PERFIL_INCOMUM" in nomes_regras:
        detalhe = next(
            (r["detalhe"] for r in regras if r["regra"] == "PERFIL_INCOMUM"), ""
        )
        # Formato esperado: "Categoria 'X' em horário incomum (HH:MMh — fora de 06h-22h)"
        categoria_txt, hora_txt = "uma loja incomum", "um horário incomum"
        try:
            inicio = detalhe.index("'") + 1
            fim = detalhe.index("'", inicio)
            categoria_txt = detalhe[inicio:fim]
            h_inicio = detalhe.index("(") + 1
            h_fim = detalhe.index("h", h_inicio)
            hora_txt = f"{detalhe[h_inicio:h_fim]}h"
        except (ValueError, IndexError):
            pass

        # Usa data_hora_exibicao se disponível para substituir a hora técnica
        hora_exibir = data_hora_exibicao if data_hora_exibicao else f"às {hora_txt}"
        loc_sufixo  = f" em {localizacao_resumo}" if localizacao_resumo else ""

        paragrafos.append(
            f"Esta compra foi feita em {categoria_txt}{loc_sufixo} {hora_exibir}, "
            f"que é um horário fora do comum para esse tipo de estabelecimento. "
            f"Compras em joalherias, lojas de eletrônicos e lugares parecidos realizadas "
            f"de madrugada ou em horários muito incomuns costumam ser um sinal de alerta. "
            f"Por isso, queremos ter certeza de que foi mesmo você quem fez essa compra."
        )

    # ── Monta a mensagem final ────────────────────────────────────────────────
    # Complemento contextual com localização e data/hora quando disponíveis
    contexto_partes: list[str] = []
    if localizacao_resumo:
        contexto_partes.append(f"local: {localizacao_resumo}")
    if data_hora_exibicao:
        contexto_partes.append(f"data/hora: {data_hora_exibicao}")
    contexto_txt = (
        f" (dados da compra — {', '.join(contexto_partes)})"
        if contexto_partes else ""
    )

    intro = (
        f"Olá! Identificamos algo diferente na sua conta e precisamos da sua confirmação "
        f"antes de liberar uma compra recente{contexto_txt}. "
        f"Não se preocupe — seu cartão não foi bloqueado, "
        f"mas precisamos de um momento da sua atenção.\n\n"
        f"Veja o que chamou nossa atenção:\n\n"
    )

    corpo = "\n\n".join(f"• {p}" for p in paragrafos)

    fechamento = (
        "\n\nA segurança da sua conta é nossa prioridade. "
        "Se foi você quem fez essa compra, basta confirmar e ela será liberada imediatamente. "
        "Se não reconhece essa transação, avise-nos agora para que possamos proteger seu cartão."
    )

    mensagem_completa = intro + corpo + fechamento

    # Título curto para push/SMS
    if len(nomes_regras) >= 2:
        titulo = "⚠️ Sua compra precisa de confirmação — identificamos mais de um motivo de alerta"
    elif "VELOCIDADE_IMPOSSIVEL" in nomes_regras:
        titulo = "⚠️ Compra em local distante do seu — precisa de confirmação"
    elif "PICO_TRANSACAO" in nomes_regras:
        titulo = "⚠️ Compra com valor fora do seu padrão — precisa de confirmação"
    else:
        titulo = "⚠️ Compra em horário incomum — precisa de confirmação"

    orientacao = (
        "Responda SIM para confirmar que foi você e liberar a compra. "
        "Responda NÃO para bloquear e acionar nossa equipe de segurança. "
        "Se não responder em 2 minutos, será orientado para se comunicar com sua agência sicredi."
    )

    return json.dumps({
        "transacao_id": transacao_id,
        "associado_id": associado_id,
        "score_risco": score,
        "requer_validacao": True,
        "alerta_falso_positivo": False,
        "titulo": titulo,
        "mensagem_associado": mensagem_completa,
        "orientacao": orientacao,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
