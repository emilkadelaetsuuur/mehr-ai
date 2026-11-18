"""Real phone line for AI calls through a Twilio-compatible voice API (optional).

The dialogue is the one the browser call has, step for step: greeting, how to reach a person, each question
with a short reaction, a second try when an answer was not understood (by keys this time: 1 yes, 2 no,
0 a person), the offer to leave a message for the doctor, and closing words written for this call.
The provider plays our cached speech, records each answer and sends it to us; we recognise it and reply
with the next step as TwiML. Without TWILIO_* settings nothing here is used and the call opens by link or QR.

Checked against a simulated provider in the tests. A live line needs an account and a number.
"""

import base64
import hashlib
import hmac
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import httpx

from . import closing, config, core, extract, voicelab
from .db import Call, SessionLocal

log = logging.getLogger("nigoh.telephony")
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="phone")
_closings = {}  # call token -> (job writing the closing words, the fixed phrase to fall back on)
KEYS = {"1": "yes", "2": "no"}


def enabled():
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM)


def number(phone):
    """A number as the provider wants it: +998901234567. Nine digits are taken as a local Uzbek mobile number."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    return "+" + digits if 10 <= len(digits) <= 15 else None


def dial(call, phone):
    """Start an outbound call. Returns the provider's call id."""
    r = httpx.post(
        f"{config.TWILIO_API}/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Calls.json",
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
        timeout=20,
        data={
            "To": number(phone),
            "From": config.TWILIO_FROM,
            "Url": f"{config.PUBLIC_URL}/api/tel/{call.token}/step?i=0",
            "Method": "POST",
            "StatusCallback": f"{config.PUBLIC_URL}/api/tel/{call.token}/status",
            "StatusCallbackEvent": "completed",
            "Timeout": "30",
        },
    )
    if r.status_code >= 400:  # the provider says why in the body: an unverified number, a country that is switched off
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    return r.json().get("sid")


