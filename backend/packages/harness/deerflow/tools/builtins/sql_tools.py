"""SQL tools for MySQL database querying."""

import os
import re
from typing import Optional

from langchain.tools import tool
from langchain_community.utilities import SQLDatabase

FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE",
    "GRANT", "REVOKE", "EXECUTE", "CALL"
]

UPDATE_INSERT_KEYWORDS = ["UPDATE", "INSERT", "REPLACE"]

DEFAULT_LIMIT = 100


def _get_mysql_connection_string(database: Optional[str] = None) -> str:
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    db = database or os.getenv("MYSQL_DATABASE", "")

    if db:
        return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{db}"
    else:
        return f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/"


def _get_default_database() -> str:
    return os.getenv("MYSQL_DATABASE", "")


def _get_db(database: Optional[str] = None) -> SQLDatabase:
    conn_str = _get_mysql_connection_string(database)
    return SQLDatabase.from_uri(
        conn_str,
        sample_rows_in_table_info=3,
    )


def _validate_sql(sql: str, allow_write: bool = False) -> tuple[bool, str]:
    sql_upper = sql.upper().strip()

    for keyword in FORBIDDEN_KEYWORDS:
        pattern = r'(^|\s|;)\s*' + keyword + r'(\s|$|;)'
        if re.search(pattern, sql_upper):
            return False, f"Forbidden operation detected: {keyword}"

    if not allow_write:
        for keyword in UPDATE_INSERT_KEYWORDS:
            pattern = r'(^|\s|;)\s*' + keyword + r'(\s|$|;)'
            if re.search(pattern, sql_upper):
                return False, f"Write operation blocked: {keyword}. Set MYSQL_ALLOW_WRITE=true to enable."

    return True, ""


def _add_limit_if_needed(sql: str, limit: int = DEFAULT_LIMIT) -> str:
    sql_upper = sql.upper().strip()

    if sql_upper.startswith("SELECT") and "LIMIT" not in sql_upper:
        sql = sql.rstrip(";")
        sql = f"{sql} LIMIT {limit}"

    return sql


@tool("sql_show_databases")
def sql_show_databases(pattern: str = "") -> str:
    """Show databases matching a name pattern.

    Use this tool to find specific databases when you don't know the exact name.
    This is a lightweight discovery tool that only queries database names,
    not their tables or schemas.

    Args:
        pattern: Optional pattern to filter databases (SQL LIKE pattern).
                 Example: "carbon_client_efficiency" will find databases like
                 "carbon_client_efficiency_20260407163459_7".
                 If empty, shows all databases (excluding system databases).

    Returns:
        List of matching database names.

    Example:
        >>> sql_show_databases("carbon_client_efficiency")
        Found 5 databases matching 'carbon_client_efficiency':
        1. carbon_client_efficiency_20260213115348_1
        2. carbon_client_efficiency_20260213141612_2
        3. carbon_client_efficiency_20260407163459_7
        ...
    """
    try:
        db = _get_db(database=None)

        if pattern:
            query = f"SHOW DATABASES LIKE '%{pattern}%'"
        else:
            query = "SHOW DATABASES"

        result = db.run(query)

        if not result:
            return f"No databases found matching pattern '{pattern}'."

        db_names = []
        if isinstance(result, str):
            import ast
            try:
                parsed = ast.literal_eval(result)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, (list, tuple)):
                            db_names.append(item[0] if item[0] else "")
                        elif isinstance(item, str):
                            db_names.append(item)
            except (ValueError, SyntaxError):
                for line in result.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("[") and not line.startswith("("):
                        db_names.append(line)
        elif isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, (list, tuple)):
                    db_names.append(item[0] if item[0] else "")
                else:
                    db_names.append(str(item) if item else "")

        excluded = {"mysql", "information_schema", "performance_schema", "sys"}
        db_names = [name for name in db_names if name and name not in excluded]

        if not db_names:
            return f"No databases found matching pattern '{pattern}'."

        if pattern:
            output = f"Found {len(db_names)} databases matching '{pattern}':\n"
        else:
            output = f"Found {len(db_names)} databases:\n"

        for i, name in enumerate(db_names, 1):
            output += f"  {i}. {name}\n"

        return output

    except Exception as e:
        return f"Error showing databases: {e}"


@tool("sql_list_tables")
def sql_list_tables(database_name: str = "") -> str:
    """List all available tables in the MySQL database.

    Use this tool first to discover what tables exist before querying.

    Args:
        database_name: Optional database name to list tables from.
                       If not provided, uses MYSQL_DATABASE from environment.

    Returns:
        A formatted list of available table names.
    """
    try:
        target_db = database_name or _get_default_database()

        if not target_db:
            return "Error: No database specified. Please provide database_name parameter or configure MYSQL_DATABASE in .env"

        db = _get_db(database=target_db)
        tables = db.get_usable_table_names()

        if not tables:
            return f"No tables found in database '{target_db}'."

        result = f"Available tables in '{target_db}' ({len(tables)}):\n"
        for i, table in enumerate(tables, 1):
            result += f"  {i}. {table}\n"

        return result

    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        return f"Error listing tables: {e}"


