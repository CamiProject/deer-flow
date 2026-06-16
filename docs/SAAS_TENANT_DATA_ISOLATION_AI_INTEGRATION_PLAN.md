# DeerFlow 接入 SaaS 租户数据隔离规划

**日期**: 2026-06-15  
**适用场景**: 将 DeerFlow 作为 SaaS 平台 AI Agent Gateway，接入租户工作台前端 AI Chat 组件，并支持按租户隔离的智能问数。  
**核心目标**: 用户在 SaaS 租户工作台登录后，AI 问数只能访问该用户所属租户、已授权数据源、已授权业务表范围内的数据。

## 1. 当前 SaaS 租户链路摘要

以租户“纳泽演示”为例：

- 用户记录位于 `carbon_client_user.admin_user`。
- 用户所属租户字段为 `belong_tenant_code = 20251231184555_6`。
- 该租户业务数据源可映射到数据库 `carbon_client_efficiency_20251231184555_6`。
- 数据源连接信息由现有 SaaS 系统在租户开通时写入 `conf_database`，包括 `code`、`url`、`userName`、`password`、`driverClass` 等。

现有业务系统的租户数据源切换流程是：

1. 租户用户登录租户工作台。
2. `client-user` 登录逻辑从用户表读取 `belongTenantId`、`belongTenantCode`、`tenantName` 等信息。
3. 登录成功后，租户上下文进入两处：
   - JWT 内的 `UserVo`
   - Redis 登录态 `LoginInfoVm{tenantId, tenantCode}`
4. 后续请求进入 SaaS Gateway。
5. SaaS Gateway 校验 `Authorization` token，优先从 Redis 登录态解析真实 `tenantId`、`tenantCode`。
6. SaaS Gateway 清理外部传入的伪造租户头，例如 `internal_token`、`x-tenant-id`、`x-tenant-code`、`x-system-code`。
7. SaaS Gateway 重新写入可信请求头：
   - `internal_token`
   - `x-tenant-id`
   - `x-tenant-code`
   - `x-system-code`
8. 下游微服务通过 `TenantFilter` 读取 `x-tenant-code` 和 `x-system-code`。
9. 根据服务名和 `tenantCode` 生成 `databaseCode`，例如 `carbon_client_efficiency_20251231184555_6`。
10. 根据 `conf_database.code` 查找并切换动态数据源。
11. 业务 Mapper/Service 在租户库中查询数据。

这条链路的关键安全点是：**下游服务不信任前端直接传入的租户头，只信任 SaaS Gateway 根据登录态重写后的租户头。**

## 2. DeerFlow 当前状态

当前 DeerFlow 已具备以下 AI Gateway 能力：

- 会话与运行：
  - `POST /api/threads`
  - `POST /api/threads/{thread_id}/runs/stream`
  - `POST /api/runs/stream`
  - `POST /api/runs/wait`
- SSE 流式输出，兼容 LangGraph SDK。
- 用户级 thread/run 归属隔离。
- `mysql-query` subagent。
- SQL 工具：
  - `sql_show_databases`
  - `sql_list_tables`
  - `sql_schema`
  - `sql_query`
  - `sql_query_checker`

当前 MySQL 问数的主要问题：

- `sql_tools.py` 直接读取全局环境变量：
  - `MYSQL_HOST`
  - `MYSQL_PORT`
  - `MYSQL_USER`
  - `MYSQL_PASSWORD`
  - `MYSQL_DATABASE`
- 这适合单租户或本地开发，不适合生产 SaaS 多租户。
- Agent 当前没有 SaaS 的 `tenantId`、`tenantCode`、`systemCode`、`dataSourceCode` 等可信业务上下文。
- SQL 工具无法根据 `belongTenantCode` 自动解析 `conf_database` 中对应的数据源。
- SQL 工具无法阻止跨租户库名访问，例如误查其他 `carbon_client_efficiency_xxx` 库。

## 3. 推荐整体架构

生产环境建议保留 SaaS Gateway 作为可信身份边界，DeerFlow 不直接暴露给浏览器。

```text
SaaS Frontend AI Chat
  -> SaaS Gateway
    -> DeerFlow Gateway
      -> Tenant-aware SQL Resolver
        -> conf_database
          -> tenant MySQL database
```

