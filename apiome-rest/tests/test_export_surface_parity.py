"""Export surface parity — MFX-40.3 (#4341).

Four surfaces export a version: the ADE Export dialog (apiome-ui), the public browse export
(apiome-browse), ``apiome export`` (apiome-cli) and the MCP ``export.targets`` / ``version.export``
tools (apiome-mcp). They must not drift: for the same source they expose the same targets, the same
options and defaults, the same advisory wording and the same fidelity report shape. This suite drives
the REST routes each surface reads, for every fixture source:

* **UI + CLI** — ``GET /v1/export/{tenant}/targets`` and ``POST /v1/export/{tenant}/preview`` (the UI's
  ``/api/export/*`` proxies forward them unchanged; the CLI calls them directly);
* **browse** — ``GET /v1/browse/…/export/targets`` and ``POST …/export/preview``;
* **MCP** — ``POST /v1/internal/mcp/export/targets`` and ``POST …/run`` (its ``blocked`` / completed
  answer, whose top-level ``advisory`` must be the envelope's message).

and asserts the three answers are identical, target by target. The sampled previews (with those
targets' badges and options) are then recorded in one golden, ``tests/fixtures/export_surface_parity.json``,
which the client surfaces consume to prove they render the advisory verbatim and read the report shape:

* ``apiome-cli/tests/fixtures/export-surface-parity.json`` (``tests/test_export_surface_parity.py``);
* ``apiome-ui/tests/fixtures/exportSurfaceParity.json`` (``tests/export-surface-parity.test.tsx``);
* ``apiome-browse/lib/__tests__/fixtures/exportSurfaceParity.json`` (``lib/__tests__/exportSurfaceParity.test.ts``).

The copies must equal the golden byte for byte, so any drift — a route, the advisory template, a stale
copy — fails CI. Regenerate the golden and every copy together with
``pytest tests/test_export_surface_parity.py --update-golden`` (or ``UPDATE_EXPORT_PARITY_GOLDEN=1``) and
review the diff.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.config import settings
from app.export_job_engine import _jobs
from app.export_source import ExportSource
from app.main import app

client = TestClient(app)

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TOKEN = "internal-token-0123456789"
_AUTH = {"tenant_id": TENANT_ID, "user_id": "parity-user", "auth_method": "jwt"}

_REPO = Path(__file__).resolve().parents[2]
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "export_surface_parity.json"
#: The client surfaces' checked-in copies of the golden: package directory → copy path.
COPIES = {
    "apiome-cli": _REPO / "apiome-cli" / "tests" / "fixtures" / "export-surface-parity.json",
    "apiome-ui": _REPO / "apiome-ui" / "tests" / "fixtures" / "exportSurfaceParity.json",
    "apiome-browse": _REPO / "apiome-browse" / "lib" / "__tests__" / "fixtures" / "exportSurfaceParity.json",
}
UPDATE_ENV = "UPDATE_EXPORT_PARITY_GOLDEN"
REGENERATE = "pytest tests/test_export_surface_parity.py --update-golden"

#: Targets whose full previews are recorded in the golden: lossless, lossy and types-only cases.
SAMPLED_TARGETS = ["openapi", "asyncapi", "graphql", "protobuf", "avro", "json-schema", "mcp"]


def _rest_source() -> CanonicalApi:
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD,
                  fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))])
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="widgets"),
                        services=[Service(key="widgets", name="widgets", operations=[op])], types=[widget])


def _event_source() -> CanonicalApi:
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD,
                 fields=[CanonicalField(key="Order.id", name="id", type=TypeRef(name="string"))])
    op = Operation(key="orderPlaced.publish", name="orderPlaced", kind=OperationKind.PUBLISH)
    return CanonicalApi(paradigm=ApiParadigm.EVENT, format="asyncapi-3.0", identity=ApiIdentity(name="orders"),
                        services=[Service(key="orders", name="orders", operations=[op])], types=[order],
                        channels=[Channel(key="orders/placed", address="orders/placed", protocol="kafka")])


def _schema_source() -> CanonicalApi:
    customer = Type(key="Customer", name="Customer", kind=TypeKind.RECORD,
                    fields=[CanonicalField(key="Customer.id", name="id", type=TypeRef(name="string")),
                            CanonicalField(key="Customer.name", name="name", type=TypeRef(name="string"))])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema-2020-12",
                        identity=ApiIdentity(name="customer"), types=[customer])


#: The fixture sources: one per paradigm family the export surfaces present differently.
SOURCES = {"rest-widgets": _rest_source, "event-orders": _event_source, "schema-customer": _schema_source}


def _export_source(name: str) -> ExportSource:
    return ExportSource(api=SOURCES[name](), artifact_id=f"artifact-{name}", version_record_id=f"rev-{name}",
                        version_label="1.0.0")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", TOKEN)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    _jobs.clear()
    yield
    _jobs.clear()
    app.dependency_overrides.pop(validate_authentication, None)


def _patched(name: str):
    """Serve the fixture source to every loader the three route families use."""
    source = _export_source(name)
    return [patch("app.export_routes.load_export_source", return_value=source),
            patch("app.browse_export_routes.load_public_export_source", return_value=source),
            patch("app.mcp_export_routes.load_export_source", return_value=source),
            patch("app.export_job_engine.load_export_source", return_value=source),
            patch("app.mcp_export_routes.db.get_tenant_slug_by_id", return_value="acme")]


class _Surfaces:
    """The three route families, answering for one fixture source."""

    browse = "/v1/browse/tenants/acme/projects/p/versions/1.0.0/export"

    def __init__(self, name: str) -> None:
        self.artifact = f"artifact-{name}"

    def _ok(self, response: Any) -> Dict[str, Any]:
        assert response.status_code == 200, response.text
        return response.json()

    def targets(self) -> Dict[str, List[Dict[str, Any]]]:
        """``{surface: targets}`` for UI/CLI, browse and MCP."""
        mcp = {"X-Internal-Service-Token": TOKEN}
        return {
            "ui+cli": self._ok(client.get(f"/v1/export/acme/targets?artifact={self.artifact}"))["targets"],
            "browse": self._ok(client.get(f"{self.browse}/targets"))["targets"],
            "mcp": self._ok(client.post("/v1/internal/mcp/export/targets",
                                        json={"tenantId": TENANT_ID, "artifact": self.artifact},
                                        headers=mcp))["targets"],
        }

    def previews(self, target: str) -> Dict[str, Dict[str, Any]]:
        """``{surface: fidelity envelope}`` for UI/CLI and browse (the dry runs)."""
        return {
            "ui+cli": self._ok(client.post("/v1/export/acme/preview",
                                           json={"artifact": self.artifact, "target": target}))["fidelity"],
            "browse": self._ok(client.post(f"{self.browse}/preview", json={"target": target}))["fidelity"],
        }

    def mcp_run(self, target: str) -> Dict[str, Any]:
        """The ``version.export`` answer without ``allowLossy`` (``blocked`` when the export is lossy)."""
        return self._ok(client.post("/v1/internal/mcp/export/run",
                                    json={"tenantId": TENANT_ID, "artifact": self.artifact, "target": target,
                                          "confirm": True, "waitSeconds": 30},
                                    headers={"X-Internal-Service-Token": TOKEN}))


def _within(name: str) -> ExitStack:
    """Context: the fixture source served to every route."""
    stack = ExitStack()
    for p in _patched(name):
        stack.enter_context(p)
    return stack


def _shape(value: Any) -> Any:
    """A value's structure — its keys, recursively — without its data (the report *shape*)."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


