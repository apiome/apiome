"""FHIR healthcare API import — MFI-20.1 (#3985).

The gaps MFI-20.1 closes over the MFI-22.2 FHIR adapter, each pinned without a network:

* **R4 / R5 / R6** — ``fhirVersion`` maps to a release (R4, R4B, R5, R6 incl. ballots), recorded on
  the model's extras (hashed, so a release move is a new version) and only when declared (so
  profiles imported before keep their fingerprint);
* **CapabilityStatement → services/operations** — one service per resource, an operation per
  *declared* interaction, typed search parameters, ``$operation``s (type and system level);
* **cross-release diff** — the same profile in R4 and R5 gets a new version from
  :func:`app.versioning.decide_version`, and the release change is in the model;
* **live ``/metadata``** — :meth:`FhirImportSource.discover` and the catalog live-refresh runner;
* **lint** — the FHIR hygiene rule pack fires on what it should and not on clean fixtures;
* **fixtures** — two servers (R4 06, R5 07, plus an R6 ballot 10) and two profiles across releases.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

from app import catalog_refresh
from app.canonical_model import CanonicalApi
from app.fhir_import_source import FhirImportSource, metadata_url
from app.fhir_parser import fhir_release, parse_fhir
from app.fingerprint import fingerprint
from app.import_source import DetectionInput, ImportSourceError, get_import_source
from app.lint_engine import lint_canonical_model

_FHIR = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "fhir"


def _text(name: str) -> str:
    return (_FHIR / name).read_text(encoding="utf-8")


def _api(name_or_text: str) -> CanonicalApi:
    source = FhirImportSource()
    text = _text(name_or_text) if name_or_text.endswith(".json") else name_or_text
    return source.normalize(source.parse(text))


def _ops(api: CanonicalApi, service: str) -> Dict[str, Any]:
    svc = next(s for s in api.services if s.name == service)
    return {f"{o.http_method} {o.http_path}": o for o in svc.operations}


def _rules(api: CanonicalApi) -> list:
    return sorted(f.rule for f in lint_canonical_model(api).findings if f.rule.startswith("fhir."))


# ===========================================================================
# Releases
# ===========================================================================


@pytest.mark.parametrize(
    ("version", "release"),
    [("4.0.1", "R4"), ("4.3.0", "R4B"), ("5.0.0", "R5"), ("6.0.0-ballot3", "R6"), ("6.0.0", "R6"),
     ("3.0.2", None), ("4.1.0", None), ("nope", None), ("", None), (None, None)],
)
def test_fhir_version_maps_to_its_release(version, release) -> None:
    assert fhir_release(version) == release


@pytest.mark.parametrize(
    ("name", "version", "release"),
    [
        ("06-capability-statement.json", "4.0.1", "R4"),
        ("07-capability-statement-r5.json", "5.0.0", "R5"),
        ("10-capability-statement-r6-ballot.json", "6.0.0-ballot3", "R6"),
        ("08-patient-profile-r4.json", "4.0.1", "R4"),
        ("09-patient-profile-r5.json", "5.0.0", "R5"),
    ],
)
def test_every_model_records_its_release(name, version, release) -> None:
    api = _api(name)
    assert (api.extras["fhir_version"], api.extras["fhir_release"]) == (version, release)


def test_a_profile_without_a_version_records_none_so_its_fingerprint_is_unchanged() -> None:
    api = _api("02-patient-structuredefinition.json")
    assert "fhir_version" not in api.extras and "fhir_release" not in api.extras
    assert all("definition" not in e for e in api.extras["fhir_structure_definition"]["elements"])


# ===========================================================================
# CapabilityStatement → services / operations
# ===========================================================================


def test_a_capability_statement_is_parsed_as_the_servers_api() -> None:
    document = parse_fhir(_text("07-capability-statement-r5.json"))
    assert document.kind == "capability_statement"
    statement = document.capability_statement
    assert (statement.name, statement.version, statement.base_url) == (
        "LabResultsServer", "2.1.0", "https://lab.example.org/fhir")
    assert [r.type for r in statement.resources] == ["DiagnosticReport", "Observation", "Specimen"]
    assert [o.name for o in statement.system_operations] == ["everything"]


def test_only_declared_interactions_become_operations() -> None:
    api = _api("07-capability-statement-r5.json")
    assert set(_ops(api, "Observation")) == {
        "GET /Observation/{id}", "POST /Observation", "PUT /Observation/{id}", "PATCH /Observation/{id}",
        "DELETE /Observation/{id}", "GET /Observation",
    }
    assert set(_ops(api, "DiagnosticReport")) == {
        "GET /DiagnosticReport/{id}", "GET /DiagnosticReport", "GET /DiagnosticReport/{id}/_history",
        "POST /DiagnosticReport/$summary",
    }
    assert set(_ops(api, "Specimen")) == {"GET /Specimen/{id}", "GET /Specimen"}


def test_search_parameters_are_typed_query_parameters() -> None:
    search = _ops(_api("07-capability-statement-r5.json"), "Observation")["GET /Observation"]
    params = {p.name: (p.location.value, p.type.name, p.extras["fhir_search_type"]) for p in search.parameters}
    assert params == {
        "subject": ("query", "string", "reference"),
        "value-quantity": ("query", "string", "quantity"),
        "component-value-quantity": ("query", "double", "number"),
    }


def test_interaction_shapes() -> None:
    ops = _ops(_api("07-capability-statement-r5.json"), "Observation")
    create = ops["POST /Observation"]
    assert [m.role.value for m in create.messages] == ["request", "response"]
    assert create.messages[1].status_code == "201"
    delete = ops["DELETE /Observation/{id}"]
    assert [(m.role.value, m.status_code, m.payload) for m in delete.messages] == [("response", "204", None)]
    read = ops["GET /Observation/{id}"]
    assert [(p.name, p.location.value, p.required) for p in read.parameters] == [("id", "path", True)]
    assert read.messages[0].payload.name.endswith("Observation")
    assert read.extras["fhir_interaction"] == "read"


def test_dollar_operations_at_type_and_system_level() -> None:
    api = _api("07-capability-statement-r5.json")
    summary = _ops(api, "DiagnosticReport")["POST /DiagnosticReport/$summary"]
    assert summary.name == "$summary"
    assert summary.extras["fhir_operation_definition"].endswith("report-summary")
    assert set(_ops(api, "system")) == {"POST /$everything"}


def test_resource_types_name_their_profiles() -> None:
    api = _api("07-capability-statement-r5.json")
    types = {t.name: t.extras for t in api.types}
    assert types["DiagnosticReport"]["fhir_profile"].endswith("lab-report")
    assert types["Observation"]["fhir_supported_profiles"] == ["http://hl7.org/fhir/StructureDefinition/vitalsigns"]
    assert types["Specimen"]["fhir_profile"] is None


def test_a_client_mode_rest_entry_is_not_the_servers_api() -> None:
    statement = json.loads(_text("10-capability-statement-r6-ballot.json"))
    statement["rest"].append({"mode": "client", "resource": [{"type": "Claim", "interaction": [{"code": "read"}]}]})
    api = _api(json.dumps(statement))
    assert [s.name for s in api.services] == ["Patient"]


def test_the_two_servers_differ() -> None:
    r4, r5 = _api("06-capability-statement.json"), _api("07-capability-statement-r5.json")
    assert {s.name for s in r4.services} == {"Patient", "Observation"}
    assert {s.name for s in r5.services} == {"DiagnosticReport", "Observation", "Specimen", "system"}


# ===========================================================================
# Cross-release diff
# ===========================================================================


def test_the_same_profile_in_r4_and_r5_is_a_new_version() -> None:
    from app.versioning import PreviousVersion, decide_version

    r4, r5 = _api("08-patient-profile-r4.json"), _api("09-patient-profile-r5.json")
    assert fingerprint(r4).fingerprint != fingerprint(r5).fingerprint
    previous = PreviousVersion(version_tag="1.0.0", fingerprint=fingerprint(r4).fingerprint, model=r4)
    decision = decide_version(r5, previous=previous, when=datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert decision.created


def test_only_the_release_changing_is_still_a_change() -> None:
    r4 = json.loads(_text("08-patient-profile-r4.json"))
    r5_same = dict(r4, fhirVersion="5.0.0")
    assert fingerprint(_api(json.dumps(r4))).fingerprint != fingerprint(_api(json.dumps(r5_same))).fingerprint


# ===========================================================================
# Live /metadata
# ===========================================================================


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://fhir.example.com/r4", "https://fhir.example.com/r4/metadata"),
        ("https://fhir.example.com/r4/", "https://fhir.example.com/r4/metadata"),
        ("https://fhir.example.com/r4/metadata", "https://fhir.example.com/r4/metadata"),
        ("https://fhir.example.com/r4?_format=json", "https://fhir.example.com/r4/metadata?_format=json"),
    ],
)
def test_metadata_url(given, expected) -> None:
    assert metadata_url(given) == expected


@pytest.mark.parametrize("bad", ["ftp://x/fhir", "fhir.example.com", ""])
def test_metadata_url_needs_http(bad) -> None:
    with pytest.raises(ImportSourceError):
        metadata_url(bad)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def public_urls(monkeypatch):
    """Let the example hosts through the SSRF pre-check (they do not resolve in tests)."""
    monkeypatch.setattr("app.live_fetch.check_public_url", lambda url, *, what: None)


def test_discover_reads_the_capability_statement(public_urls) -> None:
    seen: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), accept=request.headers.get("accept"),
                    auth=request.headers.get("authorization"))
        return httpx.Response(200, text=_text("07-capability-statement-r5.json"))

    document = FhirImportSource().discover(
        "https://lab.example.org/fhir", auth_type="bearer", auth_payload={"token": "t0k"}, client=_client(handler)
    )
    assert document.kind == "capability_statement"
    assert seen["url"] == "https://lab.example.org/fhir/metadata"
    assert "application/fhir+json" in seen["accept"]
    assert seen["auth"] == "Bearer t0k"


def test_discover_refuses_a_body_that_is_not_a_capability_statement(public_urls) -> None:
    client = _client(lambda request: httpx.Response(200, text=_text("08-patient-profile-r4.json")))
    with pytest.raises(ImportSourceError, match="did not return a FHIR CapabilityStatement"):
        FhirImportSource().discover("https://fhir.example.com/r4", client=client)


def test_discover_maps_a_404(public_urls) -> None:
    client = _client(lambda request: httpx.Response(404, text="nope"))
    with pytest.raises(ImportSourceError):
        FhirImportSource().discover("https://fhir.example.com/r4", client=client)


def test_discover_refuses_a_private_address() -> None:
    with pytest.raises(ImportSourceError, match="not allowed"):
        FhirImportSource().discover("http://127.0.0.1/fhir")


def test_the_adapter_declares_live_discovery_and_detects_r5() -> None:
    source = get_import_source("fhir")
    assert source.supports_live_discovery is True
    text = _text("07-capability-statement-r5.json")
    assert source.detect(DetectionInput(text=text, filename="metadata.json")).format == "fhir"


def test_fhir_is_a_live_refresh_adapter(monkeypatch) -> None:
    assert "fhir" in catalog_refresh.refreshable_adapters()
    calls: Dict[str, Any] = {}

    def fake_discover(self, endpoint, **kwargs):
        calls.update(endpoint=endpoint, **kwargs)
        return parse_fhir(_text("06-capability-statement.json"))

    monkeypatch.setattr(FhirImportSource, "discover", fake_discover)
    result = catalog_refresh.get_discovery_runner("fhir")(
        "https://fhir.example.com/r4", {}, "bearer", {"token": "t"}, 7.0
    )
    assert calls == {"endpoint": "https://fhir.example.com/r4", "timeout": 7.0, "auth_type": "bearer",
                     "auth_payload": {"token": "t"}}
    assert result.fingerprint and result.filename == "CapabilityStatement.fhir.json"
    assert result.model is not None and {s.name for s in result.model.services} == {"Patient", "Observation"}


# ===========================================================================
# Lint
# ===========================================================================


def test_clean_fixtures_have_no_fhir_findings() -> None:
    for name in ("06-capability-statement.json", "08-patient-profile-r4.json", "09-patient-profile-r5.json",
                 "10-capability-statement-r6-ballot.json"):
        assert _rules(_api(name)) == [], name


def test_the_r5_server_flags_its_unprofiled_unsearchable_specimen() -> None:
    findings = [f for f in lint_canonical_model(_api("07-capability-statement-r5.json")).findings
                if f.rule.startswith("fhir.")]
    assert sorted((f.rule, f.path) for f in findings) == [
        ("fhir.capability-profile", "CapabilityStatement/rest/resource/Specimen"),
        ("fhir.capability-search", "CapabilityStatement/rest/resource/Specimen/searchParam"),
    ]


def test_profile_hygiene_rules() -> None:
    profile = json.loads(_text("08-patient-profile-r4.json"))
    for key in ("url", "fhirVersion", "baseDefinition"):
        profile.pop(key)
    profile["status"] = "draft"
    profile["differential"]["element"][0].pop("short")
    assert _rules(_api(json.dumps(profile))) == [
        "fhir.element-short", "fhir.profile-base", "fhir.profile-status", "fhir.profile-url", "fhir.profile-version",
    ]


def test_a_server_without_a_fhir_version_is_flagged() -> None:
    statement = json.loads(_text("10-capability-statement-r6-ballot.json"))
    statement.pop("fhirVersion")
    assert _rules(_api(json.dumps(statement))) == ["fhir.capability-version"]


def test_a_resource_instance_gets_no_fhir_findings() -> None:
    assert _rules(_api("01-patient.json")) == []
