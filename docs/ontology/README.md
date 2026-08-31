# ontology - 企业级 Ontology（对标 Palantir）

把业务世界建模为可操作的对象/动作/函数/接口，配合治理与执行编排，
作为 Agent 的"外部大脑"和业务语义层。

## 分层架构

```
ontology/
├── semantic/       # 语义层
│   ├── object_type.py   # ObjectType/Property(ToolParameter)/LinkType
│   ├── interface.py     # Interface（多态）
│   └── vocabulary.py    # VocabularyValidator（统一词汇校验）
├── kinetic/        # 动能层
│   ├── action.py        # ActionType（参数/规则/副作用/审计）
│   └── function.py      # Function / derived_property
├── storage/        # 存储层
│   ├── object_store.py  # ObjectStore（对象存储）
│   ├── index.py         # ObjectIndex（搜索/过滤/聚合）
│   ├── graph_store.py   # GraphStore（图遍历/传递推理）
│   └── materialization.py # 物化（编辑回写）
├── governance/     # 治理层
│   ├── security.py      # SecurityManager/SecurityContext
│   ├── audit.py         # AuditManager
│   └── branching.py     # BranchManager（分支/回滚）
├── process/        # 执行编排层
│   ├── workflow.py      # WorkflowEngine（多动作编排）
│   ├── scheduler.py     # Scheduler（定时触发）
│   └── transaction.py   # TransactionManager（事务补偿）
├── query_engine.py  # 跨对象/接口查询
├── tool_gen.py      # 对象/动作/函数 → Tool
└── engine.py        # OntologyEngine（统一入口）
```

## 四种原语（核心建模）

| 原语 | 回答 | 用途 |
|------|------|------|
| **ObjectType** | 业务实体长什么样 | 定义对象（主键/属性/链接） |
| **ActionType** | 对对象做什么改变 | 写操作（规则/副作用/审计） |
| **Function** | 怎么计算新信息 | 纯计算（无副作用） |
| **Interface** | 多类型统一形状 | 抽象契约（跨类型） |

## 快速使用

```python
from agentorchestra.ontology import (
    ObjectType, ActionType, Function, Interface, OntologyEngine,
    SecurityContext, Workflow, StepNode,
)
from agentorchestra.tools.base import ToolParameter
from agentorchestra.tools.registry import ToolRegistry

# ① 定义对象类型
Customer = ObjectType("customer", "customer_id", properties=[
    ToolParameter(name="customer_id", type="string", description="ID", required=True),
    ToolParameter(name="name", type="string", description="客户名", required=True),
])

# ② 定义动作
def exec_create(params, ctx):
    return ctx["object_store"].insert("customer", params)
CreateCustomer = ActionType("create_customer", parameters=[
    ToolParameter(name="customer_id", type="string", description="ID", required=True),
    ToolParameter(name="name", type="string", description="名", required=True),
], execute_fn=exec_create)

# ③ 定义函数
ComputeDiscount = Function("compute_discount",
    impl=lambda args, ctx: args.get("amount", 0) * 0.9,
    arguments=[ToolParameter(name="amount", type="number", description="金额", required=True)])

# ④ 装配引擎
engine = OntologyEngine(security_ctx=SecurityContext("agent", ["agent"]))
engine.register_object_type(Customer)
engine.register_action(CreateCustomer)
engine.register_function(ComputeDiscount)
engine.allow(["agent"], resource="*", action="*")

# ⑤ 挂载给 Agent（解耦，任何 Agent 可用）
registry = ToolRegistry()
engine.mount(registry)
# → QueryCustomer / create_customer / CallComputeDiscount
```

## 治理能力

```python
# 权限
engine.allow(["admin"], resource="*", action="*")
engine.security.check("customer", "write", admin_ctx)

# 审计
engine.audit.log("admin", "customer", "create", detail={...})
engine.audit.query(resource="customer")

# 分支/回滚
engine.snapshot_branch("before_change")
engine.switch_branch("before_change")
```

## 执行编排

```python
# ① 流程（Workflow）
wf = Workflow("fulfill")
wf.add_node(StepNode("s1", "create_customer", {"name": "$input.name"}), entry=True)
wf.add_node(StepNode("s2", "compute_discount", {"amount": "$s1.amount"}, depends_on=["s1"]))
engine.workflow.register_workflow(wf)
engine.workflow.run("fulfill", {"input": {"name": "张三"}}, ctx={"object_store": store})

# ② 调度（Scheduler）
engine.scheduler.add_interval("heartbeat", my_func, interval_seconds=60)
engine.scheduler.start()

# ③ 事务（Transaction - Saga 补偿）
engine.transaction.register("扣库存", deduct, undo_deduct)
engine.transaction.execute([
    {"action": "扣库存", "params": {"qty": 3}},
    {"action": "扣款", "params": {"amount": 100}},
])   # 扣款失败 → 自动补偿扣库存
```

## 与 Agent 解耦

`OntologyEngine.mount(registry)` 只依赖 `ToolRegistry` 契约，不绑定 Agent 类型：
ReActAgent / SimpleAgent / ReflectionAgent / PlanSolveAgent 及子代理通过基类自动获得能力。

## 校验能力

- **统一词汇**：拒绝未在 ObjectType 声明的属性
- **数据校验**：主键/必填/类型 + 链接 domain/range（含子类继承）
- **类层次**：`parent_type` + `get_subclasses` / `get_superclasses`
