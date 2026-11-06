#!/usr/bin/env bash
# =============================================================================
#  setup.sh — Instalador do Projeto Anti-Fraude Sicredi (Linux / macOS)
# =============================================================================
#  Uso: bash setup.sh
#  O script verifica o Python, cria um ambiente virtual e instala todas as
#  dependências necessárias para rodar os servidores MCP e o pipeline de
#  orquestração.
# =============================================================================

set -euo pipefail

echo ""
echo " ============================================================"
echo "  SETUP — Sistema Anti-Fraude Sicredi"
echo " ============================================================"
echo ""

# ── 1. Verificar Python ──────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo " [ERRO] Python não encontrado."
    echo ""
    echo " Instale o Python 3.11 ou superior:"
    echo "   Ubuntu/Debian : sudo apt install python3.11 python3.11-venv"
    echo "   macOS (brew)  : brew install python@3.11"
    echo "   Download      : https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$("$PYTHON" --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

echo " Python encontrado: $PYTHON  ($PY_VERSION)"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo " [ERRO] Python 3.11+ necessário. Versão encontrada: $PY_VERSION"
    exit 1
fi
echo " [OK] Versão compatível."
echo ""

# ── 2. Criar ambiente virtual ─────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo " Criando ambiente virtual em .venv ..."
    "$PYTHON" -m venv .venv
    echo " [OK] Ambiente virtual criado."
else
    echo " [OK] Ambiente virtual .venv já existe."
fi
echo ""

# ── 3. Ativar venv e instalar dependências ────────────────────────────────
# shellcheck disable=SC1091
source .venv/bin/activate

echo " Atualizando pip..."
pip install --upgrade pip --quiet

echo " Instalando dependências (requirements.txt)..."
pip install -r requirements.txt

echo " [OK] Dependências instaladas com sucesso."
echo ""

# ── 4. Verificar instalação do MCP ───────────────────────────────────────
python -c "import mcp; print(' [OK] mcp SDK importado: v' + mcp.__version__)"
echo ""

# ── 5. Instruções finais ──────────────────────────────────────────────────
echo " ============================================================"
echo "  SETUP CONCLUÍDO COM SUCESSO"
echo " ============================================================"
echo ""
echo " Para ativar o ambiente virtual manualmente:"
echo "   source .venv/bin/activate"
echo ""
echo " Para rodar o pipeline de orquestração:"
echo "   python -m orchestration.pipeline"
echo ""
echo " Para rodar os testes do servidor MCP:"
echo "   python mcp_antifraude/test_server.py"
echo ""
echo " Para rodar os testes de orquestração:"
echo "   python orchestration/test_orchestration.py"
echo ""
