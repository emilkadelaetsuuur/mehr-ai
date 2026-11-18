"""Business logic: zones, tasks with a 24-hour timer, calls, visit verification."""

import json
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload, object_session, selectinload

from . import carepath, config, dialogue, dmed, extract, rules, telegram, vaccines
from .db import AuditLog, Call, Hospitalization, Notice, Observation, Patient, RiskEvent, SessionLocal, Task
from .schemas import Vitals

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "groups.json"), encoding="utf-8") as fh:
    GROUPS = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}  # dispensary groups; some are confidential
SCENARIOS = {}
for _f in sorted(os.listdir(os.path.join(HERE, "scenarios"))):
    if _f.endswith(".json"):
        with open(os.path.join(HERE, "scenarios", _f), encoding="utf-8") as fh:
            _s = json.load(fh)
            SCENARIOS[_s["id"]] = _s

NUM = ["bp_sys", "bp_dia", "hb", "glucose", "temp", "pulse", "breath"]
WATCHED = ("homilador", "tuqqan", "chaqaloq")  # under close watch: a week without contact is itself a warning
ZONE_UZ = {"red": "QIZIL", "yellow": "SARIQ", "green": "YASHIL"}
ZONE_RU = {"red": "КРАСНАЯ", "yellow": "ЖЁЛТАЯ", "green": "ЗЕЛЁНАЯ"}
TASK_UZ = {
    "faol_chaqiruv": "Faol chaqiruv",
    "mutaxassis": "Mutaxassis ko'rigi",
    "hamshira_tashrif": "Hamshira tashrifi",
    "murojaat": "Bemor murojaati",
    "qayta_qongiroq": "Qayta qo'ng'iroq",
    "emlash": "Emlashga chaqirish",
}
TASK_RU = {
    "faol_chaqiruv": "Активный вызов",
    "mutaxassis": "Осмотр специалиста",
    "hamshira_tashrif": "Визит медсестры",
    "murojaat": "Обращение пациента",
    "qayta_qongiroq": "Перезвонить пациенту",
    "emlash": "Пригласить на прививку",
}


def now():
    return datetime.utcnow()


def merged(patient):
    """Latest value per field, the previous values, and where each value was said."""
    data, prev, quotes = {}, {}, {}
    fresh = now() - timedelta(days=rules.T.get("valid_days", 45))  # older measurements no longer drive the zone
    obs = sorted(patient.observations, key=lambda o: (o.created_at, o.id or 0))
    for o in obs:
        d = o.data or {}
        for k in NUM:
            if d.get(k) is not None and o.created_at >= fresh:
                if k in data:
                    prev[k] = data[k]
                data[k] = d[k]
                q = (o.quotes or {}).get("bp" if k.startswith("bp_") else k)
                if q:
                    quotes["bp" if k.startswith("bp_") else k] = q
        if "complaints" in d:  # the most recent statement about complaints wins
            data["complaints"] = d.get("complaints") or []
            quotes["complaints"] = (o.quotes or {}).get("complaints") or {}
        if "extra_flags" in d:
            data["extra_flags"] = d.get("extra_flags") or []
    return data, prev, quotes


def notify(db, patient, role, level, uz, ru):
    """In-app notice for a role; urgent ones are also pushed to the bound Telegram chats."""
    db.add(Notice(patient_id=patient.id if patient else None, role=role, level=level, text_uz=uz[:400], text_ru=ru[:400]))
    if level in ("red", "yellow") and telegram.enabled() and not (patient and db.query(carepath.DemoCase).filter_by(patient_id=patient.id).first()):
        chats = set(telegram.recipients(db, role, level)) | ({config.TELEGRAM_CHAT_ID} if config.TELEGRAM_CHAT_ID else set())
        for chat in chats:
            telegram.send(chat, ("🔴 " if level == "red" else "🟡 ") + uz)


def open_task(db, patient, type_, role, reason, hours):
    for t in patient.tasks:
        if t.type == type_ and t.status == "ochiq":
            return t
    t = Task(patient_id=patient.id, type=type_, role=role, reason=reason[:240], due_at=now() + timedelta(hours=hours), created_at=now())
    db.add(t)
    patient.tasks.append(t)
    dmed.push(db, "Task: vazifa", patient, dmed.task(t, patient, TASK_UZ.get(type_, type_)), f"{TASK_UZ.get(type_, type_)} -> {role}")
    return t


def recompute(db, patient):
    """Re-evaluate the zone from all data; on a change, log it, notify and open a task."""
    data, prev, quotes = merged(patient)
    silent = rules.days_between(patient.last_contact_at) if patient.kind in WATCHED else 0
    zone, reasons = rules.evaluate(patient.kind, data, quotes, prev, days_silent=silent)
    old = patient.zone or "green"
    if old == "red" and zone != "red" and any(t.type == "mutaxassis" and t.status == "ochiq" for t in patient.tasks):
        # a red zone never clears by itself: it stays until the specialist has seen the patient
        zone, reasons = "red", [rules._reason("hold", "red", "", "", "inson qarori")] + reasons
    patient.reasons = reasons
    if zone != old:
        patient.zone = zone
        db.add(RiskEvent(patient_id=patient.id, from_zone=old, to_zone=zone, reasons=reasons))
        why_uz = "; ".join(f"{r['uz']} {r['value']}".strip() for r in reasons[:3]) or "ko'rsatkichlar me'yorda"
        why_ru = "; ".join(f"{r['ru']} {r['value']}".strip() for r in reasons[:3]) or "показатели в норме"
        if rules.ORDER[zone] > rules.ORDER[old]:
            notify(
                db,
                patient,
                "mutaxassis" if zone == "red" else "hamshira",
                zone,
                f"{patient.full_name} ({patient.mahalla}): {ZONE_UZ[zone]} zona. Sabab: {why_uz}",
                f"{patient.full_name} ({patient.mahalla}): {ZONE_RU[zone]} зона. Причина: {why_ru}",
            )
            if zone == "red":
                open_task(db, patient, "mutaxassis", "mutaxassis", why_uz, config.ACTIVE_CALL_HOURS)
            else:
                open_task(db, patient, "hamshira_tashrif", "hamshira", why_uz, 72)
        else:
            notify(
                db,
                patient,
                "mutaxassis",
                "info",
                f"{patient.full_name}: zona {ZONE_UZ[old]} → {ZONE_UZ[zone]}",
                f"{patient.full_name}: зона {ZONE_RU[old]} → {ZONE_RU[zone]}",
            )
    return zone, reasons


