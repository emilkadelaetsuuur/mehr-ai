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
for _k in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_FROM",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "GATEWAY_KEY",
    "CLINIC_PHONE",
):
    os.environ[_k] = ""
for _k in ("ANTHROPIC_BASE_URL", "CLAUDE_MODEL", "CLAUDE_LANGS", "CLAUDE_CLOSING", "CLAUDE_TIMEOUT", "VOICELAB_CLOSING"):
    os.environ.pop(_k, None)  # the server's choice of model and languages is not what the tests are about

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


def test_a_message_goes_to_the_person_the_patient_is_attached_to():
    """At the end of a call the patient may leave a message. It becomes a task with a deadline for the family
    doctor named on the card (the nurse when there is none); warning signs in it go the usual red-zone road."""
    from app import extract

    assert (
        extract.wants_human("Operator bilan gaplashmoqchiman")
        and extract.wants_human("позовите оператора")
        and not extract.wants_human("Yo'q, bosh og'rimayapti")
    )
    with TestClient(app) as c:
        doctor, nurse = {"X-Role": "shifokor"}, {"X-Role": "hamshira"}  # the demo family doctor is Qosimova D.

        def patient(name, **extra):
            return c.post(
                "/api/patients/confirm", json={"fields": {"full_name": name, "birth_year": 1997, "kind": "homilador", **extra}, "consent": True}
            ).json()

        def call(p):
            return c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).json()

        def tasks(headers, pid, kind):
            return [t for t in c.get("/api/tasks", headers=headers).json() if t["patient"]["id"] == pid and t["type"] == kind]

        mine, orphan = patient("Murojaat Sinov", doctor="Qosimova D."), patient("Shifokorsiz Sinov")
        k = call(mine)
        said = "Kechqurun oyoqlarim og'riyapti, qachon qabulga kelsam bo'ladi?"
        r = c.post(f"/api/call/{k['token']}/appeal", data={"text": said}).json()
        assert r["ok"] and r["to"] == "shifokor" and r["doctor"] == "Qosimova D." and not r["urgent"]
        (t,) = tasks(doctor, mine["id"], "murojaat")  # her own doctor sees it, with a deadline
        assert t["status"] == "ochiq" and t["reason"] == said and not tasks(nurse, mine["id"], "murojaat")
        res = c.post(f"/api/call/{k['token']}/finish").json()
        assert not res["alert"] and "murojaat" in res["flags"]
        card = c.get(f"/api/patients/{mine['id']}").json()
        assert card["zone"] == "green" and any(o["source"] == "murojaat" and o["text"] == said for o in card["observations"])
        assert c.post(f"/api/tasks/{t['id']}/done", json={"note": "Qo'ng'iroq qildim"}, headers=doctor).status_code == 200

        k = call(orphan)  # no doctor on the card: the patronage nurse
        assert c.post(f"/api/call/{k['token']}/appeal", data={"text": "Dori qachon tugashini bilmoqchi edim."}).json()["to"] == "hamshira"
        assert tasks(nurse, orphan["id"], "murojaat") and c.post(f"/api/call/{k['token']}/appeal", data={"text": " "}).json() == {"ok": False}

        k = call(mine)  # a warning sign inside the message: red zone and the specialist, whoever she is attached to
        r = c.post(f"/api/call/{k['token']}/appeal", data={"text": "Bugun ertalabdan qon ketyapti, qo'rqyapman."}).json()
        assert r["urgent"] and r["to"] == "shifokor"
        for q in c.get(f"/api/call/{k['token']}").json()["questions"]:
            c.post(f"/api/call/{k['token']}/answer", data={"qid": q["id"], "value": "no"})
        res = c.post(f"/api/call/{k['token']}/finish").json()
        assert res["alert"] and res["zone"] == "red" and "qon_ketish" in res["flags"]
        assert tasks({"X-Role": "mutaxassis"}, mine["id"], "mutaxassis")
        assert c.post(f"/api/call/{k['token']}/appeal", data={"text": "yana bir gap"}).status_code == 400  # the call is over

        # After the caller has been answered the language model reads the message again; a warning sign the
        # keyword lists missed still reaches the zone rules and the person she is attached to.
        from app import core, extract
        from app.db import Call, SessionLocal

        k = call(orphan)
        said = "Tunda yomon ahvolga tushdim"
        assert c.post(f"/api/call/{k['token']}/appeal", data={"text": said}).json()["urgent"] is False
        with SessionLocal() as db:
            kk = db.query(Call).filter(Call.token == k["token"]).first()
            old_signs, extract.signs = extract.signs, lambda text, quick=False: [] if quick else ["hushdan_ketish"]
            try:
                assert core.appeal_review(db, kk, said) == ["hushdan_ketish"]
            finally:
                extract.signs = old_signs
            db.commit()
        assert c.get(f"/api/patients/{orphan['id']}").json()["zone"] == "red"


