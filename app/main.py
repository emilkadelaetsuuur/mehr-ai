"""Nigoh API: registry with risk zones, 'Faol chaqiruv' tasks, voice input, AI calls."""
import hashlib
import hmac
import io
import json
import logging
import os
import threading
from datetime import timedelta

import qrcode
import qrcode.image.svg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, core, extract, ml, pdfgen, rules, seed, voicelab
from .db import Call, Notice, Patient, SessionLocal, Task, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nigoh")
WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app = FastAPI(title="Nigoh", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _token():
    return hmac.new(config.SECRET_KEY.encode(), config.DEMO_PASSWORD.encode(), hashlib.sha256).hexdigest()[:40]


PUBLIC = ("/api/login", "/api/health", "/api/call/", "/api/qr", "/api/meta")


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if config.DEMO_PASSWORD and path.startswith("/api/") and not path.startswith(PUBLIC):
        if not hmac.compare_digest(request.cookies.get("nigoh_auth", ""), _token()):
            return JSONResponse({"detail": "auth"}, status_code=401)
    resp = await call_next(request)
    if path.endswith((".html", ".js", ".css")) or path in ("/", "/sw.js") or path.startswith("/call/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Patient).count() == 0:
            log.info("seeded %s synthetic patients", seed.run(db))
    finally:
        db.close()
    ml.load()

    def warm():
        voicelab.discover()
        for sc in core.SCENARIOS.values():
            for text in [sc["greeting"]["uz"], sc["closing_ok"]["uz"], sc["closing_alert"]["uz"]] + [q["uz"] for q in sc["questions"]]:
                voicelab.tts(text, "uz")
    threading.Thread(target=warm, daemon=True).start()


def iso(d):
    return d.isoformat() + "Z" if d else None


def brief(p):
    return {"id": p.id, "name": p.full_name, "kind": p.kind, "zone": p.zone, "mahalla": p.mahalla, "weeks": p.weeks,
            "birth_year": p.birth_year, "doctor": p.doctor, "phone": p.phone, "last_contact": iso(p.last_contact_at),
            "top": (p.reasons or [None])[0], "born_at": iso(p.born_at)}


def task_json(t):
    return {"id": t.id, "type": t.type, "role": t.role, "reason": t.reason, "status": t.status, "due_at": iso(t.due_at),
            "done_at": iso(t.done_at), "created_at": iso(t.created_at), "escalated": t.escalated, "note": t.note,
            "patient": {"id": t.patient.id, "name": t.patient.full_name, "zone": t.patient.zone, "mahalla": t.patient.mahalla,
                        "phone": t.patient.phone, "doctor": t.patient.doctor} if t.patient else None}


def call_json(c):
    return {"id": c.id, "token": c.token, "scenario": c.scenario, "status": c.status, "flags": c.flags, "answers": c.answers,
            "planned_at": iso(c.planned_at), "finished_at": iso(c.finished_at), "attempts": c.attempts, "task_id": c.task_id,
            "url": f"{config.PUBLIC_URL}/call/{c.token}", "title": core.SCENARIOS[c.scenario]["title"],
            "patient": {"id": c.patient.id, "name": c.patient.full_name} if c.patient else None}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/login")
def login(body: dict, response: Response):
    if config.DEMO_PASSWORD and not hmac.compare_digest(str(body.get("password", "")), config.DEMO_PASSWORD):
        raise HTTPException(401, "wrong")
    response.set_cookie("nigoh_auth", _token(), httponly=True, samesite="lax", max_age=14 * 86400, secure=config.PUBLIC_URL.startswith("https"))
    return {"ok": True}


@app.get("/api/me")
def me():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    ev_path = os.path.join(config.DATA_DIR, "eval.json")
    ev = json.load(open(ev_path, encoding="utf-8")) if os.path.exists(ev_path) else None
    return {"district": config.DISTRICT, "auth": bool(config.DEMO_PASSWORD), "voicelab": voicelab.status(), "ml": ml.metrics(),
            "rules": rules.T, "complaints": {k: {"uz": v[0], "ru": v[1]} for k, v in rules.COMPLAINTS.items()},
            "scenarios": [{"id": s["id"], "title": s["title"], "basis": s["basis"], "questions": len(s["questions"]), "who": s["who"]}
                          for s in core.SCENARIOS.values()],
            "eval": ev, "hours": config.ACTIVE_CALL_HOURS}


@app.get("/api/dashboard")
def dashboard(db=Depends(db_session)):
    d = core.dashboard(db)
    d["notices"] = [{"id": n.id, "level": n.level, "role": n.role, "uz": n.text_uz, "ru": n.text_ru, "at": iso(n.created_at), "patient_id": n.patient_id}
                    for n in db.query(Notice).order_by(Notice.id.desc()).limit(25)]
    d["demo"] = [brief(p) for n in ("Sodiqova Dilnoza", "Valiyeva Madina", "Valiyev Amir")
                 for p in db.query(Patient).filter(Patient.full_name == n).limit(1)]
    return d


@app.get("/api/patients")
def patients(zone: str = "", q: str = "", kind: str = "", silent: int = 0, limit: int = 400, db=Depends(db_session)):
    qs = db.query(Patient)
    if zone:
        qs = qs.filter(Patient.zone == zone)
    if kind:
        qs = qs.filter(Patient.kind == kind)
    if q:
        qs = qs.filter(Patient.full_name.ilike(f"%{q}%"))
    if silent:
        qs = qs.filter(Patient.last_contact_at < core.now() - timedelta(days=config.SILENT_DAYS))
    rows = qs.all()
    rows.sort(key=lambda p: (-rules.ORDER.get(p.zone or "green", 0), p.last_contact_at or core.now()))
    return [brief(p) for p in rows[:limit]]


def get_patient(db, pid):
    p = db.get(Patient, pid)
    if not p:
        raise HTTPException(404, "patient")
    return p


@app.get("/api/patients/{pid}")
def patient(pid: int, db=Depends(db_session)):
    p = get_patient(db, pid)
    data, prev, quotes = core.merged(p)
    age = (core.now().year - p.birth_year) if p.birth_year and p.kind != "chaqaloq" else None
    mother = db.get(Patient, p.mother_id) if p.mother_id else None
    kids = db.query(Patient).filter(Patient.mother_id == p.id).all()
    return {**brief(p), "reasons": p.reasons or [], "diagnosis": p.diagnosis, "discharged_at": iso(p.discharged_at),
            "values": data, "prev": prev, "summary": {"uz": core.summary(p, "uz"), "ru": core.summary(p, "ru")},
            "ml": ml.predict(age, data) if p.kind != "chaqaloq" else None,
            "mother": brief(mother) if mother else None, "children": [brief(k) for k in kids],
            "observations": [{"id": o.id, "source": o.source, "data": o.data, "quotes": o.quotes, "text": o.text, "author": o.author, "at": iso(o.created_at)}
                             for o in sorted(p.observations, key=lambda o: o.created_at, reverse=True)[:30]],
            "tasks": [task_json(t) for t in sorted(p.tasks, key=lambda t: t.created_at, reverse=True)],
            "calls": [call_json(c) for c in sorted(p.calls, key=lambda c: c.planned_at, reverse=True)]}


@app.post("/api/extract")
def extract_text(body: dict):
    text = str(body.get("text", ""))[:4000]
    return {"transcript": text, "language": body.get("lang", "uz"), **extract.extract(text)}


@app.post("/api/voice")
async def voice(audio: UploadFile = File(...), lang: str = Form("uz")):
    raw = await audio.read()
    if len(raw) < 800:
        raise HTTPException(400, "audio too short")
    res = await run_in_threadpool(voicelab.stt, raw, audio.filename or "audio.webm", audio.content_type or "audio/webm",
                                  lang if lang in ("uz", "ru", "auto") else "uz")
    if not res:
        raise HTTPException(503, "stt unavailable")
    ex = await run_in_threadpool(extract.extract, res["text"])
    return {"transcript": res["text"], "language": res["language"], "stt_ms": res["ms"], **ex}


@app.post("/api/patients/confirm")
def confirm(body: dict, db=Depends(db_session)):
    f = body.get("fields") or {}
    name = str(f.get("full_name") or "").strip()
    if not name:
        raise HTTPException(400, "full_name required")
    p = db.get(Patient, body["patient_id"]) if body.get("patient_id") else None
    if not p:
        qs = db.query(Patient).filter(Patient.full_name.ilike(name))
        if f.get("birth_year"):
            qs = qs.filter(Patient.birth_year == int(f["birth_year"]))
        p = qs.first()
    created = False
    if not p:
        p = Patient(full_name=name, kind=f.get("kind") or "boshqa", zone="green", created_at=core.now(), last_contact_at=core.now())
        db.add(p)
        db.flush()
        created = True
    for k in ("birth_year", "weeks"):
        if f.get(k):
            setattr(p, k, int(f[k]))
    for k in ("mahalla", "phone", "diagnosis", "kind", "doctor"):
        if f.get(k):
            setattr(p, k, str(f[k])[:240])
    data = {k: f[k] for k in core.NUM if f.get(k) not in (None, "")}
    data["complaints"] = [c for c in (f.get("complaints") or []) if c in rules.COMPLAINTS]
    zone, reasons = core.add_observation(db, p, "ovoz", data, body.get("quotes") or {}, str(body.get("transcript") or "")[:4000],
                                         str(body.get("author") or "Hamshira"))
    if f.get("referral"):
        core.notify(db, p, "shifokor", "info", f"{p.full_name}: yo'llanma — {f['referral']}", f"{p.full_name}: направление — {f['referral']}")
    db.commit()
    return {"id": p.id, "created": created, "zone": zone, "reasons": reasons, "referral": f.get("referral")}


@app.post("/api/patients/{pid}/observations")
def observation(pid: int, body: dict, db=Depends(db_session)):
    p = get_patient(db, pid)
    data = {k: float(body[k]) for k in core.NUM if body.get(k) not in (None, "")}
    if "complaints" in body:
        data["complaints"] = [c for c in body["complaints"] if c in rules.COMPLAINTS]
    if not data:
        raise HTTPException(400, "empty")
    old = p.zone
    zone, reasons = core.add_observation(db, p, body.get("source") or "tahlil", data, {}, str(body.get("text") or ""), str(body.get("author") or "Laboratoriya"),
                                         contact=(body.get("source") != "tahlil"))
    db.commit()
    return {"zone": zone, "old": old, "reasons": reasons}


@app.post("/api/patients/{pid}/discharge")
def discharge(pid: int, body: dict = None, db=Depends(db_session)):
    p = get_patient(db, pid)
    t = core.discharge(db, p, str((body or {}).get("note") or ""))
    for k in db.query(Patient).filter(Patient.mother_id == p.id).all():  # the newborn goes home too
        core.discharge(db, k)
    db.commit()
    return task_json(t)


@app.get("/api/patients/{pid}/referral.pdf")
def referral(pid: int, lang: str = "uz", to: str = "", db=Depends(db_session)):
    p = get_patient(db, pid)
    p._referral = to[:120] or None
    return Response(pdfgen.referral(p, lang), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="yollanma-{p.id}.pdf"'})


@app.get("/api/tasks")
def tasks(status: str = "", role: str = "", db=Depends(db_session)):
    core.sweep(db)
    qs = db.query(Task)
    if status:
        qs = qs.filter(Task.status == status)
    if role:
        qs = qs.filter(Task.role == role)
    rows = qs.order_by(Task.due_at.asc()).limit(300).all()
    rows.sort(key=lambda t: (t.status != "ochiq", t.due_at or core.now()))
    return [task_json(t) for t in rows]


@app.post("/api/tasks/{tid}/done")
def done(tid: int, body: dict = None, db=Depends(db_session)):
    t = db.get(Task, tid)
    if not t or t.status != "ochiq":
        raise HTTPException(404, "task")
    c = core.task_done(db, t, str((body or {}).get("note") or ""))
    db.commit()
    return {"task": task_json(t), "call": call_json(c)}


@app.get("/api/calls")
def calls(db=Depends(db_session)):
    return [call_json(c) for c in db.query(Call).order_by(Call.planned_at.desc()).limit(120)]


@app.post("/api/patients/{pid}/calls")
def new_call(pid: int, body: dict, db=Depends(db_session)):
    p = get_patient(db, pid)
    sc = body.get("scenario")
    if sc not in core.SCENARIOS:
        raise HTTPException(400, "scenario")
    if body.get("lang") in ("uz", "ru"):
        p.lang = body["lang"]
    c = core.create_call(db, p, sc)
    db.commit()
    return call_json(c)


@app.get("/api/qr")
def qr(u: str):
    if not u.startswith(config.PUBLIC_URL):
        raise HTTPException(400, "url")
    img = qrcode.make(u, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# ---------- public call API (the patient side: no login, only an unguessable token) ----------
def get_call(db, token):
    c = db.query(Call).filter(Call.token == token).first()
    if not c:
        raise HTTPException(404, "call")
    return c


def _phrase(sc, part, lang):
    if part in ("greeting", "closing_ok", "closing_alert"):
        return sc[part][lang]
    q = next((q for q in sc["questions"] if q["id"] == part), None)
    return q[lang] if q else None


@app.get("/api/call/{token}")
def call_info(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    sc, lang = core.SCENARIOS[c.scenario], c.lang or "uz"
    return {"status": c.status, "lang": lang, "title": sc["title"][lang], "greeting": sc["greeting"][lang],
            "questions": [{"id": q["id"], "text": q[lang], "type": q["type"]} for q in sc["questions"]],
            "closing_ok": sc["closing_ok"][lang], "closing_alert": sc["closing_alert"][lang],
            "first_name": c.patient.full_name.split()[-1], "tts": voicelab.enabled()}


@app.get("/api/call/{token}/audio/{part}")
def call_audio(token: str, part: str, db=Depends(db_session)):
    c = get_call(db, token)
    text = _phrase(core.SCENARIOS[c.scenario], part, c.lang or "uz")
    wav = voicelab.tts(text, c.lang or "uz") if text else None
    if not wav:
        raise HTTPException(404, "no audio")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/call/{token}/answer")
async def call_answer(token: str, qid: str = Form(...), value: str = Form(""), audio: UploadFile = File(None), db=Depends(db_session)):
    c = get_call(db, token)
    sc = core.SCENARIOS[c.scenario]
    q = next((x for x in sc["questions"] if x["id"] == qid), None)
    if not q or c.status == "tugadi":
        raise HTTPException(400, "question")
    transcript, val = "", None
    if audio is not None:
        raw = await audio.read()
        def recognise():
            res = voicelab.stt(raw, audio.filename or "a.webm", audio.content_type or "audio/webm", c.lang or "uz") if len(raw) > 800 else None
            text = (res or {}).get("text", "")
            if q["type"] == "number":
                return text, extract.number(text)
            return text, (extract.yes_no(text, q[c.lang or "uz"]) if text else "unclear")
        transcript, val = await run_in_threadpool(recognise)
    elif value:
        if q["type"] == "number":
            val = extract.number(value)
            transcript = value
        else:
            val = value if value in ("yes", "no") else "unclear"
            transcript = {"yes": "ha (tugma)", "no": "yo'q (tugma)"}.get(val, "")
    answers = dict(c.answers or {})
    answers[qid] = {"value": val, "transcript": transcript}
    c.answers = answers
    c.status = "jarayonda"
    db.commit()
    return {"qid": qid, "value": val, "transcript": transcript}


@app.post("/api/call/{token}/finish")
def call_finish(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    if c.status == "tugadi":
        return {"alert": False, "done": True}
    res = core.finish_call(db, c)
    db.commit()
    return res


@app.post("/api/call/{token}/noanswer")
def call_noanswer(token: str, db=Depends(db_session)):
    c = get_call(db, token)
    n = core.call_no_answer(db, c)
    db.commit()
    return {"attempts": n, "status": c.status}


@app.post("/api/demo/reset")
def reset(db=Depends(db_session)):
    return {"patients": seed.run(db)}


@app.get("/call/{token}")
def call_page(token: str):
    return FileResponse(os.path.join(WEB, "call.html"))


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