def audit(db, who, action, patient=None, detail=""):
    """`who` is a User account, or a plain role name for actions without a login (the patient in a call)."""
    role, actor = (who.role, who.username) if hasattr(who, "username") else (str(who or "-"), None)
    db.add(AuditLog(role=role[:20], actor=actor, action=action, patient_id=patient.id if patient else None, detail=str(detail)[:400], at=now()))


class IneligibleScenario(ValueError):
    pass


class ConsentRequired(Exception):
    """AI calls are allowed only for patients who gave consent."""


def add_observation(db, patient, source, data, quotes=None, text="", author="", contact=True):
    o = Observation(patient_id=patient.id, source=source, data=data or {}, quotes=quotes or {}, text=text, author=author, created_at=now())
    db.add(o)
    patient.observations.append(o)
    if contact:
        patient.last_contact_at = now()
    measured = dmed.observations(patient, data or {}, o.created_at, author) if source in ("ovoz", "korik", "tahlil") else None
    if measured:  # what a nurse dictated or a laboratory sent is in DMED at once: nobody types it there again
        dmed.push(db, "Observation: o'lchovlar", patient, measured, f"{source}: {', '.join(k for k in NUM if (data or {}).get(k) is not None)}")
    return recompute(db, patient)


def allowed(patient, scenario):
    """True when the patient has agreed to this kind of call. Every AI call needs the general consent; a call
    about confidential dispensary follow-up needs a consent of its own, recorded separately."""
    return bool(patient.consent_at) and (not SCENARIOS[scenario].get("private") or bool(patient.private_consent_at))


def create_call(db, patient, scenario, task_id=None, planned_at=None, context=None, vaccine_plan=None):
    if not allowed(patient, scenario):
        raise ConsentRequired(patient.full_name)
    if scenario in carepath.IMMUNIZATION:
        plan = vaccine_plan or carepath.pending_plan(db, patient, scenario)
        recipient = carepath.vaccine_recipient(db, patient, db.get(carepath.Profile, patient.id), plan.due) if plan else None
        if (
            not plan
            or plan.status != "scheduled"
            or not recipient
            or plan.recipient_id != recipient.id
            or (scenario == "vaccine_child") != (recipient.id != patient.id)
        ):
            raise IneligibleScenario(scenario)
        if plan.call_id:
            existing = db.get(Call, plan.call_id)
            if existing and existing.status in UNFINISHED:
                return existing
            raise IneligibleScenario(scenario)
    elif not fits(patient, scenario):
        raise IneligibleScenario(scenario)
    if context is None:
        context = call_context(patient, scenario)
    c = Call(
        token=secrets.token_urlsafe(9),
        patient_id=patient.id,
        scenario=scenario,
        task_id=task_id,
        lang=patient.lang or "uz",
        planned_at=planned_at or now(),
        created_at=now(),
        answers={},
        flags=[],
        context=context or {},
    )
    db.add(c)
    patient.calls.append(c)
    if scenario in carepath.IMMUNIZATION:
        db.flush()
        plan.call_id = c.id
    return c


UNFINISHED = ("rejalashtirilgan", "jarayonda")
KINDS = ("homilador", "tuqqan", "chaqaloq", "bola", "boshqa")
# the prepared patient for a trial call, by whom the scenario is written for
TRIAL = {
    "homilador": "Sodiqova Dilnoza",
    "tuqqan": "Valiyeva Madina",
    "chaqaloq": "Valiyev Amir",
    "emlash": "Karimov Yusuf",
    "dispanser": "Toshmatov Sardor",
    "shifoxona": "Rahimov Botir",
    "any": "Valiyeva Madina",
}


def fits(patient, scenario):
    """True when a scenario is written for this patient. A call about a baby is never made to a patient
    under dispensary follow-up, nor a call about treatment to the mother of a healthy child: each scenario
    reaches only the people it was written for."""
    if scenario in carepath.TARGETED:
        return carepath.fits(object_session(patient), patient, scenario)
    who = SCENARIOS[scenario].get("who", "any")
    if who in KINDS:
        return patient.kind == who
    if who == "emlash":
        return patient.kind in vaccines.CHILD and bool(vaccines.owed(patient, now()))
    if who == "dispanser":
        return bool(patient.groups)
    if who == "shifoxona":  # after a hospital: only the questions written for the diagnosis she left with
        return patient.discharged_at is not None and after_hospital(patient, patient.icd10 or "") == scenario
    return True


def reachable(db, scenario, zone=""):
    """The patients a scenario is written for. Besides the kinds of patient, a scenario may be for children
    whose vaccination has come due ("emlash"), for everyone under dispensary follow-up ("dispanser"), or for
    those discharged from a hospital in the last month ("shifoxona")."""
    who = SCENARIOS[scenario].get("who", "any")
    q = db.query(Patient)
    if who in KINDS:
        q = q.filter(Patient.kind == who)
    elif who == "emlash":
        q = q.filter(Patient.kind.in_(vaccines.CHILD)).options(selectinload(Patient.vaccinations))
    elif who == "shifoxona":
        q = q.filter(Patient.discharged_at >= now() - timedelta(days=30))
    if zone:
        q = q.filter(Patient.zone == zone)
    rows = q.all()
    if who == "emlash":
        rows = [p for p in rows if vaccines.owed(p, now())]
    elif who == "dispanser":
        rows = [p for p in rows if p.groups]
    elif who == "shifoxona":
        rows = [p for p in rows if after_hospital(p, p.icd10 or "") == scenario]
    return rows


