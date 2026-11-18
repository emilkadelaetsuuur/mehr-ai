"""The link with DMED, the national digital health platform: the formats and the outbox.

OUT - what this system learns goes to DMED at once, so that nobody types it there a second time: the answers
      of every AI call, warning signs, the tasks staff were given, a vaccination a parent reported, the
      measurements a nurse dictated.
IN  - DMED tells this system what happened to a patient elsewhere: she was taken to a hospital, she was
      discharged with a diagnosis, a child was vaccinated. app/exchange.py acts on it.

The format is HL7 FHIR, as the platform's implementation guide prescribes (dhp.uz/fhir/core, FHIR R5):
Encounter, CarePlan and Immunization come in; QuestionnaireResponse, Flag, Task, Immunization and
Observation go out. A person is matched by PINFL.

The real platform admits only clients registered at its sign-on server. Until its address and a token are
set (DMED_BASE_URL, DMED_TOKEN), the same code works against a stand-in inside this system ("sinov
muhiti"): what would be sent is kept and shown on the DMED page, and events can be sent in by hand.
Nothing else differs, so switching to the real platform is a matter of settings and of checking the
resources against the guide's profiles.
"""

import logging
import threading
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import event

from . import config, vaccines
from .db import DmedMessage, SessionLocal

log = logging.getLogger("nigoh.dmed")
ICD = "http://hl7.org/fhir/sid/icd-10"
LOINC = {
    "bp_sys": ("8480-6", "Systolic blood pressure", "mm[Hg]"),
    "bp_dia": ("8462-4", "Diastolic blood pressure", "mm[Hg]"),
    "hb": ("718-7", "Hemoglobin [Mass/volume] in Blood", "g/L"),
    "glucose": ("2339-0", "Glucose [Mass/volume] in Blood", "mmol/L"),
    "temp": ("8310-5", "Body temperature", "Cel"),
    "pulse": ("8867-4", "Heart rate", "/min"),
    "breath": ("9279-1", "Respiratory rate", "/min"),
}
TASK_STATUS = {"ochiq": "requested", "bajarildi": "completed", "tasdiqlandi": "completed", "nomuvofiq": "rejected"}
_wake = threading.Event()


def mode():
    """'jonli' when a platform address is set, else 'sinov': the stand-in inside this system."""
    return "jonli" if config.DMED_BASE_URL else "sinov"


def now():
    return datetime.utcnow()


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def when(text):
    """A FHIR date-time as the naive UTC time the tables hold; None if it cannot be read."""
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(UTC).replace(tzinfo=None) if d.tzinfo else d


def in_icd(code, specs):
    """True when an ICD-10 code falls into one of the ranges, e.g. "I21.0" into "I00-I99" or "Z21"."""
    c = (code or "").strip().upper()[:3]
    if len(c) < 3 or not c[1:].isdigit():
        return False
    for spec in specs or []:
        a, _, b = spec.partition("-")
        if c[0] == a[0] and int(a[1:3]) <= int(c[1:]) <= int((b or a)[1:3]):
            return True
    return False


def subject(p):
    """How a person is named to DMED: by PINFL, with the name for the reader."""
    return {"identifier": {"system": config.DMED_PINFL_SYSTEM, "value": p.pinfl or ""}, "display": p.full_name}


# ---------- what goes out


def push(db, kind, patient, resource, summary=""):
    """Put a resource in the outbox. It leaves as soon as the change that produced it is saved."""
    who = patient.id if patient else None
    m = DmedMessage(direction="out", kind=kind[:40], patient_id=who, summary=summary[:240], payload=resource, status="navbatda", created_at=now())
    db.add(m)
    return m


def flush(db, limit=50):
    """Send what is waiting. The stand-in takes everything; the real platform's refusal is kept with the
    message, and a message that could not be delivered stays in the queue for the next round."""
    rows = db.query(DmedMessage).filter(DmedMessage.direction == "out", DmedMessage.status == "navbatda").order_by(DmedMessage.id).limit(limit).all()
    if not rows:
        return 0
    for m in rows:
        if mode() == "sinov":
            m.status, m.sent_at = "yuborildi", now()
            continue
        kind = (m.payload or {}).get("resourceType", "")
        try:
            r = httpx.post(
                config.DMED_BASE_URL if kind == "Bundle" else f"{config.DMED_BASE_URL}/{kind}",
                json=m.payload,
                headers={"Authorization": f"Bearer {config.DMED_TOKEN}", "Content-Type": "application/fhir+json"},
                timeout=15,
            )
        except Exception as e:  # no connection: it waits
            m.error = str(e)[:240]
            continue
        if r.status_code < 300:
            m.status, m.sent_at, m.error = "yuborildi", now(), None
        else:
            m.status, m.error = "xato", f"{r.status_code} {r.text[:200]}"
            log.warning("dmed refused %s: %s", kind, m.error)
    db.commit()
    return len(rows)


