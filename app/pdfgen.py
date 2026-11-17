"""Referral PDF (yo'llanma) built from the confirmed card. Sample layout: the approved clinic
form replaces it once the ministry template is provided."""
import io
import os
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A5
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import config, core

_F = {"ok": False}
for d in ("/usr/share/fonts/truetype/dejavu/", os.path.join(os.path.dirname(__file__), "fonts/")):
    if os.path.exists(d + "DejaVuSans.ttf") and not _F["ok"]:
        pdfmetrics.registerFont(TTFont("DV", d + "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DVB", d + "DejaVuSans-Bold.ttf"))
        _F["ok"] = True
R, B = ("DV", "DVB") if _F["ok"] else ("Helvetica", "Helvetica-Bold")
ZC = {"red": "#c62828", "yellow": "#b7791f", "green": "#1b7f4b"}


def referral(p, lang="uz"):
    uz = lang != "ru"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A5)
    W, H = A5
    c.setFillColor(HexColor("#0b3f3c"))
    c.rect(0, H - 62, W, 62, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(B, 15)
    c.drawString(24, H - 30, "YO'LLANMA" if uz else "НАПРАВЛЕНИЕ")
    c.setFont(R, 8)
    c.drawString(24, H - 46, f"Nigoh · {config.DISTRICT} · {datetime.utcnow():%d.%m.%Y}")
    c.drawRightString(W - 24, H - 30, f"№ {p.id:05d}")
    y = H - 86

    def row(label, value, bold=False):
        nonlocal y
        if not value:
            return
        c.setFillColor(HexColor("#5b6675"))
        c.setFont(R, 8)
        c.drawString(24, y, label)
        c.setFillColor(HexColor("#1c2430"))
        c.setFont(B if bold else R, 10.5)
        words, line, yy = str(value).split(), "", y - 13
        for w in words:
            if pdfmetrics.stringWidth(line + " " + w, B if bold else R, 10.5) > W - 48:
                c.drawString(24, yy, line)
                line, yy = w, yy - 13
            else:
                line = (line + " " + w).strip()
        c.drawString(24, yy, line)
        y = yy - 15

    data, _, _ = core.merged(p)
    row("Bemor" if uz else "Пациент", p.full_name, True)
    row("Tug'ilgan yili" if uz else "Год рождения", p.birth_year)
    row("Mahalla" if uz else "Махалля", p.mahalla)
    row("Telefon" if uz else "Телефон", p.phone)
    if p.weeks:
        row("Homiladorlik muddati" if uz else "Срок беременности", f"{p.weeks} {'hafta' if uz else 'нед.'}")
    vals = []
    if data.get("bp_sys"):
        vals.append(f"{'QB' if uz else 'АД'} {int(data['bp_sys'])}/{int(data.get('bp_dia') or 0)}")
    if data.get("hb"):
        vals.append(f"Hb {data['hb']:g} g/l")
    if data.get("temp"):
        vals.append(f"t {data['temp']:g} °C")
    if data.get("glucose"):
        vals.append(f"{'qand' if uz else 'сахар'} {data['glucose']:g}")
    row("Ko'rsatkichlar" if uz else "Показатели", ", ".join(vals))
    cs = [rules_label(x, uz) for x in data.get("complaints", [])]
    row("Shikoyatlar" if uz else "Жалобы", ", ".join(cs))
    row("Tashxis (shifokor aytgan)" if uz else "Диагноз (со слов врача)", p.diagnosis)
    zone = p.zone or "green"
    c.setFillColor(HexColor(ZC[zone]))
    c.roundRect(24, y - 22, W - 48, 24, 4, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(B, 10)
    c.drawString(32, y - 14, ("Xavf zonasi: " if uz else "Зона риска: ") + (core.ZONE_UZ if uz else core.ZONE_RU)[zone])
    y -= 40
    for r in (p.reasons or [])[:5]:
        c.setFillColor(HexColor("#1c2430"))
        c.setFont(R, 9)
        c.drawString(28, y, f"• {r['uz' if uz else 'ru']} {r['value']}  ({r['rule']})"[:95])
        y -= 13
    y -= 6
    row("Yo'llanma" if uz else "Куда направляется", getattr(p, "_referral", None) or ("Mutaxassis ko'rigi" if uz else "Осмотр специалиста"), True)
    row("Oilaviy shifokor" if uz else "Семейный врач", p.doctor)
    c.setFillColor(HexColor("#5b6675"))
    c.setFont(R, 7)
    foot = ("Hujjat Nigoh tizimida tasdiqlangan karta asosida tuzildi. Zona klinik protokol qoidalari bo'yicha hisoblangan; "
            "qarorni shifokor qabul qiladi. Namuna shakl." if uz else
            "Документ сформирован в системе Nigoh по подтверждённой карточке. Зона рассчитана по правилам протокола; "
            "решение принимает врач. Образец формы.")
    c.drawString(24, 40, foot[:118])
    c.drawString(24, 30, foot[118:236])
    c.line(W - 190, 64, W - 24, 64)
    c.drawRightString(W - 24, 54, "imzo / подпись")
    c.showPage()
    c.save()
    return buf.getvalue()


def rules_label(code, uz):
    from .rules import COMPLAINTS
    t = COMPLAINTS.get(code)
    return (t[0] if uz else t[1]) if t else code
