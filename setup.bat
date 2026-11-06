@echo off
REM =============================================================================
REM  setup.bat — Instalador do Projeto Anti-Fraude Sicredi (Windows)
REM =============================================================================
REM  Uso: setup.bat
REM  O script verifica o Python, cria um ambiente virtual e instala todas as
REM  dependências necessárias para rodar os servidores MCP e o pipeline de
REM  orquestração.
REM =============================================================================

setlocal enabledelayedexpansion

echo.
echo  ============================================================
echo   SETUP — Sistema Anti-Fraude Sicredi
echo  ============================================================
echo.

REM ── 1. Verificar Python ──────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    where python3 >nul 2>&1
    if errorlevel 1 (
        echo  [ERRO] Python nao encontrado.
        echo.
        echo  Instale o Python 3.11 ou superior em:
        echo    https://www.python.org/downloads/
        echo.
        echo  Dica: marque "Add Python to PATH" durante a instalacao.
        pause
        exit /b 1
    )
    set PYTHON=python3
) else (
    set PYTHON=python
)

REM Verifica versão mínima (3.11)
for /f "tokens=2 delims= " %%v in ('!PYTHON! --version 2^>^&1') do set PY_VERSION=%%v
echo  Python encontrado: !PY_VERSION!

for /f "tokens=1,2 delims=." %%a in ("!PY_VERSION!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if !PY_MAJOR! LSS 3 (
    echo  [ERRO] Python 3.11+ necessario. Versao encontrada: !PY_VERSION!
    pause
    exit /b 1
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 11 (
    echo  [ERRO] Python 3.11+ necessario. Versao encontrada: !PY_VERSION!
    pause
    exit /b 1
)
echo  [OK] Versao compativel.
echo.

REM ── 2. Criar ambiente virtual ─────────────────────────────────────────────
if not exist ".venv" (
    echo  Criando ambiente virtual em .venv ...
    !PYTHON! -m venv .venv
    if errorlevel 1 (
        echo  [ERRO] Falha ao criar ambiente virtual.
        pause
        exit /b 1
    )
    echo  [OK] Ambiente virtual criado.
) else (
    echo  [OK] Ambiente virtual .venv ja existe.
)
echo.

REM ── 3. Ativar venv e instalar dependências ────────────────────────────────
echo  Ativando ambiente virtual...
call .venv\Scripts\activate.bat

echo  Atualizando pip...
python -m pip install --upgrade pip --quiet

echo  Instalando dependencias (requirements.txt)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [ERRO] Falha ao instalar dependencias.
    pause
    exit /b 1
)
echo  [OK] Dependencias instaladas com sucesso.
echo.

REM ── 4. Verificar instalação do MCP ───────────────────────────────────────
python -c "import mcp; print('  [OK] mcp SDK importado: v' + mcp.__version__)"
if errorlevel 1 (
    echo  [ERRO] O pacote 'mcp' nao pode ser importado apos a instalacao.
    pause
    exit /b 1
)
echo.

REM ── 5. Instruções finais ──────────────────────────────────────────────────
echo  ============================================================
echo   SETUP CONCLUIDO COM SUCESSO
echo  ============================================================
echo.
echo  Para ativar o ambiente virtual manualmente:
echo    .venv\Scripts\activate.bat
echo.
echo  Para rodar o pipeline de orquestracao:
echo    python -m orchestration.pipeline
echo.
echo  Para rodar os testes do servidor MCP:
echo    python mcp_antifraude\test_server.py
echo.
echo  Para rodar os testes de orquestracao:
echo    python orchestration\test_orchestration.py
echo.
pause
endlocal
