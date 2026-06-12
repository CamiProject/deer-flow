# MySQL Query Subagent 多数据库自动发现改动说明

**日期**: 2026-04-24

## 改动概述

本次改动为 MySQL Query Subagent 添加了**多数据库自动发现**和**智能表匹配**能力。用户需要在 `.env` 中显式指定 `MYSQL_DATABASE` 作为默认数据库，但系统支持跨数据库查询（使用 `database.table` 完全限定名）。系统会自动发现所有可用数据库，并根据用户自然语言问题智能匹配相关表。同时修复了 Lead Agent system prompt 中遗漏 `mysql-query` subagent 描述的问题。

> **注意**: 由于 LangChain 的 `SQLDatabase.from_uri()` 不支持不带数据库名的连接字符串，`MYSQL_DATABASE` 必须配置，否则会报错 `'NoneType' object has no attribute 'replace'`。

---

## 新增功能

### 1. 数据库自动发现 (`sql_discover_databases`)
- 发现 MySQL 服务器上所有可访问的数据库
- 显示每个数据库的表数量和表列表概览
- 自动排除系统数据库（mysql, information_schema, performance_schema, sys）

### 2. 智能表匹配 (`sql_find_relevant_tables`)
- 根据自然语言描述自动匹配相关表
- 支持中文关键词提取和同义词扩展
- 基于表名、列名、表注释计算相关性得分
- 返回排序后的相关表列表

### 3. 跨数据库查询支持
- 使用 `database.table` 完全限定名支持跨库 JOIN
- 工具自动识别跨库查询并选择正确的数据库连接

---

## 修改文件

### 1. SQL 工具集
**文件**: `backend/packages/harness/deerflow/tools/builtins/sql_tools.py`

#### 新增工具

```python
@tool("sql_discover_databases")
def sql_discover_databases(include_tables: bool = True) -> str:
    """Discover all available databases on the MySQL server.

    Use this tool when you don't know what databases exist or when
    MYSQL_DATABASE is not configured. Returns a list of all databases
    with their table counts.
    """
    # ... 实现代码


@tool("sql_find_relevant_tables")
def sql_find_relevant_tables(query_description: str, top_k: int = 10, databases: str = "") -> str:
    """Find most relevant tables based on natural language query description.

    Use this tool to intelligently match tables when user asks a question
    without specifying which database or table to use.
    """
    # ... 实现代码
```

#### 新增辅助函数

```python
# 同义词映射表（40+ 中文关键词）
SYNONYM_MAP = {
    "用户": ["user", "users", "member", "account", "customer"],
    "订单": ["order", "orders", "purchase"],
    "活跃": ["active", "activity", "login"],
    # ... 更多映射
}

def _extract_keywords(text: str) -> set:
    """从文本中提取关键词，支持中英文"""

def _expand_keywords(keywords: set) -> set:
    """扩展关键词，添加同义词"""

def _calculate_relevance_score(keywords, table_name, columns, table_comment) -> TableMatch:
    """计算表与关键词的相关性得分"""

def _get_excluded_databases() -> set:
    """获取需要排除的系统数据库"""
```

#### 改造现有函数

**`_get_mysql_connection_string` 支持动态数据库**:
```python
# Before
def _get_mysql_connection_string() -> str:
    database = os.getenv("MYSQL_DATABASE", "")
    if database:
        return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
    else:
        return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/"

# After
def _get_mysql_connection_string(database: Optional[str] = None) -> str:
    db = database or os.getenv("MYSQL_DATABASE", "")
    if db:
        return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{db}"
    else:
        # 注意：此处需要连接到默认数据库，因为 LangChain SQLDatabase.from_uri() 不支持空数据库名
        # 实际使用时 MYSQL_DATABASE 必须配置
        raise ValueError("MYSQL_DATABASE must be configured. LangChain SQLDatabase.from_uri() requires a database name.")
```

**`_get_db` 支持动态数据库**:
```python
# Before
def _get_db() -> SQLDatabase:
    conn_str = _get_mysql_connection_string()
    return SQLDatabase.from_uri(conn_str, sample_rows_in_table_info=3)

# After
def _get_db(database: Optional[str] = None) -> SQLDatabase:
    conn_str = _get_mysql_connection_string(database)
    return SQLDatabase.from_uri(conn_str, sample_rows_in_table_info=3)
```

