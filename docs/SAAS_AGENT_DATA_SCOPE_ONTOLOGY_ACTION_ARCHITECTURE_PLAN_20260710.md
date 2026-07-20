# SaaS Agent 数据权限、Ontology 与 Action 平台规划

- **日期**: 2026-07-10
- **状态**: 第 1-8.8 节已实现并通过本轮验收；第 9 节及之后明确未实现
- **适用范围**: DeerFlow SaaS 智能问数、后续业务语义查询、受控系统写回、轨迹评测与演化发布
- **前置基线**: 已完成可信租户上下文、租户数据源解析、SQL-only `mysql-query` / `mysql-validator` 专线和 `/sql-cross-validate/*` 接口

**实现说明**: 代码落地、部署变量、内部 API 与运维契约见
[`SAAS_SEMANTIC_QUERY_ACTION_IMPLEMENTATION.md`](SAAS_SEMANTIC_QUERY_ACTION_IMPLEMENTATION.md)。
本轮保留第 9 节作为后续规划，不把现有 audit/状态轨迹误报为评测、评分归因或受控演化能力。

## 1. 执行摘要

本规划确定两阶段路线：

- **A 阶段：数据访问安全底座**。在现有租户库隔离之上增加用户、角色、场地、项目粒度的数据范围，所有 SQL 经过不可绕过的 scope 校验和执行器。A 是立即交付项，也是 B 阶段永久保留的最后安全边界。
- **B 阶段：业务语义与 Action 平台**。建立独立的 Ontology / Semantic Platform。DeerFlow 不再面向普通 SaaS 用户暴露任意 SQL，而是调用受控的 Semantic Query 和 Action API。查询通过语义查询管线，写回通过 Action 管线。

最终架构原则：

> DeerFlow 负责理解、规划、调用和解释；Semantic Platform 负责业务定义、权限判定、查询编译和 Action 编排；只有受控执行器或 Action Worker 可以接触数据源凭据和生产写权限。

A 与 B 不是替代关系：

```text
B：Agent 产品接口与业务能力
        ↓
A：不可绕过的数据访问安全内核
        ↓
租户数据库与业务系统
```

## 2. 当前基线与已知缺口

### 2.1 已完成能力

当前 SaaS 问数链路已经具备：

1. SaaS 用户通过 JWT 登录，SaaS Gateway 解析真实用户与租户。
2. SaaS Gateway 使用 `X-DeerFlow-Internal-Token` 调用 DeerFlow。
3. DeerFlow 只在内部调用身份成立时接收：
   - `tenant_id`
   - `tenant_code`
   - `tenant_name`
   - `system_code`
   - `saas_user_id`
4. `tenant_code + system_code` 生成 `carbon_client_{system_code}_{tenant_code}`。
5. DeerFlow 从 `conf_database` 解析真实数据源。
6. SaaS 问数使用 `/api/runs/sql-cross-validate/*` 或 threaded 对应接口。
7. 主查询固定使用 `mysql-query`，验证固定使用 `mysql-validator`。
8. 两个 SubAgent 只获得 SQL 工具，不获得 bash、文件、sandbox、workspace 或通用委派工具。
9. SaaS 模式只允许当前租户数据库，禁止数据库写入。

### 2.2 当前缺口

现有实现只做到**租户数据库级隔离**，没有做到同一租户库内的场地、项目和角色级隔离：

- `TenantContext` 没有 `role_codes`、`allowed_site_ids`、`allowed_project_ids` 或权限版本。
- `sql_query` 只做关键字、只读和数据库范围校验，没有行级 scope。
- SQL 表提取仍以正则为主，不能安全覆盖 CTE、子查询、UNION、复杂 JOIN 等场景。
- `sql_schema` 当前可能返回样例行，样例可能来自用户无权访问的场地。
- `sql_list_tables` 会暴露租户库内全部可用表，包括认证、密钥、配置和权限类敏感表。
- 同一个 thread 在权限变化后可能携带旧回答，形成历史数据泄露。
- 两个 SQL Agent 独立查询只能降低偶然错误，不能保证业务口径正确，也不能替代权限策略。
- 当前自由 SQL 模式不适合作为未来业务写回、稳定评测和自演化的长期接口。

