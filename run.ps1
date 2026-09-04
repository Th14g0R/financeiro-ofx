$ErrorActionPreference = "Stop"

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Ambiente virtual nao encontrado. Execute primeiro: .\setup.ps1"
}

& $Python serve_waitress.py
