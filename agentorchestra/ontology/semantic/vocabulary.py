"""Vocabulary - 统一词汇校验

统一词汇（统一语言）：
- 对象属性必须是 ObjectType 声明的属性
- 链接类型必须是 ObjectType 声明的链接
- 三元组校验（subj, link, obj）端类型匹配

提供显式校验接口，供 ObjectStore / engine 使用。
"""

from typing import Any, Dict, List, Optional


class VocabularyValidator:
    """统一词汇校验器"""

    def __init__(self, object_types: Optional[Dict[str, Any]] = None):
        """初始化

        Args:
            object_types: 对象类型注册表 {api_name: ObjectType}
        """
        self.object_types = object_types or {}

    # ==================== 属性校验 ====================

    def validate_property(self, type_name: str, prop_name: str) -> bool:
        """校验属性是否为对象类型声明的属性（统一词汇）"""
        obj_type = self.object_types.get(type_name)
        if not obj_type:
            return False
        return prop_name in obj_type.properties

    def unknown_properties(self, type_name: str, obj: Dict[str, Any]) -> List[str]:
        """返回对象中未声明的属性名"""
        obj_type = self.object_types.get(type_name)
        if not obj_type:
            return list(obj.keys())
        return [k for k in obj if k not in obj_type.properties]

    # ==================== 链接校验 ====================

    def validate_link(self, from_type: str, link_name: str, to_type: str) -> bool:
        """校验三元组（from, link, to）是否符合词汇定义

        校验规则：
        1. from_type 必须存在且定义了该链接
        2. 链接两端类型匹配（含子类继承）

        Returns:
            是否合法
        """
        from_def = self.object_types.get(from_type)
        if not from_def:
            return False
        link = from_def.get_link_type(link_name)
        if not link:
            return False

        # from 端
        if not self._matches(from_def, link.from_type, from_type):
            return False
        # to 端
        to_def = self.object_types.get(to_type)
        if not self._matches(to_def, link.to_type, to_type):
            return False
        return True

    def _matches(self, type_def, expected_type: str, actual_type: str) -> bool:
        """判断实际类型是否匹配期望类型（自身或子类）"""
        if expected_type == actual_type:
            return True
        if type_def is None:
            return False
        return type_def.is_subclass_of(expected_type, self.object_types)
