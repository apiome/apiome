"""The blast-radius query against a live Postgres — CDG-3.3 (#5968).

The golden fixture: a ``petstore`` project whose published version ``1.0.0`` exposes
``GET /pets/{petId}``, with

* three consumers whose current contracts declare it (at the operation, at a field below it, and
  through a component-schema field) and one that only calls ``POST /pets``;
* a fifth consumer that declared ``depends_on`` the first one (the transitive dependent);
* provider verification runs: the latest on two targets exercised the operation, an older run and
  a run of another operation don't count;
* a deploy-gate evaluation citing one of those runs; one agent-toolset tool for the operation (and
  one for another); a fixture pack and a scenario; an SDK subscription; and a consumer pinned to a
  deprecated version.

Acceptance: a change to ``GET /pets/{id}`` returns 3 direct consumers, 1 transitive, 2 verification
runs and 1 agent toolset tool; the direct set equals CTG-4.2's for the same classified change; a
pointer nobody consumes returns empty sections with ``evidence_checked: true``; P95 under 300 ms on
a 10k-edge tenant.

Runs in one always-rolled-back transaction (the ``tx`` fixture of ``test_catalog_graph_db``).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

import pytest

from app import consumer_contract_store
from app.blast_radius import BlastRadiusRequest, blast_radius
from app.change_taxonomy import ClassifiedChange, ClassifiedDiff
from app.consumer_contract import ConsumerContractSurface, contract_pointers
from app.consumer_impact_service import consumer_impact_for_diff
from app.declared_dependencies import DeclaredReference, replace_declared
from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db

P95_BUDGET_MS = 300.0
LATENCY_SAMPLES = 20

_OP = "/paths/~1pets~1{petId}/get"
_PET = "/components/schemas/Pet"


def _surface(*operations: Dict[str, Any]) -> Dict[str, Any]:
    return {"operations": list(operations)}


def _field(pointer: str, schema_pointer: str) -> Dict[str, Any]:
    return {"pointer": pointer, "schema_pointer": schema_pointer, "location": "response", "status": "200",
            "media_type": "application/json", "path": "id"}


_SURFACES = {
    "web": _surface({"method": "get", "path": "/pets/{petId}", "pointer": _OP, "fields": []}),
    "mobile": _surface({
        "method": "get", "path": "/pets/{petId}", "pointer": _OP,
        "fields": [_field(f"{_OP}/responses/200/content/application~1json/schema/properties/name",
                          f"{_PET}/properties/name")],
    }),
    "batch": _surface({
        "method": "get", "path": "/pets/{petId}", "pointer": _OP,
        "fields": [_field(f"{_PET}/properties/id", f"{_PET}/properties/id")],
    }),
    "admin": _surface({"method": "post", "path": "/pets", "pointer": "/paths/~1pets/post", "fields": []}),
}


def _run(cursor: Any, tenant: str, version: str, target: str, finished: str, operations: List[str]) -> str:
    cursor.execute(
        """INSERT INTO apiome.verification_run
               (tenant_id, suite_digest, target_slug, target_environment, target_base_url, runner_name,
                started_at, finished_at, duration_ms, outcome, total_cases, passed_cases, source)
           VALUES (%s, %s, %s, 'staging', 'https://pets.example.com', 'apiome', %s::timestamptz - interval '1 minute',
                   %s::timestamptz, 1000, 'passed', %s, %s, %s::jsonb)
           RETURNING id::text AS id""",
        (tenant, "sha256:" + "a" * 64, target, finished, finished, len(operations), len(operations),
         json.dumps({"revision_id": version})),
    )
    run = cursor.fetchone()["id"]
    for sequence, key in enumerate(operations):
        method, path = key.split(" ", 1)
        cursor.execute(
            """INSERT INTO apiome.verification_run_operation
                   (tenant_id, run_id, sequence, case_id, operation_key, http_method, http_path, outcome)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'passed')""",
            (tenant, run, sequence, f"case-{sequence}", key, method, path),
        )
    return run


@pytest.fixture
def petstore(tx) -> Dict[str, Any]:  # noqa: F811 - the imported fixture
    db, cursor = tx
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute("INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                   (f"pets {suffix}", f"pets-{suffix}"))
    tenant = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable)
           VALUES (%s, %s, 'Petstore', 'petstore', true) RETURNING id::text AS id""",
        (tenant, user),
    )
    project = cursor.fetchone()["id"]
    mock = {
        "fixturePacks": {"pets": {"packFormat": 1, "collections": {"/pets": []}},
                         "owners": {"packFormat": 1, "collections": {"/owners": []}}},
        "scenarios": {"slow-pets": {"operations": {"GET /pets/{petId}": {"latencyMs": 900}}},
                      "orders-down": {"operations": {"POST /orders": {"status": 503}}}},
    }
    cursor.execute(
        """INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at, mock_settings)
           VALUES (%s, %s, '1.0.0', true, now(), %s::jsonb) RETURNING id::text AS id""",
        (project, user, json.dumps(mock)),
    )
    version = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.versions
               (project_id, creator_id, version_id, published, published_at, metadata, created_at)
           VALUES (%s, %s, '0.9.0', true, now() - interval '90 days', '{"deprecated": true}'::jsonb,
                   now() - interval '90 days')
           RETURNING id::text AS id""",
        (project, user),
    )
    deprecated = cursor.fetchone()["id"]

    consumers: Dict[str, str] = {}
    for slug in ("web", "mobile", "batch", "admin", "reporting"):
        cursor.execute(
            """INSERT INTO apiome.consumer (tenant_id, project_id, slug, name)
               VALUES (%s, %s, %s, %s) RETURNING id::text AS id""",
            (tenant, project, slug, slug.title()),
        )
        consumers[slug] = cursor.fetchone()["id"]
    for slug, surface in _SURFACES.items():
        pointers = contract_pointers(ConsumerContractSurface.model_validate(surface))
        cursor.execute(
            """INSERT INTO apiome.consumer_contract
                   (tenant_id, project_id, consumer_id, revision, surface, surface_pointers, operation_count,
                    version_id, version_label)
               VALUES (%s, %s, %s, 1, %s::jsonb, %s::text[], 1, %s, %s)""",
            (tenant, project, consumers[slug], json.dumps(surface), pointers,
             deprecated if slug == "batch" else version, "0.9.0" if slug == "batch" else "1.0.0"),
        )
    # "reporting" declared that it depends on the "web" consumer (CDG-3.2).
    replace_declared(cursor, tenant, "consumer", consumers["reporting"], "manual",
                     [DeclaredReference(reference="web", kind="consumer", entity_id=consumers["web"])])

    runs = {
        "a-latest": _run(cursor, tenant, version, "staging-a", "2026-10-10T10:00:00Z",
                         ["GET /pets/{id}", "POST /pets"]),
        "a-older": _run(cursor, tenant, version, "staging-a", "2026-10-01T10:00:00Z", ["GET /pets/{id}"]),
        "b-latest": _run(cursor, tenant, version, "prod-b", "2026-10-09T10:00:00Z", ["GET /pets/{petId}"]),
        "c-other": _run(cursor, tenant, version, "other-c", "2026-10-09T10:00:00Z", ["POST /pets"]),
    }
    cursor.execute(
        """INSERT INTO apiome.verification_policy_evaluations
               (tenant_id, project_id, version_record_id, policy_content_fingerprint, purpose, passed,
                enforcement, evidence_run_ids)
           VALUES (%s, %s, %s, 'fp', 'deploy', true, 'block', %s::uuid[])""",
        (tenant, project, version, [runs["a-latest"]]),
    )
    cursor.execute("INSERT INTO apiome.agent_toolsets (tenant_id, version_id) VALUES (%s, %s) RETURNING id::text AS id",
                   (tenant, version))
    toolset = cursor.fetchone()["id"]
    for key, name in (("GET /pets/{petId}", "get_pet"), ("POST /pets", "create_pet")):
        cursor.execute(
            """INSERT INTO apiome.agent_toolset_tools (toolset_id, operation_key, tool_name, write_op, enabled)
               VALUES (%s, %s, %s, false, true)""",
            (toolset, key, name),
        )
    cursor.execute(
        """INSERT INTO apiome.sdk_regen_subscriptions (tenant_id, project_id, ecosystem, delivery_mode)
           VALUES (%s, %s, 'npm', 'registry')""",
        (tenant, project),
    )
    return {"db": db, "cursor": cursor, "tenant": tenant, "project": project, "version": version,
            "consumers": consumers, "runs": runs}


def _ask(world: Dict[str, Any], *pointers: str, **kwargs: Any) -> Dict[str, Any]:
    request = BlastRadiusRequest(kind="project", entity="petstore", pointers=tuple(pointers), **kwargs)
    return blast_radius(world["db"], world["tenant"], request)


def test_the_golden_fixture(petstore) -> None:
    result = _ask(petstore, "/paths/~1pets~1{id}/get")
    assert result["evidence_checked"] is True and result["truncated"] is False
    assert result["operations"] == ["GET /pets/{id}"]
    assert result["version"]["label"] == "1.0.0"
    assert sorted(e["slug"] for e in result["direct"]) == ["batch", "mobile", "web"]
    assert all(e["edge_kind"] == "consumes" and e["provenance"] == "derived" for e in result["direct"])
    (transitive,) = result["transitive"]
    assert (transitive["slug"], transitive["depth"], transitive["provenance"]) == ("reporting", 2, "declared")
    assert [step["edge_kind"] for step in transitive["path"]] == ["consumes", "depends_on"]

    evidence = result["invalidated_evidence"]
    assert sorted(run["run_id"] for run in evidence["verification_runs"]) == sorted(
        [petstore["runs"]["a-latest"], petstore["runs"]["b-latest"]]
    )
    assert [tool["tool_name"] for tool in evidence["agent_toolset_tools"]] == ["get_pet"]
    assert len(evidence["consumer_contracts"]) == 3
    assert [g["cited_runs"] for g in evidence["deploy_gate_evaluations"]] == [[petstore["runs"]["a-latest"]]]
    assert [(m["kind"], m["name"]) for m in evidence["mock_fixture_packs"]] == [
        ("fixture_pack", "pets"), ("scenario", "slow-pets")
    ]
    assert [t["ecosystem"] for t in evidence["sdk_regen_targets"]] == ["npm"]
    assert [(c["consumer_slug"], c["version_label"]) for c in evidence["sunset_consumers"]] == [("batch", "0.9.0")]


def test_the_direct_set_equals_ctg_4_2_for_the_same_change(petstore, monkeypatch) -> None:
    monkeypatch.setattr(consumer_contract_store, "db", petstore["db"])
    for pointer in (_OP, f"{_PET}/properties/id", "/paths/~1pets/post", "/security"):
        diff = ClassifiedDiff(
            changes=[ClassifiedChange(rule_id="r", severity="breaking", pointer=pointer, change_kind="k")],
            counts={"breaking": 1, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": 1},
        )
        report = consumer_impact_for_diff(petstore["tenant"], petstore["project"], diff)
        affected = {v.consumer_slug for v in report.consumers if v.verdict not in ("unaffected", "undeclared")}
        direct = {e["slug"] for e in _ask(petstore, pointer)["direct"] if e["edge_kind"] == "consumes"}
        assert direct == affected, pointer


def test_a_pointer_nobody_consumes_is_an_answer(petstore) -> None:
    result = _ask(petstore, "/paths/~1nobody/get")
    assert result["direct"] == [] and result["transitive"] == []
    assert all(section == [] for section in result["invalidated_evidence"].values())
    assert result["evidence_checked"] is True


def test_depth_and_provenance_bound_the_walk(petstore) -> None:
    shallow = _ask(petstore, _OP, depth=1)
    assert shallow["transitive"] == [] and shallow["truncated"] is True  # reporting was cut off
    derived_only = _ask(petstore, _OP, provenances=("derived",))
    assert derived_only["transitive"] == []


def test_a_schema_pointer_reaches_the_consumers_that_use_it(petstore) -> None:
    result = _ask(petstore, f"{_PET}/properties/id")
    assert [e["slug"] for e in result["direct"]] == ["batch"]


def test_the_whole_entity(petstore) -> None:
    result = _ask(petstore)
    assert result["operations"] is None
    assert sorted(e["slug"] for e in result["direct"]) == ["admin", "batch", "mobile", "web"]
    assert len(result["invalidated_evidence"]["verification_runs"]) == 3  # latest per target, any op


def test_p95_under_300ms_on_a_10k_edge_tenant(petstore) -> None:
    cursor, tenant, project = petstore["cursor"], petstore["tenant"], petstore["project"]
    # 10k declared edges: 300 dependents of the project, chains below them, and unrelated noise.
    cursor.execute(
        """
        WITH firsts AS (
            SELECT gen_random_uuid() AS id FROM generate_series(1, 300)
        ), direct AS (
            INSERT INTO apiome.catalog_edges (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind,
                                              provenance, source_ref)
            SELECT %s::uuid, 'project', id, 'project', %s::uuid, 'depends_on', 'declared', 'manual' FROM firsts
            RETURNING from_id
        ), second AS (
            INSERT INTO apiome.catalog_edges (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind,
                                              provenance, source_ref)
            SELECT %s::uuid, 'project', gen_random_uuid(), 'project', from_id, 'depends_on', 'declared', 'manual'
            FROM direct, generate_series(1, 3)
            RETURNING from_id
        )
        INSERT INTO apiome.catalog_edges (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind,
                                          provenance, source_ref)
        SELECT %s::uuid, 'project', gen_random_uuid(), 'project', gen_random_uuid(), 'depends_on', 'declared',
               'manual'
        FROM generate_series(1, 8800)
        """,
        (tenant, project, tenant, tenant),
    )
    cursor.execute("SELECT count(*) AS n FROM apiome.catalog_edges WHERE tenant_id = %s::uuid", (tenant,))
    assert cursor.fetchone()["n"] >= 10_000
    cursor.execute("ANALYZE apiome.catalog_edges")

    _ask(petstore, _OP)  # warm
    samples = []
    for _ in range(LATENCY_SAMPLES):
        started = time.perf_counter()
        result = _ask(petstore, _OP)
        samples.append((time.perf_counter() - started) * 1000)
    assert len(result["direct"]) == 303 and len(result["transitive"]) == 901
    samples.sort()
    p95 = samples[int(round(0.95 * (len(samples) - 1)))]
    print(f"blast radius p95 {p95:.1f} ms")
    assert p95 < P95_BUDGET_MS, f"p95 {p95:.1f} ms over {P95_BUDGET_MS} ms"
