param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [string]$ProjectDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Process = Get-CimInstance `
    -ClassName Win32_Process `
    -Filter "ProcessId = $ProcessId" `
    -ErrorAction SilentlyContinue

if ($null -eq $Process) {
    exit 0
}

$CommandLine = [string]$Process.CommandLine
$ExpectedScript = Join-Path `
    $ProjectDir `
    "serve_waitress.py"

if ([string]::IsNullOrWhiteSpace($CommandLine)) {
    throw (
        "Não foi possível validar a linha de comando do processo "
        + "$ProcessId. O processo não será encerrado por segurança."
    )
}

$HasExpectedScript = (
    $CommandLine.IndexOf(
        $ExpectedScript,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -ge 0
)

if (-not $HasExpectedScript) {
    throw (
        "O PID $ProcessId não pertence ao serve_waitress.py desta "
        + "instalação. O processo não será encerrado."
    )
}

& taskkill.exe `
    /PID $ProcessId `
    /T `
    /F | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "O Windows não conseguiu encerrar o servidor (PID $ProcessId)."
}

exit 0
