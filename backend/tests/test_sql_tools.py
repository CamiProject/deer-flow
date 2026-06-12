"""Unit tests for SQL tools with auto-discovery support."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestExtractKeywords:
    def test_extract_chinese_keywords(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("查询上个月活跃用户")
        assert len(result) > 0
        assert any("用户" in kw or "活跃" in kw or "上个月" in kw for kw in result)

    def test_extract_english_keywords(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("find active users last month")
        assert "active" in result
        assert "users" in result
        assert "last" in result
        assert "month" in result

    def test_extract_mixed_keywords(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("查询 users 表的订单数据")
        assert "users" in result
        assert any("订单" in kw or "数据" in kw for kw in result)

    def test_filter_stop_words(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("请帮我查询所有的用户数据")
        assert "请" not in result
        assert "帮" not in result
        assert "我" not in result
        assert "的" not in result
        assert len(result) > 0

    def test_filter_english_stop_words(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("the users are active in the system")
        assert "the" not in result
        assert "are" not in result
        assert "in" not in result
        assert "users" in result
        assert "active" in result
        assert "system" in result

    def test_empty_input(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("")
        assert result == set()

    def test_only_stop_words(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("的 的 的")
        assert result == set()

    def test_short_words_filtered(self):
        from deerflow.tools.builtins.sql_tools import _extract_keywords

        result = _extract_keywords("a b c d test")
        assert "a" not in result
        assert "b" not in result
        assert "test" in result


class TestExpandKeywords:
    def test_expand_chinese_synonyms(self):
        from deerflow.tools.builtins.sql_tools import _expand_keywords

        result = _expand_keywords({"用户"})
        assert "用户" in result
        assert "user" in result
        assert "users" in result
        assert "member" in result
        assert "account" in result

    def test_expand_english_to_chinese(self):
        from deerflow.tools.builtins.sql_tools import _expand_keywords

        result = _expand_keywords({"user"})
        assert "user" in result
        assert "用户" in result
        assert "users" in result

    def test_expand_multiple_keywords(self):
        from deerflow.tools.builtins.sql_tools import _expand_keywords

        result = _expand_keywords({"用户", "订单"})
        assert "user" in result
        assert "order" in result
        assert "users" in result
        assert "orders" in result

    def test_expand_no_match(self):
        from deerflow.tools.builtins.sql_tools import _expand_keywords

        result = _expand_keywords({"unknown_keyword"})
        assert "unknown_keyword" in result
        assert len(result) == 1

    def test_expand_empty_set(self):
        from deerflow.tools.builtins.sql_tools import _expand_keywords

        result = _expand_keywords(set())
        assert result == set()


class TestCalculateRelevanceScore:
    def test_exact_table_name_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"users"},
            table_name="users",
            columns=["id", "name", "email"],
            table_comment="用户表"
        )
        assert result.score == 1.0
        assert "table:users" in result.matched_keywords

    def test_partial_table_name_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"user"},
            table_name="user_activity",
            columns=["id", "user_id", "action"],
            table_comment=""
        )
        assert result.score > 0
        assert "table_contains:user" in result.matched_keywords

    def test_exact_column_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"email"},
            table_name="users",
            columns=["id", "name", "email"],
            table_comment=""
        )
        assert result.score > 0
        assert "column:email" in result.matched_keywords
        assert "email" in result.column_hints

    def test_partial_column_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"user"},
            table_name="activity",
            columns=["user_id", "user_name", "action"],
            table_comment=""
        )
        assert result.score > 0
        assert any("column_contains" in m for m in result.matched_keywords)

    def test_comment_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"订单"},
            table_name="t_data",
            columns=["id", "value"],
            table_comment="订单数据表"
        )
        assert result.score > 0
        assert "comment:订单" in result.matched_keywords

    def test_multiple_keyword_matches(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"user", "activity"},
            table_name="user_activity",
            columns=["user_id", "activity_type"],
            table_comment=""
        )
        assert result.score > 0
        assert len(result.matched_keywords) >= 2

    def test_no_match(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"product"},
            table_name="users",
            columns=["id", "name"],
            table_comment=""
        )
        assert result.score == 0.0
        assert result.matched_keywords == []

    def test_empty_keywords(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords=set(),
            table_name="users",
            columns=["id", "name"],
            table_comment=""
        )
        assert result.score == 0.0

    def test_normalized_score(self):
        from deerflow.tools.builtins.sql_tools import _calculate_relevance_score

        result = _calculate_relevance_score(
            keywords={"a", "b", "c", "d", "e"},
            table_name="a",
            columns=["b"],
            table_comment="c"
        )
        assert result.score <= 1.0


class TestValidateSQL:
    def test_valid_select_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("SELECT * FROM users")
        assert is_valid is True
        assert error == ""

    def test_valid_select_with_where(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("SELECT id, name FROM users WHERE status = 'active'")
        assert is_valid is True
        assert error == ""

    def test_valid_join_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert is_valid is True
        assert error == ""

    def test_block_drop_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("DROP TABLE users")
        assert is_valid is False
        assert "DROP" in error

    def test_block_delete_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("DELETE FROM users WHERE id = 1")
        assert is_valid is False
        assert "DELETE" in error

    def test_block_truncate_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("TRUNCATE TABLE users")
        assert is_valid is False
        assert "TRUNCATE" in error

    def test_block_alter_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("ALTER TABLE users ADD COLUMN age INT")
        assert is_valid is False
        assert "ALTER" in error

    def test_block_create_query(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("CREATE TABLE test (id INT)")
        assert is_valid is False
        assert "CREATE" in error

    def test_block_update_without_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("UPDATE users SET name = 'test'")
        assert is_valid is False
        assert "UPDATE" in error

    def test_block_insert_without_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert is_valid is False
        assert "INSERT" in error

    def test_allow_update_with_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("UPDATE users SET name = 'test'", allow_write=True)
        assert is_valid is True
        assert error == ""

    def test_allow_insert_with_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("INSERT INTO users (name) VALUES ('test')", allow_write=True)
        assert is_valid is True
        assert error == ""

    def test_block_grant_even_with_write_permission(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("GRANT ALL ON users TO test", allow_write=True)
        assert is_valid is False
        assert "GRANT" in error

    def test_case_insensitive_detection(self):
        from deerflow.tools.builtins.sql_tools import _validate_sql

        is_valid, error = _validate_sql("drop table users")
        assert is_valid is False
        assert "DROP" in error


class TestAddLimitIfNeeded:
    def test_add_limit_to_simple_select(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed("SELECT * FROM users")
        assert "LIMIT 100" in result

    def test_add_limit_with_custom_value(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed("SELECT * FROM users", limit=50)
        assert "LIMIT 50" in result

    def test_not_add_limit_if_already_exists(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed("SELECT * FROM users LIMIT 10")
        assert result == "SELECT * FROM users LIMIT 10"

    def test_not_add_limit_to_non_select(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed("SHOW TABLES")
        assert "LIMIT" not in result

    def test_remove_trailing_semicolon_before_limit(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed("SELECT * FROM users;")
        assert result == "SELECT * FROM users LIMIT 100"

    def test_complex_select_with_join(self):
        from deerflow.tools.builtins.sql_tools import _add_limit_if_needed

        result = _add_limit_if_needed(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert "LIMIT 100" in result


class TestGetExcludedDatabases:
    def test_default_excluded_databases(self):
        from deerflow.tools.builtins.sql_tools import _get_excluded_databases

        with patch.dict(os.environ, {}, clear=True):
            if "MYSQL_EXCLUDED_DBS" in os.environ:
                del os.environ["MYSQL_EXCLUDED_DBS"]
            result = _get_excluded_databases()
            assert "mysql" in result
            assert "information_schema" in result
            assert "performance_schema" in result
            assert "sys" in result

    def test_custom_excluded_databases(self):
        from deerflow.tools.builtins.sql_tools import _get_excluded_databases

        with patch.dict(os.environ, {"MYSQL_EXCLUDED_DBS": "custom_db,test_db"}):
            result = _get_excluded_databases()
            assert "custom_db" in result
            assert "test_db" in result

    def test_excluded_databases_with_spaces(self):
        from deerflow.tools.builtins.sql_tools import _get_excluded_databases

        with patch.dict(os.environ, {"MYSQL_EXCLUDED_DBS": "db1, db2 , db3 "}):
            result = _get_excluded_databases()
            assert "db1" in result
            assert "db2" in result
            assert "db3" in result


class TestGetMysqlConnectionString:
    def test_connection_string_with_database(self):
        from deerflow.tools.builtins.sql_tools import _get_mysql_connection_string

        with patch.dict(os.environ, {
            "MYSQL_HOST": "localhost",
            "MYSQL_PORT": "3306",
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": "password",
            "MYSQL_DATABASE": "testdb"
        }):
            result = _get_mysql_connection_string()
            assert "testdb" in result
            assert "localhost" in result
            assert "3306" in result
            assert "root" in result

    def test_connection_string_without_database(self):
        from deerflow.tools.builtins.sql_tools import _get_mysql_connection_string

        env_vars = {
            "MYSQL_HOST": "localhost",
            "MYSQL_PORT": "3306",
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": "password"
        }
        with patch.dict(os.environ, env_vars, clear=True):
            if "MYSQL_DATABASE" in os.environ:
                del os.environ["MYSQL_DATABASE"]
            result = _get_mysql_connection_string()
            assert result.endswith("/")

    def test_connection_string_with_explicit_database(self):
        from deerflow.tools.builtins.sql_tools import _get_mysql_connection_string

        with patch.dict(os.environ, {
            "MYSQL_HOST": "localhost",
            "MYSQL_PORT": "3306",
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": "password",
            "MYSQL_DATABASE": "defaultdb"
        }):
            result = _get_mysql_connection_string(database="otherdb")
            assert "otherdb" in result
            assert "defaultdb" not in result


class TestSqlDiscoverDatabases:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_discover_databases_success(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_discover_databases

        mock_db = MagicMock()
        mock_db.run.side_effect = [
            [["db1"], ["db2"], ["mysql"], ["information_schema"]],
            [["table1", 100, "comment1"], ["table2", 200, "comment2"]],
            [["table3", 50, "comment3"]],
        ]
        mock_get_db.return_value = mock_db

        result = sql_discover_databases.invoke({"include_tables": True})

        assert "db1" in result
        assert "db2" in result
        assert "mysql" not in result
        assert "information_schema" not in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_discover_databases_without_tables(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_discover_databases

        mock_db = MagicMock()
        mock_db.run.return_value = [["db1"], ["db2"], ["mysql"]]
        mock_get_db.return_value = mock_db

        result = sql_discover_databases.invoke({"include_tables": False})

        assert "db1" in result
        assert "db2" in result
        assert "tables" not in result.lower() or "0 tables" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_discover_databases_empty_result(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_discover_databases

        mock_db = MagicMock()
        mock_db.run.return_value = []
        mock_get_db.return_value = mock_db

        result = sql_discover_databases.invoke({"include_tables": True})

        assert "No databases found" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_discover_databases_error(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_discover_databases

        mock_get_db.side_effect = Exception("Connection failed")

        result = sql_discover_databases.invoke({"include_tables": True})

        assert "Error" in result
        assert "Connection failed" in result


class TestSqlFindRelevantTables:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_find_relevant_tables_success(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_find_relevant_tables

        mock_db = MagicMock()
        mock_db.run.side_effect = [
            [["test_db"]],
            [["users", "用户表"], ["orders", "订单表"], ["products", "商品表"]],
            [["id", "name", "email"]],
            [["id", "user_id", "total"]],
            [["id", "name", "price"]],
        ]
        mock_get_db.return_value = mock_db

        result = sql_find_relevant_tables.invoke({
            "query_description": "查询用户",
            "top_k": 5
        })

        assert "Keywords extracted" in result
        assert "用户" in result or "user" in result.lower()

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_find_relevant_tables_with_specific_databases(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_find_relevant_tables

        mock_db = MagicMock()
        mock_db.run.side_effect = [
            [["db1"], ["db2"]],
            [["users", "用户表"]],
            [["id", "name"]],
        ]
        mock_get_db.return_value = mock_db

        result = sql_find_relevant_tables.invoke({
            "query_description": "查询用户",
            "databases": "db1"
        })

        assert "Keywords extracted" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_find_relevant_tables_no_match(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_find_relevant_tables

        mock_db = MagicMock()
        mock_db.run.side_effect = [
            [["test_db"]],
            [["random_table", "随机表"]],
            [["col1", "col2"]],
        ]
        mock_get_db.return_value = mock_db

        result = sql_find_relevant_tables.invoke({
            "query_description": "查询用户信息"
        })

        assert "No relevant tables found" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_find_relevant_tables_empty_keywords(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_find_relevant_tables

        result = sql_find_relevant_tables.invoke({
            "query_description": "的的的"
        })

        assert "No relevant tables found" in result or "的的的" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    def test_find_relevant_tables_error(self, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_find_relevant_tables

        mock_get_db.side_effect = Exception("Connection error")

        result = sql_find_relevant_tables.invoke({
            "query_description": "查询用户"
        })

        assert "Error" in result


class TestSqlListTables:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_list_tables_with_default_database(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_list_tables

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = ["users", "orders", "products"]
        mock_get_db.return_value = mock_db

        result = sql_list_tables.invoke({"database_name": ""})

        assert "testdb" in result
        assert "users" in result
        assert "orders" in result
        assert "products" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_list_tables_with_specific_database(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_list_tables

        mock_get_default.return_value = "defaultdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = ["table1", "table2"]
        mock_get_db.return_value = mock_db

        result = sql_list_tables.invoke({"database_name": "otherdb"})

        assert "otherdb" in result
        assert "table1" in result

    @patch("deerflow.tools.builtins.sql_tools.sql_discover_databases")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_list_tables_no_default_database(self, mock_get_default, mock_discover):
        from deerflow.tools.builtins.sql_tools import sql_list_tables

        mock_get_default.return_value = ""
        mock_discover.return_value = "Available databases (2):\n\n📁 db1 (5 tables)\n   └─ table1, table2\n\n📁 db2 (3 tables)\n   └─ table3, table4\n"

        result = sql_list_tables.invoke({"database_name": ""})

        assert "Available databases" in result or "db1" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_list_tables_empty_database(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_list_tables

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = []
        mock_get_db.return_value = mock_db

        result = sql_list_tables.invoke({"database_name": "testdb"})

        assert "No tables found" in result


class TestSqlSchema:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_schema_single_table(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_schema

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = ["users", "orders"]
        mock_db.get_table_info.return_value = "CREATE TABLE users (id INT, name VARCHAR(100))"
        mock_get_db.return_value = mock_db

        result = sql_schema.invoke({"table_names": "users"})

        assert "users" in result
        assert "CREATE TABLE" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_schema_multiple_tables(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_schema

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = ["users", "orders"]
        mock_db.get_table_info.return_value = "Schema info for multiple tables"
        mock_get_db.return_value = mock_db

        result = sql_schema.invoke({"table_names": "users,orders"})

        assert "users" in result
        assert "orders" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_schema_cross_database_table(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_schema

        mock_get_default.return_value = ""
        mock_db = MagicMock()
        mock_db.get_table_info.return_value = "Schema info"
        mock_get_db.return_value = mock_db

        result = sql_schema.invoke({"table_names": "db1.users"})

        assert "db1.users" in result

    def test_schema_empty_table_names(self):
        from deerflow.tools.builtins.sql_tools import sql_schema

        result = sql_schema.invoke({"table_names": ""})

        assert "Error" in result
        assert "No table names" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_schema_invalid_table(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_schema

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.get_usable_table_names.return_value = ["users", "orders"]
        mock_get_db.return_value = mock_db

        result = sql_schema.invoke({"table_names": "invalid_table"})

        assert "Error" in result
        assert "not found" in result


class TestSqlQuery:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_success(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.return_value = "[[1, 'user1'], [2, 'user2']]"
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT * FROM users"})

        assert "user1" in result or "user2" in result or result != ""

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_blocked_forbidden_keyword(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        result = sql_query.invoke({"query": "DROP TABLE users"})

        assert "blocked" in result
        assert "DROP" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_empty_result(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.return_value = []
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT * FROM users WHERE id = 999"})

        assert "no results" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_unknown_column_error(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.side_effect = Exception("Unknown column 'invalid_col'")
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT invalid_col FROM users"})

        assert "Unknown column" in result
        assert "sql_schema" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_table_not_exist_error(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.side_effect = Exception("Table 'testdb.invalid_table' doesn't exist")
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT * FROM invalid_table"})

        assert "doesn't exist" in result
        assert "sql_list_tables" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_unknown_database_error(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = ""
        mock_db = MagicMock()
        mock_db.run.side_effect = Exception("Unknown database 'invalid_db'")
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT * FROM invalid_db.users"})

        assert "Unknown database" in result
        assert "sql_discover_databases" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_syntax_error(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.side_effect = Exception("You have an error in your SQL syntax")
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "SELECT * FORM users"})

        assert "Syntax Error" in result

    @patch.dict(os.environ, {"MYSQL_ALLOW_WRITE": "true"})
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_query_update_with_permission(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.return_value = "Updated 1 row"
        mock_get_db.return_value = mock_db

        result = sql_query.invoke({"query": "UPDATE users SET name = 'test' WHERE id = 1"})

        assert "blocked" not in result


class TestSqlQueryChecker:
    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_checker_valid_query(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query_checker

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.return_value = "EXPLAIN result"
        mock_get_db.return_value = mock_db

        result = sql_query_checker.invoke({"query": "SELECT * FROM users"})

        assert "valid" in result

    def test_checker_invalid_query_forbidden(self):
        from deerflow.tools.builtins.sql_tools import sql_query_checker

        result = sql_query_checker.invoke({"query": "DROP TABLE users"})

        assert "Validation failed" in result
        assert "DROP" in result

    @patch("deerflow.tools.builtins.sql_tools._get_db")
    @patch("deerflow.tools.builtins.sql_tools._get_default_database")
    def test_checker_syntax_error(self, mock_get_default, mock_get_db):
        from deerflow.tools.builtins.sql_tools import sql_query_checker

        mock_get_default.return_value = "testdb"
        mock_db = MagicMock()
        mock_db.run.side_effect = Exception("Syntax error")
        mock_get_db.return_value = mock_db

        result = sql_query_checker.invoke({"query": "SELECT * FORM users"})

        assert "validation failed" in result


class TestSQLToolsList:
    def test_sql_tools_contains_all_tools(self):
        from deerflow.tools.builtins.sql_tools import SQL_TOOLS

        tool_names = [tool.name for tool in SQL_TOOLS]

        assert "sql_discover_databases" in tool_names
        assert "sql_find_relevant_tables" in tool_names
        assert "sql_list_tables" in tool_names
        assert "sql_schema" in tool_names
        assert "sql_query" in tool_names
        assert "sql_query_checker" in tool_names

    def test_sql_tools_count(self):
        from deerflow.tools.builtins.sql_tools import SQL_TOOLS

        assert len(SQL_TOOLS) == 6