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
st.markdown(
    """
<style>
/* Fundo geral */
.stApp {
    background-color: #f4f4f4;
}
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
.wx-header p { margin: 0; font-size: 0.82rem; opacity: 0.85; }

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
.badge-alto { background:#ff832b; color:white; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }
.badge-medio { background:#f1c21b; color:#161616; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }
.badge-baixo { background:#24a148; color:white; padding:2px 8px; border-radius:12px; font-size:0.78rem; font-weight:600; }

/* Rodapé IBM */
.ibm-footer {
    text-align: center;
    color: #6f6f6f;
    font-size: 0.75rem;
    margin-top: 32px;
    padding-top: 12px;
    border-top: 1px solid #e0e0e0;
}
.chat-area {
    max-height: 520px;
    overflow-y: auto;
    padding: 4px 0;
}
[data-testid="stWidgetLabel"] p {
    color: #393939 !important;
    font-weight: 500 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(input[aria-label="Latitude"]) [data-testid="stHorizontalBlock"],
div.lat-lon-row [data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: stretch !important;
    gap: 0.75rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(input[aria-label="Latitude"]) [data-testid="stHorizontalBlock"] > div,
div.lat-lon-row [data-testid="stHorizontalBlock"] > div {
    min-width: 0 !important;
    flex: 1 1 0% !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(input[aria-label="Latitude"]) label p,
div.lat-lon-row label p {
    font-size: 0.85rem !important;
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
""",
    unsafe_allow_html=True,
)




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

    titulo  = explicacao.get("titulo", "")
    mensagem = explicacao.get("mensagem_associado", "").replace("\n", "<br>")
    orient   = explicacao.get("orientacao", "")

    motivos_html = ""
    if regras:
        itens = "".join(f"<li>{r['descricao']}</li>" for r in regras)
        motivos_html = f"<ul style='margin:6px 0 0 0;padding-left:18px;font-size:0.87rem'>{itens}</ul>"

    if score == 0:
        role = "ok"
        html = (
            f"✅ <strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>Análise concluída em {lat} ms "
            f"— Score: {score}/100 &nbsp;{badge}</span><br><br>"
            f"{mensagem}"
        )
    elif alerta_fp:
        role = "agent"
        html = (
            f"ℹ️ <strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>Análise concluída em {lat} ms "
            f"— Score: {score}/100 &nbsp;{badge}</span>"
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
            f"{motivos_html}<br><br>"
            f"{mensagem}<br><br>"
            f"<strong style='font-size:0.87rem'>{orient}</strong>"
        )
    else:
        role = "agent"
        html = (
            f"<strong>{titulo}</strong><br>"
            f"<span style='font-size:0.87rem;color:#525252'>{lat} ms — Score {score}/100 &nbsp;{badge}</span><br><br>"
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
with st.sidebar:
    st.markdown("### 🛡️ Agente Anti-Fraude")
    st.markdown("**IBM watsonx Orchestrate** · Sicredi")
    st.divider()
    st.markdown("#### 🧪 Transações de Teste")
    st.caption("Clique para preencher automaticamente")
    
    EXEMPLOS = {
        "✅ Normal — Supermercado": {
            "transacao_id": "demo-001",
            "associado_id": "demo_user",
            "valor": 130.0,
            "categoria": "Supermercados",
            "cidade": "Porto Alegre",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": -30.0346,
            "longitude": -51.2177,
        },
        "⚠️ Pico de valor — Eletrônicos": {
            "transacao_id": "demo-002",
            "associado_id": "demo_user",
            "valor": 4500.0,
            "categoria": "Eletrônicos",
            "cidade": "São Paulo",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": -23.5505,
            "longitude": -46.6333,
        },
        "🚨 GPS Impossível — Tóquio": {
            "transacao_id": "demo-gps",
            "associado_id": "demo_gps",
            "valor": 1250.0,
            "categoria": "Restaurante / Alimentação",
            "cidade": "Tóquio",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": 35.6762,
            "longitude": 139.6503,
        },
        "🚨 Joalheria de madrugada": {
            "transacao_id": "demo-004",
            "associado_id": "demo_user",
            "valor": 8900.0,
            "categoria": "Joalherias",
            "cidade": "Rio de Janeiro",
            "timestamp": datetime.now().replace(hour=2, minute=30).strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": -22.9068,
            "longitude": -43.1729,
        },
    }

    for label, tx in EXEMPLOS.items():
        if st.button(label, use_container_width=True, key=f"btn_{label[:8]}"):
            # Para o caso GPS: injeta histórico de Porto Alegre antes
            if "Tóquio" in label:
                mcp_server._HISTORICO["demo_gps"] = [{
                    "transacao_id": "hist-gps",
                    "associado_id": "demo_gps",
                    "valor": 187.0,
                    "categoria": "Supermercados",
                    "timestamp": datetime.now().replace(
                        hour=datetime.now().hour,
                        minute=max(0, datetime.now().minute - 15)
                    ).strftime("%Y-%m-%dT%H:%M:%S"),
                    "latitude": -30.0346,
                    "longitude": -51.2177,
                }]
                st.session_state.historico_mcp["demo_gps"] = mcp_server._HISTORICO["demo_gps"]
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
        👋 Olá! Sou o Agente Anti-Fraude do Sicredi, conectado ao
        <strong>IBM watsonx Orchestrate</strong>.<br><br>

        Posso analisar uma transação financeira em tempo real e dizer
        se ela parece segura ou suspeita — em menos de 50 ms.<br><br>

        <strong>Para começar:</strong> preencha os campos abaixo com
        os dados da transação, ou escolha um exemplo pronto na barra
        lateral. 👈
        </div>
        """, unsafe_allow_html=True)

    else:

        for msg in st.session_state.messages:
            _render_msg(msg)


         

# ── Formulário de entrada de transação ────────────────────────────────────────

_fill = st.session_state.get("_fill_tx", None)

# ── Controle HITL: aguardando confirmação do associado ────────────────────────
if st.session_state.aguardando_resp:

    st.markdown(
        '<div class="msg-system">'
        '⏳ <strong>Aguardando sua decisão</strong> — '
        'a transação está pausada.'
        '</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "✅ Sim, fui eu — liberar",
            use_container_width=True,
            type="primary"
        ):
            _add_msg(
                "user",
                "✅ Sim, fui eu — pode liberar"
            )

            _processar_resposta_hitl(
                "SIM",
                st.session_state.ultima_analise,
                st.session_state.ultima_analise
            )

            st.rerun()

    with col2:
        if st.button(
            "🚫 Não fui eu — bloquear cartão",
            use_container_width=True
        ):
            _add_msg(
                "user",
                "🚫 Não fui eu — bloquear cartão"
            )

            _processar_resposta_hitl(
                "NÃO",
                st.session_state.ultima_analise,
                st.session_state.ultima_analise
            )

            st.rerun()


# ── Formulário normal de transação ────────────────────────────────────────────
else:

    categorias = [
        "Supermercados",
        "Restaurantes",
        "Farmácias",
        "Postos de Combustível",
        "Eletrônicos",
        "Joalherias",
        "Artigos de Luxo",
        "Casas de Câmbio",
        "Cassinos",
        "Apostas",
        "Restaurante / Alimentação",
        "Transferência Financeira",
        "E-commerce / Eletrônicos",
        "Vestuário / Moda",
        "Educação / Ensino",
        "Streaming / Entretenimento Digital",
        "Outros"
    ]

    with st.form("form_transacao", clear_on_submit=False):

        st.markdown("**📋 Dados da Transação**")

        # ── Dados principais ──────────────────────────────────────────────────
        col1, col2 = st.columns(2)

        with col1:

            assoc_id = st.text_input(
                "ID do Associado",
                value=_fill["associado_id"] if _fill else "demo_user",
                placeholder="ex: assoc_001"
            )

            categoria = st.selectbox(
                "Categoria",
                options=categorias,
                index=(
                    categorias.index(_fill["categoria"])
                    if _fill and _fill["categoria"] in categorias
                    else 0
                )
            )

        with col2:

            valor = st.number_input(
                "Valor (R$)",
                min_value=0.01,
                max_value=999999.99,
                step=10.0,
                value=float(_fill["valor"]) if _fill else 150.0,
                format="%.2f"
            )

            cidade = st.text_input(
                "Cidade",
                value=(
                    _fill.get("cidade", "Porto Alegre")
                    if _fill else "Porto Alegre"
                ),
                placeholder="ex: São Paulo"
            )

        st.write("")

        # ── Coordenadas geográficas ───────────────────────────────────────────
        st.markdown("**📍 Localização da Transação**")

        coord_col1, coord_col2 = st.columns(2)

        with coord_col1:

            lat = st.number_input(
                "Latitude",
                value=(
                    float(_fill["latitude"])
                    if _fill else -30.0346
                ),
                format="%.4f",
                step=0.001
            )

        with coord_col2:

            lon = st.number_input(
                "Longitude",
                value=(
                    float(_fill["longitude"])
                    if _fill else -51.2177
                ),
                format="%.4f",
                step=0.001
            )

        st.write("")

        # ── Botão de análise ──────────────────────────────────────────────────
        submitted = st.form_submit_button(
            "🔍 Analisar Transação",
            use_container_width=True,
            type="primary"
        )

    # ── Processamento da transação ────────────────────────────────────────────
    if submitted:

        tx = {
            "transacao_id": f"tx-{int(time.time() * 1000)}",
            "associado_id": assoc_id.strip() or "demo_user",
            "valor": valor,
            "categoria": categoria,
            "cidade": cidade,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude": lat,
            "longitude": lon,
        }

        # ── Formatação do valor monetário ─────────────────────────────────────
        valor_fmt = (
            f"R$ {valor:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        # ── Registra mensagem do associado ────────────────────────────────────
        _add_msg(
            "user",
            f"📤 Analisar transação: "
            f"<strong>{valor_fmt}</strong> "
            f"em <strong>{categoria}</strong> — {cidade}<br>"
            f"<span style='font-size:0.82rem;opacity:0.8'>"
            f"Associado: {tx['associado_id']} &nbsp;·&nbsp; "
            f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
            f"</span>"
        )

        # ── Executa análise MCP ───────────────────────────────────────────────
        try:

            with st.spinner("🛡️ Agente analisando transação..."):

                # Motor de análise de risco
                analise = _analisar(tx)

                # Geração da explicação para o associado
                explicacao = json.loads(
                    explicar_risco_fraude(
                        json.dumps(
                            analise,
                            ensure_ascii=False
                        )
                    )
                )

                # Constrói resposta visual do agente
                html, role = _construir_mensagem_agente(
                    analise,
                    explicacao
                )

                # Adiciona resposta ao chat
                _add_msg(role, html)

                # ── Fluxo HITL para risco crítico ────────────────────────────
                if analise["score_risco"] > 70:

                    st.session_state.aguardando_resp = tx["transacao_id"]

                    st.session_state.ultima_analise = analise

                    _add_msg(
                        "system",
                        "⏸️ Fluxo de liquidação pausado — "
                        "aguardando sua confirmação abaixo."
                    )

                # ── Limpa exemplo selecionado ────────────────────────────────
                st.session_state.pop("_fill_tx", None)

        except Exception as e:

            _add_msg(
                "block",
                "❌ <strong>Erro ao processar a transação.</strong><br>"
                f"Detalhes: {str(e)}"
            )

        # Atualiza a interface
        st.rerun()


# ── Rodapé ────────────────────────────────────────────────────────────────────

st.markdown(
    """
<div class="ibm-footer">
    Sicredi · AI Experiential Learning Lab 2026
    &nbsp;|&nbsp;
    Motor MCP local · IBM watsonx Orchestrate (simulação)
    &nbsp;|&nbsp;
    <a href="https://github.com/samuel2k6/Projeto-Anti-fraude"
       target="_blank"
       rel="noopener noreferrer"
       style="color:#0f62fe;text-decoration:none">
       GitHub ↗
    </a>
</div>
    """,
    unsafe_allow_html=True
)
