"""Speech text -> patient card fields, each with the exact words it came from.

Pipeline: LLM proposes {field: {value, quote}} -> code checks that every quote really occurs
in the transcript -> unverified fields are dropped. If the LLM is unavailable, a rule-based
parser (regex + keyword lists for Uzbek and Russian) fills what it can.
The AI never writes a diagnosis of its own: `diagnosis` is kept only when it was dictated.
"""
import re

from . import voicelab
from .rules import COMPLAINTS, T

FIELDS = ["full_name", "birth_year", "kind", "weeks", "bp", "hb", "glucose", "temp", "pulse", "breath",
          "complaints", "diagnosis", "referral", "mahalla", "phone"]

SYSTEM = """Sen tibbiy registratura yordamchisisan. Hamshira yoki shifokor aytgan matndan bemor kartasi maydonlarini ajrat.
Matn o'zbek yoki rus tilida. FAQAT bitta JSON obyekt qaytar, boshqa hech narsa yozma.
Har bir topilgan maydon: {"value": ..., "quote": "matndan AYNAN ko'chirilgan bo'lak"}. Matnda yo'q maydonni qo'shma, o'ylab topma.
Maydonlar:
- full_name: bemorning ismi va familiyasi (matn)
- birth_year: tug'ilgan yili (4 xonali son)
- kind: "homilador" (homilador ayol), "tuqqan" (tuqqan ayol), "chaqaloq" (yangi tug'ilgan bola), "boshqa"
- weeks: homiladorlik haftasi (son)
- bp: qon bosimi "SYS/DIA" ko'rinishida, masalan "150/95"
- hb: gemoglobin, g/l (son)
- glucose: qondagi qand, mmol/l (son)
- temp: tana harorati, °C (son)
- pulse: puls (son)
- breath: nafas soni daqiqada (son)
- complaints: shikoyatlar ro'yxati; har biri {"code": KOD, "quote": "..."}; KOD faqat shu ro'yxatdan: %s
- diagnosis: FAQAT shifokor aytgan tashxis (o'zing tashxis qo'yma)
- referral: qayerga yoki nimaga yo'llanma (masalan "rentgen", "ginekolog")
- mahalla: mahalla nomi
- phone: telefon raqami
Sonlar so'z bilan aytilgan bo'lsa raqamga aylantir (quote esa matndagidek qoladi)."""


def _norm(s):
    s = (s or "").lower().replace("ʻ", "'").replace("’", "'").replace("`", "'").replace("‘", "'").replace("ё", "е")
    return re.sub(r"[^\w']+", " ", s, flags=re.U).strip()


def quote_ok(quote, text):
    q = _norm(quote)
    return bool(q) and q in _norm(text)


