from __future__ import annotations

import pytest

from deerflow.runtime.authorization_context import AuthorizationContext
from deerflow.semantic.sql_scope import SqlScopeError, SqlScopePolicyRegistry, guard_sql_query


@pytest.fixture()
def authorization():
    return AuthorizationContext.from_mapping(
        {
            "principal_id": "user-1",
            "tenant_id": "tenant-1",
            "tenant_code": "tenant-code",
            "system_code": "efficiency",
            "role_codes": ["site_admin"],
            "scope_mode": "resource_set",
            "allowed_site_ids": ["site-1", "site-2"],
            "allowed_project_ids": ["project-1"],
            "permission_version": "1",
        }
    )


@pytest.fixture()
def registry():
    return SqlScopePolicyRegistry.from_mapping(
        {
            "version": "test-1",
            "tables": {
                "iot_site": {
                    "access": "scoped",
                    "scope_dimension": "site",
                    "scope_column": "id",
                    "allowed_fields": ["id", "name"],
                },
                "iot_project": {
                    "access": "scoped",
                    "scope_dimension": "site",
                    "scope_column": "site_id",
                    "allowed_fields": ["id", "name", "site_id"],
                },
                "iot_device": {
                    "access": "scoped",
                    "scope_dimension": "project",
                    "scope_column": "project_id",
                    "hidden_fields": ["secret"],
                    "masked_fields": ["serial_no"],
                    "aggregate_only_fields": ["reading"],
                },
                "iot_dict_value": {"access": "reference"},
                "iot_api_auth": {"access": "forbidden"},
            },
        }
    )


def test_guard_scopes_joined_tables_and_binds_resources(authorization, registry):
    guarded = guard_sql_query(
        "SELECT p.id, s.name FROM iot_project p JOIN iot_site s ON s.id = p.site_id",
        authorization=authorization,
        allowed_databases=("tenant_db",),
        registry=registry,
    )

    assert "scope_0_0" in guarded.sql
    assert "scope_1_0" in guarded.sql
    assert set(guarded.parameters.values()) == {"site-1", "site-2"}
    assert guarded.scope_predicates_applied == 2
    assert {"id", "name", "site_id"}.issubset(set(guarded.referenced_fields))
    assert guarded.referenced_tables == ("iot_project", "iot_site")
    assert guarded.sql.endswith("LIMIT 100")


def test_guard_scopes_cte_and_union_branches(authorization, registry):
    guarded = guard_sql_query(
        "WITH p AS (SELECT id FROM iot_project) SELECT id FROM p UNION ALL SELECT id FROM iot_site",
        authorization=authorization,
        allowed_databases=("tenant_db",),
        registry=registry,
    )

    assert guarded.referenced_tables == ("iot_project", "iot_site")
    assert len(guarded.parameters) == 4


def test_guard_rejects_cte_names_that_shadow_policy_tables(authorization, registry):
    with pytest.raises(SqlScopeError, match="shadows"):
        guard_sql_query(
            "WITH iot_site AS (SELECT id FROM tenant_db.iot_site) SELECT p.id FROM iot_project p JOIN iot_site s ON s.id = p.site_id",
            authorization=authorization,
            allowed_databases=("tenant_db",),
            registry=registry,
        )


def test_guard_allows_count_star_for_field_restricted_table(authorization, registry):
    guarded = guard_sql_query(
        "SELECT COUNT(*) AS total FROM iot_site",
        authorization=authorization,
        allowed_databases=("tenant_db",),
        registry=registry,
    )

    assert "COUNT(*)" in guarded.sql
    assert guarded.scope_predicates_applied == 1


def test_guard_rejects_unqualified_field_not_allowed_by_every_candidate(authorization):
    registry = SqlScopePolicyRegistry.from_mapping(
        {
            "version": "ambiguous-1",
            "tables": {
                "table_a": {"access": "reference", "allowed_fields": ["id"]},
                "table_b": {"access": "reference", "allowed_fields": ["id", "secret"]},
            },
        }
    )

    with pytest.raises(SqlScopeError, match="not allowed"):
        guard_sql_query(
            "SELECT secret FROM table_a a JOIN table_b b ON a.id = b.id",
            authorization=authorization,
            allowed_databases=("tenant_db",),
            registry=registry,
        )