职责划分：

| 层级 | 职责 |
| --- | --- |
| SaaS Frontend | 展示 AI Chat，提交自然语言问题，展示流式答案、表格、图表、SQL 解释 |
| SaaS Gateway | 校验登录态，解析真实租户，清理伪造头，判断 AI 能力权限，转发可信上下文给 DeerFlow |
| DeerFlow Gateway | 管理 AI 会话、运行、流式事件、thread/run 隔离、调用 Agent |
| DeerFlow SQL Resolver | 根据可信租户上下文解析 `conf_database`，生成受限 MySQL 连接 |
| MySQL SQL Tools | 只执行授权范围内的只读 SQL |

## 4. 请求链路设计

### 4.1 前端到 SaaS Gateway

前端仍然只调用 SaaS 自己的 AI 接口，例如：

```http
POST /api/ai/chat/stream
Authorization: Bearer <saas-token>
Content-Type: application/json
```

请求体可以包含：

```json
{
  "thread_id": "optional-thread-id",
  "message": "查询纳泽演示本月综合能耗情况",
  "ai_mode": "data_analyst",
  "system_code": "efficiency"
}
```

注意：

- 前端可以传 `system_code` 作为用户当前页面或业务模块提示。
- 前端不应传可信 `tenantCode`。
- 即使前端传了 `tenantCode`，SaaS Gateway 也必须忽略或覆盖。

### 4.2 SaaS Gateway 到 DeerFlow Gateway

SaaS Gateway 完成以下动作：

1. 校验 `Authorization`。
2. 从 Redis 登录态读取真实 `tenantId`、`tenantCode`、`tenantName`、用户 ID。
3. 从权限系统判断该用户是否允许使用 AI 问数。
4. 根据当前页面或业务模块确定 `systemCode`，例如 `efficiency`。
5. 生成 DeerFlow 内部请求。

推荐调用 DeerFlow：

```http
POST /api/threads/{thread_id}/runs/stream
X-DeerFlow-Internal-Token: <deerflow-internal-token>
X-DeerFlow-Owner-User-Id: <saas-user-id>
X-SaaS-Tenant-Id: <tenant-id>
X-SaaS-Tenant-Code: 20251231184555_6
X-SaaS-Tenant-Name: 纳泽演示
X-SaaS-System-Code: efficiency
Content-Type: application/json
```

DeerFlow 请求体：

```json
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "type": "human",
        "content": [
          {
            "type": "text",
            "text": "查询本月综合能耗情况"
          }
        ]
      }
    ]
  },
  "context": {
    "mode": "ultra",
    "subagent_enabled": true,
    "agent_name": "saas-data-analyst"
  },
  "metadata": {
    "source": "saas-workbench",
    "ai_component": "tenant-chat"
  },
  "stream_subgraphs": true,
  "stream_resumable": true
}
```

关键要求：

- `tenant_id`、`tenant_code`、`tenant_name`、`system_code` 必须来自 SaaS Gateway 的可信 header。
- 不建议让浏览器直接调用 DeerFlow。
- 不建议把数据库连接、密码、完整 JDBC URL 放入 `context` 或 prompt。

## 5. DeerFlow 需要新增的可信租户上下文

### 5.1 新增内部请求头

在 `backend/app/gateway/internal_auth.py` 中扩展内部可信请求头常量：

```python
SAAS_TENANT_ID_HEADER_NAME = "X-SaaS-Tenant-Id"
SAAS_TENANT_CODE_HEADER_NAME = "X-SaaS-Tenant-Code"
SAAS_TENANT_NAME_HEADER_NAME = "X-SaaS-Tenant-Name"
SAAS_SYSTEM_CODE_HEADER_NAME = "X-SaaS-System-Code"
```

建议新增方法：

```python
def get_trusted_saas_context(request) -> dict[str, str]:
    ...
```

该方法只在以下条件成立时返回租户上下文：

- `request.state.user.system_role == "internal"`
- `X-DeerFlow-Internal-Token` 已由 DeerFlow AuthMiddleware 校验通过
- header 中的 `tenant_id`、`tenant_code`、`system_code` 通过格式校验

普通浏览器请求即使带了 `X-SaaS-Tenant-Code`，也应忽略。

### 5.2 注入 run context

