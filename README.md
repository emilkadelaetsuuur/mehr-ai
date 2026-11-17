# Nigoh — ona va bola: xavf guruhini nazoratdan chiqarmaslik

Umummilliy AI Xakaton, Toshkent bosqichi, «Tibbiyot» treki. Sog'liqni saqlash vazirligi ro'yxatidagi uchta muammo bitta oqimda:

| № | Muammo | Nigoh nima qiladi |
|---|--------|-------------------|
| 9 | Homilador va chaqaloqlar monitoringi: tahlil yomonlashsa, mutaxassis kech biladi | Reyestr, «qizil / sariq / yashil» zonalar, soniyalar ichida bildirishnoma |
| 10 | Smartfon va internet yo'q qishloqlar | Hamshira ovoz bilan aytadi — AI kartani to'ldiradi (oflayn navbat bilan); AI bemorga o'zi qo'ng'iroq qiladi |
| 11 | Shifoxonadan chiqqan og'ir bemor nazoratsiz qoladi | «Faol chaqiruv»: 24 soatlik taymer, tasdiq, eskalatsiya, bemorning o'zi tasdiqlaydi |

## Qanday ishlaydi

`Signal → Ma'lumot → Zona → Vazifa → Nazorat`

1. **Signal**: laboratoriya tahlili, hamshiraning ovozi, AI qo'ng'iroqdagi javob, shifoxonadan chiqarish.
2. **Ma'lumot**: nutq → matn (VoiceLab STT, o'zbek/rus) → LLM maydonlarni ajratadi → **kod har bir iqtibosni matndan tekshiradi**; topilmagan maydon olib tashlanadi.
3. **Zona**: faqat qoidalar (`app/rules.json`) belgilaydi; har bir sabab qiymat, qoida va iqtibos bilan ko'rsatiladi. ML (RandomForest, UCI Maternal Health Risk) — faqat ikkinchi fikr.
4. **Vazifa**: mutaxassis yoki oilaviy shifokorga 24 soatlik taymer bilan.
5. **Nazorat**: shifokor tashrifni belgilaydi → AI bemordan «shifokor keldimi?» deb so'raydi → nomuvofiqlik rahbarga chiqadi.

Qo'ng'iroq ssenariylari — fayllar (`app/scenarios/*.json`): yangi bemor guruhi = yangi fayl, kod o'zgarmaydi.
Chaqaloq ssenariysi JSST jadvaliga tayanadi: 3-kun, 7–14-kun, 6-hafta; savollar — chaqaloqdagi xavf belgilari.

## Texnologiyalar

FastAPI · SQLAlchemy · PostgreSQL · Docker Compose · VoiceLab (STT, TTS, LLM) · scikit-learn · ReportLab · PWA (service worker + IndexedDB oflayn navbat) · build bosqichisiz JS.

## Ishga tushirish

```bash
cp .env.example .env        # VOICELAB_API_KEY va parollarni kiriting
docker compose up -d --build
docker compose exec app python -m scripts.eval   # kartani to'ldirish aniqligini o'lchash
docker compose exec app pytest -q                # testlar (VoiceLab kerak emas)
```

Kalitsiz ham ishlaydi: nutq o'rniga matn kiritiladi, maydonlarni qoidalar ajratadi, qo'ng'iroqda tugmalar ishlaydi.

## Tuzilishi

```
app/main.py        API
app/core.py        zonalar, vazifalar, taymerlar, qo'ng'iroqlar, tashrif tasdig'i
app/rules.py/.json izohlanadigan qoidalar va chegaralar
app/extract.py     LLM ajratish + iqtibos tekshiruvi + zaxira parser
app/voicelab.py    VoiceLab mijozi (STT / TTS / LLM)
app/ml.py          ML ikkinchi fikr
app/scenarios/     qo'ng'iroq ssenariylari
web/               interfeys (o'zbekcha / ruscha), bemor uchun qo'ng'iroq sahifasi
scripts/eval.py    aniqlik o'lchovi
tests/             testlar
```

## Chegaralar

- Tashxis va davolash qarorini shifokor qabul qiladi; AI hisoblaydi, eslatadi, yetkazadi.
- AI qo'ng'iroqda o'zini AI deb tanishtiradi, davolash bo'yicha maslahat bermaydi, xavf belgisida 103 ni aytadi.
- Barcha ma'lumotlar sintetik. Ovoz yozuvi saqlanmaydi (transkripsiya olingach, o'chiriladi).
- Zona chegaralari — umumiy mo'ljal; yakuniy qiymatlarni shifokor milliy klinik protokol bo'yicha tasdiqlaydi.
- Haqiqiy telefon tarmog'i (SIP) ulanmagan: namoyishda qo'ng'iroq havola yoki QR orqali ochiladi; dialog mantig'i bir xil.
