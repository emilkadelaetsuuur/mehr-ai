"""Clinical context, eligibility and the isolated DMED test record."""

import calendar
from datetime import UTC, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint

from .db import Base, Call, DmedMessage, Hospitalization, Patient, now

LOCAL = timezone(timedelta(hours=5))
PRIVATE = {"hiv_followup", "sti_followup"}
IMMUNIZATION = {"vaccine_adult", "vaccine_child"}
TARGETED = PRIVATE | IMMUNIZATION | {"first_birth_care", "adult_followup", "respiratory_followup"}


class Profile(Base):
    __tablename__ = "mehr_patient_context"
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    birthday = Column(Date)
    first_birth = Column(Boolean, default=False)
    icd = Column(String(12), default="")
    private_consent = Column(Boolean, default=False)
    guardian_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"))
    guardian_consent = Column(Boolean, default=False)


class DemoCase(Base):
    __tablename__ = "mehr_demo_cases"
    key = Column(String(100), primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), unique=True, nullable=False)


def test_line(db, call):
    return call.scenario in (TARGETED | {"dispanser"}) or db.query(DemoCase).filter_by(patient_id=call.patient_id).first() is not None


class HospitalEvent(Base):
    __tablename__ = "mehr_hospital_events"
    event_id = Column(String(72), primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    episode = Column(String(64), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    when = Column(DateTime, nullable=False)
    hospital = Column(String(140), nullable=False)
    transport = Column(String(120), default="")
    reason = Column(String(240), default="")
    icd = Column(String(12), default="")
    doctor = Column(String(120), default="")
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="SET NULL"))
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("patient_id", "episode", "kind", "when"),)


class VaccinePlan(Base):
    __tablename__ = "mehr_vaccine_plans"
    plan_id = Column(String(64), primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(90), nullable=False)
    due = Column(Date, nullable=False)
    status = Column(String(16), nullable=False)
    recipient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"))
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="SET NULL"))


class TestRecord(Base):
    __tablename__ = "mehr_test_dmed_records"
    key = Column(String(155), primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(12), nullable=False)
    resource = Column(JSON, nullable=False)
    message_id = Column(Integer, ForeignKey("dmed_messages.id", ondelete="SET NULL"))
    updated = Column(DateTime, default=now)


def as_utc(moment):
    if moment.tzinfo is None:
        raise HTTPException(422, "timezone_required")
    return moment.astimezone(UTC).replace(tzinfo=None)


def iso(moment):
    return moment.isoformat(timespec="seconds") + "Z" if moment else None


def record(db, patient, direction, resource):
    key = f"{patient.id}/{resource['resourceType']}/{resource['id']}"
    item = db.get(TestRecord, key)
    if item is None:
        item = TestRecord(key=key, patient_id=patient.id, direction=direction, resource=resource)
        db.add(item)
    # Publish to the same journal the cabinet and the district administrator read.
    message = db.get(DmedMessage, item.message_id) if item.message_id else None
    if not message:
        message = DmedMessage(direction=direction, kind=resource["resourceType"], patient_id=patient.id, created_at=now())
        db.add(message)
        db.flush()
        item.message_id = message.id
    message.payload = resource
    message.summary = resource.get("description") or resource["resourceType"] + " · тестовая карта"
    message.status = "qabul" if direction == "in" else "yuborildi"
    message.sent_at = now() if direction == "out" else None
    item.direction, item.resource, item.updated = direction, resource, now()
    db.flush()
    return item


def subject(p):
    return {"reference": f"Patient/{p.id}"}


def add_months(day, months):
    y, m = divmod(day.year * 12 + day.month - 1 + months, 12)
    return day.replace(year=y, month=m + 1, day=min(day.day, calendar.monthrange(y, m + 1)[1]))


def private_topic(code):
    group = (code or "").strip().upper().split(".")[0]
    if group in {"Z21", "B20", "B21", "B22", "B23", "B24"}:
        return "hiv_followup"
    if len(group) == 3 and group[0] == "A" and group[1:].isdigit() and 50 <= int(group[1:]) <= 64:
        return "sti_followup"
    return None


def birthdate(p, profile):
    return (profile.birthday if profile else None) or (p.born_at.date() if p.born_at else None)


def pending_plan(db, p, scenario, call=None):
    q = db.query(VaccinePlan).filter_by(patient_id=p.id, status="scheduled")
    if call is not None:
        q = q.filter_by(call_id=call.id)
    else:
        q = q.filter(VaccinePlan.due <= datetime.now(LOCAL).date() + timedelta(days=7))
    for plan in q.order_by(VaccinePlan.due, VaccinePlan.plan_id):
        if (plan.recipient_id == p.id) == (scenario == "vaccine_adult"):
            return plan
    return None


def vaccine_recipient(db, p, profile, due=None):
    birthday = birthdate(p, profile)
    if not birthday or birthday > datetime.now(LOCAL).date() or not p.consent_at:
        return None
    if add_months(birthday, 216) <= (due or datetime.now(LOCAL).date()):
        return p
    if not profile or not profile.guardian_consent or not profile.guardian_id or profile.guardian_id == p.id:
        return None
    guardian = db.get(Patient, profile.guardian_id)
    return guardian if guardian and guardian.phone and guardian.consent_at else None


