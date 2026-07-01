"""EPIC-02 (2a) — шлюз моделей (LLM gateway).

Маршрутизация запросов к моделям через реестр model_configs: по алиасу
выбирается провайдер и модель; при сбое основного провайдера — переключение
на fallback. Пока реализован провайдер Anthropic (через прямой API или
обратный прокси egress_proxy_url); Gemini/OpenAI/Yandex/vLLM — в стадии 2b.
"""
from typing import Awaitable, Callable

import anthropic

from app import repositories as repo
from app.config import get_settings
from app.database import SessionLocal

settings = get_settings()
OnDelta = Callable[[str], Awaitable[None]]


class AnthropicProvider:
    """Провайдер Anthropic (Claude). base_url задаёт обратный прокси, если указан."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None):
        self.model = model
        kwargs = {"api_key": api_key or "missing"}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def run(self, system, tools, messages, on_delta: OnDelta):
        async with self.client.messages.stream(
            model=self.model, max_tokens=settings.max_tokens,
            system=system, tools=tools, messages=messages, timeout=120.0,
        ) as stream:
            async for chunk in stream.text_stream:
                await on_delta(chunk)
            return await stream.get_final_message()


def make_provider(provider: str, model: str):
    """Фабрика провайдера по имени. Расширяется в стадии 2b (LiteLLM/Yandex/vLLM)."""
    base_url = settings.egress_proxy_url or None
    if provider in ("anthropic", "claude"):
        return AnthropicProvider(model=model or settings.model,
                                 api_key=settings.anthropic_api_key, base_url=base_url)
    raise NotImplementedError(f"Провайдер «{provider}» пока не реализован (стадия 2b)")


async def _load_config(alias: str):
    async with SessionLocal() as s:
        return await repo.get_model_config_by_alias(s, alias)


class ModelGateway:
    async def run(self, alias: str | None, system, tools, messages, on_delta: OnDelta):
        """Маршрутизирует запрос: основной провайдер по алиасу (или дефолт),
        при сбое — fallback из model_configs."""
        alias = alias or settings.default_model
        cfg = await _load_config(alias)
        provider_name = cfg.provider if cfg else "anthropic"
        model = (cfg.endpoint if cfg and cfg.endpoint else settings.model)
        fallback = cfg.fallback_to if cfg else None

        try:
            return await make_provider(provider_name, model).run(system, tools, messages, on_delta)
        except Exception:
            if fallback:
                fb = await _load_config(fallback)
                if fb:
                    return await make_provider(
                        fb.provider, fb.endpoint or settings.model
                    ).run(system, tools, messages, on_delta)
            raise


gateway = ModelGateway()