@event.listens_for(SessionLocal, "after_commit")
def _kick(_session):
    _wake.set()  # something was saved: there may be mail to send


def sender(stop):
    """Background post office: sends the outbox whenever something was saved, and every twenty seconds anyway."""
    while not stop.is_set():
        _wake.wait(20)
        _wake.clear()
        if stop.is_set():
            break
        try:
            with SessionLocal() as db:
                flush(db)
        except Exception:
            log.exception("dmed outbox failed")


def answers(call, scenario):
    """An AI call as a QuestionnaireResponse: every question that was asked and what was understood, and
    the patient's own questions with what she was told."""
    items = []
    for q in scenario["questions"]:
        a = (call.answers or {}).get(q["id"])
        if not a:
            continue
        v = a.get("value")
        value = {"valueBoolean": v == "yes"} if v in ("yes", "no") else {"valueDecimal": v} if isinstance(v, (int, float)) else {"valueString": "noaniq"}
        items.append({"linkId": q["id"], "text": q["uz"], "answer": [value]})
    for i, x in enumerate(((call.answers or {}).get("suhbat") or {}).get("items") or [], 1):
        told = x.get("a") or ("xavf belgisi: 103 aytildi" if x.get("kind") == "alarm" else "savol shifokorga yuborildi")
        items.append({"linkId": f"savol-{i}", "text": x.get("q", ""), "answer": [{"valueString": told}]})
    return {
        "resourceType": "QuestionnaireResponse",
        "status": "completed",
        "questionnaire": f"urn:nigoh:ssenariy:{call.scenario}",
        "subject": subject(call.patient),
        "authored": iso(call.finished_at or now()),
        "author": {"display": "Nigoh AI qo'ng'iroq"},
        "item": items,
    }


def flag(patient, text, at=None):
    """A warning for whoever opens the patient's record in DMED."""
    return {
        "resourceType": "Flag",
        "status": "active",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/flag-category", "code": "clinical"}]}],
        "code": {"text": text[:240]},
        "subject": subject(patient),
        "period": {"start": iso(at or now())},
    }


def task(t, patient, label):
    """A task a member of staff was given, with its deadline."""
    return {
        "resourceType": "Task",
        "status": TASK_STATUS.get(t.status or "ochiq", "requested"),
        "intent": "order",
        "priority": "urgent" if t.type in ("mutaxassis", "qayta_qongiroq") else "routine",
        "description": f"{label}: {t.reason or ''}".strip(": ")[:300],
        "for": subject(patient),
        "authoredOn": iso(t.created_at or now()),
        "restriction": {"period": {"end": iso(t.due_at)}},
        "owner": {"display": t.role},
    }


def consent(patient, what, at):
    """A consent the patient gave, so that DMED knows what this system may do on her behalf."""
    return {"resourceType": "Consent", "status": "active", "category": [{"text": what}], "subject": subject(patient), "date": iso(at)[:10]}


def immunization(patient, code, at, reported=False):
    """A dose of the calendar. `reported`: a parent said so in a call, the vaccination room has not confirmed it."""
    r = {
        "resourceType": "Immunization",
        "status": "completed",
        "vaccineCode": {"coding": [{"system": "urn:nigoh:emlash", "code": code}], "text": vaccines.DOSES[code]["short"]},
        "patient": subject(patient),
        "occurrenceDateTime": iso(at),
        "primarySource": not reported,
    }
    if reported:
        r["informationSource"] = {"concept": {"text": "ota-ona so'zi (AI qo'ng'iroq); emlash xonasi tasdig'i kutilmoqda"}}
    return r