def call_context(patient, scenario):
    """What a call must know besides its scenario: which vaccinations are due, which hospital stay it follows."""
    who = SCENARIOS[scenario].get("who", "any")
    if who == "emlash":
        return vaccines.owed(patient, now())
    stay = max(patient.stays, key=lambda x: x.admitted_at or x.created_at, default=None) if who in ("shifoxona", "tuqqan") else None
    return {"hospital": stay.hospital, "icd10": stay.icd10, "diagnosis": stay.diagnosis} if stay and stay.discharged_at else {}


def audience(db, scenario, zone="", doctor=None):
    """Who a calling round with this scenario can reach. AI calls need consent, and a patient who already
    has an unfinished call of this scenario is not rung twice. The most worrying zone and the longest
    silence come first."""
    if scenario in carepath.TARGETED:
        who = SCENARIOS[scenario].get("who", "any")
        q = db.query(Patient)
        if scenario in carepath.PRIVATE:
            q = q.join(carepath.Profile, carepath.Profile.patient_id == Patient.id).filter(carepath.Profile.private_consent.is_(True))
        elif scenario in carepath.IMMUNIZATION:
            q = (
                q.join(carepath.VaccinePlan, carepath.VaccinePlan.patient_id == Patient.id)
                .filter(
                    carepath.VaccinePlan.status == "scheduled",
                    carepath.VaccinePlan.due <= datetime.now(carepath.LOCAL).date() + timedelta(days=7),
                    carepath.VaccinePlan.call_id.is_(None),
                )
                .distinct()
            )
        elif scenario == "first_birth_care":
            q = q.join(carepath.Profile, carepath.Profile.patient_id == Patient.id).filter(Patient.kind == "tuqqan", carepath.Profile.first_birth.is_(True))
        elif scenario in {"adult_followup", "respiratory_followup"}:
            q = q.filter(Patient.discharged_at.isnot(None), Patient.kind.notin_(("chaqaloq", "child")))
        elif who != "any":
            q = q.filter(Patient.kind == who)
        if doctor is not None:
            q = q.filter(Patient.doctor == doctor)
        if zone:
            q = q.filter(Patient.zone == zone)
        rows = [p for p in q.all() if carepath.fits(db, p, scenario)]
    else:
        rows = [p for p in reachable(db, scenario, zone) if (doctor is None or p.doctor == doctor) and fits(p, scenario)]

    busy = {pid for (pid,) in db.query(Call.patient_id).filter(Call.scenario == scenario, Call.status.in_(UNFINISHED))}
    fit = [p for p in rows if allowed(p, scenario) and p.id not in busy]
    fit.sort(key=lambda p: (-rules.ORDER.get(p.zone or "green", 0), p.last_contact_at or now()))
    return {
        "fit": fit,
        "no_consent": sum(1 for p in rows if not allowed(p, scenario)),
        "already": sum(1 for p in rows if allowed(p, scenario) and p.id in busy),
    }


def start_round(db, scenario, lang=None, zone="", limit=10, doctor=None):
    """A calling round: one call for each of the first `limit` patients the scenario can reach."""
    made = []
    for p in audience(db, scenario, zone, doctor)["fit"][:limit]:
        if lang:
            p.lang = lang
        made.append(create_call(db, p, scenario, context=call_context(p, scenario)))
    return made


def trial_call(db, scenario, lang=None):
    """One call to try a scenario on the prepared demonstration patient. An unfinished call of the same
    scenario is used again, so that trying it several times does not pile calls up."""
    who = SCENARIOS[scenario].get("who", "any")
    fit = audience(db, scenario)["fit"]
    p = db.query(Patient).filter(Patient.full_name == TRIAL.get(who, TRIAL["any"]), Patient.consent_at.isnot(None)).first()
    c = next((c for c in sorted(p.calls, key=lambda c: c.id, reverse=True) if c.scenario == scenario and c.status in UNFINISHED), None) if p else None
    if c and fits(p, scenario):
        c.lang = lang or p.lang or "uz"
        return c
    if p and not (fits(p, scenario) and allowed(p, scenario)):
        p = None  # the prepared patient is not one this scenario is for (any more), or has not agreed: somebody else will do
    p = p or (fit[0] if fit else None)
    if not p:
        return None
    if lang:
        p.lang = lang
    return create_call(db, p, scenario, context=call_context(p, scenario))


def after_hospital(patient, icd10=""):
    """Which questions the call after a discharge asks: the scenario written for the diagnosis DMED sent,
    else the one for a woman after childbirth or pregnancy, else the general one."""
    db = object_session(patient)
    profile = db.get(carepath.Profile, patient.id) if db else None
    if profile:
        targeted = carepath.recommended(db, patient)
        if targeted and targeted in carepath.TARGETED and carepath.fits(db, patient, targeted):
            return targeted
    if patient.kind == "chaqaloq":
        return "chaqaloq_30kun"
    for sc in SCENARIOS.values():
        if sc.get("icd") and dmed.in_icd(icd10, sc["icd"]):
            return sc["id"]
    return {"homilador": "homilador", "tuqqan": "chiqarishdan_keyin", "bola": None}.get(patient.kind, "chiqarish_umumiy")


