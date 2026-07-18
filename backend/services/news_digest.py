"""TASK-1004 (#42, EPIC-10) — сборка и доставка выпуска дайджеста новостей по ИИ.

Единая функция `run_once` — общий «сборщик выпуска», который вызывают:
  - Celery beat (`app/tasks.news_digest_task`) — регулярно по расписанию;
  - админ-эндпоинт `POST /api/admin/news/digest` — ручной прогон/проверка;
  - Telegram-бот (`_run_news_digest`) — доставка первому лицу.

Сбор выпуска идёт LLM-конвейером (веб-поиск свежих новостей → инструмент
`ai_news_digest`, который делает дедуп и публикует в веб-ленту `notifications`).
Доставка в Telegram — отдельным шагом. И сбор, и доставка ИНЪЕКТИРУЕМЫ (collect/
tg_sender/owner), поэтому тесты идут без сети. Ошибка/недоступность источника не
роняет задачу — логируем и возвращаем результат со `skipped`.
"""
from __future__ import annotations

from app import repositories as repo
from app.config import get_settings
from app.logging_config import get_logger

log = get_logger("remtech.news_digest")


def _prompt(topics: list[str]) -> str:
    hint = ("по темам: " + ", ".join(topics)) if topics else "по искусственному интеллекту"
    return (f"Собери свежие новости {hint} за последние сутки через веб-поиск и "
            "вызови ai_news_digest: 5–10 пунктов, каждый — суть одним предложением "
            "и ссылка на источник. Не повторяй одинаковое.")


async def _resolve_owner(s) -> tuple[dict | None, int | None]:
    """Владелец дайджеста (первое лицо) — первый активный из allow-list.
    Возвращает (user_dict | None, tg_id | None)."""
    st = get_settings()
    if not st.telegram_allowmap:
        return None, None
    tg, username = next(iter(st.telegram_allowmap.items()))
    u = await repo.get_user_by_username(s, username)
    if not u or not u.active:
        return None, None
    return ({"user_id": u.id, "username": u.username,
             "name": u.full_name or u.username, "role": u.role}, tg)


async def _resolve_agent_id(s) -> int | None:
    """id персоны-агента с личными инструментами (ai_news_digest в PERSONAL_TOOLS →
    доступен только персоне, не дефолтному агенту). Имя — из TELEGRAM_AGENT."""
    name = (get_settings().telegram_agent or "").strip()
    if not name:
        return None
    for a in await repo.list_agents(s):
        if a.name == name:
            return a.id
    return None


async def _llm_collect(user: dict, agent_id) -> str:
    """Реальный сбор выпуска: LLM (веб-поиск → ai_news_digest публикует в веб-ленту).
    Возвращает собранный текст дайджеста (или '')."""
    from app.turn import run_turn
    parts: list[str] = []

    async def emit(ev):
        if ev.get("type") == "delta":
            parts.append(ev.get("text", ""))

    # channel=telegram — служебный диалог дайджеста не должен светиться в веб-истории
    await run_turn(user, None, _prompt(get_settings().ai_news_topic_list), [], agent_id, emit,
                   channel="telegram")
    return "".join(parts).strip()


async def _default_tg(chat_id: int, text: str) -> None:
    """Доставка выпуска первому лицу в Telegram (реальная отправка)."""
    st = get_settings()
    if not st.telegram_bot_token:
        return
    from app.telegram_bot import TelegramTransport, md_to_tg_html
    tx = TelegramTransport(st.telegram_bot_token)
    try:
        await tx.call("sendMessage", {
            "chat_id": chat_id,
            "text": "📰 <b>Дайджест новостей по ИИ</b>\n\n" + md_to_tg_html(text),
            "parse_mode": "HTML",
        })
    finally:
        await tx.aclose()


async def run_once(s, *, collect=None, tg_sender=None, owner=None, agent_id=None,
                   require_enabled: bool = True) -> dict:
    """Один выпуск дайджеста новостей по ИИ. Общий вход для beat/админки/бота.

    s          — сессия БД для резолва владельца/агента.
    collect(user, agent_id) -> str  — сбор выпуска (по умолч. LLM-конвейер).
    tg_sender(chat_id, text)        — доставка в Telegram (по умолч. реальная).
    owner      — (user_dict, tg_id); None → берётся из allow-list.
    agent_id   — id персоны; None → резолв по TELEGRAM_AGENT.
    require_enabled — учитывать флаг AI_NEWS_ENABLED (beat=True; ручной прогон=False).

    Возвращает {'delivered': bool, 'text': str, 'skipped': str|None}. Недоступность
    источника/сбоя LLM не роняет — лог + skipped='collect_failed'.
    """
    st = get_settings()
    if require_enabled and not st.ai_news_enabled:
        return {"delivered": False, "text": "", "skipped": "disabled"}

    if owner is None:
        owner = await _resolve_owner(s)
    user, tg = owner
    if not user:
        log.warning("news digest: нет владельца (allow-list пуст/неактивен) — пропуск")
        return {"delivered": False, "text": "", "skipped": "no_owner"}

    if agent_id is None:
        agent_id = await _resolve_agent_id(s)
    collect = collect or _llm_collect
    tg_sender = tg_sender or _default_tg

    try:
        text = await collect(user, agent_id)
    except Exception:
        log.exception("news digest: сбор выпуска не удался (источник недоступен?)")
        return {"delivered": False, "text": "", "skipped": "collect_failed"}

    if not text:
        return {"delivered": False, "text": "", "skipped": "empty"}

    delivered = False
    if tg is not None:
        try:
            await tg_sender(tg, text)
            delivered = True
        except Exception:
            log.exception("news digest: доставка в Telegram не удалась")

    return {"delivered": delivered, "text": text, "skipped": None}
