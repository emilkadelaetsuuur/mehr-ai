"""Webhooks of the telephony provider (Twilio-compatible): the same scenario over a real phone line."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import config, core, telephony
from .deps import db_session
from .public import get_call

router = APIRouter(prefix="/api/tel")


async def _form(request: Request, path: str):
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = f"{config.PUBLIC_URL}{path}" + (f"?{request.url.query}" if request.url.query else "")
    if not telephony.valid_signature(url, form, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "signature")
    return form


def _xml(body: str):
    return Response('<?xml version="1.0" encoding="UTF-8"?>' + body, media_type="text/xml")


@router.post("/{token}/step")
async def step(token: str, request: Request, i: int = 0, db=Depends(db_session)):
    await _form(request, request.url.path)
    c = get_call(db, token)
    if not 0 <= i < len(core.SCENARIOS[c.scenario]["questions"]) or c.status in ("tugadi", "javobsiz"):
        return _xml("<Response><Hangup/></Response>")
    return _xml(telephony.step_twiml(c, i))


@router.post("/{token}/answer")
async def answer(token: str, request: Request, i: int = 0, db=Depends(db_session)):
    form = await _form(request, request.url.path)
    c = get_call(db, token)
    if not 0 <= i < len(core.SCENARIOS[c.scenario]["questions"]) or c.status in ("tugadi", "javobsiz"):
        return _xml("<Response><Hangup/></Response>")
    return _xml(telephony.take_answer(db, c, i, form.get("RecordingUrl", "")))


@router.post("/{token}/status")
async def status(token: str, request: Request, db=Depends(db_session)):
    form = await _form(request, request.url.path)
    c = get_call(db, token)
    if form.get("CallStatus") in ("no-answer", "busy", "failed", "canceled") and c.status not in ("tugadi", "javobsiz"):
        core.call_no_answer(db, c)
        db.commit()
    return {"ok": True}
