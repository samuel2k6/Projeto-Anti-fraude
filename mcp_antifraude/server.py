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

# GPS — limiares de velocidade (km/h)
# > 600 km/h: fisicamente impossível por via terrestre/aérea doméstica
# > 200 km/h: improvável para deslocamento inter-estadual em < 2h (suspeito)
# > 80  km/h: detecta mudança de estado em janela curta (alerta leve)
VELOCIDADE_CRITICA_KMH  = 600.0   # certeza de fraude
VELOCIDADE_SUSPEITA_KMH = 200.0   # muito improvável
VELOCIDADE_ALERTA_KMH   =  80.0   # mudança de estado suspeita

# Janela de tempo máxima para checar coerência geográfica (minutos)
INTERVALO_MINUTOS = 120   # ampliado de 30 → 120 para capturar inter-estados

# Distância mínima entre capitais de estados vizinhos (km) — anomalia inter-estadual
DISTANCIA_INTER_ESTADOS_KM = 100.0

# Multiplicador para "Pico de Transação"
MULTIPLICADOR_PICO = 3.0

# ---------------------------------------------------------------------------
# Tabela de estados brasileiros: sigla → (nome, lat_centro, lon_centro)
# ---------------------------------------------------------------------------
ESTADOS_BR: dict[str, tuple[str, float, float]] = {
    "AC": ("Acre",               -9.0238,  -70.8120),
    "AL": ("Alagoas",            -9.5713,  -36.7819),
    "AM": ("Amazonas",           -4.4197,  -63.5806),
    "AP": ("Amapá",               1.4102,  -51.7700),
    "BA": ("Bahia",             -12.5797,  -41.7007),
    "CE": ("Ceará",              -5.4984,  -39.3206),
    "DF": ("Distrito Federal",  -15.7801,  -47.9292),
    "ES": ("Espírito Santo",    -19.1834,  -40.3089),
    "GO": ("Goiás",             -15.8270,  -49.8362),
    "MA": ("Maranhão",          -5.4200,   -45.4410),
    "MG": ("Minas Gerais",      -18.5122,  -44.5550),
    "MS": ("Mato Grosso do Sul",-20.7722,  -54.7852),
    "MT": ("Mato Grosso",       -12.6819,  -56.9211),
    "PA": ("Pará",               -3.4168,  -52.0000),
    "PB": ("Paraíba",            -7.2399,  -36.7819),
    "PE": ("Pernambuco",         -8.8137,  -36.9541),
    "PI": ("Piauí",              -7.7183,  -42.7289),
    "PR": ("Paraná",            -24.8950,  -51.5490),
    "RJ": ("Rio de Janeiro",    -22.9068,  -43.1729),
    "RN": ("Rio Grande do Norte",-5.8127,  -36.2031),
    "RO": ("Rondônia",          -10.8380,  -63.3430),
    "RR": ("Roraima",             2.7376,  -62.0751),
    "RS": ("Rio Grande do Sul", -30.0346,  -51.2177),
    "SC": ("Santa Catarina",    -27.4500,  -50.9500),
    "SE": ("Sergipe",           -10.5741,  -37.3857),
    "SP": ("São Paulo",         -23.5505,  -46.6333),
    "TO": ("Tocantins",         -10.1753,  -48.2982),
}


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
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# Regras heurísticas
# ---------------------------------------------------------------------------

def _estado_da_coordenada(lat: float, lon: float) -> str | None:
    """
    Retorna a sigla do estado cujo centróide está mais próximo das coordenadas
    fornecidas.  Usado como proxy rápido (sem polígonos) para detectar em qual
    estado a transação ocorreu.
    """
    melhor_sigla, melhor_dist = None, float("inf")
    for sigla, (_, clat, clon) in ESTADOS_BR.items():
        d = _haversine(lat, lon, clat, clon)
        if d < melhor_dist:
            melhor_dist = d
            melhor_sigla = sigla
    return melhor_sigla


