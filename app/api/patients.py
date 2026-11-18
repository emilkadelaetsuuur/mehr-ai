"""Registry: list, patient card, confirmed voice card, results, discharge, consent, exports."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import selectinload

from .. import config, core, dmed, fhir, ml, pdfgen, rules, vaccines
from ..db import AuditLog, DmedMessage, Hospitalization, Patient
from ..schemas import CallIn, ConfirmIn, NoteIn, ObservationIn
from .deps import brief, call_json, current_user, db_session, get_patient, iso, masked, sees_all, snapshot, task_json

router = APIRouter(prefix="/api/patients")


@router.get("")
def list_patients(
    zone: str = "",
    q: str = "",
    kind: str = "",
    silent: int = 0,
    group: str = "",
    vax: int = 0,
    hospital: int = 0,
    limit: int = 400,
    db=Depends(db_session),
    u=Depends(current_user),
):
    """The register. `group`: a dispensary group, or "any" for everyone under dispensary follow-up;
    `vax`: children whose vaccination is due or overdue; `hospital`: those in a hospital now."""

    def build():
        qs = db.query(Patient).options(selectinload(Patient.vaccinations))
        if zone:
            qs = qs.filter(Patient.zone == zone)
        if kind:
            qs = qs.filter(Patient.kind == kind)
        if q:
            qs = qs.filter(Patient.full_name.ilike(f"%{q}%"))
        if silent:
            qs = qs.filter(Patient.kind.in_(core.WATCHED), Patient.last_contact_at < core.now() - timedelta(days=config.SILENT_DAYS))
        rows = qs.all()
        inside = {pid for (pid,) in db.query(Hospitalization.patient_id).filter(Hospitalization.discharged_at.is_(None))}
        behind = {p.id: vaccines.owed(p, core.now()) for p in rows if p.kind in vaccines.CHILD}
        if group == "any":
            rows = [p for p in rows if p.groups]
        elif group:  # a confidential group is a filter only for those who may see it
            rows = [p for p in rows if group in (p.groups or []) and (not core.GROUPS.get(group, {}).get("secret") or sees_all(u, p))]
        if vax:
            rows = [p for p in rows if behind.get(p.id)]
        if hospital:
            rows = [p for p in rows if p.id in inside]
        rows.sort(key=lambda p: (-rules.ORDER.get(p.zone or "green", 0), p.last_contact_at or core.now()))
        return [
            {**brief(p, u), "in_hospital": p.id in inside, "vax": ("overdue" if behind[p.id]["overdue"] else "due") if behind.get(p.id) else None}
            for p in rows[:limit]
        ]

    return snapshot(("patients", zone, q, kind, silent, group, vax, hospital, limit, u.role, u.doctor_name), build)


@router.post("/confirm")
def confirm(body: ConfirmIn, db=Depends(db_session), u=Depends(current_user)):
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
    for k in ("birth_year", "weeks", "mahalla", "phone", "diagnosis", "kind", "doctor", "pinfl", "parity"):
        if getattr(f, k) not in (None, ""):
            setattr(p, k, getattr(f, k))
    if body.consent and not p.consent_at:
        p.consent_at = core.now()
    data = f.values()
    data["complaints"] = [c for c in f.complaints if c in rules.COMPLAINTS]
    zone, reasons = core.add_observation(db, p, "ovoz", data, body.quotes, body.transcript, body.author)
    if f.referral:
        core.notify(db, p, "shifokor", "info", f"{p.full_name}: yo'llanma — {f.referral}", f"{p.full_name}: направление — {f.referral}")
    core.audit(db, u, "card_created" if created else "card_updated", p, f"zona {zone}; ovozli kiritish")
    db.commit()
    return {"id": p.id, "created": created, "zone": zone, "reasons": reasons, "referral": f.referral, "consent": bool(p.consent_at)}


@router.get("/{pid}")
def patient_card(pid: int, db=Depends(db_session), u=Depends(current_user)):
    """The patient's card, as this viewer may see it. Built once for all who look at it within a few seconds."""

    def build():
        p = get_patient(db, pid)
        hide = masked(p, u)  # a confidential diagnosis is for the specialist, the head and her own doctor only
        ages = vaccines.AGES
        data, prev, _ = core.merged(p)
        age = (core.now().year - p.birth_year) if p.birth_year and p.kind != "chaqaloq" else None
        mother = db.get(Patient, p.mother_id) if p.mother_id else None
        kids = db.query(Patient).filter(Patient.mother_id == p.id).all()
        return {
            **brief(p, u),
            "reasons": p.reasons or [],
            "diagnosis": None if hide else p.diagnosis,
            "icd10": None if hide else p.icd10,
            "pinfl": p.pinfl,
            "private_consent_at": iso(p.private_consent_at),
            "may_record_private": sees_all(u, p),
            "parity": p.parity,
            "scenarios": [s for s in core.SCENARIOS if s != "tashrif_tasdiq" and core.fits(p, s)],  # the calls that may be made to this patient
            "stays": [
                {
                    "id": s.id,
                    "hospital": s.hospital,
                    "emergency": s.emergency,
                    "brought_by": s.brought_by,
                    "reason": None if hide else s.reason,
                    "icd10": None if hide else s.icd10,
                    "diagnosis": None if hide else s.diagnosis,
                    "advice": None if hide else s.advice,
                    "admitted_at": iso(s.admitted_at),
                    "discharged_at": iso(s.discharged_at),
                }
                for s in sorted(p.stays, key=lambda s: s.admitted_at or s.created_at, reverse=True)
            ],
            "vaccines": [
                {**d, "due_at": iso(d["due_at"]), "done_at": iso(d["done_at"]), "label": ages[d["age"]]["label"]} for d in vaccines.plan(p, core.now())
            ],
            "dmed": [
                {"direction": m.direction, "kind": m.kind, "summary": m.summary, "status": m.status, "at": iso(m.created_at)}
                for m in db.query(DmedMessage).filter(DmedMessage.patient_id == p.id).order_by(DmedMessage.id.desc()).limit(12)
            ],
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
                {"at": iso(a.at), "role": a.role, "actor": a.actor, "action": a.action, "detail": a.detail}
                for a in db.query(AuditLog).filter(AuditLog.patient_id == p.id).order_by(AuditLog.id.desc()).limit(12)
            ],
        }

    return snapshot(("card", pid, u.role, u.doctor_name), build)


