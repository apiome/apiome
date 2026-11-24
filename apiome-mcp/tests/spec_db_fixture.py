"""Seed data for the DBP-1.22 (#7205) database tests: a spec of any size, and a small catalog.

:func:`seed_catalog` writes two tenants' projects and revisions covering every listing rule
(public and private, drafts, disabled and deleted rows, tags, embeddings).

:func:`seed_spec` writes one tenant, project and published revision with ``operations``
operations: two per path (``GET`` and ``POST``), each with a description, two shared parameters,
two responses with content rows, and a request body with two content types on the ``POST``; one
class with three properties (backed by three project properties) per five operations; two
security schemes and two servers. Everything is written with ``generate_series``, so a
1,000-operation spec takes well under a second.

Ids derive from ``label`` (``md5``), so two seeds with different labels never collide and a test
can name a row without reading it back.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

__all__ = ["EMBEDDING_DIMENSIONS", "cluster_vector", "fixture_id", "seed_catalog", "seed_spec"]


def fixture_id(label: str, kind: str, n: int = 0) -> UUID:
    """The id :func:`seed_spec` gives a row: ``md5('<label>:<kind>:<n>')`` as a UUID.

    Args:
        label: The seed's label.
        kind: ``tenant``, ``user``, ``project``, ``version``, ``class``, ``path`` or ``op``.
        n: The row's ordinal within its kind.

    Returns:
        The row id.
    """
    return UUID(hashlib.md5(f"{label}:{kind}:{n}".encode(), usedforsecurity=False).hexdigest())


def _id(label: str, kind: str, expr: str = "n") -> str:
    """SQL for the id of row ``expr`` of ``kind`` (the SQL twin of :func:`fixture_id`)."""
    return f"md5('{label}:{kind}:' || ({expr}))::uuid"


def seed_spec(
    conn: Any,
    *,
    label: str,
    operations: int,
    visibility: str = "public",
    published: bool = True,
) -> UUID:
    """Insert a revision with ``operations`` operations and return its id (``versions.id``).

    Args:
        conn: An open psycopg connection (sync); the caller commits or rolls back.
        label: Namespace for the ids and slugs (letters, digits, ``-``).
        operations: Number of operations; an even number, two per path.
        visibility: ``public`` or ``private``.
        published: Whether the revision is published.

    Returns:
        The revision id, ``fixture_id(label, "version")``.
    """
    if operations % 2 or operations < 2:
        raise ValueError("operations must be an even number, at least 2")
    if not label.replace("-", "").isalnum():
        raise ValueError("label must be letters, digits and '-'")
    paths = operations // 2
    classes = max(1, operations // 5)
    tenant, user, project, version = (fixture_id(label, k) for k in ("tenant", "user", "project", "version"))
    op = _id(label, "op")
    path_of_op = _id(label, "path", "n / 2")
    path = _id(label, "path")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.users (id, name, email, password) VALUES (%s, %s, %s, 'x')",
            (user, f"{label} user", f"{label}@apiome.local"),
        )
        cur.execute(
            "INSERT INTO apiome.tenants (id, name, slug) VALUES (%s, %s, %s)", (tenant, f"{label} tenant", f"t-{label}")
        )
        cur.execute(
            "INSERT INTO apiome.projects (id, tenant_id, creator_id, name, slug, description)"
            " VALUES (%s, %s, %s, %s, %s, 'Seeded spec')",
            (project, tenant, user, f"{label} project", f"p-{label}"),
        )
        cur.execute(
            "INSERT INTO apiome.versions (id, project_id, creator_id, version_id, description, published,"
            " visibility, enabled) VALUES (%s, %s, %s, '1.0.0', 'Seeded revision', %s, %s, TRUE)",
            (version, project, user, published, visibility),
        )
        statements = [
            f"""INSERT INTO apiome.classes (id, version_id, name, description, schema)
                SELECT {_id(label, "class")}, %(v)s, 'Model' || lpad(n::text, 5, '0'), 'Model ' || n,
                       '{{"type": "object"}}'::jsonb
                FROM generate_series(0, {classes - 1}) n""",
            f"""INSERT INTO apiome.properties (id, project_id, name, data)
                SELECT {_id(label, "property", "k")}, %(p)s, 'field' || k,
                       jsonb_build_object('type', CASE k WHEN 0 THEN 'string' WHEN 1 THEN 'integer' ELSE 'boolean' END)
                FROM generate_series(0, 2) k""",
            f"""INSERT INTO apiome.class_properties (class_id, property_id, name, description, data)
                SELECT {_id(label, "class")}, {_id(label, "property", "k")}, 'field' || k, 'Field ' || k,
                       jsonb_build_object('type', CASE k WHEN 0 THEN 'string' WHEN 1 THEN 'integer' ELSE 'boolean' END)
                FROM generate_series(0, {classes - 1}) n, generate_series(0, 2) k""",
            f"""INSERT INTO apiome.version_path (id, version_id, pathname, metadata)
                SELECT {path}, %(v)s, '/resources' || lpad(n::text, 5, '0') || '/{{id}}',
                       jsonb_build_object('summary', 'Resource ' || n)
                FROM generate_series(0, {paths - 1}) n""",
            f"""INSERT INTO apiome.path_operation (id, version_path_id, operation)
                SELECT {op}, {path_of_op}, CASE n %% 2 WHEN 0 THEN 'GET' ELSE 'POST' END
                FROM generate_series(0, {operations - 1}) n""",
            f"""INSERT INTO apiome.path_operation_description
                    (path_operation_id, summary, description, operation_id, metadata)
                SELECT {op}, 'Operation ' || n, 'Describes operation ' || n, 'op' || n,
                       jsonb_build_object('tags', jsonb_build_array('tag' || (n %% 7)), 'x-rank', n)
                FROM generate_series(0, {operations - 1}) n""",
            f"""INSERT INTO apiome.shared_path_parameter (id, version_path_id, name, in_location, description, data)
                SELECT {_id(label, "param", "n * 2 + k")}, {path},
                       CASE k WHEN 0 THEN 'id' ELSE 'expand' END, CASE k WHEN 0 THEN 'path' ELSE 'query' END,
                       'Parameter ' || k, jsonb_build_object('type', 'string', 'required', k = 0)
                FROM generate_series(0, {paths - 1}) n, generate_series(0, 1) k""",
            f"""INSERT INTO apiome.path_operation_parameter_link (path_operation_id, shared_path_parameter_id)
                SELECT {op}, {_id(label, "param", "(n / 2) * 2 + k")}
                FROM generate_series(0, {operations - 1}) n, generate_series(0, 1) k""",
            f"""INSERT INTO apiome.shared_path_request_body (id, version_path_id, name, description)
                SELECT {_id(label, "body")}, {path}, 'Body' || n, 'Request body ' || n
                FROM generate_series(0, {paths - 1}) n""",
            f"""INSERT INTO apiome.shared_path_request_body_content
                    (shared_path_request_body_id, media_type, class_id, inline_schema)
                SELECT {_id(label, "body")}, CASE k WHEN 0 THEN 'application/json' ELSE 'application/xml' END,
                       CASE k WHEN 0 THEN {_id(label, "class", f"n %% {classes}")} END,
                       CASE k WHEN 1 THEN '{{"type": "string"}}'::jsonb END
                FROM generate_series(0, {paths - 1}) n, generate_series(0, 1) k
                ORDER BY n, k""",
            f"""INSERT INTO apiome.path_operation_request_body_link (path_operation_id, shared_path_request_body_id)
                SELECT {op}, {_id(label, "body", "n / 2")}
                FROM generate_series(0, {operations - 1}) n WHERE n %% 2 = 1""",
            f"""INSERT INTO apiome.shared_path_response
                    (id, version_path_id, status_code, description, class_id, inline_schema)
                SELECT {_id(label, "response", "n * 2 + k")}, {path}, CASE k WHEN 0 THEN '200' ELSE '404' END,
                       CASE k WHEN 0 THEN 'OK' ELSE 'Not found' END,
                       CASE k WHEN 0 THEN {_id(label, "class", f"n %% {classes}")} END,
                       CASE k WHEN 1 THEN '{{"type": "object"}}'::jsonb END
                FROM generate_series(0, {paths - 1}) n, generate_series(0, 1) k""",
            f"""INSERT INTO apiome.shared_path_response_content
                    (shared_path_response_id, media_type, class_id, inline_schema)
                SELECT {_id(label, "response", "n * 2")}, CASE k WHEN 0 THEN 'application/json' ELSE 'text/csv' END,
                       CASE k WHEN 0 THEN {_id(label, "class", f"n %% {classes}")} END,
                       CASE k WHEN 1 THEN '{{"type": "string"}}'::jsonb END
                FROM generate_series(0, {paths - 1}) n, generate_series(0, 1) k
                ORDER BY n, k""",
            f"""INSERT INTO apiome.path_operation_response_link (path_operation_id, shared_path_response_id)
                SELECT {op}, {_id(label, "response", "(n / 2) * 2 + k")}
                FROM generate_series(0, {operations - 1}) n, generate_series(0, 1) k""",
            """INSERT INTO apiome.version_security_scheme
                   (version_id, scheme_name, scheme_type, in_location, param_name)
               VALUES (%(v)s, 'ApiKeyHeader', 'apiKey', 'header', 'X-Api-Key'),
                      (%(v)s, 'ApiKeyQuery', 'apiKey', 'query', 'api_key')""",
            """INSERT INTO apiome.version_server (version_id, name, url, description, sort_order)
               VALUES (%(v)s, 'Production', 'https://api.example.com', 'Live', 0),
                      (%(v)s, 'Sandbox', 'https://sandbox.example.com', 'Test', 1)""",
        ]
        for statement in statements:
            cur.execute(statement, {"v": version, "p": project})
    return version


#: Embedding dimensions of ``versions.mcp_public_embedding`` (V102).
EMBEDDING_DIMENSIONS = 1536


def cluster_vector(cluster: int, member: int) -> list[float]:
    """A vector near cluster ``cluster``'s axis; ``member`` moves it a little off the axis.

    Members of one cluster are closer to each other than to any other cluster. Every vector also
    has a different component on one shared axis, so no two vectors are at the same distance from
    a query vector: nearest-neighbour order has no ties, and an approximate index and an exact
    scan must agree on it.

    Args:
        cluster: Which of the first axes the vector points along (below 50).
        member: Ordinal within the cluster (0 is closest to the axis).

    Returns:
        ``EMBEDDING_DIMENSIONS`` floats.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[cluster] = 1.0
    vector[50] = 0.01 * (1 + cluster * 16 + member)
    vector[100 + member] = 0.02 * (member + 1)
    return vector