现有库表清单包含 `iot_site`、`iot_project`、`iot_device`、`iot_user_project`、`iot_role_data_scope`、`iot_report_energy_day` 等候选业务和权限表，但仅凭表名不能确定关系和字段。正式 scope 映射必须以 DDL、外键、业务代码和 SaaS 权限服务为准。

## 3. 目标与非目标

### 3.1 目标

- 同一租户内，用户只能访问 SaaS 授权的场地、项目、对象和字段。
- 用户消息、请求 body 和模型输出不能扩大授权范围。
- Agent 不直接掌握生产写权限。
- 业务指标、对象、关系、动作和权限规则可版本化。
- 查询和写回都有稳定的结构化轨迹，可用于评测、评分归因和回放。
- 演化只能优化规划、语义映射和工具使用，不能绕过权限、审批与执行内核。
- A 阶段保持当前 SQL 专用接口兼容；B 阶段逐步迁移，不一次性切断已有能力。

### 3.2 非目标

- A 阶段不支持租户用户任意写 SQL。
- A 阶段不承诺自动安全改写租户库中所有表和所有复杂 SQL。
- B 阶段不把整个数据库 schema 原样包装成 Ontology。
- B 阶段不允许 Agent 自行创建、修改或发布生产权限策略与 Action 定义。
- 本规划不以模型 prompt 作为安全边界。

## 4. 核心架构决策

### ADR-001：B 是长期主架构，A 是永久安全底座

普通 SaaS 用户最终只使用 Semantic Query 和 Action，不直接使用 `sql_query`。所有语义查询编译出的 SQL 仍必须经过 A 的强制安全执行器。

### ADR-002：DeerFlow 与 Semantic Platform 是两个独立服务

独立服务表示不同进程、容器、网络身份、配置和凭据，不强制一开始部署在不同物理服务器。

- `deerflow-agent`：现有 Gateway、LangGraph、SubAgent、线程和回答生成。
- `semantic-platform`：Ontology、Metric、Policy、Semantic Query、Action 和审计。
- `action-worker`：属于 Semantic Platform 的执行平面，可以与其同仓库，但必须是独立进程；只有它持有生产写权限。

### ADR-003：查询与写回是两条管线

- **Semantic Query Pipeline**：只读、可重试、可缓存，输出结构化事实及 lineage。
- **Action Pipeline**：有副作用，必须包含权限复核、前置条件、幂等、审批、事务或 Saga、审计和结果状态。

所有数据访问经过统一 Policy Engine 和 Scoped Data Executor，但读取不包装成 Action，写入也不暴露为任意 SQL。

### ADR-004：角色不是最终数据过滤条件

`site_admin` 等角色只能作为策略输入。实际数据边界必须解析为稳定资源范围，例如 `allowed_site_ids`、`allowed_project_ids` 或受控 `scope_ref`。

### ADR-005：先鉴权，再检索和增强上下文

Ontology-Augmented Generation 只能获取当前用户已授权的对象、关系和事实。禁止先读取全量事实再依赖模型隐藏无权数据。

### ADR-006：默认拒绝

缺少授权上下文、scope 为空、表未分类、字段未分类、SQL 无法解析、Action 未注册或策略服务不可用时，生产 SaaS 请求全部 fail closed。

## 5. 目标服务拓扑

```text
SaaS Frontend
      |
      v
SaaS Gateway / IAM
  - JWT authentication
  - RBAC / ABAC
  - issue Authorization Context
      |
      v
DeerFlow Agent Service
  - question understanding
  - planning and tool selection
  - conversation / thread
  - answer synthesis
  - agent trajectory
      |
      | SemanticQuery / ActionProposal
      v
Semantic Platform API
  - Ontology Registry
  - Metric Registry
  - Policy Engine
  - Semantic Query Compiler
  - Scoped Data Executor
  - Action Registry / Orchestrator
  - semantic trace and audit
      |                         |
      | read                    | authorized command
      v                         v
Tenant read datasource       Action Worker
                                |
                                v
                       SaaS domain API / IoT API
                       or last-resort controlled SQL
```

### 5.1 所有权矩阵

