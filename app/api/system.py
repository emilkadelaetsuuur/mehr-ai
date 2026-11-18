"""Login, district dashboard, reference data, laboratory import, audit log."""

import hmac
import io
import json
import os
import time

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import event

from .. import config, core, ml, rules, seed, voicelab
from ..db import AuditLog, Notice, Patient, SessionLocal
from ..schemas import LabImportIn, LoginIn
from .deps import auth_token, brief, db_session, iso, role

router = APIRouter(prefix="/api")
_dash = {"at": 0.0, "data": None}


@event.listens_for(SessionLocal, "after_commit")
def _invalidate(_session):
    _dash["data"] = None  # any write makes the cached district summary stale


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/login")
def login(body: LoginIn, response: Response):
    if config.DEMO_PASSWORD and not hmac.compare_digest(body.password, config.DEMO_PASSWORD):
        raise HTTPException(401, "wrong")
    response.set_cookie("nigoh_auth", auth_token(), httponly=True, samesite="lax", max_age=14 * 86400, secure=config.PUBLIC_URL.startswith("https"))
    return {"ok": True}


@router.get("/me")
def me(r: str = Depends(role)):
    return {"ok": True, "role": r}


@router.get("/meta")
def meta():
    ev_path = os.path.join(config.DATA_DIR, "eval.json")
    ev = None
    if os.path.exists(ev_path):
        with open(ev_path, encoding="utf-8") as f:
            ev = json.load(f)
    return {
        "district": config.DISTRICT,
        "auth": bool(config.DEMO_PASSWORD),
        "voicelab": voicelab.status(),
        "ml": ml.metrics(),
        "rules": rules.T,
        "complaints": {k: {"uz": v[0], "ru": v[1]} for k, v in rules.COMPLAINTS.items()},
        "scenarios": [
            {"id": s["id"], "title": s["title"], "basis": s["basis"], "questions": len(s["questions"]), "who": s["who"]} for s in core.SCENARIOS.values()
        ],
        "eval": ev,
        "hours": config.ACTIVE_CALL_HOURS,
    }


@router.get("/dashboard")
def dashboard(db=Depends(db_session), r: str = Depends(role)):
    if _dash["data"] is None or time.time() - _dash["at"] > 5:
        _dash["data"], _dash["at"] = core.dashboard(db), time.time()
    d = dict(_dash["data"])
    q = db.query(Notice)
    if r != "rahbar":  # everyone sees their own notices; the head of the district sees all
        q = q.filter(Notice.role == r)
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
        {"at": iso(a.at), "role": a.role, "action": a.action, "patient_id": a.patient_id, "detail": a.detail} for a in q.order_by(AuditLog.id.desc()).limit(100)
    ]


@router.post("/import/lab")
def import_lab(body: LabImportIn, db=Depends(db_session), r: str = Depends(role)):
    res = core.import_lab(db, body.csv)
    core.audit(db, r, "lab_import", None, f"{res['matched']}/{res['rows']} qator, {len(res['changed'])} zona o'zgardi")
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
def reset(db=Depends(db_session), r: str = Depends(role)):
    n = seed.run(db)
    core.audit(db, r, "demo_reset", None, f"{n} bemor")
    db.commit()
    return {"patients": n}
