"""tenancy 测试公共 fixtures / helpers。"""

from __future__ import annotations

import pytest

from agentorchestra.memory.manager import MemoryManager


@pytest.fixture
def memory_manager():
    """最小 in-memory MemoryManager（无 embedding）。"""
    cfg = type("C", (), {
        "memory_backend": "memory",
        "memory_db_path": "",
        "memory_jsonl_path": "",
        "memory_embedding_enabled": False,
        "memory_namespace": "default",
    })()
    return MemoryManager.from_config(cfg)