def test_a_caller_can_ask_for_a_person():
    """Asking for an operator ends the questions: staff get a task to ring back within the promised time;
    the nurse for an ordinary patient, the specialist for one in the red zone."""
    from app import dialogue

    with TestClient(app) as c:
        p = c.post("/api/patients/confirm", json={"fields": {"full_name": "Operator Sinov", "birth_year": 1999, "kind": "homilador"}, "consent": True}).json()

        def ask_for_person():
            k = c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).json()
            first = c.get(f"/api/call/{k['token']}").json()
            assert first["say"]["operator_ok"] and first["say"]["appeal_q"]
            c.post(f"/api/call/{k['token']}/answer", data={"qid": first["questions"][0]["id"], "value": "no"})
            r = c.post(f"/api/call/{k['token']}/operator", data={"said": "Operator bilan gaplashmoqchiman"}).json()
            res = c.post(f"/api/call/{k['token']}/finish?quiet=1").json()  # answers so far are kept, no closing is composed
            return r, res

        r, res = ask_for_person()
        assert r["ok"] and r["role"] == "hamshira" and r["minutes"] == dialogue.CALLBACK_MINUTES == 30
        assert "operator" in res["flags"] and res["closing_parts"] is None
        (t,) = [x for x in c.get("/api/tasks", headers={"X-Role": "hamshira"}).json() if x["patient"]["id"] == p["id"]]
        assert t["type"] == "qayta_qongiroq" and t["status"] == "ochiq"
        c.post(f"/api/patients/{p['id']}/observations", json={"bp_sys": 172, "bp_dia": 114})  # she is in the red zone now
        r, _ = ask_for_person()
        assert r["role"] == "mutaxassis"


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
    assert [w[0] for w in closing.writers("uz")] == ["voicelab"] and [w[0] for w in closing.writers("ru")] == ["claude", "voicelab"]
    assert closing.compose(call("uz"), res) == (uz, "voicelab")
    assert closing.compose(call("ru"), res) == (ru, "claude")
    monkeypatch.setattr(closing, "ask", lambda text: None)  # Claude is late or declined: the next writer is asked
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: ru)
    assert closing.compose(call("ru"), res) == (ru, "voicelab")
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: "Hammasi yaxshi.")  # fails the checks
    assert closing.compose(call("uz"), res) == (core.SCENARIOS["homilador"]["closing_alert"]["uz"], "shablon")


def test_a_slow_writer_cannot_hold_the_caller(monkeypatch):
    """A writer gets a fixed time by the clock; when it is late the next one is asked, and at the end the fixed phrase."""
    import time
    from types import SimpleNamespace

    from app import closing, config, core, voicelab

    ru = "Вы сказали о сильной головной боли. Пожалуйста, сразу позвоните по номеру сто три. Вашему врачу отправлено срочное сообщение."
    call = SimpleNamespace(scenario="homilador", lang="ru", flags=["kuchli_bosh_ogrigi"], answers={"bosh": {"value": "yes", "transcript": "Да."}})
    res = {"alert": True, "verified": None}
    monkeypatch.setattr(closing, "enabled", lambda: True)
    monkeypatch.setattr(voicelab, "enabled", lambda: True)
    monkeypatch.setattr(config, "CLAUDE_TIMEOUT", 0.3)
    monkeypatch.setattr(config, "VOICELAB_CLOSING_TIMEOUT", 0.3)
    monkeypatch.setattr(closing, "ask", lambda text: time.sleep(2) or ru)  # a gateway that keeps the connection open
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: ru)
    t0 = time.time()
    assert closing.compose(call, res) == (ru, "voicelab") and time.time() - t0 < 1.5
    monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: time.sleep(2) or ru)
    t0 = time.time()
    assert closing.compose(call, res) == (core.SCENARIOS["homilador"]["closing_alert"]["ru"], "shablon") and time.time() - t0 < 1.5

    assert closing.sentences("Rahmat sizga katta. Javoblaringiz yuborildi! Ha.") == ["Rahmat sizga katta.", "Javoblaringiz yuborildi! Ha."]
    assert closing.sentences("") == [] and closing.sentences(None) == []


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


