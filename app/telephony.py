"""Real phone line for AI calls through a Twilio-compatible voice API (optional).

The dialogue is the same scenario file as in the browser call: the provider plays our cached
question audio, records the answer, we recognise it and reply with the next step as TwiML.
Without TWILIO_* settings nothing here is used and the call opens by link or QR.
Not exercised against a live provider yet: needs an account and a number."""

import base64
import hashlib
import hmac
from xml.sax.saxutils import escape

import httpx

from . import closing, config, core, extract, voicelab


def enabled():
    return bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM)


def _url(token, path):
    return f"{config.PUBLIC_URL}/api/tel/{token}/{path}"


def dial(call, phone):
    """Start an outbound call to the patient's number. Returns the provider call id."""
    digits = "+" + "".join(ch for ch in phone if ch.isdigit())
    r = httpx.post(
        f"{config.TWILIO_API}/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Calls.json",
        auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
        timeout=20,
        data={
            "To": digits,
            "From": config.TWILIO_FROM,
            "Url": _url(call.token, "step?i=0"),
            "Method": "POST",
            "StatusCallback": _url(call.token, "status"),
            "StatusCallbackEvent": "completed",
            "Timeout": "25",
        },
    )
    r.raise_for_status()
    return r.json().get("sid")


def valid_signature(url, params, signature):
    """Twilio signs every webhook: HMAC-SHA1 over the URL plus sorted form fields."""
    if not config.TWILIO_AUTH_TOKEN:
        return True  # telephony not configured (local runs, tests)
    data = url + "".join(k + params[k] for k in sorted(params))
    want = base64.b64encode(hmac.new(config.TWILIO_AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(want, signature or "")


def _play(token, part):
    return f"<Play>{escape(f'{config.PUBLIC_URL}/api/call/{token}/audio/{part}')}</Play>"


def step_twiml(call, i):
    """Greeting (first step), question i, then record the answer."""
    qs = core.SCENARIOS[call.scenario]["questions"]
    parts = ([_play(call.token, "greeting")] if i == 0 else []) + [_play(call.token, qs[i]["id"])]
    action = escape(_url(call.token, f"answer?i={i}"))
    parts.append(f'<Record action="{action}" method="POST" maxLength="9" timeout="2" playBeep="false" trim="trim-silence"/>')
    parts.append(f'<Redirect method="POST">{action}</Redirect>')  # nothing was said: treat as an unclear answer
    return "<Response>" + "".join(parts) + "</Response>"


def take_answer(db, call, i, recording_url):
    """Recognise the recorded answer, store it and return the next TwiML (next question or closing)."""
    qs = core.SCENARIOS[call.scenario]["questions"]
    q, lang, text, val = qs[i], call.lang or "uz", "", "unclear"
    if recording_url:
        try:
            wav = httpx.get(recording_url + ".wav", auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=30).content
            text = (voicelab.stt(wav, "answer.wav", "audio/wav", lang) or {}).get("text", "")
        except Exception:
            text = ""
    if q["type"] == "number":
        val = extract.number(text) if text else None
    elif text:
        val = extract.yes_no(text, q[lang])
    call.answers = {**(call.answers or {}), q["id"]: {"value": val, "transcript": text}}
    call.status = "jarayonda"
    if i + 1 < len(qs):
        db.commit()
        return step_twiml(call, i + 1)
    res = core.finish_call(db, call)
    call.closing, call.closing_by = closing.compose(call, res)
    db.commit()
    return f"<Response>{_play(call.token, 'closing')}<Hangup/></Response>"