def discharge(db, patient, note="", stay=None):
    """Discharge from a hospital -> 'Faol chaqiruv' for the family doctor + an AI call the next day, with the
    questions that fit the diagnosis. `stay` is the hospital stay DMED reported, when the news came from there."""
    patient.discharged_at = (stay.discharged_at if stay else None) or now()
    about = ": " + note if note else ""
    t = open_task(db, patient, "faol_chaqiruv", "shifokor", "Shifoxonadan chiqarildi" + (": " + note if note else ""), config.ACTIVE_CALL_HOURS)
    notify(
        db,
        patient,
        "shifokor",
        "yellow",
        f"FAOL CHAQIRUV: {patient.full_name} ({patient.mahalla}) shifoxonadan chiqarildi{about}. {config.ACTIVE_CALL_HOURS} soat ichida ko'rib, tasdiqlang.",
        f"АКТИВНЫЙ ВЫЗОВ: {patient.full_name} ({patient.mahalla}) выписана{about}. Осмотрите и подтвердите в течение {config.ACTIVE_CALL_HOURS} часов.",
    )
    scenario = after_hospital(patient, (stay.icd10 if stay else patient.icd10) or "")
    planned = any(c.scenario == scenario and c.status == "rejalashtirilgan" for c in patient.calls)
    if not scenario or not patient.consent_at or planned:  # no consent -> no calls; a repeated discharge does not double the schedule
        return t
    if patient.kind == "chaqaloq":
        base = patient.born_at or now()
        for d in SCENARIOS["chaqaloq_30kun"].get("schedule_days", []):
            when = base + timedelta(days=d)
            if when > now() - timedelta(days=1):
                create_call(db, patient, "chaqaloq_30kun", planned_at=when)
    else:
        context = {"hospital": stay.hospital, "icd10": stay.icd10, "diagnosis": stay.diagnosis} if stay else {}
        create_call(db, patient, scenario, planned_at=max(now(), patient.discharged_at + timedelta(days=1)), context=context)
    return t


def local(d):
    """A stored (UTC) time as people in Tashkent read it."""
    return (d + timedelta(hours=5)).strftime("%d.%m %H:%M") if d else "—"


def admitted(db, patient, stay):
    """DMED reported that the patient is in a hospital. The person she is attached to learns it at once:
    who, when, where, why and who brought her. Nobody has to phone the polyclinic."""
    role, _ = responsible(patient)
    head_uz, head_ru = ("SHOSHILINCH YOTQIZILDI", "ЭКСТРЕННАЯ ГОСПИТАЛИЗАЦИЯ") if stay.emergency else ("SHIFOXONAGA YOTQIZILDI", "ГОСПИТАЛИЗАЦИЯ")
    by_uz = f" Olib bordi: {stay.brought_by}." if stay.brought_by else ""
    by_ru = f" Доставил: {stay.brought_by}." if stay.brought_by else ""
    notify(
        db,
        patient,
        role,
        "red" if stay.emergency else "yellow",
        f"{head_uz}: {patient.full_name} ({patient.mahalla}), {local(stay.admitted_at)} — {stay.hospital}. Sabab: {stay.reason or '—'}.{by_uz}",
        f"{head_ru}: {patient.full_name} ({patient.mahalla}), {local(stay.admitted_at)} — {stay.hospital}. Причина: {stay.reason or '—'}.{by_ru}",
    )
    audit(db, "dmed", "hospital_admitted", patient, f"{stay.hospital}: {stay.reason or ''}")


def discharged(db, patient, stay):
    """DMED reported the discharge with the diagnosis. The diagnosis goes on the card as the hospital wrote
    it, a diagnosis of a dispensary group puts the patient in that group, the family doctor gets the active
    call, and an AI call with the questions for this diagnosis is planned for the next day."""
    if stay.icd10:
        patient.icd10 = stay.icd10
        added = [g for g, spec in GROUPS.items() if dmed.in_icd(stay.icd10, spec["icd"]) and g not in (patient.groups or [])]
        if added:
            patient.groups = (patient.groups or []) + added
    if stay.diagnosis:
        patient.diagnosis = f"{stay.diagnosis} ({stay.hospital})"[:240]
    secret = any(GROUPS[g]["secret"] for g in patient.groups or [] if g in GROUPS)
    # a confidential diagnosis is not put into a notice
    note = stay.hospital if secret else f"{stay.hospital}, {stay.diagnosis or stay.reason or 'tashxis ko`rsatilmagan'}"
    task = discharge(db, patient, note, stay)
    audit(db, "dmed", "hospital_discharged", patient, f"{stay.hospital}: {stay.icd10 or ''} -> {after_hospital(patient, stay.icd10)}")
    return task


def task_done(db, task, note=""):
    """Doctor marks the visit as done -> the patient is asked to confirm it (double confirmation)."""
    task.status, task.done_at, task.note = "bajarildi", now(), note
    p = task.patient
    p.last_contact_at = now()
    carepath.task_record(db, p, task)
    recompute(db, p)  # a closed specialist task releases the red-zone hold
    call = create_call(db, p, "tashrif_tasdiq", task_id=task.id) if p.consent_at else None
    notify(
        db,
        p,
        "rahbar",
        "info",
        f"{p.full_name}: «{TASK_UZ.get(task.type, task.type)}» bajarildi deb belgilandi, bemor tasdig'i kutilmoqda.",
        f"{p.full_name}: «{TASK_RU.get(task.type, task.type)}» отмечен выполненным, ждём подтверждения пациента.",
    )
    return call


def responsible(patient):
    """Who answers for this patient day to day: (role, name).

    A patient is attached to a family doctor, named on the card; that doctor's account sees the patient's
    tasks. A card without a doctor belongs to the patronage nurse. Warning signs are a separate road: the
    zone rules send them to the specialist whoever the patient is attached to, and anything left undone
    past its deadline goes to the head of the district.
    """
    return ("shifokor", patient.doctor) if patient.doctor else ("hamshira", "")


