"""Synthetic district: some four hundred invented patients. No real personal data is used anywhere."""

import random
import secrets
from datetime import timedelta

from . import core, dmed, exchange, vaccines
from .db import Call, DmedMessage, Hospitalization, Notice, Observation, Patient, RiskEvent, Task, Vaccination

F = [
    "Dilnoza",
    "Madina",
    "Gulnora",
    "Nilufar",
    "Zarina",
    "Shahnoza",
    "Malika",
    "Feruza",
    "Nodira",
    "Sevara",
    "Kamola",
    "Mohira",
    "Dildora",
    "Umida",
    "Nargiza",
    "Barno",
    "Lola",
    "Ozoda",
    "Munisa",
    "Shoira",
    "Iroda",
    "Zilola",
    "Maftuna",
    "Gulshan",
]
L = [
    "Karimova",
    "Yusupova",
    "Rahimova",
    "Tosheva",
    "Abdullayeva",
    "Ismoilova",
    "Nazarova",
    "Qodirova",
    "Saidova",
    "Ergasheva",
    "Xolmatova",
    "Mirzayeva",
    "Sobirova",
    "Normatova",
    "Hamidova",
    "Jo'rayeva",
    "Aliyeva",
    "Usmonova",
    "Sultonova",
    "Boboyeva",
]
BOYS = ["Amir", "Imron", "Mustafo", "Muhammadali", "Bilol", "Abdulloh", "Yusuf", "Umar"]
GIRLS = ["Soliha", "Muslima", "Hadicha", "Oisha", "Mubina", "Safiya", "Zaynab", "Maryam"]
MAHALLA = ["Navbahor", "Bog'ishamol", "Guliston", "Istiqlol", "Do'stlik", "Yangiobod", "Tinchlik", "Obod", "Nurafshon", "Mehnatobod"]
DOCS = ["Rahmonov B.", "Xudoyberdiyeva M.", "Tursunov A.", "Qosimova D.", "Aliyev S."]
MEN = ["Sardor", "Botir", "Jasur", "Otabek", "Rustam", "Sherzod", "Farhod", "Anvar", "Dilshod", "Aziz", "Bekzod", "Sanjar"]
FIXED = ("Sodiqova Dilnoza", "Valiyeva Madina", "Valiyev Amir", "Karimova Nilufar", "Karimov Yusuf", "Rahimov Botir", "Toshmatov Sardor")
# dispensary groups of the invented adults, and the diagnosis code each group stands for
FOLLOWED = ["oiv"] * 5 + ["jyb"] * 4 + ["sil"] * 5 + ["gepatit"] * 4 + ["diabet"] * 7 + ["gipertoniya"] * 8
CODE = {"oiv": "B20", "jyb": "A54", "sil": "A15", "gepatit": "B18", "diabet": "E11", "gipertoniya": "I11"}