def test_phone_line_dialogue_and_telegram_binding(monkeypatch):
    """The provider's requests, step by step, as a real call would send them (no provider, no speech service)."""
    from app import telegram, telephony
    from app.db import SessionLocal, User

    assert telephony.number("90 123-45-67") == "+998901234567" and telephony.number("+998 (91) 234-56-78") == "+998912345678" and telephony.number("12") is None
    with TestClient(app) as c:
        p = c.post(
            "/api/patients/confirm",
            json={"fields": {"full_name": "Telefon Sinov", "birth_year": 1998, "kind": "tuqqan", "doctor": "Qosimova D."}, "consent": True},
        ).json()

        def ring():
            return c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "tashrif_tasdiq"}).json()

        def tel(k, step, **form):
            return c.post(f"/api/tel/{k['token']}/{step}", data=form).text

        k = ring()
        x = tel(k, "step?i=0")  # answered: greeting, how to reach a person, the first question, then listening
        assert all(part in x for part in ("/audio/greeting", "/audio/say_hint", "/audio/keldi", "<Record", "answer?i=0"))
        x = tel(k, "answer?i=0")  # silence: one more try, by keys
        assert "/audio/say_retry_keys" in x and "<Gather" in x and "key?i=0" in x
        x = tel(k, "key?i=0", Digits="1")  # "yes, the doctor came": a short reaction and the next question
        assert "/audio/say_ack" in x and "/audio/tushunarli" in x and "answer?i=1" in x
        x = tel(k, "key?i=1", Digits="1")  # the last question: now the offer to leave a message
        assert "/audio/say_appeal_q" in x and "offered" in x
        monkeypatch.setattr(telephony, "heard", lambda url, lang: "Ha, aytmoqchiman" if "offer" in url else "Bolam kechasi yaxshi uxlamayapti, maslahat kerak.")
        x = tel(k, "offered", RecordingUrl="https://provider.example/offer")
        assert "/audio/say_appeal_go_line" in x and 'playBeep="true"' in x and "message" in x
        x = tel(k, "message", RecordingUrl="https://provider.example/message")  # the message goes to her family doctor
        assert "/audio/say_appeal_ok<" in x and "closing" in x
        assert "<Hangup/>" in tel(k, "closing") and "/audio/closing_ok" in tel(ring(), "closing")
        mine = [t for t in c.get("/api/tasks", headers={"X-Role": "shifokor"}).json() if t["patient"]["id"] == p["id"] and t["type"] == "murojaat"]
        assert len(mine) == 1 and "uxlamayapti" in mine[0]["reason"]
        done = next(x for x in c.get("/api/calls").json() if x["id"] == k["id"])
        assert done["status"] == "tugadi" and "murojaat" in done["flags"] and done["answers"]["keldi"]["value"] == "yes"
        assert c.post(f"/api/calls/{k['id']}/dial", json={}).status_code == 404  # already finished

        k = ring()  # "operator" by key 0: staff must ring back, the call ends politely
        tel(k, "step?i=0")
        x = tel(k, "key?i=0", Digits="0")
        assert "/audio/say_operator_ok" in x and "<Hangup/>" in x and "<Dial" not in x
        assert [t for t in c.get("/api/tasks", headers={"X-Role": "hamshira"}).json() if t["patient"]["id"] == p["id"] and t["type"] == "qayta_qongiroq"]
        monkeypatch.setattr(telephony.config, "CLINIC_PHONE", "71 200-00-00")  # with the polyclinic's number the call is put through
        k = ring()
        x = tel(k, "key?i=0", Digits="0")
        assert "/audio/say_operator_dial" in x and "<Dial" in x and "+998712000000" in x

        k = ring()  # the line dropped after one answer: what was said is kept
        tel(k, "key?i=0", Digits="2")
        tel(k, "status", CallStatus="completed")
        assert next(x for x in c.get("/api/calls").json() if x["id"] == k["id"])["status"] == "tugadi"
        assert c.post(f"/api/calls/{ring()['id']}/dial", json={"phone": "901234567"}).status_code == 409  # no provider configured
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "hamshira").first()
        assert "Ulandi" in telegram.handle_update(db, {"message": {"text": "/start " + u.link_code, "chat": {"id": 777}}})
        assert telegram.recipients(db, "hamshira", "yellow") == ["777"]
        assert "topilmadi" in telegram.handle_update(db, {"message": {"text": "/start nope", "chat": {"id": 1}}})


