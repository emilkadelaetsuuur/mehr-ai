"""Telegram notifications for staff. Each account binds its own chat with a one-time code:
the user opens t.me/<bot>?start=<code>, the bot stores the chat id, alerts then go to that person.
Runs only when TELEGRAM_BOT_TOKEN is set."""

import logging
import threading

import httpx

from . import config
from .db import SessionLocal, User

log = logging.getLogger("nigoh.telegram")
API = "https://api.telegram.org/bot"
_bot = {"username": None}


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN)


def send(chat_id, text):
    if not enabled() or not chat_id:
        return False
    try:
        return httpx.post(f"{API}{config.TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=6).status_code == 200
    except Exception:
        return False


def recipients(db, role, level):
    """Who gets a notice: accounts of that role; red notices also reach the head of the district."""
    roles = {role} | ({"rahbar"} if level == "red" else set())
    return [u.telegram_chat_id for u in db.query(User).filter(User.role.in_(roles), User.telegram_chat_id.isnot(None))]


def link_for(user):
    return f"https://t.me/{_bot['username']}?start={user.link_code}" if enabled() and _bot["username"] else None


def handle_update(db, update):
    """Bind a chat on '/start <code>'. Returns the reply text (also used by tests)."""
    msg = update.get("message") or {}
    text, chat = (msg.get("text") or "").strip(), (msg.get("chat") or {}).get("id")
    if not chat or not text.startswith("/start"):
        return None
    code = text[6:].strip()
    user = db.query(User).filter(User.link_code == code).first() if code else None
    if not user:
        return "Kod topilmadi. Mehr AI tizimidagi profilingizdan havolani oching."
    user.telegram_chat_id = str(chat)
    db.commit()
    return f"Ulandi: {user.full_name}. Endi bildirishnomalar shu yerga keladi."


def poll(stop: threading.Event):
    if not enabled():
        return
    try:
        _bot["username"] = httpx.get(f"{API}{config.TELEGRAM_BOT_TOKEN}/getMe", timeout=10).json()["result"]["username"]
    except Exception as e:
        log.warning("telegram bot unavailable: %s", e)
        return
    offset = 0
    while not stop.is_set():
        try:
            res = httpx.get(f"{API}{config.TELEGRAM_BOT_TOKEN}/getUpdates", params={"timeout": 25, "offset": offset}, timeout=35).json()
            for up in res.get("result", []):
                offset = up["update_id"] + 1
                with SessionLocal() as db:
                    reply = handle_update(db, up)
                if reply:
                    send(up["message"]["chat"]["id"], reply)
        except Exception:
            stop.wait(5)
