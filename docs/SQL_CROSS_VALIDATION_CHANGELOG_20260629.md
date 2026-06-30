# SQL 问数交叉验证接口 Changelog

**日期**: 2026-06-29  
**当前分支**: `custom-v3-saas`  
**当前提交**: `5b8c4b1d630544280520ef3628f8083b3219f68f`  
**提交标题**: `SQL问数subAgent交叉验证接口按照规划开发`  
**关联规划**: `SQL 问数交叉验证接口规划`

## 结论

本次改动已经基本实现规划中的 v1 需求：DeerFlow 新增了专用 SQL 问数交叉验证入口，调用该入口时不再由 Lead Agent 自行决定是否派生 subAgent，而是由后端固定编排两个 SQL subAgent 并发查询：

| 运行角色 | 底层 subAgent | subAgent 能力域 | 在本 profile 中的职责 |
| --- | --- | --- | --- |
| Primary execution / 主查询 | `general-purpose` | 通用任务执行 | 独立理解问题、生成 SQL、执行主查询并返回结果 |
| Domain validation / 领域验证 | `mysql-query` | MySQL 查询 | 独立理解问题、生成 SQL、执行验证查询并返回验证结果 |

规划中的核心要求已经落地：专用接口、固定 run profile、强制两个 subAgent、SQL 工具范围限制、trusted runtime context 透传、SSE 进度事件、普通 `/runs/stream` 行为不变。

## 命名与运行角色约定

本功能采用“能力域名称 + run profile 分配运行角色”的约定：

- subAgent 名称表达能力域，不表达它在某次 run 中的最终运行角色。
- 运行角色由专用 run profile 决定。
- `general-purpose` 表示通用任务执行能力；在 `sql-cross-validation` profile 中，它被分配为 primary execution / 主查询角色。
- `mysql-query` 表示 MySQL 查询能力域；在 `sql-cross-validation` profile 中，它被分配为 domain validation / 领域验证角色。
- 后续如果扩展 research、write、code 等场景，也可以沿用同一模式：`general-purpose` 做 primary execution，领域 subAgent 做 domain validation。

因此，`mysql-query` 在普通场景中仍可表示 MySQL 查询能力；在 SQL 交叉验证入口中，它不是普通主查询者，而是被 `sql-cross-validation` profile 明确指定为 SQL verifier。

## Added

### 新增 SQL 交叉验证 Agent Factory

**文件**:

- `backend/packages/harness/deerflow/agents/sql_cross_validation/__init__.py`
- `backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py`

新增 `make_sql_cross_validation_agent`，作为专用 deterministic run profile 的 agent factory。

主要行为：

- 从当前 run 的最后一条用户消息提取问数问题。
- 并发启动两个 `SubagentExecutor`：
  - `general-purpose`
  - `mysql-query`
- 两个 subAgent 均只注入 `SQL_TOOLS`。
- 两个 subAgent 均继承当前 run 的 `thread_id`、`run_id`、`model_name`、`app_config`、trusted SaaS context、journal 等 runtime context。
- 子 Agent 完成后进入最终汇总阶段。
- 通过 `custom` stream event 输出交叉验证进度。

### 新增 API 路由

**文件**:

- `backend/app/gateway/routers/thread_runs.py`
- `backend/app/gateway/routers/runs.py`

新增 threaded 接口：

```text
POST /api/threads/{thread_id}/runs/sql-cross-validate/stream
POST /api/threads/{thread_id}/runs/sql-cross-validate/wait
```

新增 stateless 接口：

```text
POST /api/runs/sql-cross-validate/stream
POST /api/runs/sql-cross-validate/wait
```

这些接口复用现有 `RunCreateRequest`、`RunManager`、`StreamBridge`、SSE、wait、cancel、join、message/checkpoint 持久化能力。

### 新增 run profile 常量与 factory 路由

**文件**: `backend/app/gateway/services.py`

新增：

```python
SQL_CROSS_VALIDATION_ASSISTANT_ID = "sql-cross-validation"
```

当 assistant id 为 `sql-cross-validation` 时，`resolve_agent_factory()` 返回 `make_sql_cross_validation_agent`，不再走普通 `make_lead_agent`。

### 新增强制 stream mode 合并

**文件**: `backend/app/gateway/services.py`

