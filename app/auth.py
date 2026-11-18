"""Personal accounts: salted password hashes, signed session cookie, demo users."""

import hashlib
import hmac
import secrets
import time

from . import config
from .db import User

COOKIE = "nigoh_auth"
DEMO_USERS = [
    ("rahbar", "Tuman tibbiyot birlashmasi rahbari", "rahbar", None),
    ("mutaxassis", "Akusher-ginekolog Karimova N.", "mutaxassis", None),
    ("shifokor", "Oilaviy shifokor Qosimova D.", "shifokor", "Qosimova D."),
    ("hamshira", "Patronaj hamshirasi Tosheva M.", "hamshira", None),
]


def hash_password(password: str, salt: str = "") -> str:
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()


def check_password(password: str, stored: str) -> bool:
    salt = (stored or "$").split("$")[0]
    return bool(stored) and hmac.compare_digest(hash_password(password, salt), stored)


def _sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_session(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time()) + config.SESSION_DAYS * 86400}"
    return f"{payload}.{_sign(payload)}"


def read_session(cookie: str):
    """Return the user id from a valid, unexpired cookie, else None."""
    try:
        uid, exp, sig = (cookie or "").split(".")
        if hmac.compare_digest(sig.encode(), _sign(f"{uid}.{exp}").encode()) and int(exp) > time.time():
            return int(uid)
    except ValueError:  # malformed or foreign cookie (including one left by an older version)
        pass
    return None


def clean_password(password: str) -> str:
    """Spaces and invisible characters around a password come from copy-paste, never from intent."""
    return (password or "").strip().strip("​‌‍﻿").strip()


# Sign-in throttle: a burst of wrong passwords from one address is slowed down, not locked out for long.
MAX_FAILURES, WINDOW_SEC = 20, 300
_failures: dict[str, list[float]] = {}


def throttled(ip: str) -> bool:
    recent = [t for t in _failures.get(ip, []) if t > time.time() - WINDOW_SEC]
    _failures[ip] = recent
    return len(recent) >= MAX_FAILURES


def note_failure(ip: str):
    _failures.setdefault(ip, []).append(time.time())
    if len(_failures) > 5000:  # never grow without bound
        _failures.clear()


def clear_failures(ip: str):
    _failures.pop(ip, None)


def failure_hint(user, password: str) -> str:
    """Why a sign-in failed, for the server log only. Never contains the password itself."""
    if not user:
        return "unknown-account"
    if not password:
        return "empty-password"
    if password != password.lower() and check_password(password.lower(), user.password_hash):
        return "letter-case"
    return f"mismatch(len={len(password)})"


def ensure_users(db):
    """Create the four demo accounts once. Their initial password is DEMO_PASSWORD; each user can change it."""
    if db.query(User).count():
        return
    for username, name, role, doctor in DEMO_USERS:
        db.add(
            User(
                username=username,
                full_name=name,
                role=role,
                doctor_name=doctor,
                password_hash=hash_password(config.DEMO_PASSWORD or "demo"),
                link_code=secrets.token_hex(4),
            )
        )
    db.commit()