def _without_projection(fidelity: Dict[str, Any]) -> Dict[str, Any]:
    """The envelope as the golden records it: the projection summary is pinned by its own goldens."""
    return {key: value for key, value in fidelity.items() if key != "projection"}


@pytest.mark.parametrize("name", list(SOURCES))
def test_every_surface_lists_the_same_targets_options_and_tiers(name: str) -> None:
    with _within(name):
        answers = _Surfaces(name).targets()
    reference = answers["ui+cli"]
    assert len(reference) > 40
    for surface, targets in answers.items():
        assert [t["descriptor"]["key"] for t in targets] == [t["descriptor"]["key"] for t in reference], surface
        for got, want in zip(targets, reference):
            key = want["descriptor"]["key"]
            assert got["descriptor"] == want["descriptor"], f"{surface}/{key}: descriptor drifted"
            assert got["fidelity"] == want["fidelity"], f"{surface}/{key}: fidelity badge drifted"
            assert got.get("options_schema") == want.get("options_schema"), f"{surface}/{key}: options drifted"
            assert got.get("default_options") == want.get("default_options"), f"{surface}/{key}: defaults drifted"


@pytest.mark.parametrize("name", list(SOURCES))
def test_every_surface_previews_the_same_report_and_advisory(name: str) -> None:
    with _within(name):
        surfaces = _Surfaces(name)
        keys = [t["descriptor"]["key"] for t in surfaces.targets()["ui+cli"] if t["descriptor"].get("available", True)]
        for key in keys:
            previews = surfaces.previews(key)
            assert previews["browse"] == previews["ui+cli"], f"{name}/{key}: browse preview drifted"
            assert previews["ui+cli"]["advisory"]["message"], f"{name}/{key}: no advisory wording"


