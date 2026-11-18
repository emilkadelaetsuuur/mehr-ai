"""The rig that rings through a phone with a SIM card (see app/simline.py) talks to the server here."""

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import core, simline
from ..db import Call
from ..schemas import LineReportIn
from .deps import db_session

router = APIRouter(prefix="/api/gateway")


def rig(x_gateway_key: str = Header("")):
    """Only the program that holds the key may ask for numbers to ring."""
    if not simline.allowed(x_gateway_key):
        raise HTTPException(403, "key")


@router.get("/next", dependencies=[Depends(rig)])
def next_call():
    """The next call to ring, or nothing. Asking is also the rig's sign of life."""
    return {"call": simline.take()}


@router.get("/state", dependencies=[Depends(rig)])
def line_state(token: str):
    return {"state": simline.state(token)}


@router.post("/report", dependencies=[Depends(rig)])
def report(body: LineReportIn, db=Depends(db_session)):
    """What happened on the line: dialling, answered, nobody answered, ended."""
    simline.report(body.token, body.state)
    if body.state == "noanswer":
        c = db.query(Call).filter(Call.token == body.token).first()
        if c and c.status not in ("tugadi", "javobsiz"):
            core.call_no_answer(db, c)  # three unanswered attempts become a home visit for the nurse
            db.commit()
    return {"ok": True}
