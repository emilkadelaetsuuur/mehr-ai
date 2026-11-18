"""Database models. SQLite for local runs, PostgreSQL in production (same code)."""

import os
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from . import config

if config.DATABASE_URL.startswith("sqlite"):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def now():
    return datetime.utcnow()


class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True)
    full_name = Column(String(160), nullable=False, index=True)
    birth_year = Column(Integer)
    kind = Column(String(20), default="homilador")  # homilador | tuqqan | chaqaloq | boshqa
    weeks = Column(Integer)  # gestation weeks (homilador)
    born_at = Column(DateTime)  # chaqaloq: date of birth
    mother_id = Column(Integer, ForeignKey("patients.id"))
    mahalla = Column(String(80), index=True)
    phone = Column(String(40))
    doctor = Column(String(120))
    lang = Column(String(4), default="uz")
    zone = Column(String(10), default="green", index=True)  # red | yellow | green
    reasons = Column(JSON, default=list)
    diagnosis = Column(String(240))  # as dictated by a doctor, never produced by AI
    discharged_at = Column(DateTime)
    consent_at = Column(DateTime)  # consent to data processing and AI calls; no consent -> no calls
    last_contact_at = Column(DateTime, default=now)
    created_at = Column(DateTime, default=now)
    observations = relationship("Observation", back_populates="patient", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="patient", cascade="all, delete-orphan")
    calls = relationship("Call", back_populates="patient", cascade="all, delete-orphan")


class Observation(Base):
    __tablename__ = "observations"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True)
    source = Column(String(20))  # tahlil | ovoz | qongiroq | korik | chiqarish
    data = Column(JSON, default=dict)  # bp_sys, bp_dia, hb, glucose, temp, pulse, complaints[]
    quotes = Column(JSON, default=dict)  # field -> exact words it was taken from
    text = Column(Text)  # transcript or note
    author = Column(String(80))
    created_at = Column(DateTime, default=now, index=True)
    patient = relationship("Patient", back_populates="observations")


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True)
    from_zone = Column(String(10))
    to_zone = Column(String(10))
    reasons = Column(JSON, default=list)
    created_at = Column(DateTime, default=now)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True)
    type = Column(String(30))  # faol_chaqiruv | mutaxassis | hamshira_tashrif
    role = Column(String(20))  # shifokor | mutaxassis | hamshira
    reason = Column(String(240))
    due_at = Column(DateTime)
    status = Column(String(20), default="ochiq", index=True)  # ochiq | bajarildi | tasdiqlandi | nomuvofiq
    escalated = Column(Boolean, default=False)
    note = Column(Text)
    created_at = Column(DateTime, default=now)
    done_at = Column(DateTime)
    patient = relationship("Patient", back_populates="tasks")


class Call(Base):
    __tablename__ = "calls"
    id = Column(Integer, primary_key=True)
    token = Column(String(40), unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    scenario = Column(String(40))
    lang = Column(String(4), default="uz")
    status = Column(String(20), default="rejalashtirilgan")  # rejalashtirilgan | jarayonda | tugadi | javobsiz
    attempts = Column(Integer, default=0)
    answers = Column(JSON, default=dict)  # qid -> {value, transcript, flag}
    flags = Column(JSON, default=list)
    closing = Column(Text)  # the last words the patient heard
    closing_by = Column(String(10))  # claude | shablon
    planned_at = Column(DateTime, default=now)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=now)
    patient = relationship("Patient", back_populates="calls")


class Notice(Base):
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id"))
    role = Column(String(20))  # who should see it
    level = Column(String(10))  # red | yellow | info
    text_uz = Column(String(400))
    text_ru = Column(String(400))
    created_at = Column(DateTime, default=now, index=True)


class AuditLog(Base):
    """Who did what: every write that touches a patient is recorded (role, action, short detail)."""

    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=now, index=True)
    role = Column(String(20))
    actor = Column(String(60))  # username of the account that did it
    action = Column(String(40))
    patient_id = Column(Integer, index=True)
    detail = Column(String(400))


class User(Base):
    """A personal staff account. The role comes from the account, not from a switch in the interface."""

    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(40), unique=True, index=True)
    full_name = Column(String(120))
    role = Column(String(20))  # rahbar | mutaxassis | shifokor | hamshira
    doctor_name = Column(String(120))  # a family doctor sees the tasks of their own patients
    password_hash = Column(String(200))
    telegram_chat_id = Column(String(40))
    link_code = Column(String(20))  # one-time code that binds a Telegram chat to the account


class Meta(Base):
    __tablename__ = "meta"
    key = Column(String(40), primary_key=True)
    value = Column(String(200))


SCHEMA_VERSION = "5"


def init_db():
    """Create tables. The demo holds synthetic data only, so a schema change simply rebuilds it
    (a real deployment would use Alembic migrations instead)."""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        row = db.get(Meta, "schema")
        if row and row.value == SCHEMA_VERSION:
            return
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.merge(Meta(key="schema", value=SCHEMA_VERSION))
        db.commit()
