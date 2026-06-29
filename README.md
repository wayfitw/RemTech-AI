# Ремтехника — корпоративный ИИ-ассистент

Веб-версия ассистента (портирование mybot / inter-assist-bot в браузер).
Стек: **FastAPI + WebSocket** (бэкенд), **React + Vite** (фронтенд), **SQLite**, **Claude Sonnet 4.6**.

> Статус: **Этап 1 — веб-оболочка mybot**. Базовый чат со стримингом, загрузка/скачивание
> файлов, инструменты: веб-поиск, чтение страниц, создание Word/PDF, редактирование
> загруженных .docx, генерация изображений (FLUX) и видео (Kling). Авторизация — пока
> один общий пароль; многопользовательскую + админку делаем в Этапе 2.

## Структура

```
remtechnika-ai/
├── backend/
│   ├── main.py            # FastAPI: REST + WebSocket /ws
│   ├── config.py          # настройки из .env
│   ├── auth.py            # JWT, один общий пароль (Этап 1)
│   ├── db.py              # SQLite: users, conversations, chat_history, uploaded_files, activity_log
│   ├── storage.py         # файлы на диске + записи в БД
│   ├── agent/
│   │   ├── orchestrator.py  # агент-луп (портирован из mybot), стриминг через emit()
│   │   └── tools.py         # схемы инструментов Claude (Этап 1)
│   ├── services/
│   │   ├── replicate_svc.py # FLUX (картинки) + Kling (видео)
│   │   ├── docgen.py        # create_docx (портирован) + create_pdf (reportlab)
│   │   ├── extract.py       # извлечение текста из docx/pdf/xlsx/pptx
│   │   └── websearch.py     # read_url (trafilatura)
│   └── utils/doc_editor.py  # hash-based редактирование .docx (из mybot)
└── frontend/                # React (Vite): логин, чат, drag-and-drop, скачивание
```

## Запуск (разработка)

### 1. Бэкенд
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# заполни ключи в backend\.env (ANTHROPIC_API_KEY, REPLICATE_API_TOKEN)
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

### 2. Фронтенд
```powershell
cd frontend
npm install
npm run dev
```
Открой http://localhost:5173. Пароль по умолчанию — из `APP_PASSWORD` в `backend\.env`
(`remtechnika`). Vite проксирует `/api` и `/ws` на бэкенд (порт 8000).

## Переменные окружения (`backend/.env`)

| Переменная | Назначение |
|---|---|
| `ANTHROPIC_API_KEY` | ключ Claude (обязательно) |
| `REPLICATE_API_TOKEN` | картинки/видео (опционально) |
| `APP_PASSWORD` | общий пароль входа (Этап 1) |
| `JWT_SECRET` | секрет для подписи токенов |
| `PDF_FONT_PATH` | TTF с кириллицей для PDF (по умолчанию Arial/DejaVuSans по ОС) |
| `CORS_ORIGINS` | разрешённые источники фронтенда |

## Дальше по плану

- **Этап 2** — настоящая авторизация (логин/пароль, роли admin/user), изоляция данных, дашборд директора.
- **Этап 3** — база знаний (bge-m3 через Ollama, `search_knowledge_base`).
- **Этап 4** — КП-генератор, тендер-помощник, маркетинг.
- **Этап 5** — деплой на Ubuntu (nginx + HTTPS, Ollama на RTX 3060 Ti).
