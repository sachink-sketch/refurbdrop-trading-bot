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


_HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "")


def heartbeat():
    """Ping a dead-man's-switch URL (e.g. healthchecks.io); it emails you when pings stop arriving."""
    if not _HEALTHCHECK_URL:
        return

    def _ping():
        try:
            requests.get(_HEALTHCHECK_URL, timeout=5)
        except Exception:
            pass

    threading.Thread(target=_ping, daemon=True).start()


def notify(text: str):
    if not (_TOKEN and _CHAT):
        return
    threading.Thread(target=_send, args=(text,), daemon=True).start()
