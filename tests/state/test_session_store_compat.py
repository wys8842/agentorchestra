"""SessionStore 兼容层测试。

验证 182 个旧测试用的 SessionStore API（save/load/list_sessions/delete）仍可用。
"""

import os

from agentorchestra.core.message import Message
from agentorchestra.core.session_store import SessionStore


def test_session_store_save_and_load(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    history = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    filepath = store.save(
        agent_config={"name": "x", "llm_model": "gpt-4"},
        history=history,
        tool_schema_hash="abc",
        read_cache={},
        metadata={"step": 1},
    )
    assert os.path.exists(filepath)
    data = store.load(filepath)
    assert data["agent_config"]["name"] == "x"
    assert len(data["history"]) == 2


def test_session_store_list(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    store.save(agent_config={"name": "a"}, history=[], tool_schema_hash="",
               read_cache={}, metadata={}, session_name="s1")
    store.save(agent_config={"name": "b"}, history=[], tool_schema_hash="",
               read_cache={}, metadata={}, session_name="s2")
    sessions = store.list_sessions()
    assert len(sessions) == 2
    names = {s["filename"] for s in sessions}
    assert names == {"s1.json", "s2.json"}


def test_session_store_delete(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    store.save(agent_config={}, history=[], tool_schema_hash="",
               read_cache={}, metadata={}, session_name="to-delete")
    assert store.delete("to-delete") is True
    assert store.delete("to-delete") is False  # 第二次不存在


def test_session_store_config_consistency():
    store = SessionStore()
    saved = {"llm_provider": "openai", "llm_model": "gpt-4", "max_steps": 10}
    current = {"llm_provider": "anthropic", "llm_model": "claude", "max_steps": 10}
    result = store.check_config_consistency(saved, current)
    assert not result["consistent"]
    assert len(result["warnings"]) == 2  # provider + model 变化


def test_session_store_tool_schema_consistency():
    store = SessionStore()
    result = store.check_tool_schema_consistency("abc", "xyz")
    assert result["changed"] is True
    result = store.check_tool_schema_consistency("abc", "abc")
    assert result["changed"] is False
