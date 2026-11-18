"""Run: pytest -q  (works offline: VoiceLab is not required for these tests)."""

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"  # never the real database
os.environ["DATA_DIR"] = _tmp
os.environ["VOICELAB_API_KEY"] = ""
os.environ["DEMO_PASSWORD"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app import extract, rules  # noqa: E402
from app.main import app  # noqa: E402


def test_rules_zones():
    assert rules.evaluate("homilador", {"bp_sys": 165, "bp_dia": 112})[0] == "red"
    assert rules.evaluate("homilador", {"bp_sys": 145, "bp_dia": 92})[0] == "yellow"
    assert rules.evaluate("homilador", {"bp_sys": 145, "bp_dia": 92, "complaints": ["kuchli_bosh_ogrigi"]})[0] == "red"
    assert rules.evaluate("homilador", {"hb": 96}, prev={"hb": 118})[0] == "yellow"
    assert rules.evaluate("homilador", {"bp_sys": 110, "bp_dia": 70, "hb": 120})[0] == "green"
    assert rules.evaluate("chaqaloq", {"temp": 37.8})[0] == "red"
    assert rules.evaluate("homilador", {}, days_silent=8)[0] == "yellow"


def test_quote_check_drops_inventions():
    text = "Sodiqova Dilnoza 1998 yil, bosimi 150/95, oyoqlarida shish bor"
    raw = {
        "bp": {"value": "150/95", "quote": "bosimi 150/95"},
        "hb": {"value": 90, "quote": "gemoglobin 90"},
        "complaints": [{"code": "shish", "quote": "shish bor"}, {"code": "qon_ketish", "quote": "qon ketyapti"}],
    }
    data, quotes, dropped = extract._clean(raw, text)
    assert data["bp_sys"] == 150 and data["complaints"] == ["shish"]
    assert "hb" in dropped and "complaints:qon_ketish" in dropped


def test_fallback_and_yes_no():
    r = extract.extract("Valiyeva Madina 1995 yil tug'ilgan, homilador, qon bosimi 160/110, boshi og'riyapti")
    assert r["data"]["bp_sys"] == 160 and "kuchli_bosh_ogrigi" in r["data"]["complaints"]
    assert extract.yes_no("yo'q, og'rimayapti") == "no"
    assert extract.yes_no("ha, bor") == "yes"
    assert extract.yes_no("нет, не было") == "no"
    assert extract.yes_no("X.") == "yes" and extract.yes_no("Xa") == "yes"


def test_full_flow():
    with TestClient(app) as c:
        d = c.get("/api/dashboard").json()
        assert d["total"] >= 300 and d["zones"]["red"] > 0
        p = c.get("/api/patients", params={"q": "Sodiqova Dilnoza"}).json()[0]
        assert p["zone"] == "green"
        r = c.post(f"/api/patients/{p['id']}/observations", json={"bp_sys": 165, "bp_dia": 110}).json()
        assert r["zone"] == "red" and r["reasons"][0]["code"] == "bp"
        full = c.get(f"/api/patients/{p['id']}").json()
        assert any(t["type"] == "mutaxassis" and t["status"] == "ochiq" for t in full["tasks"])
        m = c.get("/api/patients", params={"q": "Valiyeva Madina"}).json()[0]
        t = c.post(f"/api/patients/{m['id']}/discharge", json={}).json()
        assert t["type"] == "faol_chaqiruv"
        done = c.post(f"/api/tasks/{t['id']}/done", json={}).json()
        tok = done["call"]["token"]
        assert c.get(f"/api/call/{tok}").json()["questions"][0]["id"] == "keldi"
        c.post(f"/api/call/{tok}/answer", data={"qid": "keldi", "value": "no"})
        res = c.post(f"/api/call/{tok}/finish").json()
        assert res["verified"] is False
        assert c.get("/api/tasks", params={"status": "nomuvofiq"}).json()
        baby = c.get("/api/patients", params={"q": "Valiyev Amir"}).json()[0]
        calls = c.get(f"/api/patients/{baby['id']}").json()["calls"]
        assert any(x["scenario"] == "chaqaloq_30kun" for x in calls)
        call = c.post(f"/api/patients/{baby['id']}/calls", json={"scenario": "chaqaloq_30kun"}).json()
        c.post(f"/api/call/{call['token']}/answer", data={"qid": "emish", "value": "no"})
        c.post(f"/api/call/{call['token']}/answer", data={"qid": "harorat", "value": "38"})
        res = c.post(f"/api/call/{call['token']}/finish").json()
        assert res["zone"] == "red" and res["alert"]
        v = c.post(
            "/api/patients/confirm",
            json={
                "fields": {"full_name": "Test Bemor", "birth_year": 2000, "kind": "homilador", "bp_sys": 150, "bp_dia": 95, "complaints": ["shish"]},
                "transcript": "x",
            },
        ).json()
        assert v["created"] and v["zone"] == "yellow"
        assert c.get(f"/api/patients/{v['id']}/referral.pdf").content[:4] == b"%PDF"


def test_negation_is_not_a_complaint():
    r = extract.extract("Mirzayeva Nodira, 2003 yil, bosimi 142/92, shish yo'q, qon ketishi kuzatilmadi")
    assert r["data"].get("complaints", []) == []
    r = extract.extract("Хамидова Озода, 1991 год, температура 38,2, кровотечение, отёков нет")
    assert r["data"]["complaints"] == ["qon_ketish"]


def test_red_zone_is_released_only_by_the_specialist():
    with TestClient(app) as c:
        p = c.post(
            "/api/patients/confirm",
            json={"fields": {"full_name": "Hold Test", "birth_year": 1999, "kind": "homilador", "bp_sys": 170, "bp_dia": 112}, "consent": True},
        ).json()
        assert p["zone"] == "red"
        r = c.post(f"/api/patients/{p['id']}/observations", json={"bp_sys": 118, "bp_dia": 76}).json()
        assert r["zone"] == "red" and r["reasons"][0]["code"] == "hold"  # normal numbers alone do not clear red
        task = next(t for t in c.get(f"/api/patients/{p['id']}").json()["tasks"] if t["type"] == "mutaxassis")
        c.post(f"/api/tasks/{task['id']}/done", json={"note": "ko'rildi"})
        assert c.get(f"/api/patients/{p['id']}").json()["zone"] == "green"


def test_consent_gates_calls_and_audit_is_written():
    with TestClient(app) as c:
        p = c.post("/api/patients/confirm", json={"fields": {"full_name": "Rozilik Test", "birth_year": 2001, "kind": "homilador"}}).json()
        assert p["consent"] is False
        assert c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).status_code == 409
        c.post(f"/api/patients/{p['id']}/consent", headers={"X-Role": "hamshira"})
        assert c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).status_code == 200
        card = c.get(f"/api/patients/{p['id']}").json()
        assert [a["action"] for a in card["audit"]][:2] == ["call_created", "consent_recorded"] and card["audit"][1]["role"] == "hamshira"