def test_a_calling_round_reaches_only_those_it_may():
    """A round rings the patients a scenario is written for who gave consent, the most worrying first, never
    twice; a trial call goes to the prepared patient and is not piled up by pressing the button again."""
    with TestClient(app) as c:
        a = c.get("/api/calls/audience", params={"scenario": "homilador"}).json()
        assert a["who"] == "homilador" and a["fit"] > 0
        red = c.get("/api/calls/audience", params={"scenario": "homilador", "zone": "red"}).json()["fit"]
        assert 0 < red < a["fit"]
        made = c.post("/api/calls/round", json={"scenario": "homilador", "lang": "ru", "zone": "red", "limit": 5}).json()["calls"]
        assert len(made) == min(5, red) and all(x["status"] == "rejalashtirilgan" and x["scenario"] == "homilador" for x in made)
        ids = {x["patient"]["id"] for x in made}
        assert len(ids) == len(made)  # one call each
        assert all(c.get(f"/api/patients/{i}").json()["zone"] == "red" for i in ids)
        after = c.get("/api/calls/audience", params={"scenario": "homilador", "zone": "red"}).json()
        assert after["fit"] == red - len(made) and after["already"] >= len(made)  # they are not rung twice
        assert c.post("/api/calls/round", json={"scenario": "yoq"}).status_code == 400

        one = c.post("/api/calls/round", json={"scenario": "chaqaloq_30kun", "lang": "uz", "test": True}).json()["calls"]
        assert len(one) == 1 and one[0]["patient"]["name"] == "Valiyev Amir" and one[0]["url"].endswith(one[0]["token"])
        again = c.post("/api/calls/round", json={"scenario": "chaqaloq_30kun", "test": True}).json()["calls"]
        assert again[0]["id"] == one[0]["id"]  # the same unfinished call, not a new one each time
        assert c.get(f"/api/call/{one[0]['token']}").json()["questions"]  # the link the QR code holds opens the call


