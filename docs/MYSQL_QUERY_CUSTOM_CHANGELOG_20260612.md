# MySQL Query 二开汇总变更说明

**汇总日期**: 2026-06-12  
**当前分支**: `custom-v2`  
**当前提交**: `f2c2880676b9c19e7477c313ad55244acef366a1`  
**基准来源**: DeerFlow 官方最新源码 + `deer-flow-SQL-v2` 二开改动迁移

## 说明

本文档汇总 2026-04-15、2026-04-24 两份历史变更文档中已经在当前 `custom-v2` 分支落地的改动，以及 2026-06-12 将这些二开改动迁移到最新 DeerFlow 源码时产生的变更。

本文以当前代码实现为准。历史文档中出现过但当前 `custom-v2` 没有实现的方案，会在“未落地或已替代的历史项”中单独说明，避免后续维护时误判。

## 2026-04-15: MySQL Query Subagent 基础能力

### 新增 SQL 工具模块

**文件**: `backend/packages/harness/deerflow/tools/builtins/sql_tools.py`

当前实现提供 5 个 MySQL 查询工具：

| 工具 | 作用 |
| --- | --- |
| `sql_show_databases` | 按名称模式查找数据库，排除 `mysql`、`information_schema`、`performance_schema`、`sys` 等系统库 |
| `sql_list_tables` | 列出指定数据库中的所有可用表 |
| `sql_schema` | 获取表结构和示例数据，支持 `database.table` 格式 |
| `sql_query` | 执行 SQL 查询，支持跨库 fully qualified table name |
| `sql_query_checker` | 执行 SQL 安全校验和 `EXPLAIN` 校验 |

### SQL 安全约束

- 默认只读，`UPDATE`、`INSERT`、`REPLACE` 需要显式设置 `MYSQL_ALLOW_WRITE=true`。
- 始终禁止高风险操作：`DROP`、`DELETE`、`TRUNCATE`、`ALTER`、`CREATE`、`GRANT`、`REVOKE`、`EXECUTE`、`CALL`。
- `SELECT` 查询如果没有显式 `LIMIT`，会自动追加默认 `LIMIT 100`。
- 对常见错误返回更可操作的提示：
  - Unknown column -> 建议使用 `sql_schema`
  - Table doesn't exist -> 建议使用 `sql_list_tables`
  - Unknown database -> 提示检查数据库名
  - Syntax error -> 提示检查 SQL 语法

### 新增 mysql-query Subagent 配置

**文件**: `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py`

新增内置 subagent：`mysql-query`。

主要配置：

- `name`: `mysql-query`
- `model`: `inherit`
- `max_turns`: `50`
- `timeout_seconds`: `300`
- 允许工具：
  - `sql_show_databases`
  - `sql_list_tables`
  - `sql_schema`
  - `sql_query`
  - `sql_query_checker`
- 禁用工具：
  - `task`
  - `ask_clarification`
  - `present_files`

该 subagent 面向 MySQL 数据查询、结构探索、跨库查询、统计分析等场景。

### 注册内置 Subagent

**文件**: `backend/packages/harness/deerflow/subagents/builtins/__init__.py`

当前已注册：

```python
from .mysql_query import MYSQL_QUERY_CONFIG

BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "mysql-query": MYSQL_QUERY_CONFIG,
}
```

### 注册 SQL 工具

**文件**: `backend/packages/harness/deerflow/tools/tools.py`

当前实现已将 `SQL_TOOLS` 注册进内置工具集合：

```python
from deerflow.tools.builtins.sql_tools import SQL_TOOLS

SQL_BUILTIN_TOOLS = SQL_TOOLS

if include_sql_tools:
    builtin_tools.extend(SQL_BUILTIN_TOOLS)
    logger.info(f"Including SQL tools ({len(SQL_BUILTIN_TOOLS)} tools)")
```

`get_available_tools()` 新增参数：

```python
include_sql_tools: bool = True
```

因此当前默认会加载 SQL 工具。

### 新增 Skill 文档

