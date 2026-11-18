"""Check the Claude connection used for the closing words of a call:  python -m scripts.claude_check

Lists the Claude models the key can use, then asks for one alarm and one calm closing in Uzbek and Russian
and prints each answer, how long it took and whether it passes the checks. Spends a few requests.
"""

import os
import time
from types import SimpleNamespace

from app import closing, config, core

SAMPLE = {
    "alarm": {
        "bosh": ("yes", "Ha, boshim qattiq og'riyapti."),
        "koz": ("no", "Yo'q."),
        "shish": ("yes", "Ha."),
        "qon": ("no", "Yo'q."),
        "homila": ("no", "Yo'q."),
    },
    "calm": {q: ("no", "Yo'q.") for q in ("bosh", "koz", "shish", "qon", "homila")},
}


def main():
    base = os.getenv("ANTHROPIC_BASE_URL", "").strip() or "https://api.anthropic.com"
    print(
        f"key: {'set' if closing.enabled() else 'MISSING'} | address: {base} | direct: {closing.direct()} | model: {config.CLAUDE_MODEL} | timeout: {config.CLAUDE_TIMEOUT:g}s"
    )
    if not closing.enabled():
        return
    import anthropic

    try:
        ids = [m.id for m in anthropic.Anthropic(timeout=15, max_retries=0).models.list(limit=200)]
        claude = [i for i in ids if any(w in i.lower() for w in ("claude", "fable", "opus", "sonnet", "haiku"))]
        print(f"models offered: {len(ids)}; Claude: {', '.join(claude) or 'none'}")
        print(f"configured model is {'offered' if config.CLAUDE_MODEL in ids else 'NOT in the list'}")
    except Exception as e:
        print(f"models: could not list ({type(e).__name__}: {str(e)[:160]})")
    for lang in ("uz", "ru"):
        for kind, answers in SAMPLE.items():
            flags = [q["complaint"] for q in core.SCENARIOS["homilador"]["questions"] if answers[q["id"]][0] == q["flag_if"]]
            call = SimpleNamespace(
                scenario="homilador",
                lang=lang,
                flags=flags,
                answers={k: {"value": v, "transcript": t if lang == "uz" else ""} for k, (v, t) in answers.items()},
            )
            res = {"alert": kind == "alarm", "verified": None}
            t0 = time.time()
            try:
                text = closing.ask(closing.brief(call, res))
            except Exception as e:
                text = None
                print(f"[{lang} {kind}] failed: {type(e).__name__}: {str(e)[:200]}")
            took = time.time() - t0
            if text:
                why = closing.acceptable(" ".join(text.split()), lang, kind == "alarm")
                print(f"[{lang} {kind}] {took:.1f}s | {'accepted' if why is None else 'REJECTED: ' + why} | {text}")
            else:
                print(f"[{lang} {kind}] {took:.1f}s | no usable answer; the fixed phrase would be spoken")
    print(f"plain request mode: {closing._state['plain']}")


if __name__ == "__main__":
    main()
