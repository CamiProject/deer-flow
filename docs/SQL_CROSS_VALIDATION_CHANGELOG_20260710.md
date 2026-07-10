# SQL 问数交叉验证接口 Changelog

**日期**: 2026-07-10
**当前分支**: `custom-v3-saas`
**关联提交**:

- `1ea04ef3` - `security(tools)(sql): restrict SaaS SQL cross-validation to SQL-only subagents`
- `ad8414f7` - `fix(tools): SaaS SQL tools - NLQ -query correct conf_database column names`

## 当前结论

SaaS 问数交叉验证已经改为受限 SQL 专用链路：

- 新问数入口必须走 `runs/sql-cross-validate` 专用接口。
- 后端固定使用 `sql-cross-validation` run profile。
- 每次运行固定并发启动 2 个 SQL subAgent。
- 主查询角色使用 `mysql-query`。
- 交叉验证角色使用 `mysql-validator`。
- 两个 subAgent 都只注入 `SQL_TOOLS`，不再使用 `general-purpose`。
- SaaS 租户库连接信息只从可信 runtime context 和 `conf_database` 解析，不接受用户消息或客户端 context 覆盖。

这次安全修正的核心目标是：问数链路不能继承通用 Agent 的 bash、file、workspace、sandbox、code execution 等能力，避免 SQL 问数入口被扩展成读取环境变量、`.env`、本地文件或执行非 SQL 操作的通道。

## 对外接口

Threaded 接口：

```text
POST /api/threads/{thread_id}/runs/sql-cross-validate/stream
POST /api/threads/{thread_id}/runs/sql-cross-validate/wait
```

Stateless 接口：

```text
POST /api/runs/sql-cross-validate/stream
POST /api/runs/sql-cross-validate/wait
```

普通 run 接口行为不变：

```text
POST /api/threads/{thread_id}/runs/stream
POST /api/threads/{thread_id}/runs/wait
POST /api/runs/stream
POST /api/runs/wait
```

普通接口仍按原有 assistant / Lead Agent 逻辑执行，不会自动启用 SQL 交叉验证。

## 当前运行角色

| Runtime role | SubAgent | 工具范围 | 职责 |
| --- | --- | --- | --- |
| Primary execution / 主查询 | `mysql-query` | `SQL_TOOLS` only | 独立理解用户问题、探索 schema、生成并执行只读 SQL，返回主查询结果 |
| Domain validation / 领域验证 | `mysql-validator` | `SQL_TOOLS` only | 独立选择查询路径，验证筛选条件、聚合、时间范围、数值结果和业务结论 |

旧设计中的 `general-purpose` 已从 SQL 交叉验证 profile 中移除。它仍可用于普通非 SQL 任务，但不参与 SaaS 问数交叉验证。

## 工具限制

SQL 交叉验证 profile 创建 `SubagentExecutor` 时只传入：

```python
tools=list(SQL_TOOLS)
```

当前 SQL 工具集合包括：

```text
sql_show_databases
sql_list_tables
sql_schema
sql_query
sql_query_checker
```

`mysql-query` 和 `mysql-validator` 的 subAgent 配置也都限定在 SQL 工具名集合，并显式禁用：

```text
task
ask_clarification
present_files
```

安全边界：

- 不能使用 bash。
- 不能读写文件。
- 不能访问 workspace。
- 不能使用 sandbox / code execution。
- 不能通过 `task` 再委派到通用 Agent。
- 不能要求用户切换租户或提供数据库连接信息。
- 不能泄露 JDBC URL、密码、内部 token、环境变量或 datasource 连接细节。

## Run Profile 行为

SQL 交叉验证路由调用 `start_run()` 时固定覆盖运行参数：

```python
assistant_id_override="sql-cross-validation"
context_overrides={
    "subagent_enabled": True,
    "max_concurrent_subagents": 2,
}
required_stream_modes=["custom"]
```

效果：

- 客户端传入的 `assistant_id` 不会把该 run 改回普通 Agent。
- 客户端传入 `subagent_enabled=false` 不能关闭交叉验证。
- 客户端传入其他 `max_concurrent_subagents` 不能改变固定双 Agent 策略。
- run metadata 会写入 `run_profile: sql-cross-validation`。
- 即使客户端只请求 `messages-tuple`，服务端也会强制合并 `custom` stream mode，以便前端接收交叉验证进度事件。

## 进度事件

SQL 交叉验证通过 `custom` stream event 输出进度：

```text
sql_cross_validation_started
sql_cross_validation_subagent_completed
```

这些事件用于提示前端当前已进入固定 SQL 交叉验证 profile，以及两个 SQL subAgent 的完成状态。

## SaaS 数据源解析修正

