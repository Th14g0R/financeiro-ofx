$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Financeiro OFX - Configuracao ===" -ForegroundColor Cyan
Write-Host ""


function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @(),

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command @Arguments

    $ExitCode = $LASTEXITCODE

    if ($ExitCode -ne 0) {
        throw "$Description falhou com codigo de saida $ExitCode."
    }
}


function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Test-Path ".env")) {
        return $null
    }

    $Pattern = "^\s*" + [regex]::Escape($Name) + "\s*=(.*)$"

    foreach ($Line in Get-Content ".env") {
        $Match = [regex]::Match($Line, $Pattern)

        if ($Match.Success) {
            return $Match.Groups[1].Value.Trim()
        }
    }

    return $null
}


function Ensure-EnvSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    $Existing = Get-EnvValue -Name $Name

    if ($null -eq $Existing) {
        Add-Content `
            -Path ".env" `
            -Value "$Name=$Value" `
            -Encoding utf8
    }
}


function Set-EnvSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    $Content = Get-Content ".env" -Raw
    $Pattern = "(?m)^\s*" + [regex]::Escape($Name) + "\s*=.*$"
    $Replacement = "$Name=$Value"

    if ([regex]::IsMatch($Content, $Pattern)) {
        $Content = [regex]::Replace(
            $Content,
            $Pattern,
            $Replacement
        )

        Set-Content `
            -Path ".env" `
            -Value $Content `
            -Encoding utf8
    }
    else {
        Add-Content `
            -Path ".env" `
            -Value $Replacement `
            -Encoding utf8
    }
}



if (-not (Test-Path ".venv")) {
    Write-Host "Criando ambiente virtual..."

    Invoke-NativeChecked `
        -Command "py" `
        -Arguments @("-3.14", "-m", "venv", ".venv") `
        -Description "Criacao do ambiente virtual"
}


$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"


if (-not (Test-Path $Python)) {
    throw "Python do ambiente virtual nao encontrado em: $Python"
}


if (-not (Test-Path ".env")) {
    Write-Host "Criando .env local seguro..."

    $Secret = & $Python -c "import secrets; print(secrets.token_urlsafe(64))"

    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao gerar DJANGO_SECRET_KEY."
    }

    $CredentialKey = & $Python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii'))"

    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao gerar FINANCEIRO_CREDENTIAL_KEY."
    }

    @"
DJANGO_SECRET_KEY=$Secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_SECURE_MODE=False
DJANGO_TRUST_PROXY_SSL_HEADER=False
DJANGO_CSRF_TRUSTED_ORIGINS=
FINANCEIRO_HOST=127.0.0.1
FINANCEIRO_PORT=8000
FINANCEIRO_ALLOW_NETWORK=False
FINANCEIRO_LAN_MODE=False
FINANCEIRO_CREDENTIAL_KEY=$CredentialKey
LOGIN_THROTTLE_USERNAME_MAX=5
LOGIN_THROTTLE_IP_MAX=20
LOGIN_THROTTLE_WINDOW_SECONDS=900
LOGIN_THROTTLE_LOCK_SECONDS=900
DJANGO_SESSION_AGE_SECONDS=1800
DJANGO_HSTS_SECONDS=3600
DJANGO_HSTS_INCLUDE_SUBDOMAINS=False
"@ | Set-Content ".env" -Encoding utf8
}
else {
    Write-Host ".env existente preservado."

    $CredentialKey = Get-EnvValue -Name "FINANCEIRO_CREDENTIAL_KEY"

    if ([string]::IsNullOrWhiteSpace($CredentialKey)) {
        $CredentialKey = & $Python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii'))"

        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao gerar FINANCEIRO_CREDENTIAL_KEY."
        }

        # Se a chave nao existia, grava. Se existia vazia, substitui a linha.
        $Content = Get-Content ".env" -Raw

        if ($Content -match "(?m)^\s*FINANCEIRO_CREDENTIAL_KEY\s*=") {
            $Content = [regex]::Replace(
                $Content,
                "(?m)^\s*FINANCEIRO_CREDENTIAL_KEY\s*=.*$",
                "FINANCEIRO_CREDENTIAL_KEY=$CredentialKey"
            )
            Set-Content ".env" -Value $Content -Encoding utf8
        }
        else {
            Add-Content ".env" "FINANCEIRO_CREDENTIAL_KEY=$CredentialKey" -Encoding utf8
        }
    }

    Ensure-EnvSetting -Name "DJANGO_SECURE_MODE" -Value "False"
    Ensure-EnvSetting -Name "DJANGO_TRUST_PROXY_SSL_HEADER" -Value "False"
    Ensure-EnvSetting -Name "DJANGO_CSRF_TRUSTED_ORIGINS" -Value ""
    Ensure-EnvSetting -Name "FINANCEIRO_HOST" -Value "127.0.0.1"
    Ensure-EnvSetting -Name "FINANCEIRO_PORT" -Value "8000"
    Ensure-EnvSetting -Name "FINANCEIRO_ALLOW_NETWORK" -Value "False"
    Ensure-EnvSetting -Name "FINANCEIRO_LAN_MODE" -Value "False"
    Ensure-EnvSetting -Name "LOGIN_THROTTLE_USERNAME_MAX" -Value "5"
    Ensure-EnvSetting -Name "LOGIN_THROTTLE_IP_MAX" -Value "20"
    Ensure-EnvSetting -Name "LOGIN_THROTTLE_WINDOW_SECONDS" -Value "900"
    Ensure-EnvSetting -Name "LOGIN_THROTTLE_LOCK_SECONDS" -Value "900"
    Ensure-EnvSetting -Name "DJANGO_SESSION_AGE_SECONDS" -Value "1800"
    Ensure-EnvSetting -Name "DJANGO_HSTS_SECONDS" -Value "3600"
    Ensure-EnvSetting -Name "DJANGO_HSTS_INCLUDE_SUBDOMAINS" -Value "False"
}


