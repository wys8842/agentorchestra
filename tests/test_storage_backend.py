"""ontology/storage 存储后端测试"""


from symphony.ontology import (
    GraphStore,
    ObjectStore,
    ObjectType,
    SQLiteBackend,
)
from symphony.tools.base import ToolParameter


def make_customer() -> ObjectType:
    return ObjectType("customer", "customer_id", properties=[
        ToolParameter(name="customer_id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
        ToolParameter(name="region", type="string", description="地区", required=False),
    ])


class TestMemoryBackend:
    def test_default_backend(self):
        store = ObjectStore(graph=GraphStore())
        assert store.backend_type == "MemoryBackend"

    def test_operations(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        assert store.get("customer", "c1")["name"] == "张三"
        assert store.count("customer") == 1


class TestSQLiteBackend:
    def test_persistence_across_instances(self, tmp_path):
        """SQLite 持久化：写入后新实例能读到"""
        db_path = str(tmp_path / "test.db")

        # 实例 1：写入
        store1 = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store1.register_type(make_customer())
        store1.insert("customer", {"customer_id": "c1", "name": "张三", "region": "华东"})
        store1.insert("customer", {"customer_id": "c2", "name": "张三", "region": "华北"})
        store1.close()

        # 实例 2：重新打开，数据仍在
        store2 = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store2.register_type(make_customer())
        assert store2.count("customer") == 2
        assert store2.get("customer", "c1")["name"] == "张三"
        assert len(store2.filter("customer", {"region": "华北"})) == 1
        store2.close()

    def test_update_persisted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        store.update("customer", "c1", {"region": "华南"})
        store.close()

        store2 = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store2.register_type(make_customer())
        assert store2.get("customer", "c1")["region"] == "华南"
        store2.close()

    def test_delete_persisted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        store.delete("customer", "c1")
        store.close()

        store2 = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store2.register_type(make_customer())
        assert store2.count("customer") == 0
        store2.close()

    def test_search_filter_aggregate_sqlite(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = ObjectStore(graph=GraphStore(), backend=SQLiteBackend(db_path))
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三", "region": "华东"})
        store.insert("customer", {"customer_id": "c2", "name": "李四", "region": "华东"})
        store.insert("customer", {"customer_id": "c3", "name": "王五", "region": "华北"})

        assert len(store.search("customer", "张")) == 1
        assert len(store.filter("customer", {"region": "华东"})) == 2
        assert store.aggregate("customer", "region") == {"华东": 2, "华北": 1}
        store.close()