def test_validation_lab_import_and_fhir():
    with TestClient(app) as c:
        assert c.post("/api/patients/confirm", json={"fields": {"full_name": "X", "bp_sys": 900}}).status_code == 422
        p = c.get("/api/patients", params={"q": "Sodiqova Dilnoza"}).json()[0]
        res = c.post("/api/import/lab", json={"csv": "full_name;birth_year;hb\nSodiqova Dilnoza;1998;64\nYo'q Odam;1990;100"}).json()
        assert res["matched"] == 1 and res["not_found"] == ["Yo'q Odam"]
        b = c.get(f"/api/patients/{p['id']}/fhir").json()
        kinds = {e["resource"]["resourceType"] for e in b["entry"]}
        assert {"Patient", "Observation", "RiskAssessment", "Task"} <= kinds
        d = c.get("/api/dashboard", headers={"X-Role": "hamshira"}).json()
        assert all(n["role"] == "hamshira" for n in d["notices"]) and d["doctors"]


def test_personal_accounts_and_doctor_scope(monkeypatch):
    from app import config

    with TestClient(app) as c:
        m = c.get("/api/patients", params={"q": "Valiyeva Madina"}).json()[0]
        c.post(f"/api/patients/{m['id']}/discharge", json={})
        monkeypatch.setattr(config, "DEMO_PASSWORD", "yoqilgan")  # switch auth on; demo accounts were created with "demo"
        assert c.get("/api/dashboard").status_code == 401
        assert c.post("/api/login", json={"username": "shifokor", "password": "xato"}).status_code == 401
        assert c.post("/api/login", json={"username": "shifokor", "password": "demo"}).status_code == 200
        assert c.get("/api/me").json()["role"] == "shifokor"
        tasks = c.get("/api/tasks").json()
        assert tasks and all(t["role"] == "shifokor" and t["patient"]["doctor"] == "Qosimova D." for t in tasks)
        assert c.post("/api/me/password", json={"old": "demo", "new": "yangi-parol"}).status_code == 200
        c.post("/api/logout")
        assert c.get("/api/me").status_code == 401
        assert c.post("/api/login", json={"username": "shifokor", "password": "yangi-parol"}).status_code == 200


def test_phone_line_twiml_and_telegram_binding():
    from app import telegram
    from app.db import SessionLocal, User

    with TestClient(app) as c:
        p = c.get("/api/patients", params={"q": "Valiyev Amir"}).json()[0]
        call = c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "tashrif_tasdiq"}).json()
        x = c.post(f"/api/tel/{call['token']}/step?i=0").text
        assert "<Record" in x and "/audio/greeting" in x and "/audio/keldi" in x
        assert "/audio/tushunarli" in c.post(f"/api/tel/{call['token']}/answer?i=0").text  # silence -> unclear -> next question
        assert "<Hangup/>" in c.post(f"/api/tel/{call['token']}/answer?i=1").text
        assert c.post(f"/api/calls/{call['id']}/dial").status_code == 404  # already finished
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "hamshira").first()
        assert "Ulandi" in telegram.handle_update(db, {"message": {"text": "/start " + u.link_code, "chat": {"id": 777}}})
        assert telegram.recipients(db, "hamshira", "yellow") == ["777"]
        assert "topilmadi" in telegram.handle_update(db, {"message": {"text": "/start nope", "chat": {"id": 1}}})


def test_frontend_script_is_complete():
    """Every screen the router opens, and the helpers they share, must be defined in the bundle."""
    import pathlib
    import re

    js = pathlib.Path("web/app.js").read_text(encoding="utf-8")
    defined = set(re.findall(r"(?:function|const) (\w+)", js))
    assert {"home", "patient", "tasks", "calls", "voice", "about", "profile", "showLogin", "showCall", "taskRow", "callRow", "flagLabel", "obsText"} <= defined
