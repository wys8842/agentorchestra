# 命名约定

本框架的命名原则：**包级唯一 + 语义清晰**；跨包允许同名（因有 `agentorchestra.<pkg>` 命名空间隔离），
但**同一模块/包内不得有歧义同名**。

## 规则

### 1. 包名（模块顶层目录）
- 小写、语义化、单一职责。
- 现有顶层包：`core agents context tools ontology memory skills observability`
  `state tx orchestration governance tenancy`。

### 2. 文件名
- 在**同一包内**必须唯一，且小写下划线命名（`snake_case`）。
- **跨包允许同名文件**，如：
  - `memory/index.py` 与 `ontology/storage/index.py`
  - `core/metrics.py` 与 `observability/metrics.py`
  - `ontology/process/scheduler.py` 与 `orchestration/scheduler.py`
  - `state/wal.py` 与 `tx/wal.py`
  它们靠完整模块路径区分（`from agentorchestra.observability.metrics import ...`），**不产生歧义**。
- `__init__.py` 是 Python 包约定，不计入命名冲突。

### 3. 类名
- `CapWords`；同一模块内唯一。
- 跨包可有同名类（`MetricsCollector` 在 core 与 observability 各一），引用必带包前缀。

### 4. 方法名 — 协议多态（允许重复）
同一语义在不同类上出现同名方法是**面向接口的正常现象**，保留：
`run()/arun()/execute()/close()/get_parameters()/to_dict()/add_message()` 等。
它们是：
- 工具协议（`Tool.get_parameters`）
- 存储基类（`insert/update/delete/get`）
- 序列化协议（`to_dict/from_dict`）
- Agent 生命周期（`run/arun/stream_run`）

> ⚠️ 不要为追求"全项目字面唯一"而重命名这些——那会摧毁抽象与多态。

### 5. 字段 / 属性
- 类字段在**类继承链内**语义一致；同名不同义属于 bug，须改。
- 预留/系统字段用固定集合并文档化：
  - `ObjectType.SYSTEM_FIELDS = {version, created_tx, last_modified_tx}`
  - P0-P6 的状态字段（thread/checkpoint/interrupt/lock/…）统一落在 `state`，避免各包自造同名异义字段。

### 6. 内部 / 私有
- `_private` 模块内私有；`__dunder__` 协议方法。
- 私有成员不参与公共 API 文档，允许少量无 docstring（见注释规范）。

## 判别清单

新增代码前自问：
1. 新文件名是否与**同包**内现有文件重名？→ 是则加语义前缀。
2. 新类是否与**同模块**内类重名？→ 是则改名。
3. 新方法名是否与基类/兄弟类**语义一致**？→ 一致为多态；不一致必须改名。
4. 新字段是否与同对象其它字段**同名异义**？→ 是则立即修。

## 落地现状（审计结论）

全局审计（131 个 py 文件）显示：
- 跨包同名文件 5 组：均靠包路径隔离，**保留**（见规则 2），并已在 [architecture.md](architecture.md) 的依赖表说明。
- 跨包同名类 `MetricsCollector`：core（框架级，prometheus_client 可选）与
  observability（零依赖 SLO 指标）职责不同，**保留**，文档注明差异。
- 其余数百处 `get/run/close/to_dict` 等均为**协议多态**，**保留**。
- 唯一同文件内 "重名" 是 `Agent.system_prompt`/`Agent._history` 的 property getter/setter 对，属正常模式。
