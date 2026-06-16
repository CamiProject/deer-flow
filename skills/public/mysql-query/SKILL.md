---
name: mysql-query
description: Use this skill when the user wants to query MySQL databases for data analysis, reporting, or exploration. The skill delegates to a general-purpose subagent with SQL tools to handle database discovery, schema inspection, SQL generation, query validation, and error recovery. Supports complex queries including joins, aggregations, and cross-database queries using fully qualified table names. Requires MySQL connection configuration via environment variables.
---

# MySQL Query Skill

## Overview

This skill provides MySQL database querying capabilities by delegating to a **general-purpose subagent** with SQL tools:
- Finds databases by name pattern using lightweight discovery
- Generates syntactically correct SQL queries
- Validates queries before execution
- Supports cross-database queries using fully qualified table names
- Handles errors efficiently with one-attempt fix strategy

## Prerequisites

### Local `.env` Mode

When no trusted SaaS runtime context is present, SQL tools use the local MySQL connection from `.env`:

```bash
# Required: MySQL server connection
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password

# Required: Default database
MYSQL_DATABASE=your_database

# Optional: Enable write operations (caution!)
# MYSQL_ALLOW_WRITE=false
```

### SaaS Tenant Mode

When DeerFlow is called by the trusted SaaS Gateway, SQL tools do not use global `MYSQL_HOST` / `MYSQL_DATABASE` for tenant data. Instead:

- SaaS Gateway validates login state and sends trusted headers to DeerFlow.
- DeerFlow injects `runtime.context.tenant_code` and `runtime.context.system_code`.
- SQL tools resolve `carbon_client_{system_code}_{tenant_code}` from `conf_database`.
- Queries are restricted to the resolved tenant database.

Configure the SaaS config database connection in `.env`:

```bash
SAAS_CONFIG_DB_HOST=your-config-db-host
SAAS_CONFIG_DB_PORT=3306
SAAS_CONFIG_DB_USER=your-readonly-user
SAAS_CONFIG_DB_PASSWORD=your-readonly-password
SAAS_CONFIG_DB_DATABASE=your-config-database
```

Tenant context must come from trusted runtime context. Do not ask the user to provide or override tenant identifiers, datasource URLs, passwords, or internal tokens.

## Workflow

### Step 1: Understand User's Question

Identify what the user wants:
- **Database discovery**: "Find databases for tenant X"
- **Exploration**: "What tables are available in this database?"
- **Schema check**: "What columns does the users table have?"
- **Query**: "Find user activity from last month"
- **Cross-database**: "Compare orders from db1 and db2"

### Step 2: Delegate to General-Purpose Subagent

Use the `task` tool with `subagent_type="general-purpose"` and include SQL-specific guidance in the prompt:

```json
{
  "description": "查询用户活跃度",
  "prompt": "在 carbon_service_user 数据库中查询上个月活跃度最高的前10个用户。\n\n<sql_guidance>\n可用工具: sql_show_databases, sql_list_tables, sql_schema, sql_query, sql_query_checker\n\n高效查询路径 (3-4步完成):\n1. 确定数据库: 用户指定则直接用，否则用 sql_show_databases(pattern) 一次\n2. 探索结构: sql_list_tables + sql_schema 获取表和列信息\n3. 执行查询: sql_query 直接执行\n\n错误处理原则:\n- 遇到错误只修正一次，修正后仍失败则返回错误说明\n- 不要无限循环尝试不同数据库/表/列\n- 返回部分结果或错误说明即可\n</sql_guidance>",
  "subagent_type": "general-purpose"
}
```

### Step 3: Present Results

After receiving results:
- Present data as formatted tables
- Explain key findings and insights
- Suggest follow-up queries if relevant
- Offer to export results

## SQL Tools Available

The general-purpose subagent inherits all tools including these SQL tools:

| Tool | Description | When to Use |
|------|-------------|-------------|
| `sql_show_databases` | Find databases matching a name pattern | Unknown database name |
| `sql_list_tables` | List tables in a specific database | Unknown tables |
| `sql_schema` | Get schema and sample rows | Need column information |
| `sql_query` | Execute SQL query | Final execution step |
| `sql_query_checker` | Validate SQL syntax | Complex queries, before execution |

## Example Usage

### Find Databases

```json
{
  "description": "查找数据库",
  "prompt": "查找名称包含 carbon_client_efficiency 的数据库。\n\n使用 sql_show_databases 工具，一次调用即可。",
  "subagent_type": "general-purpose"
}
```

### List Tables

```json
{
  "description": "列出数据库表",
  "prompt": "列出 carbon_service_user 数据库中的所有表。\n\n使用 sql_list_tables(database_name='carbon_service_user')。",
  "subagent_type": "general-purpose"
}
```

### Get Schema

```json
{
  "description": "获取表结构",
  "prompt": "获取 carbon_service_user.users 表的结构和示例数据。\n\n使用 sql_schema(table_names='users')。",
  "subagent_type": "general-purpose"
}
```

### Simple Query

```json
{
  "description": "简单查询",
  "prompt": "查询 carbon_service_user.users 表的前10条记录。\n\n<sql_guidance>\n1. 先用 sql_schema('users') 确认列名\n2. 再用 sql_query 执行 SELECT ... FROM users LIMIT 10\n遇到错误只修正一次，不要循环。\n</sql_guidance>",
  "subagent_type": "general-purpose"
}
```

### Cross-Database Query

```json
{
  "description": "跨库关联查询",
  "prompt": "查询 carbon_service_user.users 和 carbon_service_order.orders，找出下单次数超过5次的用户。\n\n<sql_guidance>\n使用完全限定表名: db1.table1, db2.table2\n1. sql_schema 获取两表结构\n2. sql_query 执行 JOIN 查询\n遇到错误只修正一次。\n</sql_guidance>",
  "subagent_type": "general-purpose"
}
```

### Complex Query with Database Discovery

```json
{
  "description": "复杂查询",
  "prompt": "查询武汉双碳租户下汉口银行中山路支行本月的PA用电量。\n\n<sql_guidance>\n数据层级:\n- carbon_client_user.admin_tenant: 租户表\n- carbon_client_efficiency_xxx.iot_project: 项目表\n- carbon_client_efficiency_xxx.iot_report_energy_day: 能耗日报表\n\n高效路径:\n1. sql_query 查询 admin_tenant 找租户ID (WHERE name LIKE '%武汉双碳%')\n2. 根据租户ID确定 efficiency 数据库后缀\n3. sql_query 查询 iot_project 找项目ID (WHERE project_name LIKE '%汉口银行中山路%')\n4. sql_query 查询能耗数据 (attribute_identifier='Pa_total', 本月时间范围)\n\n错误处理: 每步只修正一次，失败则返回已找到的信息和错误说明。\n</sql_guidance>",
  "subagent_type": "general-purpose"
}
```

## Database to Business Data Hierarchy Mapping

| 数据库.表 | 业务层级 |
| :--- | :--- |
| `carbon_client_user.admin_tenant` | 租户层级 |
| `carbon_client_efficiency_xxxxxx.iot_project` | 项目层级 |
| `carbon_client_efficiency_xxxxxx.iot_site` | 场地 / 场站层级 |
| `carbon_client_efficiency_xxxxxx.iot_device` | 设备层级 |
| `carbon_client_efficiency_xxxxxx.iot_statistics_day` | 按日报表 |
| `carbon_client_efficiency_xxxxxx.iot_statistics_month` | 按月报表 |

## 某些场景下的人工完整查询参考案例

### 业务意义：按照项目的维度（项目=汉口银行中山路支行）查询 本日的 电表耗电量
SELECT
  SUM(report_value) AS today_pa_total,
  ed.project_id,
  prj.project_name