新增 `merge_stream_modes()` 与 `start_run(..., required_stream_modes=...)`。

SQL 交叉验证接口会强制加入：

```python
required_stream_modes=["custom"]
```

因此即使客户端只传 `messages-tuple` 或其他 stream mode，前端仍能收到：

- `sql_cross_validation_started`
- `sql_cross_validation_subagent_completed`

### 新增 runtime context 透传能力

**文件**: `backend/packages/harness/deerflow/subagents/executor.py`

`SubagentExecutor` 新增可选参数：

```python
runtime_context: dict[str, Any] | None = None
```

在 subAgent `agent.astream(..., context=context)` 时透传给子 Agent，保证 trusted SaaS tenant context、`app_config`、`thread_id` 等运行时上下文不会丢失。

## Changed

### SQL 交叉验证接口强制覆盖客户端策略

SQL 交叉验证路由调用 `start_run()` 时固定传入：

```python
assistant_id_override="sql-cross-validation"
context_overrides={
    "subagent_enabled": True,
    "max_concurrent_subagents": 2,
}
required_stream_modes=["custom"]
```

效果：

- 客户端传 `assistant_id` 不会覆盖为普通 Agent。
- 客户端传 `subagent_enabled=false` 不会关闭交叉验证。
- 客户端传 `max_concurrent_subagents` 不会改变 v1 固定双 Agent 策略。
- run metadata 会写入 `run_profile: sql-cross-validation`。

### `build_run_config()` 避免误注入 custom agent name

**文件**: `backend/app/gateway/services.py`

`sql-cross-validation` 被视为专用 run profile，不会被当成普通 custom agent 注入 `agent_name`，避免误走 Lead Agent 的 custom agent 加载路径。

### 最终汇总策略

**文件**: `backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py`

最终汇总阶段只基于两个 subAgent 的最终输出做比较，不再执行 SQL。

汇总规则：

- 两侧成功且结果一致：输出“已通过交叉验证”，包含主 SQL、验证 SQL 和结果摘要。
- 两侧成功但结果或口径不一致：输出“交叉验证不一致”，展示差异点并标注低置信度。
- 单边失败：输出“未完成完整验证”，展示成功侧结果和失败侧原因。
- 双边失败：输出“未完成完整验证”，展示失败原因，不编造查询结果。

如果最终汇总模型调用失败，会回退到结构化 fallback 摘要；业务不一致或单边失败不会直接把 run 标记为 error。

## Security

本次改动符合规划中的安全边界：

- SQL 交叉验证入口只给 subAgent 注入 `SQL_TOOLS`，避免 `general-purpose` 在问数入口使用非 SQL 工具跑偏。
- trusted SaaS context 仍由服务端注入，不信任用户 message 或 request context 中的租户覆盖。
- `force_run_context_values()` 会覆盖客户端伪造的 `subagent_enabled`、`max_concurrent_subagents`。
- `build_run_config()` 仍会剥离 protected SaaS context key，租户身份只接受 trusted Gateway headers。
- SQL 只读限制沿用现有 SQL 工具实现。
- prompt 明确要求不泄露数据库连接串、密码、内部 token 或租户认证信息。

## Compatibility

普通 run 行为保持不变：

- `POST /api/threads/{thread_id}/runs/stream`
- `POST /api/threads/{thread_id}/runs/wait`
- `POST /api/runs/stream`
- `POST /api/runs/wait`

仍按原有 assistant/Lead Agent 逻辑执行，不会自动启用 SQL 交叉验证。

## Verification

已覆盖的测试点：

- 新 profile 能解析到 `make_sql_cross_validation_agent`。
- `sql-cross-validation` 不会被当成普通 custom agent 注入 `agent_name`。
- SQL 交叉验证入口会强制覆盖 `assistant_id/subagent_enabled/max_concurrent_subagents`。
- SQL 交叉验证入口会强制合并 `custom` stream mode。
- 每次请求固定启动 `general-purpose` 与 `mysql-query` 两个 subAgent。
- 两个 subAgent 收到相同用户问题、相同 trusted runtime context。
- 两个 subAgent 的工具范围被限制为 `SQL_TOOLS`。
- 单边失败、双边失败、最终汇总模型可用等场景有单测覆盖。
- 普通 run、stateless owner isolation、task tool 相关回归通过。

