"""A phone with a SIM card as the telephone line.

A small program on a computer next to an Android phone (gateway/gateway.py) asks this server for the next
number to ring and dials it through the phone over USB. When the call is answered it opens the call page in
"line" mode: the page speaks and listens through the computer's sound devices, which are joined to the phone
by a headset cable or by the phone's loudspeaker. The person called needs no application and no internet,
and sees an ordinary local number.

This is a demonstration rig. A working installation puts an operator's SIP trunk or a GSM gateway box in
its place; the dialogue and everything behind it stay the same. The queue lives in memory: it is a handful
of calls, and one that is lost on a restart is simply asked for again.
"""

import hmac
import time
from collections import deque

from . import config

_queue = deque()  # calls waiting to be rung: {"token", "phone", "lang"}
_seen = {"at": 0.0}  # when the rig last asked for work
_state = {}  # call token -> the last thing reported about that call on the line


def enabled():
    return bool(config.GATEWAY_KEY)


def online():
    """True while a rig is asking for work (it asks every couple of seconds)."""
    return enabled() and time.time() - _seen["at"] < 20


def allowed(key):
    return enabled() and hmac.compare_digest((key or "").encode(), config.GATEWAY_KEY.encode())


def ask(call, phone):
    """Put a call in the queue for the rig."""
    _queue.append({"token": call.token, "phone": phone, "lang": call.lang or "uz"})
    _state[call.token] = "navbatda"


def take():
    """The rig asks for the next call to ring."""
    _seen["at"] = time.time()
    return _queue.popleft() if _queue else None


def report(token, state):
    _state[token] = state[:20]


def state(token):
    return _state.get(token)
