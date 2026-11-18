"""Nigoh line rig: an Android phone with a SIM card rings real numbers for the AI call.

Run it on a computer that has the phone attached by USB (USB debugging on) and a speaker and microphone
that the phone can hear and be heard by: the phone on loudspeaker next to the computer, or a headset cable.

What it does, over and over:
  1. asks the Nigoh server for the next number to ring (staff press "SIM-karta orqali qo'ng'iroq qilish");
  2. dials it through the phone, as an ordinary call from the SIM card;
  3. waits until the person picks up, switches the phone to loudspeaker;
  4. opens the call page in "line" mode: it speaks and listens through this computer's sound devices;
  5. hangs up when the page has said its last word, or when the person hangs up.

Needs only Python 3 and adb (Android platform-tools). Usage:
    python gateway.py                       ring for real
    python gateway.py --dry-run             no phone, no browser: shows that the server side works
    python gateway.py --check               show what the phone reports and stop
"""

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
SPEAKER_WORDS = ("speaker", "динамик", "громк", "karnay", "dinamik")  # the loudspeaker button, in the phone's language
# android.telephony.PreciseCallState, as printed by `dumpsys telephony.registry`
ACTIVE, DIALING, ALERTING = 1, 3, 4


def say(*words):
    print(time.strftime("%H:%M:%S"), *words, flush=True)