def test_guard_rejects_unknown_sensitive_and_cross_database_tables(authorization, registry):
    with pytest.raises(SqlScopeError, match="not allowed"):
        guard_sql_query("SELECT * FROM unknown", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match="not allowed"):
        guard_sql_query("SELECT id FROM iot_api_auth", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match="Database"):
        guard_sql_query("SELECT id FROM other.iot_site", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)


def test_guard_rejects_multiple_statements_and_writes(authorization, registry):
    with pytest.raises(SqlScopeError, match="Exactly one"):
        guard_sql_query("SELECT id FROM iot_site; SELECT id FROM iot_site", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match="SELECT"):
        guard_sql_query("DELETE FROM iot_site", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)


def test_guard_rejects_hidden_field_and_star(authorization, registry):
    with pytest.raises(SqlScopeError, match="hidden"):
        guard_sql_query("SELECT secret FROM iot_device", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match=r"SELECT \*"):
        guard_sql_query("SELECT * FROM iot_device", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match="masked"):
        guard_sql_query("SELECT serial_no FROM iot_device", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)
    with pytest.raises(SqlScopeError, match="aggregate-only"):
        guard_sql_query("SELECT reading FROM iot_device", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)

    guarded = guard_sql_query(
        "SELECT SUM(reading) AS total FROM iot_device",
        authorization=authorization,
        allowed_databases=("tenant_db",),
        registry=registry,
    )
    assert "SUM(reading)" in guarded.sql


def test_guard_clamps_limits_and_rejects_unbounded_offsets(authorization, registry):
    guarded = guard_sql_query(
        "SELECT id FROM iot_site LIMIT 999999",
        authorization=authorization,
        allowed_databases=("tenant_db",),
        registry=registry,
        limit=100,
    )

    assert guarded.sql.endswith("LIMIT 100")

    with pytest.raises(SqlScopeError, match="OFFSET"):
        guard_sql_query(
            "SELECT id FROM iot_site LIMIT 100 OFFSET 999999",
            authorization=authorization,
            allowed_databases=("tenant_db",),
            registry=registry,
        )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT SLEEP(10) FROM iot_site",
        "SELECT LOAD_FILE('/etc/passwd') FROM iot_site",
        "SELECT id FROM iot_site FOR UPDATE",
        "SELECT id FROM iot_site INTO OUTFILE '/tmp/export.csv'",
        "SELECT @@version FROM iot_site",
        "SELECT CURRENT_USER() FROM iot_site",
        "SELECT DATABASE() FROM iot_site",
        "SELECT VERSION() FROM iot_site",
        "SELECT CONNECTION_ID() FROM iot_site",
        "SELECT @previous_value FROM iot_site",
        "SELECT @captured := name FROM iot_site",
        "SELECT LAST_INSERT_ID() FROM iot_site",
        "SELECT FOUND_ROWS() FROM iot_site",
        "SELECT ROW_COUNT() FROM iot_site",
        "SELECT /*+ SET_VAR(max_execution_time=0) */ id FROM iot_site",
    ],
)
def test_guard_rejects_dangerous_select_constructs(authorization, registry, query):
    with pytest.raises(SqlScopeError):
        guard_sql_query(
            query,
            authorization=authorization,
            allowed_databases=("tenant_db",),
            registry=registry,
        )


def test_tenant_all_keeps_policy_but_does_not_add_resource_predicates(registry):
    authorization = AuthorizationContext.from_mapping(
        {
            "principal_id": "admin",
            "tenant_id": "tenant-1",
            "tenant_code": "tenant-code",
            "system_code": "efficiency",
            "role_codes": ["tenant_admin"],
            "scope_mode": "tenant_all",
            "allowed_site_ids": [],
            "allowed_project_ids": [],
            "permission_version": "1",
        }
    )

    guarded = guard_sql_query("SELECT id FROM iot_site", authorization=authorization, allowed_databases=("tenant_db",), registry=registry)

    assert guarded.parameters == {}
    assert "scope_" not in guarded.sql