**`sql_list_tables` 无数据库时自动发现**:
```python
# Before
def sql_list_tables(database_name: str = "") -> str:
    db = _get_db()
    target_db = database_name or _get_default_database()
    if target_db:
        tables = db.get_usable_table_names()
        # ...
    else:
        result = db.run("SHOW DATABASES")
        return f"No default database configured. Available databases:\n{result}"

# After
def sql_list_tables(database_name: str = "") -> str:
    target_db = database_name or _get_default_database()
    if not target_db:
        return sql_discover_databases(include_tables=True)  # 自动发现
    db = _get_db(database=target_db)
    tables = db.get_usable_table_names()
    # ...
```

**`sql_query` 新增 Unknown database 错误处理**:
```python
# 新增错误处理
elif "Unknown database" in error_str:
    match = re.search(r"Unknown database '([^']+)'", error_str)
    if match:
        db_name = match.group(1)
        return f"SQL Error: Unknown database '{db_name}'. Use sql_discover_databases to check available databases."
```

**`SQL_TOOLS` 列表更新**:
```python
# Before
SQL_TOOLS = [
    sql_list_tables,
    sql_schema,
    sql_query,
    sql_query_checker,
]

# After
SQL_TOOLS = [
    sql_discover_databases,
    sql_find_relevant_tables,
    sql_list_tables,
    sql_schema,
    sql_query,
    sql_query_checker,
]
```

---

### 2. mysql-query Subagent 配置
**文件**: `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py`

#### description 更新

```python
# Before
description="""A specialized agent for MySQL database querying and data analysis.

Use this subagent when:
- User wants to query MySQL database for data retrieval or analysis
- Complex SQL queries are needed (joins, aggregations, subqueries, window functions)
- Schema exploration is required before writing queries
- User asks questions about data stored in MySQL database
- Statistical summaries or data insights are needed from database tables

Do NOT use for:
- Simple single-table queries that can be expressed directly
- Tasks that don't involve database querying"""

# After
description="""A specialized agent for MySQL database querying and data analysis with auto-discovery support.

Use this subagent when:
- User wants to query MySQL database for data retrieval or analysis
- User doesn't know which database or table contains the data they need
- Complex SQL queries are needed (joins, aggregations, subqueries, window functions)
- Cross-database queries are required
- Schema exploration is required before writing queries
- User asks questions about data stored in MySQL database
- Statistical summaries or data insights are needed from database tables

Do NOT use for:
- Simple single-table queries that can be expressed directly
- Tasks that don't involve database querying"""
```

#### system_prompt 更新

新增 `<available_tools>` 工具列表：
```python
<available_tools>
You have access to these SQL tools:
- sql_discover_databases: Discover all available databases on the MySQL server
- sql_find_relevant_tables: Find most relevant tables based on natural language query
- sql_list_tables: List all tables in a specific database
- sql_schema: Get schema information and sample data for specific tables
- sql_query: Execute SQL queries and return results
- sql_query_checker: Validate SQL syntax before execution
</available_tools>
```

新增 `<workflow>` 5 种场景自适应流程：
```python
<workflow>
Follow this adaptive workflow based on the situation:

**Scenario 1: Explore all databases**
1. Use sql_discover_databases to see all available databases
2. Use sql_find_relevant_tables with user's question to match relevant tables
3. Use sql_schema to understand matched tables (use "database.table" format)
4. Generate SQL using fully qualified names: database.table
5. Validate with sql_query_checker if query is complex
6. Execute with sql_query

**Scenario 2: User asks vague question, need smart matching**
1. Use sql_find_relevant_tables directly with user's natural language question
2. Review the matched tables and their relevance scores
3. Use sql_schema on the top matched tables
4. Generate SQL query based on schema information
5. Execute and return results

**Scenario 3: Known database, unknown tables**
1. Use sql_list_tables to see tables in the specific database
2. Use sql_schema to understand relevant tables
3. Generate and validate SQL
4. Execute query

**Scenario 4: Known tables, just need schema**
1. Use sql_schema directly on known tables
2. Generate and execute SQL

**Scenario 5: Cross-database queries**
1. Use sql_discover_databases or sql_find_relevant_tables to identify tables across databases
2. Use sql_schema with "db1.table1, db2.table2" format
3. Write SQL with fully qualified names: SELECT * FROM db1.users JOIN db2.orders ON ...
4. Validate and execute
</workflow>
```

