"""Дайджест новостей по ИИ (#42): форматирование, дедуп внутри выпуска, веб-лента."""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.orchestrator as orch
from app import repositories as repo
from app.config import get_settings


def _bind(monkeypatch):
    url = get_settings().database_url.rsplit("/", 1)[0] + "/remtech_test"
    monkeypatch.setattr(orch, "SessionLocal",
                        async_sessionmaker(create_async_engine(url), expire_on_commit=False))


async def _noop(_e):
    pass


async def test_ai_news_digest_formats_dedups_and_posts(session, monkeypatch):
    _bind(monkeypatch)
    res = await orch.Orchestrator()._execute_tool(
        "ai_news_digest",
        {"title": "ИИ за сутки", "items": [
            {"text": "OpenAI выпустил модель", "url": "http://a"},
            {"text": "OpenAI выпустил модель", "url": "http://a"},   # дубль → отсеять
            {"text": "Google представил Gemini", "url": "http://b"}]},
        _noop, 1, None, None)
    assert "OpenAI выпустил модель" in res and "Google представил Gemini" in res
    assert res.count("•") == 2                       # дубль отсеян
    async with orch.SessionLocal() as s:             # опубликовано в веб-ленту
        notes = await repo.list_notifications(s, "руководство")
    assert any("ИИ за сутки" in n.title for n in notes)


async def test_ai_news_digest_empty(session, monkeypatch):
    _bind(monkeypatch)
    res = await orch.Orchestrator()._execute_tool(
        "ai_news_digest", {"items": []}, _noop, 1, None, None)
    assert "не набралось" in res.lower()
