"""Alternate intake on the import-source registry (MFI-26.5, #4098).

A format may offer a way in beyond File / URL / Clipboard (live introspection, reflection, a
registry crawl). It declares that as ``ImportSource.alternate_intake`` and the descriptor carries
it on ``GET /v1/import/sources``, where the import wizard turns it into a source card. These tests
pin the two halves of that contract:

1. **Nothing declares one today.** Several adapters advertise ``supports_live_discovery``, but the
   import pipeline runs none of their discovery methods, so none may offer a card.
2. **Declaring one is enough.** A registered adapter with ``alternate_intake`` set reaches the wire
   with no route change.
"""

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.import_source import (
    _REGISTRY,
    NO_MATCH,
    ApiParadigm,
    ImportSource,
    ImportSourceAlternateIntake,
    InputKind,
    describe_import_sources,
    load_builtin_import_sources,
)
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        "tenant_id": "t1",
        "user_id": "u1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.clear()


def test_no_registered_adapter_declares_an_alternate_intake():
    load_builtin_import_sources()
    descriptors = describe_import_sources()
    assert descriptors, "the registry should not be empty"
    declared = [d.key for d in descriptors if d.alternate_intake is not None]
    assert declared == []


def test_live_discovery_alone_does_not_offer_an_alternate_intake():
    by_key = {s["key"]: s for s in client.get("/v1/import/sources").json()["sources"]}
    live = [key for key, s in by_key.items() if s["supports_live_discovery"]]
    # GraphQL introspection and gRPC reflection exist at the adapter level…
    assert {"graphql", "grpc"} <= set(live)
    # …but nothing runs them as an import yet, so neither offers a card.
    assert all(by_key[key]["alternate_intake"] is None for key in live)


def test_a_declared_alternate_intake_reaches_the_wire():
    class _ProbeImportSource(ImportSource):  # not auto-registered
        key = "probe-intake"
        label = "Probe Intake"
        description = "A throwaway adapter used only by this test."
        icon = "boxes"
        paradigm = ApiParadigm.GRAPH
        input_kinds = (InputKind.FILE, InputKind.DISCOVERY)
        supports_live_discovery = True
        alternate_intake = ImportSourceAlternateIntake(
            kind="introspection",
            label="Live introspection",
            description="Read the schema from a running endpoint",
            icon="radar",
        )
        formats = ("probe-1.0",)

        def detect(self, payload):  # pragma: no cover - not exercised here
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return raw

        def normalize(self, native_ast, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    _REGISTRY["probe-intake"] = _ProbeImportSource
    try:
        by_key = {s["key"]: s for s in client.get("/v1/import/sources").json()["sources"]}
        assert by_key["probe-intake"]["alternate_intake"] == {
            "kind": "introspection",
            "label": "Live introspection",
            "description": "Read the schema from a running endpoint",
            "icon": "radar",
        }
    finally:
        _REGISTRY.pop("probe-intake", None)


def test_the_openapi_document_describes_the_field():
    schema = app.openapi()["components"]["schemas"]
    descriptor = schema["ImportSourceDescriptor"]["properties"]
    assert "alternate_intake" in descriptor
    intake = schema["ImportSourceAlternateIntake"]
    assert set(intake["required"]) == {"kind", "label", "description", "icon"}