**文件**: `skills/public/mysql-query/SKILL.md`

该 skill 用于指导 Agent 处理 MySQL 查询任务，当前文档采用“把 SQL 指导写入 prompt，再委托给 `general-purpose` subagent”的使用方式。

当前文档覆盖：

- 数据库按模式发现：`sql_show_databases`
- 表探索：`sql_list_tables`
- Schema 获取：`sql_schema`
- 查询执行：`sql_query`
- 查询校验：`sql_query_checker`
- 跨库查询：使用 `db.table` 完全限定表名
- 错误处理策略：遇错只修正一次，避免无限循环
- 业务数据层级参考：
  - `carbon_client_user.admin_tenant`
  - `carbon_client_efficiency_xxxxxx.iot_project`
  - `carbon_client_efficiency_xxxxxx.iot_site`
  - `carbon_client_efficiency_xxxxxx.iot_device`
  - `carbon_client_efficiency_xxxxxx.iot_report_energy_day`

## 2026-04-16 至 2026-04-17: 依赖与环境配置修复

### 新增 Python 依赖

**文件**: `backend/packages/harness/pyproject.toml`

新增：

```toml
"langchain-community>=0.3.0",
"mysql-connector-python>=8.0.0",
```

原因：

- `langchain-community` 提供 `SQLDatabase`
- `mysql-connector-python` 支持 `mysql+mysqlconnector://` 连接字符串

### 新增环境变量示例

**文件**: `.env.example`

当前已加入：

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your-mysql-user
MYSQL_PASSWORD=your-mysql-password
MYSQL_DATABASE=your-database-name
```

当前代码还支持但 `.env.example` 未显式列出的变量：

```bash
MYSQL_ALLOW_WRITE=false
```

`MYSQL_ALLOW_WRITE` 默认为 `false`，只有设置为 `true` 时才允许 `UPDATE`、`INSERT`、`REPLACE`。

## 2026-04-24: 数据库发现与跨库查询能力

### 当前已落地能力

历史文档中“多数据库发现”和“跨库查询”的需求，在当前 `custom-v2` 中以轻量方案落地。

已实现：

- 通过 `sql_show_databases(pattern)` 按名称模式查找数据库。
- 自动排除系统库：
  - `mysql`
  - `information_schema`
  - `performance_schema`
  - `sys`
- `sql_list_tables(database_name)` 可指定目标数据库。
- `sql_schema(table_names)` 支持 `database.table`。
- `sql_query(query)` 支持跨库 SQL，例如：

```sql
SELECT *
FROM db1.users u
JOIN db2.orders o ON u.id = o.user_id
LIMIT 100;
```

### 当前查询推荐流程

1. 已知数据库名：直接调用 `sql_list_tables(database_name)`。
2. 不知道完整数据库名：先调用 `sql_show_databases(pattern)`。
3. 已知表名但不确定列：调用 `sql_schema(table_names)`。
4. 写 SQL 时跨库表使用 `database.table`。
5. 复杂 SQL 先用 `sql_query_checker(query)`。
6. 最后用 `sql_query(query)` 执行。

## 2026-04-28: 本地 Bash 工具启用

**文件**: `config.yaml`

当前本地配置：

```yaml
sandbox:
  allow_host_bash: true
