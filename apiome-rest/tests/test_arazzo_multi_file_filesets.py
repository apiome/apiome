"""Arazzo multi-file filesets — COA-1.2 (#7038).

An Arazzo workflow imports together with the OpenAPI/AsyncAPI files its
``sourceDescriptions`` name. Every fileset here is built the way intake builds one — zipped
(or tarred) and run through :func:`app.archive_intake.unpack_archive` — never assembled by
hand, so root selection is part of what is tested.

Covered:

* root selection: the workflow wins over the API files it calls, from a zip and a tar;
* the fileset tier resolves both sources and the lint pack checks steps against them;
* the pipeline reports every source in the job summary's ``arazzo_sources`` block, with a
  stable reason code for each unresolved one (the stored revision's copy is covered in
  :mod:`tests.test_persist_adapter_import`);
* the catalog tier (an injected lookup) and the SSRF-guarded remote tier (a fake fetcher,
  behind the import's opt-in and the deployment kill switch);
* bulk / git intake keep a workflow and its sources in one item.

Every pipeline run is a ``dry_run`` and the network is replaced at the resolver's seam.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
import zipfile
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pytest
import yaml

from app import import_source_pipeline, remote_ref_resolver
from app.arazzo_import_source import ArazzoImportSource
from app.arazzo_source_resolution import (
    REASON_INVALID_ENTRY,
    REASON_NOT_IN_FILESET,
    REASON_RELATIVE_WITHOUT_FILESET,
    REASON_UNPARSEABLE_MEMBER,
    TIER_CATALOG,
    TIER_FILESET,
    TIER_REMOTE,
    member_candidates,
    resolve_fileset_sources,
    resolve_remaining_sources,
    source_description_urls,
)
from app.archive_intake import ArchiveIntakeError, unpack_archive
from app.bulk_intake import member_references, plan_bulk_import
from app.config import settings
from app.fileset import IntakeFileset
from app.import_source_pipeline import ImportRunArtifacts, run_adapter_import_job
from app.remote_ref_resolver import (
    REASON_BLOCKED,
    REASON_BUDGET_REFS,
    REASON_DISABLED,
    RemoteRefBudget,
    RemoteRefCache,
    default_cache,
    fetch_remote_documents,
)

REMOTE_URL = "https://apis.example.com/billing.openapi.yaml"

FLOW = """arazzo: 1.0.1
info:
  title: Adopt a pet
  version: 1.0.0
sourceDescriptions:
  - name: pets
    url: ./pets.yaml
    type: openapi
  - name: users
    url: apis/users.openapi.json
    type: openapi
workflows:
  - workflowId: adopt
    steps:
      - stepId: find
        operationId: $sourceDescriptions.pets.listPets
      - stepId: owner
        operationId: $sourceDescriptions.users.getUser
"""

PETS = """openapi: 3.0.3
info: {title: Pets, version: '1'}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {'200': {description: ok}}
"""

USERS = json.dumps(
    {
        "openapi": "3.1.0",
        "info": {"title": "Users", "version": "1"},
        "servers": [{"url": "./v1"}],
        "paths": {
            "/users/{id}": {
                "get": {"operationId": "getUser", "responses": {"200": {"description": "ok"}}}
            }
        },
    }
)

BILLING = """openapi: 3.1.0
info: {title: Billing, version: '1'}
paths:
  /invoices:
    post:
      operationId: createInvoice
      responses: {'201': {description: created}}
