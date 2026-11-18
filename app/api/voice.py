"""Voice input: speech -> text -> card fields with quotes. Nothing is saved here; the nurse confirms first."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import extract, voicelab
from ..schemas import ExtractIn

router = APIRouter(prefix="/api")
MAX_AUDIO = 15 * 1024 * 1024


@router.post("/extract")
def extract_text(body: ExtractIn):
    return {"transcript": body.text, "language": body.lang, **extract.extract(body.text)}


@router.post("/voice")
async def voice(audio: UploadFile = File(...), lang: str = Form("uz")):
    raw = await audio.read()
    if not 800 < len(raw) <= MAX_AUDIO:
        raise HTTPException(400, "audio size")
    res = await run_in_threadpool(
        voicelab.stt, raw, audio.filename or "audio.webm", audio.content_type or "audio/webm", lang if lang in ("uz", "ru", "auto") else "uz"
    )
    if not res:
        raise HTTPException(503, "stt unavailable")
    ex = await run_in_threadpool(extract.extract, res["text"])
    return {"transcript": res["text"], "language": res["language"], "stt_ms": res["ms"], **ex}
