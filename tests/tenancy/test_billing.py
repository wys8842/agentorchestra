"""UsageRecorder 测试：record / export CSV / JSON。"""

import json
import os

from agentorchestra.tenancy import UsageRecorder


def test_record_and_total():
    ur = UsageRecorder()
    ur.record("a", "gpt", 100, 10.5)
    ur.record("a", "gpt", 200, 20.5)
    ur.record("b", "claude", 50, 5.0)
    assert ur.total("a") == 300
    assert ur.total("b") == 50
    assert ur.total() == 350
    by = ur.by_tenant()
    assert by == {"a": 300, "b": 50}


def test_export_csv(tmp_path):
    ur = UsageRecorder()
    ur.record("acme", "gpt", 120, 8.0)
    ur.record("acme", "claude", 30, 2.0)
    path = str(tmp_path / "usage.csv")
    ur.export_csv(path)
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "tenant_id" in content  # header
    assert "acme" in content


def test_export_json(tmp_path):
    ur = UsageRecorder()
    ur.record("acme", "gpt", 120, 8.0)
    path = str(tmp_path / "usage.json")
    ur.export_json(path)
    data = json.load(open(path, encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["tenant_id"] == "acme"
    assert data[0]["tokens"] == 120


def test_rolling_cap():
    ur = UsageRecorder(max_records=3)
    for i in range(5):
        ur.record("a", "m", 10, 0.0)
    assert len(ur.snapshot()) == 3
