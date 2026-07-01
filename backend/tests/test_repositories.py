"""Cutover Стадия 1 — тесты репозиторного слоя (async CRUD) против Postgres."""
from app import repositories as repo


async def test_user_crud(session):
    u = await repo.create_user(session, "ivan", "h$1", role="admin", full_name="Иван")
    await session.commit()
    assert u.id
    got = await repo.get_user_by_username(session, "ivan")
    assert got.role == "admin"
    assert await repo.count_registered_users(session) == 1
    await repo.set_user_active(session, u.id, False)
    await repo.update_password(session, u.id, "h$2")
    await session.commit()
    refreshed = await repo.get_user(session, u.id)
    assert refreshed.active == 0
    assert refreshed.password_hash == "h$2"
    assert [x.username for x in await repo.list_users(session)] == ["ivan"]


async def test_conversation_and_messages(session):
    u = await repo.create_user(session, "anna", "h$1")
    conv = await repo.create_conversation(session, u.id, "КП XCMG")
    await repo.save_message(session, conv.id, u.id, "user", {"type": "text", "text": "привет"})
    await repo.save_message(session, conv.id, u.id, "assistant", "готово")
    await session.commit()

    hist = await repo.load_history(session, conv.id)
    assert [m["role"] for m in hist] == ["user", "assistant"]  # порядок по возрастанию
    assert hist[0]["content"]["text"] == "привет"

    await repo.set_conversation_title(session, conv.id, "Новое имя")
    await session.commit()
    assert (await repo.get_conversation(session, conv.id)).title == "Новое имя"

    convs = await repo.list_conversations(session, u.id)
    assert len(convs) == 1


async def test_delete_conversation_cascades(session):
    u = await repo.create_user(session, "pavel", "h$1")
    conv = await repo.create_conversation(session, u.id, "tmp")
    await repo.save_message(session, conv.id, u.id, "user", "x")
    await session.commit()
    await repo.delete_conversation(session, conv.id, u.id)
    await session.commit()
    assert await repo.get_conversation(session, conv.id) is None
    assert await repo.load_history(session, conv.id) == []


async def test_files_and_ownership(session):
    u = await repo.create_user(session, "elena", "h$1")
    conv = await repo.create_conversation(session, u.id, "c")
    rec = await repo.save_file_record(session, u.id, "kp.docx", "/data/kp.docx",
                                      kind="docx", conversation_id=conv.id, direction="upload")
    await session.commit()
    assert (await repo.get_file_record(session, rec.id)).user_id == u.id
    last = await repo.get_last_uploaded(session, conv.id, "docx")
    assert last.file_name == "kp.docx"


async def test_admin_analytics(session):
    await repo.create_user(session, "director", "h$1", role="admin", full_name="Директор")
    emp = await repo.create_user(session, "worker", "h$1", full_name="Работник")
    conv = await repo.create_conversation(session, emp.id, "чат")
    await repo.save_message(session, conv.id, emp.id, "user", "вопрос")
    await repo.save_message(session, conv.id, emp.id, "assistant", "ответ")
    await repo.save_file_record(session, emp.id, "out.pdf", "/data/out.pdf",
                                kind="pdf", conversation_id=conv.id, direction="output")
    await repo.log_activity(session, emp.id, "login", "вход")
    await session.commit()

    ov = await repo.admin_overview(session)
    assert ov["users"] == 2
    assert ov["conversations"] == 1
    assert ov["user_messages"] == 1
    assert ov["generated_files"] == 1
    assert ov["active_today"] == 1

    stats = await repo.admin_user_stats(session)
    worker = next(x for x in stats if x["username"] == "worker")
    assert worker["conversations"] == 1 and worker["messages"] == 1

    per_day = await repo.messages_per_day(session, 14)
    assert sum(d["count"] for d in per_day) == 1

    ac = await repo.activity_log_list(session)
    assert ac[0]["action"] == "login" and ac[0]["username"] == "worker"

    ucs = await repo.admin_conversations(session, emp.id)
    assert ucs[0]["messages"] == 2