| 能力 | SaaS Gateway/IAM | DeerFlow | Semantic Platform | Action Worker |
| --- | --- | --- | --- | --- |
| 用户认证 | Owner | Consumer | Verifier/Consumer | Consumer |
| 用户角色与资源授权 | Owner | 不自行推断 | Policy input | 执行前复核 |
| 对话和 Agent 规划 | 无 | Owner | 无 | 无 |
| Ontology / Metric 定义 | 无 | Consumer | Owner | Consumer |
| 查询编译 | 无 | 不负责 | Owner | 无 |
| SQL scope 强制 | 提供授权事实 | 不可绕过 | Owner，A 迁移后 | 无 |
| Action 定义与规则 | 可参与业务配置 | Consumer | Owner | Consumer |
| Action 提议 | 无 | Owner | 校验并持久化 | 无 |
| Action 批准 | 用户/SaaS审批系统 | 展示和发起 | 验证批准 | 不自行批准 |
| 生产写凭据 | 无 | 禁止 | API 侧原则上禁止 | Owner |
| Agent 轨迹 | 无 | Owner | 关联 ID | 关联 ID |
| 业务审计 | 可查询 | 只写关联信息 | Owner | 写执行结果 |

## 6. 可信 Authorization Context

### 6.1 传输契约

现有 `X-DeerFlow-Internal-Token` 继续用于证明调用方是 SaaS Gateway，但它不表达某个用户的授权范围。

新增短期签名的 `X-SaaS-Authorization-Context`，推荐使用 SaaS 私钥签发的 JWT/JWS，DeerFlow 和 Semantic Platform 使用公钥或 JWKS 独立验签。禁止只解码不验签。

建议 claims：

```json
{
  "iss": "saas-gateway",
  "aud": ["deerflow", "semantic-platform"],
  "sub": "saas-user-123",
  "tenant_id": "tenant-1",
  "tenant_code": "20251231184555_6",
  "system_code": "efficiency",
  "role_codes": ["site_admin"],
  "scope": {
    "mode": "resource_set",
    "site_ids": ["site-1", "site-2"],
    "project_ids": ["project-1"]
  },
  "permission_version": "42",
  "iat": 1783650000,
  "exp": 1783650300,
  "jti": "authz-uuid"
}
```

约束：

- token 有效期默认不超过 5 分钟。
- `aud` 必须包含当前服务。
- `tenant_code`、`system_code` 和资源 ID 使用严格格式及长度限制。
- `scope.mode` 只允许 `tenant_all`、`resource_set`、`scope_ref`、`none`。
- 资源 ID 数量超过网关 Header 限制时使用 `scope_ref`，由 Semantic Platform 调 SaaS 内部授权接口解析；禁止截断列表。
- DeerFlow 将原始 token 委托给 Semantic Platform，Semantic Platform 必须独立验签，不能信任 DeerFlow 传入的已解码 JSON。
- `scope_hash` 由服务端对租户、系统、角色、资源集合和 `permission_version` 的 canonical JSON 计算，不接受客户端直接指定。

### 6.2 运行时类型

在现有 `TenantContext` 基础上新增独立的 `AuthorizationContext`，避免把身份、数据源和授权混成一个对象：

```python
@dataclass(frozen=True)
class AuthorizationContext:
    principal_id: str
    tenant_id: str
    tenant_code: str
    system_code: str
    role_codes: tuple[str, ...]
    scope_mode: str
    allowed_site_ids: tuple[str, ...]
    allowed_project_ids: tuple[str, ...]
    scope_ref: str | None
    permission_version: str
    scope_hash: str
```

`TenantContext` 继续负责数据源解析；`AuthorizationContext` 负责数据与动作权限。二者必须来自同一已验签 token，并校验租户、系统一致。

## 7. A 阶段：场地级数据访问安全底座

### 7.1 A 阶段完成定义

A 完成后，任意 SaaS SQL 问数满足：

1. 没有可信 Authorization Context 时不建立租户数据库连接。
2. 用户无法通过自然语言、body context、数据库名、SQL、CTE 或子查询扩大 scope。
3. schema、table discovery 和 sample data 与 query 使用同一权限策略。
4. thread 权限变化时不能继续读取旧的高权限上下文。
5. `mysql-query` 和 `mysql-validator` 接收完全相同且不可修改的 scope。
6. 所有允许、拒绝和执行行为可审计。

### 7.2 A1：接入可信授权上下文

Gateway 改造：

- 验证 Internal-Token 后，再验签 `X-SaaS-Authorization-Context`。
- 将授权字段加入 protected context keys，剥离普通 body/config 中的同名字段。
- 仅把服务端解析结果写入 `config["context"]`，不写入可能长期持久化敏感 token 的 `configurable`。
- 原始签名 token 不写 checkpoint、日志和模型上下文。
- SQL 专用接口缺少 scope 时返回明确的 401/403，而不是退回本地 `MYSQL_*` 模式。
- 本地开发接口可以保留显式 local SQL mode，但必须与 SaaS route/profile 分离，不能自动 fallback。

