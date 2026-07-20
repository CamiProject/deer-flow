# SaaS Agent Data Scope, Ontology and Action Changelog

## 2026-07-11 Acceptance Hardening

- Blocked signed SaaS requests from selecting Lead/custom Agent profiles.
- Added allow/deny/error audit coverage for SQL discovery, checker, executor, and precheck
  rejection; schema errors no longer reveal forbidden physical table names.
- Rejected MySQL user/session variables, session-state functions, optimizer hints, and
  CTE policy-name shadowing.
- Filtered role-restricted OAG property/link metadata and capped Semantic `IN` filters.
- Exposed Action tools only when trusted semantic coverage resolves an authorized Action.
- Bound Action execution-status reads to system, scope hash, and permission version.
- Added domain API result-field projection, response bounds, recursive secret filtering,
  and network-path SSRF rejection.
- Removed Action Worker credentials from every non-Worker local/Compose service,
  including the optional sandbox provisioner.

## 2026-07-10

Implemented architecture plan sections 1-8.8. Section 9 evaluation, attribution,
and controlled evolution remains out of scope.

### A Phase

- Added short-lived signed SaaS Authorization Context verification and canonical scope hash.
- Protected trusted identity/scope fields from request-body or config forgery.
- Added tenant/system/principal/scope/version thread binding.
- Added versioned SQL table/field policy and MySQL AST enforcement with `sqlglot`.
- Added scoped JOIN/CTE/subquery/UNION rewriting with bind parameters.
- Added schema/discovery restrictions, dangerous SELECT rejection, result limits, and SQL audit.
- Disabled SaaS fallback to local `MYSQL_*` configuration.

### B Phase

- Added independent Semantic API and metadata database.
- Added versioned Ontology objects, properties, links, metrics, Actions, policy, and lineage.
- Added authorized OAG, object queries, multi-metric queries, and `scope_ref` IAM resolution.
- Added ten restricted Semantic tools and a dedicated `/saas-query/*` run profile.
- Added semantic-first routing, role/scoped SQL fallback, shadow hashes, and break-glass controls.
- Added durable Action proposal/execution/state-transition storage, approval JWTs, isolated Worker,
  IAM revalidation, domain API execution, idempotency, optimistic concurrency, explicit
  compensation, and compensation lease recovery.
- Added internal-only Semantic API and Action Worker services to local and Compose startup.

### Security Follow-ups Included During Acceptance

- Rejected CTE aliases that shadow SQL policy table names.
- Allowed `COUNT(*)` without re-enabling projection `SELECT *` on field-restricted tables.
- Rejected ambiguous unqualified fields unless every candidate table policy allows them.
- Rejected `scope_ref` resolver responses that escalate to `tenant_all`.
- Added Action approval JWT issuer validation.
- Sanitized uncontrolled domain API and Worker exception details.

### Default Published Business Slice

- Objects: `Site`, `Project`
- Link: `Project.site`
- Metrics: `site.count`, `project.count`
- Action: `site.update_display_name`

Additional business mappings must be published from verified DDL, business definitions,
units, time semantics, and authorization relationships. They must not be inferred from table names.