"""


def _members() -> Dict[str, str]:
    """The acceptance set: a workflow plus the two OpenAPI files it calls."""
    return {"flow.arazzo.yaml": FLOW, "pets.yaml": PETS, "apis/users.openapi.json": USERS}


def _zip(members: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _tar_gz(members: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _fileset(members: Mapping[str, str]) -> IntakeFileset:
    """Build a fileset through ``unpack_archive``, exactly as archive intake does."""
    unpacked = unpack_archive(_zip(members), source_label="flow.zip")
    return IntakeFileset.from_members(unpacked.members, root=unpacked.root_path)


def _with_sources(*extra: Dict[str, Any]) -> str:
    """The acceptance workflow with more ``sourceDescriptions`` entries appended."""
    document = yaml.safe_load(FLOW)
    document["sourceDescriptions"].extend(extra)
    return yaml.safe_dump(document, sort_keys=False)


def _payload(raw: bytes, *, filename: str, options: Optional[dict] = None) -> dict:
    merged = {"dry_run": True}
    merged.update(options or {})
    return {
        "rest_job_id": "job-arazzo-set",
        "filename": filename,
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "metadata": {"source_kind": "arazzo", "options": merged},
    }


async def _run(raw: bytes, *, filename: str = "flow.zip", options: Optional[dict] = None):
    artifacts = ImportRunArtifacts()
    status = await run_adapter_import_job(
        ArazzoImportSource(), _payload(raw, filename=filename, options=options), artifacts=artifacts
    )
    return status, artifacts


@pytest.fixture(autouse=True)
def _clear_reference_cache():
    """Keep the process-wide document cache from leaking between tests."""
    default_cache().clear()
    yield
    default_cache().clear()


@pytest.fixture
def fetches(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Replace the SSRF-guarded HTTP fetcher with an in-memory one serving BILLING."""
    calls: List[str] = []

    def _fetch(url: str, *, max_bytes: int, timeout: float) -> bytes:
        calls.append(url)
        if url != REMOTE_URL:
            raise remote_ref_resolver._FetchError(
                remote_ref_resolver.REASON_FETCH_FAILED, f"HTTP 404 from {url}"
            )
        return BILLING.encode("utf-8")

    monkeypatch.setattr(remote_ref_resolver, "_http_fetch", _fetch)
    return calls


# ---------------------------------------------------------------------------
# Root selection (archive intake)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack", [_zip, _tar_gz], ids=["zip", "tar.gz"])
def test_the_workflow_is_the_root_of_its_own_set(pack) -> None:
    unpacked = unpack_archive(pack(_members()), source_label="flow.zip")
    assert unpacked.root_path == "flow.arazzo.yaml"
    assert unpacked.detection.detected.format == "arazzo"
    assert set(unpacked.ambiguous_roots) == {"pets.yaml", "apis/users.openapi.json"}


def test_an_unrelated_api_file_still_makes_the_root_ambiguous() -> None:
    """Only the workflow's own sources stop competing — a stray spec still needs a choice."""
    members = _members()
    members["stray.openapi.yaml"] = PETS.replace("Pets", "Stray")
    with pytest.raises(ArchiveIntakeError, match="ambiguous"):
        unpack_archive(_zip(members), source_label="flow.zip")


def test_an_explicit_root_still_wins() -> None:
    unpacked = unpack_archive(_zip(_members()), source_label="flow.zip", root_path="pets.yaml")
    assert unpacked.root_path == "pets.yaml"


def test_a_workflow_without_local_sources_does_not_claim_the_set() -> None:
    """A workflow whose sources are all remote earns no entrypoint boost."""
    flow = FLOW.replace("./pets.yaml", REMOTE_URL).replace("apis/users.openapi.json", REMOTE_URL)
    with pytest.raises(ArchiveIntakeError, match="ambiguous"):
        unpack_archive(_zip({"flow.arazzo.yaml": flow, "pets.yaml": PETS}), source_label="x.zip")


# ---------------------------------------------------------------------------
# Tier 1: the fileset
# ---------------------------------------------------------------------------


def test_both_sources_resolve_from_the_fileset() -> None:
    adapter = ArazzoImportSource()
    document = adapter.parse_fileset(_fileset(_members()), source_label="flow.zip")
    assert [(entry["name"], entry["path"]) for entry in document.resolved_sources] == [
        ("pets", "pets.yaml"),
        ("users", "apis/users.openapi.json"),
    ]
    assert document.pending_sources == []
    assert document.root_path == "flow.arazzo.yaml"

    model = adapter.normalize(document)
    assert [entry["name"] for entry in model.extras["resolvedSources"]] == ["pets", "users"]
    assert len(model.services) == 1


def test_lint_checks_steps_against_both_resolved_sources() -> None:
    adapter = ArazzoImportSource()
    clean = adapter.lint(adapter.normalize(adapter.parse_fileset(_fileset(_members()))))
    members = _members()
    members["flow.arazzo.yaml"] = FLOW.replace("users.getUser", "users.noSuchOperation")
    broken = adapter.lint(adapter.normalize(adapter.parse_fileset(_fileset(members))))

    rule = "arazzo.dangling-operation-id"
    assert not [finding for finding in clean.findings if finding.rule == rule]
    assert [finding for finding in broken.findings if finding.rule == rule]


