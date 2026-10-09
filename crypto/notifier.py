"""Telegram trade alerts. No-op unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env."""
import os
import threading
import requests

_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")


def _send(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT, "text": text},
            timeout=5,
        )
    except Exception:
        pass


def notify(text: str):
    if not (_TOKEN and _CHAT):
        return
    threading.Thread(target=_send, args=(text,), daemon=True).start()
