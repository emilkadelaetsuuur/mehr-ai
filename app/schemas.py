"""Request bodies. Validation lives here, so handlers only deal with clean values."""

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["homilador", "tuqqan", "chaqaloq", "boshqa"]


class LoginIn(BaseModel):
    username: str = "rahbar"
    password: str = ""


class PasswordIn(BaseModel):
    old: str
    new: str = Field(min_length=6, max_length=100)


class ExtractIn(BaseModel):
    text: str = Field(max_length=4000)
    lang: str = "uz"


class Vitals(BaseModel):
    bp_sys: float | None = Field(None, ge=40, le=300)
    bp_dia: float | None = Field(None, ge=20, le=200)
    hb: float | None = Field(None, ge=20, le=250)
    glucose: float | None = Field(None, ge=0.5, le=60)
    temp: float | None = Field(None, ge=30, le=43)
    pulse: float | None = Field(None, ge=20, le=260)
    breath: float | None = Field(None, ge=5, le=150)

    def values(self):
        return {k: v for k, v in self.model_dump().items() if k in Vitals.model_fields and v is not None}


class ObservationIn(Vitals):
    source: Literal["tahlil", "korik"] = "tahlil"
    complaints: list[str] | None = None
    text: str = Field("", max_length=1000)
    author: str = Field("Laboratoriya", max_length=80)


class CardFields(Vitals):
    full_name: str = Field(min_length=2, max_length=160)
    birth_year: int | None = Field(None, ge=1930, le=2100)
    kind: Kind | None = None
    weeks: int | None = Field(None, ge=1, le=45)
    mahalla: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, max_length=40)
    doctor: str | None = Field(None, max_length=120)
    diagnosis: str | None = Field(None, max_length=240)
    referral: str | None = Field(None, max_length=120)
    complaints: list[str] = []


class ConfirmIn(BaseModel):
    fields: CardFields
    quotes: dict = {}
    transcript: str = Field("", max_length=4000)
    author: str = Field("Hamshira", max_length=80)
    patient_id: int | None = None
    consent: bool = False


class NoteIn(BaseModel):
    note: str = Field("", max_length=500)


class CallIn(BaseModel):
    scenario: str
    lang: Literal["uz", "ru"] | None = None


class DialIn(BaseModel):
    phone: str = Field("", max_length=24)  # empty: the number on the patient's card


class LabImportIn(BaseModel):
    csv: str = Field(max_length=400_000)
