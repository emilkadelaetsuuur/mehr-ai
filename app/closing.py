"""The last words of an AI call. The rules decide the outcome; a language model only words it for this patient.

Every scenario file holds one fixed closing phrase per outcome. With a language model available, the closing
is written for the patient who was just called: it names what she reported and says what happens next.
Two models can write it: Claude (with a Claude API key) and the VoiceLab model the rest of the system already
uses. Which one writes in which language is a setting, because their speed differs by language.
The decision never comes from the model: whether to raise the alarm is the result of rules.py and is
passed to the model as a fact. Each generated phrase is checked before it is spoken (language, length,
the emergency number in an alarm, no digits for the speech engine). A phrase that fails the check, a
refusal, an error or a slow answer all end the same way: the fixed phrase is used, so a call always ends.

Nothing that identifies the patient is sent: no name, phone or address, only the questions of the
scenario and the answers given in this call.
"""

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Late

from . import config, core, rules, voicelab

log = logging.getLogger("nigoh.closing")
_state = {"client": None, "plain": False}
# One pool per writer: requests a gateway keeps open must not hold up the other writer.
_pools = {name: ThreadPoolExecutor(max_workers=4, thread_name_prefix=name) for name in ("claude", "voicelab")}

EMERGENCY = {"uz": "bir yuz uch", "ru": "сто три"}  # 103 in words: the speech engine reads words, not digits
# Spoken while the closing is being written, so the caller hears a voice instead of silence.
BRIDGE = {"uz": "Rahmat! Javoblaringizni ko'rib chiqyapman, bir oz kutib turing.", "ru": "Спасибо! Смотрю ваши ответы, одну минуту."}
LANGUAGE = {"uz": "Uzbek, Latin script", "ru": "Russian"}
ANSWER = {"yes": "yes", "no": "no", "unclear": "not understood", None: "no answer"}

SYSTEM = """You write the closing words of an automated follow-up phone call that a district polyclinic in \
Uzbekistan makes to a pregnant woman, a woman after childbirth, or the mother of a newborn. An AI voice \
assistant asked a short fixed list of questions. Your text is the last thing she hears before the call ends: \
it is turned into speech and played to her, so write for the ear.

A rules engine has already decided the outcome of the call, following the clinical protocol. You do not \
decide or re-assess it; you put it into words for this particular person. You receive the language, the \
questions with her answers, the warning signs the rules found, the outcome, and what the system has done.

Write two short sentences, or three for an alarm, in the requested language. She is waiting on the line, so \
every extra word is a delay:
- Refer to what she actually said, so the ending fits this call. If she reported warning signs, name them. \
If she reported none, say that in one short phrase and do not read the list of signs back to her: she has \
just heard it. Use everyday words a village mother would use, not clinical terms.
- Outcome "alarm": say plainly that what she described needs a doctor now, ask her to call the emergency \
number right away, and tell her that her doctor has been sent an urgent message. The emergency number must \
appear, written in words exactly as given in the request.
- Outcome "calm": thank her and tell her that her answers have been passed to her doctor. She may be told \
she can call the polyclinic if something changes. Do not tell her she is healthy or that everything is fine: \
nobody examined her, so you cannot know that.
- Outcome "visit_confirmed" or "visit_disputed": this call only checked whether the family doctor or nurse \
came to her home. Thank her and say her answer has been passed to the head of the polyclinic. If she said \
nobody came, say that the polyclinic will look into it; do not promise a date or a visit.
- If some answers were not understood, say so in a few words and that the polyclinic will see this.

You are an assistant, not a doctor. The polyclinic's rule for this call is that the AI never gives a \
diagnosis or treatment advice, because a wrong word from a machine can do harm. So: no names of diseases, \
no medicines or home remedies, no guesses about causes, no new questions, and nothing that was not in the \
request. Say only what the system has really done.

Format: plain sentences only, at most forty words in all. Write every number in words, no digits. No lists, no \
quotation marks, no emoji, no greeting, no signature. Reply with the closing words and nothing else."""