def fits(db, p, scenario):
    if scenario == "tashrif_tasdiq":
        return True
    if scenario in {"homilador", "chaqaloq_30kun", "chiqarishdan_keyin"}:
        return p.kind == {"homilador": "homilador", "chaqaloq_30kun": "chaqaloq", "chiqarishdan_keyin": "tuqqan"}[scenario]
    profile = db.get(Profile, p.id)
    if scenario in PRIVATE:
        return bool(profile and p.private_consent_at and profile.private_consent and private_topic(profile.icd) == scenario and p.kind != "chaqaloq")
    if scenario == "respiratory_followup":
        return bool(
            p.discharged_at and p.kind == "boshqa" and profile and (profile.icd or "").split(".")[0] in {"J12", "J13", "J14", "J15", "J16", "J17", "J18"}
        )
    if scenario == "first_birth_care":
        return p.kind == "tuqqan" and bool(profile and profile.first_birth)
    if scenario == "adult_followup":
        return bool(profile and p.kind == "boshqa" and p.discharged_at and not (profile.icd or p.icd10))
    if scenario in IMMUNIZATION:
        plan = pending_plan(db, p, scenario)
        recipient = vaccine_recipient(db, p, profile, plan.due) if plan else None
        return bool(recipient and recipient.id == plan.recipient_id)
    return False


def call_recipient(db, call):
    if call.scenario not in IMMUNIZATION:
        return call.patient
    plan = pending_plan(db, call.patient, call.scenario, call)
    recipient = vaccine_recipient(db, call.patient, db.get(Profile, call.patient_id), plan.due) if plan else None
    return recipient if recipient and recipient.id == plan.recipient_id else None


def recommended(db, p):
    profile = db.get(Profile, p.id)
    confidential = private_topic(profile.icd) if profile else None
    if confidential and fits(db, p, confidential):
        return confidential
    if fits(db, p, "respiratory_followup"):
        return "respiratory_followup"
    if p.kind == "homilador":
        return "homilador"
    if p.kind == "tuqqan":
        return "first_birth_care" if profile and profile.first_birth else "chiqarishdan_keyin"
    if p.kind == "chaqaloq":
        return "chaqaloq_30kun"
    if p.kind in {"child", "bola"}:
        return None
    if fits(db, p, "adult_followup"):
        return "adult_followup"
    from . import core, dmed

    for scenario, details in core.SCENARIOS.items():
        if details.get("icd") and dmed.in_icd(p.icd10, details["icd"]):
            return scenario
    return "chiqarish_umumiy"


def task_record(db, p, task):
    db.flush()
    return record(
        db,
        p,
        "out",
        {
            "resourceType": "Task",
            "id": f"mehr-{task.id}",
            "status": {"ochiq": "requested", "bajarildi": "completed", "tasdiqlandi": "completed", "nomuvofiq": "rejected"}.get(task.status, "requested"),
            "intent": "order",
            "for": subject(p),
            "owner": {"display": p.doctor or task.role},
            "description": task.reason,
            "restriction": {"period": {"end": iso(task.due_at)}},
        },
    )


def finish_record(db, call, questions):
    from . import core

    p = call.patient
    db.flush()
    items = []
    for q in questions:
        a = (call.answers or {}).get(q["id"])
        if not a:
            continue
        v = a.get("value")
        value = {"valueBoolean": v == "yes"} if v in ("yes", "no") else ({"valueDecimal": v} if isinstance(v, (int, float)) else {"valueString": "unknown"})
        items.append({"linkId": q["id"], "text": q[call.lang or "uz"], "answer": [value]})
    record(
        db,
        p,
        "out",
        {
            "resourceType": "QuestionnaireResponse",
            "id": f"mehr-{call.id}",
            "status": "completed",
            "subject": subject(p),
            "authored": iso(call.finished_at),
            "questionnaire": "urn:mehr-ai:questionnaire:" + call.scenario,
            "item": items,
        },
    )
    flags = set(call.flags or [])
    if call.scenario in TARGETED and flags & {"callback", "ahvol", "unclear"}:
        hours = 1 if "ahvol" in flags else 24
        task = core.open_task(db, p, "qayta_qongiroq", "shifokor", "Контроль после индивидуального опроса", hours)
        if hours == 1:
            task.due_at = min(task.due_at, now() + timedelta(hours=1))
            core.notify(db, p, "shifokor", "yellow", "Bemorning ahvoli yomonlashgan, tezroq bog‘laning.", "Пациент сообщил об ухудшении. Нужен звонок врача.")
        task_record(db, p, task)


