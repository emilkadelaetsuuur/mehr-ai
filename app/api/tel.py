"""Webhooks of the telephony provider (Twilio-compatible): the call dialogue over a real phone line.

Each step of a call is one request from the provider; the reply is TwiML saying what to play and what to
wait for next. Speech recognition is slow work, so it runs off the event loop.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from .. import config, core, telephony
from .deps import db_session
from .public import get_call

router = APIRouter(prefix="/api/tel")
OVER = ("tugadi", "javobsiz")


async def _form(request: Request):
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = f"{config.PUBLIC_URL}{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")
    if not telephony.valid_signature(url, form, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "signature")
    return form


def _xml(body: str):
    return Response('<?xml version="1.0" encoding="UTF-8"?>' + body, media_type="text/xml")


def _question(call, i):
    return 0 <= i < len(core.SCENARIOS[call.scenario]["questions"]) and call.status not in OVER


@router.post("/{token}/step")
async def step(token: str, request: Request, i: int = 0, db=Depends(db_session)):
    await _form(request)
    c = get_call(db, token)
    return _xml(telephony.step_twiml(c, i) if _question(c, i) else telephony._reply(telephony.HANGUP))


@router.post("/{token}/answer")
async def answer(token: str, request: Request, i: int = 0, db=Depends(db_session)):
    """A spoken answer to question i."""
    form = await _form(request)
    c = get_call(db, token)
    if not _question(c, i):
        return _xml(telephony._reply(telephony.HANGUP))
    return _xml(await run_in_threadpool(telephony.take_answer, db, c, i, form.get("RecordingUrl", "")))


@router.post("/{token}/key")
async def key(token: str, request: Request, i: int = 0, db=Depends(db_session)):
    """The second try at question i, answered with a key: 1 yes, 2 no, 0 a person."""
    form = await _form(request)
    c = get_call(db, token)
    if not _question(c, i):
        return _xml(telephony._reply(telephony.HANGUP))
    return _xml(await run_in_threadpool(telephony.take_answer, db, c, i, "", form.get("Digits", "")))


@router.post("/{token}/offered")
async def offered(token: str, request: Request, db=Depends(db_session)):
    """Her answer to the offer to leave a message for the doctor."""
    form = await _form(request)
    c = get_call(db, token)
    if c.status in OVER:
        return _xml(telephony._reply(telephony.HANGUP))
    return _xml(await run_in_threadpool(telephony.take_offer, db, c, form.get("RecordingUrl", ""), form.get("Digits")))


@router.post("/{token}/message")
async def message(token: str, request: Request, db=Depends(db_session)):
    """The message she spoke after the tone."""
    form = await _form(request)
    c = get_call(db, token)
    if c.status in OVER:
        return _xml(telephony._reply(telephony.HANGUP))
    return _xml(await run_in_threadpool(telephony.take_message, db, c, form.get("RecordingUrl", "")))


@router.post("/{token}/closing")
async def closing_words(token: str, request: Request, db=Depends(db_session)):
    await _form(request)
    c = get_call(db, token)
    return _xml(await run_in_threadpool(telephony.closing_twiml, c))


@router.post("/{token}/status")
async def status(token: str, request: Request, db=Depends(db_session)):
    form = await _form(request)
    c = get_call(db, token)
    state = form.get("CallStatus")
    if state in ("no-answer", "busy", "failed", "canceled") and c.status not in OVER:
        core.call_no_answer(db, c)
        db.commit()
    elif state == "completed":
        telephony.hung_up(db, c)
    return {"ok": True}