在 `backend/app/gateway/services.py` 的 `start_run()` 中：

1. 读取 `get_trusted_internal_owner_user_id(request)`，当前已有。
2. 新增读取 `get_trusted_saas_context(request)`。
3. 将可信 SaaS 上下文写入 `config["context"]`，例如：

```python
runtime_context["saas_user_id"] = owner_user_id
runtime_context["tenant_id"] = tenant_id
runtime_context["tenant_code"] = tenant_code
runtime_context["tenant_name"] = tenant_name
runtime_context["system_code"] = system_code
```

注意：

- 这些字段不要从 `body.context` 直接信任。
- 可以允许 `body.context["agent_name"]`、`mode`、`model_name` 等 AI 行为参数。
- 租户身份字段必须由可信 header 或 DeerFlow 自己的认证结果生成。

### 5.3 建议新增 Tenant Context 工具模块

新增模块：

```text
backend/packages/harness/deerflow/runtime/tenant_context.py
```

职责：

- 从 `ToolRuntime.context` 中解析租户上下文。
- 为 SQL tool 提供统一读取方式。
- 在缺失租户上下文时返回清晰错误。

建议接口：

```python
@dataclass(frozen=True)
class TenantContext:
    user_id: str
    tenant_id: str
    tenant_code: str
    tenant_name: str | None
    system_code: str

def resolve_runtime_tenant_context(runtime: object | None) -> TenantContext:
    ...
```

## 6. 数据源解析设计

### 6.1 新增 DataSourceResolver

新增模块：

```text
backend/packages/harness/deerflow/tools/builtins/tenant_datasource.py
```

核心职责：

1. 根据 `tenant_code` 和 `system_code` 生成候选数据源编码。
2. 查询 `conf_database` 获取连接信息。
3. 校验数据源属于当前租户。
4. 返回 SQL 工具可使用的 MySQL 连接配置。

建议接口：

```python
@dataclass(frozen=True)
class TenantDataSource:
    code: str
    host: str
    port: int
    database: str
    username: str
    password: str
    driver_class: str
    allowed_databases: tuple[str, ...]

def resolve_tenant_datasource(ctx: TenantContext) -> TenantDataSource:
    ...
```

### 6.2 数据源编码规则

从现有 SaaS 文档看，动态数据源编码主要有两种形态：

```text
serviceName + "_" + tenantCode
carbon_client_{projectCode}_{tenantCode}
```

对于 DeerFlow 智能问数，建议先支持显式映射规则：

| `system_code` | 目标数据库 code 示例 | 说明 |
| --- | --- | --- |
| `efficiency` | `carbon_client_efficiency_20251231184555_6` | 能耗/双碳业务库 |
| `user` | `carbon_client_user` 或 default | 用户、租户、权限基础库 |

最小可行规则：

```python
database_code = f"carbon_client_{system_code}_{tenant_code}"
```

以“纳泽演示”为例：

```text
tenant_code = 20251231184555_6
system_code = efficiency
database_code = carbon_client_efficiency_20251231184555_6
```

随后用该 `database_code` 查询 `conf_database.code`。

### 6.3 `conf_database` 查询方式

推荐两种实现方式，按落地难度排序：

#### 方案 A：DeerFlow 只连接配置库

DeerFlow `.env` 只保存配置库只读连接：

```bash
SAAS_CONFIG_DB_HOST=...
SAAS_CONFIG_DB_PORT=3306
SAAS_CONFIG_DB_USER=readonly_user
SAAS_CONFIG_DB_PASSWORD=...
SAAS_CONFIG_DB_DATABASE=carbon_client_user
```

DataSourceResolver 查询：

```sql
SELECT code, url, userName, password, driverClass
FROM conf_database
WHERE code = :database_code
LIMIT 1;
```

优点：

- DeerFlow 自己完成数据源解析。
- SaaS Gateway 只传可信租户上下文。
- DeerFlow 侧审计完整。

缺点：

- DeerFlow 需要知道 `conf_database` 表结构和 JDBC URL 解析规则。
- DeerFlow 需要具备解密 `conf_database.password` 的能力，如果该字段加密存储。

#### 方案 B：SaaS Gateway 解析数据源，DeerFlow 只拿 data_source_ref

