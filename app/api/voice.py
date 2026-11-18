"""Voice input: speech -> text -> card fields with quotes. Nothing is saved here; the nurse confirms first."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import extract, voiceguide, voicelab
from ..schemas import ExtractIn, VoiceDraftIn

router = APIRouter(prefix="/api")
MAX_AUDIO = 15 * 1024 * 1024


@router.post("/extract")
def extract_text(body: ExtractIn):
    return {"transcript": body.text, "language": body.lang, **extract.extract(body.text)}


@router.post("/voice/draft")
def guided_draft(body: VoiceDraftIn):
    try:
        return voiceguide.make_draft(body.answers, body.kind, body.lang)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/voice")
async def voice(audio: UploadFile = File(...), lang: str = Form("uz"), transcript_only: bool = Form(False)):
    raw = await audio.read()
    if not 800 < len(raw) <= MAX_AUDIO:
        raise HTTPException(400, "audio size")
    res = await run_in_threadpool(
        voicelab.stt, raw, audio.filename or "audio.webm", audio.content_type or "audio/webm", lang if lang in ("uz", "ru", "auto") else "uz"
    )
    if not res:
        raise HTTPException(503, "stt unavailable")
    output = {"transcript": res["text"], "language": res["language"], "stt_ms": res["ms"]}
    if transcript_only:
        return output
    return {**output, **await run_in_threadpool(extract.extract, res["text"])}