@router.post("/{pid}/observations")
def add_result(pid: int, body: ObservationIn, db=Depends(db_session), u=Depends(current_user)):
    p = get_patient(db, pid)
    data = body.values()
    if body.complaints is not None:
        data["complaints"] = [c for c in body.complaints if c in rules.COMPLAINTS]
    if not data:
        raise HTTPException(400, "empty")
    old = p.zone
    zone, reasons = core.add_observation(db, p, body.source, data, {}, body.text, body.author, contact=body.source != "tahlil")
    core.audit(db, u, "result_added", p, f"{body.source}: zona {old} -> {zone}")
    db.commit()
    return {"zone": zone, "old": old, "reasons": reasons}


@router.post("/{pid}/discharge")
def discharge(pid: int, body: NoteIn = NoteIn(), db=Depends(db_session), u=Depends(current_user)):
    p = get_patient(db, pid)
    t = core.discharge(db, p, body.note)
    for k in db.query(Patient).filter(Patient.mother_id == p.id).all():  # the newborn goes home too
        core.discharge(db, k)
    core.audit(db, u, "discharged", p, "Faol chaqiruv ochildi")
    db.commit()
    return task_json(t)


@router.post("/{pid}/consent")
def consent(pid: int, db=Depends(db_session), u=Depends(current_user)):
    p = get_patient(db, pid)
    p.consent_at = p.consent_at or core.now()
    core.audit(db, u, "consent_recorded", p, "Ma'lumotlarni qayta ishlash va AI qo'ng'iroqlarga rozilik")
    db.commit()
    return {"consent": True}


@router.post("/{pid}/consent/private")
def private_consent(pid: int, db=Depends(db_session), u=Depends(current_user)):
    """The patient's own consent to be called about confidential dispensary follow-up. It is recorded by
    someone who may know the diagnosis: the specialist, the head, or the doctor the patient is attached to."""
    p = get_patient(db, pid)
    if not sees_all(u, p):
        raise HTTPException(403, "role")
    if not p.groups:
        raise HTTPException(400, "no dispensary group")
    p.consent_at = p.consent_at or core.now()
    p.private_consent_at = p.private_consent_at or core.now()
    what = "Dispanser nazorati bo'yicha AI qo'ng'iroqlarga va maxfiy ma'lumotni qayta ishlashga rozilik"
    core.audit(db, u, "private_consent_recorded", p, what)
    dmed.push(db, "Consent: maxfiy nazorat", p, dmed.consent(p, what, p.private_consent_at), "rozilik qayd etildi")
    db.commit()
    return {"private_consent": True, "at": iso(p.private_consent_at)}


@router.post("/{pid}/calls")
def new_call(pid: int, body: CallIn, db=Depends(db_session), u=Depends(current_user)):
    p = get_patient(db, pid)
    if body.scenario not in core.SCENARIOS:
        raise HTTPException(400, "scenario")
    if not core.fits(p, body.scenario):  # every scenario is for the people it was written for, and nobody else
        raise HTTPException(409, "scenario does not fit this patient")
    if body.lang:
        p.lang = body.lang
    try:
        c = core.create_call(db, p, body.scenario)
    except core.ConsentRequired:
        raise HTTPException(409, "consent")
    core.audit(db, u, "call_created", p, body.scenario)
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