def test_fileset_tier_records_why_a_source_is_pending() -> None:
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources(
        {"name": "missing", "url": "./missing.yaml", "type": "openapi"},
        {"name": "broken", "url": "broken.yaml", "type": "openapi"},
        {"name": "billing", "url": REMOTE_URL, "type": "openapi"},
        {"name": "nourl"},
    )
    members["broken.yaml"] = "openapi: [unterminated\n"
    document = ArazzoImportSource().parse_fileset(_fileset(members))
    reasons = {entry["name"]: entry["reason"] for entry in document.pending_sources}
    assert reasons == {
        "missing": REASON_NOT_IN_FILESET,
        "broken": REASON_UNPARSEABLE_MEMBER,
        "billing": None,
        "nourl": REASON_INVALID_ENTRY,
    }


def test_member_candidates_never_leave_the_set() -> None:
    assert member_candidates("../outside.yaml", "flow.arazzo.yaml") == ()
    assert member_candidates(REMOTE_URL, "flow.arazzo.yaml") == ()
    assert member_candidates("#/components", "flow.arazzo.yaml") == ()
    assert member_candidates("../pets.yaml", "flows/flow.arazzo.yaml") == ("pets.yaml",)
    assert member_candidates("./pets.yaml#/paths", "flows/flow.arazzo.yaml") == (
        "flows/pets.yaml",
        "pets.yaml",
    )


# ---------------------------------------------------------------------------
# The import report (pipeline)
# ---------------------------------------------------------------------------


async def test_zip_imports_as_one_workflow_with_both_sources_resolved() -> None:
    status, artifacts = await _run(_zip(_members()))

    assert status.state == "completed"
    assert status.summary["format"] == "arazzo"
    report = status.summary["arazzo_sources"]
    assert report["resolved"] == 2
    assert report["unresolved"] == 0
    assert report["by_tier"] == {TIER_FILESET: 2, TIER_CATALOG: 0, TIER_REMOTE: 0}
    assert [(s["name"], s["tier"], s["path"]) for s in report["sources"]] == [
        ("pets", TIER_FILESET, "pets.yaml"),
        ("users", TIER_FILESET, "apis/users.openapi.json"),
    ]
    codes = [event.code for event in status.events]
    assert "ARAZZO_SOURCES_RESOLVED" in codes
    assert "ARAZZO_SOURCES_UNRESOLVED" not in codes
    assert artifacts.arazzo_sources is not None


async def test_unresolved_sources_are_listed_in_the_import_report(fetches: List[str]) -> None:
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources(
        {"name": "missing", "url": "./missing.yaml", "type": "openapi"},
        {"name": "billing", "url": REMOTE_URL, "type": "openapi"},
    )
    status, _artifacts = await _run(_zip(members))

    assert status.state == "completed"
    report = status.summary["arazzo_sources"]
    assert report["resolved"] == 2
    assert report["unresolved"] == 2
    assert [(s["name"], s["url"], s["reason"]) for s in report["unresolved_sources"]] == [
        ("missing", "./missing.yaml", REASON_NOT_IN_FILESET),
        ("billing", REMOTE_URL, REASON_DISABLED),
    ]
    # Remote resolution is opt-in: nothing was fetched.
    assert fetches == []
    warning = next(e for e in status.events if e.code == "ARAZZO_SOURCES_UNRESOLVED")
    assert warning.level == "warn"
    assert "missing" in warning.message and "billing" in warning.message


async def test_a_single_file_workflow_reports_its_relative_sources() -> None:
    status, _artifacts = await _run(FLOW.encode("utf-8"), filename="flow.arazzo.yaml")

    assert status.state == "completed"
    report = status.summary["arazzo_sources"]
    assert report["resolved"] == 0
    assert {s["reason"] for s in report["unresolved_sources"]} == {
        REASON_RELATIVE_WITHOUT_FILESET
    }


async def test_a_workflow_without_sources_has_no_report() -> None:
    document = yaml.safe_load(FLOW)
    document.pop("sourceDescriptions")
    status, _ = await _run(yaml.safe_dump(document).encode(), filename="flow.arazzo.yaml")
    assert "arazzo_sources" not in status.summary


# ---------------------------------------------------------------------------
# Tier 2: the catalog
# ---------------------------------------------------------------------------