验证命令：

```bash
cd backend
uv run pytest tests/test_sql_cross_validation_agent.py tests/test_gateway_services.py tests/test_runs_api_endpoints.py tests/test_stateless_runs_owner_isolation.py tests/test_task_tool_core_logic.py -q
uv run python -m py_compile packages/harness/deerflow/agents/sql_cross_validation/agent.py packages/harness/deerflow/agents/sql_cross_validation/__init__.py app/gateway/services.py app/gateway/routers/runs.py app/gateway/routers/thread_runs.py packages/harness/deerflow/subagents/executor.py
```

最近一次验证结果：

```text
110 passed
py_compile passed
git diff --check passed
```

## 与原规划逐项对照

| 规划项 | 当前状态 | 说明 |
| --- | --- | --- |
| 新增专用问数接口 | 已实现 | threaded/stateless 的 stream/wait 均已新增 |
| 复用现有 run body shape | 已实现 | 继续使用 `RunCreateRequest` |
| 复用 RunManager、StreamBridge、SSE、wait 能力 | 已实现 | 新路由仍通过 `start_run()` 和现有 SSE/wait 流程 |
| 固定使用 `sql-cross-validation` profile | 已实现 | `assistant_id_override` 强制覆盖 |
| 不让 Lead Agent 自行决定是否派生 subAgent | 已实现 | 新 profile 直接编排两个 `SubagentExecutor` |
| 固定并发两个 subAgent | 已实现 | `asyncio.create_task()` + `asyncio.gather()` |
| 主查询使用 `general-purpose` | 已实现 | 主查询角色固定为 `general-purpose` |
| 验证使用 `mysql-query` | 已实现 | 验证角色固定为 `mysql-query` |
| 两者只使用 SQL 工具 | 已实现 | executor 初始化时只传 `SQL_TOOLS` |
| 继承 thread/tenant/user/model/runtime context | 已实现 | `runtime_context` 透传到 `SubagentExecutor` |
| 客户端不能关闭 subAgent | 已实现 | `force_run_context_values()` 强制覆盖 |
| 客户端不能改变并发数 | 已实现 | v1 固定 `max_concurrent_subagents=2` |
| 客户端不能用 assistant_id 覆盖为普通 Agent | 已实现 | 路由层使用 `assistant_id_override` |
| 不一致不标记 run error | 已实现 | 业务不一致进入最终答案，运行时异常才走 error |
| 单边失败返回另一边结果和失败原因 | 已实现 | 汇总/fallback 均覆盖 |
| 双边失败返回失败原因 | 已实现 | 汇总/fallback 均覆盖 |
| trusted SaaS context 不接受用户覆盖 | 已实现 | protected key 剥离 + trusted headers 注入 |
| 前端可看到流式进度 | 已实现 | 新接口强制 `custom` stream mode |
| 普通 `/runs/stream` 行为不变 | 已实现 | 只在新路由传入 profile override |

## 实现偏差与说明

### `mysql-query` 默认 subAgent 配置未全局改成验证角色

规划中提到“改造 `mysql-query` subAgent 为验证角色”。当前实现没有修改 `mysql-query` 的全局默认配置，而是在 `sql-cross-validation` profile 中通过 verifier prompt 让 `mysql-query` 扮演验证角色。

这样做的原因是避免破坏普通场景中已有的 `mysql-query` 查询能力。当前效果等价于：只在新 SQL 交叉验证入口里，`mysql-query` 被强制作为验证 Agent 使用。

### 最终一致性判断由汇总模型完成

当前 v1 没有实现结构化 SQL/结果的硬编码 diff 引擎，而是由最终汇总模型读取两侧结果并输出“已通过交叉验证”或“交叉验证不一致”。

如果汇总模型失败，会回退到结构化摘要，避免业务结果导致 run error。

## 后续建议

后续可以考虑增强为更严格的结构化验证：

- 要求两个 subAgent 输出固定 JSON schema。
- 对数值型结果做 deterministic diff。
- 对 SQL 中的时间范围、租户范围、筛选条件做结构化提取。
- 将“已通过/不一致/未完整验证”落到 run metadata 或 message metadata，便于前端展示状态。