@pytest.mark.parametrize("name", list(SOURCES))
@pytest.mark.parametrize("target", SAMPLED_TARGETS)
def test_mcp_answers_with_the_same_report_and_the_advisory_verbatim(name: str, target: str) -> None:
    with _within(name):
        surfaces = _Surfaces(name)
        preview = surfaces.previews(target)["ui+cli"]
        answer = surfaces.mcp_run(target)
    assert answer["state"] in ("blocked", "completed"), answer
    assert answer["state"] == ("completed" if preview["summary"]["tier"] == "lossless" else "blocked")
    assert answer["fidelity"] == preview, f"{name}/{target}: the MCP report drifted"
    assert answer["advisory"] == preview["advisory"]["message"]
    assert _shape(answer["fidelity"]) == _shape(preview)


def _record() -> Dict[str, Any]:
    """The golden: per fixture source, the sampled targets' badges, options and previews.

    Only :data:`SAMPLED_TARGETS` are recorded, so registering a new emitter does not churn the golden;
    every target is still compared across the surfaces live, above.
    """
    recorded: Dict[str, Any] = {"envelope_version": 1, "sources": {}}
    for name in SOURCES:
        with _within(name):
            surfaces = _Surfaces(name)
            targets = surfaces.targets()["ui+cli"]
            previews = {target: _without_projection(surfaces.previews(target)["ui+cli"])
                        for target in SAMPLED_TARGETS}
        recorded["sources"][name] = {
            "paradigm": SOURCES[name]().paradigm.value,
            "targets": [{"key": t["descriptor"]["key"], "tier": t["fidelity"]["tier"],
                         "preserved_percent": t["fidelity"]["preserved_percent"],
                         "options": sorted((t.get("options_schema") or {}).get("properties", {})),
                         "default_options": t.get("default_options") or {}}
                        for t in targets if t["descriptor"]["key"] in SAMPLED_TARGETS],
            "previews": previews,
        }
    return recorded


def _render(recorded: Dict[str, Any]) -> str:
    return json.dumps(recorded, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _updating(request: Any) -> bool:
    return os.environ.get(UPDATE_ENV) == "1" or bool(request.config.getoption("--update-golden"))


def test_the_golden_matches_the_live_routes(request) -> None:
    live = _render(_record())
    if _updating(request):
        GOLDEN_PATH.write_text(live, encoding="utf-8")
        for package, copy in COPIES.items():
            if (_REPO / package).exists():
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_text(live, encoding="utf-8")
        return
    assert GOLDEN_PATH.exists(), f"missing {GOLDEN_PATH.name}; regenerate with `{REGENERATE}`"
    assert GOLDEN_PATH.read_text(encoding="utf-8") == live, (
        f"the export surfaces drifted from {GOLDEN_PATH.name}; if intended, regenerate with `{REGENERATE}`, "
        "review the diff and commit the golden with its copies"
    )


@pytest.mark.parametrize("package", list(COPIES))
def test_each_client_surface_copy_equals_the_golden(package: str) -> None:
    copy = COPIES[package]
    if not (_REPO / package).exists():
        pytest.skip(f"{package} is not in this checkout")
    assert copy.exists(), f"missing {copy.relative_to(_REPO)}; regenerate with `{REGENERATE}`"
    assert copy.read_text(encoding="utf-8") == GOLDEN_PATH.read_text(encoding="utf-8"), (
        f"{copy.relative_to(_REPO)} is stale; regenerate with `{REGENERATE}`"
    )


def test_the_golden_records_lossless_lossy_and_types_only_advisories() -> None:
    recorded = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    tiers = {preview["summary"]["tier"] for source in recorded["sources"].values()
             for preview in source["previews"].values()}
    assert {"lossless", "lossy", "types-only"} <= tiers
    for source in recorded["sources"].values():
        for preview in source["previews"].values():
            advisory = preview["advisory"]
            assert advisory["show"] == (preview["summary"]["tier"] != "lossless")
            assert advisory["headline"] and advisory["message"]
