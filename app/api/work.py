"""Work queues of the staff: tasks with the 24-hour timer and the list of AI calls."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import joinedload

from .. import core, telephony
from ..db import Call, Patient, Task
from ..schemas import DialIn, NoteIn
from .deps import call_json, can_close, current_user, db_session, task_json

router = APIRouter(prefix="/api")


@router.get("/tasks")
def tasks(status: str = "", db=Depends(db_session), u=Depends(current_user)):
    """The head sees every task; others see their role's queue; a family doctor sees only their own patients."""
    qs = db.query(Task).options(joinedload(Task.patient))
    if status:
        qs = qs.filter(Task.status == status)
    if u.role != "rahbar":
        qs = qs.filter(Task.role == u.role)
        if u.role == "shifokor" and u.doctor_name:
            qs = qs.join(Patient, Task.patient_id == Patient.id).filter(Patient.doctor == u.doctor_name)
    rows = qs.order_by(Task.due_at.asc()).limit(300).all()
    rows.sort(key=lambda t: (t.status != "ochiq", t.due_at or core.now()))
    return [task_json(t) for t in rows]


@router.post("/tasks/{tid}/done")
def done(tid: int, body: NoteIn = NoteIn(), db=Depends(db_session), u=Depends(current_user)):
    """The doctor marks the visit as done; the patient is then asked to confirm it."""
    t = db.get(Task, tid)
    if not t or t.status != "ochiq":
        raise HTTPException(404, "task")
    if not can_close(u, t):
        raise HTTPException(403, "role")
    c = core.task_done(db, t, body.note)
    core.audit(db, u, "task_done", t.patient, f"{t.type}; bemor tasdig'i {'so`raladi' if c else 'yo`q: rozilik olinmagan'}")
    db.commit()
    return {"task": task_json(t), "call": call_json(c) if c else None}


@router.get("/calls")
def calls(db=Depends(db_session)):
    rows = db.query(Call).options(joinedload(Call.patient)).order_by(Call.planned_at.desc()).limit(150).all()
    return [call_json(c) for c in rows]


@router.post("/calls/{cid}/dial")
def dial(cid: int, body: DialIn = DialIn(), db=Depends(db_session), u=Depends(current_user)):
    """Ring a real phone (needs a telephony provider in the settings): the number on the patient's card,
    or another number given for this call, which is how a demo rings the presenter's own phone."""
    c = db.get(Call, cid)
    if not c or c.status in ("tugadi", "javobsiz"):
        raise HTTPException(404, "call")
    if not telephony.enabled():
        raise HTTPException(409, "telephony")
    to = telephony.number(body.phone.strip() or c.patient.phone)
    if not to:
        raise HTTPException(400, "phone")
    try:
        sid = telephony.dial(c, to)
    except Exception as e:
        raise HTTPException(502, f"provider: {e}"[:300])
    core.audit(db, u, "call_dialed", c.patient, f"{c.scenario} -> {to[:5]}…{to[-2:]}")
    db.commit()
    return {"sid": sid, "to": to}
