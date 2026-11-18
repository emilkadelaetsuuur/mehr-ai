"""Patient side of an AI call. No login: the only key is an unguessable token in the link."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from .. import closing, config, core, dialogue, extract, voicelab
from ..db import Call
from .deps import db_session

router = APIRouter(prefix="/api/call")
MAX_ANSWER = 3 * 1024 * 1024
MAX_APPEAL = 8 * 1024 * 1024
BUTTON = {"yes": "ha (tugma)", "no": "yo'q (tugma)"}


def get_call(db, token: str) -> Call:
    c = db.query(Call).filter(Call.token == token).first()
    if not c:
        raise HTTPException(404, "call")
    return c


def phrase(sc, part, lang):
    if part in ("greeting", "closing_ok", "closing_alert"):
        return sc[part][lang]
    q = next((q for q in sc["questions"] if q["id"] == part), None)
    return q[lang] if q else None


@router.get("/{token}")
def info(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    sc, lang = core.SCENARIOS[c.scenario], c.lang or "uz"
    return {
        "status": c.status,
        "lang": lang,
        "title": sc["title"][lang],
        "greeting": sc["greeting"][lang],
        "questions": [{"id": q["id"], "text": q[lang], "type": q["type"]} for q in sc["questions"]],
        "closing_ok": sc["closing_ok"][lang],
        "closing_alert": sc["closing_alert"][lang],
        # spoken while the closing is being written; absent when the fixed phrase is used and nothing has to be waited for
        "bridge": closing.BRIDGE.get(lang) if closing.writers(lang) else None,
        "say": dialogue.say(lang),  # reactions, the message for the doctor, the hand-over to a person
        "clinic_phone": config.CLINIC_PHONE or None,
        "tts": voicelab.enabled(),
    }


@router.get("/{token}/audio/{part}")
def audio(token: str, part: str, i: int | None = None, db=Depends(db_session)):
    """Speech for one part of the call. `closing` with `i` is one sentence of the closing words."""
    c = get_call(db, token)
    lang = c.lang or "uz"
    if part == "bridge":
        text = closing.BRIDGE.get(lang)
    elif part.startswith("say_"):
        text = (dialogue.SAY.get(part[4:]) or {}).get(lang)
    elif part == "closing" and i is not None:
        parts = closing.sentences(c.closing)
        text = parts[i] if 0 <= i < len(parts) else None
    elif part == "closing":
        text = c.closing
    else:
        text = phrase(core.SCENARIOS[c.scenario], part, lang)
    wav = voicelab.tts(text, lang) if text else None
    if not wav:
        raise HTTPException(404, "no audio")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/{token}/answer")
async def answer(token: str, qid: str = Form(...), value: str = Form(""), audio: UploadFile = File(None), db=Depends(db_session)):
    c = get_call(db, token)
    lang = c.lang or "uz"
    q = next((x for x in core.SCENARIOS[c.scenario]["questions"] if x["id"] == qid), None)
    if not q or c.status in ("tugadi", "javobsiz"):
        raise HTTPException(400, "question")
    transcript, val = "", None
    if audio is not None:
        raw = await audio.read()
        if len(raw) > MAX_ANSWER:
            raise HTTPException(400, "audio size")

        def recognise():
            res = voicelab.stt(raw, audio.filename or "a.webm", audio.content_type or "audio/webm", lang) if len(raw) > 800 else None
            text = (res or {}).get("text", "")
            if q["type"] == "number":
                return text, extract.number(text)
            return text, (extract.yes_no(text, q[lang]) if text else "unclear")

        transcript, val = await run_in_threadpool(recognise)
    elif value:
        if q["type"] == "number":
            transcript, val = value[:40], extract.number(value)
        else:
            val = value if value in ("yes", "no") else "unclear"
            transcript = BUTTON.get(val, "")
    c.answers = {**(c.answers or {}), qid: {"value": val, "transcript": transcript}}
    c.status = "jarayonda"
    db.commit()
    # "operator" in a spoken answer is a request for a person, not an answer to the question
    return {
        "qid": qid,
        "value": val,
        "transcript": transcript,
        "flagged": bool(q.get("complaint")) and val == q.get("flag_if"),  # the page reacts differently to a warning sign
        "operator": audio is not None and extract.wants_human(transcript),
    }


@router.post("/{token}/hear")
async def hear(token: str, audio: UploadFile = File(...), db=Depends(db_session)):
    """A spoken yes or no to a question that is not part of the scenario (the offer to leave a message). Nothing is stored."""
    c = get_call(db, token)
    raw = await audio.read()
    if len(raw) > MAX_ANSWER:
        raise HTTPException(400, "audio size")
    lang = c.lang or "uz"

    def recognise():
        text = ((voicelab.stt(raw, audio.filename or "a.webm", audio.content_type or "audio/webm", lang) or {}).get("text") or "") if len(raw) > 800 else ""
        return text, (extract.yes_no(text, dialogue.SAY["appeal_q"][lang]) if text else "unclear")

    text, val = await run_in_threadpool(recognise)
    return {"value": val, "transcript": text, "operator": extract.wants_human(text)}


@router.post("/{token}/appeal")
async def appeal(token: str, text: str = Form(""), audio: UploadFile = File(None), db=Depends(db_session)):
    """The patient's own message at the end of a call: spoken (recognised, the recording is not kept) or typed."""
    c = get_call(db, token)
    if c.status in ("tugadi", "javobsiz"):
        raise HTTPException(400, "call")
    said = text.strip()[:2000]
    if audio is not None:
        raw = await audio.read()
        if len(raw) > MAX_APPEAL:
            raise HTTPException(400, "audio size")
        res = await run_in_threadpool(voicelab.stt, raw, audio.filename or "a.webm", audio.content_type or "audio/webm", c.lang or "uz")
        said = ((res or {}).get("text") or "").strip()[:2000]
    if len(said) < 3:
        return {"ok": False}
    out = core.appeal(db, c, said)
    db.commit()
    body = {"ok": True, "transcript": said, "to": out["role"], "doctor": out["doctor"], "urgent": out["urgent"]}
    # the caller is answered at once; the careful reading of her words runs after the response has gone
    return JSONResponse(body, background=BackgroundTask(core.review_later, c.id, said) if voicelab.enabled() else None)