def appeal(db, call, text):
    """A message the patient left at the end of a call. It goes at once to the person the patient is
    attached to, as a task with a deadline, and is kept in the patient's history. If the words contain a
    warning sign, the zone rules treat it like any other report: red zone, specialist, urgent notice."""
    p = call.patient
    role, name = responsible(p)
    found = extract.signs(text, quick=True)  # she is waiting on the line: keywords now, the careful reading follows (appeal_review)
    urgent = any(c in rules.T["red_complaints"] for c in found)
    if found:  # the same road as a symptom reported in any other way
        add_observation(db, p, "murojaat", {"complaints": found}, {"complaints": dict.fromkeys(found, text[:200])}, text, "Bemor")
    else:
        o = Observation(patient_id=p.id, source="murojaat", data={}, quotes={}, text=text, author="Bemor", created_at=now())
        db.add(o)
        p.observations.append(o)
        p.last_contact_at = now()
    t = Task(
        patient_id=p.id, type="murojaat", role=role, reason=text[:240], due_at=now() + timedelta(hours=2 if urgent else config.APPEAL_HOURS), created_at=now()
    )
    db.add(t)
    p.tasks.append(t)
    dmed.push(db, "Task: bemor murojaati", p, dmed.task(t, p, TASK_UZ["murojaat"]), f"murojaat -> {role}")
    notify(
        db,
        p,
        role,
        "red" if urgent else "yellow",
        f"MUROJAAT: {p.full_name} ({p.mahalla}, {p.phone}): {text[:220]}",
        f"ОБРАЩЕНИЕ: {p.full_name} ({p.mahalla}, {p.phone}): {text[:220]}",
    )
    before = (call.answers or {}).get("murojaat") or {}  # a call may carry several messages: none of them is lost
    said = " | ".join(x for x in (before.get("transcript"), text) if x)
    signs = (before.get("complaints") or []) + [c for c in found if c not in (before.get("complaints") or [])]
    call.answers = {**(call.answers or {}), "murojaat": {"value": "yes", "transcript": said, "complaints": signs, "to": role}}
    audit(db, "bemor", "appeal_left", p, f"-> {role} {name}".strip())
    return {"role": role, "doctor": name, "urgent": urgent, "task": t}


def appeal_review(db, call, text):
    """The careful reading of a message, after the caller has been answered: the language model looks for
    warning signs the keyword lists missed. What it finds goes the same road as any reported symptom."""
    note = (call.answers or {}).get("murojaat") or {}
    known = note.get("complaints") or []
    more = [c for c in extract.signs(text) if c not in known]
    if not more:
        return []
    p = call.patient
    add_observation(db, p, "murojaat", {"complaints": known + more}, {"complaints": dict.fromkeys(known + more, text[:200])}, text, "Bemor")
    call.answers = {**(call.answers or {}), "murojaat": {**note, "complaints": known + more}}
    if any(c in rules.T["red_complaints"] for c in more):
        role, _ = responsible(p)
        notify(
            db,
            p,
            role,
            "red",
            f"MUROJAATDA XAVF BELGISI: {p.full_name} ({p.mahalla}, {p.phone}): {text[:200]}",
            f"ТРЕВОЖНЫЙ ПРИЗНАК В ОБРАЩЕНИИ: {p.full_name} ({p.mahalla}, {p.phone}): {text[:200]}",
        )
    return more


def review_later(call_id, text):
    """appeal_review in its own database session: it runs after the caller has been answered."""
    with SessionLocal() as db:
        call = db.get(Call, call_id)
        if call:
            appeal_review(db, call, text)
            db.commit()


def callback(db, call, said=""):
    """The caller asked for a person. A member of staff must ring back within the time the call promised:
    the patronage nurse, or the specialist when the patient is in the red zone. Overdue goes to the head.
    A caller who asked for a doctor by name ("мне нужен доктор") gets a doctor: the family doctor, or the
    specialist in the red zone, with an urgent notice."""
    p = call.patient
    doctor = extract.wants_doctor(said)
    if call.scenario in (carepath.PRIVATE | {"dispanser"}):
        role = "shifokor"
    elif p.zone == "red":
        role = "mutaxassis"
    else:
        role = "shifokor" if doctor else "hamshira"
    t = Task(
        patient_id=p.id,
        type="qayta_qongiroq",
        role=role,
        reason=(("Bemor shifokorni so'radi" if doctor else "Bemor xodim bilan gaplashishni so'radi") + (f": {said}" if said else ""))[:240],
        due_at=now() + timedelta(minutes=dialogue.CALLBACK_MINUTES),
        created_at=now(),
    )
    db.add(t)
    p.tasks.append(t)
    if doctor:
        notify(
            db,
            p,
            role,
            "red",
            f"BEMOR SHIFOKORNI SO'RADI: {p.full_name} ({p.phone}). {dialogue.CALLBACK_MINUTES} daqiqa ichida qo'ng'iroq qiling."
            + (f" Bemor aytdi: «{said[:160]}»" if said else ""),
            f"ПАЦИЕНТ ПРОСИТ ВРАЧА: {p.full_name} ({p.phone}). Позвоните в течение {dialogue.CALLBACK_MINUTES} минут."
            + (f" Слова пациента: «{said[:160]}»" if said else ""),
        )
    else:
        notify(
            db,
            p,
            role,
            "yellow",
            f"QAYTA QO'NG'IROQ: {p.full_name} ({p.phone}) xodim bilan gaplashishni so'radi. {dialogue.CALLBACK_MINUTES} daqiqa ichida qo'ng'iroq qiling.",
            f"ПЕРЕЗВОНИТЬ: {p.full_name} ({p.phone}) просит поговорить с сотрудником. Позвоните в течение {dialogue.CALLBACK_MINUTES} минут.",
        )
    call.answers = {**(call.answers or {}), "operator": {"value": "yes", "transcript": said, "doctor": doctor}}
    audit(db, "bemor", "doctor_asked" if doctor else "operator_asked", p, f"-> {role}")
    return t


