"""The parts of a call that are about this one person: the greeting by name, the check that the right
person picked up, and her own questions.

A call does not start with the list of questions. The assistant says where it is calling from, names the
patient and asks whether it is speaking with her; it goes on only after a "yes", so nothing about health is
said to anyone else. After the scenario's questions the patient may ask her own.

An answer comes only from the polyclinic's leaflet (app/advice.json: short notes, each tied to the WHO
document it follows). A language model picks the notes that fit the question and words them for the ear; it
must name the notes it used, and an answer that names none is not spoken. A question the leaflet does not
answer, or one about her own diagnosis or medicines, is not answered by the machine at all: it goes to the
person she is attached to, as a message with a deadline. A warning sign in her words never waits for a
model: the keyword rules send it the usual red road and she is told to call the emergency number.

The model is told the kind of patient, the notes and her question. No name, phone or address.
"""

import json
import os
import re

from . import closing, core, extract, vaccines, voicelab
from .db import Patient

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "advice.json"), encoding="utf-8") as _fh:
    ADVICE = json.load(_fh)

NO_ANSWER = "TOPILMADI"  # the model's word for "the leaflet does not answer this"
MAX_QUESTIONS = 3  # her own questions in one call; the page counts them too

HELLO = {
    "uz": "Assalomu alaykum! Sizga poliklinikadan Nigoh — sun'iy intellekt yordamchisi qo'ng'iroq qilyapti. {ask}",
    "ru": "Здравствуйте! Вам звонит Nigoh — помощник поликлиники на основе искусственного интеллекта. {ask}",
}
IS_IT_YOU = {"uz": "Men {name} bilan gaplashyapmanmi?", "ru": "Скажите, пожалуйста, вы — {name}?"}
IS_IT_YOUR_CHILD = {"uz": "{name} — sizning farzandingizmi?", "ru": "Скажите, пожалуйста, ваш ребёнок — {name}?"}
THANKS = {"uz": "Rahmat, {name}.", "ru": "Спасибо, {name}."}
THANKS_PLAIN = {"uz": "Rahmat.", "ru": "Спасибо."}
# said after the scenario's own introduction, so she knows the call is not only a questionnaire
YOUR_TURN = {"uz": "Oxirida o'z savollaringizni berishingiz mumkin.", "ru": "В конце вы сможете задать свои вопросы."}

# said when the call follows a stay in a hospital; the hospital and the diagnosis are not named aloud
AFTER_HOSPITAL = {
    "uz": "Shifoxonadan chiqqaningizdan keyin ahvolingizni bilish uchun qo'ng'iroq qilyapman.",
    "ru": "Звоню узнать, как вы себя чувствуете после выписки из больницы.",
}
POLITE = {"f": " opa", "m": " aka"}  # how a woman and a man are addressed by first name in Uzbek

PERSON = {
    "homilador": "a pregnant woman",
    "tuqqan": "a woman who gave birth recently",
    "chaqaloq": "the mother of a newborn",
    "bola": "the parent of a child whose vaccination has come due",
    "dispanser": "a patient under regular dispensary follow-up at the polyclinic (the diagnosis is confidential: you do not know it and never guess it)",
}
# What a first-time mother is offered to hear after the questions: the offer and the leaflet notes read to her.
TIPS = {"homilador": ("tips_q_preg", ["xavf_homila", "ovqat", "korik"]), "ona": ("tips_q_baby", ["emizish", "kindik", "uyqu", "xavf_chaqaloq"])}

SYSTEM = """You are the voice of Nigoh, the AI assistant of a district polyclinic in Uzbekistan, in a follow-up \
phone call with {person}. She has just asked a question in her own words. Your reply is turned into speech \
and played to her while she waits on the line.

You may answer only from the numbered notes below. They are the polyclinic's leaflet for patients and follow \
World Health Organization recommendations. You are not a doctor and you do not know her medical history.

- If the notes answer her question, reply in {language} with two or three short sentences in everyday words, \
using only what the notes say. Begin the reply with the numbers of the notes you used in square brackets, \
for example [3] or [3, 7].
- If the notes do not answer it, reply with the single word {none} and nothing else. Do the same when she \
asks about her own diagnosis, her test results, a particular medicine or its dose, or whether something is \
safe for her personally, and when you cannot tell what she is asking. Her question is then passed to her \
doctor, so {none} is a good answer and never a failure.
- Add nothing of your own: no facts, causes, medicine names, amounts or home remedies that are not in the \
notes. Never tell her that she is healthy or that something is nothing to worry about.
- If she describes something the notes list as a danger sign, tell her to call the emergency number at \
once, as the note says.

Format: plain sentences, at most forty-five words, every number written in words, no digits apart from the \
note numbers in the brackets, no lists, no quotation marks, no greeting. Reply with the brackets and the \
answer, or with {none}, and nothing else.

Notes:
{notes}"""

