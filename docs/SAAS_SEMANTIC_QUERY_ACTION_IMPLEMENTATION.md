# SaaS Semantic Query and Action Implementation

本文档描述 `SAAS_AGENT_DATA_SCOPE_ONTOLOGY_ACTION_ARCHITECTURE_PLAN_20260710.md`
第 1-8.8 节的已实现形态。第 9 节及之后的评测、评分归因和受控演化不在本轮范围内。

## 1. Runtime Topology

```text
SaaS frontend
  -> SaaS Gateway (user JWT, role and resource authorization)
  -> DeerFlow Gateway :8001
       -> /saas-query/* dedicated run profile
       -> Semantic API :8003 (internal network only)
            -> scoped read-only tenant database access
            -> semantic metadata database
       -> Action Worker (no public port)
            -> SaaS IAM revalidation API
            -> SaaS domain write API
```

- A 阶段 SQL Guard 是不可绕过的查询安全内核。
- B 阶段 Semantic API 是普通 SaaS 问数和 Action 的产品接口。
- Lead Agent、`general-purpose`、bash、文件和 sandbox 工具不参与 `/saas-query/*`。
- 携带签名 SaaS Authorization Context 的内部请求不能改选 Lead/custom profile，只能使用
  `saas-query` 或受控 SQL 兼容 profile。
- Gateway 和 Semantic API 不接收 Action Worker 的写凭据。
- Action Worker 不接受 Agent 提供的 SQL，只执行 Ontology 中发布的 domain API executor。

## 2. Public Gateway Routes

生产 SaaS 前端使用：

```text
POST /api/runs/saas-query/stream
POST /api/runs/saas-query/wait
POST /api/threads/{thread_id}/runs/saas-query/stream
POST /api/threads/{thread_id}/runs/saas-query/wait
```

兼容和 break-glass 路径保留：

```text
POST /api/runs/sql-cross-validate/stream
POST /api/runs/sql-cross-validate/wait
POST /api/threads/{thread_id}/runs/sql-cross-validate/stream
POST /api/threads/{thread_id}/runs/sql-cross-validate/wait
```

`/sql-cross-validate/*` 仍受 A 阶段 SQL scope policy 和 AST Guard 保护，但不应作为普通
SaaS 用户的长期入口。可用 `DEER_FLOW_SQL_CROSS_VALIDATE_ALLOWED_ROLES` 限制角色。

## 3. Trusted Authorization Contract

SaaS Gateway 调用 DeerFlow Gateway 时必须同时发送：

```text
X-DeerFlow-Internal-Token: <service token>
X-SaaS-Authorization-Context: <short-lived signed JWT>
```

JWT 必填 claims：

```json
{
  "iss": "saas-gateway",
  "aud": ["deerflow", "semantic-platform"],
  "sub": "user-id",
  "jti": "unique-token-id",
  "iat": 1783680000,
  "exp": 1783680300,
  "tenant_id": "tenant-id",
  "tenant_code": "tenant-code",
  "system_code": "efficiency",
  "role_codes": ["site_admin"],
  "permission_version": "42",
  "scope": {
    "mode": "resource_set",
    "site_ids": ["site-1"],
    "project_ids": ["project-1"]
  }
}
```

支持的 `scope.mode`：

- `resource_set`: token 内携带有限 site/project 集合。
- `scope_ref`: token 携带 `scope_ref`，Semantic API 调 SaaS IAM 解析。
- `tenant_all`: 仅由 SaaS 签名授权明确授予。
- `none`: 显式无数据权限，所有数据访问 fail closed。

`scope_ref` resolver 必须返回新的、短期、签名的 `resource_set` token。Semantic API 会独立
校验签名、issuer、audience、身份、租户、系统和权限版本，并拒绝 resolver 将 `scope_ref`
升级成 `tenant_all`。

推荐 TTL 不超过 300 秒。Gateway audience 默认 `deerflow`，Semantic audience 默认
`semantic-platform`；同一原始 token 被转发时，`aud` 应包含两个 audience。

## 4. A Phase: Scoped SQL Kernel

策略文件由 `DEER_FLOW_SQL_SCOPE_POLICY_PATH` 指定，默认文件是：

```text
backend/packages/harness/deerflow/semantic/default_sql_scope_policy.yaml
```

策略支持：

- `scoped`: 按 site/project 注入资源谓词。
- `reference`: 租户内参考数据，不注入资源谓词，但仍受字段 allowlist。
- `forbidden`: 禁止访问。
- 未分类表：默认禁止。
- 字段控制：`allowed_fields`、`hidden_fields`、`masked_fields`、
  `aggregate_only_fields`。

