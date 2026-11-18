"""Business logic: zones, tasks with a 24-hour timer, calls, visit verification."""

import json
import os
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from . import config, rules, telegram
from .db import AuditLog, Call, Notice, Observation, Patient, RiskEvent, Task
from .schemas import Vitals

HERE = os.path.dirname(__file__)
SCENARIOS = {}
for _f in sorted(os.listdir(os.path.join(HERE, "scenarios"))):
    if _f.endswith(".json"):
        with open(os.path.join(HERE, "scenarios", _f), encoding="utf-8") as fh:
            _s = json.load(fh)
            SCENARIOS[_s["id"]] = _s

NUM = ["bp_sys", "bp_dia", "hb", "glucose", "temp", "pulse", "breath"]
ZONE_UZ = {"red": "QIZIL", "yellow": "SARIQ", "green": "YASHIL"}
ZONE_RU = {"red": "КРАСНАЯ", "yellow": "ЖЁЛТАЯ", "green": "ЗЕЛЁНАЯ"}
TASK_UZ = {"faol_chaqiruv": "Faol chaqiruv", "mutaxassis": "Mutaxassis ko'rigi", "hamshira_tashrif": "Hamshira tashrifi"}
TASK_RU = {"faol_chaqiruv": "Активный вызов", "mutaxassis": "Осмотр специалиста", "hamshira_tashrif": "Визит медсестры"}


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
    if level in ("red", "yellow") and telegram.enabled():
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
    return t


def recompute(db, patient):
    """Re-evaluate the zone from all data; on a change, log it, notify and open a task."""
    data, prev, quotes = merged(patient)
    silent = rules.days_between(patient.last_contact_at)
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


class ConsentRequired(Exception):
    """AI calls are allowed only for patients who gave consent."""


def add_observation(db, patient, source, data, quotes=None, text="", author="", contact=True):
    o = Observation(patient_id=patient.id, source=source, data=data or {}, quotes=quotes or {}, text=text, author=author, created_at=now())
    db.add(o)
    patient.observations.append(o)
    if contact:
        patient.last_contact_at = now()
    return recompute(db, patient)


def create_call(db, patient, scenario, task_id=None, planned_at=None):
    if not patient.consent_at:
        raise ConsentRequired(patient.full_name)
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
    )
    db.add(c)
    patient.calls.append(c)
    return c


def discharge(db, patient, note=""):
    """Hospital discharge of a high-risk patient -> 'Faol chaqiruv' for the family doctor + planned AI calls."""
    patient.discharged_at = now()
    t = open_task(db, patient, "faol_chaqiruv", "shifokor", "Shifoxonadan chiqarildi" + (": " + note if note else ""), config.ACTIVE_CALL_HOURS)
    notify(
        db,
        patient,
        "shifokor",
        "yellow",
        f"FAOL CHAQIRUV: {patient.full_name} ({patient.mahalla}) shifoxonadan chiqarildi. {config.ACTIVE_CALL_HOURS} soat ichida ko'rib, tasdiqlang.",
        f"АКТИВНЫЙ ВЫЗОВ: {patient.full_name} ({patient.mahalla}) выписана. Осмотрите и подтвердите в течение {config.ACTIVE_CALL_HOURS} часов.",
    )
    scenario = "chaqaloq_30kun" if patient.kind == "chaqaloq" else "chiqarishdan_keyin"
    planned = any(c.scenario == scenario and c.status == "rejalashtirilgan" for c in patient.calls)
    if not patient.consent_at or planned:  # no consent -> no calls; a repeated discharge does not double the schedule
        return t
    if patient.kind == "chaqaloq":
        base = patient.born_at or now()
        for d in SCENARIOS["chaqaloq_30kun"].get("schedule_days", []):
            when = base + timedelta(days=d)
            if when > now() - timedelta(days=1):
                create_call(db, patient, "chaqaloq_30kun", planned_at=when)
    else:
        create_call(db, patient, "chiqarishdan_keyin", planned_at=now() + timedelta(days=1))
    return t


def task_done(db, task, note=""):
    """Doctor marks the visit as done -> the patient is asked to confirm it (double confirmation)."""
    task.status, task.done_at, task.note = "bajarildi", now(), note
    p = task.patient
    p.last_contact_at = now()
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
    call.status, call.finished_at = "tugadi", now()
    call.flags = complaints + extra + ([] if verified in (None, True) else ["tashrif_tasdiqlanmadi"])
    if call.scenario == "tashrif_tasdiq":
        t = db.get(Task, call.task_id) if call.task_id else None
        if t and verified is not None:
            t.status = "tasdiqlandi" if verified else "nomuvofiq"
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
        zone = p.zone
    else:
        data["complaints"] = sorted(set(complaints))
        data["extra_flags"] = sorted(set(extra))
        zone, _ = add_observation(db, p, "qongiroq", data, quotes, "\n".join(lines), "Nigoh AI")
    return {"zone": zone, "flags": call.flags, "alert": bool(complaints) or zone == "red", "verified": verified}


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
    for p in db.query(Patient).filter(Patient.last_contact_at < limit, Patient.zone != "red").limit(200).all():
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
    silent = db.query(func.count(Patient.id)).filter(Patient.last_contact_at < now() - timedelta(days=config.SILENT_DAYS)).scalar()
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
