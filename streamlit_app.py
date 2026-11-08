# -*- coding: utf-8 -*-
"""
streamlit_app.py — Simulador de Chat do watsonx Orchestrate
=============================================================
Interface conversacional que replica a experiência do IBM watsonx Orchestrate,
conectando-se ao motor de análise de fraudes do Sicredi via MCP.

Execute:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import sys
import types
import time
from datetime import datetime
from pathlib import Path

# ── Bootstrap: mock FastMCP para evitar bloqueio de stdin ────────────────────
class _MockFastMCP:
    def __init__(self, *args, **kwargs): pass
    def tool(self, *args, **kwargs):
        def decorator(fn): return fn
        return decorator
    def run(self, *args, **kwargs): pass

_mcp_module = types.ModuleType("mcp.server.fastmcp")
_mcp_module.FastMCP = _MockFastMCP
sys.modules["mcp.server.fastmcp"] = _mcp_module
if "mcp" not in sys.modules:
    sys.modules["mcp"] = types.ModuleType("mcp")
if "mcp.server" not in sys.modules:
    sys.modules["mcp.server"] = types.ModuleType("mcp.server")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_antifraude"))

import server as mcp_server  # type: ignore  (mcp_antifraude/server.py)
analisar_risco_transacao = mcp_server.analisar_risco_transacao
explicar_risco_fraude    = mcp_server.explicar_risco_fraude

# Tabela de estados internalizada — server.py não expõe mais ESTADOS_BR
# Formato: sigla → (nome completo, lat_centro, lon_centro)
ESTADOS_BR: dict[str, tuple[str, float, float]] = {
    "AC": ("Acre",                -9.0238,  -70.8120),
    "AL": ("Alagoas",             -9.5713,  -36.7819),
    "AM": ("Amazonas",            -4.4197,  -63.5806),
    "AP": ("Amapá",                1.4102,  -51.7700),
    "BA": ("Bahia",              -12.5797,  -41.7007),
    "CE": ("Ceará",               -5.4984,  -39.3206),
    "DF": ("Distrito Federal",   -15.7801,  -47.9292),
    "ES": ("Espírito Santo",     -19.1834,  -40.3089),
    "GO": ("Goiás",              -15.8270,  -49.8362),
    "MA": ("Maranhão",            -5.4200,  -45.4410),
    "MG": ("Minas Gerais",       -18.5122,  -44.5550),
    "MS": ("Mato Grosso do Sul", -20.7722,  -54.7852),
    "MT": ("Mato Grosso",        -12.6819,  -56.9211),
    "PA": ("Pará",                -3.4168,  -52.0000),
    "PB": ("Paraíba",             -7.2399,  -36.7819),
    "PE": ("Pernambuco",          -8.8137,  -36.9541),
    "PI": ("Piauí",               -7.7183,  -42.7289),
    "PR": ("Paraná",             -24.8950,  -51.5490),
    "RJ": ("Rio de Janeiro",     -22.9068,  -43.1729),
    "RN": ("Rio Grande do Norte", -5.8127,  -36.2031),
    "RO": ("Rondônia",           -10.8380,  -63.3430),
    "RR": ("Roraima",              2.7376,  -62.0751),
    "RS": ("Rio Grande do Sul",  -30.0346,  -51.2177),
    "SC": ("Santa Catarina",     -27.4500,  -50.9500),
    "SE": ("Sergipe",            -10.5741,  -37.3857),
    "SP": ("São Paulo",          -23.5505,  -46.6333),
    "TO": ("Tocantins",          -10.1753,  -48.2982),
}

def _estado_da_coordenada(lat: float, lon: float) -> str:
    """Retorna a sigla do estado cujo centróide está mais próximo das coordenadas."""
    import math
    def _hav(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    melhor_sigla, melhor_dist = "RS", float("inf")
    for sigla, (_, clat, clon) in ESTADOS_BR.items():
        d = _hav(lat, lon, clat, clon)
        if d < melhor_dist:
            melhor_dist = d
            melhor_sigla = sigla
    return melhor_sigla

# Lista ordenada para o seletor: "SP — São Paulo", …
_OPCOES_ESTADO = sorted(
    [f"{sig} — {nome}" for sig, (nome, _, _) in ESTADOS_BR.items()]
)
_SIGLA_DE_OPCAO = {f"{sig} — {nome}": sig for sig, (nome, _, _) in ESTADOS_BR.items()}

# ── Streamlit ─────────────────────────────────────────────────────────────────
import streamlit as st

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente Anti-Fraude Sicredi — watsonx Orchestrate",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS customizado (visual watsonx Orchestrate) ──────────────────────────────
st.markdown("""
<style>
  /* Fundo geral */
  .stApp { background-color: #f4f4f4; }

  /* Cabeçalho do chat */
  .wx-header {
    background: linear-gradient(135deg, #0f62fe 0%, #0043ce 100%);
    color: white;
    padding: 18px 24px;
    border-radius: 12px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .wx-header h2 { margin: 0; font-size: 1.25rem; font-weight: 600; }
  .wx-header p  { margin: 0; font-size: 0.82rem; opacity: 0.85; }

  /* Bolhas do chat */
  .msg-user {
    background: #0f62fe;
    color: white;
    padding: 12px 16px;
    border-radius: 18px 18px 4px 18px;
    margin: 8px 0;
    max-width: 75%;
    margin-left: auto;
    font-size: 0.93rem;
    line-height: 1.5;
  }
  .msg-agent {
    background: white;
    color: #161616;
    padding: 12px 16px;
    border-radius: 18px 18px 18px 4px;
    margin: 8px 0;
    max-width: 80%;
    border: 1px solid #e0e0e0;
    font-size: 0.93rem;
    line-height: 1.55;
  }
  .msg-system {
    background: #fff3cd;
    color: #664d03;
    padding: 10px 14px;
    border-radius: 10px;
    margin: 6px auto;
    max-width: 70%;
    text-align: center;
    font-size: 0.82rem;
    border: 1px solid #ffc107;
  }
  .msg-block {
    background: #fff1f1;
    color: #a2191f;
    padding: 12px 16px;
    border-radius: 18px 18px 18px 4px;
    margin: 8px 0;
    max-width: 80%;
    border: 1px solid #ffd7d9;
    font-size: 0.93rem;
    line-height: 1.55;
  }
  .msg-ok {
    background: #defbe6;
    color: #044317;
    padding: 12px 16px;
    border-radius: 18px 18px 18px 4px;
    margin: 8px 0;
    max-width: 80%;
    border: 1px solid #a7f0ba;
    font-size: 0.93rem;
    line-height: 1.55;
  }

  /* Badge de score */
  .badge-critico { background:#a2191f; color:white; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }
  .badge-alto    { background:#ff832b; color:white; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }
  .badge-medio   { background:#f1c21b; color:#161616; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }
  .badge-baixo   { background:#24a148; color:white; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }

  /* Rodapé IBM */
  .ibm-footer {
    text-align: center;
    color: #6f6f6f;
    font-size: 0.75rem;
    margin-top: 32px;
    padding-top: 12px;
    border-top: 1px solid #e0e0e0;
  }

  /* Remove padding extra dos containers de chat */
  .chat-area { max-height: 520px; overflow-y: auto; padding: 4px 0; }
</style>
""", unsafe_allow_html=True)


# ── Estado da sessão ──────────────────────────────────────────────────────────
if "messages"      not in st.session_state: st.session_state.messages      = []
if "historico_mcp" not in st.session_state: st.session_state.historico_mcp = {}
if "aguardando_resp" not in st.session_state: st.session_state.aguardando_resp = None
if "ultima_analise"  not in st.session_state: st.session_state.ultima_analise  = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _badge(nivel: str) -> str:
    cls = {"BAIXO": "baixo", "MEDIO": "medio", "ALTO": "alto", "CRITICO": "critico"}.get(nivel, "baixo")
    labels = {"BAIXO": "Risco Baixo", "MEDIO": "Risco Médio",
              "ALTO": "Risco Alto", "CRITICO": "Risco Crítico"}
    return f'<span class="badge-{cls}">{labels.get(nivel, nivel)}</span>'


def _add_msg(role: str, html: str) -> None:
    st.session_state.messages.append({"role": role, "html": html})


def _render_msg(msg: dict) -> None:
    role = msg["role"]
    html = msg["html"]
    if role == "user":
        st.markdown(f'<div class="msg-user">{html}</div>', unsafe_allow_html=True)
    elif role == "agent":
        st.markdown(f'<div class="msg-agent">{html}</div>', unsafe_allow_html=True)
    elif role == "block":
        st.markdown(f'<div class="msg-block">{html}</div>', unsafe_allow_html=True)
    elif role == "ok":
        st.markdown(f'<div class="msg-ok">{html}</div>', unsafe_allow_html=True)
    elif role == "system":
        st.markdown(f'<div class="msg-system">{html}</div>', unsafe_allow_html=True)


def _analisar(tx: dict) -> dict:
    """Injeta histórico e chama analisar_risco_transacao."""
    assoc = tx.get("associado_id", "demo")
    if assoc in st.session_state.historico_mcp:
        mcp_server._HISTORICO[assoc] = st.session_state.historico_mcp[assoc]
    t0 = time.perf_counter()
    raw = analisar_risco_transacao(json.dumps(tx, ensure_ascii=False))
    lat_ms = (time.perf_counter() - t0) * 1000
    resultado = json.loads(raw)
    resultado["_latencia_ms"] = round(lat_ms, 2)
    # Persiste transação no histórico para próximas análises
    mcp_server._HISTORICO.setdefault(assoc, []).append(tx)
    st.session_state.historico_mcp[assoc] = mcp_server._HISTORICO[assoc]
    return resultado


def _construir_mensagem_agente(analise: dict, explicacao: dict) -> tuple[str, str]:
    """Retorna (html_da_mensagem, role)."""
    score  = analise["score_risco"]
    nivel  = analise["nivel_risco"]
    regras = analise.get("regras_violadas", [])
    lat    = analise.get("_latencia_ms", 0)
    badge  = _badge(nivel)
    alerta_fp = explicacao.get("alerta_falso_positivo", False)
    requer    = explicacao.get("requer_validacao", False)

    titulo   = explicacao.get("titulo", "")
    mensagem = explicacao.get("mensagem_associado", "").replace("\n", "<br>")
    orient   = explicacao.get("orientacao", "")

    # Contexto enriquecido (novos campos do server.py)
    loc_resumo  = analise.get("localizacao_resumo", "")
    dt_exibicao = analise.get("data_hora_exibicao", "")
    contexto_html = ""
    if loc_resumo or dt_exibicao:
        partes = []
        if loc_resumo:
            partes.append(f"📍 {loc_resumo}")
        if dt_exibicao:
            partes.append(f"🕐 {dt_exibicao}")
        contexto_html = (
            f"<div style='font-size:0.82rem;color:#525252;margin:4px 0 8px 0'>"
            + " &nbsp;·&nbsp; ".join(partes)
            + "</div>"
        )

    motivos_html = ""
    if regras:
        itens = "".join(f"<li>{r['descricao']}</li>" for r in regras)
        motivos_html = f"<ul style='margin:6px 0 0 0;padding-left:18px;font-size:0.87rem'>{itens}</ul>"

    if score == 0:
        role = "ok"
        html = (
            f"✅ <strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>Análise concluída em {lat} ms "
            f"— Score: {score}/100 &nbsp;{badge}</span><br>"
            f"{contexto_html}"
            f"{mensagem}"
        )
    elif alerta_fp:
        role = "agent"
        html = (
            f"ℹ️ <strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>Análise concluída em {lat} ms "
            f"— Score: {score}/100 &nbsp;{badge}</span>"
            f"{contexto_html}"
            f"{motivos_html}<br><br>"
            f"{mensagem}<br><br>"
            f"<em style='font-size:0.85rem;color:#525252'>{orient}</em>"
        )
    elif requer:
        role = "block"
        html = (
            f"⚠️ <strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem'>Análise concluída em {lat} ms "
            f"— Score: {score}/100 &nbsp;{badge}</span>"
            f"{contexto_html}"
            f"{motivos_html}<br><br>"
            f"{mensagem}<br><br>"
            f"<strong style='font-size:0.87rem'>{orient}</strong>"
        )
    else:
        role = "agent"
        html = (
            f"<strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>{lat} ms — Score {score}/100 &nbsp;{badge}</span><br>"
            f"{contexto_html}"
            f"{mensagem}"
        )

    return html, role


def _processar_resposta_hitl(resposta: str, analise: dict, explicacao: dict) -> None:
    """
    Processa SIM/NÃO do associado após alerta crítico de forma segura.
    """
    if resposta.upper() in ('SIM', 'S', '1', 'FUI EU'):
        _add_msg('ok', (
            "✅ <strong>Compra confirmada por você.</strong><br>"
            "A transação foi liberada e o pagamento será processado normalmente. "
            "Obrigado pela confirmação!"
        ))
    else:
        _add_msg('block', (
            "🚫 <strong>Transação bloqueada a seu pedido.</strong><br>"
            "Seu cartão foi protegido. Nossa equipe de segurança foi acionada e "
            "entrará em contato em breve. Se precisar de ajuda imediata, ligue para "
            "a Central Sicredi: <strong>0800 724 4440</strong>."
        ))
    
    # Atualiza os estados antes de recarregar o layout do Streamlit
    st.session_state.aguardando_resp = None
    st.session_state.ultima_analise = None



# ── Sidebar ───────────────────────────────────────────────────────────────────
    # ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🛡️ Agente Anti-Fraude")
    st.markdown("**IBM watsonx Orchestrate** · Sicredi")
    st.divider()
    st.markdown("#### 🧪 Transações de Teste")
    st.caption("Clique para preencher automaticamente")

    # Cada entrada: (label, tx_dict, historico_para_injetar_ou_None)
    # Históricos definem o padrão do associado antes da transação suspeita.
    _now = datetime.now()
    from datetime import timedelta as _td

    EXEMPLOS = [
        # ── 1. Normal — sem fraude ───────────────────────────────────────────
        (
            "✅ Normal — Farmácia R$87,43",
            {
                "transacao_id": "demo-n0", "associado_id": "demo_n0",
                "valor": 87.43, "categoria": "Farmácias",
                "cidade": "Curitiba", "estado": "PR",
                "timestamp": _now.replace(hour=10, minute=17).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -25.4297, "longitude": -49.2716,
            },
            None,  # sem histórico → score 0, BAIXO
        ),
        # ── 2. Pico de Valor — alerta médio ─────────────────────────────────
        (
            "⚠️ Pico de Valor — Eletrônicos 4.6x acima",
            {
                "transacao_id": "demo-a1", "associado_id": "demo_a1",
                "valor": 1847.63, "categoria": "Eletrônicos",
                "cidade": "Fortaleza", "estado": "CE",
                "timestamp": _now.replace(hour=16, minute=54).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -3.7172, "longitude": -38.5433,
            },
            # histórico: 2 compras de eletrônicos no CE, média ~R$405 → 1847 = 4.6x → MÉDIO
            [
                {"transacao_id": "ha1a", "associado_id": "demo_a1", "valor": 423.18,
                 "categoria": "Eletrônicos", "cidade": "Fortaleza", "estado": "CE",
                 "timestamp": (_now - _td(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -3.7172, "longitude": -38.5433},
                {"transacao_id": "ha1b", "associado_id": "demo_a1", "valor": 387.55,
                 "categoria": "Eletrônicos", "cidade": "Fortaleza", "estado": "CE",
                 "timestamp": (_now - _td(days=5)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -3.7172, "longitude": -38.5433},
            ],
        ),
        # ── 3. GPS Impossível Nacional (CRÍTICO, janela < 24h) ───────────────
        (
            "🚨 GPS Impossível — SP → AM em 15 min (Nacional)",
            {
                "transacao_id": "demo-gn1", "associado_id": "demo_gn1",
                "valor": 923.50, "categoria": "Eletrônicos",
                "cidade": "Manaus", "estado": "AM",
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -3.1190, "longitude": -60.0217,
            },
            # SP→Manaus ≈ 2.690 km em 15 min → 10.760 km/h → > 600 km/h → CRÍTICO
            # Janela < 24h nacional ativa (estado=AM)
            [
                {"transacao_id": "hgn1a", "associado_id": "demo_gn1", "valor": 189.75,
                 "categoria": "Supermercados", "cidade": "São Paulo", "estado": "SP",
                 "timestamp": (_now - _td(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -23.5505, "longitude": -46.6333},
            ],
        ),
        # ── 4. GPS Impossível Internacional (CRÍTICO, janela < 48h) ─────────
        (
            "🚨 GPS Impossível — RS → Tóquio em 12 min (Internacional)",
            {
                "transacao_id": "demo-f1", "associado_id": "demo_f1",
                "valor": 1247.83, "categoria": "Restaurante / Alimentação",
                "cidade": "Tóquio", "pais": "JP",
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": 35.6762, "longitude": 139.6503,
            },
            # RS→Tóquio ≈ 18.822 km em 12 min → 94.115 km/h → CRÍTICO
            # Janela < 48h internacional ativa (pais=JP)
            [
                {"transacao_id": "hf1a", "associado_id": "demo_f1", "valor": 143.78,
                 "categoria": "Supermercados", "cidade": "Porto Alegre", "estado": "RS",
                 "timestamp": (_now - _td(minutes=12)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -30.0346, "longitude": -51.2177},
            ],
        ),
        # ── 5. Joalheria de Madrugada — perfil incomum (alerta médio) ────────
        (
            "⚠️ Joalheria às 03h17 — perfil incomum",
            {
                "transacao_id": "demo-a2", "associado_id": "demo_a2",
                "valor": 7312.49, "categoria": "Joalherias",
                "cidade": "Rio de Janeiro", "estado": "RJ",
                "timestamp": _now.replace(hour=3, minute=17).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -22.9068, "longitude": -43.1729,
            },
            None,  # sem histórico → só PERFIL_INCOMUM, score 25, MÉDIO
        ),
    ]

    for i, (label, tx, hist_injectar) in enumerate(EXEMPLOS):
        if st.button(label, use_container_width=True, key=f"btn_exemplo_{i}"):
            assoc = tx["associado_id"]
            if hist_injectar is not None:
                mcp_server._HISTORICO[assoc] = hist_injectar
                st.session_state.historico_mcp[assoc] = hist_injectar
            else:
                mcp_server._HISTORICO.pop(assoc, None)
                st.session_state.historico_mcp.pop(assoc, None)
            st.session_state["_fill_tx"] = tx
            st.rerun()

    st.divider()
    st.markdown("#### ℹ️ Sobre")
    st.caption("Simulação do agente anti-fraude Sicredi rodando localmente com o motor MCP. As análises são executadas em memória — sem chamadas externas.")
    
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.messages = []
        st.session_state.historico_mcp = {}
        st.session_state.aguardando_resp = None
        st.session_state.ultima_analise = None
        st.rerun()



# ── Cabeçalho principal ───────────────────────────────────────────────────────
st.markdown("""
<div class="wx-header">
  <span style="font-size:2rem">🛡️</span>
  <div>
    <h2>Agente Anti-Fraude Sicredi</h2>
    <p>IBM watsonx Orchestrate &nbsp;·&nbsp; Motor MCP local &nbsp;·&nbsp; Análise em tempo real</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Área do chat ──────────────────────────────────────────────────────────────
chat_container = st.container()

with chat_container:
    if not st.session_state.messages:
        st.markdown("""
<div class="msg-agent">
👋 Olá! Sou o Agente Anti-Fraude do Sicredi, conectado ao <strong>IBM watsonx Orchestrate</strong>.<br><br>
Posso analisar uma transação financeira em tempo real e dizer se ela parece segura ou suspeita —
em menos de 50 ms.<br><br>
<strong>Para começar:</strong> preencha os campos abaixo com os dados da transação, ou escolha um
exemplo pronto na barra lateral. 👈
</div>
""", unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            _render_msg(msg)


# ── Formulário de entrada de transação ────────────────────────────────────────
st.divider()

# Preenche campos se um exemplo foi selecionado
_fill = st.session_state.get("_fill_tx", None)

if st.session_state.aguardando_resp:
    st.markdown('<div class="msg-system">⏳ <strong>Aguardando sua decisão</strong> — a transação está pausada.</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Sim, fui eu — liberar", use_container_width=True, type="primary"):
            _add_msg('user', "✅ Sim, fui eu — pode liberar")
            # Passa a análise guardada em sessão para evitar perda de contexto
            _processar_resposta_hitl('SIM', st.session_state.ultima_analise, st.session_state.ultima_analise)
            st.meta_private_attributes = {}
            st.rerun()
    with col2:
        if st.button("🚫 Não fui eu — bloquear cartão", use_container_width=True):
            _add_msg('user', "🚫 Não fui eu — bloquear cartão")
            _processar_resposta_hitl('NÃO', st.session_state.ultima_analise, st.session_state.ultima_analise)
            st.rerun()


else:
    # ── Formulário normal de transação ────────────────────────────────────────
    with st.form("form_transacao", clear_on_submit=False):

        # ── Linha 1: ID Associado | Categoria | Valor ─────────────────────

    st.markdown("<p style='font-weight:600;color:#3d3d3d;margin-bottom:4px'>📋 Dados da Transação</p>", unsafe_allow_html=True)
    r1c1, r1c2, r1c3 = st.columns([1.2, 1.8, 1.0])
    with r1c1:
        assoc_id = st.text_input(
            "ID do Associado",
            value=_fill["associado_id"] if _fill else "demo_user",
            placeholder="ex: assoc_001",
        )
    _cats = [
        "Supermercados", "Restaurantes", "Farmácias", "Postos de Combustível",
        "Eletrônicos", "Joalherias", "Artigos de Luxo", "Casas de Câmbio",
        "Cassinos", "Apostas", "Restaurante / Alimentação", "Transferência Financeira",
        "E-commerce / Eletrônicos", "Vestuário / Moda", "Educação / Ensino",
        "Streaming / Entretenimento Digital", "Outros",
    ]
    with r1c2:
        categoria = st.selectbox(
            "Categoria",
            options=_cats,
            index=( _cats.index(_fill["categoria"]) if _fill and _fill.get("categoria") in _cats else 0 ),
        )
    with r1c3:
        valor = st.number_input(
            "Valor (R$)",
            min_value=0.01,
            max_value=999999.99,
            step=10.0,
            value=float(_fill["valor"]) if _fill else 150.0,
            format="%.2f",
        )
    st.write( )

    # ── Linha 2: Cidade | Estado/País | Latitude | Longitude (DINÂMICA) ──────────
    st.markdown("<p style='font-weight:600;color:#3d3d3d;margin-bottom:4px'>🗺️ Localização</p>", unsafe_allow_html=True)
    _OPCOES_LOCAL = _OPCOES_ESTADO + [ "🌍 Internacional" ]
    _fill_is_intl = ( _fill and not _fill.get("estado") and str(_fill.get("pais", "BR")).upper() not in ( "", "BR" ) )
    if _fill_is_intl:
        _fill_opcao_local = "🌍 Internacional"
    else:
        _fill_estado = _fill.get("estado") if _fill else None
        if not _fill_estado and _fill and _fill.get("latitude") and _fill.get("longitude"):
            _fill_estado = _estado_da_coordenada( float(_fill["latitude"]), float(_fill["longitude"]) )
        _fill_estado = _fill_estado or "RS"
        _fill_opcao_local = next( (o for o in _OPCOES_ESTADO if o.startswith(_fill_estado + " —")), _OPCOES_ESTADO[0] )

    r2c1, r2c2, r2c3, r2c4 = st.columns([1.4, 1.6, 1.0, 1.0])
    with r2c1:
        cidade = st.text_input("Cidade", value=_fill.get("cidade", "") if _fill else "", placeholder="ex: Porto Alegre")
    with r2c2:
        local_opcao = st.selectbox(
            "Estado / País",
            options=_OPCOES_LOCAL,
            index=_OPCOES_LOCAL.index(_fill_opcao_local),
            help="Estado BR (lat/lon automáticos) ou 🌍 Internacional para coordenadas livres.",
        )

    _is_intl = local_opcao == "🌍 Internacional"
    if _is_intl:
        estado_sigla = ""
        _lat_def = float(_fill["latitude"]) if (_fill and _fill.get("latitude")) else 48.8566
        _lon_def = float(_fill["longitude"]) if (_fill and _fill.get("longitude")) else 2.3522
        _pais_def = str(_fill.get("pais", "FR")).upper() if (_fill and _fill.get("pais")) else "FR"
    else:
        estado_sigla = _SIGLA_DE_OPCAO[local_opcao]
        _, _lat_def, _lon_def = ESTADOS_BR[estado_sigla]
        _pais_def = "BR"

    with r2c3:
        lat = st.number_input(
            "Latitude",
            value=_lat_def,
            format="%.4f",
            step=0.0001,
            help="Automático para BR; editável para Internacional.",
            key=f"lat_input_{local_opcao}"
        )
    with r2c4:
        lon = st.number_input(
            "Longitude",
            value=_lat_def if _is_intl else _lon_def, # Ajuste para garantir sincronismo
            format="%.4f",
            step=0.0001,
            help="Automático para BR; editável para Internacional.",
            key=f"lon_input_{local_opcao}"
        )

    if _is_intl:
        pais_intl = st.text_input(
            "País (ISO-2)",
            value=_pais_def,
            placeholder="ex: JP, AR, US, PT",
            max_chars=2,
            help="Código ISO 3166-1 alpha-2. Janela GPS crítica: < 48h para internacionais.",
        ).upper().strip() or "XX"
    else:
        pais_intl = "BR"
    st.write( )

    # ── Linha 3: Data | Hora local ───────────────────────────────────────────────
    st.markdown("<p style='font-weight:600;color:#3d3d3d;margin-bottom:4px'>🕐 Data e Hora Local da Transação</p>", unsafe_allow_html=True)
    _fill_ts = _fill.get("timestamp", "") if _fill else ""
    try:
        _fill_dt = datetime.fromisoformat(_fill_ts[:19]) if _fill_ts else datetime.now()
    except (ValueError, TypeError):
        _fill_dt = datetime.now()

    r3c1, r3c2, r3c3 = st.columns([1.2, 1.0, 1.8])
    with r3c1:
        data_local = st.date_input("Data local", value=_fill_dt.date())
    with r3c2:
        hora_local = st.time_input("Hora local", value=_fill_dt.time(), step=60)
    with r3c3:
        fuso_horario = st.text_input(
            "Fuso Horário",
            value=_fill.get("fuso_horario", "America/Sao_Paulo") if _fill else "America/Sao_Paulo",
            placeholder="ex: America/Sao_Paulo, Asia/Tokyo",
            help="Fuso IANA. Usado para exibição da data/hora ao associado.",
        )
    st.write( )

    submitted = st.button(
        "🔍 Analisar Transação",
        use_container_width=True,
        type="primary",
    )      
                
        

    if submitted:
        # Monta offset a partir do fuso informado
        _offset = {
            "America/Sao_Paulo": "-03:00", "America/Fortaleza": "-03:00",
            "America/Manaus": "-04:00",    "America/Rio_Branco": "-05:00",
            "America/Noronha": "-02:00",   "Asia/Tokyo": "+09:00",
            "Europe/London": "+00:00",     "America/New_York": "-05:00",
            "America/Los_Angeles": "-08:00",
        }.get(fuso_horario.strip(), "-03:00")
        data_hora_local_str = (
            f"{data_local.isoformat()}T{hora_local.strftime('%H:%M:%S')}{_offset}"
        )

        tx = {
            "transacao_id": f"tx-{int(time.time()*1000)}",
            "associado_id": assoc_id.strip() or "demo_user",
            "valor":        valor,
            "categoria":    categoria,
            "cidade":       cidade or (local_opcao.split(" — ")[-1] if not _is_intl else ""),
            "fuso_horario": fuso_horario.strip(),
            "timestamp":    f"{data_local.isoformat()}T{hora_local.strftime('%H:%M:%S')}",
            "data_hora_local": data_hora_local_str,
            "latitude":     lat,
            "longitude":    lon,
        }
        if _is_intl:
            tx["pais"] = pais_intl
        else:
            tx["estado"] = estado_sigla
            tx["pais"] = "BR"

        # Mensagem do usuário no chat
        valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        cidade_exib = tx.get("cidade", "")
        if _is_intl:
            local_exib = f"{cidade_exib} ({pais_intl}) 🌍"
        else:
            local_exib = f"{cidade_exib} ({estado_sigla})"
        _add_msg("user",
            f"📤 Analisar transação: <strong>{valor_fmt}</strong> em "
            f"<strong>{categoria}</strong> — {local_exib}<br>"
            f"<span style='font-size:0.82rem;opacity:0.8'>Associado: {tx['associado_id']} &nbsp;·&nbsp; "
            f"{data_local.strftime('%d/%m/%Y')} às {hora_local.strftime('%H:%M')} "
            f"({fuso_horario.strip() or 'UTC'})</span>"
        )

        with st.spinner("Agente analisando..."):
            analise    = _analisar(tx)
            explicacao = json.loads(
                explicar_risco_fraude(json.dumps(analise, ensure_ascii=False))
            )

        html, role = _construir_mensagem_agente(analise, explicacao)
        _add_msg(role, html)

        # Se crítico: ativa modo HITL
        if analise["score_risco"] > 70:
            st.session_state.aguardando_resp = tx["transacao_id"]
            st.session_state.ultima_analise  = analise
            _add_msg("system",
                "⏸️ Fluxo de liquidação pausado — aguardando sua confirmação abaixo."
            )

        st.rerun()


# ── Rodapé ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="ibm-footer">
  Sicredi · AI Experiential Learning Lab 2026 &nbsp;|&nbsp;
  Motor MCP local · IBM watsonx Orchestrate (simulação) &nbsp;|&nbsp;
  <a href="https://github.com/samuel2k6/Projeto-Anti-fraude" target="_blank"
     style="color:#0f62fe;text-decoration:none">
    GitHub ↗
  </a>
</div>
""", unsafe_allow_html=True)
