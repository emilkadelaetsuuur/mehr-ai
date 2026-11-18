"""Measure how accurately dictated phrases become card fields.

Run inside the app container:  python -m scripts.eval
Writes data/eval.json, which the "Tizim haqida" page shows. Text-level test: it checks the
LLM + quote-verification step. Audio recognition is measured separately with real recordings.
"""

import datetime
import json
import os

from app import config, extract, voicelab

CASES = [
    (
        "uz",
        "Sodiqova Dilnoza, 1998-yil tug'ilgan, homiladorlik 32 hafta, qon bosimi 150 ga 95, oyoqlarida shish bor",
        {"full_name": "Sodiqova Dilnoza", "birth_year": 1998, "kind": "homilador", "weeks": 32, "bp_sys": 150, "bp_dia": 95, "complaints": ["shish"]},
    ),
    (
        "uz",
        "Valiyeva Madina 1995-yil, homilador, 28 hafta, gemoglobin 86, holsizlikdan shikoyat qilyapti",
        {"full_name": "Valiyeva Madina", "birth_year": 1995, "kind": "homilador", "weeks": 28, "hb": 86, "complaints": ["holsizlik"]},
    ),
    (
        "uz",
        "Bemor Rahimova Gulnora, 2001-yil, homiladorlik 36 hafta, bosimi 165 ga 110, boshi qattiq og'riyapti, ko'zi xiralashgan",
        {
            "full_name": "Rahimova Gulnora",
            "birth_year": 2001,
            "weeks": 36,
            "bp_sys": 165,
            "bp_dia": 110,
            "complaints": ["kuchli_bosh_ogrigi", "korish_buzilishi"],
        },
    ),
    (
        "uz",
        "Tosheva Nilufar, 1990-yil, homilador, 20 hafta, qon bosimi 110 ga 70, gemoglobin 121, shikoyati yo'q",
        {"full_name": "Tosheva Nilufar", "birth_year": 1990, "weeks": 20, "bp_sys": 110, "bp_dia": 70, "hb": 121, "complaints": []},
    ),
    (
        "uz",
        "Chaqaloq Valiyev Amir, harorati 38, ko'krakni emmayapti, lanj bo'lib qolgan",
        {"full_name": "Valiyev Amir", "kind": "chaqaloq", "temp": 38, "complaints": ["emmayapti", "harakatsiz"]},
    ),
    (
        "uz",
        "Nazarova Zarina, 1997-yil, homiladorlik 30 hafta, qon ketyapti, qorni og'riyapti",
        {"full_name": "Nazarova Zarina", "birth_year": 1997, "weeks": 30, "complaints": ["qon_ketish", "qorin_ogrigi"]},
    ),
    (
        "uz",
        "Qodirova Shahnoza, 1993-yil, homilador, 34 hafta, homila qimirlamayapti deydi, bosimi 120 ga 80",
        {"full_name": "Qodirova Shahnoza", "birth_year": 1993, "weeks": 34, "bp_sys": 120, "bp_dia": 80, "complaints": ["homila_qimirlamaydi"]},
    ),
    (
        "uz",
        "Saidova Malika 1999-yil, 12 hafta, qand miqdori 7,8, ko'ngli aynayapti",
        {"full_name": "Saidova Malika", "birth_year": 1999, "weeks": 12, "glucose": 7.8, "complaints": ["kongil_aynishi"]},
    ),
    (
        "uz",
        "Ergasheva Feruza, 1988-yil, tuqqan ayol, harorati 38,5, isitmasi bor, puls 104",
        {"full_name": "Ergasheva Feruza", "birth_year": 1988, "kind": "tuqqan", "temp": 38.5, "pulse": 104, "complaints": ["isitma"]},
    ),
    (
        "uz",
        "Mirzayeva Nodira, 2003-yil, homiladorlik 24 hafta, Guliston mahallasi, bosimi 142 ga 92, shish yo'q",
        {"full_name": "Mirzayeva Nodira", "birth_year": 2003, "weeks": 24, "bp_sys": 142, "bp_dia": 92, "mahalla": "Guliston", "complaints": []},
    ),
    (
        "ru",
        "Каримова Севара, 1996 года рождения, беременность 31 неделя, давление 155 на 100, отёки на ногах",
        {"full_name": "Каримова Севара", "birth_year": 1996, "kind": "homilador", "weeks": 31, "bp_sys": 155, "bp_dia": 100, "complaints": ["shish"]},
    ),
    (
        "ru",
        "Юсупова Камола, 1992 год, беременная, 26 недель, гемоглобин 68, сильная слабость",
        {"full_name": "Юсупова Камола", "birth_year": 1992, "weeks": 26, "hb": 68, "complaints": ["holsizlik"]},
    ),
    (
        "ru",
        "Новорождённый Алиев Умар, температура 37,9, плохо сосёт грудь, кожа пожелтела",
        {"full_name": "Алиев Умар", "kind": "chaqaloq", "temp": 37.9, "complaints": ["emmayapti", "sariqlik"]},
    ),
    (
        "ru",
        "Исмоилова Барно, 1994 года рождения, беременность 38 недель, давление 170 на 115, сильная головная боль, мушки в глазах",
        {
            "full_name": "Исмоилова Барно",
            "birth_year": 1994,
            "weeks": 38,
            "bp_sys": 170,
            "bp_dia": 115,
            "complaints": ["kuchli_bosh_ogrigi", "korish_buzilishi"],
        },
    ),
    (
        "ru",
        "Абдуллаева Лола, 2000 год, беременность 16 недель, давление 115 на 75, гемоглобин 124, жалоб нет",
        {"full_name": "Абдуллаева Лола", "birth_year": 2000, "weeks": 16, "bp_sys": 115, "bp_dia": 75, "hb": 124, "complaints": []},
    ),
    (
        "ru",
        "Хамидова Озода, 1991 год, родильница, температура 38,2, кровотечение",
        {"full_name": "Хамидова Озода", "birth_year": 1991, "kind": "tuqqan", "temp": 38.2, "complaints": ["qon_ketish"]},
    ),
    (
        "ru",
        "Султонова Ирода, 1998 год, беременность 29 недель, сахар 11,4, тошнота",
        {"full_name": "Султонова Ирода", "birth_year": 1998, "weeks": 29, "glucose": 11.4, "complaints": ["kongil_aynishi"]},
    ),
    (
        "ru",
        "Нормaтова Умида, 1989 год, беременность 33 недели, не чувствует шевелений плода, давление 130 на 85",
        {"birth_year": 1989, "weeks": 33, "bp_sys": 130, "bp_dia": 85, "complaints": ["homila_qimirlamaydi"]},
    ),
    (
        "uz",
        "Xolmatova Dildora, ming to'qqiz yuz to'qson yettinchi yil, homiladorlik o'ttiz hafta, bosimi bir yuz qirq beshga to'qson",
        {"full_name": "Xolmatova Dildora", "birth_year": 1997, "weeks": 30, "bp_sys": 145, "bp_dia": 90},
    ),
    (
        "uz",
        "Aliyeva Munisa 2002-yil, homilador, 22 hafta, yo'talyapti, harorati 37,6, diagnoz shifokor aytdi: o'tkir bronxit, rentgenga yo'llanma",
        {"full_name": "Aliyeva Munisa", "birth_year": 2002, "weeks": 22, "temp": 37.6, "complaints": ["yotal"], "diagnosis": "o'tkir bronxit"},
    ),
]


