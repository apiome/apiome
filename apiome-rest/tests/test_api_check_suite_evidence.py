"""Reading the API change check suite's evidence — GNC-3.1 (#4740).

Each reader is a thin adapter over machinery an earlier ticket owns; what is pinned here is that it
reads the *right* thing: the stored-first lint report's error findings, the CTG classification
against the prior *published* baseline, the newest contract run of *this revision* and whether it is
still this draft's suite, and the SDK kit built from the draft with the project's branding. The
classifier and the kit builder run for real; only storage and the suite compiler are doubled.
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from app import api_check_suite_evidence as evidence
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Server,
    Service,
)
from app.contract_suite_service import SchemaReferenceError
from tests.fake_suite_db import FakeSuiteDb

TENANT = "2d3e4f50-8888-4aaa-8bbb-000000000001"
PROJECT = "2d3e4f50-8888-4aaa-8bbb-000000000002"
VERSION = "2d3e4f50-8888-4aaa-8bbb-000000000010"
BASELINE = "2d3e4f50-8888-4aaa-8bbb-000000000011"

BASE_DOC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/pets/{id}": {
            "get": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


@pytest.fixture
def fake(monkeypatch) -> FakeSuiteDb:
    """A store beneath the evidence readers."""
    database = FakeSuiteDb()
    database.add_project(TENANT, PROJECT, "pets")
    database.add_version(PROJECT, VERSION, "2.0.0")
    database.add_version(PROJECT, BASELINE, "1.0.0")
    monkeypatch.setattr(evidence, "db", database)
    return database


def test_every_component_links_to_where_its_evidence_lives():
    links = evidence.evidence_links("acme", PROJECT, VERSION)
    assert links["lint"] == f"/v1/versions/acme/{PROJECT}/{VERSION}/lint"
    assert links["breaking"].endswith(f"/{VERSION}/breaking-publish-guardrail")
    assert links["consumers"] == f"/v1/tenants/acme/projects/{PROJECT}/consumers"
    assert links["contract"] == "/v1/tenants/acme/verification-runs"
    assert links["sdk"] == f"/v1/projects/acme/{PROJECT}/sdk-settings"


# ---------------------------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------------------------


def test_the_lint_report_is_read_stored_first_and_its_errors_are_kept(monkeypatch):
    seen: List[Any] = []

    async def build_lint_report(version, project_id, tenant_slug, tenant_id):
        seen.append((version["id"], project_id, tenant_slug, tenant_id))
        return SimpleNamespace(
            grade="b",
            score=81,
            severity_counts={"error": 1, "warning": 3},
            findings=[
                SimpleNamespace(rule="no-empty", path="/info", message="empty", severity="error"),
                SimpleNamespace(rule="style", path="/paths", message="meh", severity="warning"),
            ],
            guide_id="g1",
            guide_name="Acme",
            guide_source="tenant",
            guide_revision_id="gr1",
            report_fingerprint="sha256:report",
        )

    monkeypatch.setattr("app.lint_routes.build_lint_report", build_lint_report)
    facts = asyncio.run(
        evidence.read_lint_facts(
            tenant_id=TENANT, tenant_slug="acme", project_id=PROJECT, version={"id": VERSION}
        )
    )
    assert seen == [(VERSION, PROJECT, "acme", TENANT)]
    assert facts.grade == "B"
    assert facts.error_findings == [{"rule": "no-empty", "path": "/info", "message": "empty"}]
    # The pinned guide revision is present on a fresh lint and absent on a stored read of the same
    # report; it is left out so the two read the same, and the report fingerprint pins the content.
    assert facts.guide == {"id": "g1", "name": "Acme", "source": "tenant"}
    assert facts.report_fingerprint == "sha256:report"


# ---------------------------------------------------------------------------------------------
# breaking
# ---------------------------------------------------------------------------------------------


def _draft_documents(monkeypatch, documents: Dict[str, Dict[str, Any]]) -> None:
    """Rebuild each revision's document from a table, in place of the canonical tables."""

    def read_draft_document(_tenant_id: str, version: Dict[str, Any]):
        return copy.deepcopy(documents[version["id"]]), f"sha256:{version['id']}"

    monkeypatch.setattr("app.spec_sync_store.read_draft_document", read_draft_document)


