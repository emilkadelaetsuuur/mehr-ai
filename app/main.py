"""Nigoh application: wiring only. Domain logic lives in core.py, HTTP handlers in app/api/."""

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, core, ml, seed, voicelab
from .api import patients, public, system, voice, work
from .api.deps import auth_token
from .db import Patient, SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nigoh")
WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
OPEN_PATHS = ("/api/login", "/api/health", "/api/call/", "/api/qr", "/api/meta")
_stop = threading.Event()


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


@asynccontextmanager
async def lifespan(_app):
    init_db()
    with SessionLocal() as db:
        if db.query(Patient).count() == 0:
            log.info("seeded %s synthetic patients", seed.run(db))
        core.sweep(db)
    ml.load()
    threading.Thread(target=warm_speech, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="Nigoh", version="1.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    guarded = config.DEMO_PASSWORD and path.startswith("/api/") and not path.startswith(OPEN_PATHS)
    if guarded and not hmac.compare_digest(request.cookies.get("nigoh_auth", ""), auth_token()):
        return JSONResponse({"detail": "auth"}, status_code=401)
    resp = await call_next(request)
    if path.endswith((".html", ".js", ".css")) or path == "/" or path.startswith("/call/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


for module in (system, patients, work, voice, public):
    app.include_router(module.router)


@app.get("/call/{token}", include_in_schema=False)
def call_page(token: str):
    return FileResponse(os.path.join(WEB, "call.html"))


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
