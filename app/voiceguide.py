"""Questions for clinician dictation and the reviewed, answer-by-answer draft."""

import re

from . import extract

QUESTIONS = [
    {"id": "full_name", "ru": "Как зовут пациента?", "uz": "Bemorning familiyasi va ismi nima?"},
    {"id": "birth_year", "ru": "В каком году родился пациент?", "uz": "Bemor qaysi yilda tug‘ilgan?"},
    {"id": "complaints", "ru": "Какие жалобы есть сегодня?", "uz": "Bugun bemorda qanday shikoyatlar bor?"},
    {"id": "weeks", "kind": "homilador", "ru": "Какой сейчас срок беременности?", "uz": "Hozir homiladorlik necha haftalik?"},
    {"id": "recovery", "kind": "tuqqan", "ru": "Как проходит восстановление после родов?", "uz": "Tug‘ruqdan keyin tiklanish qanday kechmoqda?"},
    {"id": "feeding", "kind": "chaqaloq", "ru": "Как новорождённый ест и набирает вес?", "uz": "Chaqaloq qanday emyapti va vazn olyapti?"},
    {"id": "vaccination", "kind": "bola", "ru": "Какие прививки указаны в карте ребёнка?", "uz": "Bolaning kartasida qaysi emlashlar qayd etilgan?"},
    {"id": "vitals", "ru": "Какие показатели вы измерили?", "uz": "Qaysi ko‘rsatkichlarni o‘lchadingiz?"},
    {"id": "diagnosis", "ru": "Какой диагноз вы зафиксировали?", "uz": "Qanday tashxisni qayd etdingiz?"},
    {"id": "plan", "ru": "Какой следующий шаг вы назначили?", "uz": "Keyingi kuzatuv yoki yo‘llanma bo‘yicha nima belgiladingiz?"},
]


def make_draft(answers, kind, lang):
    questions = [q for q in QUESTIONS if not q.get("kind") or q["kind"] == kind]
    if answers.keys() - {q["id"] for q in questions}:
        raise ValueError("question_outside_exam")
    entries = {q["id"]: answers[q["id"]].strip() for q in questions if answers.get(q["id"], "").strip()}
    if not 2 <= len(entries.get("full_name", "")) <= 160:
        raise ValueError("patient_name")
    transcript = "\n\n".join(f"{q[lang]}\n{entries[q['id']]}" for q in questions if q["id"] in entries)
    if len(transcript) > 4000:
        raise ValueError("answers_too_long")

    # Only the clinician's words are evidence. A question mentioning a symptom, a date or
    # vaccination must never become a finding by itself.
    result = extract.extract("\n".join(entries.values()))
    data, quotes = result["data"], result["quotes"]
    for key, source in (("birth_year", "birth_year"), ("weeks", "weeks"), ("referral", "plan")):
        if key in data and not extract.quote_ok(quotes.get(key), entries.get(source, "")):
            data.pop(key, None)
            quotes.pop(key, None)
    for key, pattern, low, high in (("birth_year", r"\b\d{4}\b", 1930, 2100), ("weeks", r"\b\d{1,2}\b", 1, 45)):
        spoken = entries.get(key, "")
        numbers = re.findall(pattern, spoken)
        if len(numbers) == 1 and low <= int(numbers[0]) <= high:
            data[key], quotes[key] = int(numbers[0]), spoken
        elif len(numbers) > 1 or (key in data and not low <= data[key] <= high):
            data.pop(key, None)
            quotes.pop(key, None)

    data["full_name"] = quotes["full_name"] = entries["full_name"]
    data.pop("kind", None)
    quotes.pop("kind", None)
    if kind:
        data["kind"] = kind  # explicitly selected by the clinician
    data.pop("diagnosis", None)
    quotes.pop("diagnosis", None)
    diagnosis = entries.get("diagnosis", "")
    unspecified = diagnosis.casefold().strip(" .!?").replace("‘", "'").replace("’", "'") in {
        "нет", "пока нет", "не установлен", "не установлено", "диагноз не установлен", "диагноза нет",
        "yo'q", "aniqlanmagan", "qo'yilmagan", "tashxis qo'yilmagan",
    }
    if diagnosis and not unspecified and len(diagnosis) <= 240:
        data["diagnosis"] = quotes["diagnosis"] = diagnosis

    return {**result, "transcript": transcript, "answers": entries, "kind": kind, "language": lang}
