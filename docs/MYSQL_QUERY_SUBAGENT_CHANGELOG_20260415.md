# MySQL Query Subagent 改动说明

**日期**: 2026-04-15

## 改动概述

本次改动为 DeerFlow 添加了 MySQL 数据库查询能力，通过创建一个专门的 `mysql-query` subagent 实现。该 subagent 使用 DeerFlow 内置的 subagent 机制，而非在 skill 脚本中嵌套 LangChain Agent。

---

## 新增文件

### 1. SQL 工具集
**文件**: `backend/packages/harness/deerflow/tools/builtins/sql_tools.py`

提供四个 SQL 相关工具：
- `sql_list_tables`: 列出数据库中所有表
- `sql_schema`: 获取指定表的 schema 信息
- `sql_query`: 执行 SQL 查询
- `sql_query_checker`: 验证 SQL 语法

**安全特性**:
- 默认只读模式，禁止 INSERT/UPDATE/DELETE/DROP
- 自动添加 LIMIT 防止返回过多数据
- 错误信息友好提示

### 2. mysql-query Subagent 配置
**文件**: `backend/packages/harness/deerflow/subagents/builtins/mysql_query.py`

定义 `mysql-query` subagent 的配置：
- 专用系统提示，指导 SQL 查询工作流
- 工具白名单：只允许 SQL 工具
- 继承父 Agent 模型（无需单独配置 LLM）
- 最大轮次：20，超时：300秒

### 3. Skill 指导文档
**文件**: `skills/public/mysql-query/SKILL.md`

指导 Lead Agent 如何使用 `task` 工具委托查询任务给 `mysql-query` subagent。

---

## 修改文件

### 1. Subagent 注册
**文件**: `backend/packages/harness/deerflow/subagents/builtins/__init__.py`

**改动**:
```python
# 新增导入
from .mysql_query import MYSQL_QUERY_CONFIG

# 新增注册
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "bash": BASH_AGENT_CONFIG,
    "mysql-query": MYSQL_QUERY_CONFIG,  # 新增
}
```

### 2. 工具注册
**文件**: `backend/packages/harness/deerflow/tools/tools.py`

**改动**:
```python
# 新增导入
from deerflow.tools.builtins.sql_tools import SQL_TOOLS

# 新增 SQL 工具列表
SQL_BUILTIN_TOOLS = SQL_TOOLS

# get_available_tools 函数新增参数
include_sql_tools: bool = True

# 新增 SQL 工具加载逻辑
if include_sql_tools:
    builtin_tools.extend(SQL_BUILTIN_TOOLS)
```

---

## 架构

### 新设计（当前）
```
Lead Agent → task 工具 → mysql-query subagent (由 DeerFlow 运行时管理) → 查询数据库
```
**优势**: 单一 Agent 管理，模型继承，上下文隔离

---

## 数据流

```
用户请求
    ↓
Lead Agent (识别意图，加载 SKILL.md)
    ↓
task 工具 (委托任务)
    ↓
mysql-query Subagent (独立上下文)
    │
    ├─ sql_list_tables (探索表)
    ├─ sql_schema (获取结构)
    ├─ sql_query_checker (验证 SQL)
    └─ sql_query (执行查询)
    ↓
MySQL Database
    ↓
SubagentResult (返回结果)
    ↓
Lead Agent (呈现给用户)
```

---

## 配置要求

在 `.env` 中添加 MySQL 连接配置：

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database（可选）

# 可选：启用写操作（谨慎使用）
MYSQL_ALLOW_WRITE=false
```

---

## 影响范围

| 影响项 | 说明 |
|--------|------|
| **新增 subagent** | `mysql-query` 可通过 `task` 工具调用 |
| **新增工具** | 4 个 SQL 工具注册到工具池 |
| **向后兼容** | 不影响现有功能，纯增量改动 |
| **依赖** | 需要 `langchain-community` 和 `mysql-connector-python` |

---

## 后续建议

1. **测试**: 需要在有 MySQL 数据库的环境中测试完整流程
2. **扩展**: 可考虑添加 PostgreSQL、SQLite 等其他数据库支持
3. **优化**: 可添加查询结果缓存机制
4. **文档**: 可在 DeerFlow 官方文档中添加此 skill 的使用说明

---

## 更新记录

### 2026-04-16

**问题**: 启动服务时报错 `ModuleNotFoundError: No module named 'langchain_community'`

**原因**: `sql_tools.py` 中使用了 `from langchain_community.utilities import SQLDatabase`，但 `langchain-community` 包未在依赖中声明。

**修复**: 在 `backend/packages/harness/pyproject.toml` 中添加依赖：

```toml
"langchain-community>=0.3.0",
```

**文件变更**:
- `backend/packages/harness/pyproject.toml`: 新增 `langchain-community>=0.3.0` 依赖

---

### 2026-04-17

**问题**: 执行 SQL 工具时报错 `No module named 'mysql'`

**原因**: `sql_tools.py` 使用 `mysql+mysqlconnector://` 连接字符串，需要 `mysql-connector-python` 包，但依赖中未声明。

**修复**: 在 `backend/packages/harness/pyproject.toml` 中添加依赖：

```toml
"mysql-connector-python>=8.0.0",
```

**文件变更**:
- `backend/packages/harness/pyproject.toml`: 新增 `mysql-connector-python>=8.0.0` 依赖

---

### 2026-04-17 (2)

**问题**: 执行 SQL 工具时报错 `'NoneType' object has no attribute 'replace'`

**原因**: `MYSQL_DATABASE` 环境变量为空，导致连接字符串没有指定默认数据库，`SQLDatabase.from_uri()` 内部处理失败。

**修复**: 在 `.env` 中配置默认数据库：

```bash
MYSQL_DATABASE=your_database_name
```
