"""tools/builtin/task_tool + devlog_tool 测试"""


class FakeSubAgent:
    """最小子代理 mock"""

    def run_as_subagent(self, task, tool_filter=None,
                        return_summary=True, max_steps_override=None):
        return {
            "success": True,
            "summary": f"任务: {task}\n结果: 完成",
            "metadata": {"steps": 2, "duration_seconds": 1.5,
                         "tools_used": ["Read"], "tokens": 100},
        }


class TestTaskTool:
    def test_run_success(self):
        from symphony.tools.builtin.task_tool import TaskTool

        tool = TaskTool(agent_factory=lambda at: FakeSubAgent())
        resp = tool.run({"task": "探索代码库", "agent_type": "react"})
        assert resp.status.value == "success"
        assert "任务完成" in resp.text
        assert "探索代码库" in resp.text

    def test_run_missing_task(self):
        from symphony.tools.builtin.task_tool import TaskTool
        tool = TaskTool(agent_factory=lambda at: FakeSubAgent())
        resp = tool.run({})
        assert resp.status.value == "error"
        assert resp.error_info["code"] == "INVALID_PARAM"

    def test_run_unsupported_agent(self):
        from symphony.tools.builtin.task_tool import TaskTool

        def bad_factory(agent_type):
            raise ValueError(f"不支持的类型: {agent_type}")

        tool = TaskTool(agent_factory=bad_factory)
        resp = tool.run({"task": "x", "agent_type": "unknown"})
        assert resp.status.value == "error"

    def test_get_parameters(self):
        from symphony.tools.builtin.task_tool import TaskTool
        tool = TaskTool(agent_factory=lambda at: FakeSubAgent())
        params = {p.name for p in tool.get_parameters()}
        assert "task" in params and "agent_type" in params


class TestDevLog:
    def test_run_missing_params(self, tmp_path):
        from symphony.tools.builtin.devlog_tool import DevLogTool
        tool = DevLogTool(session_id="s-1", agent_name="agent1",
                          project_root=str(tmp_path),
                          persistence_dir=str(tmp_path / "devlogs"))
        resp = tool.run({})
        # 缺必填参数 → 错误响应（不崩溃）
        assert resp.status.value == "error"
