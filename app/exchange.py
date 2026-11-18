"""What DMED tells this system, and what follows from it.

A patient is taken to a hospital somewhere in the country: DMED knows, the family doctor does not. Here the
news arrives as it happens. An admission is shown to the person the patient is attached to at once; a
discharge brings the diagnosis, opens the active call and plans an AI call for the next day with the
questions written for that diagnosis; a vaccination recorded in a vaccination room closes the dose in the
child's calendar. Every message is kept in the exchange log with what was done about it.
"""

from . import core, dmed, vaccines
from .db import DmedMessage, Hospitalization, Patient


def find(db, pinfl, name=""):
    """The patient DMED means: by PINFL, or by the full name when the message carries no number."""
    p = db.query(Patient).filter(Patient.pinfl == pinfl).first() if pinfl else None
    return p or (db.query(Patient).filter(Patient.full_name == name).first() if name else None)


def note(db, kind, patient, resource, summary, status="qabul"):
    m = DmedMessage(
        direction="in",
        kind=kind[:40],
        patient_id=patient.id if patient else None,
        summary=summary[:240],
        payload=resource,
        status=status,
        created_at=core.now(),
    )
    db.add(m)
    return m


def receive(db, resource):
    """Act on a resource or a bundle of them. Returns the log entries, one for each resource that was read."""
    parts = [e.get("resource") or {} for e in resource.get("entry") or []] if resource.get("resourceType") == "Bundle" else [resource]
    advice = next((r.get("description") or "" for r in parts if r.get("resourceType") == "CarePlan"), "")
    done = []
    for r in parts:
        if r.get("resourceType") == "Encounter":
            done.append(_stay(db, r, advice))
        elif r.get("resourceType") == "Immunization":
            done.append(_dose(db, r))
    return done


def _stay(db, e, advice):
    f = dmed.read_encounter(e)
    p = find(db, f["pinfl"], f["name"])
    if not p:  # somebody who is not in this district's register: kept in the log, nothing else
        return note(db, "Encounter", None, e, f"bemor topilmadi: {f['name'] or f['pinfl'] or '?'}", "topilmadi")
    # the stay this message continues, if it is known already (also one written a moment ago and not saved yet)
    stay = next((s for s in p.stays if s.external_id == f["id"]), None) if f["id"] else None
    new = stay is None
    if new:
        stay = Hospitalization(patient_id=p.id, external_id=f["id"], created_at=core.now(), admitted_at=f["start"] or core.now())
        db.add(stay)
        p.stays.append(stay)
    stay.emergency = f["emergency"] if new else stay.emergency
    for field in ("hospital", "reason", "icd10", "diagnosis", "brought_by"):
        if f[field]:
            setattr(stay, field, f[field][:240] if field != "icd10" else f[field][:12])
    if advice:
        stay.advice = advice[:2000]
    if new and not f["over"]:
        core.admitted(db, p, stay)
        return note(db, "Encounter: yotqizildi", p, e, f"{stay.hospital}: {stay.reason or ''}")
    if f["over"] and not stay.discharged_at:
        stay.discharged_at = f["end"] or core.now()
        core.discharged(db, p, stay)
        return note(db, "Encounter: chiqarildi", p, e, f"{stay.hospital}: {stay.icd10 or ''} {stay.diagnosis or ''}".strip())
    return note(db, "Encounter: yangilandi", p, e, stay.hospital or "")


def _dose(db, r):
    f = dmed.read_immunization(r)
    p = find(db, f["pinfl"], f["name"])
    if not p or not f["code"]:
        return note(db, "Immunization", p, r, "bemor yoki emlash kodi topilmadi", "topilmadi")
    vaccines.record(db, p, [f["code"]], "dmed", f["at"] or core.now(), confirmed=True)
    core.audit(db, "dmed", "vaccination_recorded", p, vaccines.DOSES[f["code"]]["short"])
    return note(db, "Immunization: emlandi", p, r, vaccines.DOSES[f["code"]]["short"])
