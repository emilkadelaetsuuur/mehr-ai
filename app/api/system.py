"""Login and accounts, district dashboard, reference data, laboratory import, audit log."""

import io
import json
import logging
import os
import time

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import event

from .. import auth, closing, config, core, dmed, ml, rules, seed, simline, telegram, telephony, vaccines, voiceguide, voicelab
from ..db import AuditLog, Hospitalization, Notice, Patient, SessionLocal, User
from ..schemas import LabImportIn, LoginIn, PasswordIn
from .deps import brief, current_user, db_session, iso, masked, require, snapshot

router = APIRouter(prefix="/api")
log = logging.getLogger("nigoh.auth")
_dash = {"at": 0.0, "data": None}


@event.listens_for(SessionLocal, "after_commit")
def _invalidate(_session):
    _dash["data"] = None  # any write makes the cached district summary stale


@router.get("/health")
async def health():
    """Answered by the event loop itself: it tells the truth even when every worker thread is busy."""
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db=Depends(db_session)):
    ip = request.client.host if request.client else "-"
    if auth.throttled(ip):
        raise HTTPException(429, "too_many")
    username, password = body.username.strip().lower(), auth.clean_password(body.password)
    user = db.query(User).filter(User.username == username).first()
    if config.DEMO_PASSWORD and not (user and auth.check_password(password, user.password_hash)):
        auth.note_failure(ip)
        log.warning("sign-in refused: account=%r reason=%s", username[:40], auth.failure_hint(user, password))
        raise HTTPException(401, "wrong")
    auth.clear_failures(ip)
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
    new = auth.clean_password(body.new)
    if not auth.check_password(auth.clean_password(body.old), u.password_hash):
        raise HTTPException(400, "wrong")
    if len(new) < 6:
        raise HTTPException(422, "short")
    u.password_hash = auth.hash_password(new)
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
        "voice_questions": voiceguide.QUESTIONS,
        "telephony": telephony.enabled(),
        "sim": simline.enabled(),  # a phone with a SIM card can stand in as the telephone line
        "sim_online": simline.online(),
        "closing": {lang: [w[0] for w in closing.writers(lang)] for lang in ("uz", "ru")},
        "claude": {"enabled": closing.enabled(), "model": config.CLAUDE_MODEL},
        "ml": ml.metrics(),
        "rules": rules.T,
        "complaints": {k: {"uz": v[0], "ru": v[1]} for k, v in rules.COMPLAINTS.items()},
        "scenarios": [
            {"id": s["id"], "title": s["title"], "basis": s["basis"], "questions": len(s["questions"]), "who": s["who"], "private": bool(s.get("private"))}
            for s in core.SCENARIOS.values()
        ],
        "flags": {k: {"uz": v[0], "ru": v[1]} for k, v in rules.LABELS.items()},  # what a call may mark besides complaints
        "groups": {k: {"uz": v["uz"], "ru": v["ru"], "secret": v["secret"]} for k, v in core.GROUPS.items()},
        "vaccines": {"ages": {k: v["label"] for k, v in vaccines.AGES.items()}, "note": vaccines.CALENDAR["note"]},
        "dmed": {"mode": dmed.mode(), "address": config.DMED_BASE_URL or None},
        "eval": ev,
        "hours": config.ACTIVE_CALL_HOURS,
        "accounts": [{"username": x.username, "name": x.full_name, "role": x.role} for x in db.query(User).order_by(User.id)],
    }


@router.get("/dashboard")
def dashboard(db=Depends(db_session), u=Depends(current_user)):
    def build():
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
        names = ("Sodiqova Dilnoza", "Valiyeva Madina", "Valiyev Amir", "Karimov Yusuf", "Rahimov Botir", "Toshmatov Sardor")
        d["demo"] = [brief(p, u) for n in names for p in db.query(Patient).filter(Patient.full_name == n).limit(1)]
        # What DMED reported from hospitals: a family doctor sees own patients, the others see the district.
        stays = db.query(Hospitalization).order_by(Hospitalization.id.desc()).limit(60).all()
        mine = [s for s in stays if s.patient and (u.role != "shifokor" or not u.doctor_name or s.patient.doctor == u.doctor_name)][:12]
        d["stays"] = [
            {
                "id": s.id,
                "patient": {"id": s.patient.id, "name": s.patient.full_name, "mahalla": s.patient.mahalla, "doctor": s.patient.doctor},
                "hospital": s.hospital,
                "emergency": s.emergency,
                "brought_by": s.brought_by,
                "reason": None if masked(s.patient, u) else s.reason,
                "icd10": None if masked(s.patient, u) else s.icd10,
                "diagnosis": None if masked(s.patient, u) else s.diagnosis,
                "admitted_at": iso(s.admitted_at),
                "discharged_at": iso(s.discharged_at),
            }
            for s in mine
        ]
        return d

    return snapshot(("dashboard", u.role, u.doctor_name), build)


@router.get("/audit")
def audit_log(patient_id: int = 0, db=Depends(db_session), u=Depends(current_user)):
    if not patient_id and u.role != "rahbar":  # the district-wide journal is for the head only
        raise HTTPException(403, "role")
    q = db.query(AuditLog)
    if patient_id:
        from .care import access

        person = db.get(Patient, patient_id)
        if person:
            access(db, person, u)
        q = q.filter(AuditLog.patient_id == patient_id)
    return [
        {"at": iso(a.at), "role": a.role, "actor": a.actor, "action": a.action, "patient_id": a.patient_id, "detail": a.detail}
        for a in q.order_by(AuditLog.id.desc()).limit(100)
    ]


@router.post("/import/lab")
def import_lab(body: LabImportIn, db=Depends(db_session), u=Depends(require("rahbar", "mutaxassis"))):
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
def reset(db=Depends(db_session), u=Depends(require("rahbar"))):
    n = seed.run(db)
    core.audit(db, u, "demo_reset", None, f"{n} bemor")
    db.commit()
    return {"patients": n}