def test_a_line_with_nothing_published_has_no_baseline(fake):
    classification = evidence.read_breaking_facts(
        tenant_id=TENANT, project_id=PROJECT, version={"id": VERSION}, draft_document=BASE_DOC
    )
    assert classification.facts.baseline_revision_id is None
    assert classification.diff is None


def test_the_draft_is_classified_against_the_prior_published_revision(fake, monkeypatch):
    fake.baselines[VERSION] = BASELINE
    _draft_documents(monkeypatch, {BASELINE: BASE_DOC})
    draft = copy.deepcopy(BASE_DOC)
    del draft["paths"]["/pets/{id}"]

    classification = evidence.read_breaking_facts(
        tenant_id=TENANT,
        project_id=PROJECT,
        version={"id": VERSION, "version_id": "2.0.0"},
        draft_document=draft,
    )
    facts = classification.facts
    assert facts.baseline_revision_id == BASELINE
    assert facts.baseline_label == "1.0.0"
    assert facts.max_severity == "breaking"
    assert facts.counts["breaking"] >= 1
    assert facts.breaking_changes
    assert all(change["pointer"].startswith("/paths") for change in facts.breaking_changes)
    # The same classification is handed on for the consumer intersection.
    assert classification.diff is not None


def test_an_unchanged_draft_has_nothing_to_classify(fake, monkeypatch):
    fake.baselines[VERSION] = BASELINE
    _draft_documents(monkeypatch, {BASELINE: BASE_DOC})
    classification = evidence.read_breaking_facts(
        tenant_id=TENANT, project_id=PROJECT, version={"id": VERSION}, draft_document=BASE_DOC
    )
    assert classification.facts.max_severity is None
    assert classification.facts.breaking_changes == []


def test_a_baseline_the_database_names_but_cannot_read_is_an_error(fake):
    fake.baselines[VERSION] = "2d3e4f50-8888-4aaa-8bbb-0000000000ff"
    with pytest.raises(LookupError):
        evidence.read_breaking_facts(
            tenant_id=TENANT, project_id=PROJECT, version={"id": VERSION}, draft_document=BASE_DOC
        )


# ---------------------------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------------------------


def _compiler(monkeypatch, digest: Optional[str] = "sha256:suite", *, ok: bool = True, error=None):
    """Stand in for the suite compiler; returns the references it was asked to compile."""
    asked: List[str] = []

    def compile_version_contract_suite(reference, _request, *, tenant_id):
        asked.append(reference)
        if error:
            raise error
        return SimpleNamespace(ok=ok, manifest=SimpleNamespace(digest=digest) if ok else None)

    monkeypatch.setattr(
        "app.contract_suite_service.compile_version_contract_suite", compile_version_contract_suite
    )
    return asked


_API = SimpleNamespace(services=[object()])


def test_a_version_without_services_has_no_contract(fake):
    facts = evidence.read_contract_facts(
        tenant_id=TENANT, version_id=VERSION, api=SimpleNamespace(services=[])
    )
    assert facts.applicable is False


def test_a_revision_nobody_ran_has_no_contract_evidence(fake):
    fake.add_verification_run(TENANT, BASELINE)
    facts = evidence.read_contract_facts(tenant_id=TENANT, version_id=VERSION, api=_API)
    assert facts.applicable is True
    assert facts.run is None


def test_the_newest_run_of_this_revision_is_read_and_its_reference_recompiled(fake, monkeypatch):
    asked = _compiler(monkeypatch)
    fake.add_verification_run(TENANT, VERSION, outcome="failed", reference="project/pets/2.0.0")
    newest = fake.add_verification_run(TENANT, VERSION, reference=f"project/{PROJECT}/{VERSION}")
    facts = evidence.read_contract_facts(tenant_id=TENANT, version_id=VERSION, api=_API)
    assert facts.run["id"] == newest["id"]
    assert facts.run["outcome"] == "passed"
    assert facts.run["cases"] == {"total": 3, "passed": 3, "failed": 0, "errored": 0, "skipped": 0}
    assert facts.run["finishedAt"] == newest["finished_at"].isoformat()
    # The run's *own* spelling is recompiled: the digest covers the reference string.
    assert asked == [f"project/{PROJECT}/{VERSION}"]
    assert facts.current_digest == "sha256:suite"