def observations(patient, data, at, author=""):
    """Measurements as one transaction: each value is an Observation with its LOINC code."""
    entries = []
    for k, (code, display, unit) in LOINC.items():
        if data.get(k) is not None:
            entries.append(
                {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                    "subject": subject(patient),
                    "effectiveDateTime": iso(at),
                    "valueQuantity": {"value": data[k], "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
                    "performer": [{"display": author}] if author else [],
                }
            )
    if not entries:
        return None
    return {"resourceType": "Bundle", "type": "transaction", "entry": [{"resource": e, "request": {"method": "POST", "url": "Observation"}} for e in entries]}


# ---------- what comes in: the shapes DMED uses, written and read


def encounter(patient, hospital, start, end=None, emergency=True, reason="", icd10="", diagnosis="", brought_by="", advice="", eid=None):
    """A hospital stay as DMED sends it: an Encounter (in progress, or completed with the diagnosis), and
    with it the hospital's recommendations as a CarePlan. Used by the stand-in and by the tests."""
    e = {
        "resourceType": "Encounter",
        "id": eid or uuid.uuid4().hex[:12],
        "status": "completed" if end else "in-progress",
        "class": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER" if emergency else "IMP"}]}],
        "subject": subject(patient),
        "serviceProvider": {"display": hospital},
        "actualPeriod": {"start": iso(start), **({"end": iso(end)} if end else {})},
    }
    if reason:
        e["reason"] = [{"value": [{"concept": {"text": reason}}]}]
    if icd10 or diagnosis:
        e["diagnosis"] = [{"condition": [{"concept": {"coding": [{"system": ICD, "code": icd10, "display": diagnosis}], "text": diagnosis}}]}]
    if brought_by:
        e["admission"] = {"admitSource": {"text": brought_by}}
    plan = [{"resourceType": "CarePlan", "status": "active", "intent": "plan", "subject": subject(patient), "description": advice}] if advice else []
    return {"resourceType": "Bundle", "type": "message", "entry": [{"resource": r} for r in [e, *plan]]}


def _first(x):
    return (x[0] if x else {}) if isinstance(x, list) else (x or {})


def read_encounter(e):
    """The few facts this system needs from an Encounter, whichever FHIR version shaped it (R5 or R4)."""
    classes = e.get("class") if isinstance(e.get("class"), list) else [{"coding": [e.get("class") or {}]}]
    codes = {c.get("code") for cc in classes for c in (cc or {}).get("coding") or []}
    period = e.get("actualPeriod") or e.get("period") or {}
    concept = _first(_first(_first(e.get("diagnosis")).get("condition")).get("concept")) if e.get("diagnosis") else {}
    if not concept and e.get("diagnosis"):  # R4: the condition is a reference with a display
        concept = {"text": (_first(e.get("diagnosis")).get("condition") or {}).get("display", "")}
    coding = _first(concept.get("coding"))
    reason = _first(_first(_first(e.get("reason")).get("value")).get("concept")).get("text") or _first(e.get("reasonCode")).get("text") or ""
    who = e.get("subject") or {}
    return {
        "id": str(e.get("id") or ""),
        "pinfl": (who.get("identifier") or {}).get("value") or "",
        "name": who.get("display") or "",
        "hospital": (e.get("serviceProvider") or {}).get("display") or "",
        "emergency": "EMER" in codes,
        "start": when(period.get("start")),
        "end": when(period.get("end")),
        "over": e.get("status") in ("completed", "finished", "discharged") or bool(period.get("end")),
        "reason": reason,
        "icd10": (coding.get("code") or "").upper(),
        "diagnosis": concept.get("text") or coding.get("display") or "",
        "brought_by": ((e.get("admission") or e.get("hospitalization") or {}).get("admitSource") or {}).get("text") or "",
    }


def read_immunization(r):
    """Who was vaccinated, with which dose of the calendar and when."""
    code = _first((r.get("vaccineCode") or {}).get("coding")).get("code") or ""
    text = (r.get("vaccineCode") or {}).get("text") or ""
    known = code if code in vaccines.DOSES else next((d["id"] for d in vaccines.CALENDAR["doses"] if text and d["short"].lower() == text.lower()), "")
    who = r.get("patient") or {}
    return {"pinfl": (who.get("identifier") or {}).get("value") or "", "name": who.get("display") or "", "code": known, "at": when(r.get("occurrenceDateTime"))}
