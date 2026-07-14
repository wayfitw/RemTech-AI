"""EPIC-02 (2a) — шлюз моделей (LLM gateway).

Маршрутизация запросов к моделям через реестр model_configs: по алиасу
выбирается провайдер и модель; при сбое основного провайдера — переключение
на fallback. Пока реализован провайдер Anthropic (через прямой API или
обратный прокси egress_proxy_url); Gemini/OpenAI/Yandex/vLLM — в стадии 2b.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

import anthropic

from app import repositories as repo
from app.config import get_settings
from app.logging_config import get_logger

settings = get_settings()
log = get_logger("remtech.llm")
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
    """Фабрика провайдера по имени. Anthropic реализован (в т.ч. через egress-прокси
    base_url). Yandex/vLLM/OpenAI/Gemini — стадия 2b (нужны ключи/локальный сервер)."""
    base_url = settings.egress_proxy_url or None
    if provider in ("anthropic", "claude"):
        return AnthropicProvider(model=model or settings.model,
                                 api_key=settings.anthropic_api_key, base_url=base_url)
    raise NotImplementedError(
        f"Провайдер «{provider}» пока не реализован (стадия 2b: нужны ключи/сервер). "
        f"Настройте агента на доступный провайдер (anthropic).")


@dataclass
class ModelRoute:
    """Разрешённый маршрут модели: основной провайдер/модель + опциональный fallback."""
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


async def resolve_route(s, alias: str | None) -> ModelRoute:
    """Резолвит маршрут по алиасу из model_configs. Сессию передаёт вызывающий слой —
    сам шлюз БД не открывает (issue #18: не течём в чужой слой)."""
    alias = alias or settings.default_model
    cfg = await repo.get_model_config_by_alias(s, alias)
    provider = cfg.provider if cfg else "anthropic"
    model = cfg.endpoint if cfg and cfg.endpoint else settings.model
    fb_provider = fb_model = None
    if cfg and cfg.fallback_to:
        fb = await repo.get_model_config_by_alias(s, cfg.fallback_to)
        if fb:
            fb_provider = fb.provider
            fb_model = fb.endpoint or settings.model
    return ModelRoute(provider, model, fb_provider, fb_model)


class ModelGateway:
    async def run(self, route: ModelRoute, system, tools, messages, on_delta: OnDelta):
        """Выполняет запрос по готовому маршруту: основной провайдер, при сбое —
        fallback. БД не трогает (маршрут уже разрешён вызывающим слоем)."""
        try:
            return await make_provider(route.provider, route.model).run(
                system, tools, messages, on_delta)
        except Exception as primary:
            # #15/#21 — не глотаем первопричину: при недоступном fallback пробрасываем
            # именно ИСХОДНУЮ ошибку основного провайдера.
            log.warning("provider '%s' failed: %s: %s", route.provider,
                        type(primary).__name__, primary)
            if route.fallback_provider:
                try:
                    log.info("switching to fallback provider '%s'", route.fallback_provider)
                    return await make_provider(route.fallback_provider, route.fallback_model).run(
                        system, tools, messages, on_delta)
                except Exception as fb_err:
                    log.warning("fallback '%s' unavailable: %s: %s", route.fallback_provider,
                                type(fb_err).__name__, fb_err)
            raise primary


gateway = ModelGateway()