def finish_call(db, call):
    """Turn call answers into data: complaints, flags, zone, visit verification."""
    sc = SCENARIOS[call.scenario]
    p = call.patient
    complaints, extra, quotes, data, lines, verified = [], [], {}, {}, [], None
    for q in sc["questions"]:
        a = (call.answers or {}).get(q["id"])
        if not a:
            continue
        lines.append(f"{q['uz']} — {a.get('transcript') or a.get('value')}")
        v = a.get("value")
        if q["type"] == "number":
            if isinstance(v, (int, float)):
                data[q["field"]] = v
                quotes[q["field"]] = a.get("transcript", "")
            continue
        if v == "unclear":
            extra.append("unclear")
            continue
        flagged = v == q["flag_if"]
        if q.get("verify"):
            verified = not flagged
        elif flagged and q.get("complaint"):
            complaints.append(q["complaint"])
            quotes.setdefault("complaints", {})[q["complaint"]] = a.get("transcript", "")
        elif flagged and q.get("extra"):
            extra.append(q["extra"])
    note = (call.answers or {}).get("murojaat") or {}
    for c in note.get("complaints") or []:  # signs named in the message she left count like answers
        if c in rules.COMPLAINTS and c not in complaints:
            complaints.append(c)
            quotes.setdefault("complaints", {})[c] = (note.get("transcript") or "")[:200]
    call.status, call.finished_at = "tugadi", now()
    call.flags = (
        complaints
        + extra
        + ([] if verified in (None, True) else ["tashrif_tasdiqlanmadi"])
        + (["murojaat"] if note else [])
        + (["operator"] if (call.answers or {}).get("operator") else [])
    )
    if call.scenario == "emlash":
        # A missed vaccination is shown by the calendar and gives the nurse her own task; it is not a sign of
        # illness, so it does not move the child's zone. A bad reaction is a complaint and does.
        vaccination_answers(db, call)
        extra = [x for x in extra if x == "unclear"]
    if call.scenario == "tashrif_tasdiq":
        t = db.get(Task, call.task_id) if call.task_id else None
        if t and verified is not None:
            t.status = "tasdiqlandi" if verified else "nomuvofiq"
            carepath.task_record(db, p, t)
            if not verified:
                notify(
                    db,
                    p,
                    "rahbar",
                    "red",
                    f"NOMUVOFIQLIK: {p.full_name} shifokor kelmaganini aytdi, vazifa esa bajarildi deb belgilangan.",
                    f"РАСХОЖДЕНИЕ: {p.full_name} сообщила, что врач не приходил, а задача отмечена выполненной.",
                )
        if "fikr" in extra:
            notify(
                db,
                p,
                "rahbar",
                "yellow",
                f"Bemor fikri: {p.full_name} — tushuntirishlar tushunarsiz bo'lgan.",
                f"Отзыв пациента: {p.full_name} — объяснения врача были непонятны.",
            )
        p.last_contact_at = now()
        zone, alert = p.zone, False  # the visit check has no symptoms: its outcome is `verified`
    else:
        data["complaints"] = sorted(set(complaints))
        data["extra_flags"] = sorted(set(extra))
        before = p.zone
        zone, _ = add_observation(db, p, "qongiroq", data, quotes, "\n".join(lines), "Mehr AI")
        # What the caller hears depends on this call's answers alone, not on the zone the patient was in before.
        own, found = rules.evaluate(p.kind, data)
        alert = bool(complaints) or own == "red"
        if alert and zone == before:
            # The zone did not move (she was in it already), so the zone change sent nobody a notice.
            # New warning signs must still reach the staff, and a red sign needs an open specialist task.
            uz = "; ".join(f"{r['uz']} {r['value']}".strip() for r in found[:3])
            ru = "; ".join(f"{r['ru']} {r['value']}".strip() for r in found[:3])
            notify(
                db,
                p,
                "mutaxassis" if own == "red" else "hamshira",
                "red" if own == "red" else "yellow",
                f"{p.full_name} ({p.mahalla}): AI qo'ng'iroqda yangi xavf belgilari — {uz}",
                f"{p.full_name} ({p.mahalla}): в ИИ-звонке новые тревожные признаки — {ru}",
            )
            if own == "red":
                open_task(db, p, "mutaxassis", "mutaxassis", uz, config.ACTIVE_CALL_HOURS)
    if call.scenario in carepath.TARGETED:
        carepath.finish_record(db, call, sc["questions"])
    # DMED has the call the moment it ends: the answers, and a flag on the record when they are alarming.
    if call.scenario not in carepath.TARGETED:
        dmed.push(db, "QuestionnaireResponse: qo'ng'iroq", p, dmed.answers(call, sc), f"{sc['title']['uz']}: {', '.join(call.flags) or 'belgi yo`q'}")
    if alert:
        signs = ", ".join(rules.COMPLAINTS[c][0] for c in complaints if c in rules.COMPLAINTS) or "xavf belgilari"
        dmed.push(db, "Flag: xavf belgisi", p, dmed.flag(p, f"AI qo'ng'iroqda xavf belgilari: {signs}", call.finished_at), signs)
    return {"zone": zone, "flags": call.flags, "alert": alert, "verified": verified}


