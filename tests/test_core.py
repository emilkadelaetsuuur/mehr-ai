"""Run: pytest -q  (works offline: VoiceLab is not required for these tests)."""

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"  # never the real database
os.environ["DATA_DIR"] = _tmp
os.environ["VOICELAB_API_KEY"] = ""
os.environ["DEMO_PASSWORD"] = ""
# The suite also runs inside the production container: it must not inherit that environment
# (an https PUBLIC_URL makes the session cookie Secure; real tokens would reach real services).
os.environ["PUBLIC_URL"] = "http://testserver"
for _k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
    os.environ[_k] = ""

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
        c.post(f"/api/call/{call['token']}/answer", data={"qid": "emish", "value": "yes"})
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


def test_symptom_calls_alarm_only_on_yes():
    """In a symptom call the worrying answer is always "yes": a caller who says "no" to everything
    must not be told to ring 103, and a single "yes" must raise the alarm."""
    from app import core

    symptom = [s for s in core.SCENARIOS.values() if s["id"] != "tashrif_tasdiq"]  # the visit check asks "did the doctor come?"
    assert len(symptom) == 3 and all(q["flag_if"] == "yes" for s in symptom for q in s["questions"] if q["type"] == "yesno")
    with TestClient(app) as c:
        p = c.post("/api/patients/confirm", json={"fields": {"full_name": "Qo'ng'iroq Sinov", "birth_year": 1996, "kind": "homilador"}, "consent": True}).json()

        def ring(scenario, answer):
            call = c.post(f"/api/patients/{p['id']}/calls", json={"scenario": scenario}).json()
            for q in c.get(f"/api/call/{call['token']}").json()["questions"]:
                c.post(f"/api/call/{call['token']}/answer", data={"qid": q["id"], "value": answer})
            return c.post(f"/api/call/{call['token']}/finish").json()

        calm = ring("homilador", "no")
        assert not calm["alert"] and calm["flags"] == [] and calm["zone"] == "green"
        alarm = ring("homilador", "yes")
        assert alarm["alert"] and alarm["zone"] == "red" and len(alarm["flags"]) == 5
        # The patient is red now and stays red until the specialist has seen her, but what a caller hears
        # depends on the answers of that call alone.
        again = ring("homilador", "no")
        assert again["zone"] == "red" and not again["alert"]
        visit = ring("tashrif_tasdiq", "yes")
        assert visit["verified"] is True and not visit["alert"]  # a confirmed visit of a red-zone patient is not an alarm


def test_closing_words_come_from_claude_only_when_they_pass_the_checks(monkeypatch):
    """The rules decide the outcome; Claude may only word it. Whatever fails the checks is replaced by the fixed phrase."""
    from app import closing, core

    fixed_alarm = core.SCENARIOS["homilador"]["closing_alert"]["uz"]
    good = (
        "Siz bosh og'rig'i va qon ketishi haqida aytdingiz. Iltimos, hoziroq bir yuz uch raqamiga qo'ng'iroq qiling. "
        "Shifokoringizga shoshilinch xabar yuborildi."
    )
    assert closing.acceptable(good, "uz", alarm=True) is None
    assert closing.acceptable(good.replace("bir yuz uch", "tez yordam"), "uz", alarm=True) == "no emergency number"
    assert closing.acceptable(good.replace("bir yuz uch", "103"), "uz", alarm=True) == "digits"
    assert closing.acceptable("Вы сказали о головной боли, позвоните сто три прямо сейчас.", "uz", alarm=True) == "language"
    assert closing.acceptable("Rahmat.", "uz", alarm=False) == "length"

    with TestClient(app) as c:
        p = c.post(
            "/api/patients/confirm",
            json={
                "fields": {"full_name": "Yakun Sinov", "birth_year": 1995, "kind": "homilador", "phone": "+998 90 000-11-22", "mahalla": "Guliston"},
                "consent": True,
            },
        ).json()

        def ring(answer="yes"):
            call = c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).json()
            for q in c.get(f"/api/call/{call['token']}").json()["questions"]:
                c.post(f"/api/call/{call['token']}/answer", data={"qid": q["id"], "value": answer})
            return c.post(f"/api/call/{call['token']}/finish").json(), call["id"]

        def said(call_id):
            return next(x for x in c.get("/api/calls").json() if x["id"] == call_id)

        res, cid = ring()  # no key configured: the scenario's own phrase
        assert res["closing"] == fixed_alarm and said(cid)["closing_by"] == "shablon"

        seen = []
        monkeypatch.setattr(closing, "enabled", lambda: True)
        monkeypatch.setattr(closing, "ask", lambda text: seen.append(text) or good)
        res, cid = ring()
        assert res["closing"] == good and said(cid)["closing_by"] == "claude" and said(cid)["closing"] == good
        sent = seen[-1]  # the model is told the answers and the outcome, never who the patient is
        assert "Outcome: alarm" in sent and "bir yuz uch" in sent and "Qon ketishi" in sent
        assert not any(secret in sent for secret in ("Yakun Sinov", "000-11-22", "Guliston", "1995"))

        def broken(text):
            raise RuntimeError("network down")

        for bad in (lambda t: good.replace("bir yuz uch", "103"), lambda t: "Hammasi joyida, xavotir olmang, rahmat sizga!", lambda t: None, broken):
            monkeypatch.setattr(closing, "ask", bad)
            res, cid = ring()
            assert res["closing"] == fixed_alarm and said(cid)["closing_by"] == "shablon"

        # She was red before these calls, so the zone did not move; the staff still hear about every new alarm.
        notices = [n for n in c.get("/api/dashboard").json()["notices"] if n["patient_id"] == p["id"] and "yangi xavf belgilari" in n["uz"]]
        assert len(notices) >= 4 and all(n["level"] == "red" and n["role"] == "mutaxassis" for n in notices)
        assert any(t["type"] == "mutaxassis" and t["status"] == "ochiq" for t in c.get(f"/api/patients/{p['id']}").json()["tasks"])


