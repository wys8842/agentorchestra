# governance — 对象身份与权限（P3 / M3）

Ontology 对象带版本号与事务身份；权限 = RBAC + 对象 ACL 在事务 pre-condition 求值；审计走 WORM。

设计见 [M3 spec](../superpowers/specs/2026-09-04-m3-object-identity-acl-design.md)。

## 模块组成

| 文件 | 职责 |
|------|------|
| `identity.py` | `IdentityService`：principal + roles 上下文（ContextVar） |
| `acl.py` | `ACLManager` / `ACLRule`：对象级（行级）权限，支持通配 `order:*` |
| `permission.py` | `PermissionChecker`（RBAC → ACL 两段决策）+ `PermissionDenied` |
| `cas.py` | `ObjectCAS`：对象 version/created_tx/last_modified_tx 读写 |

## 对象身份（ObjectStore 自动）

`ObjectStore` insert/update/delete 自动注入/维护系统字段：

```
version            # 从 1 递增（update CAS 依据）
created_tx         # 创建时事务 id
last_modified_tx   # 最后修改事务 id
```

- `ObjectType.SYSTEM_FIELDS` 常量；`validate_object` / `unknown_properties` 豁免（不报未声明）
- `store.update(..., expected_version=n)` → 版本不匹配抛 `TxConflict`

```python
store.insert("Order", {"id": "o1", "amount": 100})
# 返回 obj 含 version=1 / created_tx="none" / last_modified_tx="none"

obj = store.update("Order", "o1", {"amount": 150}, expected_version=1)  # CAS
```

## 权限决策

```python
from agentorchestra.governance import (
    IdentityService, ACLManager, PermissionChecker, PermissionDenied,
)

acl = ACLManager()
acl.grant("order:o1", "write", principal="alice")
checker = PermissionChecker(security=security_manager, acl=acl)

checker.check("order", "write", principal="alice", roles=[], obj_id="o1")  # ok
checker.check("order", "write", principal="bob", obj_id="o1")  # PermissionDenied
```

决策顺序：**RBAC 先行**（SecurityManager，角色→资源/动作）→ **ACL 行级**（有 obj_id 时）。
- SecurityManager 无规则 → RBAC 默认开放（向后兼容）
- ACL 是白名单：无 ACL 规则匹配 → 拒绝（除非未装配 ACL）

## coordinator 集成

```python
async with coord.transaction(principal="alice", roles=["admin"]) as tx:
    tx.authorize("order", "write", obj_id="o1")   # 拒绝 → PermissionDenied → 自动回滚
```

事务进入时经 IdentityService ContextVar 注入身份（退出还原），供审计/ACL 自动读取。

## 审计（WORM）

`CheckpointStore` 新增 `audit_log` 表：仅 `append_audit` / `query_audit`，**无 update/delete/clear 公开方法**（接口层 WORM）。`AuditManager.attach_backend(store)` 后写操作自动 append；配 backend 后 `clear()` 只清内存不删 DB 行。
