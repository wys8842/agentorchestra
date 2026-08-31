"""
Symphony - 灵活、可扩展的多智能体框架

基于OpenAI原生API构建，提供简洁高效的智能体开发体验。
"""

# 配置第三方库的日志级别，减少噪音
import logging

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("qdrant_client").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

from .agents.plan_solve_agent import PlanSolveAgent
from .agents.react_agent import ReActAgent
from .agents.reflection_agent import ReflectionAgent

# Agent实现
from .agents.simple_agent import SimpleAgent
from .core.config import Config
from .core.exceptions import SymphonyException

# 核心组件
from .core.llm import SymphonyLLM
from .core.message import Message
from .tools.builtin.calculator import CalculatorTool, calculate

# 工具系统
from .tools.registry import ToolRegistry, global_registry
from .version import __author__, __description__, __email__, __version__

__all__ = [
    # 版本信息
    "__version__",
    "__author__",
    "__email__",
    "__description__",

    # 核心组件
    "SymphonyLLM",
    "Config",
    "Message",
    "SymphonyException",

    # Agent范式
    "SimpleAgent",
    "ReActAgent",
    "ReflectionAgent",
    "PlanSolveAgent",

    # 工具系统
    "ToolRegistry",
    "global_registry",
    "CalculatorTool",
    "calculate",
]

