from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deerflow.runtime.tenant_context import TenantContext, resolve_runtime_tenant_context
from deerflow.tools.builtins.tenant_datasource import TenantDataSource, TenantDataSourceError, build_database_code


TENANT_DB = "carbon_client_efficiency_20251231184555_6"


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        context={
            "saas_user_id": "saas-user-1",
            "tenant_id": "tenant-1",
            "tenant_code": "20251231184555_6",
            "tenant_name": "纳泽演示",
            "system_code": "efficiency",
        }
    )


def _datasource() -> TenantDataSource:
    return TenantDataSource(
        code=TENANT_DB,
        host="127.0.0.1",
        port=3306,
        database=TENANT_DB,
        username="readonly",
        password="secret",
        driver_class="com.mysql.cj.jdbc.Driver",
        allowed_databases=(TENANT_DB,),
    )


def test_runtime_tenant_context_resolves_from_tool_context():
    ctx = resolve_runtime_tenant_context(_runtime())

    assert ctx.user_id == "saas-user-1"
    assert ctx.tenant_id == "tenant-1"
    assert ctx.tenant_code == "20251231184555_6"
    assert ctx.tenant_name == "纳泽演示"
    assert ctx.system_code == "efficiency"


def test_build_database_code_uses_system_and_tenant_code():
    ctx = TenantContext(
        user_id="saas-user-1",
        tenant_id="tenant-1",
        tenant_code="20251231184555_6",
        tenant_name="纳泽演示",
        system_code="efficiency",
    )

    assert build_database_code(ctx) == TENANT_DB


def test_build_database_code_rejects_unsafe_identifiers():
    ctx = TenantContext(
        user_id="saas-user-1",
        tenant_id="tenant-1",
        tenant_code="20251231184555_6;DROP",
        tenant_name=None,
        system_code="efficiency",
    )

    with pytest.raises(TenantDataSourceError):
        build_database_code(ctx)


def test_get_db_without_tenant_context_uses_local_mysql(monkeypatch):
    from deerflow.tools.builtins import sql_tools

    captured = {}

    def fake_from_uri(uri: str, sample_rows_in_table_info: int = 3):
        captured["uri"] = uri
        captured["sample_rows_in_table_info"] = sample_rows_in_table_info
        return MagicMock()

    monkeypatch.setenv("MYSQL_HOST", "localhost")
    monkeypatch.setenv("MYSQL_PORT", "3306")
    monkeypatch.setenv("MYSQL_USER", "local_user")
    monkeypatch.setenv("MYSQL_PASSWORD", "local_password")
    monkeypatch.setenv("MYSQL_DATABASE", "local_db")
    monkeypatch.setattr(sql_tools.SQLDatabase, "from_uri", fake_from_uri)

    sql_tools._get_db(runtime=SimpleNamespace(context={}))

    assert captured["uri"] == "mysql+mysqlconnector://local_user:local_password@localhost:3306/local_db"


def test_sql_show_databases_saas_mode_only_returns_allowed_database(monkeypatch):
    from deerflow.tools.builtins import sql_tools

    monkeypatch.setattr(sql_tools, "resolve_tenant_datasource", lambda ctx: _datasource())

    result = sql_tools.sql_show_databases.func(runtime=_runtime())

    assert TENANT_DB in result
    assert "carbon_client_efficiency_other" not in result


def test_validate_query_databases_allows_current_tenant_database():
    from deerflow.tools.builtins.sql_tools import _validate_query_databases

    ok, error = _validate_query_databases(f"SELECT * FROM {TENANT_DB}.iot_project", _datasource())

    assert ok is True
    assert error == ""


def test_validate_query_databases_blocks_other_tenant_database():
    from deerflow.tools.builtins.sql_tools import _validate_query_databases

    ok, error = _validate_query_databases("SELECT * FROM carbon_client_efficiency_other.iot_project", _datasource())

    assert ok is False
    assert "not allowed" in error


def test_validate_table_databases_blocks_other_tenant_schema():
    from deerflow.tools.builtins.sql_tools import _validate_table_databases

    ok, error = _validate_table_databases(["carbon_client_efficiency_other.iot_project"], _datasource())

    assert ok is False
    assert "not allowed" in error


def test_saas_schema_blocks_other_tenant_database(monkeypatch):
    from deerflow.tools.builtins import sql_tools

    monkeypatch.setattr(sql_tools, "resolve_tenant_datasource", lambda ctx: _datasource())

    result = sql_tools.sql_schema.func("carbon_client_efficiency_other.iot_project", runtime=_runtime())

    assert result.startswith("Error getting schema:")
    assert "not allowed" in result


def test_saas_query_blocks_write_operations():
    from deerflow.tools.builtins import sql_tools

    result = sql_tools.sql_query.func("DELETE FROM iot_project", runtime=_runtime())

    assert result.startswith("Query blocked:")
    assert "DELETE" in result


def test_saas_query_ignores_mysql_allow_write(monkeypatch):
    from deerflow.tools.builtins import sql_tools

    monkeypatch.setenv("MYSQL_ALLOW_WRITE", "true")

    result = sql_tools.sql_query.func("UPDATE iot_project SET name = 'x'", runtime=_runtime())

    assert result.startswith("Query blocked:")


def test_saas_query_blocks_outfile():
    from deerflow.tools.builtins import sql_tools

    result = sql_tools.sql_query.func("SELECT * FROM iot_project INTO OUTFILE '/tmp/x.csv'", runtime=_runtime())

    assert result.startswith("Query blocked:")
    assert "OUTFILE" in result


def test_saas_query_adds_default_limit_and_uses_tenant_database(monkeypatch):
    from deerflow.tools.builtins import sql_tools

    db = MagicMock()
    db.run.return_value = "[(1,)]"
    captured = {}

    def fake_from_uri(uri: str, sample_rows_in_table_info: int = 3):
        captured["uri"] = uri
        return db

    monkeypatch.setattr(sql_tools, "resolve_tenant_datasource", lambda ctx: _datasource())
    monkeypatch.setattr(sql_tools.SQLDatabase, "from_uri", fake_from_uri)

    result = sql_tools.sql_query.func("SELECT * FROM iot_project", runtime=_runtime())

    assert result == "[(1,)]"
    assert captured["uri"] == f"mysql+mysqlconnector://readonly:secret@127.0.0.1:3306/{TENANT_DB}"
    db.run.assert_called_once_with("SELECT * FROM iot_project LIMIT 100")


def test_sql_tools_hide_runtime_from_model_schema():
    from deerflow.tools.builtins.sql_tools import sql_query, sql_show_databases

    assert "runtime" not in sql_query.args
    assert "runtime" not in sql_show_databases.args
