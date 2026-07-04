"""Issue #18 — единый реестр инструментов покрывает все схемы."""
from agent.registry import TOOL_META, status_label, tool_options
from agent.tools import TOOLS

_NAMED = [t["name"] for t in TOOLS if t.get("name")]


def test_every_named_tool_has_meta():
    for name in _NAMED:
        assert name in TOOL_META, f"нет подписи для {name}"


def test_tool_options_match_schemas():
    opts = tool_options()
    assert {o["name"] for o in opts} == set(_NAMED)
    assert all(o["label"] for o in opts)


def test_status_label_fallback():
    assert status_label("read_url").strip()
    assert status_label("unknown-tool") == "⚙️ Делаю..."