def test_catalog_tier_resolves_what_the_fileset_lacks() -> None:
    document = yaml.safe_load(
        _with_sources(
            {"name": "orders", "url": "./orders.yaml", "type": "openapi"},
            {"name": "billing", "url": REMOTE_URL, "type": "openapi"},
        )
    )
    resolved, pending = resolve_fileset_sources(
        document, "flow.arazzo.yaml", {"pets.yaml": yaml.safe_load(PETS)}
    )
    seen: List[Tuple[str, Tuple[str, ...]]] = []

    def lookup(url: str, candidates: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
        seen.append((url, candidates))
        if url == "./orders.yaml":
            return {"project_id": "p-orders", "version_id": None, "path": "orders.yaml"}
        if url == REMOTE_URL:
            return {"project_id": "p-billing", "version_id": "v-7", "path": None}
        return None

    outcome = resolve_remaining_sources(
        document,
        root_path="flow.arazzo.yaml",
        fileset_resolved=resolved,
        pending=pending,
        catalog_lookup=lookup,
    )

    tiers = {source.name: (source.tier, source.project_id) for source in outcome.resolved}
    assert tiers == {
        "pets": (TIER_FILESET, None),
        "orders": (TIER_CATALOG, "p-orders"),
        "billing": (TIER_CATALOG, "p-billing"),
    }
    assert [source.name for source in outcome.unresolved] == ["users"]
    assert ("./orders.yaml", ("orders.yaml",)) in seen
    assert (REMOTE_URL, ()) in seen
    # Declaration order is kept, so the report reads like the document.
    assert [source.name for source in outcome.resolved] == ["pets", "orders", "billing"]


def test_a_failing_catalog_lookup_is_a_miss_not_an_error() -> None:
    def lookup(url: str, candidates: Tuple[str, ...]):
        raise RuntimeError("database down")

    outcome = resolve_remaining_sources(yaml.safe_load(FLOW), catalog_lookup=lookup)
    assert {source.reason for source in outcome.unresolved} == {REASON_RELATIVE_WITHOUT_FILESET}


async def test_pipeline_consults_the_catalog_for_a_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Tuple[str, Optional[dict]]] = []

    def fake_lookup(tenant_id: str, git_source: Optional[dict]):
        calls.append((tenant_id, git_source))
        return lambda url, candidates: (
            {"project_id": "p-billing", "version_id": "v-1", "path": None}
            if url == REMOTE_URL
            else None
        )

    monkeypatch.setattr(import_source_pipeline, "_arazzo_catalog_lookup", fake_lookup)
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources({"name": "billing", "url": REMOTE_URL})
    payload = _payload(_zip(members), filename="flow.zip")
    payload["tenant_id"] = "00000000-0000-0000-0000-000000000001"
    status = await run_adapter_import_job(ArazzoImportSource(), payload)

    assert status.state == "completed"
    assert calls and calls[0][0] == payload["tenant_id"]
    sources = {s["name"]: s for s in status.summary["arazzo_sources"]["sources"]}
    assert sources["billing"]["tier"] == TIER_CATALOG
    assert sources["billing"]["project_id"] == "p-billing"
    assert sources["billing"]["version_id"] == "v-1"


# ---------------------------------------------------------------------------
# Tier 3: remote (SSRF-guarded, opt-in)
# ---------------------------------------------------------------------------


async def test_opted_in_import_fetches_a_remote_source(fetches: List[str]) -> None:
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources(
        {"name": "billing", "url": REMOTE_URL, "type": "openapi"}
    )
    status, artifacts = await _run(_zip(members), options={"resolve_remote_refs": True})

    assert status.state == "completed"
    assert fetches == [REMOTE_URL]
    report = status.summary["arazzo_sources"]
    assert report["by_tier"] == {TIER_FILESET: 2, TIER_CATALOG: 0, TIER_REMOTE: 1}
    billing = next(s for s in report["sources"] if s["name"] == "billing")
    assert billing["tier"] == TIER_REMOTE
    assert billing["digest"]
    # The fetched document joins the resolved sources the lint pack reads.
    names = [entry["name"] for entry in artifacts.model.extras["resolvedSources"]]
    assert names == ["pets", "users", "billing"]


async def test_a_remote_source_on_a_single_file_import(fetches: List[str]) -> None:
    document = yaml.safe_load(FLOW)
    document["sourceDescriptions"] = [{"name": "billing", "url": REMOTE_URL, "type": "openapi"}]
    document["workflows"][0]["steps"] = [
        {"stepId": "bill", "operationId": "$sourceDescriptions.billing.noSuchOperation"}
    ]
    status, artifacts = await _run(
        yaml.safe_dump(document).encode(),
        filename="flow.arazzo.yaml",
        options={"resolve_remote_refs": True},
    )

    assert status.state == "completed"
    assert status.summary["arazzo_sources"]["by_tier"][TIER_REMOTE] == 1
    rules = [finding.rule for finding in artifacts.lint.findings]
    assert "arazzo.dangling-operation-id" in rules