# Uzbek Latin letters as the Russian voice should read them; the longer spellings come first.
_CYRILLIC = [("o'", "у"), ("g'", "г"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"), ("j", "дж")] + list(
    zip("abdefghiklmnopqrstuvxyzcw", "абдефгхиклмнопкрстувхйзкв", strict=True)
)
# a short reply that is not a question: she has none, or she only says that she has one
_QUIET = {"yo'q", "yoq", "rahmat", "raxmat", "katta", "savolim", "savol", "kerak", "emas", "boshqa", "hammasi", "tushunarli"} | {
    "нет",
    "нету",
    "спасибо",
    "вопросов",
    "не",
    "надо",
    "больше",
    "все",
    "понятно",
}
_NO = {"yo'q", "yoq", "emas", "rahmat", "raxmat", "tushunarli", "нет", "нету", "не", "спасибо", "понятно"}
_GO = {"ha", "xa", "bor", "savolim", "savol", "bitta", "mayli", "xo'p", "да", "есть", "вопрос", "один"}
_YES = {"ha", "xa", "bor", "да", "есть"}


def cyrillic(name):
    """An Uzbek name in Latin letters, written in Cyrillic for the Russian voice: Sodiqova -> Содикова."""
    out = []
    for word in extract._norm(name).split():
        said, i = "", 0
        while i < len(word):
            for latin, cyr in _CYRILLIC:
                if word.startswith(latin, i):
                    said += "э" if latin == "e" and i == 0 else cyr
                    i += len(latin)
                    break
            else:
                said += word[i] if word[i].isalpha() and not word[i].isascii() else ""  # already Cyrillic stays; an apostrophe goes
                i += 1
        out.append(said.capitalize())
    return " ".join(w for w in out if w)


def spoken(full_name, lang):
    """A name as it is said aloud: the given name first, in the letters the voice reads.
    Cards hold the family name first: "Sodiqova Dilnoza" is greeted as "Dilnoza Sodiqova"."""
    parts = (full_name or "").split()
    said = f"{parts[1]} {parts[0]}" if len(parts) > 1 else " ".join(parts)
    return cyrillic(said) if lang == "ru" else said


def given(full_name, lang):
    parts = (full_name or "").split()
    name = parts[1] if len(parts) > 1 else "".join(parts[:1])
    return cyrillic(name) if lang == "ru" else name


def opening(db, call):
    """What is said before any question: (hello, intro). `hello` says who is calling and asks whether the
    right person is on the line; `intro` follows her "yes". A call about a newborn is a call to the mother."""
    p, lang = call.patient, call.lang if call.lang in ("uz", "ru") else "uz"
    child = p.kind in vaccines.CHILD
    mother = db.get(Patient, p.mother_id) if child and p.mother_id else None
    if child and not mother:
        ask, name = IS_IT_YOUR_CHILD[lang].format(name=spoken(p.full_name, lang)), ""
    else:
        who = mother or p
        ask, name = IS_IT_YOU[lang].format(name=spoken(who.full_name, lang)), given(who.full_name, lang)
        woman = who.sex == "f" or (not who.sex and (child or p.kind in ("homilador", "tuqqan")))
        if name and lang == "uz":
            name += POLITE["f"] if woman else POLITE.get(who.sex, "")
    thanks = THANKS[lang].format(name=name) if name else THANKS_PLAIN[lang]
    context = call.context or {}
    about = vaccines.sentence(context, lang, given(p.full_name, lang) if lang == "uz" else "") if context.get("doses") else ""
    about = about or (AFTER_HOSPITAL[lang] if context.get("hospital") else "")
    return HELLO[lang].format(ask=ask), " ".join(x for x in (thanks, about, core.SCENARIOS[call.scenario]["intro"][lang], YOUR_TURN[lang]) if x)


def topic(call):
    """Whose leaflet a call's answers come from: the kind of patient, or what the scenario is about."""
    who = core.SCENARIOS[call.scenario].get("who")
    return "dispanser" if who == "dispanser" else "bola" if who == "emlash" else call.patient.kind


ASK = {"homilador": "ask_q_homilador", "tuqqan": "ask_q_ona", "chaqaloq": "ask_q_ona", "bola": "ask_q_bola", "dispanser": "ask_q_dispanser"}


def ask_key(call):
    """Which invitation to ask her own questions a call uses: it names only what concerns this person."""
    return ASK.get(topic(call), "ask_q")


def needs_year(call):
    """A call about dispensary follow-up asks the year of birth after the name: a second key before anything is said."""
    return bool(core.SCENARIOS[call.scenario].get("private") and call.patient.birth_year)


def year_matches(said, year):
    """'yes' when the spoken or typed words name this year of birth, 'no' when they name another, 'unclear'
    when no year can be read. Two digits are enough: "to'qson sakkiz" is how a year is usually said."""
    found = re.findall(r"\d+", said or "")
    if not found and said and voicelab.enabled():  # the year was said in words: the model writes it in digits
        out = voicelab.chat(
            [
                {"role": "system", "content": "Matnda aytilgan tug'ilgan yilni raqam bilan yoz. Faqat son. Yil aytilmagan bo'lsa: YOQ."},
                {"role": "user", "content": said},
            ],
            max_tokens=8,
        )
        found = re.findall(r"\d+", out or "")
    if not found:
        return "unclear"
    return "yes" if any(int(x) == year or (len(x) <= 2 and int(x) == year % 100) for x in found) else "no"


def tips(db, call):
    """For a first-time mother: (the offer's phrase, the leaflet notes that are read to her), else None."""
    p, who = call.patient, core.SCENARIOS[call.scenario].get("who")
    mother = db.get(Patient, p.mother_id) if p.kind in vaccines.CHILD and p.mother_id else p
    if who not in ("homilador", "tuqqan", "chaqaloq") or not mother or mother.parity != 0:
        return None
    offer, ids = TIPS["homilador" if who == "homilador" else "ona"]
    lang = call.lang if call.lang in ("uz", "ru") else "uz"
    return offer, [n[lang] for i in ids for n in ADVICE["notes"] if n["id"] == i]


def short(said):
    """A reply to "do you have a question?" that is not a question itself: 'none' when she has none,
    'go' when she only says that she has one. Anything else returns None and is read as her question."""
    words = extract._norm(said).split()
    if not words or len(words) > 4:
        return None
    if all(w in _QUIET for w in words) and any(w in _NO for w in words):
        return "none"
    if all(w in _GO for w in words) and any(w in _YES for w in words):
        return "go"
    return None


def notes(kind):
    """The leaflet's notes for this kind of patient, in the order they are numbered for the model.
    A patient of another kind has none: every question of hers goes to her doctor."""
    return [n for n in ADVICE["notes"] if kind in n["who"]]


def source(ids, lang):
    """The documents the notes with these ids follow, for the staff who read what the patient was told."""
    seen = []
    for n in ADVICE["notes"]:
        title = ADVICE["sources"][n["src"]][lang if lang in ("uz", "ru") else "uz"]
        if n["id"] in ids and title not in seen:
            seen.append(title)
    return seen


def _split(text):
    """A model's reply as (note numbers it names, the words to speak)."""
    m = re.match(r"\s*\[([\d,;\s]*)\][\s.:—-]*", text)
    return ([int(x) for x in re.findall(r"\d+", m.group(1))], text[m.end() :].strip()) if m else ([], text)


def compose(kind, lang, said):
    """An answer to her question, worded from the leaflet: (text, who wrote it, ids of the notes used).
    (None, None, []) when the leaflet has no answer, no model is available or none gave an acceptable one
    in time: the question then goes to her doctor."""
    lang = lang if lang in ("uz", "ru") else "uz"
    leaflet = notes(kind)
    if not leaflet or not closing.writers(lang):
        return None, None, []
    system = SYSTEM.format(
        person=PERSON[kind], language=closing.LANGUAGE[lang], none=NO_ANSWER, notes="\n".join(f"{i}. {n[lang]}" for i, n in enumerate(leaflet, 1))
    )

    def check(text):
        if NO_ANSWER in text.upper():
            return None  # "not in the leaflet" is a decision, not a failed reply
        numbers, words = _split(text)
        if not any(0 < n <= len(leaflet) for n in numbers):
            return "no note named"
        return closing.acceptable(words, lang, False)

    # She is in the middle of a conversation: the first acceptable answer is spoken, a slower model is not waited for.
    text, by = closing.write(lang, f"Her question: {said[:600]}", check, system, fastest=True)
    if not text or NO_ANSWER in text.upper():
        return None, None, []
    numbers, words = _split(text)
    return words, by, [leaflet[n - 1]["id"] for n in numbers if 0 < n <= len(leaflet)]


def keep(call, said, kind, answer=None, by=None, used=(), told=None):
    """Every exchange of the free part stays in the call's record: what she asked, what she was told, who
    worded it and from which notes, and whether her doctor was told. Returns its number in the call."""
    talk = dict((call.answers or {}).get("suhbat") or {})
    items = list(talk.get("items") or [])
    items.append({"q": said[:600], "kind": kind, "a": answer, "by": by, "notes": list(used), "source": source(used, call.lang), "to": told})
    call.answers = {**(call.answers or {}), "suhbat": {"value": len(items), "items": items}}
    return len(items) - 1
