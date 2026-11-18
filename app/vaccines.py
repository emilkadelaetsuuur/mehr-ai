"""The national calendar of preventive vaccinations, and what follows from it for one child.

The calendar is a file (vaccines.json): the age at which each dose is due. Together with the child's date of
birth and the doses already recorded it gives, for every child in the register, what is done, what is due
now and what is overdue. Nobody has to keep a list: the calendar finds the children itself, and a calling
round asks their parents.

A dose a parent reports in a call is kept as said, not as given: it waits for a record from the vaccination
room (through DMED) and until then it is shown as unconfirmed.
"""

import json
import os
from datetime import timedelta

from .db import Vaccination

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "vaccines.json"), encoding="utf-8") as _fh:
    CALENDAR = json.load(_fh)
AGES, DOSES = CALENDAR["ages"], {d["id"]: d for d in CALENDAR["doses"]}
GRACE = timedelta(days=CALENDAR["grace_days"])  # how long after its day a dose is still simply "due"
CHILD = ("chaqaloq", "bola")


def plan(patient, now):
    """Every dose of the calendar for this child, oldest first:
    {id, short, age, due_at, done_at, source, state}, where state is
    done (recorded), said (a parent said so, not confirmed yet), due, overdue or later."""
    if patient.kind not in CHILD or not patient.born_at:
        return []
    got = {v.code: v for v in patient.vaccinations}
    out = []
    for d in CALENDAR["doses"]:
        if d.get("who") and d["who"] != patient.sex:
            continue
        due = patient.born_at + timedelta(days=AGES[d["age"]]["days"])
        v = got.get(d["id"])
        if v:
            state = "done" if v.confirmed else "said"
        else:
            state = "later" if now < due else "due" if now <= due + GRACE else "overdue"
        done, source = (v.done_at, v.source) if v else (None, None)
        out.append({"id": d["id"], "short": d["short"], "age": d["age"], "due_at": due, "done_at": done, "source": source, "state": state})
    return out


def owed(patient, now):
    """What a call to the parent asks about: the doses of the earliest age that are due or overdue
    (catching up starts from the oldest gap). {} when the child is up to date."""
    behind = [d for d in plan(patient, now) if d["state"] in ("due", "overdue")]
    if not behind:
        return {}
    age = behind[0]["age"]
    return {"age": age, "doses": [d["id"] for d in behind if d["age"] == age], "overdue": any(d["state"] == "overdue" for d in behind)}


def names(codes, lang):
    """The doses as they are said aloud, each kind once: "pentavalent, poliomiyelitga qarshi va ..."."""
    said = []
    for c in codes:
        name = DOSES[c][lang if lang in ("uz", "ru") else "uz"]
        if name not in said:
            said.append(name)
    last = " va " if lang != "ru" else " и "
    return said[0] if len(said) == 1 else ", ".join(said[:-1]) + last + said[-1] if said else ""


def sentence(context, lang, child=""):
    """What the call says before its questions: which vaccinations have come due for the child."""
    age, said = AGES[context["age"]], names(context["doses"], lang)
    if lang == "ru":
        return f"По календарю вашему ребёнку подошёл срок прививок, которые делают {age['ru']}: {said}."
    return f"Taqvim bo'yicha farzandingiz{' ' + child + 'ga' if child else 'ga'} {age['uz']} emlashlar muddati kelgan: {said} emlashlar."


def record(db, patient, codes, source, when, confirmed=True):
    """Write doses down. A confirmed record replaces a parent's word; nothing replaces a confirmed record."""
    got = {v.code: v for v in patient.vaccinations}
    changed = []
    for c in codes:
        if c not in DOSES:
            continue
        v = got.get(c)
        if v and (v.confirmed or not confirmed):
            continue
        if v:
            v.done_at, v.source, v.confirmed = when, source, True
        else:
            v = Vaccination(patient_id=patient.id, code=c, done_at=when, source=source, confirmed=confirmed, created_at=when)
            db.add(v)
            patient.vaccinations.append(v)
        changed.append(c)
    return changed


def coverage(children, now):
    """For the district: how many children the calendar covers, how many are behind, and by how much."""
    behind = [p for p in children if any(d["state"] == "overdue" for d in plan(p, now))]
    waiting = [p for p in children if p not in behind and any(d["state"] == "due" for d in plan(p, now))]
    total = len(children)
    return {"children": total, "overdue": len(behind), "due": len(waiting), "in_time_pct": round(100 * (total - len(behind)) / total) if total else None}
