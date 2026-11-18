"""The exchange with DMED: where the platform sends events, what staff see of the exchange, and the stand-in."""

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import config, core, dmed, exchange, vaccines
from ..db import DmedMessage, Hospitalization, Patient
from ..schemas import DmedEventIn
from .deps import db_session, get_patient, iso, require

router = APIRouter(prefix="/api/dmed")


def entry(m, names):
    return {
        "id": m.id,
        "direction": m.direction,
        "kind": m.kind,
        "summary": m.summary,
        "status": m.status,
        "error": m.error,
        "at": iso(m.created_at),
        "sent_at": iso(m.sent_at),
        "patient": {"id": m.patient_id, "name": names.get(m.patient_id, "")} if m.patient_id else None,
        "payload": m.payload,
    }


@router.post("/fhir")
def inbound(resource: dict, x_dmed_key: str = Header(""), db=Depends(db_session)):
    """Where DMED sends what happened to a patient: FHIR resources or a bundle of them. The platform presents
    the key agreed with it; without a key configured nothing is accepted from outside."""
    if not config.DMED_INBOUND_KEY or not hmac.compare_digest(x_dmed_key.encode(), config.DMED_INBOUND_KEY.encode()):
        raise HTTPException(403, "key")
    rows = exchange.receive(db, resource)
    db.commit()
    return {"accepted": [{"kind": m.kind, "status": m.status, "summary": m.summary} for m in rows]}


@router.get("")
def state(db=Depends(db_session), u=Depends(require("rahbar", "mutaxassis"))):
    """The state of the link and the latest messages both ways."""
    rows = db.query(DmedMessage).order_by(DmedMessage.id.desc()).limit(80).all()
    ids = {m.patient_id for m in rows if m.patient_id}
    names = dict(db.query(Patient.id, Patient.full_name).filter(Patient.id.in_(ids))) if ids else {}
    count = lambda *where: db.query(DmedMessage).filter(*where).count()  # noqa: E731
    return {
        "mode": dmed.mode(),
        "address": config.DMED_BASE_URL or None,
        "accepts_events": bool(config.DMED_INBOUND_KEY),
        "received": count(DmedMessage.direction == "in"),
        "sent": count(DmedMessage.direction == "out", DmedMessage.status == "yuborildi"),
        "waiting": count(DmedMessage.direction == "out", DmedMessage.status == "navbatda"),
        "failed": count(DmedMessage.direction == "out", DmedMessage.status == "xato"),
        "messages": [entry(m, names) for m in rows],
    }


@router.post("/simulate")
def simulate(body: DmedEventIn, db=Depends(db_session), u=Depends(require("rahbar", "mutaxassis"))):
    """The stand-in for DMED: sends an event the way the platform would, through the same door.
    For showing and trying the system while there is no access to the real platform."""
    p = get_patient(db, body.patient_id)
    if not p.pinfl:
        raise HTTPException(400, "pinfl")
    if body.event == "vaccine":
        # the vaccination room records what was given: the doses that are due, and those only a parent has reported
        doses = [d["id"] for d in vaccines.plan(p, core.now()) if d["state"] in ("due", "overdue", "said")]
        if not doses:
            raise HTTPException(400, "nothing due")
        resource = {"resourceType": "Bundle", "type": "message", "entry": [{"resource": dmed.immunization(p, c, core.now())} for c in doses]}
    else:
        stay = (
            db.query(Hospitalization)
            .filter(Hospitalization.patient_id == p.id, Hospitalization.discharged_at.is_(None))
            .order_by(Hospitalization.id.desc())
            .first()
        )
        if body.event == "admit":
            if stay:
                raise HTTPException(409, "already in hospital")
            resource = dmed.encounter(p, body.hospital, core.now(), None, body.emergency, body.reason, "", "", body.brought_by)
        else:
            start = stay.admitted_at if stay else core.now() - timedelta(days=3)
            resource = dmed.encounter(
                p,
                body.hospital or (stay.hospital if stay else ""),
                start,
                core.now(),
                stay.emergency if stay else body.emergency,
                body.reason or (stay.reason if stay else ""),
                body.icd10.upper(),
                body.diagnosis,
                body.brought_by or (stay.brought_by if stay else ""),
                body.advice,
                stay.external_id if stay else None,
            )
    rows = exchange.receive(db, resource)
    core.audit(db, u, "dmed_simulated", p, body.event)
    db.commit()
    return {"accepted": [{"kind": m.kind, "status": m.status, "summary": m.summary} for m in rows]}
