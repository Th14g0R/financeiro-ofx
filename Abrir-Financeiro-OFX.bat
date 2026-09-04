@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo.
    echo === Financeiro OFX ===
    echo Ambiente virtual nao encontrado.
    echo Abra primeiro:
    echo   Gerenciar-Financeiro-OFX.bat
    echo e execute "Instalar / Atualizar".
    echo.
    pause
    exit /b 1
)

if not exist "windows_manager.py" (
    echo.
    echo ERRO: windows_manager.py nao foi encontrado.
    echo Confirme se este BAT esta dentro da pasta do Financeiro OFX.
    echo.
    pause
    exit /b 1
)

"%PYTHON%" "windows_manager.py" --start

if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar o Financeiro OFX.
    echo Consulte:
    echo   logs\manager.log
    echo.
    pause
    exit /b 1
)

start "" "http://127.0.0.1:8000/"

endlocal
exit /b 0