# Instalações/atualizações normais do Financeiro OFX não devem rodar
# com páginas de erro detalhadas expostas.
Set-EnvSetting -Name "DJANGO_DEBUG" -Value "False"

Write-Host "Atualizando pip..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("-m", "pip", "install", "--upgrade", "pip") `
    -Description "Atualizacao do pip"


Write-Host "Instalando dependencias..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("-m", "pip", "install", "-r", "requirements.txt") `
    -Description "Instalacao das dependencias"


Write-Host "Validando configuracao..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "check") `
    -Description "Validacao do Django"


Write-Host "Conferindo se models e migrations estao sincronizados..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @(
        "manage.py",
        "makemigrations",
        "--check",
        "--dry-run"
    ) `
    -Description "Validacao de models e migrations"


Write-Host "Executando testes antes de alterar o banco local..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "test") `
    -Description "Execucao dos testes"


$BackupDir = Join-Path $PSScriptRoot "backups"

if (Test-Path "db.sqlite3") {
    New-Item `
        -ItemType Directory `
        -Path $BackupDir `
        -Force | Out-Null

    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupPath = Join-Path $BackupDir "db-before-update-$Timestamp.sqlite3"

    Copy-Item `
        -Path "db.sqlite3" `
        -Destination $BackupPath `
        -Force

    Write-Host "Backup criado: $BackupPath"
}


Write-Host "Aplicando migrations..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "migrate") `
    -Description "Aplicacao das migrations"


Write-Host "Reconstruindo contrapartes..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "rebuild_counterparties") `
    -Description "Reconstrucao de contrapartes"


Write-Host "Analisando transferencias entre contas proprias..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "analyze_internal_transfers") `
    -Description "Analise de transferencias internas"


Write-Host "Coletando arquivos estaticos..."

Invoke-NativeChecked `
    -Command $Python `
    -Arguments @("manage.py", "collectstatic", "--noinput") `
    -Description "Coleta de arquivos estaticos"


$SecureMode = Get-EnvValue -Name "DJANGO_SECURE_MODE"

if (
    $SecureMode -and
    $SecureMode.ToLowerInvariant() -in @("1", "true", "yes", "on")
) {
    Write-Host "Executando checklist de deploy seguro..."

    Invoke-NativeChecked `
        -Command $Python `
        -Arguments @("manage.py", "check", "--deploy") `
        -Description "Checklist de seguranca do Django"
}


Write-Host ""
Write-Host "Etapa configurada com sucesso." -ForegroundColor Green
Write-Host ""
Write-Host "Para iniciar:"
Write-Host "  .\run.ps1"
Write-Host ""
Write-Host "Ou use:"
Write-Host "  Gerenciar-Financeiro-OFX.bat"
Write-Host ""
Write-Host "Se ainda nao existir um administrador:"
Write-Host "  .\.venv\Scripts\python.exe manage.py createsuperuser"
Write-Host ""
