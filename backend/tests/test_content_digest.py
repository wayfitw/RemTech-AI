"""TASK-0905 (#47) — контент-дайджест ТГ-каналов: сборка выпуска на фикстурах,
дедуп между выпусками, устойчивость к недоступности источника, управление каналами."""
import types

from app import repositories as repo
from services import content_digest

TOPICS = [
    {"topic": "Рост спроса на экскаваторы XCMG", "summary": "В канале обсуждают поставки",
     "source": "@spectehnika"},
    {"topic": "Дефицит запчастей LiuGong", "summary": "Сроки поставки выросли",
     "source": "@zapchasti"},
]


def _collect(text="публикации"):
    async def _c(channels, hours):
        return text
    return _c


def _llm(topics):
    async def _l(text, s):
        return list(topics)
    return _l


async def _setup_channel(session, ref="@spectehnika"):
    await repo.add_content_channel(session, ref, "Спецтехника")
    await session.commit()


# ── сборка выпуска ────────────────────────────────────────────────────────────

async def test_digest_publishes_topics_to_feed(session, monkeypatch):
    await _setup_channel(session)
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(
                            content_digest_enabled=True, content_digest_hours=24,
                            content_digest_role_list=["маркетинг"], telegram_allowmap={}))
    r = await content_digest.run_once(session, collect=_collect(), llm_summarize=_llm(TOPICS),
                                      deliver_tg=False)
    assert r["published"] == 2 and r["skipped"] is None
    assert "Рост спроса" in r["text"] and "@spectehnika" in r["text"]
    notes = await repo.list_notifications(session, "маркетинг")
    assert any("Темы для контента" in n.title for n in notes)   # доставка в веб-ленту


async def test_digest_dedups_between_issues(session, monkeypatch):
    # вторая сборка с теми же темами → ничего нового (дедуп МЕЖДУ выпусками)
    await _setup_channel(session)
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(
                            content_digest_enabled=True, content_digest_hours=24,
                            content_digest_role_list=["маркетинг"], telegram_allowmap={}))
    first = await content_digest.run_once(session, collect=_collect(), llm_summarize=_llm(TOPICS),
                                          deliver_tg=False)
    assert first["published"] == 2
    second = await content_digest.run_once(session, collect=_collect(), llm_summarize=_llm(TOPICS),
                                           deliver_tg=False)
    assert second["published"] == 0 and second["skipped"] == "all_duplicates"
    # новая тема в следующем выпуске проходит
    third = await content_digest.run_once(
        session, collect=_collect(),
        llm_summarize=_llm(TOPICS + [{"topic": "Сервис 24/7 как преимущество"}]),
        deliver_tg=False)
    assert third["published"] == 1 and "Сервис 24/7" in third["text"]


# ── устойчивость ──────────────────────────────────────────────────────────────

async def test_digest_source_unavailable_no_crash(session, monkeypatch):
    await _setup_channel(session)
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(
                            content_digest_enabled=True, content_digest_hours=24,
                            content_digest_role_list=["маркетинг"], telegram_allowmap={}))

    async def boom(channels, hours):
        raise RuntimeError("telethon недоступен")

    r = await content_digest.run_once(session, collect=boom, llm_summarize=_llm(TOPICS),
                                      deliver_tg=False)
    assert r["published"] == 0 and r["skipped"] == "collect_failed"   # задача не упала


async def test_digest_llm_failure_no_crash(session, monkeypatch):
    await _setup_channel(session)
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(
                            content_digest_enabled=True, content_digest_hours=24,
                            content_digest_role_list=["маркетинг"], telegram_allowmap={}))

    async def boom(text, s):
        raise RuntimeError("модель недоступна")

    r = await content_digest.run_once(session, collect=_collect(), llm_summarize=boom,
                                      deliver_tg=False)
    assert r["skipped"] == "llm_failed"


async def test_digest_no_channels_skips(session, monkeypatch):
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(
                            content_digest_enabled=True, content_digest_hours=24,
                            content_digest_role_list=["маркетинг"], telegram_allowmap={}))
    r = await content_digest.run_once(session, collect=_collect(), llm_summarize=_llm(TOPICS),
                                      deliver_tg=False)
    assert r["skipped"] == "no_channels"


async def test_digest_disabled_noop(session, monkeypatch):
    # выключенный флаг + режим Celery beat → no-op (сбор не запускаем)
    monkeypatch.setattr(content_digest, "get_settings",
                        lambda: types.SimpleNamespace(content_digest_enabled=False))

    async def collect(channels, hours):
        raise AssertionError("не должно вызываться при выключенном флаге")

    r = await content_digest.run_once(session, collect=collect, require_enabled=True)
    assert r["skipped"] == "disabled"


# ── список каналов (настраивается без перезапуска) ────────────────────────────

async def test_channels_crud(session):
    ch = await repo.add_content_channel(session, "@kanal", "Канал")
    assert ch and ch.ref == "@kanal"
    assert await repo.add_content_channel(session, "@kanal", "Канал") is None   # идемпотентно
    await session.commit()
    rows = await repo.list_content_channels(session, only_active=True)
    assert [c.ref for c in rows] == ["@kanal"]
    assert await repo.delete_content_channel(session, "@kanal") == "Канал"
    await session.commit()
    assert await repo.list_content_channels(session) == []


async def test_topic_seen_dedup(session):
    assert await repo.mark_topic_seen(session, "Тема про запчасти") is True
    # повтор с другим регистром/пунктуацией — та же тема
    assert await repo.mark_topic_seen(session, "тема про запчасти!") is False
    assert await repo.mark_topic_seen(session, "") is False
