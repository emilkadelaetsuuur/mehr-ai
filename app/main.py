"""Nigoh application: wiring only. Domain logic lives in core.py, HTTP handlers in app/api/."""

import hashlib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, closing, config, core, dialogue, dmed, ml, seed, telegram, voicelab
from .api import dmed as dmed_api
from .api import line, patients, public, system, tel, voice, work
from .db import Patient, SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nigoh")
WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
OPEN_PATHS = ("/api/login", "/api/logout", "/api/health", "/api/call/", "/api/tel/", "/api/gateway/", "/api/dmed/fhir", "/api/qr", "/api/meta")
_stop = threading.Event()


def _build():
    """A short fingerprint of the interface files: it changes whenever a release changes them."""
    h = hashlib.sha1()
    for name in ("app.js", "i18n.js", "call.js", "styles.css", "index.html"):
        with open(os.path.join(WEB, name), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


BUILD = _build()

# A screen asks for its list again every 12-20 seconds. A tab still running an old copy of the interface can
# ask thousands of times a minute: its refresh timers piled up (fixed since, but a tab that was never
# reloaded keeps the old code). Such a tab is told to sign in again. The interface, old or new, answers that
# by dropping all its timers and showing the sign-in form, so the flood stops and a reload brings the new code.
LISTS = ("/api/calls", "/api/patients", "/api/dashboard", "/api/tasks")
RUNAWAY, WINDOW = 40, 10  # more than this many requests for one list from one browser within these seconds...
CLOSED = 60  # ...closes that list to that browser for this long
_asked = {}  # (browser, list) -> [when the count began, how many since, closed until]


def runaway(key, now=None):
    """True when one browser asks for the same list far more often than any screen does, and for a minute
    after that. The minute matters: an old tab drops its timers on the first refusal, but a reply that was
    already on its way starts one more; that one must meet a refusal too, or the flood grows back."""
    now = time.monotonic() if now is None else now
    slot = _asked.get(key)
    if slot and now < slot[2]:
        return True
    if not slot or now - slot[0] >= WINDOW:
        if len(_asked) > 2000:
            _asked.clear()
        slot = _asked[key] = [now, 0, 0.0]
    slot[1] += 1
    if slot[1] <= RUNAWAY:
        return False
    slot[2] = now + CLOSED
    log.warning("a runaway tab asked for %s more than %s times in %ss: told to sign in again", key[1], RUNAWAY, WINDOW)
    return True


def scheduler():
    """Background timers: escalate overdue tasks and re-zone silent patients once a minute."""
    while not _stop.wait(60):
        try:
            with SessionLocal() as db:
                core.sweep(db)
        except Exception:
            log.exception("sweep failed")


def warm_speech():
    """Synthesise every scenario phrase once so that a call never waits for speech."""
    voicelab.discover()
    for sc in core.SCENARIOS.values():
        for text in [sc["greeting"]["uz"], sc["closing_ok"]["uz"], sc["closing_alert"]["uz"]] + [q["uz"] for q in sc["questions"]]:
            voicelab.tts(text, "uz")
    for lang, text in closing.BRIDGE.items():
        voicelab.tts(text, lang)
    for phrase in dialogue.SAY.values():
        for lang, text in phrase.items():
            voicelab.tts(text, lang)


@asynccontextmanager
async def lifespan(_app):
    _stop.clear()  # a second start in the same process (the tests) gets its background workers too
    init_db()
    with SessionLocal() as db:
        auth.ensure_users(db)
        if db.query(Patient).count() == 0:
            log.info("seeded %s synthetic patients", seed.run(db))
        core.sweep(db)
    ml.load()
    threading.Thread(target=warm_speech, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=telegram.poll, args=(_stop,), daemon=True).start()
    threading.Thread(target=dmed.sender, args=(_stop,), daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="Nigoh", version="1.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)


@app.middleware("http")
async def session_guard(request: Request, call_next):
    path = request.url.path
    request.state.uid = auth.read_session(request.cookies.get(auth.COOKIE, ""))
    guarded = config.DEMO_PASSWORD and path.startswith("/api/") and not path.startswith(OPEN_PATHS)
    if guarded and request.state.uid is None:
        return JSONResponse({"detail": "auth"}, status_code=401)
    if guarded and request.method == "GET" and path in LISTS and runaway((request.cookies.get(auth.COOKIE, ""), path)):
        return JSONResponse({"detail": "reload"}, status_code=401)
    resp = await call_next(request)
    if path.endswith((".html", ".js", ".css")) or path == "/" or path.startswith("/call/"):
        resp.headers["Cache-Control"] = "no-cache"
    if path.startswith("/api/"):
        resp.headers["X-Nigoh-Build"] = BUILD  # a tab opened before a release sees a new value and reloads itself
    return resp


for module in (system, patients, work, voice, public, tel, line, dmed_api):
    app.include_router(module.router)


@app.get("/call/{token}", include_in_schema=False)
def call_page(token: str):
    return FileResponse(os.path.join(WEB, "call.html"))


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