def test_closing_writer_follows_the_language_setting(monkeypatch):
    """Claude writes only in the languages it is set for; elsewhere, and when Claude gives nothing, the VoiceLab
    model writes; if neither gives an acceptable phrase, the fixed one is spoken."""
    from types import SimpleNamespace

    from app import closing, config, core, voicelab

    uz = "Bosh og'rig'i borligini aytdingiz. Tezda bir yuz uch raqamiga qo'ng'iroq qiling. Shifokoringizga shoshilinch xabar yuborildi."
    ru = "Вы сказали о сильной головной боли. Пожалуйста, сразу позвоните по номеру сто три. Вашему врачу отправлено срочное сообщение."
    res = {"alert": True, "verified": None}

    def call(lang):
        return SimpleNamespace(scenario="homilador", lang=lang, flags=["kuchli_bosh_ogrigi"], answers={"bosh": {"value": "yes", "transcript": "Ha."}})

    monkeypatch.setattr(closing, "enabled", lambda: True)
    monkeypatch.setattr(voicelab, "enabled", lambda: True)
    monkeypatch.setattr(config, "CLAUDE_LANGS", ["ru"])
    monkeypatch.setattr(closing, "ask", lambda text: ru)
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: uz)
    assert [n for n, _ in closing.writers("uz")] == ["voicelab"] and [n for n, _ in closing.writers("ru")] == ["claude", "voicelab"]
    assert closing.compose(call("uz"), res) == (uz, "voicelab")
    assert closing.compose(call("ru"), res) == (ru, "claude")
    monkeypatch.setattr(closing, "ask", lambda text: None)  # Claude is late or declined: the next writer is asked
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: ru)
    assert closing.compose(call("ru"), res) == (ru, "voicelab")
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: "Hammasi yaxshi.")  # fails the checks
    assert closing.compose(call("uz"), res) == (core.SCENARIOS["homilador"]["closing_alert"]["uz"], "shablon")


