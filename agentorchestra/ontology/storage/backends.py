"""StorageBackend - 存储后端抽象

提供对象数据的持久化后端：
- MemoryBackend: 内存存储（默认，演示/轻量）
- SQLiteBackend: SQLite 文件存储（生产，进程间持久化）

ObjectIndex 通过后端访问数据，上层（ObjectStore/QueryEngine）无感知。
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseStorageBackend(ABC):
    """存储后端接口"""

    @abstractmethod
    def register_type(self, type_name: str) -> None: ...

    @abstractmethod
    def put(self, type_name: str, pk: str, obj: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def delete(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def all(self, type_name: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def types(self) -> List[str]: ...

    def close(self) -> None:  # 可选：关闭后端
        pass


class MemoryBackend(BaseStorageBackend):
    """内存后端"""

    def __init__(self):
        self._objects: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def register_type(self, type_name: str) -> None:
        self._objects.setdefault(type_name, {})

    def put(self, type_name: str, pk: str, obj: Dict[str, Any]) -> None:
        self._objects.setdefault(type_name, {})[pk] = dict(obj)

    def get(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        return self._objects.get(type_name, {}).get(pk)

    def delete(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        return self._objects.get(type_name, {}).pop(pk, None)

    def all(self, type_name: str) -> List[Dict[str, Any]]:
        return list(self._objects.get(type_name, {}).values())

    def types(self) -> List[str]:
        return list(self._objects.keys())

    def clear(self) -> None:
        self._objects.clear()


class SQLiteBackend(BaseStorageBackend):
    """SQLite 文件后端（生产持久化）

    表结构：objects(type TEXT, pk TEXT, data TEXT, PRIMARY KEY(type, pk))
    data 为 JSON 序列化的对象。
    """

    def __init__(self, db_path: str = "memory/ontology.db"):
        """初始化 SQLite 后端

        Args:
            db_path: SQLite 数据库文件路径
        """
        import os
        import threading
        if os.path.dirname(db_path):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.db_path = db_path
        # check_same_thread=False 支持跨线程（Scheduler/工作流场景）
        self._lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS objects (
                type TEXT NOT NULL,
                pk TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (type, pk)
            )"""
        )
        self._conn.commit()

    def _check_open(self) -> None:
        """检查连接是否已关闭"""
        if self._closed:
            raise RuntimeError(f"SQLiteBackend 已关闭: {self.db_path}")

    def register_type(self, type_name: str) -> None:
        # SQLite 无需预注册类型
        pass

    def put(self, type_name: str, pk: str, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj, ensure_ascii=False)
        with self._lock:
            self._check_open()
            self._conn.execute(
                """INSERT OR REPLACE INTO objects (type, pk, data) VALUES (?, ?, ?)""",
                (type_name, pk, data),
            )
            self._conn.commit()

    def get(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._check_open()
            row = self._conn.execute(
                "SELECT data FROM objects WHERE type = ? AND pk = ?",
                (type_name, pk),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def delete(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        obj = self.get(type_name, pk)
        if obj is not None:
            with self._lock:
                self._check_open()
                self._conn.execute(
                    "DELETE FROM objects WHERE type = ? AND pk = ?", (type_name, pk))
                self._conn.commit()
        return obj

    def all(self, type_name: str) -> List[Dict[str, Any]]:
        with self._lock:
            self._check_open()
            rows = self._conn.execute(
                "SELECT data FROM objects WHERE type = ?", (type_name,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def types(self) -> List[str]:
        with self._lock:
            self._check_open()
            rows = self._conn.execute("SELECT DISTINCT type FROM objects").fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()

    def clear(self) -> None:
        with self._lock:
            self._check_open()
            self._conn.execute("DELETE FROM objects")
        self._conn.commit()


# 向后兼容别名
StorageBackend = BaseStorageBackend
