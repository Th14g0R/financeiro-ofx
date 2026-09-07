param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Remove", "Run")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$TaskName,

    [string]$Pythonw,
    [string]$Manager,
    [string]$RunAsUser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ExistingTask {
    $Task = Get-ScheduledTask `
        -TaskName $TaskName `
        -ErrorAction SilentlyContinue

    return $Task
}

if ($Action -eq "Remove") {
    $Existing = Get-ExistingTask

    if ($null -ne $Existing) {
        Unregister-ScheduledTask `
            -TaskName $TaskName `
            -Confirm:$false
    }

    exit 0
}

if ($Action -eq "Run") {
    $Existing = Get-ExistingTask

    if ($null -eq $Existing) {
        throw "A tarefa '$TaskName' não está registrada."
    }

    Start-ScheduledTask `
        -TaskName $TaskName

    exit 0
}

if ([string]::IsNullOrWhiteSpace($Pythonw)) {
    throw "Pythonw não informado."
}

if ([string]::IsNullOrWhiteSpace($Manager)) {
    throw "Gerenciador não informado."
}

if ([string]::IsNullOrWhiteSpace($RunAsUser)) {
    throw "Usuário do Windows não informado."
}

if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "pythonw.exe não encontrado: $Pythonw"
}

if (-not (Test-Path -LiteralPath $Manager -PathType Leaf)) {
    throw "Gerenciador não encontrado: $Manager"
}

$WorkingDirectory = Split-Path `
    -Parent `
    $Manager

$ManagerArgument = '"' + $Manager + '" --start'

$TaskAction = New-ScheduledTaskAction `
    -Execute $Pythonw `
    -Argument $ManagerArgument `
    -WorkingDirectory $WorkingDirectory

$TaskTrigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $RunAsUser

# Interactive + Limited: a tarefa inicia somente quando o proprietário
# entra no Windows e o servidor NÃO recebe privilégios administrativos.
$TaskPrincipal = New-ScheduledTaskPrincipal `
    -UserId $RunAsUser `
    -LogonType Interactive `
    -RunLevel Limited

$TaskSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$Task = New-ScheduledTask `
    -Action $TaskAction `
    -Trigger $TaskTrigger `
    -Principal $TaskPrincipal `
    -Settings $TaskSettings `
    -Description "Inicia o Financeiro OFX ao entrar no Windows."

Register-ScheduledTask `
    -TaskName $TaskName `
    -InputObject $Task `
    -Force | Out-Null

$Registered = Get-ExistingTask

if ($null -eq $Registered) {
    throw "A tarefa foi criada, mas não pôde ser confirmada."
}

exit 0