`ad8414f7` 修正了 SaaS 租户数据源解析逻辑。

`conf_database` 查询现在使用实际的 snake_case 字段：

```sql
SELECT code, url, user_name, password, driver_class
FROM conf_database
WHERE code = ...
LIMIT 1
```

返回映射也使用：

```text
user_name
driver_class
```

不再使用错误的 camelCase 字段：

```text
userName
driverClass
```

这保证 `tenant_datasource.py` 能按当前 SaaS 配置库表结构解析租户数据库连接参数。

## 租户上下文边界

SaaS 租户身份仍只接受服务端可信来源：

- `tenant_id`
- `tenant_code`
- `tenant_name`
- `system_code`
- `saas_user_id`

这些字段属于 protected SaaS context key。客户端从 `body.context` 或 `body.config.context/configurable` 传入时会被剥离；真实值只由内部可信 Gateway header 注入。

SQL 工具根据 runtime context 解析当前租户 datasource，只查询当前租户和系统对应的数据库范围。

## 最终汇总策略

最终汇总阶段只读取两个 SQL subAgent 的最终输出，不再生成或执行新的 SQL。

汇总规则：

- 两边成功且 SQL 路径、关键筛选条件、数值结果或业务结论一致：输出“已通过交叉验证”。
- 两边成功但结果或路径不一致：输出“交叉验证不一致”，展示差异点并标注低置信度。
- 单边失败：输出“未完成完整验证”，展示成功侧结果和失败侧原因。
- 双边失败：输出“未完成完整验证”，展示失败原因，不编造查询结果。
- 汇总模型失败时回退到结构化 fallback 摘要，不因为业务不一致直接把 run 标记为 error。

## 涉及文件

主要实现：

- `backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py`
- `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py`
- `backend/packages/harness/deerflow/subagents/builtins/mysql_validator.py`
- `backend/packages/harness/deerflow/tools/builtins/tenant_datasource.py`
- `backend/app/gateway/services.py`
- `backend/app/gateway/routers/runs.py`
- `backend/app/gateway/routers/thread_runs.py`

主要测试：

- `backend/tests/test_sql_cross_validation_agent.py`
- `backend/tests/test_saas_sql_tools.py`
- `backend/tests/test_gateway_services.py`
- `backend/tests/test_subagent_prompt_security.py`
- `backend/tests/test_subagent_skills_config.py`

## Verification

本次 rebase 后已验证的相关测试：

```bash
cd backend
uv run pytest tests/test_internal_auth.py tests/test_thread_state_reducers.py tests/test_compose_default_workers.py -q
uv run pytest tests/test_sql_cross_validation_agent.py tests/test_saas_sql_tools.py tests/test_runs_api_endpoints.py -q
uv run pytest tests/test_gateway_services.py -q
```

结果：

```text
55 passed
34 passed
75 passed
```

补充前端检查：

```bash
cd frontend
pnpm exec eslint src/core/i18n/locales/zh-CN.ts --ext .ts,.tsx
```

结果：通过。

完整 `pnpm check` 在当前本地环境因前端依赖缺失未完成，缺失模块包括 `@rstest/core`、`@rsbuild/plugin-react`、`rehype-slug` 等；这不是本次 SQL 交叉验证代码路径的类型错误。

## 当前设计与旧设计差异

| 项目 | 旧设计 | 当前设计 |
| --- | --- | --- |
| 主查询 subAgent | `general-purpose` | `mysql-query` |
| 验证 subAgent | `mysql-query` | `mysql-validator` |
| 工具范围 | 计划限制 SQL，但存在通用 Agent 继承风险 | 两个 subAgent 都只注入 `SQL_TOOLS` |
| 通用 Agent 参与 | 参与主查询 | 不参与 SQL 交叉验证 |
| 租户 datasource 字段 | 曾使用错误 camelCase 字段 | 使用 `user_name` / `driver_class` |
| 客户端可否关闭 subAgent | 不允许 | 不允许，服务端强制覆盖 |
| 客户端可否改变并发数 | 不允许 | 不允许，固定 2 个 SQL subAgent |
| 客户端可否伪造 tenant context | 不允许 | 不允许，protected key 剥离 + trusted header 注入 |

## 后续建议

- 将两个 SQL subAgent 的输出进一步结构化为固定 JSON schema，降低最终汇总模型判断不一致的自由度。
- 对数值结果、时间范围、租户范围、筛选条件做 deterministic diff。
- 将“已通过 / 不一致 / 未完成完整验证”的状态写入 run metadata 或 message metadata，便于前端展示。
- 持续避免 SQL 问数链路引入非 SQL 工具，尤其是 bash、file、workspace、sandbox、task 委派能力。