SaaS Gateway 查询 `conf_database`，得到数据源后，在一个内部 DataSource Registry 中登记临时引用：

```text
data_source_ref = dsref_abc123
ttl = 10 minutes
```

DeerFlow 只收到：

```http
X-SaaS-Data-Source-Ref: dsref_abc123
```

SQL Resolver 用内部服务接口换取连接，或通过共享安全存储读取。

优点：

- DeerFlow 不直接依赖 SaaS 配置库结构。
- 数据源解密逻辑留在原 SaaS 系统。

缺点：

- 需要新增 DataSource Registry 或内部接口。
- 调用链更长。

建议当前项目优先采用 **方案 A**，因为现有问数能力已经在 DeerFlow 内部，改造闭环更短。后续如果数据源加密、权限模型复杂，再演进到方案 B。

## 7. SQL 工具改造

### 7.1 从全局 env 改为运行时租户解析

当前：

```python
def _get_mysql_connection_string(database: Optional[str] = None) -> str:
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    db = database or os.getenv("MYSQL_DATABASE", "")
```

目标：

```python
def _get_mysql_connection_string(
    runtime: object | None = None,
    database: Optional[str] = None,
) -> str:
    ctx = resolve_runtime_tenant_context(runtime)
    ds = resolve_tenant_datasource(ctx)
    db = database or ds.database
    ensure_database_allowed(ds, db)
    return build_mysql_uri(ds, db)
```

### 7.2 LangChain tool 获取 runtime

当前 SQL 工具函数签名是：

```python
def sql_query(query: str) -> str:
    ...
```

需要确认当前 LangGraph/LangChain 工具运行时注入方式。建议目标形态：

```python
def sql_query(query: str, runtime: ToolRuntime | None = None) -> str:
    ...
```

如果当前版本不自动注入 `ToolRuntime`，可采用 ContextVar 保存本次 run 的租户上下文，或在工具封装层做 wrapper。优先建议使用已有的 `runtime.context` 方式，因为项目中 `resolve_runtime_user_id(runtime)` 已经采用类似模式。

### 7.3 数据库范围限制

SQL 执行前必须做库名约束：

- 默认库只能是 `carbon_client_efficiency_{tenant_code}`。
- 如需访问基础库 `carbon_client_user`，必须明确允许，并限制表范围。
- 禁止访问其他 `carbon_client_efficiency_*`。
- 禁止访问系统库：
  - `mysql`
  - `information_schema`
  - `performance_schema`
  - `sys`

以“纳泽演示”为例，允许：

```text
carbon_client_efficiency_20251231184555_6
carbon_client_user.admin_user
carbon_client_user.admin_tenant
```

禁止：

```text
carbon_client_efficiency_其他tenantCode
carbon_client_order_其他tenantCode
mysql
information_schema
```

### 7.4 SQL 只读限制

继续保留并加强当前限制：

- 禁止：
  - `DROP`
  - `DELETE`
  - `TRUNCATE`
  - `ALTER`
  - `CREATE`
  - `GRANT`
  - `REVOKE`
  - `EXECUTE`
  - `CALL`
  - `UPDATE`
  - `INSERT`
  - `REPLACE`
- 生产环境不建议保留 `MYSQL_ALLOW_WRITE=true`。
- 对无 `LIMIT` 的 `SELECT` 自动追加 `LIMIT 100`。
- 建议增加最大返回行数和最大执行时间。

### 7.5 SQL 表名解析

为了防止 SQL 中绕过默认库访问其他库，执行前需要解析 SQL 中引用的库表：

```sql
SELECT *
FROM carbon_client_efficiency_20251231184555_6.iot_project
JOIN carbon_client_user.admin_user ON ...
```

需要提取：

```text
carbon_client_efficiency_20251231184555_6.iot_project
carbon_client_user.admin_user
```

然后逐一校验：

- database 是否在 `allowed_databases`
- table 是否在 `allowed_tables`
- 如未显式写库名，则按租户默认库处理

最小实现可以先用 SQL 解析库，例如 `sqlglot`；不建议长期依赖正则解析复杂 SQL。

## 8. Agent 和 Skill 改造

### 8.1 新增 SaaS 数据分析 Agent

建议新增自定义 agent：

```text
agents/saas-data-analyst/
  config.yaml
  SOUL.md
```

