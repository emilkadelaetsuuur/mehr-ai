"""VoiceLab client: Uzbek/Russian speech-to-text, text-to-speech and LLM.

Only documented endpoints are used (docs.voicelab.uz). The API key stays on the server.
Without a key the module runs in offline mode: STT/TTS/LLM return None and callers fall
back to deterministic logic, so the product and the tests keep working.
"""
import hashlib
import json
import logging
import os
import time
import uuid

import httpx

from . import config

log = logging.getLogger("nigoh.voicelab")
BASE = config.VOICELAB_BASE
_state = {"voices": {}, "model": None, "checked": False, "error": None}


def enabled():
    return bool(config.VOICELAB_API_KEY)


def _headers(extra=None):
    h = {"Authorization": f"Bearer {config.VOICELAB_API_KEY}"}
    h.update(extra or {})
    return h


def discover():
    """Pick an LLM model and one voice per language once; env values win."""
    if _state["checked"] or not enabled():
        return _state
    _state["checked"] = True
    try:
        with httpx.Client(timeout=20) as c:
            models = c.get(f"{BASE}/v1/models", headers=_headers()).json().get("data", [])
            ids = [m["id"] for m in models]
            want = config.VOICELAB_LLM_MODEL or "aisha-gemma-4"
            _state["model"] = want if want in ids else (ids[0] if ids else None)
            for lang, env, prefer in (("uz", config.VOICELAB_VOICE_UZ, "Lola"), ("ru", config.VOICELAB_VOICE_RU, "Alina")):
                if env:
                    _state["voices"][lang] = env
                    continue
                vs = c.get(f"{BASE}/v1/voices", params={"language": lang}, headers=_headers()).json().get("data", [])
                pick = next((v for v in vs if prefer.lower() in (v.get("display_name") or "").lower()), vs[0] if vs else None)
                if pick:
                    _state["voices"][lang] = pick["id"]
    except Exception as e:  # network or auth problem: stay usable offline
        _state["error"] = str(e)[:200]
        log.warning("VoiceLab discovery failed: %s", e)
    return _state


def status():
    s = discover()
    return {"enabled": enabled(), "model": s["model"], "voices": s["voices"], "error": s["error"]}


def stt(audio: bytes, filename="audio.webm", content_type="audio/webm", language="uz", timeout=90):
    """Transcribe audio. Returns {'text', 'language', 'ms'} or None. The job is deleted afterwards:
    the transcript lives only in our database, the audio is not kept."""
    if not enabled() or not audio:
        return None
    t0 = time.time()
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(
                f"{BASE}/v1/stt",
                headers=_headers({"Idempotency-Key": str(uuid.uuid4())}),
                files={"audio": (filename, audio, content_type)},
                data={"language": language, "include_speakers": "false"},
            )
            if r.status_code >= 400:
                log.warning("stt upload %s %s", r.status_code, r.text[:300])
                return None
            job = r.json()["id"]
            deadline = time.time() + timeout
            delay = 0.4
            body = {}
            while time.time() < deadline:
                p = c.get(f"{BASE}/v1/stt/transcriptions/{job}", headers=_headers())
                body = p.json() if p.status_code == 200 else {}
                if body.get("status") in ("completed", "failed"):
                    break
                time.sleep(delay)
                delay = min(delay * 1.3, 1.5)
            try:
                c.delete(f"{BASE}/v1/stt/transcriptions/{job}", headers=_headers())
            except Exception:
                pass
            if body.get("status") != "completed":
                log.warning("stt job %s ended as %s", job, body.get("status"))
                return None
            return {"text": (body.get("transcript") or "").strip(), "language": body.get("language") or language,
                    "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        log.warning("stt failed: %s", e)
        return None


def chat(messages, max_tokens=700, temperature=0.0, timeout=60):
    """One LLM completion. Returns text or None."""
    s = discover()
    if not enabled() or not s["model"]:
        return None
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(
                f"{BASE}/v1/chat/completions",
                headers=_headers({"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}),
                json={"model": s["model"], "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                      **({"reasoning_effort": "none"} if s["model"].startswith("aisha-gemma") else {})},
            )
            if r.status_code >= 400:
                log.warning("llm %s %s", r.status_code, r.text[:300])
                return None
            return (r.json()["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:
        log.warning("llm failed: %s", e)
        return None


def chat_json(system, user, max_tokens=700):
    """Completion that must be a JSON object; returns dict or None."""
    out = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens)
    if not out:
        return None
    a, b = out.find("{"), out.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(out[a:b + 1])
    except Exception:
        return None


def tts(text, lang="uz", speed=1.0):
    """Speech for a phrase as WAV bytes, cached on disk so a call never waits twice."""
    s = discover()
    voice = s["voices"].get(lang) or s["voices"].get("uz")
    if not enabled() or not voice or not text:
        return None
    cache_dir = os.path.join(config.DATA_DIR, "tts")
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{lang}|{speed}|{text}".encode()).hexdigest()
    path = os.path.join(cache_dir, key + ".wav")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        with open(path, "rb") as f:
            return f.read()
    body = {"text": text[:4900], "language": lang, "voice_id": voice, "speed": speed}
    if config.VOICELAB_TTS_MODEL:
        body["model_id"] = config.VOICELAB_TTS_MODEL
    try:
        with httpx.Client(timeout=90) as c:
            r = c.post(f"{BASE}/v1/tts", headers=_headers({"Idempotency-Key": "nigoh-" + key[:40]}), json=body)
            audio = None
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio"):
                audio = r.content
            elif r.status_code in (200, 202):
                gid = r.json().get("id")
                for _ in range(60):
                    time.sleep(1)
                    g = c.get(f"{BASE}/v1/tts/generations/{gid}", headers=_headers()).json()
                    if g.get("status") == "completed" and g.get("audio_url"):
                        audio = httpx.get(g["audio_url"], timeout=60).content
                        break
                    if g.get("status") == "failed":
                        break
            else:
                log.warning("tts %s %s", r.status_code, r.text[:300])
            if audio and len(audio) > 1000:
                with open(path, "wb") as f:
                    f.write(audio)
                return audio
    except Exception as e:
        log.warning("tts failed: %s", e)
    return None
