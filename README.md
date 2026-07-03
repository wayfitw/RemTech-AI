# Ремтехника — корпоративный ИИ-ассистент (RemTech-AI)

Веб-версия ассистента для компании «Ремтехника» (дилер спецтехники XCMG и запчастей).
Порт Telegram-бота mybot / inter-assist-bot в браузер с многопользовательским доступом,
ролями и базой знаний.

Стек: **FastAPI + WebSocket** (бэкенд, async), **React + Vite** (фронтенд),
**PostgreSQL + pgvector** (данные и векторный поиск), **Claude** (через шлюз моделей),
**bge-m3 через Ollama** (эмбеддинги для RAG). Оркестрация — Docker Compose (postgres,
redis, api, caddy).

> Статус: Этап 1 (фундамент) завершён; Этап 2 (шлюз моделей + агенты + база знаний) —
> в работе. Многопользовательская авторизация по логину/паролю с ролями (admin/user) и
> JWT; регистрация — только по приглашению (первый зарегистрированный становится админом).

## Структура

```
remtechnika-ai/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI: REST + WebSocket /ws (точка входа: app.main:app)
│   │   ├── config.py        # pydantic-settings из .env (гейт секретов в production)
│   │   ├── database.py      # SQLAlchemy 2.0 async + asyncpg, get_db, init_extensions
│   │   ├── models.py        # модели по ER (users, conversations, chat_history, …, kb_*, agents, model_configs)
│   │   ├── repositories.py  # async CRUD и аналитика
│   │   ├── auth.py          # JWT (HS256), pbkdf2, регистрация по приглашению, RBAC
│   │   ├── orchestrator.py  # агент-луп, стриминг через emit(), tool-use
│   │   ├── llm.py           # ModelGateway: выбор провайдера по alias + fallback
│   │   ├── embeddings.py    # OllamaEmbedder (bge-m3) / FakeEmbedder (тесты)
│   │   ├── kb.py            # чанкинг + ингест + поиск (pgvector, фильтр по ролям)
│   │   └── storage.py       # файлы на диске + записи в БД
│   ├── agent/tools.py       # схемы инструментов
│   ├── services/            # docgen, reports, extract, websearch, replicate_svc
│   ├── alembic/             # миграции схемы
│   └── tests/               # pytest (REST/RBAC/IDOR, auth, репозитории, RAG, миграции)
├── frontend/                # React (Vite): логин, чат со стримингом, админка
├── deploy/                  # caddy/Caddyfile, postgres/init
└── docker-compose.yml
```

## Запуск через Docker Compose (целевой стек)

Поднимает `postgres` (pgvector), `redis`, `api` (FastAPI) и `caddy` (HTTPS в ЛВС):

```bash
# 1. Заполни секреты (ANTHROPIC_API_KEY, сильный JWT_SECRET, креды Postgres)
cp backend/.env.example backend/.env

# 2. Собери фронтенд (Caddy раздаёт frontend/dist)
cd frontend && npm install && npm run build && cd ..

# 3. Подними стек (api стартует с APP_ENV=production → гейт секретов активен)
docker compose up -d --build

# Проверка:
curl http://localhost/api/health      # {"status":"ok"}
```

`postgres` инициализируется с расширением `pgvector` (см. `deploy/postgres/init`).
Миграции Alembic применяются при старте контейнера `api` (`alembic upgrade head`).

## Запуск (локальная разработка без Docker)

### 1. Бэкенд
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# нужен запущенный Postgres+pgvector (docker compose up -d postgres) и заполненный .env
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```
Первый вход: открой фронтенд и зарегистрируйся — первый аккаунт получит роль `admin`,
дальше пользователей заводит администратор в панели.

### 2. Фронтенд
```powershell
cd frontend
npm install
npm run dev
```
Открой http://localhost:5173. Vite проксирует `/api` и `/ws` на бэкенд (порт 8000).

## База знаний (RAG) — эмбеддинги bge-m3 через Ollama

Для векторизации документов нужен локальный эмбеддер **bge-m3** (бесплатно, данные
не покидают контур — 152-ФЗ):

```bash
ollama serve            # установить Ollama (ollama.com) и запустить сервер
ollama pull bge-m3      # скачать модель эмбеддингов (~1.2 ГБ)
```
В `.env` (по умолчанию уже так): `EMBED_BACKEND=ollama`, `OLLAMA_URL=http://localhost:11434`,
`EMBED_MODEL=bge-m3`. Для тестов/без GPU: `EMBED_BACKEND=fake` (детерминированный эмбеддер).
Загрузка документов — `POST /api/admin/kb/upload` (только admin); поиск — инструмент
`search_knowledge_base` в агенте (фильтр по ролям).

## Переменные окружения

Полный список с комментариями — в `backend/.env.example`. Ключевые:

| Переменная | Назначение |
|---|---|
| `APP_ENV` | `development` / `production` (в prod включается гейт обязательных секретов) |
| `JWT_SECRET` | секрет подписи JWT (в prod — не дефолт, ≥32 символов) |
| `JWT_TTL_HOURS` | срок жизни токена |
| `DATABASE_URL` | async-строка Postgres (`postgresql+asyncpg://…`) |
| `REDIS_URL` | адрес Redis |
| `ANTHROPIC_API_KEY` | ключ Claude |
| `DEFAULT_MODEL` / `FALLBACK_MODEL` | алиасы моделей в реестре `model_configs` |
| `EMBED_BACKEND` / `OLLAMA_URL` / `EMBED_MODEL` | эмбеддер для RAG |
| `CORS_ORIGINS` | разрешённые источники фронтенда (в prod обязателен) |

## Тесты и CI

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```
CI (GitHub Actions): ruff + pytest (Postgres+pgvector сервис) для бэкенда и `npm run build`
для фронтенда. Тесты используют отдельную БД `remtech_test`, миграции — `remtech_migtest`.

## Этапы

- **Этап 1** — фундамент: Docker Compose, async-БД + миграции, модели по ER, JWT + RBAC, IDOR-защита, CI. ✅
- **Этап 2** — шлюз моделей (реестр/fallback), агенты-модули (конструктор + выбор в чате), база знаний (RAG). 🔄
- **Этап 3** — TEI (bge-m3 + reranker) на GPU, Celery-конвейер ингеста, HNSW-индекс.
- **Этап 4** — модули: КП-генератор, тендер-помощник, маркетинг, сервис.
- **Этап 5** — деплой в ЛВС (Caddy + HTTPS, egress-прокси, Yandex-fallback, локальный vLLM).
