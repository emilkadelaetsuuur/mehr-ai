"""Shared pieces of the HTTP layer: database session, caller role, JSON views of the models."""

import hashlib
import hmac

from fastapi import Header, HTTPException

from .. import config, core
from ..db import Patient, SessionLocal

ROLES = ("rahbar", "mutaxassis", "shifokor", "hamshira")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def role(x_role: str = Header("rahbar")):
    """The role the interface is used in. It scopes lists and is written to the audit log."""
    return x_role if x_role in ROLES else "rahbar"


def auth_token():
    return hmac.new(config.SECRET_KEY.encode(), config.DEMO_PASSWORD.encode(), hashlib.sha256).hexdigest()[:40]


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
