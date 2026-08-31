"""Agent实现模块 - Symphony原生Agent范式"""

# 子代理机制（第06章）
from .factory import create_agent, default_subagent_factory
from .plan_solve_agent import PlanSolveAgent
from .react_agent import ReActAgent
from .reflection_agent import ReflectionAgent
from .simple_agent import SimpleAgent

# 向后兼容别名
PlanAndSolveAgent = PlanSolveAgent

__all__ = [
    "SimpleAgent",
    "ReActAgent",
    "ReflectionAgent",
    "PlanSolveAgent",
    "PlanAndSolveAgent",  # 向后兼容

    # 子代理工厂函数
    "create_agent",
    "default_subagent_factory",
]
