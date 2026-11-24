"""Benchmark the Pact matrix on a scratch database — PFX-1.6 (#6919).

Acceptance: a matrix query's p95 stays under 200 ms with 10,000 pact versions. This script seeds
that many into a **scratch** database, times the queries a Pact client really sends, prints the
percentiles, and removes what it seeded.

It seeds one workspace with 5 consumers and 5 providers; each consumer has 400 versions and every
one of them publishes a different pact for every provider (10,000 pact versions, 10,000
publications); every pact is verified by two provider versions (20,000 results); one version of
each application is deployed to ``production``.

Run it against a database that has the migrations applied and nothing you care about::

    createdb pfx_bench
    (cd ../apiome-db && node --import tsx src/cli.ts --database-url "postgresql:///pfx_bench" \
        migrate --scripts-dir scripts)
    DATABASE_URL="postgresql:///pfx_bench" PYTHONPATH=src python scripts/bench_pact_matrix.py

Exits ``1`` when a query's p95 is over the budget. Each measured call is the whole of what a
request does after authentication: parse, resolve the selectors, read the rows, decide the
verdict, read the version details.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid
from typing import Any, Callable, Dict, List

from app.database import Database
from app.pact_matrix import deployment_verdict, parse_can_i_deploy_query, parse_matrix_query
from app.pact_matrix_store import query_matrix, read_version_details

BUDGET_MS = 200.0

_SEED = """
WITH roles AS (
    SELECT role, n FROM (VALUES ('consumer'), ('provider')) r(role), generate_series(1, %(apps)s) n
), apps AS (
    INSERT INTO apiome.pacticipant (tenant_id, slug, name, main_branch)
    SELECT %(tenant)s::uuid, role || '-' || n, initcap(role) || ' ' || n, 'main' FROM roles
    RETURNING id, slug
), versions AS (
    INSERT INTO apiome.pacticipant_version (pacticipant_id, number)
    SELECT a.id, 'v' || g FROM apps a, generate_series(1, %(versions)s) g
    RETURNING id, pacticipant_id, number
), numbered AS (
    SELECT v.id, v.pacticipant_id, substr(v.number, 2)::int AS n, a.slug
    FROM versions v JOIN apps a ON a.id = v.pacticipant_id
), pacts AS (
    INSERT INTO apiome.pact_version (tenant_id, consumer_id, provider_id, sha, content, interaction_count)
    SELECT %(tenant)s::uuid, cv.pacticipant_id, p.id,
           encode(sha256((cv.id::text || p.id::text)::bytea), 'hex'), '{}'::jsonb, 1
    FROM numbered cv JOIN apps p ON p.slug LIKE 'provider-%%'
    WHERE cv.slug LIKE 'consumer-%%'
    RETURNING id, consumer_id, provider_id, sha
), publications AS (
    INSERT INTO apiome.pact_publication (consumer_id, provider_id, consumer_version_id, pact_version_id)
    SELECT pv.consumer_id, pv.provider_id, cv.id, pv.id
    FROM pacts pv
    JOIN numbered cv ON cv.pacticipant_id = pv.consumer_id
     AND pv.sha = encode(sha256((cv.id::text || pv.provider_id::text)::bytea), 'hex')
    RETURNING consumer_version_id, pact_version_id, consumer_id, provider_id
), results AS (
    INSERT INTO apiome.verification_result
        (tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number, success)
    SELECT %(tenant)s::uuid, pub.consumer_id, pub.provider_id, pub.pact_version_id, rv.id,
           1 + (cv.n - rv.n), (cv.n + rv.n) %% 17 <> 0
    FROM publications pub
    JOIN numbered cv ON cv.id = pub.consumer_version_id
    JOIN numbered rv ON rv.pacticipant_id = pub.provider_id AND rv.n IN (cv.n, cv.n - 1)
    RETURNING 1
), branches AS (
    INSERT INTO apiome.pacticipant_branch (pacticipant_id, name, head_version_id)
    SELECT v.pacticipant_id, 'main', v.id FROM numbered v WHERE v.n = %(versions)s
    RETURNING id, pacticipant_id
), branch_versions AS (
    INSERT INTO apiome.pacticipant_branch_version (branch_id, pacticipant_id, version_id)
    SELECT b.id, b.pacticipant_id, v.id FROM branches b JOIN numbered v ON v.pacticipant_id = b.pacticipant_id
    RETURNING 1
), environment AS (
    INSERT INTO apiome.pact_environment (tenant_id, name, display_name, production)
    VALUES (%(tenant)s::uuid, 'production', 'Production', TRUE)
    RETURNING id
), deployed AS (
    INSERT INTO apiome.deployed_version (tenant_id, pacticipant_id, version_id, environment_id)
    SELECT %(tenant)s::uuid, v.pacticipant_id, v.id, e.id FROM numbered v, environment e WHERE v.n = %(versions)s - 1
    RETURNING 1
)
SELECT (SELECT count(*) FROM pacts) AS pact_versions,
       (SELECT count(*) FROM publications) AS publications,
       (SELECT count(*) FROM results) AS results,
       (SELECT count(*) FROM branch_versions) AS branch_versions,
       (SELECT count(*) FROM deployed) AS deployed