def _num(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _denied(quote, text):
    """A complaint quoted together with its denial ('shish yo'q', 'жалоб нет') is not a complaint."""
    q, low = _norm(quote), _norm(text)
    if re.search(r"\b(yo'q|yoq|emas|нет|без|kuzatilmadi|bo'lmadi|не было)\b", q):
        return True
    i = low.find(q)
    return i >= 0 and _negated(low, i, len(q))


def _clean(raw, text):
    """Keep only fields whose quote is really present in the transcript."""
    data, quotes, dropped = {}, {}, []
    for k in FIELDS:
        item = raw.get(k)
        if item in (None, "", [], {}):
            continue
        if k == "complaints":
            codes, cq = [], {}
            for c in item if isinstance(item, list) else []:
                code = (c.get("code") if isinstance(c, dict) else c) or ""
                q = c.get("quote", "") if isinstance(c, dict) else ""
                if code in COMPLAINTS and quote_ok(q, text) and not _denied(q, text):
                    codes.append(code)
                    cq[code] = q
                elif code:
                    dropped.append(f"complaints:{code}")
            if codes:
                data["complaints"], quotes["complaints"] = sorted(set(codes)), cq
            continue
        val = item.get("value") if isinstance(item, dict) else item
        q = item.get("quote", "") if isinstance(item, dict) else ""
        if val in (None, "") or not quote_ok(q, text):
            dropped.append(k)
            continue
        if k == "bp":
            m = re.match(r"\s*(\d{2,3})\D+(\d{2,3})", str(val))
            if not m:
                dropped.append(k)
                continue
            data["bp_sys"], data["bp_dia"] = int(m.group(1)), int(m.group(2))
        elif k in ("birth_year", "weeks", "pulse", "breath"):
            n = _num(val)
            if n is None:
                dropped.append(k)
                continue
            data[k] = int(n)
        elif k in ("hb", "glucose", "temp"):
            n = _num(val)
            if n is None:
                dropped.append(k)
                continue
            data[k] = n
        elif k == "kind":
            data[k] = val if val in ("homilador", "tuqqan", "chaqaloq", "boshqa") else "boshqa"
        else:
            data[k] = str(val).strip()[:200]
        quotes[k] = q
    return data, quotes, dropped


def _negated(low, i, n):
    """True when a complaint keyword is denied nearby: 'shish yo'q', 'отёков нет', 'без отёков'."""
    after, before = low[i + n:i + n + 22], low[max(0, i - 14):i]
    return bool(re.search(r"^\w*\s*(yo'q|yoq|emas|нет|не было|kuzatilmadi|bo'lmadi)\b", after) or re.search(r"(без|нет|не)\s+\w*\s*$", before))


def fallback(text):
    """Rule-based parser used when the LLM is unreachable. Digits only, no spelled numbers."""
    raw, low = {}, _norm(text)
    m = re.search(r"(\d{2,3})\s*(?:/|ga|на|-|дан|dan)\s*(\d{2,3})", text.lower())
    if m and 60 <= int(m.group(1)) <= 260:
        raw["bp"] = {"value": f"{m.group(1)}/{m.group(2)}", "quote": m.group(0)}
    m = re.search(r"\b(19[4-9]\d|20[0-2]\d)\b", text)
    if m:
        raw["birth_year"] = {"value": m.group(1), "quote": m.group(0)}
    for key, pat in (("hb", r"(?:gemoglobin\w*|гемоглобин\w*)\D{0,12}(\d{2,3})"),
                     ("weeks", r"(\d{1,2})\s*[- ]?(?:hafta|недел)"),
                     ("temp", r"(?:harorat\w*|температур\w*|isitma\w*)\D{0,12}(\d{2}(?:[.,]\d)?)"),
                     ("pulse", r"(?:puls\w*|пульс\w*)\D{0,10}(\d{2,3})"),
                     ("glucose", r"(?:qand\w*|сахар\w*)\D{0,12}(\d{1,2}(?:[.,]\d)?)")):
        m = re.search(pat, text.lower())
        if m:
            raw[key] = {"value": m.group(1), "quote": m.group(0)}
    comp = []
    for code, (_, _, kws) in COMPLAINTS.items():
        for kw in kws:
            k = _norm(kw)
            i = low.find(k)
            if i >= 0 and not _negated(low, i, len(k)):
                comp.append({"code": code, "quote": kw})
                break
    if comp:
        raw["complaints"] = comp
    if re.search(r"homilador|беремен", low):
        raw["kind"] = {"value": "homilador", "quote": re.search(r"homilador\w*|беремен\w*", low).group(0)}
    elif re.search(r"chaqaloq|новорожд|младен", low):
        raw["kind"] = {"value": "chaqaloq", "quote": re.search(r"chaqaloq\w*|новорожд\w*|младен\w*", low).group(0)}
    m = re.match(r"\s*([A-ZА-ЯЁ][\w'ʻ’]+\s+[A-ZА-ЯЁ][\w'ʻ’]+)", text)
    if m:
        raw["full_name"] = {"value": m.group(1), "quote": m.group(1)}
    return raw


def extract(text):
    """Return {'data', 'quotes', 'dropped', 'engine'} for a transcript."""
    text = (text or "").strip()
    if not text:
        return {"data": {}, "quotes": {}, "dropped": [], "engine": "none"}
    engine, raw = "llm", voicelab.chat_json(SYSTEM % ", ".join(COMPLAINTS.keys()), "Matn:\n" + text)
    if not isinstance(raw, dict):
        engine, raw = "qoidalar", fallback(text)
    data, quotes, dropped = _clean(raw, text)
    if data.get("temp") and "isitma" in data.get("complaints", []) and re.search(r"\d", quotes.get("complaints", {}).get("isitma", "")):
        data["complaints"].remove("isitma")  # a measured temperature is a value, not a complaint: the rules read the number
        quotes["complaints"].pop("isitma", None)
    if engine == "llm":  # safety net: red-flag keywords the model may have skipped
        fb, fq, _ = _clean({"complaints": fallback(text).get("complaints", [])}, text)
        for c in fb.get("complaints", []):
            if c in T["red_complaints"] and c not in data.get("complaints", []):
                data.setdefault("complaints", []).append(c)
                quotes.setdefault("complaints", {})[c] = fq["complaints"][c]
        if data.get("complaints"):
            data["complaints"] = sorted(set(data["complaints"]))
    return {"data": data, "quotes": quotes, "dropped": dropped, "engine": engine}


YES = ["ha", "xa", "bor", "shunday", "albatta", "to'g'ri", "keldi", "kelgan", "да", "есть", "ага", "угу", "приходил", "был", "была", "конечно"]
NO = ["yo'q", "yoq", "emas", "kelmadi", "kelmagan", "нет", "не было", "не приходил", "нету", "неа"]


def yes_no(text, question=""):
    """Classify a spoken answer: 'yes' | 'no' | 'unclear'. Keywords first, LLM for the rest."""
    low = " " + _norm(text) + " "
    if not low.strip():
        return "unclear"
    no = any(f" {_norm(w)} " in low for w in NO) or bool(re.search(r"\w+ma(y|d)\w*\b", low)) or " не " in low
    yes = any(f" {_norm(w)} " in low for w in YES)
    if no and not yes:
        return "no"
    if yes and not no:
        return "yes"
    out = voicelab.chat([
        {"role": "system", "content": "Savolga berilgan javobni tasnifla. Faqat bitta so'z yoz: HA, YOQ yoki NOANIQ."},
        {"role": "user", "content": f"Savol: {question}\nJavob: {text}"}], max_tokens=5)
    if out:
        o = _norm(out)
        if o.startswith("ha"):
            return "yes"
        if o.startswith("yo"):
            return "no"
    return "no" if no else ("yes" if yes else "unclear")


def number(text):
    """First number in a spoken answer (digits); LLM converts spelled numbers."""
    m = re.search(r"\d{1,3}(?:[.,]\d)?", text or "")
    if m:
        return _num(m.group(0))
    out = voicelab.chat([
        {"role": "system", "content": "Matndagi sonni raqam bilan yoz. Faqat son, masalan 37.5. Son bo'lmasa: YOQ."},
        {"role": "user", "content": text or ""}], max_tokens=8)
    m = re.search(r"\d{1,3}(?:[.,]\d)?", out or "")
    return _num(m.group(0)) if m else None