SQL 使用 `sqlglot` MySQL AST 解析，覆盖 JOIN、CTE、子查询和 UNION。资源 ID 只通过 bind
parameters 传递。Guard 拒绝多语句、DDL/DML、跨库、系统库、锁、outfile、危险函数、动态
LIMIT/OFFSET 和策略无法证明安全的查询。CTE 不得使用策略表名称进行 shadow。

SaaS schema/discovery 只返回策略允许的表和字段，不返回 sample rows，也不会在“物理表缺失”
错误中回显全库表名。query/checker/schema/list/show 的 allow、deny 和 error 均写结构化 scope
audit；audit 只保存规范化 hash、引用表/字段、策略/scope 版本、行数和错误类别，不保存原始 SQL
或结果全集。Guard 还拒绝 MySQL user/session variables、会话状态函数和 optimizer hints。
生产租户数据库账号仍应保持只读，作为第二道防线。

## 5. B Phase: Ontology and Semantic Query

Ontology 由 `DEER_FLOW_ONTOLOGY_PATH` 指定，默认文件是：

```text
backend/packages/harness/deerflow/semantic/default_ontology.yaml
```

当前默认发布的、经过现有字段信息确认的最小切片为：

- Objects: `Site`, `Project`
- Link: `Project.site`
- Metrics: `site.count`, `project.count`
- Action: `site.update_display_name`

不要仅根据表名猜测 Device、Energy、Alarm 等业务映射。新增对象、指标和 Action 前必须核对
DDL、业务代码、单位、时间口径和权限关系。

Semantic tools：

```text
resolve_business_context
search_objects
get_object
query_metrics
explain_metric
list_available_actions
propose_action
preview_action
execute_action
get_action_status
```

工具 schema 不暴露 tenant、database、JDBC URL、password、token 或 scope 参数。Semantic API
编译出的 SQL 仍必须通过 A 阶段 Guard。OAG 会按角色过滤 property/link metadata；结构化
`IN` filter 最多接受 100 个值，避免生成无界占位符 SQL。

## 6. Semantic-First Routing

`/saas-query/*` 先调用 Semantic API 做确定性 coverage resolution：

1. 已覆盖问题走 Semantic tools。
2. `mysql-query` 作为 semantic primary；普通查询只拿 5 个只读 Semantic tools，只有服务器
   coverage 明确命中授权 Action 时才加入 Action tools。
3. `mysql-validator` 只拿 `explain_metric`，不执行第二条查询。
4. Semantic API 不可用时 fail closed，不降级 SQL。
5. 未覆盖问题是否允许 scoped SQL fallback 由环境变量控制。

```text
DEER_FLOW_SAAS_QUERY_SQL_FALLBACK_MODE=scoped|disabled|role_allowlist
DEER_FLOW_SAAS_QUERY_SQL_FALLBACK_ROLES=tenant_admin,data_engineer
DEER_FLOW_SAAS_QUERY_SHADOW_SQL=false
```

Shadow 模式只在 Run Journal 记录 semantic/SQL 输出 hash 和 exact-match 标记，不把第二份结果
展示给用户。语义等价评测属于第 9 节，不在本轮实现范围。

## 7. Action Lifecycle

Action 状态迁移持久化到独立 transition 表：

```text
PROPOSED
  -> VALIDATED
  -> PREVIEWED
  -> PENDING_APPROVAL | READY
  -> EXECUTING
  -> SUCCEEDED | FAILED | COMPENSATING -> COMPENSATED | FAILED
```

规则：

- `execute_action` 只能引用已持久化 proposal。
- proposal 绑定 principal、tenant、scope hash、permission version、Action version、目标和参数。
- approval token 绑定 issuer、audience、proposal、principal、scope hash 和短 TTL。
- Worker 执行前重新从 SaaS IAM 获取 `action-worker` audience 的签名授权 token。
- Worker 重新检查角色、scope、目标可见性、目标版本、前置条件和 Action version。
- domain API 请求携带 correlation headers、`Idempotency-Key` 和可选 `If-Match`。
- execution status/result 读取必须继续匹配 principal、tenant、system、scope hash 和 permission
  version，权限变化后不能读取旧 scope 的执行结果。
- 只有 Ontology 显式声明 `compensation` domain API 的 Action 才进入补偿流程。
- 补偿使用独立幂等键；过期 `COMPENSATING` lease 可由新 Worker 恢复，不重放主 Action。
- Worker 只持久化 Ontology `result_fields` allowlist 中的响应字段，并限制响应大小、嵌套深度，
  递归移除敏感键。
- domain API path 禁止 `//host/...` network-path reference，防止改写 base host 并外送 Worker token。
- 任意未受控执行异常只返回通用错误，不持久化底层 URL、token 或响应诊断。