def valid_signature(url, params, signature):
    """Twilio signs every webhook: HMAC-SHA1 over the URL plus sorted form fields."""
    if not config.TWILIO_AUTH_TOKEN:
        return True  # telephony not configured (local runs, tests)
    data = url + "".join(k + params[k] for k in sorted(params))
    want = base64.b64encode(hmac.new(config.TWILIO_AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(want, signature or "")


# ---------- TwiML pieces


def _to(token, path):
    return escape(f"{config.PUBLIC_URL}/api/tel/{token}/{path}")


def _play(token, part):
    return f"<Play>{escape(f'{config.PUBLIC_URL}/api/call/{token}/audio/{part}')}</Play>"


def _record(token, action, seconds=9, quiet=2, beep=False):
    """Record what the caller says and send it to `action`; silence goes there too, as an empty answer."""
    to = _to(token, action)
    return (
        f'<Record action="{to}" method="POST" maxLength="{seconds}" timeout="{quiet}" playBeep="{str(beep).lower()}" trim="trim-silence"/>'
        f'<Redirect method="POST">{to}</Redirect>'
    )


def _reply(*parts):
    return "<Response>" + "".join(p for p in parts if p) + "</Response>"


HANGUP = "<Hangup/>"


def _question(call, i):
    qs = core.SCENARIOS[call.scenario]["questions"]
    return _play(call.token, qs[i]["id"]) + _record(call.token, f"answer?i={i}")


def step_twiml(call, i):
    """The call is answered: greeting and how to reach a person, then the first question."""
    opening = _play(call.token, "greeting") + _play(call.token, "say_hint") if i == 0 else ""
    return _reply(opening, _question(call, i))


def heard(recording_url, lang):
    """The caller's recorded words as text. The provider needs a moment before a recording can be fetched."""
    if not recording_url:
        return ""
    for _ in range(4):
        try:
            r = httpx.get(recording_url + ".wav", auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=20, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 800:
                return ((voicelab.stt(r.content, "answer.wav", "audio/wav", lang) or {}).get("text") or "").strip()
        except Exception as e:
            log.warning("recording not fetched: %s", e)
        time.sleep(0.5)
    return ""


# ---------- the dialogue


def take_answer(db, call, i, recording_url="", digits=None):
    """An answer to question i, spoken or keyed. Returns the next TwiML."""
    qs = core.SCENARIOS[call.scenario]["questions"]
    q, lang = qs[i], call.lang or "uz"
    keyed = digits is not None
    text = "" if keyed else heard(recording_url, lang)
    if digits == "0" or (text and extract.wants_human(text)):
        return hand_over(db, call, text)
    if q["type"] == "number":
        val = extract.number(text) if text else None
    elif keyed:
        val = KEYS.get(digits, "unclear")
    else:
        val = extract.yes_no(text, q[lang]) if text else "unclear"
    if q["type"] != "number" and val == "unclear" and not keyed:
        # one more try, by keys: on a bad line a digit gets through where a word does not
        to = _to(call.token, f"key?i={i}")
        return _reply(
            _play(call.token, "say_retry_keys"),
            f'<Gather input="dtmf" numDigits="1" timeout="7" action="{to}" method="POST"/>',
            f'<Redirect method="POST">{to}</Redirect>',
        )
    call.answers = {**(call.answers or {}), q["id"]: {"value": val, "transcript": f"tugma {digits}" if keyed and digits else text}}
    call.status = "jarayonda"
    db.commit()
    flagged = bool(q.get("complaint")) and val == q.get("flag_if")
    ack = _play(call.token, "say_ack_flag" if flagged else f"say_ack{1 + i % 3}")
    if i + 1 < len(qs):
        return _reply(ack, _question(call, i + 1))
    return _reply(ack, _play(call.token, "say_appeal_q"), _record(call.token, "offered", seconds=6))


def take_offer(db, call, recording_url="", digits=None):
    """Her answer to "do you want to leave a message for your doctor?"."""
    lang = call.lang or "uz"
    text = "" if digits is not None else heard(recording_url, lang)
    if digits == "0" or (text and extract.wants_human(text)):
        return hand_over(db, call, text)
    yes = digits == "1" or (bool(text) and extract.yes_no(text, "") == "yes")
    if yes:
        return _reply(_play(call.token, "say_appeal_go"), _record(call.token, "message", seconds=45, quiet=3, beep=True))
    return _reply(*start_closing(db, call))


def take_message(db, call, recording_url=""):
    """The message she left: recognised, sent to the person she is attached to, then the closing."""
    text = heard(recording_url, call.lang or "uz")
    if len(text) < 3:
        said = "say_appeal_fail"
    else:
        out = core.appeal(db, call, text)
        db.commit()
        if voicelab.enabled():
            _pool.submit(core.review_later, call.id, text)  # the careful reading, after she has been answered
        said = "say_appeal_ok_nurse" if out["role"] == "hamshira" else "say_appeal_ok"
    return _reply(_play(call.token, said), *start_closing(db, call))


def _write_closing(call_id, res):
    """Closing words for this call, and their speech, ready before the caller is asked to listen."""
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        call.closing, call.closing_by = closing.compose(call, res)
        db.commit()
        if call.closing_by != "shablon":
            voicelab.tts(call.closing, call.lang or "uz")
        return call.closing_by


def start_closing(db, call):
    """The questions are over: the answers become data now; the closing words are written while a short
    "one moment" plays, and the provider comes back for them."""
    res = core.finish_call(db, call)
    call.closing, call.closing_by = closing.fixed(call, res), "shablon"
    db.commit()
    fixed = "closing_alert" if res["alert"] or res["verified"] is False else "closing_ok"
    written = bool(closing.writers(call.lang or "uz"))
    if written:
        _closings[call.token] = (_pool.submit(_write_closing, call.id, res), fixed)
    else:
        _closings[call.token] = (None, fixed)
    return [_play(call.token, "bridge") if written else "", f'<Redirect method="POST">{_to(call.token, "closing")}</Redirect>']


def closing_twiml(call):
    """The last words. If the written closing is not ready in time, the scenario's own phrase is spoken."""
    job, fixed = _closings.pop(call.token, (None, "closing_ok"))
    part = fixed
    try:
        if job and job.result(timeout=10) != "shablon":
            part = "closing"
    except Exception as e:  # late or failed: the fixed phrase is already cached
        log.warning("closing not ready: %s", type(e).__name__)
    return _reply(_play(call.token, part), HANGUP)


def hand_over(db, call, said=""):
    """The caller asked for a person. Staff get a task to ring back. With the polyclinic's number set the
    call is put through at once, and the task stays in case nobody picks up."""
    core.callback(db, call, said)
    if call.status != "tugadi":
        res = core.finish_call(db, call)  # the answers given so far are kept
        call.closing, call.closing_by = closing.fixed(call, res), "shablon"
    db.commit()
    clinic = number(config.CLINIC_PHONE)
    if clinic:
        return _reply(
            _play(call.token, "say_operator_dial"),
            f'<Dial timeout="25" callerId="{escape(config.TWILIO_FROM)}">{clinic}</Dial>',
            _play(call.token, "say_operator_ok"),
            HANGUP,
        )
    return _reply(_play(call.token, "say_operator_ok"), HANGUP)


def hung_up(db, call):
    """The line dropped in the middle of the questions: what was answered is not lost."""
    if call.status == "jarayonda":
        res = core.finish_call(db, call)
        call.closing, call.closing_by = closing.fixed(call, res), "shablon"
        db.commit()