def test_a_phone_with_a_sim_card_as_the_line(monkeypatch):
    """Staff ask for a call; the rig next to the phone takes it, reports what happens on the line, and three
    unanswered attempts become a home visit, as with any other call."""
    from app import config, simline

    with TestClient(app) as c:
        p = c.post(
            "/api/patients/confirm",
            json={"fields": {"full_name": "SIM Sinov", "birth_year": 1996, "kind": "homilador", "phone": "+998 90 111-22-33"}, "consent": True},
        ).json()
        k = c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador"}).json()
        assert c.post(f"/api/calls/{k['id']}/sim", json={}).status_code == 409 and c.get("/api/meta").json()["sim"] is False  # no rig set up
        monkeypatch.setattr(config, "GATEWAY_KEY", "kalit")
        rig = {"X-Gateway-Key": "kalit"}
        assert c.get("/api/gateway/next").status_code == 403 and c.get("/api/gateway/next", headers={"X-Gateway-Key": "boshqa"}).status_code == 403
        assert c.post(f"/api/calls/{k['id']}/sim", json={}).status_code == 409  # the rig has not shown up yet
        assert c.get("/api/gateway/next", headers=rig).json() == {"call": None} and c.get("/api/meta").json()["sim_online"]
        assert c.post(f"/api/calls/{k['id']}/sim", json={"phone": "12"}).status_code == 400
        assert c.post(f"/api/calls/{k['id']}/sim", json={"phone": "93 555-66-77"}).json() == {"queued": True, "to": "+998935556677"}
        job = c.get("/api/gateway/next", headers=rig).json()["call"]
        assert job == {"token": k["token"], "phone": "+998935556677", "lang": "uz"} and c.get("/api/gateway/next", headers=rig).json()["call"] is None
        # The call page is opened while the phone still rings: it gets ready and waits for the pick-up.
        c.post(f"/api/call/{k['token']}/line", data={"state": "ready"})
        assert c.get(f"/api/call/{k['token']}/line").json() == {"go": False}
        c.post("/api/gateway/report", json={"token": k["token"], "state": "go"}, headers=rig)  # she picked up
        assert c.get(f"/api/call/{k['token']}/line").json() == {"go": True}
        c.post(f"/api/call/{k['token']}/line", data={"state": "talking"})
        assert c.get("/api/gateway/state", params={"token": k["token"]}, headers=rig).json() == {"state": "talking", "rig": "go"}
        c.post(f"/api/call/{k['token']}/line", data={"state": "done"})
        assert c.get("/api/gateway/state", params={"token": k["token"]}, headers=rig).json()["state"] == "done"
        for _ in range(3):  # nobody picks up, three times
            c.post("/api/gateway/report", json={"token": k["token"], "state": "noanswer"}, headers=rig)
        assert next(x for x in c.get("/api/calls").json() if x["id"] == k["id"])["status"] == "javobsiz"
        assert [t for t in c.get("/api/tasks", headers={"X-Role": "hamshira"}).json() if t["patient"]["id"] == p["id"] and t["type"] == "hamshira_tashrif"]
        simline._seen["at"] = 0  # the rig is gone