def _regra_velocidade_impossivel(
    transacao: dict[str, Any],
    historico: list[dict[str, Any]],
) -> tuple[bool, str]:
    """
    Regra 1 — Coerência Geográfica (GPS Aprimorado)

    Compara a localização da transação atual com cada transação anterior dentro
    da janela INTERVALO_MINUTOS e classifica a anomalia em três níveis:

    Nível CRÍTICO  (score += 45): velocidade implícita > 600 km/h — fisicamente
        impossível para qualquer meio de transporte convencional.

    Nível SUSPEITO (score += 35): velocidade > 200 km/h OU mudança de estado
        em < 60 min com distância > 100 km — muito improvável por via terrestre.

    Nível ALERTA   (score += 20): velocidade > 80 km/h OU mudança de estado
        em < 30 min — padrão incomum que merece atenção.

    Retorna o pior caso encontrado (maior score) dentro da janela de tempo.
    """
    lat_atual = transacao.get("latitude")
    lon_atual = transacao.get("longitude")
    estado_atual = transacao.get("estado") or _estado_da_coordenada(lat_atual, lon_atual) if (
        lat_atual is not None and lon_atual is not None
    ) else None

    if lat_atual is None or lon_atual is None:
        return False, ""
    if not isinstance(lat_atual, (int, float)) or not isinstance(lon_atual, (int, float)):
        return False, ""

    try:
        ts_atual = _parse_ts(transacao["timestamp"])
    except (ValueError, TypeError):
        return False, ""

    # Guarda o pior caso encontrado
    pior_score = 0
    pior_detalhe = ""

    for tx in historico:
        if "latitude" not in tx or "longitude" not in tx:
            continue
        try:
            ts_ant = _parse_ts(tx["timestamp"])
        except (ValueError, TypeError):
            continue

        diff_min = abs((ts_atual - ts_ant).total_seconds()) / 60.0
        if diff_min > INTERVALO_MINUTOS:
            continue

        dist_km = _haversine(lat_atual, lon_atual, tx["latitude"], tx["longitude"])
        velocidade = dist_km / (diff_min / 60.0) if diff_min > 0 else float("inf")

        estado_ant = tx.get("estado") or _estado_da_coordenada(tx["latitude"], tx["longitude"])
        mudou_estado = (estado_atual and estado_ant and estado_atual != estado_ant)

        # ── Classificação por gravidade ────────────────────────────────────
        if velocidade > VELOCIDADE_CRITICA_KMH:
            # Fisicamente impossível
            nivel_score = 45
            nivel_txt = "fisicamente impossível"
            cidade_ant = tx.get("cidade", estado_ant or "local anterior")
            cidade_now = transacao.get("cidade", estado_atual or "local atual")
            detalhe = (
                f"Distância de {dist_km:.1f} km em {diff_min:.0f} min "
                f"({velocidade:.0f} km/h) — {nivel_txt}. "
                f"Último uso: {cidade_ant}"
                + (f" ({estado_ant})" if estado_ant else "")
                + f" → atual: {cidade_now}"
                + (f" ({estado_atual})" if estado_atual else "")
                + f" [ref: {tx['transacao_id']}]"
            )

        elif velocidade > VELOCIDADE_SUSPEITA_KMH or (
            mudou_estado and diff_min < 60 and dist_km > DISTANCIA_INTER_ESTADOS_KM
        ):
            # Muito improvável por via terrestre
            nivel_score = 35
            nivel_txt = "muito improvável por via terrestre"
            cidade_ant = tx.get("cidade", estado_ant or "local anterior")
            cidade_now = transacao.get("cidade", estado_atual or "local atual")
            detalhe = (
                f"Distância de {dist_km:.1f} km em {diff_min:.0f} min "
                f"({velocidade:.0f} km/h) entre {cidade_ant}"
                + (f" ({estado_ant})" if estado_ant else "")
                + f" e {cidade_now}"
                + (f" ({estado_atual})" if estado_atual else "")
                + f" — {nivel_txt} [ref: {tx['transacao_id']}]"
            )

        elif velocidade > VELOCIDADE_ALERTA_KMH or (
            mudou_estado and diff_min < 30
        ):
            # Padrão incomum — mudança de estado em tempo curto
            nivel_score = 20
            cidade_ant = tx.get("cidade", estado_ant or "local anterior")
            cidade_now = transacao.get("cidade", estado_atual or "local atual")
            motivo = (
                f"mudança de {estado_ant} para {estado_atual} em {diff_min:.0f} min"
                if mudou_estado
                else f"{velocidade:.0f} km/h entre localidades"
            )
            detalhe = (
                f"Distância de {dist_km:.1f} km em {diff_min:.0f} min — {motivo}. "
                f"{cidade_ant} → {cidade_now} [ref: {tx['transacao_id']}]"
            )

        else:
            continue

        if nivel_score > pior_score:
            pior_score = nivel_score
            pior_detalhe = detalhe

    if pior_score > 0:
        return True, pior_detalhe

    return False, ""


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
    - timestamp     (str ISO-8601, ex: "2026-11-02T23:45:00")

    Campos opcionais (necessários para Regra 1):
    - latitude      (float)
    - longitude     (float)

    Retorna um JSON com:
    - transacao_id   : identificador da transação analisada
    - associado_id   : identificador do associado
    - score_risco    : inteiro de 0 (sem risco) a 100 (altíssimo risco)
    - nivel_risco    : "BAIXO" | "MEDIO" | "ALTO" | "CRITICO"
    - regras_violadas: lista de objetos {regra, descricao, detalhe}
    - historico_usado: número de transações históricas consideradas
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

    ok, detalhe = _regra_velocidade_impossivel(transacao, historico)
    if ok:
        # Score é proporcional ao nível detectado: extraímos da função via detalhe
        _score_gps = (
            45 if "fisicamente impossível" in detalhe
            else 35 if "muito improvável" in detalhe
            else 20
        )
        regras_violadas.append(
            {
                "regra": "VELOCIDADE_IMPOSSIVEL",
                "descricao": "Compra registrada em localização geograficamente incompatível com o histórico recente",
                "detalhe": detalhe,
            }
        )
        score += _score_gps

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

    resultado = {
        "transacao_id": transacao["transacao_id"],
        "associado_id": assoc_id,
        "score_risco": score,
        "nivel_risco": nivel,
        "regras_violadas": regras_violadas,
        "historico_usado": len(historico),
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
        - transacao_id    (str)
        - associado_id    (str)
        - score_risco     (int,  0–100)
        - nivel_risco     (str)
        - regras_violadas (list) — cada item com "regra" e "detalhe"

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
        # Formato esperado: "Distância de X km em Y min (Z km/h) em relação à transação TID"
        dist_txt, tempo_txt = "", ""
        partes = detalhe.split(" ")
        try:
            dist_txt = f"{partes[2]} km"   # "X km"
            tempo_txt = f"{partes[4]} minutos"  # "Y min"
        except IndexError:
            dist_txt, tempo_txt = "uma grande distância", "pouquíssimo tempo"

        paragrafos.append(
            f"Identificamos que, há muito pouco tempo antes desta compra, seu cartão "
            f"foi usado em um lugar bem diferente deste. A distância entre os dois locais "
            f"é de {dist_txt}, e o intervalo entre as duas compras foi de apenas {tempo_txt}. "
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

        paragrafos.append(
            f"Esta compra foi feita em {categoria_txt} às {hora_txt}, "
            f"que é um horário fora do comum para esse tipo de estabelecimento. "
            f"Compras em joalherias, lojas de eletrônicos e lugares parecidos realizadas "
            f"de madrugada ou em horários muito incomuns costumam ser um sinal de alerta. "
            f"Por isso, queremos ter certeza de que foi mesmo você quem fez essa compra."
        )

    # ── Monta a mensagem final ────────────────────────────────────────────────
    intro = (
        "Olá! Identificamos algo diferente na sua conta e precisamos da sua confirmação "
        "antes de liberar uma compra recente. Não se preocupe — seu cartão não foi bloqueado, "
        "mas precisamos de um momento da sua atenção.\n\n"
        "Veja o que chamou nossa atenção:\n\n"
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
        "Se não responder em 2 minutos, entre em contato com sua agência Sicredi."
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