def run(db, n=300, seed=7):
    rnd = random.Random(seed)
    for model in (DmedMessage, Vaccination, Hospitalization, Notice, Call, Task, RiskEvent, Observation, Patient):
        db.query(model).delete()
    db.commit()
    now = core.now()
    used = set(FIXED)

    def pinfl():
        return "".join(str(rnd.randint(0, 9)) for _ in range(14))

    def phone():
        return f"+998 9{rnd.randint(0, 9)} {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}"

    def give(child, share, only=None):
        """The doses whose day has come, most of them given: recorded as a vaccination room would record them."""
        for d in vaccines.CALENDAR["doses"]:
            due = child.born_at + timedelta(days=vaccines.AGES[d["age"]]["days"])
            if (d.get("who") and d["who"] != child.sex) or due > now or (only is not None and d["age"] not in only) or rnd.random() >= share:
                continue
            when = min(now, due + timedelta(days=rnd.randint(0, 9)))
            db.add(Vaccination(patient_id=child.id, code=d["id"], done_at=when, source="dmed", confirmed=True, created_at=when))

    def name():
        while True:
            s = f"{rnd.choice(L)} {rnd.choice(F)}"
            if s not in used:
                used.add(s)
                return s

    def obs(p, days_ago, source, data, text=""):
        o = Observation(
            patient=p, source=source, data=data, quotes={}, text=text, author="seed", created_at=now - timedelta(days=days_ago, hours=rnd.randint(0, 9))
        )
        db.add(o)

    patients = []
    for i in range(n):
        kind = "homilador" if i < 215 else ("tuqqan" if i < 250 else "chaqaloq")
        mah = rnd.choice(MAHALLA)
        boy = False
        if kind == "chaqaloq":
            mother = rnd.choice([x for x in patients if x.kind == "tuqqan"])
            born = now - timedelta(days=rnd.randint(1, 27))
            boy = rnd.random() < 0.5
            p = Patient(
                full_name=f"{mother.full_name.split()[0][:-1] if boy else mother.full_name.split()[0]} {rnd.choice(BOYS if boy else GIRLS)}",
                kind=kind,
                born_at=born,
                birth_year=born.year,
                mother_id=mother.id,
                mahalla=mother.mahalla,
                phone=mother.phone,
                doctor=mother.doctor,
                zone="green",
                consent_at=now,
                last_contact_at=now - timedelta(days=rnd.randint(0, 5)),
                created_at=born,
            )
        else:
            p = Patient(
                full_name=name(),
                kind=kind,
                birth_year=rnd.randint(1984, 2006),
                weeks=rnd.randint(8, 39) if kind == "homilador" else None,
                mahalla=mah,
                phone=f"+998 9{rnd.randint(0, 9)} {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}",
                doctor=rnd.choice(DOCS),
                zone="green",
                consent_at=now,
                last_contact_at=now - timedelta(days=rnd.randint(0, 6)),
                created_at=now - timedelta(days=rnd.randint(20, 160)),
            )
        db.add(p)
        db.flush()
        patients.append(p)
        p.pinfl, p.sex = pinfl(), "m" if boy else "f"
        if kind == "chaqaloq":
            give(p, 0.97)
        else:
            p.parity = 0 if rnd.random() < 0.35 else rnd.randint(1, 4)  # 0: this is her first child
        r = rnd.random()
        if kind == "chaqaloq":
            d = {"temp": round(rnd.uniform(36.4, 37.2), 1), "complaints": []}
            if r < 0.06:
                d = {"temp": 37.9, "complaints": ["emmayapti"]}
            obs(p, rnd.randint(0, 4), "korik", d)
            continue
        hb0 = rnd.randint(114, 134)
        obs(p, rnd.randint(25, 60), "tahlil", {"hb": hb0, "bp_sys": rnd.randint(100, 128), "bp_dia": rnd.randint(62, 82)})
        d = {
            "hb": hb0 + rnd.randint(-6, 4),
            "bp_sys": rnd.randint(100, 132),
            "bp_dia": rnd.randint(62, 84),
            "glucose": round(rnd.uniform(4.0, 6.2), 1),
            "complaints": [],
        }
        if r < 0.045:
            d.update(bp_sys=rnd.randint(160, 178), bp_dia=rnd.randint(104, 116), complaints=["kuchli_bosh_ogrigi"])
        elif r < 0.065:
            d.update(hb=rnd.randint(58, 69), complaints=["holsizlik"])
        elif r < 0.16:
            d.update(bp_sys=rnd.randint(140, 152), bp_dia=rnd.randint(90, 98), complaints=rnd.choice([[], ["shish"]]))
        elif r < 0.25:
            d.update(hb=rnd.randint(86, 104))
        elif r < 0.29:
            p.last_contact_at = now - timedelta(days=rnd.randint(8, 12))
        obs(p, rnd.randint(0, 6) if r >= 0.25 or r < 0.25 else 1, "tahlil", d)
    # children of the district: the vaccination calendar follows each of them until sixteen
    mothers = [x for x in patients if x.kind in ("tuqqan", "homilador")]
    for i in range(70):
        mother, boy = rnd.choice(mothers), rnd.random() < 0.5
        born = now - timedelta(days=rnd.choice([rnd.randint(40, 150), rnd.randint(150, 520), rnd.randint(520, 2700)]))
        family = mother.full_name.split()[0]
        full = f"{family[:-1] if boy else family} {rnd.choice(BOYS if boy else GIRLS)}"
        if full in FIXED:
            continue
        p = Patient(
            full_name=full,
            kind="bola",
            sex="m" if boy else "f",
            born_at=born,
            birth_year=born.year,
            mother_id=mother.id,
            mahalla=mother.mahalla,
            phone=mother.phone,
            doctor=mother.doctor,
            zone="green",
            consent_at=now,
            last_contact_at=now - timedelta(days=rnd.randint(0, 40)),
            created_at=born,
            pinfl=pinfl(),
        )
        db.add(p)
        db.flush()
        patients.append(p)
        give(p, 0.75 if i % 6 == 0 else 0.997)  # every sixth child has gaps in the calendar
    # adults under dispensary follow-up; some of the groups are confidential
    for g in FOLLOWED:
        man, family = rnd.random() < 0.5, rnd.choice(L)
        full = f"{family[:-1] if man else family} {rnd.choice(MEN if man else F)}"
        if full in used:
            continue
        used.add(full)
        p = Patient(
            full_name=full,
            kind="boshqa",
            sex="m" if man else "f",
            birth_year=rnd.randint(1958, 2001),
            groups=[g],
            icd10=CODE[g],
            mahalla=rnd.choice(MAHALLA),
            phone=phone(),
            doctor=rnd.choice(DOCS),
            zone="green",
            consent_at=now,
            # most gave the separate consent to calls about their follow-up; a few have not been asked yet
            private_consent_at=None if rnd.random() < 0.15 else now - timedelta(days=rnd.randint(5, 300)),
            last_contact_at=now - timedelta(days=rnd.randint(0, 30)),
            created_at=now - timedelta(days=rnd.randint(60, 900)),
            pinfl=pinfl(),
        )
        db.add(p)
        db.flush()
        patients.append(p)
    # an early signal: several people with fever and cough in one mahalla this week
    for p in [x for x in patients if x.mahalla == "Navbahor" and x.kind == "homilador"][:5]:
        obs(p, rnd.randint(0, 3), "korik", {"complaints": ["isitma", "yotal"], "temp": 37.6})
    db.flush()
    for p in patients:
        db.refresh(p)
        core.recompute(db, p)
    db.flush()
    # history of closed tasks so that the district indicators are not empty
    for p in rnd.sample([x for x in patients if x.kind != "chaqaloq"], 46):
        created = now - timedelta(days=rnd.randint(3, 40))
        late = rnd.random() < 0.13
        st = rnd.choices(["tasdiqlandi", "bajarildi", "nomuvofiq"], [0.8, 0.16, 0.04])[0]
        db.add(
            Task(
                patient_id=p.id,
                type=rnd.choice(["faol_chaqiruv", "mutaxassis"]),
                role="shifokor",
                reason="Arxiv yozuvi",
                created_at=created,
                due_at=created + timedelta(hours=24),
                done_at=created + timedelta(hours=rnd.randint(30, 50) if late else rnd.randint(2, 22)),
                status=st,
                escalated=late,
            )
        )
    # one overdue open task to show escalation
    q = next(x for x in patients if x.zone == "yellow" and x.kind == "homilador")
    db.add(
        Task(
            patient_id=q.id,
            type="faol_chaqiruv",
            role="shifokor",
            reason="Shifoxonadan chiqarildi",
            created_at=now - timedelta(hours=31),
            due_at=now - timedelta(hours=7),
            status="ochiq",
        )
    )
    # calls: a few finished and planned ones so the calls page shows the whole cycle
    ok = {
        "emish": {"value": "no", "transcript": "Yo'q, yaxshi emyapti."},
        "tutqanoq": {"value": "no", "transcript": "Yo'q."},
        "nafas": {"value": "no", "transcript": "Yo'q, bir tekis."},
        "lanj": {"value": "no", "transcript": "Yo'q."},
        "sariq": {"value": "no", "transcript": "Yo'q."},
        "harorat": {"value": 36.7, "transcript": "O'ttiz olti-yu yetti."},
    }
    for i, p in enumerate([x for x in patients if x.kind == "chaqaloq" and x.zone == "green"][:9]):
        when = now - timedelta(days=i + 1, hours=3)
        if i < 4:
            db.add(
                Call(
                    token=secrets.token_urlsafe(9),
                    patient_id=p.id,
                    scenario="chaqaloq_30kun",
                    lang="uz",
                    status="tugadi",
                    answers=ok,
                    flags=[],
                    planned_at=when,
                    finished_at=when,
                    created_at=when,
                )
            )
        else:
            db.add(
                Call(
                    token=secrets.token_urlsafe(9),
                    patient_id=p.id,
                    scenario="chaqaloq_30kun",
                    lang="uz",
                    status="rejalashtirilgan",
                    answers={},
                    flags=[],
                    planned_at=now + timedelta(days=i - 3),
                    created_at=now,
                )
            )
    late = next(x for x in patients if x.kind == "homilador" and x.zone == "yellow")
    db.add(
        Call(
            token=secrets.token_urlsafe(9),
            patient_id=late.id,
            scenario="homilador",
            lang="uz",
            status="javobsiz",
            attempts=3,
            answers={},
            flags=["noanswer"],
            planned_at=now - timedelta(days=1),
            finished_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        )
    )
    db.query(Notice).delete()
    # three fixed patients for the live demo
    a = Patient(
        full_name="Sodiqova Dilnoza",
        kind="homilador",
        birth_year=1998,
        weeks=32,
        mahalla="Bog'ishamol",
        phone="+998 90 123-45-67",
        doctor="Rahmonov B.",
        zone="green",
        consent_at=now,
        last_contact_at=now,
        created_at=now - timedelta(days=90),
    )
    b = Patient(
        full_name="Valiyeva Madina",
        kind="tuqqan",
        birth_year=1995,
        mahalla="Guliston",
        phone="+998 91 234-56-78",
        doctor="Qosimova D.",
        zone="green",
        consent_at=now,
        last_contact_at=now,
        created_at=now - timedelta(days=200),
        diagnosis="Og'ir preeklampsiya, kesarcha kesish (shifokor yozuvi)",
    )
    db.add_all([a, b])
    db.flush()
    c = Patient(
        full_name="Valiyev Amir",
        kind="chaqaloq",
        born_at=now - timedelta(days=3),
        birth_year=now.year,
        mother_id=b.id,
        mahalla="Guliston",
        phone=b.phone,
        doctor=b.doctor,
        zone="green",
        consent_at=now,
        last_contact_at=now,
        created_at=now - timedelta(days=3),
    )
    db.add(c)
    # for the other parts of the demonstration: a child whose three-month vaccinations have come due,
    # a man with hypertension (the hospital story), a man under confidential dispensary follow-up
    d = Patient(full_name="Karimova Nilufar", kind="boshqa", sex="f", birth_year=1997, parity=1, mahalla="Navbahor", phone="+998 93 345-67-89")
    e = Patient(
        full_name="Rahimov Botir", kind="boshqa", sex="m", birth_year=1968, groups=["gipertoniya"], icd10="I11", mahalla="Guliston", phone="+998 94 456-78-90"
    )
    f = Patient(
        full_name="Toshmatov Sardor", kind="boshqa", sex="m", birth_year=1990, groups=["oiv"], icd10="B20", mahalla="Istiqlol", phone="+998 95 567-89-01"
    )
    e.private_consent_at = f.private_consent_at = now - timedelta(days=30)  # both agreed to calls about their follow-up
    for x in (d, e, f):
        x.doctor, x.zone, x.consent_at, x.last_contact_at, x.created_at = "Qosimova D.", "green", now, now, now - timedelta(days=300)
    db.add_all([d, e, f])
    db.flush()
    y = Patient(
        full_name="Karimov Yusuf",
        kind="bola",
        sex="m",
        born_at=now - timedelta(days=108),
        birth_year=(now - timedelta(days=108)).year,
        mother_id=d.id,
        mahalla=d.mahalla,
        phone=d.phone,
        doctor=d.doctor,
        zone="green",
        consent_at=now,
        last_contact_at=now - timedelta(days=45),
        created_at=now - timedelta(days=108),
    )
    db.add(y)
    db.flush()
    a.parity, b.parity, a.sex, b.sex, c.sex = 0, 0, "f", "f", "m"
    for x in (a, b, c, d, e, f, y):
        x.pinfl = pinfl()
    give(c, 1.0)
    give(y, 1.0, only=("tugilganda", "2oy"))  # the two-month doses are done, the three-month ones are not
    obs(a, 30, "tahlil", {"hb": 121, "bp_sys": 112, "bp_dia": 72})
    obs(a, 2, "tahlil", {"hb": 118, "bp_sys": 118, "bp_dia": 76, "glucose": 4.9, "complaints": []})
    obs(b, 1, "korik", {"bp_sys": 132, "bp_dia": 84, "hb": 109, "complaints": []})
    obs(c, 1, "korik", {"temp": 36.8, "complaints": []})
    db.flush()
    for p in (a, b, c, d, e, f, y):
        db.refresh(p)
        core.recompute(db, p)
    db.query(Notice).delete()
    db.query(DmedMessage).delete()

    # What DMED reported from hospitals, through the same door real messages come in.
    def stay(p, hospital, days_in, days_out, emergency, reason, icd10="", diagnosis="", advice="", by="103 tez yordam brigadasi"):
        start, eid = now - timedelta(days=days_in, hours=rnd.randint(1, 6)), f"seed-{p.id}"
        exchange.receive(db, dmed.encounter(p, hospital, start, None, emergency, reason, "", "", by, eid=eid))
        if days_out is not None:
            end = now - timedelta(days=days_out, hours=2)
            exchange.receive(db, dmed.encounter(p, hospital, start, end, emergency, reason, icd10, diagnosis, by, advice, eid=eid))

    own = [x for x in patients if x.doctor == "Qosimova D."]  # the demonstration family doctor sees her own patients
    inside = next((x for x in own if x.kind == "homilador" and x.zone != "green"), None) or next(x for x in patients if x.kind == "homilador")
    stay(inside, "Tuman perinatal markazi", 0, None, True, "Qon bosimi 170/110, kuchli bosh og'rig'i")
    home = next((x for x in own if x.kind == "tuqqan"), None) or next(x for x in patients if x.kind == "tuqqan")
    stay(
        home,
        "Viloyat perinatal markazi",
        5,
        0,
        True,
        "Qon ketishi",
        "O72.1",
        "Tug'ruqdan keyingi qon ketishi",
        "Gemoglobin nazorati; 3 kundan keyin oilaviy shifokor ko'rigi",
    )
    heart = next((x for x in patients if "gipertoniya" in (x.groups or []) and x.full_name not in FIXED), None)
    if heart:
        advice = "Qon bosimini kuniga ikki marta o'lchash; dorilarni uzluksiz ichish; bir haftadan keyin kardiolog ko'rigi"
        stay(heart, "Tuman markaziy shifoxonasi", 9, 2, True, "Ko'krakda og'riq, qon bosimi 190/110", "I11.9", "Gipertonik kriz", advice)
    db.flush()
    total = len(patients) + 7
    core.notify(
        db, None, "rahbar", "info", f"Namuna ma'lumotlar yuklandi: {total} ta sintetik bemor.", f"Загружены демо-данные: синтетических пациентов — {total}."
    )
    db.commit()
    return total
