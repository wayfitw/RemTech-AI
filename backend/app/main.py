"""FastAPI-приложение RemTech-AI: сборка из доменных роутеров (issue #18).

Ранее весь REST/WS был одним монолитом (~660 строк). Теперь эндпоинты разнесены
по роутерам (auth/chat/files/admin/kb/ws), общие зависимости — в app/deps.py,
схемы — в app/schemas.py.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import cookies
from app import repositories as repo
from app.config import get_settings
from app.database import SessionLocal, init_extensions

# Переэкспорт для тестов и обратной совместимости (app.main.<name>).
from app.deps import (  # noqa: F401
    _login_limiter,
    _register_limiter,
    _ws_limiter,
    embedder_dep,
    role_can_use_agent,
)
from app.routers import admin, auth, chat, files, kb, ws

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_extensions()
    # Сид моделей шлюза: основная (claude) + реальный резерв (claude-fast, тот же
    # провайдер, быстрая модель) — issue #21. Yandex/vLLM-провайдеры — стадия 2b.
    async with SessionLocal() as s:
        if not await repo.get_model_config_by_alias(s, settings.default_model):
            if not await repo.get_model_config_by_alias(s, settings.fallback_model):
                await repo.create_model_config(
                    s, settings.fallback_model, "anthropic", settings.model_fast, None)
            await repo.create_model_config(
                s, settings.default_model, "anthropic",
                settings.model, settings.fallback_model)
            await s.commit()
    yield


app = FastAPI(title="Remtechnika AI", lifespan=lifespan)

# CORS: только явный whitelist источников; без фолбэка на "*". JWT — в заголовке
# Authorization, cookie не используются → allow_credentials=False.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# #4 — CSRF-защита при cookie-аутентификации (double-submit). Bearer-запросы
# (API-клиенты) не требуют CSRF: заголовок Authorization кросс-сайтом не подделать.
_CSRF_EXEMPT = {"/api/login", "/api/register", "/api/refresh", "/api/auth/status", "/api/health"}


@app.middleware("http")
async def _csrf_guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path not in _CSRF_EXEMPT:
        has_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        has_cookie = request.cookies.get(settings.auth_cookie_name)
        if has_cookie and not has_bearer and not cookies.csrf_ok(request):
            return JSONResponse({"detail": "CSRF проверка не пройдена"}, status_code=403)
    return await call_next(request)


for _router in (auth.router, chat.router, files.router, admin.router, kb.router, ws.router):
    app.include_router(_router)

# Раздача собранного фронта тем же процессом (single-origin: /, /api, /ws на одном
# домене — удобно для демо-туннеля и прод-развёртывания без отдельного веб-сервера).
# Монтируется ПОСЛЕ роутеров, поэтому /api и /ws имеют приоритет. Включается только
# если сборка есть (frontend/dist). html=True → SPA отдаёт index.html.
import os as _os  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = _os.path.join(_os.path.dirname(__file__), "..", "..", "frontend", "dist")
if _os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