def seed_catalog(conn: Any, *, label: str, projects_per_tenant: int = 12) -> dict[str, Any]:
    """Insert a small catalog that exercises every listing rule, and return its ids.

    Two tenants, ``projects_per_tenant`` projects each, six revisions per project:

    ==========  =========  ===========  ========================================
    version     published  visibility   notes
    ==========  =========  ===========  ========================================
    ``1.0.0``   yes        public       tags ``stable`` and one per project
    ``1.1.0``   yes        public       an embedding (cluster by project)
    ``2.0.0``   yes        private      tag ``beta``
    ``2.1.0``   yes        private
    ``3.0.0``   no         public       a draft: never listed
    ``0.9.0``   yes        public       disabled: never listed
    ==========  =========  ===========  ========================================

    Every third project is disabled or soft-deleted (alternating), so its revisions are not
    listed. Timestamps are spread over a year and repeat (ties), so order depends on the id
    tiebreak too.

    Args:
        conn: An open psycopg connection (sync); the caller commits.
        label: Namespace for ids and slugs (letters, digits, ``-``).
        projects_per_tenant: Projects in each of the two tenants.

    Returns:
        ``{"tenants": [a, b], "projects": {tenant: [ids]}, "user": id}``.
    """
    if not label.replace("-", "").isalnum():
        raise ValueError("label must be letters, digits and '-'")
    user = fixture_id(label, "user")
    tenants = [fixture_id(label, "tenant", n) for n in range(2)]
    versions = ("1.0.0", "1.1.0", "2.0.0", "2.1.0", "3.0.0", "0.9.0")
    projects: dict[Any, list[Any]] = {t: [] for t in tenants}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.users (id, name, email, password) VALUES (%s, %s, %s, 'x')",
            (user, f"{label} user", f"{label}@apiome.local"),
        )
        for t, tenant in enumerate(tenants):
            cur.execute(
                "INSERT INTO apiome.tenants (id, name, slug) VALUES (%s, %s, %s)",
                (tenant, f"{label} tenant {t}", f"t-{label}-{t}"),
            )
            for n in range(projects_per_tenant):
                ordinal = t * projects_per_tenant + n
                project = fixture_id(label, "project", ordinal)
                projects[tenant].append(project)
                cur.execute(
                    "INSERT INTO apiome.projects (id, tenant_id, creator_id, name, slug, enabled, deleted_at,"
                    " updated_at) VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END,"
                    " timestamptz '2026-01-01' + make_interval(days => %s))",
                    (
                        project,
                        tenant,
                        user,
                        f"Catalog {label} {['payments', 'orders', 'billing'][ordinal % 3]} {ordinal}",
                        f"p-{label}-{ordinal}",
                        ordinal % 6 != 2,
                        ordinal % 6 == 5,
                        (ordinal * 37) % 300,
                    ),
                )
                for k, version in enumerate(versions):
                    vid = fixture_id(label, "version", ordinal * 10 + k)
                    cur.execute(
                        "INSERT INTO apiome.versions (id, project_id, creator_id, version_id, description,"
                        " published, visibility, enabled, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,"
                        " timestamptz '2026-01-01' + make_interval(days => %s))",
                        (
                            vid,
                            project,
                            user,
                            version,
                            f"Revision {version} of {label} project {ordinal}",
                            k != 4,
                            "private" if k in (2, 3) else "public",
                            k != 5,
                            # Repeats across projects: ties in the listing order.
                            ((ordinal % 5) * 61 + k * 13) % 330,
                        ),
                    )
                    tags = {0: ["stable", f"rel-{ordinal % 4}"], 2: ["beta"]}.get(k, [])
                    for tag in tags:
                        cur.execute(
                            "INSERT INTO apiome.version_tags (project_id, version_id, name, updated_at) VALUES"
                            " (%s, %s, %s, timestamptz '2026-01-01' + make_interval(days => %s))",
                            (project, vid, tag, (ordinal * 53 + len(tag)) % 340),
                        )
                    if k == 1:
                        cur.execute(
                            "UPDATE apiome.versions SET mcp_public_embedding = %s::vector WHERE id = %s",
                            (str(cluster_vector(ordinal % 4, ordinal // 4)), vid),
                        )
    return {"tenants": tenants, "projects": projects, "user": user}
