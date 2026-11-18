"""ML second opinion (never decides the zone).

RandomForest trained on the open UCI "Maternal Health Risk" dataset (1,014 records:
age, blood pressure, blood sugar, temperature, heart rate -> low / mid / high risk).
Metrics are measured on a 25% hold-out and shown in the app.
"""

import csv
import logging
import os

from . import config

log = logging.getLogger("nigoh.ml")
_m = {"model": None, "metrics": None}
PATHS = [os.path.join(config.DATA_DIR, "maternal_health_risk.csv"), os.path.join(os.path.dirname(__file__), "maternal_health_risk.csv")]
LEVEL = {"high risk": "red", "mid risk": "yellow", "low risk": "green"}


def load():
    path = next((p for p in PATHS if os.path.exists(p)), None)
    if not path:
        return None
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score, recall_score
        from sklearn.model_selection import train_test_split

        X, y = [], []
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                X.append([float(r["Age"]), float(r["SystolicBP"]), float(r["DiastolicBP"]), float(r["BS"]), float(r["BodyTemp"]), float(r["HeartRate"])])
                y.append(LEVEL[r["RiskLevel"].strip().lower()])
        Xa, Xb, ya, yb = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
        clf = RandomForestClassifier(n_estimators=200, random_state=42).fit(Xa, ya)
        pred = clf.predict(Xb)
        _m["model"] = clf
        _m["metrics"] = {
            "records": len(X),
            "holdout": len(Xb),
            "accuracy": round(accuracy_score(yb, pred), 3),
            "recall_red": round(recall_score(yb, pred, labels=["red"], average="macro"), 3),
        }
        log.info("ML model ready: %s", _m["metrics"])
    except Exception as e:
        log.warning("ML model not loaded: %s", e)
    return _m["metrics"]


def metrics():
    return _m["metrics"]


def predict(age, data):
    """Second opinion for an adult patient with a blood-pressure reading; None otherwise."""
    if not _m["model"] or not data.get("bp_sys") or not data.get("bp_dia"):
        return None
    row = [
        float(age or 27),
        float(data["bp_sys"]),
        float(data["bp_dia"]),
        float(data.get("glucose") or 7.0),
        float(data.get("temp") or 36.7) * 9 / 5 + 32,
        float(data.get("pulse") or 76),
    ]
    proba = _m["model"].predict_proba([row])[0]
    best = max(range(len(proba)), key=lambda i: proba[i])
    assumed = [k for k in ("glucose", "temp", "pulse") if not data.get(k)]
    return {"zone": _m["model"].classes_[best], "confidence": round(float(proba[best]), 2), "assumed": assumed}
