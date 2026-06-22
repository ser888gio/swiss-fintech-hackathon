<#
.SYNOPSIS
  Send a test /sign approval request to the local Firefly bridge.

.DESCRIPTION
  Builds a well-formed BridgeSignRequest and POSTs it to the bridge so you can
  exercise the device button press without going through the web dashboard.
  All fields have placeholder defaults; override any of them with parameters.

.EXAMPLE
  ./scripts/test-sign.ps1
  # Sends the default placeholder payment.

.EXAMPLE
  ./scripts/test-sign.ps1 -Amount 75000 -Dest rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe
  # Override individual fields.

.EXAMPLE
  ./scripts/test-sign.ps1 -BridgeUrl http://localhost:4747 -Health
  # Hit /health first to print the device public key, then sign.
#>
[CmdletBinding()]
param(
    [string] $BridgeUrl          = "http://localhost:4747",
    [string] $PaymentId          = "test-001",
    [double] $Amount             = 50000.00,
    [string] $Currency           = "RLUSD",
    [string] $Dest               = "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
    [string] $Reference          = "Demo payment",
    [string] $Network            = "xrpl:testnet",
    [string] $Owner              = "rDsbeomae4FXwgQTJp9Rs64Qg9vDiTCdBv",
    [int]    $EscrowSequence     = 12345,
    [string] $EscrowCreateTxHash = "A1B2C3D4E5F600000000000000000000000000000000000000000000000000FF",
    [switch] $Health
)

$ErrorActionPreference = "Stop"

if ($Health) {
    Write-Host "Checking bridge health at $BridgeUrl/health ..." -ForegroundColor DarkCyan
    $h = Invoke-RestMethod -Uri "$BridgeUrl/health" -Method Get
    Write-Host "  status:    $($h.status)"
    Write-Host "  publicKey: $($h.publicKey)"
    Write-Host ""
}

$body = @{
    paymentId          = $PaymentId
    amount             = $Amount
    currency           = $Currency
    dest               = $Dest
    reference          = $Reference
    network            = $Network
    owner              = $Owner
    escrowSequence     = $EscrowSequence
    escrowCreateTxHash = $EscrowCreateTxHash
} | ConvertTo-Json

Write-Host "Sending approval request -> watch the Firefly and press APPROVE..." -ForegroundColor Cyan
try {
    $res = Invoke-RestMethod -Uri "$BridgeUrl/sign" -Method Post -ContentType 'application/json' -Body $body
    Write-Host "Signed." -ForegroundColor Green
    $res | ConvertTo-Json
} catch {
    Write-Host "Sign request failed:" -ForegroundColor Red
    $resp = $_.Exception.Response
    if ($resp) {
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        Write-Host $reader.ReadToEnd() -ForegroundColor Red
    } else {
        Write-Host $_.Exception.Message -ForegroundColor Red
    }
    exit 1
}