### 7.3 A2：建立 SQL Scope Policy Registry

每张可查询表或安全视图必须明确分类：

```yaml
tables:
  iot_site:
    access: scoped
    scope_dimension: site
    scope_column: id

  iot_project:
    access: scoped
    scope_dimension: site
    scope_column: site_id

  iot_carbon_factor:
    access: reference

  iot_api_auth:
    access: forbidden
```

支持类型：

- `scoped`：必须按场地或项目过滤。
- `reference`：租户内公共字典或指标定义，可以不加资源过滤，但仍受字段 allowlist。
- `forbidden`：认证、密钥、配置、权限、审计、系统表等不可由问数 Agent 访问。
- `unclassified`：默认等同 `forbidden`。

第一批只覆盖真实高频问数需要的表。对间接关联到场地的事实表，优先提供带统一 `scope_site_id` 的安全视图；在业务关系未确认前禁止根据表名猜测 JOIN。

策略注册表需要版本号 `policy_version`，每次执行轨迹记录该版本。

### 7.4 A3：实现 Scoped SQL Guard / Executor

新增框架无关的安全执行内核，LangChain SQL tools 只做参数适配。使用 `sqlglot` 的 MySQL dialect 解析 AST，不再用正则承担主安全职责。

执行顺序固定为：

```text
解析单条语句
  -> 只允许 SELECT 或最终为 SELECT 的 WITH
  -> 拒绝 DDL / DML / CALL / SET / INTO OUTFILE 等节点
  -> 提取所有真实表、别名、CTE、子查询和 UNION 分支
  -> 校验数据库、表、字段 policy
  -> 为每个 scoped 数据源注入 scope predicate
  -> 参数绑定，不拼接用户资源 ID
  -> 设置 LIMIT、执行超时和最大扫描/返回限制
  -> 执行
  -> 结果字段脱敏和行数限制
  -> 写审计轨迹
```

强制规则：

- 只允许一条 SQL statement。
- parse 失败直接拒绝。
- 查询引用任何未分类表直接拒绝。
- scope 注入不能证明覆盖全部 scoped 表时直接拒绝。
- `resource_set` 为空时返回无权限，不执行 `IN ()` 或退化为全量。
- `tenant_all` 只能由签名授权声明，模型和用户不能请求升级。
- 所有 scope 值通过 bind parameters 或临时授权表传递。
- 禁止依赖 Agent 自己生成 `WHERE site_id = ...`；即使已有条件，执行器仍追加授权交集。
- `sql_query_checker` 和 `sql_query` 必须调用同一 guard，checker 不得验证一个 SQL、executor 执行另一个未校验 SQL。
- 生产 SaaS 数据库账号保持只读，数据库权限作为第二道防线。

### 7.5 A4：限制 schema 与 discovery

- SaaS 模式 `sample_rows_in_table_info=0`。
- `sql_schema` 只返回允许表和允许字段的 DDL/描述，不返回原始样例行。
- `sql_list_tables` 只返回 policy 中的 `scoped` 和 `reference` 表或安全视图。
- `sql_show_databases` 只返回当前授权数据源，或在 SaaS profile 中直接省略该工具。
- schema 输出不得包含 comment 中的密钥、连接串或内部 token。
- 敏感字段应支持 `hidden`、`masked`、`aggregate_only` 分类。

### 7.6 A5：thread 与 scope 绑定

thread 第一次 SaaS 问数时记录：

```text
principal_id
tenant_id
system_code
scope_hash
permission_version
```

后续 run 如果 scope identity 不一致：

- 默认拒绝复用并要求创建新 thread。
- 禁止仅因为新 scope 是旧 scope 的子集就继续使用历史，因为旧消息可能已包含更大范围数据。
- 权限提升同样创建新 thread，确保评测和审计边界清晰。
- stateless 接口不传 thread id 时继续自动创建新 thread。

### 7.7 A6：审计与轨迹

每次 SQL tool 调用记录：

