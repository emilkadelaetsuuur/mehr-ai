"""Patient side of an AI call. No login: the only key is an unguessable token in the link."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import closing, core, extract, voicelab
from ..db import Call
from .deps import db_session

router = APIRouter(prefix="/api/call")
MAX_ANSWER = 3 * 1024 * 1024
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
        "tts": voicelab.enabled(),
    }


@router.get("/{token}/audio/{part}")
def audio(token: str, part: str, i: int | None = None, db=Depends(db_session)):
    """Speech for one part of the call. `closing` with `i` is one sentence of the closing words."""
    c = get_call(db, token)
    lang = c.lang or "uz"
    if part == "bridge":
        text = closing.BRIDGE.get(lang)
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
    return {"qid": qid, "value": val, "transcript": transcript}


@router.post("/{token}/finish")
def finish(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    if c.status == "tugadi":
        return {"alert": False, "done": True, "closing": c.closing}
    res = core.finish_call(db, c)
    c.closing, c.closing_by = closing.compose(c, res)  # a language model's wording when available, else the scenario's phrase
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
