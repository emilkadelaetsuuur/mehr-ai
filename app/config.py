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

DISTRICT = os.getenv("DISTRICT_NAME", "Namuna tumani")
ACTIVE_CALL_HOURS = int(os.getenv("ACTIVE_CALL_HOURS", "24"))
SILENT_DAYS = int(os.getenv("SILENT_DAYS", "7"))

# Real phone line (optional). Any Twilio-compatible voice API; without these the call opens by link or QR.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM = os.getenv("TWILIO_FROM", "").strip()
TWILIO_API = os.getenv("TWILIO_API", "https://api.twilio.com").rstrip("/")
SESSION_DAYS = 14
