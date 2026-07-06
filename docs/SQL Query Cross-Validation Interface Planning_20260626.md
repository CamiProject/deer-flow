# SQL 问数交叉验证接口规划

## Summary

### 2026-07-06 Security Update

This plan has been tightened for SaaS question-answering safety. The dedicated SQL cross-validation endpoints remain the only recommended DeerFlow entrypoints for SaaS asking-data flows:

```text
POST /api/threads/{thread_id}/runs/sql-cross-validate/stream
POST /api/threads/{thread_id}/runs/sql-cross-validate/wait
POST /api/runs/sql-cross-validate/stream
POST /api/runs/sql-cross-validate/wait
```

The role assignment is superseded as follows:

| Runtime role | SubAgent | Tool scope |
| --- | --- | --- |
| Primary execution / main query | `mysql-query` | SQL tools only |
| Domain validation / cross-check | `mysql-validator` | SQL tools only |

`general-purpose` remains available for ordinary non-SQL tasks, but it must not participate in SaaS asking-data flows. The SQL cross-validation profile must not use `bash`, file, workspace, sandbox, code-execution, or general-purpose delegated tools, so it has no normal tool path to read `.env` or process environment secrets.
- 你的方向合理：问数交叉验证不应只靠 `mysql-query` skill/prompt，而应新增一个专用运行入口，由后端强制编排两个 subAgent。
- v1 目标：新增一个面向智能问数的 `stream/wait` 兼容接口，内部固定并发启动 2 个 SQL subAgent：`general-purpose` 执行主查询，`mysql-query` 做独立交叉验证。
- 关键修正：不要让 Lead Agent 自己决定是否派生两个 subAgent；新增 deterministic SQL cross-validation run profile/agent factory，保证每次请求都启动这两个角色。

## Key Changes
- 新增问数接口，复用现有 `RunCreateRequest`、RunManager、StreamBridge、SSE、cancel/join/message 持久化能力：
  - `POST /api/threads/{thread_id}/runs/sql-cross-validate/stream`
  - `POST /api/threads/{thread_id}/runs/sql-cross-validate/wait`
  - 可选同步补齐 stateless 版本：`POST /api/runs/sql-cross-validate/stream|wait`
- 新增内部 `sql-cross-validation` agent factory，而不是走普通 `make_lead_agent`：
  - 从用户最后一条 message 提取问数问题。
  - 并发启动 `general-purpose` 和 `mysql-query` 两个 `SubagentExecutor`。
  - 两者都继承当前 run 的 thread、tenant、user、model、sandbox/runtime context。
  - 两者工具范围限制为 SQL 相关工具，避免 general-purpose 在问数入口里使用非 SQL 工具跑偏。
- 改造 `mysql-query` subAgent 为验证角色：
  - `general-purpose` prompt：独立完成查询并返回 SQL、关键筛选条件、结果表、简短结论。
  - `mysql-query` prompt：不信任主查询结果，独立理解问题、独立生成 SQL、独立执行并返回验证结果。
  - 两个 Agent 不互相共享推理过程；只在最终汇总阶段比较结果。

## Behavior
- 接口强制策略：
  - 客户端传不传 `subagent_enabled` 都不影响，该接口始终启动 2 个 subAgent。
  - 客户端传 `max_concurrent_subagents` 不影响 v1，该接口固定两个角色。
  - 客户端不能通过 `assistant_id` 覆盖为普通 Agent；该接口内部固定使用 `sql-cross-validation` run profile。
- 结果策略：
  - 一致：返回“已通过交叉验证”的最终答案，包含主 SQL、验证 SQL、结果摘要。
  - 不一致：run 不标记为 error，最终答案标注“交叉验证不一致”，展示主结果、验证结果、差异点、低置信度结论。
  - 单边失败：返回另一边结果和失败原因，标注“未完成完整验证”。
  - 双边失败或基础设施异常：SQL/业务失败作为最终消息返回；运行时异常才标记 run error。
- 安全边界：
  - 只支持问数读操作，沿用 SQL 工具的只读限制。
  - SaaS 租户上下文只接受 trusted runtime context，不接受用户 message/context 中的 tenant/database override。
  - v1 不做写 SQL、跨租户查询、自动导出文件、自动多轮重试。

## Test Plan
- Router/service 测试：
  - 新接口复用现有 run body shape，能创建 run、stream、wait。
  - 新接口覆盖客户端 `assistant_id/subagent_enabled/max_concurrent_subagents`，固定进入交叉验证 profile。
  - 普通 `/runs/stream` 行为不变。
- Orchestration 单测：
  - 每次请求恰好启动 `general-purpose` 和 `mysql-query` 两个 subAgent。
  - 两个 subAgent 并发执行，并收到相同用户问题和相同 runtime context。
  - 一致、不一致、单边失败、双边失败分别生成正确最终消息。
- 安全测试：
  - 用户提供 tenant/database override 不会覆盖 trusted SaaS context。
  - SQL 工具只读限制仍生效。
  - `mysql-query` 验证 prompt 不泄露连接串、密码、内部 token。
- 前端/网关验收：
  - 前端用新问数接口能看到流式进度和最终回答。
  - run message/event 查询、取消、join 与普通 run 保持兼容。

## Assumptions
- 默认采用“新增专用问数接口”，不在现有 `/runs/stream` 上加 flag，避免污染普通 Agent 语义。
- 默认采用“独立查询验证”，而不是只复核主 SQL，因为它更能发现 SQL 设计和业务理解错误。
- 默认不一致时返回争议结果，不直接让 run 失败；失败只用于运行时异常。
- v1 固定两个角色，不开放客户端配置验证 Agent 数量或角色。
