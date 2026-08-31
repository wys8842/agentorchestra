"""语义层 - 定义组织的业务对象模型（对标 Palantir Semantic elements）"""

from .interface import Interface
from .object_type import LinkType, ObjectType
from .vocabulary import VocabularyValidator

__all__ = ["ObjectType", "LinkType", "Interface", "VocabularyValidator"]