def vaccination_answers(db, call):
    """What follows from a call about vaccinations that have come due. "Done" is written down as the
    parent's word and waits for the vaccination room's record; "not done" gives the patronage nurse a task
    to bring the child in, and a deferral for a medical reason goes to the family doctor to decide."""
    p, doses = call.patient, (call.context or {}).get("doses") or []
    said = {k: (v or {}).get("value") for k, v in (call.answers or {}).items()}
    if said.get("emlandi") == "yes":
        for code in vaccines.record(db, p, doses, "ota-ona", now(), confirmed=False):
            dmed.push(db, "Immunization: ota-ona so'zi", p, dmed.immunization(p, code, now(), reported=True), vaccines.DOSES[code]["short"])
        return
    if said.get("emlandi") != "no":
        return
    names = ", ".join(vaccines.DOSES[c]["short"] for c in doses if c in vaccines.DOSES)
    why = (
        "ota-ona kela olmaydi"
        if said.get("keladi") == "no"
        else "bola kasal yoki emlash kechiktirilgan"
        if said.get("kasal") == "yes"
        else "ota-ona kelishga rozi"
    )
    open_task(db, p, "emlash", "hamshira", f"{names}: emlanmagan ({why})", 72)
    if said.get("kasal") == "yes":
        notify(
            db,
            p,
            "shifokor",
            "yellow",
            f"EMLASH KECHIKTIRILGAN: {p.full_name} ({p.mahalla}) — {names}. Ota-ona: bola kasal yoki shifokor kechiktirgan. Qaror kerak.",
            f"ПРИВИВКА ОТЛОЖЕНА: {p.full_name} ({p.mahalla}) — {names}. Со слов родителя: ребёнок болеет или врач отложил. Нужно решение.",
        )


def call_no_answer(db, call):
    """Three unanswered attempts -> the nurse gets a home-visit task (nobody stays silent)."""
    call.attempts = (call.attempts or 0) + 1
    if call.attempts >= 3:
        call.status, call.finished_at, call.flags = "javobsiz", now(), ["noanswer"]
        p = call.patient
        open_task(db, p, "hamshira_tashrif", "hamshira", "Qo'ng'iroqqa 3 marta javob bermadi", 24)
        notify(
            db,
            p,
            "hamshira",
            "yellow",
            f"{p.full_name}: qo'ng'iroqqa 3 marta javob bermadi — uyiga borish kerak.",
            f"{p.full_name}: не ответила на 3 звонка — нужен визит на дом.",
        )
    return call.attempts


def wrong_person(db, call, said=""):
    """Somebody else picked up, or the person did not say who she is. Nothing about health was said; the
    call stays planned and counts as an attempt, so three of them still bring the nurse to the door."""
    call.answers = {**(call.answers or {}), "shaxs": {"value": "no", "transcript": said[:200]}}
    audit(db, "bemor", "call_wrong_person", call.patient, call.scenario)
    return call_no_answer(db, call)


def sweep(db):
    """Timers, run every minute by the scheduler: overdue tasks escalate once; silent patients change zone."""
    for t in db.query(Task).filter(Task.status == "ochiq", Task.due_at < now(), Task.escalated == False).all():  # noqa: E712
        t.escalated = True
        p = t.patient
        notify(
            db,
            p,
            "rahbar",
            "red",
            f"MUDDAT O'TDI: {p.full_name} — «{TASK_UZ.get(t.type, t.type)}» o'z vaqtida bajarilmadi.",
            f"ПРОСРОЧКА: {p.full_name} — «{TASK_RU.get(t.type, t.type)}» не выполнен в срок.",
        )
    limit = now() - timedelta(days=rules.T["silent_days"]["yellow"])
    for p in db.query(Patient).filter(Patient.kind.in_(WATCHED), Patient.last_contact_at < limit, Patient.zone != "red").limit(200).all():
        recompute(db, p)
    db.commit()


def summary(p, lang="uz"):
    """Five-line case summary for the doctor, built from facts only (no generation)."""
    data, prev, _ = merged(p)
    uz = lang != "ru"
    kind = {
        "homilador": ("Homilador", "Беременная"),
        "tuqqan": ("Tuqqan ayol", "Родильница"),
        "chaqaloq": ("Chaqaloq", "Новорождённый"),
        "bola": ("Bola", "Ребёнок"),
        "boshqa": ("Bemor", "Пациент"),
    }.get(p.kind, ("Bemor", "Пациент"))[0 if uz else 1]
    lines = [
        f"{kind}: {p.full_name}"
        + (f", {p.birth_year}" if p.birth_year else "")
        + (f", {p.weeks} {'hafta' if uz else 'нед.'}" if p.weeks else "")
        + f"; {p.mahalla or ''}"
    ]
    z = (ZONE_UZ if uz else ZONE_RU)[p.zone or "green"]
    rs = p.reasons or []
    lines.append(
        (f"Zona: {z}. Sabablar: " if uz else f"Зона: {z}. Причины: ")
        + ("; ".join(f"{r['uz' if uz else 'ru']} {r['value']}".strip() for r in rs) or ("yo'q" if uz else "нет"))
    )
    vals = []
    if data.get("bp_sys"):
        vals.append(f"{'QB' if uz else 'АД'} {int(data['bp_sys'])}/{int(data['bp_dia'] or 0)}")
    if data.get("hb"):
        vals.append(f"Hb {data['hb']:g}" + (f" ({'avval' if uz else 'было'} {prev['hb']:g})" if prev.get("hb") else ""))
    if data.get("temp"):
        vals.append(f"t {data['temp']:g}°C")
    if data.get("glucose"):
        vals.append(f"{'qand' if uz else 'сахар'} {data['glucose']:g}")
    lines.append(("Oxirgi ko'rsatkichlar: " if uz else "Последние показатели: ") + (", ".join(vals) or "—"))
    open_t = [t for t in p.tasks if t.status == "ochiq"]
    lines.append(
        ("Ochiq vazifalar: " if uz else "Открытые задачи: ")
        + (", ".join((TASK_UZ if uz else TASK_RU).get(t.type, t.type) for t in open_t) or ("yo'q" if uz else "нет"))
    )
    last = rules.days_between(p.last_contact_at)
    lines.append(
        (f"Oxirgi aloqa: {last} kun oldin." if uz else f"Последний контакт: {last} дн. назад.")
        + ((" Tashxis (shifokor aytgan): " if uz else " Диагноз (со слов врача): ") + p.diagnosis if p.diagnosis else "")
    )
    return lines