@router.post("/{token}/operator")
def operator(token: str, said: str = Form(""), db=Depends(db_session)):
    """The caller asked for a person: a member of staff gets a task to ring back."""
    c = get_call(db, token)
    if c.status in ("tugadi", "javobsiz"):
        raise HTTPException(400, "call")
    t = core.callback(db, c, said.strip()[:200])
    db.commit()
    return {"ok": True, "minutes": dialogue.CALLBACK_MINUTES, "role": t.role, "phone": config.CLINIC_PHONE or None}


@router.post("/{token}/finish")
def finish(token: str, quiet: int = 0, db=Depends(db_session)):
    c = get_call(db, token)
    if c.status == "tugadi":
        return {"alert": False, "done": True, "closing": c.closing}
    res = core.finish_call(db, c)
    # a language model's wording when available, else the scenario's phrase; `quiet` is a call that ended with a hand-over to a person
    c.closing, c.closing_by = (closing.fixed(c, res), "shablon") if quiet else closing.compose(c, res)
    core.audit(db, "bemor", "call_finished", c.patient, f"{c.scenario}: {', '.join(c.flags) or 'belgi yo`q'}")
    db.commit()
    # A written closing is spoken sentence by sentence; the fixed phrase is one clip that is already cached.
    return {**res, "closing": c.closing, "closing_parts": closing.sentences(c.closing) if c.closing_by != "shablon" else None}


@router.post("/{token}/noanswer")
def noanswer(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    n = core.call_no_answer(db, c)
    db.commit()
    return {"attempts": n, "status": c.status}