def same(k, got, want):
    if k == "complaints":
        return sorted(got or []) == sorted(want)
    if isinstance(want, (int, float)):
        try:
            return abs(float(got) - float(want)) < 0.05
        except Exception:
            return False
    g, w = extract._norm(str(got or "")), extract._norm(str(want))
    return g == w or (k in ("diagnosis", "mahalla") and w in g)


def main():
    by, rows, ok, total = {}, [], 0, 0
    for lang, text, want in CASES:
        res = extract.extract(text)
        miss = [k for k, v in want.items() if not same(k, res["data"].get(k), v)]
        ok += len(want) - len(miss)
        total += len(want)
        b = by.setdefault(lang, {"lang": {"uz": "O'zbekcha", "ru": "Русский"}[lang], "ok": 0, "total": 0})
        b["ok"] += len(want) - len(miss)
        b["total"] += len(want)
        rows.append({"lang": lang, "text": text, "engine": res["engine"], "missed": miss})
        print(("OK  " if not miss else "MISS"), lang, res["engine"], miss or "", "|", text[:70])
    out = {
        "date": datetime.date.today().isoformat(),
        "phrases": len(CASES),
        "fields_ok": ok,
        "fields_total": total,
        "by_lang": list(by.values()),
        "model": voicelab.status().get("model"),
        "rows": rows,
    }
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(os.path.join(config.DATA_DIR, "eval.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n{ok}/{total} fields correct ({100 * ok / total:.0f}%), model={out['model']}")


if __name__ == "__main__":
    main()
