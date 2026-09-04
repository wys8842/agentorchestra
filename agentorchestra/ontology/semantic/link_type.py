"""LinkType - 对象间链接类型

语义层：定义对象与对象之间的关系（方向、基数、描述）。
- from_type: 源对象类型名
- to_type: 目标对象类型名
- cardinality: 基数（ONE_TO_ONE / ONE_TO_MANY / MANY_TO_MANY）
"""

from typing import Any, Dict


class LinkType:
    """对象间链接类型"""

    def __init__(
        self,
        name: str,
        from_type: str,
        to_type: str,
        cardinality: str = "ONE_TO_MANY",
        description: str = "",
    ):
        self.name = name
        self.from_type = from_type
        self.to_type = to_type
        self.cardinality = cardinality
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "name": self.name,
            "from_type": self.from_type,
            "to_type": self.to_type,
            "cardinality": self.cardinality,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"LinkType({self.from_type}-[{self.name}]->{self.to_type})"
