# Manual hardware test: sends one approval request to the local bridge,
# which forwards it to the Firefly device. Press APPROVE on the device within 30s.
$body = @{
    paymentId          = "test-001"
    amount             = 125000.50
    currency           = "USD"
    dest               = "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe"
    network            = "XRPL Testnet"
    owner              = "rOwnerAddr123456789abcdef"
    escrowSequence     = 42
    escrowCreateTxHash = "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789"
    reference          = "Invoice 2026-Q2"
} | ConvertTo-Json -Compress

Write-Host "Sending approval request -> watch the Firefly and press APPROVE..." -ForegroundColor Cyan
Invoke-RestMethod -Uri http://localhost:4747/sign -Method Post -ContentType 'application/json' -Body $body
