param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Open", "Close")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$Port
)

$ErrorActionPreference = "Stop"

$RuleName = "Financeiro OFX - Rede Local"

$Existing = Get-NetFirewallRule `
    -DisplayName $RuleName `
    -ErrorAction SilentlyContinue

if ($Existing) {
    $Existing | Remove-NetFirewallRule
}

if ($Action -eq "Open") {
    New-NetFirewallRule `
        -DisplayName $RuleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -Profile Private `
        -RemoteAddress LocalSubnet `
        -EdgeTraversalPolicy Block | Out-Null
}