FROM carbon_client_efficiency_20260407163459_7.iot_report_energy_day ed
INNER JOIN carbon_client_efficiency_20260407163459_7.iot_project prj ON ed.project_id = prj.id  -- prj = project
WHERE
  ed.attribute_identifier = 'Pa_total'
  AND ed.create_time >= CONCAT(CURDATE(), ' 00:00:00')
  AND ed.create_time < CONCAT(CURDATE() + INTERVAL 1 DAY, ' 00:00:00')
  AND ed.project_id = '1988792523903102977'
  AND ed.report_type = 1
GROUP BY
  ed.project_id,
  prj.project_name

### 业务意义：按照场地的维度（场地=汉口银行）查询 一周内（7天内）的 电表耗电量
SELECT
  SUM(report_value) AS week_pa_total,
  ed.site_id,
  site.site_name
FROM
  carbon_client_efficiency_20260407163459_7.iot_report_energy_day ed
  INNER JOIN carbon_client_efficiency_20260407163459_7.iot_site site ON ed.site_id = site.id
WHERE
  ed.attribute_identifier = 'Pa_total'
  AND ed.create_time >= CONCAT(CURDATE() - INTERVAL 7 DAY, ' 00:00:00')  -- 7天前零点
  AND ed.create_time < CONCAT(CURDATE() + INTERVAL 1 DAY, ' 00:00:00')   -- 明天零点（包含今天全天）
  AND ed.site_id = '1998293825305702401'
  AND ed.report_type = 1
GROUP BY
  ed.site_id,
  site.site_name

### 业务意义：按照设备的维度（设备=汉口银行某台电表）查询 本月的 电表耗电量
SELECT
  SUM(report_value) AS month_pa_total,
  ed.device_id,
  device.`NAME` AS device_name,
  device.device_no
FROM
  carbon_client_efficiency_20260407163459_7.iot_report_energy_day ed
  INNER JOIN carbon_client_efficiency_20260407163459_7.iot_device device ON ed.device_id = device.`id`
WHERE
  ed.attribute_identifier = 'Pa_total'
  AND ed.create_time >= CONCAT(DATE_FORMAT(CURDATE(), '%Y-%m-01'), ' 00:00:00')  -- 本月1号零点
  AND ed.create_time < CONCAT(DATE_FORMAT(CURDATE() + INTERVAL 1 MONTH, '%Y-%m-01'), ' 00:00:00')  -- 下月1号零点
  AND device.device_no = 'hkyh202508160002'
  AND ed.report_type = 1
GROUP BY
  ed.device_id,
  device.`NAME`,
  device.device_no

## Safety Constraints

> [!WARNING]
> By default, the subagent operates in **read-only mode**:
> - Only SELECT, SHOW, DESCRIBE queries allowed
> - INSERT, UPDATE, DELETE, DROP, ALTER are blocked
> - Query results are automatically limited
> - Timeout: 5 minutes (300 seconds)

To enable write operations, set `MYSQL_ALLOW_WRITE=true` in `.env` (use with caution).

## Why General-Purpose Subagent?

Using `general-purpose` instead of a dedicated `mysql-query` subagent provides:

1. **Better termination behavior**: "Think step by step but act decisively" - stops when blocked
2. **Efficient error handling**: "If you encounter issues, explain them clearly" - no infinite retry loops
3. **All tools available**: Inherits SQL tools plus file/web tools for comprehensive tasks
4. **Proven behavior pattern**: Same design that works well for main Agent

The SQL-specific guidance is embedded in the prompt, giving the subagent clear instructions without needing a separate specialized agent configuration.

## Notes

- **Database discovery**: Use sql_show_databases("pattern") to find databases by name pattern
- **Cross-database**: Supports `database.table` fully qualified names
- The subagent inherits the model from the parent agent
- The subagent runs in an isolated context
- MySQL-specific functions (DATE_FORMAT, GROUP_CONCAT, IFNULL, etc.) are supported