SQLite metadata DB 只适合单 Action Worker。多副本生产部署应改用 PostgreSQL，并使用正式
数据库 migration 流程。

## 8. Internal Semantic API

Semantic API 监听内部端口 `8003`，不应通过 nginx 或公网暴露。主要 endpoint：

```text
POST /v1/ontology/resolve
POST /v1/objects/search
GET  /v1/objects/{object_type}/{object_id}
POST /v1/queries
GET  /v1/metrics/{metric_id}
GET  /v1/actions
POST /v1/actions/proposals
POST /v1/actions/proposals/{proposal_id}/preview
POST /v1/actions/proposals/{proposal_id}/approve
POST /v1/actions/proposals/{proposal_id}/execute
GET  /v1/actions/executions/{execution_id}
```

每个请求必须携带：

```text
X-DeerFlow-Semantic-Token
X-SaaS-Authorization-Context
X-DeerFlow-Run-Id
X-DeerFlow-Thread-Id
X-DeerFlow-Tool-Call-Id
X-DeerFlow-Semantic-Trace-Id
```

创建 proposal 还必须携带 `Idempotency-Key`。

## 9. IAM and Domain API Contracts

### Scope resolver

```text
POST SAAS_AUTHORIZATION_SCOPE_RESOLVER_URL
X-SaaS-Internal-Token: DEER_FLOW_SEMANTIC_SCOPE_RESOLVER_TOKEN
X-SaaS-Authorization-Context: <original JWT>
```

响应：

```json
{"authorization_token": "<signed resource_set JWT>"}
```

### Action revalidation

```text
POST SAAS_ACTION_AUTHORIZATION_REVALIDATION_URL
X-SaaS-Internal-Token: DEER_FLOW_ACTION_WORKER_AUTHORIZATION_TOKEN
```

响应：

```json
{"authorization_token": "<signed action-worker JWT>"}
```

### Domain write API

Worker 按 Ontology executor 调用 `SAAS_DOMAIN_API_BASE_URL`，并发送：

```text
X-SaaS-Internal-Token: DEER_FLOW_ACTION_WORKER_DOMAIN_API_TOKEN
Idempotency-Key
If-Match
X-DeerFlow-Run-Id
X-DeerFlow-Thread-Id
X-DeerFlow-Tool-Call-Id
X-DeerFlow-Semantic-Trace-Id
```

## 10. Environment Variables

完整示例见根目录 `.env.example`。关键分组：

- JWT: `SAAS_AUTHORIZATION_JWT_*`, `SAAS_AUTHORIZATION_SEMANTIC_AUDIENCE`
- Semantic: `DEER_FLOW_SEMANTIC_*`, `DEER_FLOW_ONTOLOGY_PATH`,
  `DEER_FLOW_SQL_SCOPE_POLICY_PATH`
- Scope resolver: `SAAS_AUTHORIZATION_SCOPE_RESOLVER_URL`,
  `DEER_FLOW_SEMANTIC_SCOPE_RESOLVER_TOKEN`
- Migration routing: `DEER_FLOW_SAAS_QUERY_*`,
  `DEER_FLOW_SQL_CROSS_VALIDATE_ALLOWED_ROLES`
- Approval: `SAAS_ACTION_APPROVAL_*`
- Worker: `DEER_FLOW_ACTION_WORKER_*`, `SAAS_ACTION_*`, `SAAS_DOMAIN_API_BASE_URL`

## 11. Startup and Verification

Local：

```bash
make dev
```

`make dev/start` 会启动 Semantic API；只有
`DEER_FLOW_ACTIONS_ENABLED=true` 时才启动本地 Action Worker。本地 launcher 在 fork Worker 后会
从 Semantic API、Gateway、Frontend 和 nginx 的继承环境中移除 Worker 写凭据。

Docker production：

```bash
make up
```

Compose 启动 Gateway、Semantic API 和独立 Action Worker，共享 semantic metadata volume。
Semantic API 和 Worker 不发布宿主端口；Gateway、Semantic API 和可选 provisioner 都显式
覆盖为空的 Worker 写凭据。

核心测试：

```bash
cd backend
python -m pytest \
  tests/test_authorization_context.py \
  tests/test_sql_scope.py \
  tests/test_semantic_ontology_query.py \
  tests/test_semantic_api.py \
  tests/test_semantic_actions.py \
  tests/test_semantic_worker.py \
  tests/test_saas_query_agent.py
```

## 12. Explicit Non-Goals

本轮未实现：

- 第 9 节统一评测轨迹产品化。
- golden case 管理平台和自动评分。
- 评分归因面板。
- candidate -> eval -> canary -> rollback 的受控演化发布系统。

已有 audit 和状态轨迹是后续能力的数据基础，但不能宣称第 9 节已经完成。