def test_a_call_names_the_patient_and_answers_her_questions_from_the_leaflet(monkeypatch):
    """The call greets the patient by name and goes on only after her "yes". Her own question is answered
    when a model words an answer from the leaflet and names the notes it used; anything else goes to her
    doctor as a message. A warning sign in her words never waits for a model."""
    import re
    import time
    from types import SimpleNamespace

    from app import closing, talk, voicelab

    assert talk.spoken("Sodiqova Dilnoza", "uz") == "Dilnoza Sodiqova" and talk.spoken("Sodiqova Dilnoza", "ru") == "Дилноза Содикова"
    assert talk.cyrillic("Jo'rayev Elyor") == "Джураев Элёр" and talk.cyrillic("O'g'iloy") == "Угилой"
    assert talk.short("Yo'q, rahmat") == "none" and talk.short("Ha, savolim bor") == "go" and talk.short("Молока нет") is None
    # every note names its document and is written for the voice: no digits
    assert all(n["src"] in talk.ADVICE["sources"] and n["who"] and not re.search(r"\d", n["uz"] + n["ru"]) for n in talk.ADVICE["notes"])
    assert talk.notes("homilador") and talk.notes("chaqaloq") and not talk.notes("boshqa")

    baby, mother = SimpleNamespace(kind="chaqaloq", mother_id=7, full_name="Valiyev Amir"), SimpleNamespace(full_name="Valiyeva Madina")
    db = SimpleNamespace(get=lambda model, pk: mother if pk == 7 else None)
    hello, intro = talk.opening(db, SimpleNamespace(patient=baby, lang="uz", scenario="chaqaloq_30kun"))  # a call about a newborn is a call to the mother
    assert "Men Madina Valiyeva bilan gaplashyapmanmi?" in hello and intro.startswith("Rahmat, Madina opa. Chaqalog'ingiz haqida")
    baby.mother_id = None
    assert "Amir Valiyev — sizning farzandingizmi?" in talk.opening(db, SimpleNamespace(patient=baby, lang="uz", scenario="chaqaloq_30kun"))[0]

    with TestClient(app) as c:
        card = {"full_name": "Karimova Zilola", "birth_year": 1996, "kind": "homilador", "doctor": "Qosimova D.", "phone": "+998 90 111-22-33"}
        p = c.post("/api/patients/confirm", json={"fields": card, "consent": True}).json()

        def call(lang=None):
            return c.post(f"/api/patients/{p['id']}/calls", json={"scenario": "homilador", **({"lang": lang} if lang else {})}).json()

        def ask(k, text):
            return c.post(f"/api/call/{k['token']}/ask", data={"text": text}).json()

        def row(k):
            return next(x for x in c.get("/api/calls").json() if x["id"] == k["id"])

        def messages():
            return [t for t in c.get("/api/tasks", headers={"X-Role": "shifokor"}).json() if t["patient"]["id"] == p["id"] and t["type"] == "murojaat"]

        k = call()
        info = c.get(f"/api/call/{k['token']}").json()
        assert "Men Zilola Karimova bilan gaplashyapmanmi?" in info["hello"] and info["intro"].startswith("Rahmat, Zilola opa. Sog'lig'ingiz haqida")
        ru = c.get(f"/api/call/{call('ru')['token']}").json()
        assert "вы — Зилола Каримова?" in ru["hello"] and ru["intro"].startswith("Спасибо, Зилола. Задам")

        # somebody else picked up: nothing more is said, the call stays planned and counts as an attempt
        assert c.post(f"/api/call/{k['token']}/identity", data={"value": "no"}).json()["value"] == "no"
        assert row(k)["status"] == "rejalashtirilgan" and row(k)["attempts"] == 1 and row(k)["answers"]["shaxs"]["value"] == "no"
        assert c.post(f"/api/call/{k['token']}/identity", data={"value": "yes"}).json()["value"] == "yes"
        assert row(k)["status"] == "jarayonda" and row(k)["answers"]["shaxs"]["value"] == "yes"

        # replies that are not questions
        assert ask(k, "Yo'q, rahmat")["kind"] == "none" and ask(k, "Operator bilan gaplashmoqchiman")["kind"] == "operator" and ask(k, " ")["kind"] == "unclear"
        # no model at hand: the machine does not answer, the question goes to her own doctor
        r = ask(k, "Homiladorlikda qanday ovqatlanishim kerak?")
        assert r["kind"] == "doctor" and r["to"] == "shifokor" and r["doctor"] == "Qosimova D." and r["answer"] is None and len(messages()) == 1

        # a model words the answer from the leaflet and names the note it used
        seen = []
        good = "[1] Ovqatingiz xilma-xil bo'lsin: sabzavot, meva, go'sht yoki baliq, tuxum va sut mahsulotlari. Kam-kamdan, tez-tez ovqatlaning."
        monkeypatch.setattr(voicelab, "enabled", lambda: True)
        monkeypatch.setattr(voicelab, "chat", lambda messages, **kw: seen.append(messages) or good)
        r = ask(k, "Homiladorlikda qanday ovqatlanishim kerak?")
        assert r["kind"] == "answer" and r["by"] == "voicelab" and r["answer"].startswith("Ovqatingiz") and r["to"] is None
        assert r["parts"] == closing.sentences(r["answer"]) and r["source"] == [talk.ADVICE["sources"]["anc"]["uz"]]
        system, question = seen[-1][0]["content"], seen[-1][1]["content"]
        assert "1. Homiladorlikda ovqat" in system and "a pregnant woman" in system and "ovqatlanishim" in question
        assert not any(secret in system + question for secret in ("Zilola", "Karimova", "111-22-33", "1996"))  # the model is not told who she is
        assert len(messages()) == 1  # answered: nothing new for the doctor
        with monkeypatch.context() as m:  # she is waiting: the first acceptable answer wins, a slow writer is not waited for
            m.setattr(closing, "enabled", lambda: True)
            m.setattr(closing, "ask", lambda text, system=None: time.sleep(2) or good)
            t0 = time.time()
            assert talk.compose("homilador", "uz", "Qanday ovqatlanishim kerak?")[1] == "voicelab" and time.time() - t0 < 1.5

        # an answer that names no note, carries digits, or says "not in the leaflet" is never spoken
        for bad in (
            "Ovqatingiz xilma-xil bo'lsin, sabzavot va meva yeng, kam-kamdan va tez-tez ovqatlaning.",
            "[1] Kuniga 3 marta ovqatlaning va 2 litr suv iching, bu siz uchun juda muhim narsa.",
            "TOPILMADI",
            None,
        ):
            monkeypatch.setattr(voicelab, "chat", lambda messages, bad=bad, **kw: bad)
            r = ask(k, "Qaysi vitaminni ichsam bo'ladi?")
            assert r["kind"] == "doctor" and r["answer"] is None
        said = row(k)["answers"]["suhbat"]["items"]  # the whole exchange stays in the call's record
        assert [x["kind"] for x in said] == ["doctor", "answer"] + ["doctor"] * 4 and said[1]["notes"] == ["ovqat"] and said[1]["by"] == "voicelab"
        assert ask(k, "Yana bitta savolim bor edi, aytsam maylimi?")["kind"] == "none"  # the lid on questions in one call

        # a warning sign in her words: no model is asked, the alarm goes the usual red road
        asked = []
        monkeypatch.setattr(talk, "compose", lambda *a: asked.append(a) or (None, None, []))
        k = call()
        r = ask(k, "Ertalabdan beri qon ketyapti, nima qilay?")
        assert r["kind"] == "alarm" and r["to"] == "shifokor" and not asked
        for q in c.get(f"/api/call/{k['token']}").json()["questions"]:
            c.post(f"/api/call/{k['token']}/answer", data={"qid": q["id"], "value": "no"})
        res = c.post(f"/api/call/{k['token']}/finish").json()
        assert res["alert"] and res["zone"] == "red" and "qon_ketish" in res["flags"]
        assert c.post(f"/api/call/{k['token']}/ask", data={"text": "yana bir savol"}).status_code == 400  # the call is over


