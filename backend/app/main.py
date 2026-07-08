"""FastAPI-приложение RemTech-AI: сборка из доменных роутеров (issue #18).

Ранее весь REST/WS был одним монолитом (~660 строк). Теперь эндпоинты разнесены
по роутерам (auth/chat/files/admin/kb/ws), общие зависимости — в app/deps.py,
схемы — в app/schemas.py.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

for _router in (auth.router, chat.router, files.router, admin.router, kb.router, ws.router):
    app.include_router(_router)
