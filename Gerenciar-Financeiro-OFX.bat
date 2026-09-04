@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist "requirements.txt" (
    echo.
    echo ERRO: requirements.txt nao foi encontrado.
    echo Confirme se este BAT esta dentro da pasta do Financeiro OFX.
    echo.
    pause
    exit /b 1
)

if not exist "windows_manager.py" (
    echo.
    echo ERRO: windows_manager.py nao foi encontrado.
    echo.
    pause
    exit /b 1
)

if not exist "github_sync.py" (
    echo.
    echo ERRO: github_sync.py nao foi encontrado.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo === Financeiro OFX - Preparacao inicial ===
    echo Verificando Python 3.14...

    py -3.14 --version >nul 2>&1

    if errorlevel 1 (
        echo.
        echo Python 3.14 nao foi encontrado pelo launcher "py".
        echo Instale o Python 3.14 e abra novamente este BAT.
        echo.
        pause
        exit /b 1
    )

    echo Criando ambiente virtual...
    py -3.14 -m venv .venv

    if errorlevel 1 (
        echo.
        echo Nao foi possivel criar o ambiente virtual.
        echo.
        pause
        exit /b 1
    )

    echo Atualizando pip...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip

    if errorlevel 1 (
        echo.
        echo Falha ao atualizar o pip.
        echo.
        pause
        exit /b 1
    )

    echo Instalando dependencias iniciais...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt

    if errorlevel 1 (
        echo.
        echo Falha ao instalar dependencias.
        echo.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo Python GUI nao encontrado no ambiente virtual.
    echo Recrie a .venv ou execute setup.ps1 para diagnostico.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m py_compile "windows_manager.py" "github_sync.py"

if errorlevel 1 (
    echo.
    echo ERRO: foi encontrada uma falha de sintaxe no Gerenciador/GitHub.
    echo O Gerenciador nao sera aberto.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import tkinter" >nul 2>&1

if errorlevel 1 (
    echo.
    echo ERRO: Tkinter nao esta disponivel nesta instalacao do Python.
    echo.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "windows_manager.py"

if errorlevel 1 (
    echo.
    echo Nao foi possivel abrir o Gerenciador.
    echo.
    pause
    exit /b 1
)

endlocal
exit /b 0
