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

# Reutiliza a tabela de estados do motor MCP (lat/lon já calibrados)
# Formato: sigla → (nome completo, lat_centro, lon_centro)
ESTADOS_BR = mcp_server.ESTADOS_BR

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
        # ── Casos SEM fraude ────────────────────────────────────────────────
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
        (
            "✅ Normal — Supermercado no padrão",
            {
                "transacao_id": "demo-n1", "associado_id": "demo_n1",
                "valor": 231.67, "categoria": "Supermercados",
                "cidade": "Porto Alegre", "estado": "RS",
                "timestamp": _now.replace(hour=11, minute=43).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -30.0346, "longitude": -51.2177,
            },
            # histórico: 3 compras no mesmo estado/cidade, média ~R$196
            [
                {"transacao_id": "hn1a", "associado_id": "demo_n1", "valor": 213.57,
                 "categoria": "Supermercados", "cidade": "Porto Alegre", "estado": "RS",
                 "timestamp": (_now - _td(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -30.0346, "longitude": -51.2177},
                {"transacao_id": "hn1b", "associado_id": "demo_n1", "valor": 178.29,
                 "categoria": "Supermercados", "cidade": "Porto Alegre", "estado": "RS",
                 "timestamp": (_now - _td(days=5)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -30.0346, "longitude": -51.2177},
                {"transacao_id": "hn1c", "associado_id": "demo_n1", "valor": 196.84,
                 "categoria": "Supermercados", "cidade": "Porto Alegre", "estado": "RS",
                 "timestamp": (_now - _td(days=8)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -30.0346, "longitude": -51.2177},
            ],
        ),
        # ── Casos COM alerta inter-estadual (novo) ──────────────────────────
        (
            "⚠️ PR → SP em 60 min — inter-estadual suspeito",
            {
                "transacao_id": "demo-g1", "associado_id": "demo_g1",
                "valor": 318.47, "categoria": "Eletrônicos",
                "cidade": "São Paulo", "estado": "SP",
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -23.5505, "longitude": -46.6333,
            },
            # PR→SP ≈ 341 km em 60 min → 341 km/h — improvável por via terrestre (SUSPEITO)
            [
                {"transacao_id": "hg1a", "associado_id": "demo_g1", "valor": 214.93,
                 "categoria": "Supermercados", "cidade": "Curitiba", "estado": "PR",
                 "timestamp": (_now - _td(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -25.4297, "longitude": -49.2716},
            ],
        ),
        (
            "⚠️ MG → RJ em 90 min — mudança inter-estadual",
            {
                "transacao_id": "demo-g2", "associado_id": "demo_g2",
                "valor": 476.19, "categoria": "Restaurantes",
                "cidade": "Rio de Janeiro", "estado": "RJ",
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -22.9068, "longitude": -43.1729,
            },
            # MG→RJ ≈ 341 km em 90 min → 228 km/h — suspeito por via terrestre
            [
                {"transacao_id": "hg2a", "associado_id": "demo_g2", "valor": 312.84,
                 "categoria": "Supermercados", "cidade": "Belo Horizonte", "estado": "MG",
                 "timestamp": (_now - _td(minutes=90)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -19.9167, "longitude": -43.9345},
            ],
        ),
        # ── Casos COM fraude: alerta (score 1–70) ──────────────────────────
        (
            "⚠️ Pico — Eletrônicos 4.6x acima",
            {
                "transacao_id": "demo-a1", "associado_id": "demo_a1",
                "valor": 1847.63, "categoria": "Eletrônicos",
                "cidade": "Fortaleza", "estado": "CE",
                "timestamp": _now.replace(hour=16, minute=54).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -3.7172, "longitude": -38.5433,
            },
            # histórico: 2 compras de eletrônicos no CE, média ~R$405
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
        (
            "🔴 Cassino 04h38 — pico + perfil (ALTO)",
            {
                "transacao_id": "demo-a3", "associado_id": "demo_a3",
                "valor": 4256.17, "categoria": "Cassinos",
                "cidade": "Belo Horizonte", "estado": "MG",
                "timestamp": _now.replace(hour=4, minute=38).strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -19.9167, "longitude": -43.9345,
            },
            # histórico: 2 compras pequenas no MG, média ~R$145 → valor 4256 = 29x acima
            [
                {"transacao_id": "hca1", "associado_id": "demo_a3", "valor": 156.38,
                 "categoria": "Restaurantes", "cidade": "Belo Horizonte", "estado": "MG",
                 "timestamp": (_now - _td(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -19.9167, "longitude": -43.9345},
                {"transacao_id": "hca2", "associado_id": "demo_a3", "valor": 134.71,
                 "categoria": "Supermercados", "cidade": "Belo Horizonte", "estado": "MG",
                 "timestamp": (_now - _td(days=3)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -19.9167, "longitude": -43.9345},
            ],
        ),
        # ── Casos COM fraude: CRÍTICO (score > 70) — aciona HITL ───────────
        (
            "🚨 GPS Impossível — RS → Tóquio (CRÍTICO)",
            {
                "transacao_id": "demo-f1", "associado_id": "demo_f1",
                "valor": 1247.83, "categoria": "Restaurante / Alimentação",
                "cidade": "Tóquio", "estado": "RS",  # estado RS para o seletor
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": 35.6762, "longitude": 139.6503,
            },
            # histórico: 1 compra em Porto Alegre (RS) há 12 min → 18.822 km = 94.115 km/h
            [
                {"transacao_id": "hf1a", "associado_id": "demo_f1", "valor": 143.78,
                 "categoria": "Supermercados", "cidade": "Porto Alegre", "estado": "RS",
                 "timestamp": (_now - _td(minutes=12)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -30.0346, "longitude": -51.2177},
            ],
        ),
        (
            "🚨 GPS — DF → Buenos Aires (CRÍTICO)",
            {
                "transacao_id": "demo-f2", "associado_id": "demo_f2",
                "valor": 1893.54, "categoria": "Artigos de Luxo",
                "cidade": "Buenos Aires", "estado": "DF",
                "timestamp": _now.strftime("%Y-%m-%dT%H:%M:%S"),
                "latitude": -34.6037, "longitude": -58.3816,
            },
            # histórico: 1 compra em Brasília (DF) há 8 min → 2.338 km = 17.541 km/h
            [
                {"transacao_id": "hf2a", "associado_id": "demo_f2", "valor": 198.37,
                 "categoria": "Supermercados", "cidade": "Brasília", "estado": "DF",
                 "timestamp": (_now - _td(minutes=8)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -15.7801, "longitude": -47.9292},
                {"transacao_id": "hf2b", "associado_id": "demo_f2", "valor": 217.64,
                 "categoria": "Restaurantes", "cidade": "Brasília", "estado": "DF",
                 "timestamp": (_now - _td(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "latitude": -15.7805, "longitude": -47.9285},
            ],
        ),
    ]

    for label, tx, hist_injectar in EXEMPLOS:
        if st.button(label, use_container_width=True, key=f"btn_{label[:12]}"):
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
        st.markdown("**📋 Dados da Transação**")

        # ── Linha 1: Associado | Categoria | Valor ────────────────────────
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            assoc_id = st.text_input(
                "ID do Associado",
                value=_fill["associado_id"] if _fill else "demo_user",
                placeholder="ex: assoc_001",
            )

        _cats = [
            "Supermercados", "Restaurantes", "Farmácias",
            "Postos de Combustível", "Eletrônicos", "Joalherias",
            "Artigos de Luxo", "Casas de Câmbio", "Cassinos", "Apostas",
            "Restaurante / Alimentação", "Transferência Financeira",
            "E-commerce / Eletrônicos", "Vestuário / Moda", "Educação / Ensino",
            "Streaming / Entretenimento Digital", "Outros",
        ]
        with col2:
            categoria = st.selectbox(
                "Categoria",
                options=_cats,
                index=(
                    _cats.index(_fill["categoria"])
                    if _fill and _fill.get("categoria") in _cats
                    else 0
                ),
            )

        with col3:
            valor = st.number_input(
                "Valor (R$)",
                min_value=0.01, max_value=999999.99, step=10.0,
                value=float(_fill["valor"]) if _fill else 150.0,
                format="%.2f",
            )

        # ── Linha 2: Estado (seletor) | Cidade (texto) | Lat | Lon ────────
        # Determina o estado inicial (do _fill ou padrão RS)
        _fill_estado = _fill.get("estado") if _fill else None
        if not _fill_estado and _fill:
            # Infere pelo centróide mais próximo das coords do _fill
            _fill_estado = mcp_server._estado_da_coordenada(
                float(_fill["latitude"]), float(_fill["longitude"])
            )
        _fill_estado = _fill_estado or "RS"
        _fill_opcao  = next(
            (o for o in _OPCOES_ESTADO if o.startswith(_fill_estado + " ")), _OPCOES_ESTADO[0]
        )

        col4, col5, col6, col7 = st.columns([2, 2, 1, 1])
        with col4:
            estado_opcao = st.selectbox(
                "Estado",
                options=_OPCOES_ESTADO,
                index=_OPCOES_ESTADO.index(_fill_opcao),
                help="Selecione o estado. Latitude e longitude são preenchidos automaticamente.",
            )
            estado_sigla = _SIGLA_DE_OPCAO[estado_opcao]
            _, _lat_est, _lon_est = ESTADOS_BR[estado_sigla]

        with col5:
            cidade = st.text_input(
                "Cidade",
                value=_fill.get("cidade", "") if _fill else "",
                placeholder="ex: Porto Alegre",
            )

        with col6:
            lat = st.number_input(
                "Latitude",
                value=float(_fill["latitude"]) if _fill else _lat_est,
                format="%.4f", step=0.0001,
                help="Preenchido automaticamente pelo estado. Edite para precisão.",
            )

        with col7:
            lon = st.number_input(
                "Longitude",
                value=float(_fill["longitude"]) if _fill else _lon_est,
                format="%.4f", step=0.0001,
                help="Preenchido automaticamente pelo estado. Edite para precisão.",
            )

        submitted = st.form_submit_button(
            "🔍 Analisar Transação",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        tx = {
            "transacao_id": f"tx-{int(time.time()*1000)}",
            "associado_id": assoc_id.strip() or "demo_user",
            "valor":        valor,
            "categoria":    categoria,
            "cidade":       cidade or estado_opcao.split(" — ")[-1],
            "estado":       estado_sigla,
            "timestamp":    datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "latitude":     lat,
            "longitude":    lon,
        }

        # Mensagem do usuário no chat
        valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        cidade_exib = tx["cidade"]
        _add_msg("user",
            f"📤 Analisar transação: <strong>{valor_fmt}</strong> em "
            f"<strong>{categoria}</strong> — {cidade_exib} ({estado_sigla})<br>"
            f"<span style='font-size:0.82rem;opacity:0.8'>Associado: {tx['associado_id']} &nbsp;·&nbsp; "
            f"{datetime.now().strftime('%d/%m/%Y %H:%M')}</span>"
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