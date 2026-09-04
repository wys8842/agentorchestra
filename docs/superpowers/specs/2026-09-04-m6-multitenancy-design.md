# M6 — 多租户隔离（P6）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M6 / P6（路线图 §8）
- 依赖: M3 权限 + M5 审计（已就位）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

多个业务团队/客户共享同一部署时，资源/记忆/Agent 调用按租户隔离；token 配额可限额，用量可导出。

**M6 验收（roadmap §8.5）**：
- [ ] 两个租户跑相同 agent namespace 完全隔离
- [ ] 配额耗尽时事务优雅失败（不崩进程）
- [ ] 用量统计可导出 CSV/JSON 给计费系统

**不在范围**：coordinator/审计/存储 schema 前缀级隔离（后续）；硬隔离独立进程（roadmap P7）。

---

## 2. 关键决策

| 决策项 | 结论 |
|--------|------|
| 范围 | TenantContext + namespace 隔离 + token 配额 + 用量导出 |
| Context | `TenantContext`（tenant_id + user_id 经 ContextVar），与 IdentityService 协同 |
| namespace | 默认 `f"{tenant_id}:{user_id}"`；MemoryManager 自动加 tenant 前缀 |
| 配额 | `QuotaGuard` 挂 SymphonyLLM：invoke/ainvoke 后按 `usage.total_tokens` 扣减；超限抛 `QuotaExceeded`（优雅） |
| 用量导出 | UsageRecorder → CSV/JSON |

---

## 3. 包结构

```
agentorchestra/tenancy/
├── __init__.py
├── tenant.py        # TenantContext / TenantManager（ContextVar 承载）
├── quota.py         # TokenQuota / QuotaManager / QuotaExceeded
└── billing.py       # UsageRecorder（记录 + CSV/JSON 导出）
```

---

## 4. 模块接口

### 4.1 tenant.py

```python
@dataclass
class TenantContext:
    tenant_id: str
    user_id: str = ""
    @property
    def namespace(self) -> str: return f"{tenant_id}:{user_id}" if user_id else tenant_id

class TenantManager:
    @asynccontextmanager
    async def run_as(self, tenant_id, user_id=""): ...
    @contextmanager
    def sync_run_as(self, tenant_id, user_id=""): ...
    def current(self) -> TenantContext | None: ...
```

### 4.2 quota.py

```python
class QuotaExceeded(Exception): ...

class TokenQuota:
    tenant_id: str
    limit: int            # 总 token 上限（-1 = 不限）
    used: int
    def add(self, tokens) -> None: # used+=tokens; 超 limit → QuotaExceeded

class QuotaManager:
    def __init__(self): self._quotas: dict[str, TokenQuota] = {}
    def set_limit(self, tenant_id, limit): ...
    def get(self, tenant_id) -> TokenQuota: ...
    def charge(self, tenant_id, tokens) -> None: # 优雅抛 QuotaExceeded
    def snapshot(self) -> dict: ...
```

### 4.3 billing.py

```python
class UsageRecorder:
    def record(self, tenant_id, model, tokens, latency_ms, ts=None): ...
    def export_csv(self, path) -> None: ...
    def export_json(self, path) -> None: ...
```

---

## 5. 接入

| 现有组件 | 改动 |
|---------|------|
| `core/llm.py` | SymphonyLLM 增加可选 `quota_manager`；`invoke`/`ainvoke` 成功后 charge + record（tenant context 存在时）；抛 QuotaExceeded |
| `memory/manager.py` | namespace 默认 = TenantContext.current().namespace（若存在）|
| Agent/IdentityService | TenantContext 与 IdentityService 可同时激活（互不覆盖）|

---

## 6. 测试策略（tests/tenancy/）

| 文件 | 覆盖 |
|------|------|
| `test_tenant.py` | ContextVar tenant 切换 / namespace 计算 / 还原 |
| `test_quota.py` | set_limit / charge / QuotaExceeded（优雅）|
| `test_billing.py` | record / export CSV / JSON |
| `test_llm_quota.py` | QuotaGuard 挂 LLM 计数（mock usage）|
| `test_memory_tenant.py` | 两租户同 agent namespace 隔离 |

兼容：现有 310 测试全绿。

---

## 7. 验收标准

- [ ] `pytest tests/tenancy/` 全绿
- [ ] `pytest tests/`（现有 310）全绿
- [ ] ruff + mypy
- [ ] 两租户 memory namespace 隔离
- [ ] QuotaExceeded 优雅（不崩）
- [ ] CSV/JSON 导出

---

## 8. 实施步骤

1. tenancy 包（tenant/quota/billing）
2. SymphonyLLM 挂 QuotaGuard
3. MemoryManager namespace 前缀
4. tests/tenancy/
5. 全量回归 + lint + mypy
6. 提交

---

## 9. 风险与回退

- **无 tenant 上下文**：不计数（LLM 零影响，向后兼容）
- **quota 并发**：单实例内存计数；跨进程后续
- **namespace 破坏**：默认无 tenant 时 namespace 不变（"default"）