@pytest.mark.parametrize(
    "compiler",
    [
        {"error": SchemaReferenceError("gone", status_code=404)},
        {"ok": False},
    ],
)
def test_a_reference_that_no_longer_compiles_has_no_current_digest(fake, monkeypatch, compiler):
    _compiler(monkeypatch, **compiler)
    fake.add_verification_run(TENANT, VERSION)
    facts = evidence.read_contract_facts(tenant_id=TENANT, version_id=VERSION, api=_API)
    assert facts.run is not None
    assert facts.current_digest is None


def test_a_run_that_recorded_no_reference_cannot_be_shown_current(fake, monkeypatch):
    asked = _compiler(monkeypatch)
    run = fake.add_verification_run(TENANT, VERSION)
    run["source"] = {"revision_id": VERSION}
    facts = evidence.read_contract_facts(tenant_id=TENANT, version_id=VERSION, api=_API)
    assert facts.current_digest is None
    assert asked == []


# ---------------------------------------------------------------------------------------------
# sdk
# ---------------------------------------------------------------------------------------------


def _model(operations: Optional[List[Operation]] = None) -> CanonicalApi:
    """A REST model with one HTTP operation."""
    ops = (
        operations
        if operations is not None
        else [
            Operation(
                key="GET /pets",
                name="listPets",
                kind=OperationKind.REQUEST_RESPONSE,
                http_method="get",
                http_path="/pets",
                extras={"operationId": "listPets"},
            )
        ]
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Pets API",
        version="2.0.0",
        identity=ApiIdentity(name="pets"),
        servers=[Server(url="https://api.pets.dev")],
        services=[Service(key="pets", name="pets", operations=ops)],
    )


@pytest.fixture
def branding(monkeypatch) -> List[Any]:
    """The project's SDK settings, unbranded; records the scope it was asked for."""
    asked: List[Any] = []

    def load_settings(tenant_id, project_id=None, context=None):
        asked.append((tenant_id, project_id, context))
        return SimpleNamespace(
            resolved=SimpleNamespace(package_names={}, license_header=None, user_agent=None),
            content_fingerprint="sha256:settings",
        )

    monkeypatch.setattr("app.sdk_generation_settings_store.load_settings", load_settings)
    return asked


def _sdk(api: CanonicalApi):
    """Read the SDK facts of the draft."""
    return evidence.read_sdk_facts(
        tenant_id=TENANT,
        tenant_slug="acme",
        project={"id": PROJECT, "slug": "pets"},
        version={"id": VERSION, "version_id": "2.0.0"},
        source=SimpleNamespace(api=api, source_text=None, source_format=None),
    )


def test_the_kit_is_built_from_the_draft_with_the_projects_branding(branding):
    facts = _sdk(_model())
    assert facts.operation_count == 1
    assert facts.total_operation_count == 1
    assert facts.go_client_error is None and facts.server_stub_error is None
    assert facts.kit_digest.startswith("sha256:")
    assert facts.file_count > 0
    (tenant_id, project_id, context) = branding[0]
    assert (tenant_id, project_id) == (TENANT, PROJECT)
    assert (context.tenant, context.project, context.version) == ("acme", "pets", "2.0.0")


def test_the_same_draft_builds_the_same_kit(branding):
    # The kit is byte-deterministic, so its digest is an evidence id a re-run reproduces.
    assert _sdk(_model()).kit_digest == _sdk(_model()).kit_digest


def test_a_generator_that_raises_is_reported_not_raised(branding, monkeypatch):
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("unrenderable")

    monkeypatch.setattr("app.sdk_kit.generate_go_client", broken)
    facts = _sdk(_model())
    assert facts.go_client_error == "ValueError: unrenderable"
    assert facts.server_stub_error is None


def test_an_operation_without_an_http_binding_is_counted_as_skipped(branding):
    api = _model(
        [
            Operation(
                key="GET /pets",
                name="listPets",
                kind=OperationKind.REQUEST_RESPONSE,
                http_method="get",
                http_path="/pets",
            ),
            Operation(key="Query.pets", name="petsQuery", kind=OperationKind.QUERY),
        ]
    )
    facts = _sdk(api)
    assert facts.total_operation_count == 2
    assert facts.operation_count == 1
    assert facts.skipped_operations == 1
