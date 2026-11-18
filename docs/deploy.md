# Запуск и выкладка

## Docker Compose

```bash
cp .env.example .env              # задайте POSTGRES_PASSWORD, SECRET_KEY, DEMO_PASSWORD
docker compose up -d --build      # приложение: http://localhost:18700
docker compose exec app pytest -q # тесты
docker compose exec app python -m scripts.eval   # замер точности заполнения карты
```

При первом запуске создаётся синтетическая база (400 пациентов). Пересоздать её можно под руководителем: «Tizim haqida» → сброс демо-данных.

## Без Docker

Нужен Python 3.12. База — SQLite в `./data`.

```bash
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload     # http://localhost:8000
pytest -q
```

## Переменные окружения

Все настройки с пояснениями — в [`.env.example`](../.env.example). Обязательны только `POSTGRES_PASSWORD`, `SECRET_KEY` и `DEMO_PASSWORD`. Остальное включает дополнительные возможности:

| Переменные | Что включают |
|------------|--------------|
| `VOICELAB_*` | распознавание и озвучка речи, языковая модель для ответов |
| `ANTHROPIC_API_KEY`, `CLAUDE_*` | заключительные слова звонка и ответы пациенту от Claude |
| `DMED_*` | обмен с настоящей платформой DMED вместо тестовой среды |
| `TELEGRAM_*` | уведомления сотрудникам в Telegram |
| `GATEWAY_KEY` | стенд «Android-телефон с SIM-картой» |
| `TWILIO_*` | звонки через голосовой API, совместимый с Twilio |

## Выкладка на сервер

Сервер общий с другими сайтами, поэтому образ на нём не собирается: код монтируется поверх готового образа (`deploy/compose.mount.yml`).

```bash
/opt/nigoh/release.sh /opt/nigoh/<архив>.tgz <sha256>
```

[`deploy/release.sh`](../deploy/release.sh) распаковывает архив, перезапускает приложение, доставляет новые пакеты, ждёт `/api/health`, запускает тесты и проверяет вход всех четырёх ролей. Если приложение не поднялось, возвращает предыдущую версию. Данные сохраняются. Простой при выкладке — около двух минут.

## Тесты

`tests/test_core.py` — 27 тестов предметных правил: зоны и их причины, удержание красной зоны, согласия, адресаты сценариев, проверка личности в звонке, ответы по памятке, события из DMED, календарь прививок, конфиденциальные группы, роли, защита от перегрузки. Тесты не обращаются к VoiceLab, Claude и DMED и работают на отдельной SQLite.