```text
run_id / thread_id / tool_call_id
principal_id / tenant_id / system_code
scope_hash / permission_version
policy_version
normalized_sql_hash
referenced_tables / referenced_fields
scope_predicates_applied
decision: allow | deny
deny_reason
duration_ms / returned_rows / truncated
error_category
```

禁止记录：

- 数据库密码和完整连接串。
- 原始 Authorization Context token。
- 未脱敏结果全集。

如确需保存原始 SQL 用于评测，应进入受限审计存储，配置保留期和访问权限，不直接写普通应用日志。

### 7.8 A7：A 阶段实施批次

#### A-0：权限关系发现

- 导出核心表 DDL、索引和外键。
- 阅读 SaaS 现有角色/数据权限代码，确认场地、项目、用户的真实关系。
- 形成第一版 table/field scope policy，不以表名猜测。
- 建立包含两个场地、多个项目和不同角色的匿名化测试数据集。

#### A-1：授权上下文与 Gateway

- 实现签名 token 验证、protected context 和 SaaS profile fail-closed。
- 增加 token 过期、错误 audience、伪造字段和 scope 为空测试。

#### A-2：SQL Guard 与工具接入

- 引入 `sqlglot`。
- 实现 AST allowlist、scope 注入、参数绑定和统一 checker/executor。
- 改造 schema/list/show 工具。

#### A-3：thread、审计与灰度

- 绑定 `scope_hash`。
- 增加结构化 audit event。
- 先在测试环境启用 audit，对策略覆盖率进行检查；生产 SaaS route 上线时必须使用 enforce，不允许长期 audit-only。

### 7.9 A 阶段测试与验收

必须覆盖：

- 正常场地管理员只能查询被授权场地。
- 用户在 prompt 中声称自己是租户管理员不能升级权限。
- body/config/header 中伪造 scope 被拒绝或被可信值覆盖。
- 显式查询其他场地、其他租户库、系统库被拒绝。
- JOIN、CTE、嵌套子查询、UNION 每个分支都受到 scope。
- 使用别名、反引号、大小写、注释不能绕过。
- 未分类表、敏感表和敏感字段被拒绝。
- `sql_schema` 不泄露其他场地样例。
- checker 与 executor 使用相同重写结果。
- primary 和 validator 获得同一 `scope_hash`。
- 权限变更后复用旧 thread 被拒绝。
- token 过期、验签失败、Semantic/IAM 不可用时 fail closed。
- 日志、异常和 SSE event 不包含密码、连接串和 token。

A 阶段验收门槛：所有权限绕过测试必须 100% 通过；安全项不以平均分或模型概率验收。

## 8. B 阶段：Ontology / Semantic Platform

### 8.1 B 阶段目标

将生产 SaaS 问数从“Agent 生成任意 SQL”迁移为“Agent 生成受控业务语义请求”。A 的 SQL 安全执行器下沉到 Semantic Platform，成为查询编译器之后的执行边界。

### 8.2 B1：Ontology Registry

Ontology 至少表达：

- **Object Types**：例如 Site、Project、Device、Alarm、WorkOrder。
- **Properties**：业务名称、类型、单位、敏感级别、可筛选/可聚合属性。
- **Links**：对象关系及基数。
- **Metrics**：口径、粒度、时间语义、单位、允许维度、数据来源。
- **Actions**：目标对象、参数、前置条件、权限、审批和执行器。
- **Policies**：对象、字段、关系、指标和 Action 的访问规则。
- **Mappings / Lineage**：语义对象到表、字段、API 和转换逻辑的映射。
- **Versions**：每次发布的 ontology、metric、policy 和 action 版本。

第一版只建模高价值垂直切片，建议从 `Site -> Project -> Device` 及能耗/告警查询开始。对象关系必须经业务代码和 DDL 验证后确定。

### 8.3 B2：Ontology-Augmented Generation

新增授权感知的事实检索：

```text
用户问题
  -> 解析候选对象、指标和时间范围
  -> Policy Engine 计算可见对象
  -> 检索授权范围内的 schema、定义、关系与事实
  -> 返回结构化 context + lineage
  -> DeerFlow 规划或回答
```

OAG 返回的数据必须包含：

- `ontology_version`
- `object_type` / `object_id`
- `metric_id` / `metric_version`
- `source_refs`
- `as_of`
- `authorization_scope_hash`

OAG 不直接把全量数据库 schema 和样例数据放入模型上下文。

### 8.4 B3：Semantic Query Pipeline

