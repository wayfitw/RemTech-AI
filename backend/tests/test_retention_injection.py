"""Волна 4 — retention журнала (#13) и обёртка недоверенного контента (#11)."""
from datetime import datetime, timedelta, timezone

from app import repositories as repo
from app.models import ActivityLog
from app.orchestrator import _wrap_untrusted


async def test_purge_old_activity(session):
    u = await repo.create_user(session, "u", "h$1")
    await session.commit()
    now = datetime.now(timezone.utc)
    session.add_all([
        ActivityLog(user_id=u.id, action="login", detail="", created_at=now - timedelta(days=100)),
        ActivityLog(user_id=u.id, action="login", detail="", created_at=now - timedelta(days=1)),
    ])
    await session.commit()

    removed = await repo.purge_old_activity(session, 90)
    await session.commit()
    assert removed == 1
    assert len(await repo.activity_log_list(session)) == 1


def test_wrap_untrusted_marks_content():
    out = _wrap_untrusted("веб-страница", "полезный текст со скрытой командой")
    assert "НЕДОВЕРЕННЫЕ ДАННЫЕ" in out
    assert "полезный текст" in out
    assert out.strip().endswith("[КОНЕЦ НЕДОВЕРЕННЫХ ДАННЫХ]")