def apply_event(db, p, body):
    from . import core

    occurred = as_utc(body.occurred_at)
    if occurred > now() + timedelta(minutes=5):
        raise HTTPException(422, "future_event")
    old = db.get(HospitalEvent, body.event_id)
    signature = (p.id, body.episode, body.kind, occurred, body.hospital, body.transport, body.reason, body.icd, body.doctor)
    if old:
        if (old.patient_id, old.episode, old.kind, old.when, old.hospital, old.transport, old.reason, old.icd, old.doctor) != signature:
            raise HTTPException(409, "event_id_conflict")
        return old
    prior = db.query(HospitalEvent).filter_by(patient_id=p.id, episode=body.episode).order_by(HospitalEvent.when.desc()).first()
    if prior and prior.kind == "discharge" and body.kind == "discharge":
        raise HTTPException(409, "episode_already_discharged")
    event = HospitalEvent(
        event_id=body.event_id,
        patient_id=p.id,
        episode=body.episode,
        kind=body.kind,
        when=occurred,
        hospital=body.hospital,
        transport=body.transport,
        reason=body.reason,
        icd=body.icd,
        doctor=body.doctor,
    )
    db.add(event)
    db.flush()
    stay = db.query(Hospitalization).filter_by(patient_id=p.id, external_id=body.episode).first()
    if not stay:
        stay = Hospitalization(patient_id=p.id, external_id=body.episode, admitted_at=occurred, hospital=body.hospital)
        db.add(stay)
        p.stays.append(stay)
    if body.kind != "discharge":
        stay.admitted_at = min(stay.admitted_at, occurred)
    if body.kind == "transport":
        stay.emergency = True
        stay.brought_by = body.transport
    if body.kind == "discharge":
        stay.discharged_at = occurred
    if not prior or occurred >= prior.when:
        stay.hospital = body.hospital
        if body.reason:
            stay.reason = stay.diagnosis = body.reason
        if body.icd:
            stay.icd10 = body.icd
    record(
        db,
        p,
        "in",
        {
            "resourceType": "Encounter",
            "id": body.event_id,
            "status": "finished" if body.kind == "discharge" else "in-progress",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER" if body.kind == "transport" else "IMP"},
            "subject": subject(p),
            "serviceProvider": {"display": body.hospital},
            "period": {"end" if body.kind == "discharge" else "start": iso(occurred)},
            "reasonCode": [{"text": body.reason or body.kind}],
            "identifier": [{"value": body.episode}],
        },
    )
    last = db.query(HospitalEvent).filter_by(patient_id=p.id).order_by(HospitalEvent.when.desc(), HospitalEvent.event_id.desc()).first()
    if last.event_id != event.event_id:
        return event
    if body.icd:
        profile = db.get(Profile, p.id) or Profile(patient_id=p.id)
        if private_topic(profile.icd) != private_topic(body.icd):
            profile.private_consent = False
        profile.icd = p.icd10 = body.icd
        db.add(profile)
        db.flush()
        if body.reason:
            p.diagnosis = body.reason
        record(
            db,
            p,
            "in",
            {
                "resourceType": "Condition",
                "id": "diagnosis-" + event.event_id,
                "subject": subject(p),
                "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed"}]},
                "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": body.icd}], "text": body.reason or body.icd},
            },
        )
    if body.kind != "discharge":
        if body.kind == "transport":
            core.notify(
                db, p, "shifokor", "info", f"{p.full_name}: {body.hospital}, {body.transport}.", f"{p.full_name}: доставка в {body.hospital}, {body.transport}."
            )
        for previous in db.query(HospitalEvent).filter(HospitalEvent.patient_id == p.id, HospitalEvent.call_id.isnot(None), HospitalEvent.when < occurred):
            c = db.get(Call, previous.call_id)
            if c and c.status == "rejalashtirilgan":
                c.status = "cancelled"
        return event
    p.discharged_at = occurred
    deadline = occurred + timedelta(days=1)
    reason = "Контроль после выписки" if private_topic(body.icd) else body.hospital + " · " + (body.reason or "Выписка")
    task = core.open_task(db, p, "faol_chaqiruv", "shifokor", reason, 24)
    task.due_at = deadline
    db.flush()
    event.task_id = task.id
    task_record(db, p, task)
    scenario = recommended(db, p)
    if p.consent_at and scenario:
        c = core.create_call(db, p, scenario, planned_at=max(deadline, now()))
        db.flush()
        event.call_id = c.id
    return event


def schedule_vaccine(db, p, plan):
    from . import core

    profile = db.get(Profile, p.id)
    recipient = vaccine_recipient(db, p, profile, plan.due)
    previous = db.get(Call, plan.call_id) if plan.call_id else None
    if previous and (plan.status != "scheduled" or not recipient or plan.recipient_id != recipient.id):
        if previous.status in core.UNFINISHED:
            previous.status = "cancelled"
        plan.call_id = None
        previous = None
    plan.recipient_id = recipient.id if recipient else None
    if plan.status != "scheduled" or not recipient:
        return
    when = datetime.combine(plan.due - timedelta(days=3), time(10), LOCAL).astimezone(UTC).replace(tzinfo=None)
    if previous and previous.status == "cancelled":
        plan.call_id = None
        previous = None
    if previous:
        if previous.status == "rejalashtirilgan":
            previous.planned_at = max(when, now())
        return
    scenario = "vaccine_adult" if recipient.id == p.id else "vaccine_child"
    db.flush()
    c = core.create_call(db, p, scenario, planned_at=max(when, now()), vaccine_plan=plan)
    db.flush()
    plan.call_id = c.id
