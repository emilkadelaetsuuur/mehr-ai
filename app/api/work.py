"""Work queues of the staff: tasks with the 24-hour timer and the list of AI calls."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import joinedload

from .. import carepath, core, simline, telephony
from ..db import Call, Patient, Task
from ..schemas import DialIn, NoteIn, RoundIn
from .care import authorized
from .deps import call_json, can_close, current_user, db_session, snapshot, task_json


def private_scope(scenario, u):
    if scenario not in (carepath.PRIVATE | {"dispanser"}):
        return None
    if u.role in {"rahbar", "mutaxassis"}:
        return None
    if u.role == "shifokor" and u.doctor_name:
        return u.doctor_name
    raise HTTPException(403, "role")


router = APIRouter(prefix="/api")


@router.get("/tasks")
def tasks(status: str = "", db=Depends(db_session), u=Depends(current_user)):
    """The head sees every task; others see their role's queue; a family doctor sees only their own patients."""

    def build():
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

    return snapshot(("tasks", status, u.role, u.doctor_name), build)


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
def calls(db=Depends(db_session), u=Depends(current_user)):
    def build():
        rows = db.query(Call).options(joinedload(Call.patient)).order_by(Call.planned_at.desc()).limit(150).all()
        return [call_json(c) for c in rows if c.scenario not in (carepath.PRIVATE | {"dispanser"}) or authorized(db, c.patient, u)]

    return snapshot(("calls", u.role, u.doctor_name), build)


@router.get("/calls/audience")
def round_audience(scenario: str, zone: str = "", db=Depends(db_session), u=Depends(current_user)):
    """How many patients a calling round would reach, and why the others are left out."""
    if scenario not in core.SCENARIOS:
        raise HTTPException(400, "scenario")
    a = core.audience(db, scenario, zone if zone in ("red", "yellow", "green") else "", private_scope(scenario, u))
    return {"fit": len(a["fit"]), "no_consent": a["no_consent"], "already": a["already"], "who": core.SCENARIOS[scenario].get("who", "any")}


@router.post("/calls/round")
def start_round(body: RoundIn, db=Depends(db_session), u=Depends(current_user)):
    """Start a calling round for a group, or one trial call whose link opens as a QR code."""
    if body.scenario not in core.SCENARIOS:
        raise HTTPException(400, "scenario")
    doctor = private_scope(body.scenario, u)
    if body.test and body.scenario in carepath.TARGETED:
        from .care import example_call

        c = example_call(db, body.scenario, u, body.lang)
        made = [c] if c else []
    elif body.test:
        c = core.trial_call(db, body.scenario, body.lang)
        if c and doctor is not None and c.patient.doctor != doctor:
            raise HTTPException(403, "role")
        made = [c] if c else []
    else:
        made = core.start_round(db, body.scenario, body.lang, body.zone, body.limit, doctor)
    if made:
        core.audit(
            db, u, "round_started", None if len(made) > 1 else made[0].patient, f"{body.scenario}: {len(made)} qo'ng'iroq" + (" (sinov)" if body.test else "")
        )
    db.commit()
    return {"calls": [call_json(c) for c in made]}


@router.post("/calls/{cid}/dial")
def dial(cid: int, body: DialIn = DialIn(), db=Depends(db_session), u=Depends(current_user)):
    """Ring a real phone (needs a telephony provider in the settings): the number on the patient's card,
    or another number given for this call, which is how a demo rings the presenter's own phone."""
    c = db.get(Call, cid)
    if not c or c.status not in core.UNFINISHED:
        raise HTTPException(404, "call")
    if carepath.test_line(db, c):
        raise HTTPException(409, "test_call_by_link")
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


@router.post("/calls/{cid}/sim")
def ring_by_sim(cid: int, body: DialIn = DialIn(), db=Depends(db_session), u=Depends(current_user)):
    """Ring through the phone with a SIM card that stands by as the telephone line (app/simline.py)."""
    c = db.get(Call, cid)
    if not c or c.status not in core.UNFINISHED:
        raise HTTPException(404, "call")
    if carepath.test_line(db, c):
        raise HTTPException(409, "test_call_by_link")
    if not simline.online():
        raise HTTPException(409, "line")
    to = telephony.number(body.phone.strip() or c.patient.phone)
    if not to:
        raise HTTPException(400, "phone")
    simline.ask(c, to)
    core.audit(db, u, "call_dialed", c.patient, f"{c.scenario} SIM -> {to[:5]}…{to[-2:]}")
    db.commit()
    return {"queued": True, "to": to}