async def test_the_kill_switch_overrides_the_opt_in(
    fetches: List[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "remote_ref_resolution_allowed", False)
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources({"name": "billing", "url": REMOTE_URL})
    status, _ = await _run(_zip(members), options={"resolve_remote_refs": True})

    assert fetches == []
    unresolved = status.summary["arazzo_sources"]["unresolved_sources"]
    assert [(s["name"], s["reason"]) for s in unresolved] == [("billing", REASON_DISABLED)]


async def test_a_refused_scheme_is_blocked_not_fetched(fetches: List[str]) -> None:
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources({"name": "secrets", "url": "file:///etc/passwd"})
    status, _ = await _run(_zip(members), options={"resolve_remote_refs": True})

    assert fetches == []
    unresolved = status.summary["arazzo_sources"]["unresolved_sources"]
    assert [(s["name"], s["reason"]) for s in unresolved] == [("secrets", REASON_BLOCKED)]


async def test_a_failed_fetch_is_reported(fetches: List[str]) -> None:
    missing = "https://apis.example.com/gone.yaml"
    members = _members()
    members["flow.arazzo.yaml"] = _with_sources({"name": "gone", "url": missing})
    status, _ = await _run(_zip(members), options={"resolve_remote_refs": True})

    assert fetches == [missing]
    unresolved = status.summary["arazzo_sources"]["unresolved_sources"]
    assert [(s["name"], s["reason"]) for s in unresolved] == [("gone", "fetch-failed")]


def test_fetch_remote_documents_honours_the_reference_budget() -> None:
    def fetcher(url: str, *, max_bytes: int, timeout: float) -> bytes:
        return BILLING.encode("utf-8")

    outcomes = fetch_remote_documents(
        ["https://a.example.com/one.yaml", "https://a.example.com/two.yaml"],
        budget=RemoteRefBudget(max_refs=1),
        cache=RemoteRefCache(),
        fetcher=fetcher,
    )
    one, two = outcomes.values()
    assert one.document["openapi"] == "3.1.0" and one.reason is None
    assert two.document is None and two.reason == REASON_BUDGET_REFS


# ---------------------------------------------------------------------------
# Bulk and repository intake keep the set together
# ---------------------------------------------------------------------------


def test_source_urls_are_read_only_from_arazzo_documents() -> None:
    assert source_description_urls(FLOW) == ["./pets.yaml", "apis/users.openapi.json"]
    # An OpenAPI `servers[].url` is not a file reference.
    assert source_description_urls(USERS) == []
    assert source_description_urls(json.dumps(yaml.safe_load(FLOW))) == [
        "./pets.yaml",
        "apis/users.openapi.json",
    ]


def test_member_references_follow_source_descriptions() -> None:
    assert member_references("flow.arazzo.yaml", FLOW, _members()) == (
        "pets.yaml",
        "apis/users.openapi.json",
    )


def test_a_bulk_plan_keeps_the_workflow_and_its_sources_in_one_item() -> None:
    members = _members()
    members["other.openapi.yaml"] = PETS.replace("Pets", "Other")
    plan = plan_bulk_import(members)

    roots = {group.root_path: set(group.members) for group in plan.groups}
    assert roots["flow.arazzo.yaml"] == {"flow.arazzo.yaml", "pets.yaml", "apis/users.openapi.json"}
    assert roots["other.openapi.yaml"] == {"other.openapi.yaml"}


def test_a_ticked_workflow_in_a_repository_arrives_with_its_sources() -> None:
    """Repository intake (BLK-1.5 closure) follows ``sourceDescriptions[].url`` too."""
    from test_git_intake import _REPO_URL, FakeRepositoryClient

    from app.git_intake import GitSelector, fetch_git_files

    repo = FakeRepositoryClient(
        {
            "flows/flow.arazzo.yaml": FLOW.replace("./pets.yaml", "../apis/pets.yaml").replace(
                "apis/users.openapi.json", "../apis/users.openapi.json"
            ),
            "apis/pets.yaml": PETS,
            "apis/users.openapi.json": USERS,
            "apis/unrelated.yaml": PETS.replace("Pets", "Unrelated"),
        }
    )
    selector = GitSelector(repo_url=_REPO_URL, ref="main", path="", root=None)
    result = fetch_git_files(selector, ["flows/flow.arazzo.yaml"], client=repo)

    assert set(result.members) == {
        "flows/flow.arazzo.yaml",
        "apis/pets.yaml",
        "apis/users.openapi.json",
    }
    plan = plan_bulk_import(result.members)
    assert [group.root_path for group in plan.groups] == ["flows/flow.arazzo.yaml"]
