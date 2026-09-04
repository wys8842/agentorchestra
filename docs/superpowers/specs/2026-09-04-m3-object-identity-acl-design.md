# M3 — 对象身份与权限落地（P3）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M3 / P3（路线图 §5）
- 依赖: M0（CheckpointStore/WAL）、M1（tx coordinator / locks）、M2（可选）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

Ontology 对象带版本号与事务身份；权限 = RBAC + 对象 ACL（行级）在事务 pre-condition 求值；审计日志 WORM。

**M3 验收（roadmap §5.5）**：

- [ ] 并发事务同时改同对象 → 仅一个 commit，另一个抛 CAS 冲突
- [ ] 无权用户尝试修改 → pre-condition 抛 `PermissionDenied`，事务自动回滚
- [ ] 审计表禁 update/delete

**不在本里程碑范围**：

- M6 多租户隔离（依赖 M3 权限 + M5 审计，后续做）
- ACL 跨进程强一致（内存 ACL + 可选持久化，最小可用）
- DB trigger 级 WORM（接口层禁改）

---

## 2. 关键决策（用户确认）

| 决策项 | 结论 |
|--------|------|
| 对象身份 | ObjectStore insert/update/delete 自动注入/维护 `version`/`created_tx`/`last_modified_tx`；validate 豁免 3 保留字段 |
| ACL | 内存 ACL（resource_key + principal/role + permission）+ 可选持久化到 CheckpointStore |
| 审计 | CheckpointStore 加 `audit_log` 表；接口层 WORM（仅 append/query，无 update/delete） |
| CAS 集成 | 对象 version + coordinator pre_condition；并发写冲突抛 TxConflict |
| PermissionDenied | 新异常；RBAC 先行、ACL 行级次之；SecurityManager 无规则默认开放不变 |
| SYSTEM_FIELDS | `ObjectType.SYSTEM_FIELDS` 公共常量；validate_object 与 unknown_properties 豁免 |
| AuditManager 兼容 | `clear()` 保留仅清内存；配 store backend 后 clear 不删 DB 行（WORM 保证） |

---

## 3. 包结构

```
agentorchestra/governance/               # 新顶层包（roadmap §5.3）
├── __init__.py
├── identity.py            # IdentityService + principal/roles（ContextVar 承载）
├── acl.py                 # ACLManager（对象级规则；内存 + 可选 backend）
├── cas.py                 # ObjectCAS（version 读写/校验）
└── permission.py          # PermissionDenied / PermissionChecker
```

---

## 4. 数据模型

### 4.1 CheckpointStore 新增 audit_log 表

```sql
CREATE TABLE audit_log (
    entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TIMESTAMP NOT NULL,
    principal   TEXT NOT NULL,
    resource    TEXT NOT NULL,
    action      TEXT NOT NULL,
    obj_id      TEXT,
    success     INTEGER,
    detail_json TEXT,
    tx_id       TEXT
);
```

### 4.2 CheckpointStore 抽象新增 2 方法

- `append_audit(entry: AuditEntry) -> None`
- `query_audit(limit=100, principal=None, resource=None) -> List[AuditEntry]`

**WORM 保证**：接口层不提供 `update_audit` / `delete_audit` / `clear_audit`。

两后端（SQLAlchemy 基类 + InMemory）同步实现。

---

## 5. 模块接口

### 5.1 identity.py

```python
class IdentityService:
    """principal + roles 上下文（ContextVar）。"""
    async def run_as(self, principal, roles=None) -> ContextManager:
        """进入带 principal/roles 的上下文；退出还原。"""
    def current(self) -> IdentityContext | None:   # (principal, roles)

    @contextmanager
    def sync_run_as(self, principal, roles=None): ...  # 同步版本
```

### 5.2 acl.py

```python
@dataclass
class ACLRule:
    resource: str        # "order:o1" 或 "order:*"
    permission: str      # read | write | delete
    principal: str | None = None
    role: str | None = None

class ACLManager:
    def __init__(self, backend=None): ...   # 可选持久化 backend
    def grant(self, resource, permission, principal=None, role=None): ...
    def revoke(self, resource, permission, principal=None, role=None): ...
    def check(self, resource, permission, principal, roles) -> bool:
        # 先精确 resource，再通配 resource:*；principal 匹配优先，role 其次
```

### 5.3 permission.py