新增 `<decision_logic>` 决策逻辑：
```python
<decision_logic>
When deciding which tool to use first:
- If you don't know what databases exist → sql_discover_databases
- If user's question is vague or you need to find relevant tables → sql_find_relevant_tables
- If you know the database but not tables → sql_list_tables
- If you know the tables but not columns → sql_schema
- Always validate complex queries with sql_query_checker before sql_query
</decision_logic>
```

新增 `<cross_database_queries>` 跨库查询说明：
```python
<cross_database_queries>
When querying across databases, use fully qualified table names:
- Single database: SELECT * FROM table_name
- Cross database: SELECT * FROM db1.users JOIN db2.orders ON db1.users.id = db2.orders.user_id
</cross_database_queries>
```

#### tools 列表更新

```python
# Before
tools=["sql_list_tables", "sql_schema", "sql_query", "sql_query_checker"]

# After
tools=["sql_discover_databases", "sql_find_relevant_tables", "sql_list_tables", "sql_schema", "sql_query", "sql_query_checker"]
```

---

### 3. Lead Agent Prompt
**文件**: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`

#### 问题修复

Lead Agent 的 system prompt 中未包含 `mysql-query` subagent 的描述信息，导致用户不知道可以通过 `task` 工具委托 MySQL 查询任务。

**修复**: 在 `_build_subagent_section` 函数中添加 `mysql-query` subagent 的描述：

```python
n = max_concurrent
bash_available = "bash" in get_available_subagent_names()
mysql_query_available = "mysql-query" in get_available_subagent_names()
available_subagents = (
    "- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.\n- **bash**: For command execution (git, build, test, deploy operations)\n- **mysql-query**: A specialized agent for MySQL database querying and data analysis with auto-discovery support."
    if bash_available and mysql_query_available
    else "- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.\n"
    "- **bash**: Not available in the current sandbox configuration. Use direct file/web tools or switch to AioSandboxProvider for isolated shell access.\n"
    "- **mysql-query**: A specialized agent for MySQL database querying and data analysis with auto-discovery support."
    if not bash_available and mysql_query_available
    else "- **general-purpose**: For ANY non-trivial task - web research, code exploration, file operations, analysis, etc.\n"
    "- **bash**: For command execution (git, build, test, deploy operations)\n"
    "- **mysql-query**: Not available. MySQL connection not configured."
)
```

---

### 4. 单元测试
**文件**: `backend/tests/test_sql_tools.py`

#### 新增测试文件

为 SQL 工具模块新增完整的单元测试覆盖，共 **79 个测试用例**。

#### 测试覆盖范围

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|----------|
| `TestExtractKeywords` | 8 | 中文/英文关键词提取、停用词过滤 |
| `TestExpandKeywords` | 5 | 同义词扩展（40+ 中文关键词映射） |
| `TestCalculateRelevanceScore` | 9 | 表名/列名/注释匹配评分算法 |
| `TestValidateSQL` | 13 | SQL 安全验证（禁止 DROP/DELETE/UPDATE 等） |
| `TestAddLimitIfNeeded` | 6 | SELECT 查询自动添加 LIMIT |
| `TestGetExcludedDatabases` | 3 | 系统数据库排除配置 |
| `TestGetMysqlConnectionString` | 3 | MySQL 连接字符串生成 |
| `TestSqlDiscoverDatabases` | 4 | 数据库自动发现工具 |
| `TestSqlFindRelevantTables` | 5 | 智能表匹配工具 |
| `TestSqlListTables` | 4 | 表列表工具 |
| `TestSqlSchema` | 5 | Schema 获取工具 |
| `TestSqlQuery` | 9 | SQL 执行工具（含错误处理） |
| `TestSqlQueryChecker` | 3 | SQL 验证工具 |
| `TestSQLToolsList` | 2 | 工具列表完整性 |

#### 测试示例

```python
class TestExtractKeywords:
    def test_extract_chinese_keywords(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("查询上个月活跃用户")
        assert len(result) > 0
        assert any("用户" in kw or "活跃" in kw or "上个月" in kw for kw in result)

class TestValidateSQL:
    def test_block_drop_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("DROP TABLE users")
        assert is_valid is False
        assert "DROP" in error

    def test_allow_update_with_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("UPDATE users SET name = 'test'", allow_write=True)
        assert is_valid is True
        assert error == ""
```

#### 运行测试

```bash
cd backend
$env:PYTHONPATH='.'; uv run pytest tests/test_sql_tools.py -v
```

测试结果: **79 passed in 0.65s**

---

### 5. Skill 指导文档
**文件**: `skills/public/mysql-query/SKILL.md`

#### description 更新

```yaml
# Before
description: Use this skill when the user wants to query MySQL databases for data analysis, reporting, or exploration. The skill delegates to a specialized mysql-query subagent that handles schema inspection, SQL generation, query validation, and automatic error recovery. Supports complex queries including joins, aggregations, and subqueries. Requires MySQL connection configuration via environment variables.

# After
description: Use this skill when the user wants to query MySQL databases for data analysis, reporting, or exploration. The skill now supports automatic database discovery and intelligent table matching - users can ask questions without specifying which database to use. The subagent will automatically discover all available databases, match relevant tables based on the question, and support cross-database queries. Requires MySQL connection configuration via environment variables.
```

#### Prerequisites 更新

```markdown
# Before
```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

# After
```bash
# Required: MySQL server connection
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password

# Required: Default database (must be specified due to LangChain SQLDatabase.from_uri() limitation)
MYSQL_DATABASE=your_database

# Optional: Exclude system databases from discovery
MYSQL_EXCLUDED_DBS=mysql,information_schema,performance_schema,sys
```
```

#### Subagent Tools 表格更新

```markdown
# Before (4 tools)
| Tool | Description |
|------|-------------|
| `sql_list_tables` | List all tables in the database |
| `sql_schema` | Get schema and sample rows for specified tables |
| `sql_query` | Execute SQL query and return results |
| `sql_query_checker` | Validate SQL syntax before execution |

# After (6 tools)
| Tool | Description | When to Use |
|------|-------------|-------------|
| `sql_discover_databases` | Discover all databases and table overview | Unknown database environment |
| `sql_find_relevant_tables` | Match tables based on natural language | Need smart table matching |
| `sql_list_tables` | List tables in a specific database | Known database, unknown tables |
| `sql_schema` | Get schema and sample rows | Need column information |
| `sql_query` | Execute SQL query | Final execution step |
| `sql_query_checker` | Validate SQL syntax | Complex queries, before execution |
```

#### 新增使用示例

```markdown
### Auto-discovery (No Database Specified)

```json
{
  "description": "探索所有数据库",
  "prompt": "列出 MySQL 服务器上所有可用的数据库及其表概览",
  "subagent_type": "mysql-query"
}
```

### Smart Matching Query

```json
{
  "description": "智能匹配查询",
  "prompt": "查询上个月活跃度最高的前10个用户，显示用户名和活跃次数",
  "subagent_type": "mysql-query"
}
```

### Cross-Database Query

```json
{
  "description": "跨库关联查询",
  "prompt": "查询 carbon_service_user.users 和 carbon_service_order.orders，找出下单次数超过5次的用户",
  "subagent_type": "mysql-query"
}
```
```

---

## 配置变更

### 环境变量

| 变量 | 变更 | 说明 |
|------|------|------|
| `MYSQL_DATABASE` | **必填** | 必须指定默认数据库（LangChain 限制） |
| `MYSQL_EXCLUDED_DBS` | **新增** | 排除系统数据库，默认值已内置 |

### 新增默认配置

```bash
# 系统自动使用以下默认排除列表
MYSQL_EXCLUDED_DBS=mysql,information_schema,performance_schema,sys
```

---

## 工具对比

| 特性 | 旧版 (4 工具) | 新版 (6 工具) |
|------|---------------|---------------|
| 数据库发现 | ❌ 需手动指定 | ✅ 自动发现 |
| 智能匹配 | ❌ 需知道表名 | ✅ 自然语言匹配 |
| 跨库查询 | ❌ 不支持 | ✅ 支持 `db.table` 格式 |
| 同义词扩展 | ❌ 无 | ✅ 40+ 中文关键词映射 |
| 错误提示 | 基础 | 增强（Unknown database） |
| Lead Agent 描述 | ❌ 遗漏 | ✅ 已添加 |

---

## 使用示例

### 场景 1：完全陌生环境

用户: "帮我查一下数据库里有什么数据"

```json
{
  "description": "探索数据库",
  "prompt": "列出所有可用的数据库和表",
  "subagent_type": "mysql-query"
}
```

Subagent 执行流程:
1. `sql_discover_databases()` → 发现 4 个数据库
2. 返回数据库概览给用户

### 场景 2：智能匹配查询

用户: "查询上个月活跃用户的情况"

```json
{
  "description": "智能查询用户活跃度",
  "prompt": "查询上个月活跃度最高的前10个用户",
  "subagent_type": "mysql-query"
}
```

Subagent 执行流程:
1. `sql_find_relevant_tables("上个月活跃用户")` → 匹配 `user_activity`, `users`
2. `sql_schema("carbon_service_user.user_activity")` → 获取表结构
3. `sql_query("SELECT ... FROM carbon_service_user.user_activity ...")` → 执行查询

### 场景 3：跨库查询

用户: "对比用户服务和订单服务的数据"

```json
{
  "description": "跨库对比分析",
  "prompt": "查询 carbon_service_user.users 和 carbon_service_order.orders，统计每个用户的订单数",
  "subagent_type": "mysql-query"
}
```

Subagent 执行流程:
1. `sql_schema("carbon_service_user.users, carbon_service_order.orders")` → 获取两表结构
2. `sql_query("SELECT u.name, COUNT(o.id) FROM carbon_service_user.users u JOIN carbon_service_order.orders o ON u.id = o.user_id GROUP BY u.id")` → 跨库 JOIN

---

## 影响范围

| 影响项 | 说明 |
|--------|------|
| **工具数量** | 从 4 个扩展到 6 个 |
| **配置要求** | `MYSQL_DATABASE` 必填（LangChain 限制） |
| **向后兼容** | 完全兼容，原有配置仍可使用 |
| **新增能力** | 自动发现、智能匹配、跨库查询 |
| **Lead Agent** | system prompt 中添加 `mysql-query` subagent 描述 |

---

## 后续建议

1. **性能优化**: 可添加元数据缓存机制，避免重复查询 `information_schema`
2. **语义增强**: 可集成 embedding 模型，提升语义匹配准确度
3. **扩展支持**: 可添加 PostgreSQL、SQLite 等其他数据库支持
4. **权限控制**: 可添加数据库/表级别的访问权限配置

---

## 文件变更汇总

| 文件 | 改动说明 |
|------|----------|
| `backend/packages/harness/deerflow/tools/builtins/sql_tools.py` | 新增 2 个工具，改造 4 个现有工具 |
| `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py` | 更新 system_prompt 和 tools 列表 |
| `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` | 在 `_build_subagent_section` 中添加 `mysql-query` 描述 |
| `skills/public/mysql-query/SKILL.md` | 更新文档内容 |
| `backend/tests/test_sql_tools.py` | 新增单元测试文件（79 个测试用例） |

---

## Bash 工具启用改动 (2026-04-28)

### 问题背景

在使用 `chart-visualization` 技能生成图表时，发现任务执行失败并导致服务崩溃。根本原因是：

1. **Subagent 没有 bash 工具**: `config.yaml` 中 `allow_host_bash: false` 导致 bash 工具被禁用
2. **连锁反应**: Subagent 无法执行 `node generate.js` 命令，尝试多次 workaround 后失败
3. **服务阻塞**: 主 agent 在 `task_tool.py` 中轮询等待 subagent 完成，阻塞共享事件循环
4. **线程池耗尽**: `_scheduler_pool(3)`, `_execution_pool(3)`, `_isolated_loop_pool(3)` 满负荷运转
5. **服务崩溃**: 最终触发超时重启

### 改动内容

**文件**: `config.yaml`

```yaml
# Before
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false

# After
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: true
```

### 影响说明

| 影响项 | 说明 |
|--------|------|
| **bash 工具可用** | Subagent 现在可以执行 shell 命令 |
| **chart-visualization** | 可以正常执行 `node generate.js` 生成图表 |
| **安全性** | 仅适合可信单机环境，生产环境建议使用 `AioSandboxProvider` |

### 长期建议

生产环境建议切换到容器沙箱：

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  # bash 工具自动可用，无需 allow_host_bash
```

### 文件变更

| 文件 | 改动说明 |
|------|----------|
| `config.yaml` | `allow_host_bash: false` → `allow_host_bash: true` |