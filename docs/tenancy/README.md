# tenancy — 多租户隔离（P6 / M6）

多个业务团队/客户共享同一部署时，资源/记忆/Agent 调用按租户隔离；token 配额可限额，用量可导出。

设计见 [M6 spec](../superpowers/specs/2026-09-04-m6-multitenancy-design.md)。

## 模块组成

| 文件 | 职责 |
|------|------|
| `tenant.py` | `TenantManager` / `TenantContext`：tenant_id + user_id 上下文（ContextVar） |
| `quota.py` | `QuotaManager` / `TokenQuota` / `QuotaExceeded`：token 配额限额 |
| `billing.py` | `UsageRecorder`：用量记录 + CSV/JSON 导出 |

## TenantContext

```python
from agentorchestra.tenancy import TenantManager

tm = TenantManager()
with tm.sync_run_as("acme", "alice"):
    tm.namespace()    # "acme:alice"（user_id 空 → "acme"）
    tm.tenant_id()    # "acme"
# 退出还原为 default
```

## namespace 隔离（Memory）

`MemoryManager` 自动把 namespace 加 tenant 前缀（无租户上下文时不变 "default"）：
两个租户即使显式用相同 namespace 也完全隔离。

```python
from agentorchestra.tenancy import TenantManager
tm = TenantManager()
with tm.sync_run_as("tenant_a", "u1"):
    memory_manager.remember("A 的秘密")     # 落 tenant_a:u1 命名空间
with tm.sync_run_as("tenant_b", "u2"):
    hits = memory_manager.recall("秘密")     # 只命中 B 的
```

## Token 配额（LLM 层 QuotaGuard）

`SymphonyLLM` 支持可选 `quota_manager` / `usage_recorder`；invoke/ainvoke 成功后按
`usage.total_tokens` 扣减。tenant context 不存在时不计数（向后兼容）。

```python
from agentorchestra.tenancy import QuotaManager, QuotaExceeded

qm = QuotaManager()
qm.set_limit("acme", 100_000)

llm = SymphonyLLM(..., quota_manager=qm, usage_recorder=recorder)
with tm.sync_run_as("acme"):
    resp = llm.invoke(messages)   # 配额耗尽 → QuotaExceeded（优雅，不崩进程）
```

## 用量导出

```python
from agentorchestra.tenancy import UsageRecorder

ur = UsageRecorder()
ur.record("acme", "gpt-4o", tokens=1234, latency_ms=800)
ur.by_tenant()     # {"acme": 1234}
ur.export_csv("usage.csv")    # CSV（给计费系统）
ur.export_json("usage.json")  # JSON
```

## 配置

配额在 `QuotaManager` 运行时设置；SymphonyLLM 构造传入（框架不存配额配置，避免全局可变状态耦合）。
