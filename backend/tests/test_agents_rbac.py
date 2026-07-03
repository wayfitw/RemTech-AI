"""Issue #2 — доступ роли к агенту (используется в листинге и в WebSocket).

Единый хелпер role_can_use_agent — источник правды для RBAC агентов.
Полный WS-интеграционный сценарий покрывается в волне тестирования (issue #20)."""
from types import SimpleNamespace

import pytest

from app.main import role_can_use_agent


def _agent(allowed_roles):
    return SimpleNamespace(allowed_roles=allowed_roles)


@pytest.mark.parametrize("role,allowed,expected", [
    ("admin", "manager", True),      # админ — всегда
    ("admin", "", True),
    ("user", "", True),              # пустой список — доступен всем
    ("user", None, True),
    ("manager", "manager,sales", True),
    ("manager", " manager , sales ", True),   # устойчив к пробелам
    ("user", "manager", False),      # роль не входит — запрет
    ("sales", "manager", False),
    ("user", "manager,sales", False),
])
def test_role_can_use_agent(role, allowed, expected):
    assert role_can_use_agent(role, _agent(allowed)) is expected
