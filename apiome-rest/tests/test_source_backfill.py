"""Backfill of missing captured sources — E1-6 (#6221).

Pins :mod:`app.source_backfill`: a revision with no captured source is repaired from a sibling
revision or its linked-repository file **only** when that copy re-imports to the fingerprint the
revision recorded; otherwise it is left (``no-copy`` / ``unverifiable``) and the report says how
many were repaired. The database is faked; parsing and fingerprinting are real.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.catalog_conversion import build_conversion_source
from app.import_source import canonical_fingerprint
from app.source_backfill import backfill_captured_sources

SDL_V1 = "type Query { pet(id: ID!): Pet }\ntype Pet { id: ID! name: String }\n"
SDL_V2 = "type Query { pet(id: ID!): Pet pets: [Pet] }\ntype Pet { id: ID! name: String tag: String }\n"


def _fingerprint(sdl: str) -> str:
    item = {"id": "p", "source_format": "graphql", "format_metadata": {"sourceContent": sdl}}
    return canonical_fingerprint(build_conversion_source(item).api)


def _row(revision: str, *, fingerprint: str | None) -> Dict[str, Any]:
    fmd: Dict[str, Any] = {"sourceLabel": "schema.graphql", "inputKind": "file"}
    if fingerprint:
        fmd["fingerprint"] = fingerprint
    return {
        "id": revision, "project_id": "proj-1", "tenant_id": "tenant-1", "source_format": "graphql",
        "protocol": "graph", "format_metadata": fmd, "tool_versions": {}, "metadata": {},
    }


class FakeDb:
    """Answers the backfill's three queries and records its writes."""

    def __init__(self, missing: List[Dict[str, Any]], siblings: List[Dict[str, Any]]):
        self.missing, self.siblings = missing, siblings
        self.writes: List[tuple] = []
        self.queries: List[tuple] = []

    def execute_query(self, sql: str, params: tuple = ()):
        self.queries.append((sql, params))
        if sql.lstrip().startswith("UPDATE"):
            self.writes.append((params[1], json.loads(params[0])))
            return [{"id": params[1]}]
        if "v.id <> %s::uuid" in sql:
            return [s for s in self.siblings if s["id"] != params[1]]
        return list(self.missing)


def _no_repo(*_args):
    return []


def test_a_sibling_holding_the_identical_source_repairs_the_revision():
    db = FakeDb(
        [_row("rev-1", fingerprint=_fingerprint(SDL_V1))],
        [
            {"id": "rev-2", "format_metadata": {"sourceContent": SDL_V2, "inputKind": "file"}},
            {"id": "rev-0", "format_metadata": {"sourceContent": SDL_V1, "sourceLabel": "x"}},
        ],
    )
    report = backfill_captured_sources(db, read_repository=_no_repo).as_dict()
    assert (report["scanned"], report["repaired"], report["unrepaired"]) == (1, 1, 0)
    assert report["outcomes"][0]["source"] == "sibling:rev-0"
    [(revision, fields)] = db.writes
    # Only the content keys are copied, plus where they came from.
    assert revision == "rev-1"
    assert fields == {"sourceContent": SDL_V1, "sourceBackfilledFrom": "sibling:rev-0"}


def test_a_different_versions_source_is_never_copied():
    db = FakeDb(
        [_row("rev-1", fingerprint=_fingerprint(SDL_V1))],
        [{"id": "rev-2", "format_metadata": {"sourceContent": SDL_V2}}],
    )
    report = backfill_captured_sources(db, read_repository=_no_repo).as_dict()
    assert (report["repaired"], report["no_copy"]) == (0, 1)
    assert "re-import" in report["outcomes"][0]["detail"]
    assert db.writes == []


def test_the_linked_repository_file_repairs_when_it_still_matches():
    db = FakeDb([_row("rev-1", fingerprint=_fingerprint(SDL_V1))], [])
    seen = []

    def read_repository(_db, tenant, project):
        seen.append((tenant, project))
        return [("repository:r1@main:a.graphql", SDL_V2), ("repository:r1@main:b.graphql", SDL_V1)]

    report = backfill_captured_sources(db, read_repository=read_repository).as_dict()
    assert seen == [("tenant-1", "proj-1")]
    assert report["outcomes"][0]["source"] == "repository:r1@main:b.graphql"
    [(_revision, fields)] = db.writes
    assert fields["sourceContent"] == SDL_V1
    assert fields["sourceBackfilledFrom"] == "repository:r1@main:b.graphql"
    assert "secretScrub" not in fields  # the scrub report is not a source field


def test_a_revision_without_a_recorded_fingerprint_is_unverifiable():
    db = FakeDb(
        [_row("rev-1", fingerprint=None)],
        [{"id": "rev-0", "format_metadata": {"sourceContent": SDL_V1}}],
    )
    report = backfill_captured_sources(db, read_repository=_no_repo).as_dict()
    assert (report["repaired"], report["unverifiable"]) == (0, 1)
    assert db.writes == []


def test_a_dry_run_reports_without_writing():
    db = FakeDb(
        [_row("rev-1", fingerprint=_fingerprint(SDL_V1))],
        [{"id": "rev-0", "format_metadata": {"sourceContent": SDL_V1}}],
    )
    report = backfill_captured_sources(db, dry_run=True, read_repository=_no_repo).as_dict()
    assert report["dry_run"] is True and report["repaired"] == 1
    assert report["outcomes"][0]["status"] == "would-repair"
    assert db.writes == []


def test_one_failing_revision_does_not_stop_the_job():
    def boom(*_args):
        raise RuntimeError("github down")

    db = FakeDb(
        [_row("rev-1", fingerprint=_fingerprint(SDL_V1)), _row("rev-9", fingerprint=_fingerprint(SDL_V1))],
        [],
    )
    report = backfill_captured_sources(db, read_repository=boom).as_dict()
    assert report["scanned"] == 2 and report["repaired"] == 0
    assert all("github down" in o["detail"] for o in report["outcomes"])


def test_the_candidate_query_skips_withheld_and_openapi_and_scopes_the_tenant():
    db = FakeDb([], [])
    backfill_captured_sources(db, tenant_id="tenant-7", read_repository=_no_repo)
    sql, params = db.queries[0]
    assert "sourceWithheld" in sql and "openapi" in sql and "swagger" in sql
    assert params == ("tenant-7",)
