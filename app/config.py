"""Runtime settings. Everything comes from the environment; nothing secret lives in code."""

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/nigoh.db")
DATA_DIR = os.getenv("DATA_DIR", "./data")

VOICELAB_API_KEY = os.getenv("VOICELAB_API_KEY", "").strip()
VOICELAB_BASE = os.getenv("VOICELAB_BASE", "https://api.voicelab.uz").rstrip("/")
VOICELAB_LLM_MODEL = os.getenv("VOICELAB_LLM_MODEL", "").strip()
VOICELAB_VOICE_UZ = os.getenv("VOICELAB_VOICE_UZ", "").strip()
VOICELAB_VOICE_RU = os.getenv("VOICELAB_VOICE_RU", "").strip()
VOICELAB_TTS_MODEL = os.getenv("VOICELAB_TTS_MODEL", "").strip()

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "").strip()  # empty = open demo
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DISTRICT = os.getenv("DISTRICT_NAME", "").strip()
if DISTRICT.casefold() == "namuna tumani":  # legacy demo configuration
    DISTRICT = ""
ACTIVE_CALL_HOURS = int(os.getenv("ACTIVE_CALL_HOURS", "24"))
SILENT_DAYS = int(os.getenv("SILENT_DAYS", "7"))

# Real phone line (optional). Any Twilio-compatible voice API; without these the call opens by link or QR.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM = os.getenv("TWILIO_FROM", "").strip()
TWILIO_API = os.getenv("TWILIO_API", "https://api.twilio.com").rstrip("/")
SESSION_DAYS = 14

# The polyclinic's own number, shown to a caller who asks for a person (optional).
CLINIC_PHONE = os.getenv("CLINIC_PHONE", "").strip()
# Key of the rig that rings through a phone with a SIM card (app/simline.py); empty: no rig.
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "").strip()
APPEAL_HOURS = int(os.getenv("APPEAL_HOURS") or "24")  # time to answer a patient's message

# Claude words the closing of a call (optional). The key itself is read by the SDK from ANTHROPIC_API_KEY.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "").strip() or "claude-opus-5-5"
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT") or "6")  # seconds a caller may wait for Claude before the other writer's text is used
CLAUDE_CLOSING = os.getenv("CLAUDE_CLOSING", "1").strip() != "0"
# Languages in which Claude words the closing. Elsewhere, and when Claude is late, the VoiceLab model writes it.
CLAUDE_LANGS = [x.strip() for x in (os.getenv("CLAUDE_LANGS") or "uz,ru").split(",") if x.strip()]
VOICELAB_CLOSING = os.getenv("VOICELAB_CLOSING", "1").strip() != "0"
VOICELAB_CLOSING_TIMEOUT = float(os.getenv("VOICELAB_CLOSING_TIMEOUT") or "7")
# DMED, the national digital health platform. Empty address: the stand-in inside this system ("sinov muhiti").
DMED_BASE_URL = os.getenv("DMED_BASE_URL", "").strip().rstrip("/")  # the platform's FHIR address, e.g. its playground
DMED_TOKEN = os.getenv("DMED_TOKEN", "").strip()  # access token of the client registered at the platform's sign-on server
DMED_INBOUND_KEY = os.getenv("DMED_INBOUND_KEY", "").strip()  # what DMED must present when it sends events here
DMED_PINFL_SYSTEM = os.getenv("DMED_PINFL_SYSTEM", "urn:uz:pinfl").strip()  # the identifier system for PINFL: take it from the platform's guide
