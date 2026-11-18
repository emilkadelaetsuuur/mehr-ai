"""Staff-only clinical timeline and bidirectional, isolated DMED simulation."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from .. import carepath as care
from .. import core
from ..db import Call, DmedMessage, Patient, User, now
from .deps import current_user, db_session, get_patient

router = APIRouter(prefix="/api/care")


class ContextIn(BaseModel):
    birthday: date | None = None
    first_birth: bool = False
    icd: str = Field("", pattern=r"^([A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?)?$")
    private_consent: bool = False
    guardian_id: int | None = Field(None, gt=0)
    guardian_consent: bool = False


class EventIn(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-zA-Z0-9.-]{1,58}$")
    episode: str = Field(min_length=1, max_length=64)
    kind: Literal["transport", "admission", "discharge"]
    occurred_at: datetime
    hospital: str = Field(min_length=1, max_length=140)
    transport: str = Field("", max_length=120)
    reason: str = Field("", max_length=240)
    doctor: str = Field("", max_length=120)
    icd: str = Field("", pattern=r"^([A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?)?$")


class VaccineIn(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[A-Za-z0-9.-]{1,60}$")
    name: str = Field(min_length=1, max_length=90)
    due: date | None = None
    age_months: int | None = Field(None, ge=0, le=1440)
    status: Literal["scheduled", "given", "deferred", "cancelled"] = "scheduled"


def authorized(db, p, u):
    if u.role in {"rahbar", "mutaxassis"}:
        return True
    return u.role == "shifokor" and bool(u.doctor_name and u.doctor_name == p.doctor)


def access(db, p, u, write=False):
    profile = db.get(care.Profile, p.id)
    history = (code for (code,) in db.query(care.HospitalEvent.icd).filter_by(patient_id=p.id))
    restricted = bool(profile and care.private_topic(profile.icd)) or any(care.private_topic(code) for code in history)
    if (write or restricted) and not authorized(db, p, u):
        raise HTTPException(403, "role")


def locked(db, pid):
    p = db.query(Patient).filter_by(id=pid).with_for_update().first()
    if not p:
        raise HTTPException(404, "patient")
    return p


def render(db, p, u):
    profile = db.get(care.Profile, p.id)
    events = db.query(care.HospitalEvent).filter_by(patient_id=p.id).order_by(care.HospitalEvent.when.desc()).all()
    plans = db.query(care.VaccinePlan).filter_by(patient_id=p.id).order_by(care.VaccinePlan.due).all()
    known = {e.episode for e in events}
    for stay in p.stays:
        if stay.external_id in known:
            continue
        for kind, stamp in (("admission", stay.admitted_at), ("discharge", stay.discharged_at)):
            if not stamp:
                continue
            following = (
                next((c.id for c in p.calls if (c.context or {}).get("hospital") == stay.hospital and c.planned_at >= stamp), None)
                if kind == "discharge"
                else None
            )
            events.append(
                SimpleNamespace(
                    event_id=f"stay-{stay.id}-{kind}",
                    episode=stay.external_id or str(stay.id),
                    kind=kind,
                    when=stamp,
                    hospital=stay.hospital,
                    transport=stay.brought_by,
                    reason=(stay.diagnosis if kind == "discharge" else stay.reason),
                    icd=stay.icd10 if kind == "discharge" else "",
                    doctor=p.doctor,
                    call_id=following,
                )
            )
    events.sort(key=lambda event: event.when, reverse=True)
    records = db.query(DmedMessage).filter_by(patient_id=p.id).order_by(DmedMessage.id.desc()).limit(40).all()

    def call_info(i):
        c = db.get(Call, i) if i else None
        return (
            {"at": care.iso(c.planned_at), "scenario": c.scenario, "title": core.SCENARIOS[c.scenario]["title"], "status": c.status, "url": "/call/" + c.token}
            if c
            else None
        )

    return {
        "calls": [call_info(c.id) for c in sorted(p.calls, key=lambda c: c.planned_at, reverse=True)[:20]],
        "mode": "test",
        "can_edit": authorized(db, p, u),
        "patient_id": p.id,
        "name": p.full_name,
        "is_example": db.query(care.DemoCase).filter_by(patient_id=p.id).first() is not None,
        "doctor": p.doctor,
        "kind": p.kind,
        "profile": {
            "birthday": care.birthdate(p, profile),
            "icd": profile.icd if profile else (p.icd10 or ""),
            "private_consent": bool(profile and profile.private_consent),
            "first_birth": bool(profile and profile.first_birth),
            "guardian_id": profile.guardian_id if profile else p.mother_id,
            "guardian_consent": bool(profile and profile.guardian_consent),
        },
        "eligible": [{"id": k, "title": v["title"]} for k, v in core.SCENARIOS.items() if p.consent_at and core.fits(p, k)],
        "events": [
            {
                "id": e.event_id,
                "episode": e.episode,
                "kind": e.kind,
                "when": care.iso(e.when),
                "hospital": e.hospital,
                "transport": e.transport,
                "reason": e.reason,
                "icd": e.icd,
                "doctor": e.doctor,
                "call": call_info(e.call_id),
            }
            for e in events
        ],
        "vaccines": [
            {
                "id": v.plan_id,
                "name": v.name,
                "due": v.due,
                "status": v.status,
                "recipient": db.get(Patient, v.recipient_id).full_name if v.recipient_id and db.get(Patient, v.recipient_id) else None,
                "call": call_info(v.call_id),
            }
            for v in plans
        ],
        "records": [
            {
                "type": row.payload.get("resourceType", row.kind),
                "id": row.payload.get("id", str(row.id)),
                "direction": row.direction,
                "at": care.iso(row.sent_at or row.created_at),
                "resource": row.payload,
                "status": row.status,
            }
            for row in records
        ],
    }


@router.get("/patients/{pid}")
def detail(pid: int, db=Depends(db_session), u=Depends(current_user)):
    from .deps import masked

    p = get_patient(db, pid)
    access(db, p, u)
    if masked(p, u):
        raise HTTPException(403, "role")
    return render(db, p, u)


@router.put("/patients/{pid}/context")
def context(pid: int, body: ContextIn, db=Depends(db_session), u=Depends(current_user)):
    p = locked(db, pid)
    access(db, p, u, True)
    if body.birthday and body.birthday > datetime.now(care.LOCAL).date():
        raise HTTPException(422, "birthday")
    if body.first_birth and p.kind != "tuqqan":
        raise HTTPException(422, "first_birth_after_delivery")
    if body.private_consent and (not p.consent_at or not care.private_topic(body.icd)):
        raise HTTPException(422, "confidential_consent")
    if body.guardian_consent and not body.guardian_id:
        raise HTTPException(422, "guardian")
    if body.guardian_id and (body.guardian_id == p.id or not db.get(Patient, body.guardian_id)):
        raise HTTPException(422, "guardian")
    row = db.get(care.Profile, p.id) or care.Profile(patient_id=p.id)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    if body.private_consent:
        p.private_consent_at = p.private_consent_at or core.now()
    elif care.private_topic(body.icd) or care.private_topic(p.icd10):
        p.private_consent_at = None
    p.icd10 = body.icd
    if body.birthday:
        p.birth_year = body.birthday.year
    if p.kind == "tuqqan" and body.first_birth:
        p.parity = 0
    if p.kind in {"bola", "chaqaloq"} and body.birthday:
        p.born_at = datetime.combine(body.birthday, datetime.min.time())
    db.add(row)
    db.flush()
    care.record(
        db,
        p,
        "in",
        {"resourceType": "Patient", "id": str(p.id), "name": [{"text": p.full_name}], **({"birthDate": body.birthday.isoformat()} if body.birthday else {})},
    )
    care.record(
        db,
        p,
        "in",
        {
            "resourceType": "Consent",
            "id": "contact-" + str(p.id),
            "status": "active" if p.consent_at else "inactive",
            "patient": care.subject(p),
            "scope": {"text": "contact preferences"},
            "category": [{"text": "health follow-up"}],
            "extension": [
                {"url": "urn:mehr-ai:private-contact", "valueBoolean": body.private_consent},
                {"url": "urn:mehr-ai:guardian-contact", "valueBoolean": body.guardian_consent},
            ],
        },
    )
    for c in p.calls:
        if c.scenario in care.PRIVATE and c.status in core.UNFINISHED and not care.fits(db, p, c.scenario):
            c.status = "cancelled"
    for plan in db.query(care.VaccinePlan).filter_by(patient_id=p.id, status="scheduled"):
        care.schedule_vaccine(db, p, plan)
    core.audit(db, u, "care_context", p, "test DMED: clinical context updated")
    db.commit()
    return render(db, p, u)


@router.post("/patients/{pid}/events")
def event(pid: int, body: EventIn, db=Depends(db_session), u=Depends(current_user)):
    p = locked(db, pid)
    access(db, p, u, True)
    try:
        existed = db.get(care.HospitalEvent, body.event_id)
        care.apply_event(db, p, body)
        if not existed:
            core.audit(db, u, "hospital_event", p, body.kind + " · " + body.hospital)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "duplicate_event")
    return render(db, p, u)


@router.put("/patients/{pid}/vaccination")
def vaccine(pid: int, body: VaccineIn, db=Depends(db_session), u=Depends(current_user)):
    p = locked(db, pid)
    access(db, p, u, True)
    birthday = care.birthdate(p, db.get(care.Profile, p.id))
    if (body.due is None) == (body.age_months is None):
        raise HTTPException(422, "choose_date_or_age")
    if body.age_months is not None and not birthday:
        raise HTTPException(422, "birthday_required")
    due = body.due or care.add_months(birthday, body.age_months)
    if birthday and due < birthday:
        raise HTTPException(422, "before_birth")
    plan = db.get(care.VaccinePlan, body.plan_id)
    if plan and plan.patient_id != p.id:
        raise HTTPException(409, "plan_id_conflict")
    if not plan:
        plan = care.VaccinePlan(plan_id=body.plan_id, patient_id=p.id)
    plan.name, plan.due, plan.status = body.name, due, body.status
    db.add(plan)
    db.flush()
    care.schedule_vaccine(db, p, plan)
    record_vaccine(db, p, plan)
    core.audit(db, u, "vaccine_plan", p, plan.status)
    db.commit()
    return render(db, p, u)


def record_vaccine(db, p, plan):
    code = {"scheduled": "due", "given": "complete", "deferred": "deferred", "cancelled": "cancelled"}[plan.status]
    resource = {
        "resourceType": "ImmunizationRecommendation",
        "id": plan.plan_id,
        "patient": care.subject(p),
        "date": care.iso(now()),
        "recommendation": [
            {
                "vaccineCode": [{"text": plan.name}],
                "forecastStatus": {"text": code},
                "dateCriterion": [{"code": {"text": "recommended date"}, "value": plan.due.isoformat()}],
            }
        ],
    }
    return care.record(db, p, "in", resource)


EXAMPLES = {
    "respiratory_followup": ("Учебный пациент · Каримов Азиз", "boshqa", "J18.9"),
    "adult_followup": ("Учебный пациент · Алиев Рустам", "boshqa", ""),
    "first_birth_care": ("Учебная пациентка · Нурова Севара", "tuqqan", "Z39.2"),
    "homilador": ("Учебная пациентка · Усманова Лейла", "homilador", "Z34.0"),
    "hiv_followup": ("Учебный пациент · Мирзаев Камол", "boshqa", "Z21"),
    "sti_followup": ("Учебная пациентка · Алиева Зара", "boshqa", "A56.0"),
    "vaccine_child": ("Учебный ребёнок · Азимова Самира", "bola", ""),
    "vaccine_adult": ("Учебный пациент · Рахимов Умар", "boshqa", ""),
}


def make_example(db, scenario, u, lang):
    if scenario not in EXAMPLES:
        raise HTTPException(404, "example")
    if u.role not in {"rahbar", "mutaxassis", "shifokor"}:
        raise HTTPException(403, "role")
    # One fictional chart per example and per account. Concurrent clicks serialize on this row.
    db.query(User).filter_by(id=u.id).with_for_update().one()
    key = f"{u.id}/{scenario}"
    existing = db.get(care.DemoCase, key)
    if existing:
        return db.get(Patient, existing.patient_id)
    name, kind, icd = EXAMPLES[scenario]
    assigned = u.doctor_name or next((v[0] for v in db.query(User.doctor_name).filter_by(role="shifokor") if v[0]), "Учебный врач")

    def patient(label, kind, key):
        row = Patient(full_name=label, kind=kind, doctor=assigned, lang=lang or "ru", phone="TEST", mahalla="Учебный район", zone="green", consent_at=now())
        db.add(row)
        db.flush()
        db.add(care.DemoCase(key=key, patient_id=row.id))
        db.flush()
        return row

    p = patient(name, kind, key)
    today = datetime.now(care.LOCAL).date()
    profile = care.Profile(
        patient_id=p.id, birthday=care.add_months(today, -360), icd=icd, first_birth=scenario == "first_birth_care", private_consent=scenario in care.PRIVATE
    )
    if scenario in care.PRIVATE:
        p.private_consent_at = core.now()
    if scenario == "homilador":
        p.weeks = 24
    if scenario == "vaccine_child":
        guardian = patient("Учебный представитель · Азимова Нодира", "boshqa", key + "/guardian")
        profile.birthday = care.add_months(today + timedelta(days=2), -12)
        profile.guardian_id = guardian.id
        profile.guardian_consent = True
    p.birth_year = profile.birthday.year
    p.born_at = datetime.combine(profile.birthday, datetime.min.time()) if kind == "bola" else p.born_at
    p.parity = 0 if scenario in {"homilador", "first_birth_care"} else None
    p.icd10 = icd
    if scenario == "vaccine_child":
        p.mother_id = profile.guardian_id
    db.add(profile)
    db.flush()
    short = hashlib.sha256(key.encode()).hexdigest()[:12]
    if scenario in care.IMMUNIZATION:
        plan = care.VaccinePlan(
            plan_id="demo-" + short,
            patient_id=p.id,
            status="scheduled",
            name="КПК · учебное назначение" if scenario == "vaccine_child" else "Грипп · учебное назначение",
            due=care.add_months(profile.birthday, 12) if scenario == "vaccine_child" else today + timedelta(days=2),
        )
        db.add(plan)
        db.flush()
        care.schedule_vaccine(db, p, plan)
        record_vaccine(db, p, plan)
    elif scenario in {"respiratory_followup", "adult_followup", "first_birth_care"}:
        at = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1, minutes=5)
        reason = {
            "respiratory_followup": "Пневмония, период восстановления",
            "adult_followup": "Наблюдение на дому",
            "first_birth_care": "Послеродовой осмотр",
        }[scenario]
        for kind, offset in [("transport", 48), ("admission", 47), ("discharge", 0)]:
            body = EventIn(
                event_id=f"demo-{short}-{kind}",
                episode="demo-" + short,
                kind=kind,
                occurred_at=at - timedelta(hours=offset),
                hospital="Городская больница · учебная",
                transport="Бригада 04 · учебная" if kind == "transport" else "",
                reason=reason,
                icd=icd,
                doctor="Дежурный врач" if kind != "discharge" else assigned,
            )
            care.apply_event(db, p, body)
    else:
        core.create_call(db, p, scenario)
    return p


def example_call(db, scenario, u, lang):
    p = make_example(db, scenario, u, lang)
    db.flush()
    matches = [c for c in p.calls if c.scenario == scenario and c.status in core.UNFINISHED]
    if matches:
        call = matches[-1]
    elif scenario in care.IMMUNIZATION:
        return None
    else:
        call = core.create_call(db, p, scenario)
    call.lang = lang or p.lang or "ru"
    return call


@router.post("/examples/{scenario}")
def example(scenario: str, lang: Literal["ru", "uz"] = "ru", db=Depends(db_session), u=Depends(current_user)):
    p = make_example(db, scenario, u, lang)
    db.commit()
    return render(db, p, u)
