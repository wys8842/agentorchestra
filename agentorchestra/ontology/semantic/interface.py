"""Interface - 接口

对象类型多态：描述对象类型的形状（要求的属性），
多个对象类型可实现同一接口 → 统一建模和查询。
"""

from typing import Any, Dict, List, Optional


class Interface:
    """接口定义"""

    def __init__(
        self,
        api_name: str,
        required_properties: Optional[List[str]] = None,
        description: str = "",
        display_name: Optional[str] = None,
    ):
        self.api_name = api_name
        self.display_name = display_name or api_name
        self.description = description
        self.required_properties: List[str] = required_properties or []
        self._implementations: List[str] = []

    def add_required_property(self, name: str) -> "Interface":
        if name not in self.required_properties:
            self.required_properties.append(name)
        return self

    def register_implementation(self, object_type_name: str) -> None:
        if object_type_name not in self._implementations:
            self._implementations.append(object_type_name)

    def get_implementations(self) -> List[str]:
        return list(self._implementations)

    def check_implements(self, object_type) -> bool:
        """检查对象类型是否包含接口所有必需属性"""
        obj_props = set(object_type.properties.keys())
        return set(self.required_properties).issubset(obj_props)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_name": self.api_name,
            "display_name": self.display_name,
            "description": self.description,
            "required_properties": self.required_properties,
            "implementations": self._implementations,
        }

    def __repr__(self) -> str:
        return f"Interface({self.api_name}, impl={self._implementations})"
