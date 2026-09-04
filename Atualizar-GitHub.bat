@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo.
echo ============================================================
echo Financeiro OFX - Enviar alteracoes ao GitHub
echo Repositorio:
echo https://github.com/Th14g0R/financeiro-ofx
echo ============================================================
echo.

where git.exe >nul 2>&1

if errorlevel 1 (
    echo Git nao foi encontrado no PATH.
    echo Instale o Git for Windows e abra novamente este BAT.
    echo.
    pause
    exit /b 1
)

if not exist "github_sync.py" (
    echo ERRO: github_sync.py nao foi encontrado.
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "github_sync.py" push
) else (
    py -3.14 --version >nul 2>&1

    if errorlevel 1 (
        echo Python 3.14 nao foi encontrado.
        echo.
        pause
        exit /b 1
    )

    py -3.14 "github_sync.py" push
)

set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo Processo concluido.
) else (
    echo O GitHub nao foi atualizado.
    echo Revise a mensagem acima.
)

echo.
pause
endlocal
exit /b %EXITCODE%
