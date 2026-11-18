"""Shared pieces of the HTTP layer: database session, caller role, JSON views of the models."""

from fastapi import Depends, Header, HTTPException, Request

from .. import config, core
from ..db import Patient, SessionLocal, User

ROLES = ("rahbar", "mutaxassis", "shifokor", "hamshira")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db=Depends(db_session), x_role: str = Header("")) -> User:
    """The signed-in account. With auth switched off (local runs, tests) the caller acts as the
    head of the district, or as the role named in X-Role."""
    uid = getattr(request.state, "uid", None)
    user = db.get(User, uid) if uid else None
    if user:
        return user
    return db.query(User).filter(User.role == (x_role if x_role in ROLES else "rahbar")).first()


def get_patient(db, pid: int) -> Patient:
    p = db.get(Patient, pid)
    if not p:
        raise HTTPException(404, "patient")
    return p


def iso(d):
    return d.isoformat() + "Z" if d else None


def brief(p):
    return {
        "id": p.id,
        "name": p.full_name,
        "kind": p.kind,
        "zone": p.zone,
        "mahalla": p.mahalla,
        "weeks": p.weeks,
        "birth_year": p.birth_year,
        "doctor": p.doctor,
        "phone": p.phone,
        "last_contact": iso(p.last_contact_at),
        "top": (p.reasons or [None])[0],
        "born_at": iso(p.born_at),
        "consent": bool(p.consent_at),
    }


def task_json(t):
    p = t.patient
    return {
        "id": t.id,
        "type": t.type,
        "role": t.role,
        "reason": t.reason,
        "status": t.status,
        "due_at": iso(t.due_at),
        "done_at": iso(t.done_at),
        "created_at": iso(t.created_at),
        "escalated": t.escalated,
        "note": t.note,
        "patient": {"id": p.id, "name": p.full_name, "zone": p.zone, "mahalla": p.mahalla, "phone": p.phone, "doctor": p.doctor} if p else None,
    }


def call_json(c):
    return {
        "id": c.id,
        "token": c.token,
        "scenario": c.scenario,
        "status": c.status,
        "flags": c.flags,
        "answers": c.answers,
        "planned_at": iso(c.planned_at),
        "finished_at": iso(c.finished_at),
        "attempts": c.attempts,
        "task_id": c.task_id,
        "due": c.status == "rejalashtirilgan" and c.planned_at <= core.now(),
        "url": f"{config.PUBLIC_URL}/call/{c.token}",
        "title": core.SCENARIOS[c.scenario]["title"],
        "patient": {"id": c.patient.id, "name": c.patient.full_name} if c.patient else None,
    }
