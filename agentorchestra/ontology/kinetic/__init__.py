"""动能层 - 定义组织的写操作与业务逻辑（对标 Palantir Kinetic elements）"""

from .action import ActionType
from .function import Function, derived_property

__all__ = ["ActionType", "Function", "derived_property"]