DeerFlow 使用少量稳定工具，避免为每个指标创建一个工具：

```text
resolve_business_context
search_objects
get_object
query_metrics
explain_metric
```

`query_metrics` 请求示例：

```json
{
  "metrics": ["energy.consumption_kwh"],
  "dimensions": ["site"],
  "filters": [
    {"field": "time", "op": "gte", "value": "2026-07-01"},
    {"field": "time", "op": "lt", "value": "2026-08-01"}
  ],
  "order_by": [
    {"field": "energy.consumption_kwh", "direction": "desc"}
  ],
  "limit": 20
}
```

处理流程：

```text
validate semantic request
  -> resolve ontology and metric versions
  -> authorize objects, fields and dimensions
  -> compile deterministic query plan
  -> invoke Scoped Data Executor
  -> return typed result + lineage + warnings
```

Agent 不提交数据库名、表名、JOIN、JDBC URL、密码或 scope 条件。

### 8.5 B4：Action Registry 与 Action Pipeline

Action 拆为三个职责：

1. **Action 定义**在 Semantic Platform：业务名称、目标对象、参数、前置条件、权限、审批、幂等和执行器。
2. **Action 调用工具**在 DeerFlow：理解意图、收集参数、展示预览、请求确认和解释结果。
3. **Action 执行**在 Action Worker：重新鉴权、执行事务、写 outbox 和审计。

DeerFlow 工具：

```text
list_available_actions
propose_action
preview_action
execute_action
get_action_status
```

Action 定义示例：

```yaml
id: alarm.change_threshold
version: 1
target_type: Device
parameters:
  threshold:
    type: number
    minimum: 0
    maximum: 100
authorization:
  relation: target.site_id in principal.allowed_site_ids
preconditions:
  - target.status == active
approval:
  required_when: threshold > 90
executor:
  type: saas_domain_api
  operation: update_alarm_threshold
```

Action 状态机：

```text
PROPOSED
  -> VALIDATED
  -> PREVIEWED
  -> PENDING_APPROVAL | READY
  -> EXECUTING
  -> SUCCEEDED | FAILED | COMPENSATING | COMPENSATED
```

执行规则：

- `execute_action` 必须引用已持久化 proposal，不能直接提交任意执行参数。
- 执行前重新验证 token、scope、对象当前状态和 action version。
- 每次执行携带 `idempotency_key` 和 `expected_object_version`。
- 优先调用 SaaS 领域 API，复用其事务、校验、缓存和事件逻辑。
- 没有领域 API 时才允许受控 SQL handler；handler 是版本化代码，不接受 Agent 提供 SQL。
- 高风险 Action 必须通过外部审批或明确的人机确认 token。
- 只有 Action Worker 拥有生产写凭据；DeerFlow 和 Semantic API 不持有通用写账号。

### 8.6 B5：Semantic Platform API

初始内部 API：

```text
POST /v1/ontology/resolve
POST /v1/objects/search
GET  /v1/objects/{object_type}/{object_id}
POST /v1/queries
GET  /v1/metrics/{metric_id}
POST /v1/actions/proposals
POST /v1/actions/proposals/{proposal_id}/preview
POST /v1/actions/proposals/{proposal_id}/execute
GET  /v1/actions/executions/{execution_id}
```

所有请求必须包含：

- DeerFlow service authentication。
- 原始 SaaS Authorization Context。
- `run_id`、`thread_id`、`tool_call_id` 和新的 `semantic_trace_id`。
- 幂等请求需要 `Idempotency-Key`。

统一错误类别：

```text
AUTHENTICATION_FAILED
AUTHORIZATION_DENIED
SCOPE_CHANGED
ONTOLOGY_NOT_FOUND
ONTOLOGY_VERSION_CONFLICT
INVALID_SEMANTIC_QUERY
POLICY_UNAVAILABLE
QUERY_BUDGET_EXCEEDED
ACTION_PRECONDITION_FAILED
ACTION_APPROVAL_REQUIRED
ACTION_CONFLICT
EXECUTION_FAILED
```

### 8.7 B6：部署边界

建议初始部署：

```text
gateway                 # DeerFlow Gateway + agent runtime
semantic-api            # Ontology/query/policy/action orchestration
action-worker           # isolated write execution
semantic-metadata-db    # registry/version/proposal/audit metadata
action-command-queue    # durable command delivery
```

