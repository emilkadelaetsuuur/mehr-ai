"""Short-lived recipient confirmation, scoped to one follow-up and one browser."""

import hashlib
import hmac
import time

from fastapi import HTTPException

from . import carepath, config

COOKIE = "mehr_recipient"
LIFETIME = 900
QUESTION = {"ru": "Вам сейчас удобно говорить о здоровье без посторонних?", "uz": "Hozir salomatligingiz haqida boshqalarsiz gaplasha olasizmi?"}
NEUTRAL_PHRASES = {"who_retry", "who_no", "who_year", "who_year_no", "who_fail", "private_later", "operator_ok", "doctor_ok"}
NEUTRAL = {"ru": "Звонок из поликлиники", "uz": "Poliklinikadan qo‘ng‘iroq"}


def ticket(token, scope, expires=None):
    until = int(expires or (time.time() + LIFETIME))
    body = f"{token}|{scope}|{until}"
    signature = hmac.new(config.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{until}.{signature}"


def valid(token, scope, value):
    try:
        expiry = int((value or "").split(".", 1)[0])
        return int(time.time()) <= expiry <= time.time() + LIFETIME + 1 and hmac.compare_digest(ticket(token, scope, expiry), value)
    except (ValueError, TypeError):
        return False


def grant(response, token, scope):
    response.set_cookie(
        COOKIE,
        ticket(token, scope),
        max_age=LIFETIME,
        httponly=True,
        samesite="strict",
        secure=config.PUBLIC_URL.startswith("https://"),
        path="/api/call/" + token,
    )


def enabled(db, c):
    if c.status == "cancelled" or not c.patient.consent_at:
        return False
    if c.scenario == "dispanser" and not c.patient.private_consent_at:
        return False
    if c.scenario in carepath.IMMUNIZATION:
        return carepath.call_recipient(db, c) is not None
    if c.scenario in carepath.PRIVATE:
        return carepath.fits(db, c.patient, c.scenario)
    if c.scenario == "first_birth_care":
        return carepath.fits(db, c.patient, c.scenario)
    return True


def public_guard(db, c, request):
    if not enabled(db, c):
        raise HTTPException(410, "call_unavailable")
    if c.scenario not in carepath.TARGETED and c.scenario != "dispanser":
        return
    part = request.url.path.split("/api/call/" + c.token, 1)[-1].strip("/")
    if part in {"", "identity", "privacy", "audio/hello", "audio/privacy", "line", "operator", "noanswer"} or (
        part.startswith("audio/say_") and part[10:] in NEUTRAL_PHRASES
    ):
        return
    if valid(c.token, "talk", request.cookies.get(COOKIE)):
        return

    raise HTTPException(403, "recipient_confirmation")
