' Starts run_bot.cmd with no visible window, so closing a window can never stop the bot.
CreateObject("WScript.Shell").Run "cmd /c ""C:\Users\almig\Documents\REFURBDROP\trading_bot\run_bot.cmd""", 0, False