@tool("sql_schema")
def sql_schema(table_names: str) -> str:
    """Get schema information and sample rows for specified tables.

    Use this tool to understand table structure before writing queries.

    Args:
        table_names: Comma-separated list of table names to inspect.
                     Example: "users,orders,products"
                     For cross-database queries, use "database.table" format.
                     Example: "db1.users,db2.orders"

    Returns:
        Schema information including columns, types, and sample data.
    """
    try:
        tables = [t.strip() for t in table_names.split(",") if t.strip()]

        if not tables:
            return "Error: No table names provided. Example: 'users,orders' or 'db1.users,db2.orders'"

        default_db = _get_default_database()

        db_to_use = default_db
        for table in tables:
            if "." in table:
                db_to_use = table.split(".")[0]
                break

        if not db_to_use:
            return "Error: No database specified. Please provide table names with database prefix (e.g., 'db1.users') or configure MYSQL_DATABASE in .env"

        db = _get_db(database=db_to_use)

        if default_db and "." not in tables[0]:
            available_tables = db.get_usable_table_names()
            invalid_tables = [t for t in tables if t not in available_tables and "." not in t]
            if invalid_tables:
                return f"Error: Tables not found: {invalid_tables}. Available: {available_tables}"

        schema_info = db.get_table_info(tables)

        return f"Schema for tables: {tables}\n\n{schema_info}"

    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        return f"Error getting schema: {e}"


@tool("sql_query")
def sql_query(query: str) -> str:
    """Execute a SQL query on the MySQL database and return results.

    This tool validates the query for safety before execution.
    By default, only SELECT queries are allowed.

    Args:
        query: The SQL query to execute. Must be a valid MySQL query.
               For cross-database queries, use fully qualified names.
               Example: "SELECT * FROM db1.users JOIN db2.orders ON ..."
               Example: "SELECT * FROM users WHERE status = 'active' LIMIT 10"

    Returns:
        Query results formatted as a table, or error message.
    """
    allow_write = os.getenv("MYSQL_ALLOW_WRITE", "false").lower() == "true"

    is_valid, error_msg = _validate_sql(query, allow_write)
    if not is_valid:
        return f"Query blocked: {error_msg}"

    try:
        default_db = _get_default_database()

        db_to_use = default_db
        if "." in query:
            match = re.search(r'FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE)
            if match:
                db_to_use = match.group(1)

        if not db_to_use:
            return "Error: No database specified. Please use fully qualified table names (e.g., 'db1.users') or configure MYSQL_DATABASE in .env"

        db = _get_db(database=db_to_use)

        query = _add_limit_if_needed(query)

        result = db.run(query)

        if not result:
            return "Query returned no results."

        return result

    except ValueError as e:
        return f"Configuration error: {e}"
    except Exception as e:
        error_str = str(e)

        if "Unknown column" in error_str:
            match = re.search(r"Unknown column '([^']+)'", error_str)
            if match:
                col_name = match.group(1)
                return f"SQL Error: Unknown column '{col_name}'. Use sql_schema to check available columns."
        elif "Table" in error_str and "doesn't exist" in error_str:
            match = re.search(r"Table '([^']+)'", error_str)
            if match:
                table_name = match.group(1)
                return f"SQL Error: Table '{table_name}' doesn't exist. Use sql_list_tables to check available tables."
        elif "Unknown database" in error_str:
            match = re.search(r"Unknown database '([^']+)'", error_str)
            if match:
                db_name = match.group(1)
                return f"SQL Error: Unknown database '{db_name}'. Please check the database name."
        elif "syntax" in error_str.lower():
            return f"SQL Syntax Error: {e}. Please check your query syntax."

        return f"Error executing query: {e}"


@tool("sql_query_checker")
def sql_query_checker(query: str) -> str:
    """Validate a SQL query for correctness before execution.

    Use this tool to double-check your query syntax before running it.

    Args:
        query: The SQL query to validate.

    Returns:
        Validation result indicating if the query is valid or has errors.
    """
    allow_write = os.getenv("MYSQL_ALLOW_WRITE", "false").lower() == "true"

    is_valid, error_msg = _validate_sql(query, allow_write)
    if not is_valid:
        return f"Validation failed: {error_msg}"

    try:
        default_db = _get_default_database()

        db_to_use = default_db
        if "." in query:
            match = re.search(r'FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE)
            if match:
                db_to_use = match.group(1)

        if not db_to_use:
            return "Validation skipped: No database specified. Query syntax check only."

        db = _get_db(database=db_to_use)

        db.run(f"EXPLAIN {query}")

        return f"Query is valid and ready to execute.\nQuery: {query}"

    except Exception as e:
        return f"Query validation failed: {e}"


SQL_TOOLS = [
    sql_show_databases,
    sql_list_tables,
    sql_schema,
    sql_query,
    sql_query_checker,
]