"""Work queues of the staff: tasks with the 24-hour timer and the list of AI calls."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import joinedload

from .. import core
from ..db import Call, Task
from ..schemas import NoteIn
from .deps import call_json, db_session, role, task_json

router = APIRouter(prefix="/api")


@router.get("/tasks")
def tasks(status: str = "", role: str = "", db=Depends(db_session)):
    qs = db.query(Task).options(joinedload(Task.patient))
    if status:
        qs = qs.filter(Task.status == status)
    if role:
        qs = qs.filter(Task.role == role)
    rows = qs.order_by(Task.due_at.asc()).limit(300).all()
    rows.sort(key=lambda t: (t.status != "ochiq", t.due_at or core.now()))
    return [task_json(t) for t in rows]


@router.post("/tasks/{tid}/done")
def done(tid: int, body: NoteIn = NoteIn(), db=Depends(db_session), r: str = Depends(role)):
    """The doctor marks the visit as done; the patient is then asked to confirm it."""
    t = db.get(Task, tid)
    if not t or t.status != "ochiq":
        raise HTTPException(404, "task")
    c = core.task_done(db, t, body.note)
    core.audit(db, r, "task_done", t.patient, f"{t.type}; bemor tasdig'i {'so`raladi' if c else 'yo`q: rozilik olinmagan'}")
    db.commit()
    return {"task": task_json(t), "call": call_json(c) if c else None}


@router.get("/calls")
def calls(db=Depends(db_session)):
    rows = db.query(Call).options(joinedload(Call.patient)).order_by(Call.planned_at.desc()).limit(150).all()
    return [call_json(c) for c in rows]
