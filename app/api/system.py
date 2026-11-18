"""Login and accounts, district dashboard, reference data, laboratory import, audit log."""

import io
import json
import os
import time

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import event

from .. import auth, config, core, ml, rules, seed, telegram, telephony, voicelab
from ..db import AuditLog, Notice, Patient, SessionLocal, User
from ..schemas import LabImportIn, LoginIn, PasswordIn
from .deps import brief, current_user, db_session, iso

router = APIRouter(prefix="/api")
_dash = {"at": 0.0, "data": None}


@event.listens_for(SessionLocal, "after_commit")
def _invalidate(_session):
    _dash["data"] = None  # any write makes the cached district summary stale


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, response: Response, db=Depends(db_session)):
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if config.DEMO_PASSWORD and not (user and auth.check_password(body.password, user.password_hash)):
        raise HTTPException(401, "wrong")
    if user:
        response.set_cookie(
            auth.COOKIE,
            auth.make_session(user.id),
            httponly=True,
            samesite="lax",
            max_age=config.SESSION_DAYS * 86400,
            secure=config.PUBLIC_URL.startswith("https"),
        )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/me")
def me(u=Depends(current_user)):
    return {
        "username": u.username,
        "name": u.full_name,
        "role": u.role,
        "doctor": u.doctor_name,
        "auth": bool(config.DEMO_PASSWORD),
        "telegram": {"enabled": telegram.enabled(), "linked": bool(u.telegram_chat_id), "link": telegram.link_for(u)},
    }


@router.post("/me/password")
def change_password(body: PasswordIn, db=Depends(db_session), u=Depends(current_user)):
    if not auth.check_password(body.old, u.password_hash):
        raise HTTPException(400, "wrong")
    u.password_hash = auth.hash_password(body.new)
    core.audit(db, u, "password_changed")
    db.commit()
    return {"ok": True}


@router.get("/meta")
def meta(db=Depends(db_session)):
    ev_path = os.path.join(config.DATA_DIR, "eval.json")
    ev = None
    if os.path.exists(ev_path):
        with open(ev_path, encoding="utf-8") as f:
            ev = json.load(f)
    return {
        "district": config.DISTRICT,
        "auth": bool(config.DEMO_PASSWORD),
        "voicelab": voicelab.status(),
        "telephony": telephony.enabled(),
        "ml": ml.metrics(),
        "rules": rules.T,
        "complaints": {k: {"uz": v[0], "ru": v[1]} for k, v in rules.COMPLAINTS.items()},
        "scenarios": [
            {"id": s["id"], "title": s["title"], "basis": s["basis"], "questions": len(s["questions"]), "who": s["who"]} for s in core.SCENARIOS.values()
        ],
        "eval": ev,
        "hours": config.ACTIVE_CALL_HOURS,
        "accounts": [{"username": x.username, "name": x.full_name, "role": x.role} for x in db.query(User).order_by(User.id)],
    }


@router.get("/dashboard")
def dashboard(db=Depends(db_session), u=Depends(current_user)):
    if _dash["data"] is None or time.time() - _dash["at"] > 5:
        _dash["data"], _dash["at"] = core.dashboard(db), time.time()
    d = dict(_dash["data"])
    q = db.query(Notice)
    if u.role != "rahbar":  # everyone sees their own notices; the head of the district sees all
        q = q.filter(Notice.role == u.role)
    d["notices"] = [
        {"id": n.id, "level": n.level, "role": n.role, "uz": n.text_uz, "ru": n.text_ru, "at": iso(n.created_at), "patient_id": n.patient_id}
        for n in q.order_by(Notice.id.desc()).limit(25)
    ]
    d["demo"] = [brief(p) for n in ("Sodiqova Dilnoza", "Valiyeva Madina", "Valiyev Amir") for p in db.query(Patient).filter(Patient.full_name == n).limit(1)]
    return d


@router.get("/audit")
def audit_log(patient_id: int = 0, db=Depends(db_session)):
    q = db.query(AuditLog)
    if patient_id:
        q = q.filter(AuditLog.patient_id == patient_id)
    return [
        {"at": iso(a.at), "role": a.role, "actor": a.actor, "action": a.action, "patient_id": a.patient_id, "detail": a.detail}
        for a in q.order_by(AuditLog.id.desc()).limit(100)
    ]


@router.post("/import/lab")
def import_lab(body: LabImportIn, db=Depends(db_session), u=Depends(current_user)):
    res = core.import_lab(db, body.csv)
    core.audit(db, u, "lab_import", None, f"{res['matched']}/{res['rows']} qator, {len(res['changed'])} zona o'zgardi")
    db.commit()
    return res


@router.get("/qr")
def qr(u: str):
    if not u.startswith(config.PUBLIC_URL):
        raise HTTPException(400, "url")
    img = qrcode.make(u, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@router.post("/demo/reset")
def reset(db=Depends(db_session), u=Depends(current_user)):
    n = seed.run(db)
    core.audit(db, u, "demo_reset", None, f"{n} bemor")
    db.commit()
    return {"patients": n}