def doctor_stats(tasks):
    """Per-doctor accountability for the head of the district: open, overdue, closed on time, mismatches."""
    out = {}
    for t in tasks:
        doc = (t.patient.doctor if t.patient else None) or "—"
        d = out.setdefault(doc, {"doctor": doc, "open": 0, "overdue": 0, "closed": 0, "in_time": 0, "mismatch": 0})
        if t.status == "ochiq":
            d["open"] += 1
            d["overdue"] += bool(t.due_at and t.due_at < now())
        elif t.done_at:
            d["closed"] += 1
            d["in_time"] += t.done_at <= t.due_at
            d["mismatch"] += t.status == "nomuvofiq"
    for d in out.values():
        d["in_time_pct"] = round(100 * d["in_time"] / d["closed"]) if d["closed"] else None
    return sorted(out.values(), key=lambda d: (-d["overdue"], -d["open"]))


def dashboard(db):
    zones = dict(db.query(Patient.zone, func.count(Patient.id)).group_by(Patient.zone).all())
    tasks = db.query(Task).options(joinedload(Task.patient)).all()
    closed = [t for t in tasks if t.status != "ochiq" and t.done_at]
    open_ = [t for t in tasks if t.status == "ochiq"]
    silent = db.query(func.count(Patient.id)).filter(Patient.kind.in_(WATCHED), Patient.last_contact_at < now() - timedelta(days=config.SILENT_DAYS)).scalar()
    # complaint clusters by mahalla in the last 7 days: an early, anonymised signal for the epidemiologist
    cl = {}
    week = db.query(Observation).options(joinedload(Observation.patient)).filter(Observation.created_at >= now() - timedelta(days=7))
    for o in week:
        if set((o.data or {}).get("complaints") or []) & {"isitma", "yotal"} and o.patient:
            cl.setdefault(o.patient.mahalla or "—", set()).add(o.patient_id)
    clusters = sorted(
        ({"mahalla": m, "count": len(ids), "zone": "red" if len(ids) >= 8 else "yellow" if len(ids) >= 4 else "green"} for m, ids in cl.items()),
        key=lambda x: -x["count"],
    )[:8]
    children = db.query(Patient).filter(Patient.kind.in_(vaccines.CHILD)).options(selectinload(Patient.vaccinations)).all()
    return {
        "district": config.DISTRICT,
        "zones": {z: zones.get(z, 0) for z in ("red", "yellow", "green")},
        "total": sum(zones.values()),
        "tasks_open": len(open_),
        "tasks_overdue": sum(1 for t in open_ if t.due_at and t.due_at < now()),
        "closed_in_time_pct": round(100 * sum(1 for t in closed if t.done_at <= t.due_at) / len(closed)) if closed else None,
        "verified": sum(1 for t in tasks if t.status == "tasdiqlandi"),
        "mismatch": sum(1 for t in tasks if t.status == "nomuvofiq"),
        "silent": silent,
        "calls_done": db.query(func.count(Call.id)).filter(Call.status == "tugadi").scalar(),
        "calls_due": db.query(func.count(Call.id)).filter(Call.status == "rejalashtirilgan", Call.planned_at <= now()).scalar(),
        "no_consent": db.query(func.count(Patient.id)).filter(Patient.consent_at.is_(None)).scalar(),
        "clusters": clusters,
        "doctors": doctor_stats(tasks),
        "in_hospital": db.query(func.count(Hospitalization.id)).filter(Hospitalization.discharged_at.is_(None)).scalar(),
        "vaccines": vaccines.coverage(children, now()),
        "dispensary": sum(1 for (g,) in db.query(Patient.groups).filter(Patient.groups.isnot(None)) if g),
        "kinds": dict(db.query(Patient.kind, func.count(Patient.id)).group_by(Patient.kind).all()),
    }


LAB_COLUMNS = {
    "full_name": "full_name",
    "fio": "full_name",
    "birth_year": "birth_year",
    "hb": "hb",
    "gemoglobin": "hb",
    "bp_sys": "bp_sys",
    "bp_dia": "bp_dia",
    "glucose": "glucose",
    "qand": "glucose",
    "temp": "temp",
    "pulse": "pulse",
}


def import_lab(db, text):
    """Batch of laboratory results as CSV (full_name, birth_year, hb, bp_sys, bp_dia, glucose...).
    Every row goes through the same rules as a single result. Returns what changed."""
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(text.strip()), delimiter=";" if text.count(";") > text.count(",") else ","))
    res = {"rows": len(rows), "matched": 0, "not_found": [], "invalid": [], "changed": []}
    for r in rows[:2000]:
        row = {LAB_COLUMNS[k.strip().lower()]: (v or "").strip() for k, v in r.items() if k and k.strip().lower() in LAB_COLUMNS}
        name = row.get("full_name", "")
        q = db.query(Patient).filter(Patient.full_name.ilike(name))
        if row.get("birth_year", "").isdigit():
            q = q.filter(Patient.birth_year == int(row["birth_year"]))
        p = q.first() if name else None
        if not p:
            res["not_found"].append(name or "?")
            continue
        try:  # the same plausibility limits as for a result typed by hand
            data = Vitals(**{k: row[k].replace(",", ".") for k in NUM if row.get(k)}).values()
        except ValueError:
            res["invalid"].append(name)
            continue
        if not data:
            continue
        old = p.zone
        zone, _ = add_observation(db, p, "tahlil", data, {}, "CSV", "Laboratoriya", contact=False)
        res["matched"] += 1
        if zone != old:
            res["changed"].append({"id": p.id, "name": p.full_name, "from": old, "to": zone})
    return res
