"""Shared pieces of the HTTP layer: database session, caller role, JSON views of the models."""

import json
import time

from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import event

from .. import config, core
from ..db import Patient, SessionLocal, User

ROLES = ("rahbar", "mutaxassis", "shifokor", "hamshira")
_snapshots = {}  # key -> (when, finished JSON)


@event.listens_for(SessionLocal, "after_commit")
def _forget_snapshots(_session):
    _snapshots.clear()  # anything written to the database makes every copy stale


def snapshot(key, build, seconds=3):
    """The finished JSON of a list that many screens ask for every few seconds. It is built once and served
    to all of them until it is `seconds` old or anything is written to the database: twenty open screens,
    or one runaway tab, cost one computation instead of twenty."""
    hit = _snapshots.get(key)
    if not hit or time.time() - hit[0] >= seconds:
        if len(_snapshots) > 300:
            _snapshots.clear()
        hit = _snapshots[key] = (time.time(), json.dumps(build(), ensure_ascii=False).encode())
    return Response(hit[1], media_type="application/json")


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


def require(*roles: str):
    """Dependency: the signed-in account must hold one of these roles."""

    def check(u: User = Depends(current_user)) -> User:
        if u.role not in roles:
            raise HTTPException(403, "role")
        return u

    return check


def can_close(u: User, task) -> bool:
    """The head closes any task; others only tasks of their role, a family doctor only for own patients."""
    if u.role == "rahbar":
        return True
    if u.role != task.role:
        return False
    return not (u.role == "shifokor" and u.doctor_name and task.patient and task.patient.doctor != u.doctor_name)


def get_patient(db, pid: int) -> Patient:
    p = db.get(Patient, pid)
    if not p:
        raise HTTPException(404, "patient")
    return p


def iso(d):
    return d.isoformat() + "Z" if d else None


def sees_all(u, p):
    """Who may see a confidential dispensary group and its diagnosis: the specialist, the head of the
    district, and the family doctor the patient is attached to. Everyone else sees only that the patient is
    under dispensary follow-up."""
    return bool(u) and (u.role in ("rahbar", "mutaxassis") or (u.role == "shifokor" and (not u.doctor_name or p.doctor == u.doctor_name)))


def marks(p, u=None):
    """The dispensary marks on a patient, as this viewer may see them."""
    out, hidden = [], False
    for g in p.groups or []:
        spec = core.GROUPS.get(g)
        if not spec:
            continue
        if spec["secret"] and not sees_all(u, p):
            hidden = True
            continue
        out.append({"code": g, "uz": spec["uz"], "ru": spec["ru"], "secret": spec["secret"]})
    if hidden:
        out.append({"code": "maxfiy", "uz": "Dispanser hisobida", "ru": "Диспансерный учёт", "secret": True})
    return out


def masked(p, u):
    """True when this viewer must not see the patient's diagnosis: it belongs to a confidential group."""
    return any(core.GROUPS.get(g, {}).get("secret") for g in p.groups or []) and not sees_all(u, p)


def brief(p, u=None):
    return {
        "marks": marks(p, u),
        "sex": p.sex,
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
        "private_consent": bool(p.private_consent_at),  # agreed to calls about confidential dispensary follow-up
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
        "closing": c.closing,
        "closing_by": c.closing_by,
        "planned_at": iso(c.planned_at),
        "finished_at": iso(c.finished_at),
        "attempts": c.attempts,
        "task_id": c.task_id,
        "due": c.status == "rejalashtirilgan" and c.planned_at <= core.now(),
        "url": f"{config.PUBLIC_URL}/call/{c.token}",
        "title": core.SCENARIOS[c.scenario]["title"],
        "patient": {"id": c.patient.id, "name": c.patient.full_name} if c.patient else None,
    }