def test_claude_request_fits_a_gateway(monkeypatch):
    """Straight to Anthropic the request uses the API's own fallback; behind a gateway it is the plain Messages
    request, and a field the gateway refuses is dropped and not sent again."""
    import pytest

    anthropic = pytest.importorskip("anthropic")
    import httpx2

    from app import closing

    class Recorder:
        def __init__(self, refuse=()):
            self.calls, self.refuse = [], refuse
            self.messages = self.beta = self
            self.beta.messages = self

        def create(self, **kw):
            self.calls.append(sorted(kw))
            if any(k in kw for k in self.refuse):
                bad = httpx2.Response(400, request=httpx2.Request("POST", "https://gateway.example/v1/messages"))
                raise anthropic.BadRequestError("unknown field", response=bad, body=None)
            return "ok"

    monkeypatch.setitem(closing._state, "plain", False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    c = Recorder()
    assert closing.direct() and closing._send(c, "x") == "ok" and "fallbacks" in c.calls[0] and "betas" in c.calls[0]

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    c = Recorder()
    assert not closing.direct() and closing._send(c, "x") == "ok"
    assert "fallbacks" not in c.calls[0] and "betas" not in c.calls[0] and "output_config" in c.calls[0]

    c = Recorder(refuse=("output_config",))
    assert closing._send(c, "x") == "ok" and len(c.calls) == 2 and "output_config" not in c.calls[1]
    assert closing._send(c, "x") == "ok" and len(c.calls) == 3 and "output_config" not in c.calls[2]  # remembered


def test_sign_in_forgives_paste_noise_but_not_a_wrong_password(monkeypatch):
    from app import auth, config

    with TestClient(app) as c:
        monkeypatch.setattr(config, "DEMO_PASSWORD", "yoqilgan")  # auth on; demo accounts were created with "demo"
        auth._failures.clear()
        # spaces and invisible characters around a pasted password are ignored; the account name ignores case
        assert c.post("/api/login", json={"username": " Rahbar ", "password": "  demo​ \n"}).status_code == 200
        assert c.get("/api/me").json()["role"] == "rahbar"
        c.post("/api/logout")
        for bad in ("Demo", "пароль", "", "demo1"):  # letter case matters; non-ASCII is a wrong password, not a crash
            assert c.post("/api/login", json={"username": "rahbar", "password": bad}).status_code == 401
        assert c.post("/api/login", json={"username": "nobody", "password": "demo"}).status_code == 401
        for stale in ("eski-versiya-cookie", "1.2.3", "1.99999999999.0000"):  # foreign or forged cookies never sign in
            c.cookies.set("nigoh_auth", stale)
            assert c.get("/api/me").status_code == 401
        c.cookies.clear()
        auth._failures.clear()
        for _ in range(auth.MAX_FAILURES):  # a burst of wrong passwords is slowed down...
            assert c.post("/api/login", json={"username": "rahbar", "password": "xato"}).status_code == 401
        assert c.post("/api/login", json={"username": "rahbar", "password": "demo"}).status_code == 429
        auth._failures.clear()  # ...and the window passes
        assert c.post("/api/login", json={"username": "rahbar", "password": "demo"}).status_code == 200


def test_roles_limit_what_an_account_may_do():
    with TestClient(app) as c:
        nurse, doctor = {"X-Role": "hamshira"}, {"X-Role": "shifokor"}  # the demo family doctor is Qosimova D.
        mine = c.get("/api/patients", params={"q": "Valiyeva Madina"}).json()[0]
        other = next(p for p in c.get("/api/patients").json() if p["doctor"] not in (None, "Qosimova D.") and p["kind"] == "homilador")
        t_mine = c.post(f"/api/patients/{mine['id']}/discharge", json={}).json()
        t_other = c.post(f"/api/patients/{other['id']}/discharge", json={}).json()
        assert c.post("/api/demo/reset", headers=nurse).status_code == 403
        assert c.post("/api/import/lab", json={"csv": "full_name,hb\nX,100"}, headers=nurse).status_code == 403
        assert c.get("/api/audit", headers=nurse).status_code == 403
        assert c.get(f"/api/audit?patient_id={mine['id']}", headers=nurse).status_code == 200
        assert c.post(f"/api/tasks/{t_mine['id']}/done", json={}, headers=nurse).status_code == 403  # not the nurse's task
        assert c.post(f"/api/tasks/{t_other['id']}/done", json={}, headers=doctor).status_code == 403  # another doctor's patient
        assert c.post(f"/api/tasks/{t_mine['id']}/done", json={}, headers=doctor).status_code == 200
        assert c.post(f"/api/tasks/{t_other['id']}/done", json={}).status_code == 200  # the head of the district may close any
        # a laboratory row with an impossible value is reported, not stored
        res = c.post("/api/import/lab", json={"csv": "full_name,hb\nValiyeva Madina,999\nValiyeva Madina,abc"}).json()
        assert res["matched"] == 0 and res["invalid"] == ["Valiyeva Madina", "Valiyeva Madina"]


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