`semantic-api` 与 `action-worker` 可以在同一仓库维护，但使用不同服务账号。生产环境网络策略只允许 action-worker 访问写 API 或写数据源。

### 8.8 B7：从 SQL 专线迁移

迁移采用覆盖率驱动，不一次性替换：

1. 保留现有 `/sql-cross-validate/*` 作为 A 保护下的兼容入口。
2. 选择 Top 20 高频问数建立 ontology、metric 和 golden cases。
3. 对已覆盖问题优先路由 Semantic Query；未覆盖问题才允许 scoped SQL fallback。
4. shadow 模式并行执行 Semantic Query 和旧 SQL，比较结果，不重复展示给用户。
5. 语义覆盖率、正确率和权限测试达标后，普通 SaaS 角色关闭自由 SQL fallback。
6. 自由 SQL 仅保留给独立的管理员/数据工程师 break-glass 入口，使用单独权限、审计和短期授权。
7. `mysql-query` 逐步改为生成或验证 `SemanticQuery`，不再直接生成生产 SQL。
8. `mysql-validator` 改为验证指标、维度、时间口径、scope 和结果，不再简单独立生成第二条 SQL。

### 8.8.1 实施结果（2026-07-10）

- A 阶段已实现签名 Authorization Context、场地/项目 resource scope、SQL AST Guard、
  schema/discovery 限制、thread scope 绑定和结构化 SQL audit。
- B 阶段已实现独立 Semantic API、Ontology/OAG、受控对象/指标查询、十个 Semantic tools、
  `saas-query` 专用 run profile、SQL fallback/shadow/break-glass 控制以及独立 Action Worker。
- Action 已持久化 `PROPOSED -> VALIDATED -> PREVIEWED -> PENDING_APPROVAL/READY ->
  EXECUTING -> SUCCEEDED/FAILED/COMPENSATING/COMPENSATED` 状态轨迹；补偿仅允许 Ontology
  显式发布的 domain API，并支持 lease 恢复。
- 默认 Ontology 只发布已经从现有资料确认的 `Site`、`Project`、`Project.site`、
  `site.count`、`project.count` 和一个受审批 Site Action。Device/能耗/告警等 Top 20 内容需要
  后续取得真实 DDL、业务口径和权限关系后作为版本化配置发布，禁止按表名猜测。
- 现有 `/sql-cross-validate/*` 保留为 A 保护下的兼容/break-glass 路径；普通 SaaS 流量应迁移到
  `/saas-query/*`。
- 验收加固已覆盖 SQL discovery 审计与错误脱敏、MySQL 会话变量/optimizer hint 拒绝、
  SaaS JWT 禁止回退 Lead/custom profile、OAG metadata 权限过滤、Action tool 最小授权、
  Action result/status scope 隔离、domain API SSRF 防护以及本地/Compose Worker 凭据隔离。
- 第 9 节评测、评分归因和受控演化没有实现，现有 hash shadow 与 audit 只作为后续数据基础。

## 9. 轨迹、评测、评分归因与演化部署

### 9.1 统一轨迹

每次请求关联：

```text
run_id
thread_id
tool_call_id
semantic_trace_id
action_proposal_id
action_execution_id
```

关键事件：

```text
authorization_context_resolved
business_intent_resolved
ontology_context_retrieved
semantic_plan_created
policy_decision_recorded
query_compiled
query_executed
answer_synthesized
action_proposed
action_previewed
action_approved
action_executed
evaluation_recorded
```

每个事件记录对应的 model、prompt、skill、ontology、metric、policy、compiler 和 action version。

### 9.2 评测分层

评测不能只比较最终自然语言答案：

| 维度 | 评测内容 |
| --- | --- |
| Intent | 是否识别正确对象、指标、动作和时间范围 |
| Semantic grounding | 是否选择正确 ontology object / metric / relation |
| Authorization | 是否严格遵守 tenant/site/project/field/action scope |
| Query correctness | 结构化结果是否与 golden data 一致 |
| Business correctness | 单位、粒度、时区、缺失值和业务口径是否正确 |
| Answer quality | 是否忠实于结果，是否说明范围、时间和限制 |
| Action safety | 参数、前置条件、审批、幂等和副作用是否正确 |
| Efficiency | 延迟、模型调用数、查询扫描量和 token 成本 |

Authorization 和 Action safety 是硬门禁，失败即整例失败，不能被其他分数抵消。

