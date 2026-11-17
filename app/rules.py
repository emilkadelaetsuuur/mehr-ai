"""Deterministic, explainable risk zones.

The zone is ALWAYS produced by these rules (thresholds live in rules.json).
ML and LLM never change a zone: they only add a second opinion and a summary.
Every reason carries the value and the exact words it came from.
"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "rules.json"), encoding="utf-8") as f:
    T = json.load(f)

ORDER = {"green": 0, "yellow": 1, "red": 2}

# code -> (uz, ru, keywords used by the offline fallback parser)
COMPLAINTS = {
    "qon_ketish": ("Qon ketishi", "Кровотечение", ["qon ket", "qon kel", "кровотеч", "кровь ид", "кровян"]),
    "tutqanoq": ("Tutqanoq", "Судороги", ["tutqanoq", "talvasa", "судорог"]),
    "homila_qimirlamaydi": ("Homila qimirlamayapti", "Нет шевелений плода", ["qimirlama", "harakat sezma", "не шевел", "нет шевел"]),
    "kuchli_bosh_ogrigi": ("Kuchli bosh og'rig'i", "Сильная головная боль", ["bosh og'ri", "boshi og'ri", "bosh ogri", "boshim og'ri", "головн", "голова бол"]),
    "korish_buzilishi": ("Ko'rish buzilishi", "Нарушение зрения", ["ko'zi xira", "ko'rish", "ko'z oldi", "зрени", "в глазах", "мушки"]),
    "shish": ("Shish", "Отёки", ["shish", "отек", "отёк"]),
    "holsizlik": ("Holsizlik", "Слабость", ["holsiz", "darmonsiz", "quvvatsiz", "слабост"]),
    "isitma": ("Isitma", "Температура", ["isitma", "issig'i ko'tar", "isitmala", "лихорад", "жар"]),
    "yotal": ("Yo'tal", "Кашель", ["yo'tal", "yotal", "кашел", "кашля"]),
    "qorin_ogrigi": ("Qorin og'rig'i", "Боль в животе", ["qorin og'ri", "qorni og'ri", "живот бол", "боль в живот"]),
    "kongil_aynishi": ("Ko'ngil aynishi", "Тошнота", ["ko'ngil ayn", "ko'ngli ayn", "qus", "тошнот", "рвот"]),
    "hushdan_ketish": ("Hushdan ketish", "Потеря сознания", ["hushdan ket", "hushidan ket", "сознани"]),
    "emmayapti": ("Yaxshi emmayapti", "Плохо сосёт", ["emmayapti", "emmay", "ko'krak olma", "не сосет", "не сосёт", "плохо сос", "не ест"]),
    "tez_nafas": ("Tez nafas olish", "Частое дыхание", ["tez nafas", "hansira", "частое дых", "часто дыш"]),
    "kokrak_tortilishi": ("Ko'krak qafasi tortilishi", "Втяжение грудной клетки", ["ko'krak qafasi tortil", "втяжен"]),
    "harakatsiz": ("Harakatsiz, lanj", "Вялый, не двигается", ["lanj", "harakatsiz", "bo'shashgan", "вял", "не двига"]),
    "sariqlik": ("Sariqlik", "Желтуха", ["sarg'ay", "sariq", "желту", "пожелт"]),
}

LABELS = {
    "bp": ("Qon bosimi", "Давление"),
    "hb": ("Gemoglobin", "Гемоглобин"),
    "glucose": ("Qand miqdori", "Сахар крови"),
    "temp": ("Tana harorati", "Температура тела"),
    "pulse": ("Puls", "Пульс"),
    "breath": ("Nafas soni", "Частота дыхания"),
    "silent": ("Aloqa yo'q", "Нет связи"),
    "missed": ("Rejali tashrif o'tkazib yuborilgan", "Пропущен плановый визит"),
    "hb_drop": ("Gemoglobin pasaygan", "Гемоглобин снизился"),
    "discharge": ("Shifoxonadan chiqarilgan", "Выписана из стационара"),
    "unclear": ("Qo'ng'iroqda javob noaniq", "Ответ в звонке неясен"),
    "noanswer": ("Qo'ng'iroqqa javob bermadi", "Не ответила на звонок"),
    "ahvol": ("Ahvoli yomonlashgan", "Состояние ухудшилось"),
    "dori": ("Dorilarni qabul qilmayapti", "Не принимает лекарства"),
    "fikr": ("Tushuntirish tushunarsiz bo'lgan", "Объяснения врача были непонятны"),
}


def _reason(code, zone, value, quote="", rule=""):
    uz, ru = LABELS.get(code, COMPLAINTS.get(code, (code, code)))[:2]
    return {"code": code, "zone": zone, "uz": uz, "ru": ru, "value": value, "quote": quote, "rule": rule}


def evaluate(kind, data, quotes=None, prev=None, days_silent=0, missed_visit=False):
    """Return (zone, reasons). `data` is the merged latest values; `prev` the previous ones."""
    quotes = quotes or {}
    prev = prev or {}
    reasons = []
    complaints = set(data.get("complaints") or [])
    newborn = kind == "chaqaloq"

    sys_, dia = data.get("bp_sys"), data.get("bp_dia")
    if sys_ and dia and not newborn:
        val = f"{int(sys_)}/{int(dia)}"
        ry, rr = T["bp"]["yellow"], T["bp"]["red"]
        severe = complaints & set(T["bp_red_with"])
        if sys_ >= rr[0] or dia >= rr[1]:
            reasons.append(_reason("bp", "red", val, quotes.get("bp", ""), f">= {rr[0]}/{rr[1]}"))
        elif (sys_ >= ry[0] or dia >= ry[1]) and severe:
            reasons.append(_reason("bp", "red", val, quotes.get("bp", ""), f">= {ry[0]}/{ry[1]} + " + ", ".join(sorted(severe))))
        elif sys_ >= ry[0] or dia >= ry[1]:
            reasons.append(_reason("bp", "yellow", val, quotes.get("bp", ""), f">= {ry[0]}/{ry[1]}"))

    hb = data.get("hb")
    if hb and not newborn:
        if hb < T["hb"]["red_below"]:
            reasons.append(_reason("hb", "red", f"{hb:g} g/l", quotes.get("hb", ""), f"< {T['hb']['red_below']}"))
        elif hb < T["hb"]["yellow_below"]:
            reasons.append(_reason("hb", "yellow", f"{hb:g} g/l", quotes.get("hb", ""), f"< {T['hb']['yellow_below']}"))
        old = prev.get("hb")
        if old and old - hb >= T["hb"]["drop_yellow"]:
            reasons.append(_reason("hb_drop", "yellow", f"{old:g} -> {hb:g} g/l", quotes.get("hb", ""), f"pasayish >= {T['hb']['drop_yellow']}"))

    glu = data.get("glucose")
    if glu and not newborn:
        if glu >= T["glucose"]["red_from"]:
            reasons.append(_reason("glucose", "red", f"{glu:g} mmol/l", quotes.get("glucose", ""), f">= {T['glucose']['red_from']}"))
        elif glu >= T["glucose"]["yellow_from"]:
            reasons.append(_reason("glucose", "yellow", f"{glu:g} mmol/l", quotes.get("glucose", ""), f">= {T['glucose']['yellow_from']}"))

    temp = data.get("temp")
    if temp:
        if newborn:
            nt = T["newborn_temp"]
            if temp >= nt["red_from"] or temp < nt["red_below"]:
                reasons.append(_reason("temp", "red", f"{temp:g} °C", quotes.get("temp", ""), f">= {nt['red_from']} yoki < {nt['red_below']}"))
        elif temp >= T["temp_adult"]["red_from"]:
            reasons.append(_reason("temp", "red", f"{temp:g} °C", quotes.get("temp", ""), f">= {T['temp_adult']['red_from']}"))
        elif temp >= T["temp_adult"]["yellow_from"]:
            reasons.append(_reason("temp", "yellow", f"{temp:g} °C", quotes.get("temp", ""), f">= {T['temp_adult']['yellow_from']}"))

    pulse = data.get("pulse")
    if pulse and not newborn:
        if pulse >= T["pulse"]["red_from"]:
            reasons.append(_reason("pulse", "red", f"{int(pulse)}", quotes.get("pulse", ""), f">= {T['pulse']['red_from']}"))
        elif pulse >= T["pulse"]["yellow_from"]:
            reasons.append(_reason("pulse", "yellow", f"{int(pulse)}", quotes.get("pulse", ""), f">= {T['pulse']['yellow_from']}"))

    breath = data.get("breath")
    if breath and newborn and breath >= T["newborn_breath"]["red_from"]:
        reasons.append(_reason("breath", "red", f"{int(breath)}/daq", quotes.get("breath", ""), f">= {T['newborn_breath']['red_from']}"))

    for c in sorted(complaints):
        q = (quotes.get("complaints") or {}).get(c, "") if isinstance(quotes.get("complaints"), dict) else ""
        if c in T["red_complaints"]:
            reasons.append(_reason(c, "red", "", q, "xavf belgisi"))
        elif newborn and c == "isitma":
            reasons.append(_reason(c, "red", "", q, "chaqaloqda xavf belgisi"))
        elif c in T["yellow_complaints"]:
            reasons.append(_reason(c, "yellow", "", q, "shikoyat"))

    for extra in data.get("extra_flags") or []:  # unclear answer / no answer in a call
        reasons.append(_reason(extra, "yellow", "", "", "qo'ng'iroq"))

    if days_silent >= T["silent_days"]["red"]:
        reasons.append(_reason("silent", "red", f"{days_silent} kun", "", f">= {T['silent_days']['red']} kun"))
    elif days_silent >= T["silent_days"]["yellow"]:
        reasons.append(_reason("silent", "yellow", f"{days_silent} kun", "", f">= {T['silent_days']['yellow']} kun"))
    if missed_visit:
        reasons.append(_reason("missed", "yellow", "", "", "reja"))

    zone = "green"
    for r in reasons:
        if ORDER[r["zone"]] > ORDER[zone]:
            zone = r["zone"]
    reasons.sort(key=lambda r: -ORDER[r["zone"]])
    return zone, reasons


def days_between(a, b=None):
    b = b or datetime.utcnow()
    return max(0, (b - a).days) if a else 0