def test_a_runaway_tab_is_told_to_sign_in_again(monkeypatch):
    """A tab that asks for one list far more often than any screen does (an old copy of the interface whose
    timers piled up) is told to sign in again: that makes the interface drop its timers. Other lists, other
    browsers are not affected, and a minute later the list opens again."""
    from app import config, main

    key = ("browser-a", "/api/calls")
    assert not any(main.runaway(key, now=100 + i / 100) for i in range(main.RUNAWAY))  # no screen comes near this
    assert main.runaway(key, now=101) and main.runaway(key, now=105)
    assert not main.runaway(("browser-b", "/api/calls"), now=105) and not main.runaway(("browser-a", "/api/tasks"), now=105)
    assert main.runaway(key, now=100 + main.WINDOW + 5)  # still closed: a timer that survived must meet a refusal too
    assert not main.runaway(key, now=102 + main.CLOSED)  # a minute later the list opens again

    with TestClient(app) as c:
        monkeypatch.setattr(config, "DEMO_PASSWORD", "yoqilgan")
        assert c.post("/api/login", json={"username": "hamshira", "password": "demo"}).status_code == 200
        codes = [c.get("/api/calls").status_code for _ in range(main.RUNAWAY + 5)]
        assert codes[: main.RUNAWAY] == [200] * main.RUNAWAY and codes[-1] == 401
        assert c.get("/api/calls").json() == {"detail": "reload"}
        assert c.get("/api/tasks").status_code == 200 and c.get("/api/me").status_code == 200  # only the flooded list is closed


def test_frontend_script_is_complete():
    """Every screen the router opens, and the helpers they share, must be defined in the bundle."""
    import pathlib
    import re

    js = pathlib.Path("web/app.js").read_text(encoding="utf-8")
    # A screen redraws itself, so its refresh timer must be replaced, never added: timers that pile up double
    # the requests on every tick (a tab left open took the site down this way).
    assert "S.timers.push" not in js and js.count("refreshEvery(") == 5
    defined = set(re.findall(r"(?:function|const) (\w+)", js))
    assert {"home", "patient", "tasks", "calls", "voice", "about", "profile", "showLogin", "showCall", "taskRow", "callRow", "flagLabel", "obsText"} <= defined
