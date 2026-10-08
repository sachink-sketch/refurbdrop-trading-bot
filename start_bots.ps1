Set-Location "C:\Users\almig\Documents\REFURBDROP\trading_bot"

# Kill existing python processes
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Rotate logs — keep last 5000 lines to avoid huge files
foreach ($log in @("logs\crypto_live_out.log","logs\crypto_live_err.log","logs\stock_out.log","logs\stock_err.log")) {
    if (Test-Path $log) {
        $lines = Get-Content $log -Tail 5000
        $lines | Set-Content $log -Encoding utf8
    }
}

# Start crypto bot (--live auto-detected from CRYPTO_EXCHANGE in .env)
$cryptoLog = "logs\crypto_live_out.log"
$cryptoErr = "logs\crypto_live_err.log"
Start-Process -FilePath "python" `
    -ArgumentList "-W", "ignore", "-u", "crypto/main_crypto.py" `
    -WorkingDirectory (Get-Location) `
    -RedirectStandardOutput $cryptoLog `
    -RedirectStandardError $cryptoErr `
    -WindowStyle Hidden
Write-Host "Crypto bot started -> $cryptoLog"

Start-Sleep -Seconds 3

# Start stock bot
$stockLog = "logs\stock_out.log"
$stockErr = "logs\stock_err.log"
Start-Process -FilePath "python" `
    -ArgumentList "-W", "ignore", "-u", "main.py" `
    -WorkingDirectory (Get-Location) `
    -RedirectStandardOutput $stockLog `
    -RedirectStandardError $stockErr `
    -WindowStyle Hidden
Write-Host "Stock bot started -> $stockLog"

Write-Host "Both bots running. Check logs/ for output."