```

作用：

- 允许本地 subagent/工具执行 host bash 命令。
- 主要用于本地可信开发环境，例如图表生成、脚本执行等场景。

注意：

- 该配置适合本机可信环境。
- 生产环境建议使用隔离沙箱方案，而不是直接开放 host bash。

## 2026-06-12: 迁移到 DeerFlow 最新源码

### 迁移目标

将 `deer-flow-SQL-v2` 中基于 2026-04-13 DeerFlow 源码的二开改动，迁移到 2026-06-12 的 DeerFlow 最新源码上。

最终长期维护分支：

```bash
custom-v2
```

官方源码跟踪分支：

```bash
main
```

### 迁移提交

当前提交：

```bash
f2c2880676b9c19e7477c313ad55244acef366a1
custom: apply deer-flow-SQL-v2 changes from 20260413 baseline
```

### 迁移中新增的主要文件

- `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py`
- `backend/packages/harness/deerflow/tools/builtins/sql_tools.py`
- `backend/tests/test_sql_tools.py`
- `docs/MYSQL_QUERY_AUTO_DISCOVERY_CHANGELOG_20260424.md`
- `docs/MYSQL_QUERY_SUBAGENT_CHANGELOG_20260415.md`
- `skills/public/mysql-query/SKILL.md`

### 迁移中修改的主要文件

- `.env.example`
- `backend/packages/harness/deerflow/subagents/builtins/__init__.py`
- `backend/packages/harness/deerflow/tools/tools.py`
- `backend/packages/harness/pyproject.toml`
- `backend/uv.lock`
- `config.example.yaml`
- `frontend/src/components/workspace/workspace-header.tsx`
- `frontend/src/core/i18n/locales/en-US.ts`
- `frontend/src/core/i18n/locales/zh-CN.ts`
- `scripts/check.py`

另外迁移中保留并适配了 DeerFlow 最新源码中的 MCP、tool_search、present file、Jina 等较新实现，没有用 4 月旧版本整体覆盖 6 月新代码。

## 当前实际能力总览

| 分类 | 当前状态 |
| --- | --- |
| MySQL SQL 工具 | 已实现 |
| `mysql-query` 内置 subagent | 已注册 |
| SQL 工具默认加载 | 已启用 |
| MySQL 连接环境变量 | 已支持 |
| 只读安全模式 | 默认启用 |
| 写操作开关 | 支持 `MYSQL_ALLOW_WRITE=true` |
| 自动追加 LIMIT | 已实现 |
| 按模式查找数据库 | 已实现 `sql_show_databases` |
| 指定数据库列表 | 已实现 `sql_list_tables(database_name)` |
| 跨库查询 | 支持 `database.table` |
| 智能自然语言表匹配 | 当前未实现 |
| 全库表元数据自动扫描 | 当前未实现 |

## 未落地或已替代的历史项

以下内容曾出现在 2026-04-24 历史文档中，但当前 `custom-v2` 代码没有实现，不能作为当前能力使用：

- `sql_discover_databases`
- `sql_find_relevant_tables`
- `_extract_keywords`
- `_expand_keywords`
- `_calculate_relevance_score`
- `_get_excluded_databases`
- 基于中文/英文关键词和同义词的自然语言表匹配
- 返回相关性得分的智能表排序
- `MYSQL_EXCLUDED_DBS` 环境变量配置

当前对应替代方案：

- 使用 `sql_show_databases(pattern)` 做轻量数据库发现。
- 使用 `sql_list_tables(database_name)` 和 `sql_schema(table_names)` 手动探索表结构。
- 跨库查询时直接使用 `database.table` 完全限定表名。

## 测试说明

当前仓库中存在 `backend/tests/test_sql_tools.py`，但该测试文件包含部分 2026-04-24 历史增强方案的测试用例，例如 `sql_discover_databases`、`sql_find_relevant_tables`、`_extract_keywords` 等。

由于当前 `custom-v2` 实际实现采用的是 `sql_show_databases` 轻量发现方案，这些测试与当前代码并不完全一致。后续需要二选一处理：

1. 以当前代码为准：重写 `test_sql_tools.py`，让测试覆盖当前 5 个工具。
2. 以 2026-04-24 增强方案为准：补齐智能发现和智能表匹配实现。

## 后续维护建议

长期建议保留两个核心分支：

- `main`: 跟踪 DeerFlow 官方最新源码。
- `custom-v2`: 保留并持续维护当前 MySQL 查询二开能力。

后续同步官方代码时推荐流程：

```powershell
cd D:\Project\VSCodeWorkspace\deer-flow
git checkout main
git pull origin main
git checkout custom-v2
git rebase main
```

遇到冲突时优先保留 DeerFlow 官方新架构，再把 MySQL 二开注册、依赖、工具和 skill 文档补回。

