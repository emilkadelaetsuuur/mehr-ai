"""Registry: list, patient card, confirmed voice card, results, discharge, consent, exports."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import config, core, fhir, ml, pdfgen, rules
from ..db import AuditLog, Patient
from ..schemas import CallIn, ConfirmIn, NoteIn, ObservationIn
from .deps import brief, call_json, db_session, get_patient, iso, role, task_json

router = APIRouter(prefix="/api/patients")


@router.get("")
def list_patients(zone: str = "", q: str = "", kind: str = "", silent: int = 0, limit: int = 400, db=Depends(db_session)):
    qs = db.query(Patient)
    if zone:
        qs = qs.filter(Patient.zone == zone)
    if kind:
        qs = qs.filter(Patient.kind == kind)
    if q:
        qs = qs.filter(Patient.full_name.ilike(f"%{q}%"))
    if silent:
        qs = qs.filter(Patient.last_contact_at < core.now() - timedelta(days=config.SILENT_DAYS))
    rows = qs.all()
    rows.sort(key=lambda p: (-rules.ORDER.get(p.zone or "green", 0), p.last_contact_at or core.now()))
    return [brief(p) for p in rows[:limit]]


@router.post("/confirm")
def confirm(body: ConfirmIn, db=Depends(db_session), r: str = Depends(role)):
    """Save a card the nurse has checked. Finds the patient by name and birth year or creates a new one."""
    f = body.fields
    p = db.get(Patient, body.patient_id) if body.patient_id else None
    if not p:
        qs = db.query(Patient).filter(Patient.full_name.ilike(f.full_name.strip()))
        if f.birth_year:
            qs = qs.filter(Patient.birth_year == f.birth_year)
        p = qs.first()
    created = p is None
    if created:
        p = Patient(full_name=f.full_name.strip(), kind=f.kind or "boshqa", zone="green", created_at=core.now(), last_contact_at=core.now())
        db.add(p)
        db.flush()
    for k in ("birth_year", "weeks", "mahalla", "phone", "diagnosis", "kind", "doctor"):
        if getattr(f, k) not in (None, ""):
            setattr(p, k, getattr(f, k))
    if body.consent and not p.consent_at:
        p.consent_at = core.now()
    data = f.values()
    data["complaints"] = [c for c in f.complaints if c in rules.COMPLAINTS]
    zone, reasons = core.add_observation(db, p, "ovoz", data, body.quotes, body.transcript, body.author)
    if f.referral:
        core.notify(db, p, "shifokor", "info", f"{p.full_name}: yo'llanma — {f.referral}", f"{p.full_name}: направление — {f.referral}")
    core.audit(db, r, "card_created" if created else "card_updated", p, f"zona {zone}; ovozli kiritish")
    db.commit()
    return {"id": p.id, "created": created, "zone": zone, "reasons": reasons, "referral": f.referral, "consent": bool(p.consent_at)}


@router.get("/{pid}")
def patient_card(pid: int, db=Depends(db_session)):
    p = get_patient(db, pid)
    data, prev, _ = core.merged(p)
    age = (core.now().year - p.birth_year) if p.birth_year and p.kind != "chaqaloq" else None
    mother = db.get(Patient, p.mother_id) if p.mother_id else None
    kids = db.query(Patient).filter(Patient.mother_id == p.id).all()
    return {
        **brief(p),
        "reasons": p.reasons or [],
        "diagnosis": p.diagnosis,
        "discharged_at": iso(p.discharged_at),
        "values": data,
        "prev": prev,
        "summary": {"uz": core.summary(p, "uz"), "ru": core.summary(p, "ru")},
        "ml": ml.predict(age, data) if p.kind != "chaqaloq" else None,
        "mother": brief(mother) if mother else None,
        "children": [brief(k) for k in kids],
        "observations": [
            {"id": o.id, "source": o.source, "data": o.data, "quotes": o.quotes, "text": o.text, "author": o.author, "at": iso(o.created_at)}
            for o in sorted(p.observations, key=lambda o: o.created_at, reverse=True)[:30]
        ],
        "tasks": [task_json(t) for t in sorted(p.tasks, key=lambda t: t.created_at, reverse=True)],
        "calls": [call_json(c) for c in sorted(p.calls, key=lambda c: c.planned_at, reverse=True)],
        "audit": [
            {"at": iso(a.at), "role": a.role, "action": a.action, "detail": a.detail}
            for a in db.query(AuditLog).filter(AuditLog.patient_id == p.id).order_by(AuditLog.id.desc()).limit(12)
        ],
    }


@router.post("/{pid}/observations")
def add_result(pid: int, body: ObservationIn, db=Depends(db_session), r: str = Depends(role)):
    p = get_patient(db, pid)
    data = body.values()
    if body.complaints is not None:
        data["complaints"] = [c for c in body.complaints if c in rules.COMPLAINTS]
    if not data:
        raise HTTPException(400, "empty")
    old = p.zone
    zone, reasons = core.add_observation(db, p, body.source, data, {}, body.text, body.author, contact=body.source != "tahlil")
    core.audit(db, r, "result_added", p, f"{body.source}: zona {old} -> {zone}")
    db.commit()
    return {"zone": zone, "old": old, "reasons": reasons}


@router.post("/{pid}/discharge")
def discharge(pid: int, body: NoteIn = NoteIn(), db=Depends(db_session), r: str = Depends(role)):
    p = get_patient(db, pid)
    t = core.discharge(db, p, body.note)
    for k in db.query(Patient).filter(Patient.mother_id == p.id).all():  # the newborn goes home too
        core.discharge(db, k)
    core.audit(db, r, "discharged", p, "Faol chaqiruv ochildi")
    db.commit()
    return task_json(t)


@router.post("/{pid}/consent")
def consent(pid: int, db=Depends(db_session), r: str = Depends(role)):
    p = get_patient(db, pid)
    p.consent_at = p.consent_at or core.now()
    core.audit(db, r, "consent_recorded", p, "Ma'lumotlarni qayta ishlash va AI qo'ng'iroqlarga rozilik")
    db.commit()
    return {"consent": True}


@router.post("/{pid}/calls")
def new_call(pid: int, body: CallIn, db=Depends(db_session), r: str = Depends(role)):
    p = get_patient(db, pid)
    if body.scenario not in core.SCENARIOS:
        raise HTTPException(400, "scenario")
    if body.lang:
        p.lang = body.lang
    try:
        c = core.create_call(db, p, body.scenario)
    except core.ConsentRequired:
        raise HTTPException(409, "consent")
    core.audit(db, r, "call_created", p, body.scenario)
    db.commit()
    return call_json(c)


@router.get("/{pid}/referral.pdf")
def referral(pid: int, lang: str = "uz", to: str = "", db=Depends(db_session)):
    p = get_patient(db, pid)
    return Response(
        pdfgen.referral(p, lang, to[:120]), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="yollanma-{p.id}.pdf"'}
    )


@router.get("/{pid}/fhir")
def fhir_bundle(pid: int, db=Depends(db_session)):
    return fhir.bundle(get_patient(db, pid))
