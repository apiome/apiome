"""Tests for the public browse export surface — ``/v1/browse/…/export/*`` — MFX-7.1 (#3860).

Pins the route contract of the anonymous export path:

* all three endpoints work **without any credentials** — the public counterpart of the
  authenticated ``/v1/export`` surface;
* the source is resolved by slugs through :func:`app.export_source.load_public_export_source`,
  whose uniform 404 (private / draft / unknown are indistinguishable) surfaces unchanged;
* ``GET …/export/targets`` returns every registered target with its per-source fidelity badge
  and echoes the slug coordinates + resolved revision;
* ``POST …/export/preview`` returns the full fidelity envelope (report + advisory + summary)
  without emitting;
* ``POST …/export/document`` emits through the same Emitter SPI (JSON default, YAML under
  ``Accept: application/yaml``) and honours per-target options;
* loader/emitter errors map to the right HTTP statuses (404 / 422 / 400).

The public source loader is faked here — its own DB-backed logic is exercised in
``test_export_source.py`` — so these tests pin only the route wiring.
"""

from __future__ import annotations

from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.export_source import ExportSource, ExportSourceError
from app.main import app

client = TestClient(app)

_BASE = "/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export"

_LOADER = "app.browse_export_routes.load_public_export_source"


def _source() -> ExportSource:
    """A loaded public source: a REST API with one operation + one type, at a fixed revision."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


_NOT_FOUND = ExportSourceError(
    "Published version '1.0.0' was not found for 'acme'/'widgets'.", status_code=404
)


# ---------------------------------------------------------------------------
# GET …/export/targets
# ---------------------------------------------------------------------------
def test_public_targets_no_auth_required():
    """The targets list is served to a fully anonymous caller — no credentials of any kind."""
    with patch(_LOADER, return_value=_source()) as loader:
        response = client.get(f"{_BASE}/targets")

    assert response.status_code == 200
    loader.assert_called_once_with("acme", "widgets", "1.0.0")
    body = response.json()
    assert body["tenant_slug"] == "acme"
    assert body["project_slug"] == "widgets"
    assert body["version_slug"] == "1.0.0"
    assert body["version_record_id"] == "rev-uuid-1"
    assert body["version_label"] == "1.0.0"


def test_public_targets_returns_per_target_fidelity():
    """Every registered target is listed with a tier + preserved-% badge, like the ADE surface."""
    with patch(_LOADER, return_value=_source()):
        response = client.get(f"{_BASE}/targets")

    assert response.status_code == 200
    by_key = {t["descriptor"]["key"]: t for t in response.json()["targets"]}
    assert "openapi" in by_key and "sample" in by_key
    assert by_key["openapi"]["fidelity"]["tier"] == "lossless"
    assert by_key["openapi"]["fidelity"]["preserved_percent"] == 100
    # A schema-only target drops the operation → types-only.
    assert by_key["sample"]["fidelity"]["tier"] == "types-only"
    # The registry's descriptor + options are surfaced alongside the badge.
    assert "options_schema" in by_key["openapi"]
    assert "capability_profile" in by_key["openapi"]


def test_public_targets_404_when_not_published_public():
    """A private/draft/unknown version is a uniform 404 — the route cannot confirm existence."""
    with patch(_LOADER, side_effect=_NOT_FOUND):
        response = client.get(f"{_BASE}/targets")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST …/export/preview
# ---------------------------------------------------------------------------
def test_public_preview_returns_full_envelope():
    """The preview returns the full report + advisory + summary for the chosen target."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/preview", json={"target": "sample"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_slug"] == "acme"
    assert body["version_record_id"] == "rev-uuid-1"
    fidelity = body["fidelity"]
    assert fidelity["target"]["key"] == "sample"
    assert fidelity["summary"]["tier"] == "types-only"
    assert len(fidelity["report"]["items"]) == 2
    assert fidelity["advisory"]["show"] is True


def test_public_preview_lossless_target_hides_advisory():
    """OpenAPI → OpenAPI is lossless, so the advisory is suppressed — same as the ADE."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/preview", json={"target": "openapi"})
    assert response.status_code == 200
    fidelity = response.json()["fidelity"]
    assert fidelity["summary"]["tier"] == "lossless"
    assert fidelity["advisory"]["show"] is False


def test_public_preview_400_for_unknown_target():
    """An unresolvable target is a 400 (the export service's status)."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/preview", json={"target": "no-such-target"})
    assert response.status_code == 400
    assert "unsupported export target" in response.json()["detail"].lower()


def test_public_preview_404_when_not_published_public():
    with patch(_LOADER, side_effect=_NOT_FOUND):
        response = client.post(f"{_BASE}/preview", json={"target": "openapi"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST …/export/document
# ---------------------------------------------------------------------------
def test_public_document_emits_json_download():
    """The emit route returns the document as JSON by default, with a filename hint."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/document", json={"target": "asyncapi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert 'filename="asyncapi.json"' in response.headers["content-disposition"]
    body = response.json()
    assert body["asyncapi"] == "3.1.0"
    assert body["info"]["title"] == "widgets"


def test_public_document_emits_yaml_with_accept():
    """``Accept: application/yaml`` serializes the same document as YAML with a .yaml filename."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(
            f"{_BASE}/document",
            json={"target": "asyncapi"},
            headers={"Accept": "application/yaml"},
        )

    assert response.status_code == 200
    assert "yaml" in response.headers["content-type"]
    assert 'filename="asyncapi.yaml"' in response.headers["content-disposition"]
    document = yaml.safe_load(response.text)
    assert document["asyncapi"] == "3.1.0"


def test_public_document_applies_emit_options():
    """Per-target emit options flow through the public path too."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(
            f"{_BASE}/document",
            json={"target": "asyncapi", "options": {"include_channels": False}},
        )
    assert response.status_code == 200
    body = response.json()
    assert "operations" not in body
    assert "channels" not in body


def test_public_document_400_for_unknown_target():
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/document", json={"target": "no-such-target"})
    assert response.status_code == 400


def test_public_document_404_when_not_published_public():
    """Private artifacts are unavailable on the public download path (MFX-7.1 acceptance)."""
    with patch(_LOADER, side_effect=_NOT_FOUND):
        response = client.post(f"{_BASE}/document", json={"target": "asyncapi"})
    assert response.status_code == 404


def test_public_document_422_when_source_unreconstructable():
    with patch(
        _LOADER,
        side_effect=ExportSourceError("no captured source", status_code=422),
    ):
        response = client.post(f"{_BASE}/document", json={"target": "asyncapi"})
    assert response.status_code == 422


def test_public_document_rejects_unknown_body_fields():
    """The public request model is closed (extra='forbid') — no smuggling artifact overrides."""
    with patch(_LOADER, return_value=_source()):
        response = client.post(
            f"{_BASE}/document",
            json={"target": "asyncapi", "artifact": "someone-elses-project"},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# MFX-7.3 guards — rate limit + download size cap
# ---------------------------------------------------------------------------
def test_public_export_rate_limit_returns_429(monkeypatch):
    """Anonymous export routes enforce a dedicated per-IP rate limit (MFX-7.3)."""
    from app.config import settings
    from app.rate_limit import FixedWindowRateLimiter

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "public_browse_export_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with patch("app.public_export_guards._public_export_limiter", FixedWindowRateLimiter()):
        with patch(_LOADER, return_value=_source()):
            assert client.get(f"{_BASE}/targets").status_code == 200
            assert client.get(f"{_BASE}/targets").status_code == 200
            third = client.get(f"{_BASE}/targets")
    assert third.status_code == 429
    assert third.headers.get("Retry-After")
    assert "rate limit" in third.json()["detail"].lower()


def test_public_document_413_when_over_download_size_cap(monkeypatch):
    """Oversized emitted documents are rejected on the public download path (MFX-7.3)."""
    from app.config import settings

    monkeypatch.setattr(settings, "public_browse_export_document_max_bytes", 32)
    with patch(_LOADER, return_value=_source()):
        response = client.post(f"{_BASE}/document", json={"target": "asyncapi"})
    assert response.status_code == 413
    assert "download limit" in response.json()["detail"].lower()