定位：

- 面向租户工作台智能问数。
- 默认使用当前登录租户上下文。
- 不允许主动查询其他租户。
- 不向用户暴露数据库密码、连接串、内部 token。
- 回答中可以展示查询 SQL，但必须脱敏和只展示业务相关部分。

### 8.2 mysql-query subagent 约束

当前 `mysql-query` subagent 已经只允许 SQL 工具：

```python
tools=[
    "sql_show_databases",
    "sql_list_tables",
    "sql_schema",
    "sql_query",
    "sql_query_checker",
]
```

后续建议：

- 保留 `disallowed_tools=["task", "ask_clarification", "present_files"]`。
- 不给 `bash`、`read_file`、host filesystem 工具。
- system prompt 明确：
  - “你只能查询当前租户数据源”
  - “当前租户由系统上下文提供，不可由用户输入覆盖”
  - “如果用户要求查询其他租户，拒绝”

### 8.3 Skill 文档更新

`skills/public/mysql-query/SKILL.md` 需要从“通过 `.env` 配置 MySQL”更新为“两种模式”：

1. 本地开发模式：
   - 使用 `MYSQL_HOST`、`MYSQL_DATABASE`
2. SaaS 租户模式：
   - 使用 `runtime.context.tenant_code`
   - 使用 `runtime.context.system_code`
   - 通过 `conf_database` 解析数据源

## 9. API 设计建议

### 9.1 SaaS Gateway 对前端 API

```http
POST /api/ai/tenant-chat/stream
Authorization: Bearer <saas-token>
```

请求：

```json
{
  "thread_id": "optional",
  "message": "纳泽演示本月 PA 用电量是多少？",
  "system_code": "efficiency",
  "page_context": {
    "module": "energy-dashboard",
    "project_id": "optional",
    "site_id": "optional"
  }
}
```

响应：

- SSE 透传 DeerFlow 事件。
- 或由 SaaS Gateway 转换成前端 AI 组件自己的事件格式。

### 9.2 DeerFlow 内部 API

沿用：

```http
POST /api/threads/{thread_id}/runs/stream
```

使用内部可信 header 承载 SaaS 租户上下文。

### 9.3 可选：结构化问数 API

后续可以增加：

```http
POST /api/ai/query
```

返回结构化结果：

```json
{
  "answer": "本月 PA 用电量为 ...",
  "sql": "SELECT ...",
  "columns": ["project_name", "month_pa_total"],
  "rows": [
    ["纳泽演示项目", 12345.67]
  ],
  "chart": {
    "type": "bar",
    "x": "project_name",
    "y": "month_pa_total"
  },
  "warnings": []
}
```

第一阶段可以先用 Chat SSE，第二阶段再沉淀结构化问数 API。

## 10. 审计与安全

智能问数必须记录审计日志：

| 字段 | 说明 |
| --- | --- |
| `run_id` | DeerFlow run ID |
| `thread_id` | DeerFlow thread ID |
| `saas_user_id` | SaaS 用户 ID |
| `tenant_id` | 租户 ID |
| `tenant_code` | 租户编码 |
| `tenant_name` | 租户名称 |
| `system_code` | 业务系统编码 |
| `datasource_code` | 实际命中的 `conf_database.code` |
| `question` | 用户原始问题 |
| `sql` | 最终执行 SQL |
| `tables` | 命中的库表 |
| `row_count` | 返回行数 |
| `duration_ms` | 执行耗时 |
| `status` | success / blocked / error |
| `error` | 错误信息 |

敏感信息处理：

- 不记录数据库密码。
- 不向 LLM prompt 写入数据库密码。
- 不向前端返回 JDBC URL。
- 日志过滤 `password`、`Authorization`、`X-DeerFlow-Internal-Token`。

## 11. 推荐实施阶段

### 阶段 1：打通 SaaS 到 DeerFlow 的可信调用

目标：

- SaaS Gateway 能代表当前登录用户调用 DeerFlow。
- DeerFlow thread/run 归属到 SaaS 用户 ID。
- 前端 AI Chat 能流式显示 DeerFlow 回答。

改造点：