def enabled():
    return config.CLAUDE_CLOSING and bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def fixed(call, res):
    """The scenario's own closing phrase for this outcome."""
    sc = core.SCENARIOS[call.scenario]
    return sc["closing_alert" if res["alert"] or res["verified"] is False else "closing_ok"][call.lang or "uz"]


def outcome(call, res):
    if call.scenario == "tashrif_tasdiq":
        return {True: "visit_confirmed", False: "visit_disputed"}.get(res["verified"], "calm")
    return "alarm" if res["alert"] else "calm"


def brief(call, res):
    """What the model is told about the call. No name, phone or address: answers only."""
    sc, lang = core.SCENARIOS[call.scenario], call.lang or "uz"
    lines = [
        f"Language: {LANGUAGE.get(lang, LANGUAGE['uz'])}",
        f"Call: {sc['title'][lang]}",
        f"Emergency number in words: {EMERGENCY.get(lang, EMERGENCY['uz'])}",
        "Questions and answers:",
    ]
    for q in sc["questions"]:
        a = (call.answers or {}).get(q["id"]) or {}
        said = a.get("value")
        said = ANSWER.get(said, f"{said}") if not isinstance(said, (int, float)) else f"{said:g}"
        heard = f' (her words: "{a["transcript"]}")' if a.get("transcript") and "tugma" not in a["transcript"] else ""
        lines.append(f"- {q[lang]} -> {said}{heard}")
    signs = [rules.COMPLAINTS[f][1 if lang == "ru" else 0] for f in call.flags or [] if f in rules.COMPLAINTS]
    kind = outcome(call, res)
    done = {
        "alarm": "an urgent message was sent to her doctor",
        "calm": "her answers were recorded in her card for her doctor",
        "visit_confirmed": "her confirmation was recorded and passed to the head of the polyclinic",
        "visit_disputed": "the head of the polyclinic was told that she says nobody came, although the visit was marked as done",
    }[kind]
    if (call.answers or {}).get("murojaat"):
        done += "; the message she left at the end of this call was passed to the person she is attached to"
    lines += [f"Warning signs found by the rules: {', '.join(signs) or 'none'}", f"Outcome: {kind}", f"What the system has done: {done}"]
    return "\n".join(lines)


def direct():
    """True when requests go straight to Anthropic, False behind another company's gateway (ANTHROPIC_BASE_URL)."""
    base = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    return not base or "api.anthropic.com" in base


