"""Export of one patient as an HL7 FHIR R4 Bundle (Patient, Observation, RiskAssessment, Task).

This is the integration seam: a ministry system such as DMED can read the same data without
knowing our tables. LOINC codes are used where a standard code exists.
"""

from . import core

LOINC = {
    "bp_sys": ("8480-6", "Systolic blood pressure", "mm[Hg]"),
    "bp_dia": ("8462-4", "Diastolic blood pressure", "mm[Hg]"),
    "hb": ("718-7", "Hemoglobin [Mass/volume] in Blood", "g/L"),
    "glucose": ("2339-0", "Glucose [Mass/volume] in Blood", "mmol/L"),
    "temp": ("8310-5", "Body temperature", "Cel"),
    "pulse": ("8867-4", "Heart rate", "/min"),
    "breath": ("9279-1", "Respiratory rate", "/min"),
}
ZONE = {"red": "high", "yellow": "moderate", "green": "low"}
STATUS = {"ochiq": "requested", "bajarildi": "completed", "tasdiqlandi": "completed", "nomuvofiq": "rejected"}


def _iso(d):
    return d.isoformat() + "Z" if d else None


def bundle(p):
    ref = f"Patient/{p.id}"
    family, _, given = p.full_name.partition(" ")
    entries = [
        {
            "resourceType": "Patient",
            "id": str(p.id),
            "name": [{"family": family, "given": [given] if given else []}],
            "gender": "unknown",
            "birthDate": p.born_at.date().isoformat() if p.born_at else (str(p.birth_year) if p.birth_year else None),
            "telecom": [{"system": "phone", "value": p.phone}] if p.phone else [],
            "address": [{"district": p.mahalla, "country": "UZ"}] if p.mahalla else [],
        }
    ]
    for o in sorted(p.observations, key=lambda o: o.created_at):
        for k, (code, display, unit) in LOINC.items():
            v = (o.data or {}).get(k)
            if v is not None:
                entries.append(
                    {
                        "resourceType": "Observation",
                        "id": f"{o.id}-{k}",
                        "status": "final",
                        "subject": {"reference": ref},
                        "effectiveDateTime": _iso(o.created_at),
                        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
                        "valueQuantity": {"value": v, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
                    }
                )
    entries.append(
        {
            "resourceType": "RiskAssessment",
            "id": f"risk-{p.id}",
            "status": "final",
            "subject": {"reference": ref},
            "method": {"text": "Mehr AI rule engine (rules.json); decision stays with the clinician"},
            "prediction": [
                {
                    "qualitativeRisk": {
                        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/risk-probability", "code": ZONE[p.zone or "green"]}],
                        "text": core.ZONE_UZ[p.zone or "green"],
                    },
                    "rationale": "; ".join(f"{r['uz']} {r['value']} ({r['rule']})".strip() for r in (p.reasons or [])),
                }
            ],
        }
    )
    for t in p.tasks:
        entries.append(
            {
                "resourceType": "Task",
                "id": str(t.id),
                "status": STATUS.get(t.status, "requested"),
                "intent": "order",
                "for": {"reference": ref},
                "description": f"{core.TASK_UZ.get(t.type, t.type)}: {t.reason or ''}".strip(),
                "authoredOn": _iso(t.created_at),
                "restriction": {"period": {"end": _iso(t.due_at)}},
                "priority": "urgent" if t.escalated else "routine",
            }
        )
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"fullUrl": f"urn:nigoh:{e['resourceType']}/{e['id']}", "resource": e} for e in entries]}