class Rig:
    def __init__(self, a):
        self.a, self.key, self.conn = a, "", None
        if os.path.exists(a.key):
            with open(a.key, encoding="utf-8") as f:
                self.key = f.read().strip()

    # ---------- the server

    def http(self, method, path, body=None):
        """One request to the server over a connection that is kept open between requests."""
        url = urllib.parse.urlsplit(self.a.server)
        headers = {"X-Gateway-Key": self.key, "Content-Type": "application/json", "User-Agent": "nigoh-gateway"}
        data = json.dumps(body).encode() if body is not None else None
        for attempt in (1, 2):
            try:
                if self.conn is None:
                    make = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
                    self.conn = make(url.netloc, timeout=15)
                self.conn.request(method, path, body=data, headers=headers)
                r = self.conn.getresponse()
                text = r.read().decode()
                if r.status >= 400:
                    raise urllib.error.HTTPError(self.a.server + path, r.status, text[:200], r.headers, None)
                return json.loads(text or "{}")
            except urllib.error.HTTPError:
                raise
            except Exception:  # the kept connection went stale: open a new one, once
                self.conn = None
                if attempt == 2:
                    raise

    def report(self, token, state):
        try:
            self.http("POST", "/api/gateway/report", {"token": token, "state": state})
        except Exception as e:
            say("   (server did not take the report:", e, ")")

    # ---------- the phone

    def adb(self, *args, timeout=20):
        if self.a.dry_run:
            return ""
        r = subprocess.run([self.a.adb, *args], capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return (r.stdout or "") + (r.stderr or "")

    def phone_ready(self):
        out = self.adb("devices")
        lines = [x for x in out.splitlines()[1:] if x.strip()]
        if not lines:
            return "no phone is attached by USB"
        if "unauthorized" in lines[0]:
            return "the phone has not allowed USB debugging: unlock it and tap Allow"
        return None if "\tdevice" in lines[0] else f"the phone is not ready: {lines[0]}"

    def line_state(self):
        """'idle', 'ringing-out' or 'talking', from what the phone itself reports about its call."""
        out = self.adb("shell", "dumpsys", "telephony.registry")
        fg = [int(x) for x in re.findall(r"mForegroundCallState=(\d+)", out)]
        off = [int(x) for x in re.findall(r"mCallState=(\d+)", out)]
        if ACTIVE in fg:
            return "talking"
        if DIALING in fg or ALERTING in fg or 2 in off:
            return "ringing-out"
        return "idle"

    def loudspeaker(self):
        """Tap the loudspeaker button of the phone's own call screen, if it is not on already."""
        self.adb("shell", "uiautomator", "dump", "/sdcard/nigoh-ui.xml")
        xml = self.adb("shell", "cat", "/sdcard/nigoh-ui.xml")
        for node in re.findall(r"<node [^>]*>", xml):
            label = " ".join(re.findall(r'(?:text|content-desc)="([^"]*)"', node)).lower()
            box = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            if box and any(w in label for w in SPEAKER_WORDS):
                if 'checked="true"' in node or 'selected="true"' in node:
                    return True
                x1, y1, x2, y2 = map(int, box.groups())
                self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
                return True
        return False

    def hang_up(self):
        self.adb("shell", "input", "keyevent", "KEYCODE_ENDCALL")

    # ---------- one call

    def browser(self, url):
        exe = self.a.browser or next((b for b in BROWSERS if os.path.exists(b)), None)
        if not exe:
            raise RuntimeError("no Edge or Chrome found: give its path with --browser")
        return subprocess.Popen(
            [
                exe,
                f"--app={url}",
                f"--user-data-dir={os.path.join(HERE, 'browser-profile')}",
                "--autoplay-policy=no-user-gesture-required",  # the page speaks without anyone clicking
                "--use-fake-ui-for-media-stream",  # ...and listens without a permission prompt
                # nobody watches this window: it must keep working behind others and with the display asleep
                "--disable-features=CalculateNativeWinOcclusion",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--hide-crash-restore-bubble",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=440,760",
            ]
        )

    def close(self, page):
        """Close the call window: ask first, so the browser does not think it crashed."""
        if not page:
            return
        subprocess.run(["taskkill", "/PID", str(page.pid), "/T"], capture_output=True)
        try:
            page.wait(timeout=3)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(page.pid), "/T", "/F"], capture_output=True)

    def page_state(self, token):
        try:
            return self.http("GET", f"/api/gateway/state?token={token}").get("state")
        except Exception:
            return None

    def ring(self, job):
        token, phone = job["token"], job["phone"]
        say(f"ringing {phone[:5]}…{phone[-2:]} ({job['lang']})")
        self.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        self.adb("shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{phone}")
        self.report(token, "dialing")
        # The call window opens now, while the phone is still ringing, gets its microphone and speaker ready
        # and waits: the first word is then spoken the moment the person picks up.
        url = f"{self.a.server.rstrip('/')}/call/{token}?line=1&hold=1" + (f"&{self.a.page}" if self.a.page else "")
        page = None if self.a.dry_run else self.browser(url)
        try:
            started, seen_out, ready = time.time(), False, False
            while True:  # wait for the person to pick up
                time.sleep(0.4)
                state = "talking" if self.a.dry_run and time.time() - started > 2 else self.line_state()
                if not ready and not self.a.dry_run and self.page_state(token) == "ready":
                    ready = True
                    say("   the call window is ready")
                if state == "talking":
                    break
                seen_out = seen_out or state == "ringing-out"
                waited = time.time() - started
                if (state == "idle" and (seen_out or waited > 8)) or waited > self.a.ring_seconds:
                    say("   nobody picked up")
                    self.hang_up()
                    return self.report(token, "noanswer")
            self.report(token, "go")  # the call window starts speaking at once; the greeting needs no reply
            say("   picked up")
            if self.a.speaker and not self.a.dry_run:
                say("   loudspeaker:", "on" if self.loudspeaker() else "button not found - tap it on the phone")
            started, last = time.time(), "ready" if ready else None
            while time.time() - started < self.a.talk_seconds:
                time.sleep(1)
                if self.a.dry_run and time.time() - started > 3:
                    break
                state = self.page_state(token)
                if state and state != last:
                    last = state
                    say("   call window:", state)
                if state in ("done", "nomic"):
                    time.sleep(1.5)  # let the last word leave the speaker
                    break
                if not self.a.dry_run and self.line_state() == "idle":
                    say("   the person hung up")
                    break
        finally:
            self.hang_up()
            self.close(page)
            self.report(token, "ended")
            say("   call over")

    def run(self):
        if not self.key:
            sys.exit(f"no key: put the server's GATEWAY_KEY into {self.a.key}")
        problem = None if self.a.dry_run else self.phone_ready()
        if problem:
            sys.exit(problem)
        if self.a.check:
            say("phone:", self.adb("shell", "getprop", "ro.product.model").strip(), "| line:", self.line_state())
            say("server:", self.http("GET", "/api/gateway/next"))
            return
        say(f"waiting for calls from {self.a.server}" + (" (dry run: no phone, no browser)" if self.a.dry_run else ""))
        while True:
            try:
                job = self.http("GET", "/api/gateway/next").get("call")
            except urllib.error.HTTPError as e:
                sys.exit(f"the server refused the key ({e.code}): check {self.a.key}") if e.code == 403 else say("server:", e)
                job = None
            except Exception as e:
                say("server unreachable:", e)
                job = None
            if job:
                try:
                    self.ring(job)
                except Exception as e:
                    say("   the call failed:", e)
                    self.hang_up()
                    self.report(job["token"], "ended")
                if self.a.once:
                    return
            time.sleep(2)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Nigoh line rig: an Android phone with a SIM card as the telephone line")
    p.add_argument("--server", default="https://nasa.cartify.ink")
    p.add_argument("--key", default=os.path.join(HERE, "gateway.key"), help="file with the server's GATEWAY_KEY")
    p.add_argument("--adb", default=os.path.join(HERE, "platform-tools", "adb.exe"))
    p.add_argument("--browser", default="", help="path to Edge or Chrome (found automatically if left out)")
    p.add_argument("--page", default="", help="extra settings for the call page, e.g. vad=4 for a quiet line")
    p.add_argument("--ring-seconds", type=int, default=45, help="how long to let it ring")
    p.add_argument("--talk-seconds", type=int, default=420, help="the longest a call may last")
    p.add_argument("--no-speaker", dest="speaker", action="store_false", help="do not switch the phone to loudspeaker (headset cable)")
    p.add_argument("--dry-run", action="store_true", help="no phone and no browser: only the conversation with the server")
    p.add_argument("--check", action="store_true", help="show what the phone and the server answer, then stop")
    p.add_argument("--once", action="store_true", help="stop after one call")
    try:
        Rig(p.parse_args()).run()
    except KeyboardInterrupt:
        say("stopped")