def _send(client, text):
    import anthropic

    common = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 2000,  # the answer is three sentences; the room is for the model's own thinking
        "system": SYSTEM,
        "messages": [{"role": "user", "content": text}],
    }
    effort = {"output_config": {"effort": "low"}}
    if direct():
        # if a safety classifier declines, the API itself retries the request on its fallback model
        return client.beta.messages.create(**common, **effort, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    # A gateway in front of the API gets the plain Messages request. Gateways often lag behind the API, so
    # optional fields it refuses are dropped and not sent again.
    if "sonnet-5-5" in config.CLAUDE_MODEL:
        # The one current model whose thinking can be switched off: three sentences need none, and a caller is waiting.
        effort["thinking"] = {"type": "between_tools"}
    if not _state["plain"]:
        try:
            return client.messages.create(**common, **effort)
        except anthropic.BadRequestError as e:
            log.warning("claude: the gateway refused %s (%s); sending the plain request from now on", "/".join(effort), str(e.message)[:160])
            _state["plain"] = True
    return client.messages.create(**common)


def ask(text):
    """One request to Claude. Returns its words, or None if it declined, ran out of room or the call failed."""
    import anthropic  # imported here so the application starts and works without the package

    if _state["client"] is None:  # the key and, behind a gateway, its address come from the environment
        _state["client"] = anthropic.Anthropic(timeout=config.CLAUDE_TIMEOUT, max_retries=0)  # a caller is waiting: no retries
    try:
        r = _send(_state["client"], text)
    except anthropic.RateLimitError:
        log.warning("claude: rate limited")
        return None
    except anthropic.APIStatusError as e:
        log.warning("claude: api error %s %s", e.status_code, str(e.message)[:200])
        return None
    except anthropic.APIConnectionError as e:  # includes a timeout
        log.warning("claude: no answer in time (%s)", type(e).__name__)
        return None
    if r.stop_reason in ("refusal", "max_tokens"):  # declined, or cut off before the answer was complete
        log.warning("claude: stopped with %s", r.stop_reason)
        return None
    return " ".join(b.text.strip() for b in r.content if b.type == "text").strip()


def acceptable(text, lang, alarm):
    """Checks a generated closing before it is spoken. Returns the reason it is rejected, or None."""
    if not 30 <= len(text) <= 480:
        return "length"
    if re.search(r"\d", text):
        return "digits"
    letters = [ch.lower() for ch in text if ch.isalpha()]
    cyrillic = sum("а" <= ch <= "я" or ch in "ёўқғҳ" for ch in letters) / max(1, len(letters))
    if (lang == "ru" and cyrillic < 0.85) or (lang != "ru" and cyrillic > 0.1):
        return "language"
    if alarm and EMERGENCY.get(lang, EMERGENCY["uz"]) not in text.lower():
        return "no emergency number"
    return None


def ask_voicelab(text):
    """The same request to the VoiceLab language model: quick in Uzbek, and it runs in Uzbekistan."""
    return voicelab.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], max_tokens=220, temperature=0.3, timeout=8)


def writers(lang):
    """Who may word a closing in this language, in the order they are tried: [(name, function, seconds allowed)]."""
    out = []
    if enabled() and lang in config.CLAUDE_LANGS:
        out.append(("claude", ask, config.CLAUDE_TIMEOUT))
    if config.VOICELAB_CLOSING and voicelab.enabled():
        out.append(("voicelab", ask_voicelab, config.VOICELAB_CLOSING_TIMEOUT))
    return out


def sentences(text):
    """A closing split into sentences: each is turned into speech on its own, so the first is heard sooner."""
    out = []
    for part in re.split(r"(?<=[.!?…])\s+", text or ""):
        part = part.strip()
        if part and out and len(part) < 20:
            out[-1] += " " + part  # a two-word tail is not worth a separate clip
        elif part:
            out.append(part)
    return out


def compose(call, res):
    """Closing words for a finished call and who wrote them: 'claude', 'voicelab', or 'shablon' for the fixed phrase."""
    lang = call.lang or "uz"
    request, started = brief(call, res), time.monotonic()
    # A caller is on the line. All writers start at once and each has its time by the clock from that moment,
    # whatever its own network timeouts do: the wait is the longest single limit, not the sum of them.
    jobs = [(name, _pools[name].submit(write, request), seconds) for name, write, seconds in writers(lang)]
    for name, job, seconds in jobs:  # in order of preference
        try:
            text = job.result(timeout=max(0.0, seconds - (time.monotonic() - started)))
        except Late:
            log.warning("%s: no closing within %gs", name, seconds)
            continue
        except ImportError:
            log.warning("%s: the anthropic package is not installed", name)
            continue
        except Exception:  # anything unexpected must not break the end of a call
            log.exception("%s: closing failed", name)
            continue
        if not text:
            continue
        text = re.sub("[‘’ʻʼ`]", "'", text)  # one spelling of the Uzbek apostrophe, as in the scenario texts
        text = re.sub(r"\s+", " ", text).strip().strip('"«»“”')
        why = acceptable(text, lang, outcome(call, res) == "alarm")
        if why is None:
            return text, name
        log.warning("%s: closing rejected (%s)", name, why)
    return fixed(call, res), "shablon"
