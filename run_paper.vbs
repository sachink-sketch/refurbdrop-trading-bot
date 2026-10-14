' Runs the forward paper test once, hidden. Scheduled hourly; each run is idempotent.
CreateObject("WScript.Shell").Run "cmd /c ""cd /d C:\Users\almig\Documents\REFURBDROP\trading_bot && C:\Users\almig\AppData\Local\Programs\Python\Python312\python.exe crypto\paper_trend.py >> logs\paper_trend.log 2>&1""", 0, False
