"""Unit + contract tests for the destination capability & documentation registry — EFP-1.2 (#4811).

Pins the ticket's acceptance criteria:

* **coverage** — every runtime-available emitter has a capability entry, with an explicit
  availability state (available / experimental / unavailable) for the fallback cases;
* **reviewed, authoritative docs** — every registered documentation link passes the host
  allowlist, and destinations without a stable public spec get a truthful
  ``documentation_unavailable`` fallback rather than an invented link;
* **separated cause categories** — a reviewed explanation exists for every reason code, and a
  destination-format link is offered *only* for a genuine destination-specification limit,
  never for an emitter / source / option / redaction cause;
* **versioned evidence** — the registry version and emitter/tool versions appear in the entry
  and in projection evidence;
* **safety** — an unsafe or off-allowlist URL is rejected both by :func:`validate_documentation_url`
  and by the :class:`DocumentationEvidence` model, and no reason code outside the taxonomy is used.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import validate_authentication
from app.avro_emitter import AvroEmitter
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
from app.capability_registry import (
    ALLOWED_DOCUMENTATION_HOSTS,
    REASON_CODES,
    REGISTRY_VERSION,
    CapabilityRegistrySnapshot,
    DestinationAvailability,
    DocumentationEvidence,
    UnsafeDocumentationUrlError,
    capability_for,
    documentation_for,
    explanation_for,
    is_safe_documentation_url,
    reason_explanation,
    reason_explanations,
    registry_snapshot,
    validate_documentation_url,
)
from app.emitter import describe_emit_targets, load_builtin_emitters
from app.export_projection import ProjectionStatus, build_projection_manifest
from app.main import app
from app.openapi_emitter import OpenApiEmitter
from app.projection_taxonomy import ProjectionReason
from app.sample_emitter import SampleEmitter

# ---------------------------------------------------------------------------
# URL allowlist validation (the unsafe-URL guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://spec.openapis.org/oas/v3.1.0.html",
        "https://protobuf.dev/programming-guides/proto3/",
        "https://avro.apache.org/docs/1.11.1/specification/",
    ],
)
def test_validate_documentation_url_accepts_allowlisted_https(url: str):
    assert validate_documentation_url(url) == url
    assert is_safe_documentation_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://spec.openapis.org/oas/v3.1.0.html",  # not https
        "javascript:alert(1)",  # dangerous scheme
        "data:text/html,<script>alert(1)</script>",  # dangerous scheme
        "https://evil.test/oas",  # off-allowlist host
        "https://spec.openapis.org.evil.test/oas",  # look-alike host
        "https://user:pass@spec.openapis.org/oas",  # embedded credentials
        "https://spec.openapis.org:8443/oas",  # explicit port
        "ftp://spec.openapis.org/oas",  # wrong scheme
        "spec.openapis.org/oas",  # no scheme/host
        "",  # empty
    ],
)
def test_validate_documentation_url_rejects_unsafe(url: str):
    with pytest.raises(UnsafeDocumentationUrlError):
        validate_documentation_url(url)
    assert is_safe_documentation_url(url) is False


def test_documentation_evidence_model_rejects_unsafe_url():
    """An unsafe URL cannot even enter a model instance (rejected at construction)."""
    with pytest.raises(ValidationError):
        DocumentationEvidence(url="http://evil.test/spec")
    # A safe URL and a url-less fallback both construct fine.
    assert DocumentationEvidence(url="https://spec.graphql.org/October2021/").url
    assert DocumentationEvidence(documentation_unavailable=True, note="n/a").url is None


def test_allowlist_hosts_are_normalized():
    for host in ALLOWED_DOCUMENTATION_HOSTS:
        assert host == host.lower()
        assert "/" not in host and "@" not in host and ":" not in host


# ---------------------------------------------------------------------------
# Coverage: every runtime emitter has an entry with a safe/annotated doc state
# ---------------------------------------------------------------------------


def test_every_registered_emitter_has_a_capability_entry():
    """Snapshot has exactly one entry per registered destination, all links safe."""
    load_builtin_emitters()
    snapshot = registry_snapshot()

    described = {t.descriptor.key for t in describe_emit_targets()}
    entry_keys = {d.key for d in snapshot.destinations}
    assert entry_keys == described
    assert len(snapshot.destinations) == len(described)

    for dest in snapshot.destinations:
        # Either a safe authoritative link, or a truthful documentation-unavailable fallback.
        if dest.documentation.url is not None:
            assert is_safe_documentation_url(dest.documentation.url), dest.key
            assert dest.documentation.documentation_unavailable is False
        else:
            assert dest.documentation.documentation_unavailable is True, dest.key
            assert dest.documentation.note, dest.key
        assert dest.registry_version == REGISTRY_VERSION
        assert dest.emitter_version


def test_availability_states_are_explicit():
    """A runnable emitter is available; the sample target is explicitly experimental."""
    assert capability_for(OpenApiEmitter).availability is DestinationAvailability.AVAILABLE
    assert capability_for(SampleEmitter).availability is DestinationAvailability.EXPERIMENTAL


def test_known_destination_carries_reviewed_versioned_docs():
    cap = capability_for(OpenApiEmitter)
    assert cap.documentation.specification == "OpenAPI Specification"
    assert cap.documentation.version == "3.1.0"
    assert cap.documentation.url and "spec.openapis.org" in cap.documentation.url
    assert cap.documentation.documentation_unavailable is False


# ---------------------------------------------------------------------------
# Separated cause categories + reason-scoped documentation
# ---------------------------------------------------------------------------


def test_one_reviewed_explanation_per_reason_code():
    explanations = reason_explanations()
    assert {e.reason for e in explanations} == set(ProjectionReason)
    for reason in ProjectionReason:
        assert reason_explanation(reason).summary_template
        assert reason_explanation(reason).remediation


def test_only_destination_unsupported_offers_a_format_link():
    """The distinction that keeps destination limits separate from emitter/source causes."""
    applies = {
        r for r in ProjectionReason if reason_explanation(r).destination_documentation_applies
    }
    assert applies == {ProjectionReason.DESTINATION_UNSUPPORTED}


def test_documentation_for_is_reason_scoped():
    # A genuine destination limit → the destination's authoritative link.
    dest_doc = documentation_for(OpenApiEmitter, ProjectionReason.DESTINATION_UNSUPPORTED)
    assert dest_doc.url and "spec.openapis.org" in dest_doc.url
    # An emitter / source / option / redaction cause → no destination-format link.
    for reason in (
        ProjectionReason.EMITTER_UNSUPPORTED,
        ProjectionReason.SOURCE_INCOMPLETE,
        ProjectionReason.SOURCE_PARSE_LIMIT,
        ProjectionReason.OPTION_EXCLUDED,
        ProjectionReason.SECURITY_REDACTED,
    ):
        doc = documentation_for(OpenApiEmitter, reason)
        assert doc.url is None
        assert doc.documentation_unavailable is True
    # A reason-less (target-level) lookup returns the destination documentation.
    assert documentation_for(OpenApiEmitter).url == dest_doc.url


def test_explanation_names_the_construct_safely():
    text = explanation_for(ProjectionReason.DESTINATION_UNSUPPORTED, "User.email")
    assert "User.email" in text
    generic = explanation_for(ProjectionReason.DESTINATION_UNSUPPORTED)
    assert "this construct" in generic


def test_reason_codes_match_the_taxonomy():
    assert REASON_CODES == frozenset(r.value for r in ProjectionReason)
    assert set(registry_snapshot().reason_codes) == REASON_CODES


# ---------------------------------------------------------------------------
# Registry/tool versions appear in projection evidence
# ---------------------------------------------------------------------------


def _lossy_api() -> CanonicalApi:
    """A REST source whose operation is dropped when exported to a schema-only Avro target."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )


def test_manifest_carries_registry_version_and_reason_scoped_evidence():
    manifest = build_projection_manifest(_lossy_api(), AvroEmitter)
    assert manifest.target.registry_version == REGISTRY_VERSION
    assert manifest.target.availability is DestinationAvailability.AVAILABLE

    non_preserved = [e for e in manifest.projects_edges if e.status is not ProjectionStatus.RETAINED]
    assert non_preserved, "the lossy fixture must drop/approximate at least one construct"
    for edge in non_preserved:
        assert edge.reason is not None
        assert edge.explanation, edge.id
        assert edge.documentation is not None
        # Destination limits carry a link; other causes carry the truthful fallback.
        if edge.reason is ProjectionReason.DESTINATION_UNSUPPORTED:
            assert edge.documentation.url and is_safe_documentation_url(edge.documentation.url)
        else:
            assert edge.documentation.documentation_unavailable is True

    # Retained edges carry no reason-scoped evidence.
    for edge in manifest.projects_edges:
        if edge.status is ProjectionStatus.RETAINED:
            assert edge.explanation is None
            assert edge.documentation is None


def test_registry_version_changes_the_snapshot_hash():
    """Folding the registry version into the hash makes a registry revision a new snapshot."""
    api = _lossy_api()
    base = build_projection_manifest(api, AvroEmitter).manifest_hash
    with patch("app.export_projection.REGISTRY_VERSION", "999"):
        bumped = build_projection_manifest(api, AvroEmitter).manifest_hash
    assert base != bumped


# ---------------------------------------------------------------------------
# REST contract: the endpoint returns a valid, safe snapshot
# ---------------------------------------------------------------------------


client = TestClient(app)
_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}


@pytest.fixture()
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def test_capability_registry_endpoint_returns_safe_snapshot(_auth):
    response = client.get("/v1/export/test-tenant/capability-registry")
    assert response.status_code == 200
    body = response.json()

    snapshot = CapabilityRegistrySnapshot.model_validate(body)
    assert snapshot.version == REGISTRY_VERSION
    assert set(snapshot.reason_codes) == REASON_CODES
    assert {e.reason for e in snapshot.reasons} == set(ProjectionReason)
    assert snapshot.destinations

    # Contract: no unknown reason code, no unsafe URL escapes to the wire.
    for code in snapshot.reason_codes:
        assert code in REASON_CODES
    for dest in snapshot.destinations:
        if dest.documentation.url is not None:
            assert is_safe_documentation_url(dest.documentation.url), dest.key


def test_capability_registry_endpoint_requires_authentication():
    app.dependency_overrides.clear()
    response = client.get("/v1/export/test-tenant/capability-registry")
    assert response.status_code == 401