- 在现有 SaaS Gateway 新增 `/api/ai/tenant-chat/stream`，作为 AI Chat 组件的统一入口；这里不是新增独立 BFF 服务。
- SaaS Gateway 调 DeerFlow 时带：
  - `X-DeerFlow-Internal-Token`
  - `X-DeerFlow-Owner-User-Id`
  - `X-SaaS-Tenant-Id`
  - `X-SaaS-Tenant-Code`
  - `X-SaaS-Tenant-Name`
  - `X-SaaS-System-Code`
- DeerFlow `internal_auth.py` 增加 SaaS header 解析。
- DeerFlow `services.py` 将可信 SaaS context 注入 run context。

### 阶段 2：租户数据源解析

目标：

- DeerFlow 能根据 `tenant_code + system_code` 解析到 `conf_database.code`。
- 以“纳泽演示”为例，解析到 `carbon_client_efficiency_20251231184555_6`。

改造点：

- 新增 `tenant_context.py`。
- 新增 `tenant_datasource.py`。
- DeerFlow `.env` 新增配置库连接：
  - `SAAS_CONFIG_DB_HOST`
  - `SAAS_CONFIG_DB_PORT`
  - `SAAS_CONFIG_DB_USER`
  - `SAAS_CONFIG_DB_PASSWORD`
  - `SAAS_CONFIG_DB_DATABASE`
- 实现 `resolve_tenant_datasource(ctx)`。

### 阶段 3：SQL 工具租户隔离

目标：

- SQL 工具不再默认读全局 `MYSQL_DATABASE`。
- SQL 工具按当前 run 的租户上下文连接租户库。
- 禁止跨租户库访问。

改造点：

- 改造 `_get_mysql_connection_string()`。
- 改造 `_get_default_database()`。
- `sql_show_databases()` 只返回当前租户允许的数据源，或在 SaaS 模式下禁用全库发现。
- `sql_list_tables()` 默认列出当前租户库表。
- `sql_schema()` 校验库表范围。
- `sql_query()` 执行前校验 SQL 只读和库表授权。
- `sql_query_checker()` 使用当前租户库做 `EXPLAIN`。

## 12. 最小可行闭环

针对“纳泽演示”的最小可行闭环：

1. 用户登录 SaaS 租户工作台。
2. SaaS Gateway 从 Redis 登录态解析：
   - `tenantCode = 20251231184555_6`
   - `tenantName = 纳泽演示`
3. 用户在 AI Chat 中提问：
   - “本月 PA 用电量是多少？”
4. SaaS Gateway 调 DeerFlow，写入可信 header：
   - `X-SaaS-Tenant-Code: 20251231184555_6`
   - `X-SaaS-System-Code: efficiency`
5. DeerFlow 注入 run context：
   - `tenant_code = 20251231184555_6`
   - `system_code = efficiency`
6. SQL Resolver 生成：
   - `database_code = carbon_client_efficiency_20251231184555_6`
7. SQL Resolver 查询 `conf_database` 获取连接。
8. `sql_schema()` 读取当前租户库 `iot_project`、`iot_report_energy_day` 等表结构。
9. `sql_query()` 执行受限 SQL：

```sql
SELECT
  SUM(report_value) AS month_pa_total
FROM carbon_client_efficiency_20251231184555_6.iot_report_energy_day
WHERE attribute_identifier = 'Pa_total'
  AND report_type = 1
  AND create_time >= CONCAT(DATE_FORMAT(CURDATE(), '%Y-%m-01'), ' 00:00:00')
  AND create_time < CONCAT(DATE_FORMAT(CURDATE() + INTERVAL 1 MONTH, '%Y-%m-01'), ' 00:00:00')
LIMIT 100;
```

10. DeerFlow 流式返回回答。
11. 审计日志记录用户、租户、数据源、SQL、耗时和结果行数。

## 13. 关键结论

- SaaS Gateway 必须继续作为可信身份和租户边界。
- DeerFlow 不应直接信任前端传入的 `tenantCode`。
- DeerFlow SQL 工具应从“全局 `.env` MySQL 连接”改造成“基于可信 run context 的租户数据源解析”。
- `belongTenantCode` 是 DeerFlow 智能问数租户隔离的核心输入。
- `conf_database.code` 是 DeerFlow 解析真实租户库连接的核心落点。
- 生产智能问数必须做 SQL 只读、库表白名单、审计日志和敏感信息脱敏。