"""


def _seed(db: Database, apps: int, versions: int) -> str:
    """Create a workspace with ``apps`` consumers and providers of ``versions`` versions each."""
    slug = f"pfx-bench-{uuid.uuid4().hex[:10]}"
    tenant = db.execute_query(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id", (slug, slug)
    )[0]["id"]
    counts = db.execute_query(_SEED, {"tenant": tenant, "apps": apps, "versions": versions})[0]
    for table in ("pact_version", "pact_publication", "verification_result", "pacticipant_version"):
        db._execute_write(f"ANALYZE apiome.{table}")
    print("seeded:", ", ".join(f"{value} {key}" for key, value in dict(counts).items()))
    return tenant


def _matrix(db: Database, tenant: str, parse: Callable[[str], Any], query: str) -> Dict[str, Any]:
    """Everything a matrix request does after authentication."""
    selectors, options = parse(query)
    result = query_matrix(db, tenant, selectors, options)
    verdict = deployment_verdict(result)
    rows = list(result.considered_rows) + list(result.ignored_rows)
    read_version_details(db, [r.consumer_version_id for r in rows] + [r.provider_version_id for r in rows])
    return {"rows": len(rows), "deployable": verdict.deployable}


def main() -> int:
    """Seed, measure, report, clean up. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apps", type=int, default=5, help="consumers, and providers (default 5)")
    parser.add_argument("--versions", type=int, default=400, help="versions per application (default 400)")
    parser.add_argument("--runs", type=int, default=200, help="measured calls per query (default 200)")
    parser.add_argument("--keep", action="store_true", help="leave the seeded workspace in place")
    args = parser.parse_args()

    db = Database()
    tenant = _seed(db, args.apps, args.versions)
    last = args.versions
    queries = {
        "can-i-deploy consumer to environment": (
            parse_matrix_query,
            f"q[][pacticipant]=consumer-1&q[][version]=v{last}&latestby=cvpv&environment=production",
        ),
        "can-i-deploy provider to environment": (
            parse_matrix_query,
            f"q[][pacticipant]=provider-1&q[][version]=v{last}&latestby=cvpv&environment=production",
        ),
        "can-i-deploy to latest (no environment)": (
            parse_matrix_query,
            f"q[][pacticipant]=consumer-1&q[][version]=v{last}&latestby=cvp&latest=true",
        ),
        "GET /can-i-deploy": (
            parse_can_i_deploy_query,
            f"pacticipant=consumer-2&version=v{last - 1}&toEnvironment=production",
        ),
        "two versions": (
            parse_matrix_query,
            f"q[][pacticipant]=consumer-1&q[][version]=v{last}&q[][pacticipant]=provider-1&q[][version]=v{last}"
            "&latestby=cvpv",
        ),
        "pair history (name only, limit 100)": (
            parse_matrix_query,
            "q[][pacticipant]=consumer-1&q[][pacticipant]=provider-1&latestby=cvpv",
        ),
        "one pacticipant, every row (limit 100)": (parse_matrix_query, "q[][pacticipant]=provider-1"),
    }
    worst = 0.0
    try:
        print(f"{'query':45} {'rows':>5} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8}")
        for label, (parse, query) in queries.items():
            answer = _matrix(db, tenant, parse, query)  # warm: prepares the statements
            timings: List[float] = []
            for _ in range(args.runs):
                start = time.perf_counter()
                _matrix(db, tenant, parse, query)
                timings.append((time.perf_counter() - start) * 1000)
            p95 = statistics.quantiles(timings, n=20)[18]
            worst = max(worst, p95)
            print(f"{label:45} {answer['rows']:>5} {statistics.median(timings):>8.2f} {p95:>8.2f} {max(timings):>8.2f}")
    finally:
        if not args.keep:
            db._execute_write("DELETE FROM apiome.tenants WHERE id = %s::uuid", (tenant,))
    print(f"worst p95 {worst:.2f} ms; budget {BUDGET_MS:.0f} ms")
    return 0 if worst < BUDGET_MS else 1


if __name__ == "__main__":
    sys.exit(main())
