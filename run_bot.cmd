@echo off
rem Keeps the crypto bot running: restarts it 30s after any crash. Exit code 3 = already running elsewhere.
cd /d "C:\Users\almig\Documents\REFURBDROP\trading_bot"
:loop
"C:\Users\almig\AppData\Local\Programs\Python\Python312\python.exe" crypto\main_crypto.py >> logs\crypto_live_out.log 2>> logs\crypto_live_err.log
if %errorlevel%==3 exit /b 0
ping -n 31 127.0.0.1 >nul
goto loop