### 9.3 评分归因

失败应归因到明确组件：

```text
identity/scope
intent parser
ontology retrieval
metric mapping
policy engine
query compiler
data freshness/source
answer synthesis
action precondition
action executor
```

禁止将所有错误统一归因给 LLM。

### 9.4 演化部署

允许自动生成候选改进：

- prompt 和 few-shot 示例。
- tool description 和路由规则。
- semantic mapping 候选。
- workflow / pipeline 编排。
- 评测用例候选。

禁止自动直接发布：

- 权限策略。
- Action 权限、审批和风险级别。
- SQL Guard / compiler 安全逻辑。
- 生产凭据和网络策略。
- 数据库 migration 和不可逆 Action。

发布流程固定为：

```text
失败轨迹聚类
  -> 生成候选变体
  -> 静态约束检查
  -> 离线 golden + adversarial eval
  -> shadow
  -> canary
  -> 人工或策略门禁批准
  -> version promotion
  -> 监控与一键回滚
```

## 10. 实施里程碑

| 里程碑 | 交付结果 | 退出条件 |
| --- | --- | --- |
| M0 关系发现 | 核心 DDL、权限关系、测试数据和 scope policy 草案 | 业务负责人确认真实场地/项目关系 |
| M1 A 授权上下文 | 签名 Authorization Context 接入 | 伪造、过期、缺失 scope 全部 fail closed |
| M2 A SQL 安全 | AST guard、table/field policy、schema 限制 | 权限绕过测试 100% 通过 |
| M3 A 生产灰度 | thread scope、审计、专线 enforce | SaaS 问数无跨场地泄露，审计完整 |
| M4 B 语义读取 MVP | Site/Project/Device + 首批指标 | Top 高频问题可走 Semantic Query |
| M5 B 查询迁移 | shadow 比对、覆盖率路由 | 普通角色主要流量不再走自由 SQL |
| M6 B Action MVP | 1-3 个低风险 Action | dry-run、审批、幂等、审计闭环 |
| M7 轨迹评测 | 分层评分和归因面板/报表 | 每次发布有可重复 eval 结论 |
| M8 演化发布 | candidate -> eval -> canary -> rollback | 只在受控边界内自动演化 |

## 11. Codex 后续开发约束

后续 Codex 按本规划开发时必须遵守：

1. 每个里程碑先读当前代码和相关 `AGENTS.md`，不得以本文中的旧路径替代代码事实。
2. 后端功能和修复先写失败测试，再实现；权限类测试必须包含正向和绕过场景。
3. A 阶段不能通过修改 prompt 代替代码级 scope enforcement。
4. 不得让 SaaS 专用问数重新经过 Lead Agent 或 `general-purpose`。
5. 不得把原始 Authorization Context、数据库密码或连接串写入 checkpoint、普通日志或模型上下文。
6. 不得将未知表自动标为可查询；策略必须显式发布并版本化。
7. B 阶段 Semantic Platform 必须独立验签和鉴权，不能信任 DeerFlow 声称的 scope。
8. Action 写回优先调用领域 API；新增直写 SQL handler 必须单独安全评审。
9. 每个公共 API、context type、event schema 和配置项都要同步文档与兼容性测试。
10. 每个阶段完成后更新本规划状态、相关 README/AGENTS 以及变更日志。

## 12. 最终验收标准

项目达到本规划目标时应满足：

- 普通 SaaS 用户无法通过任何输入或 Agent 路径访问未授权租户、场地、项目、对象和字段。
- DeerFlow 不持有生产通用写凭据，也不能绕过 Semantic Platform 执行 Action。
- 已语义化问题不再依赖模型生成任意 SQL。
- 所有查询能说明使用的业务指标、范围、时间和数据来源。
- 所有写回能说明谁、何时、对什么对象、基于哪个 Action 版本、为何执行及最终结果。
- 任意回答或 Action 失败可归因到身份、语义、权限、编译、数据、模型或执行组件。
- 模型、prompt、skill 和 pipeline 可以通过评测演化；权限内核和写回护栏只能通过受控发布变更。

## 13. 一句话架构结论

> 先用 A 建立不可绕过的场地级数据安全底座，再用独立 Semantic Platform 建立 Ontology、Semantic Query 和 Action；DeerFlow 只负责规划与协调，查询由 Scoped Data Executor 执行，写回只由隔离的 Action Worker 执行。
