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
    raw = {"bp": {"value": "150/95", "quote": "bosimi 150/95"}, "hb": {"value": 90, "quote": "gemoglobin 90"},
           "complaints": [{"code": "shish", "quote": "shish bor"}, {"code": "qon_ketish", "quote": "qon ketyapti"}]}
    data, quotes, dropped = extract._clean(raw, text)
    assert data["bp_sys"] == 150 and data["complaints"] == ["shish"]
    assert "hb" in dropped and "complaints:qon_ketish" in dropped


def test_fallback_and_yes_no():
    r = extract.extract("Valiyeva Madina 1995 yil tug'ilgan, homilador, qon bosimi 160/110, boshi og'riyapti")
    assert r["data"]["bp_sys"] == 160 and "kuchli_bosh_ogrigi" in r["data"]["complaints"]
    assert extract.yes_no("yo'q, og'rimayapti") == "no"
    assert extract.yes_no("ha, bor") == "yes"
    assert extract.yes_no("нет, не было") == "no"


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
        v = c.post("/api/patients/confirm", json={"fields": {"full_name": "Test Bemor", "birth_year": 2000, "kind": "homilador", "bp_sys": 150, "bp_dia": 95,
                                                                "complaints": ["shish"]}, "transcript": "x"}).json()
        assert v["created"] and v["zone"] == "yellow"
        assert c.get(f"/api/patients/{v['id']}/referral.pdf").content[:4] == b"%PDF"


def test_negation_is_not_a_complaint():
    r = extract.extract("Mirzayeva Nodira, 2003 yil, bosimi 142/92, shish yo'q, qon ketishi kuzatilmadi")
    assert r["data"].get("complaints", []) == []
    r = extract.extract("Хамидова Озода, 1991 год, температура 38,2, кровотечение, отёков нет")
    assert r["data"]["complaints"] == ["qon_ketish"]