```python
class PermissionDenied(Exception):
    def __init__(self, resource, permission, principal): ...

class PermissionChecker:
    """两段式决策：RBAC（SecurityManager）→ ACL（对象级）。"""
    def __init__(self, security: SecurityManager | None, acl: ACLManager | None): ...
    def check(self, resource, permission, principal, roles,
              obj_id=None) -> None:
        # RBAC 失败 或 (有 obj_id 且 ACL 拒绝) → raise PermissionDenied
```

### 5.4 cas.py

```python
class ObjectCAS:
    """对象 version 读取/校验（封装 object dict 字段）。"""
    SYSTEM_FIELDS = {"version", "created_tx", "last_modified_tx"}
    @staticmethod
    def version_of(obj) -> int: ...
    @staticmethod
    def bump(obj): obj["version"] += 1
```

---

## 6. ObjectStore 接入

| 方法 | 改动 |
|------|------|
| `insert` | 注入 `version=1, created_tx=<ctx or "none">, last_modified_tx=same` |
| `update` | 读当前对象 version → CAS 校验（读取快照 vs 提交时）→ 失败抛 TxConflict；成功 `version+=1, last_modified_tx=ctx` |
| `delete` | 校验存在；发审计 |
| `_wal_emit` | 不变（M0 已有） |
| 审计 | 若装配 `audit`（AuditManager + store backend），insert/update/delete 自动 append |

**validate_object 豁免**：ObjectType 增加 `SYSTEM_FIELDS` 常量；`validate_object` 与 `unknown_properties` 跳过 SYSTEM_FIELDS 键。

---

## 7. Coordinator 接入

- `TransactionCoordinator.transaction()` 增加 `principal: str = "anonymous"`、`roles: list = []`
- 进入上下文时经 `IdentityService.run_as(principal, roles)` 注入 ContextVar
- `TxContext.pre_condition` 增加对象 ACL 检查：签名扩展支持 `(resource, permission, obj_id, expected_version)`

并发写冲突：ObjectStore.update 内部 CAS（读时 version vs 提交时 version）不一致 → `TxConflict`。

---

## 8. 测试策略（tests/governance/）

| 文件 | 覆盖 |
|------|------|
| `test_identity.py` | ContextVar 上下文切换（async + sync）|
| `test_acl.py` | grant/revoke/check（精确 + 通配 resource，principal + role）|
| `test_object_identity.py` | insert 注入 version/created_tx；update CAS 成功/冲突 TxConflict |
| `test_permission.py` | 无权写 → PermissionDenied；RBAC+ACL 组合决策 |
| `test_worm_audit.py` | append-only（无 update/delete 方法）；query 过滤 |
| `test_coordinator_integration.py` | coordinator principal 注入；并发改同对象仅一 commit |

兼容：现有 276 测试必须全绿（insert/update 返回对象带 SYSTEM_FIELDS 但语义不变）。

---

## 9. 验收标准

- [ ] `pytest tests/governance/` 全绿
- [ ] `pytest tests/`（现有 276）全绿
- [ ] `ruff check agentorchestra/governance agentorchestra/state tests/governance`
- [ ] `mypy agentorchestra/governance`
- [ ] CAS 冲突（对象 version）→ TxConflict
- [ ] PermissionDenied 触发事务回滚
- [ ] audit_log 无 update/delete 方法

---

## 10. 实施步骤

1. `state/records.py` 加 `AuditEntry` dataclass
2. `state/checkpoint.py` CheckpointStore 抽象 + `append_audit`/`query_audit`
3. `state/backends/*` 实现（1 表）
4. 写 `governance/` 包：identity → acl → permission → cas
5. ObjectType `SYSTEM_FIELDS` + validate 豁免
6. ObjectStore 注入 version/审计接入
7. coordinator principal/roles 注入 + ACL pre_condition
8. `tests/governance/` 全套
9. 全量测试 + ruff + mypy
10. 提交

---

## 11. 风险与回退

- **现有测试破坏（对象多 3 字段）**：SYSTEM_FIELDS 豁免 + 现有断言多为取值/in 断言；如破坏则针对性修
- **SecurityManager 兼容**：无规则默认开放保留；PermissionDenied 仅在新权限路径抛
- **审计性能**：append-only 批量；WORM 由接口层保证（如需 DB 级再加 trigger）
- **并发写**：单实例内存 CAS；跨进程乐观锁依赖 M1 locks 表（后端可选）