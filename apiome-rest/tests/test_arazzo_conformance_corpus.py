"""Arazzo conformance corpus — COA-1.4 (#7040).

Foreign-source goldens: Arazzo documents Apiome did not write — the OpenAPI Initiative's 1.0.0 examples and
1.1.0 schema fixtures, and the Arazzo files Redocly, Spectral and Specmatic publish — selected from the
example corpus by ``origin: derived`` (``apiome-ui/examples/arazzo{,-1.1}/``, each linked in the manifest's
``source_url``). For every one:

* **schema** — the document passes the official OAI JSON Schema for the version it declares;
* **import** — the Arazzo adapter detects and normalizes it;
* **rebuild** — exported from the canonical model alone (no raw document, the path a stored revision takes),
  the rebuilt document equals the source field for field and declares the same version, so nothing the
  source wrote is lost or invented;
* **round trip** — the rebuilt document re-imports to an identical model, with nothing unexplained.

The set must cover both readable versions, all three third-party tools, and the 1.1 constructs the issue
names: ``$components`` references, runtime expressions and ``querystring`` parameters — plus the 1.1
``channelPath`` step target and ``$self`` the corpus surfaced. The canonical snapshot of each document is
pinned by ``tests/test_corpus_golden.py`` like every other corpus entry.

The unit tests at the end pin the 1.1 fields COA-1.4 taught the importer and the rebuild path to keep.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import yaml
from corpus_loader import CorpusEntry, Origin, load_corpus

from app.arazzo_emitter import ArazzoEmitter
from app.arazzo_import_source import ArazzoImportSource
from app.arazzo_roundtrip import RoundTripStatus, arazzo_schema_violations, round_trip_arazzo
from app.arazzo_spec import resolve_step_target, step_is_async, validate_arazzo_semantics
from app.canonical_model import CanonicalApi
from app.import_source import DetectionInput

#: The foreign-source entries: every Arazzo corpus file copied or adapted from a third party.
FOREIGN: List[CorpusEntry] = sorted(
    load_corpus(format="arazzo", origin=Origin.DERIVED), key=lambda entry: entry.path
)


def _document(entry: CorpusEntry) -> Dict[str, Any]:
    return yaml.safe_load(entry.read_text())


def _import(entry: CorpusEntry) -> CanonicalApi:
    """Import ``entry`` without its raw document, as a stored revision is re-exported."""
    source = ArazzoImportSource()
    return source.normalize(source.parse(entry.read_text(), source_label=entry.path), include_raw=False)


def _rebuilt(api: CanonicalApi) -> Dict[str, Any]:
    return yaml.safe_load(ArazzoEmitter().emit(api).files[0].content)


# ---------------------------------------------------------------------------
# The set
# ---------------------------------------------------------------------------


def test_the_foreign_set_covers_both_versions_and_every_tool() -> None:
    versions = {str(_document(entry)["arazzo"]).rsplit(".", 1)[0] for entry in FOREIGN}
    assert versions == {"1.0", "1.1"}
    sources = {entry.source for entry in FOREIGN}
    assert {
        "OAI/Arazzo-Specification",
        "Redocly/museum-openapi-example",
        "Redocly/redocly-cli",
        "stoplightio/spectral",
        "specmatic/specmatic-arazzo-auth",
    } <= sources


@pytest.mark.parametrize(
    "feature", ["components-reference", "runtime-expression", "querystring", "channelPath", "self-uri"]
)
def test_the_foreign_set_covers_the_1_1_construct(feature: str) -> None:
    assert any(feature in entry.features for entry in FOREIGN), f"no foreign Arazzo entry exercises {feature!r}"


def test_every_foreign_entry_links_its_upstream_document() -> None:
    for entry in FOREIGN:
        assert entry.source_url and entry.source_url.startswith("https://github.com/"), entry.path
        assert entry.read_text().startswith("# Derived corpus fixture"), f"{entry.path} lost its attribution header"


# ---------------------------------------------------------------------------
# Per document
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", FOREIGN, ids=[entry.path for entry in FOREIGN])
def test_the_document_passes_the_official_schema(entry: CorpusEntry) -> None:
    assert arazzo_schema_violations(_document(entry)) == []


@pytest.mark.parametrize("entry", FOREIGN, ids=[entry.path for entry in FOREIGN])
def test_the_document_is_detected_and_imported(entry: CorpusEntry) -> None:
    detection = ArazzoImportSource().detect(DetectionInput(document=_document(entry)))
    assert detection.matched and detection.confidence >= entry.expected_detection.min_confidence
    assert _import(entry).operations(), f"{entry.path} imported no step"


@pytest.mark.parametrize("entry", FOREIGN, ids=[entry.path for entry in FOREIGN])
def test_the_rebuilt_document_equals_the_source(entry: CorpusEntry) -> None:
    """Rebuilt from the model alone, the document says exactly what the source said, in the same version."""
    assert _rebuilt(_import(entry)) == _document(entry)


@pytest.mark.parametrize("entry", FOREIGN, ids=[entry.path for entry in FOREIGN])
def test_the_document_round_trips_losslessly(entry: CorpusEntry) -> None:
    report = round_trip_arazzo(_import(entry))
    assert report.status is RoundTripStatus.LOSSLESS, (report.problems, report.import_error, report.unexplained)


# ---------------------------------------------------------------------------
# The 1.1 fields COA-1.4 keeps
# ---------------------------------------------------------------------------

_ASYNC_DOC = {
    "arazzo": "1.1.0",
    "$self": "https://example.com/workflows/signup.arazzo.yaml",
    "info": {"title": "Signup", "version": "1.0.0"},
    "sourceDescriptions": [{"name": "events", "url": "./events.asyncapi.yaml", "type": "asyncapi"}],
    "workflows": [{
        "workflowId": "await-signup",
        "summary": "Wait for a signup event.",
        "parameters": [{"in": "header", "name": "X-Tenant", "value": "$inputs.tenant"}],
        "steps": [{
            "stepId": "receive",
            "channelPath": "$sourceDescriptions.events#/channels/signedUp",
            "action": "receive",
            "correlationId": "$inputs.email",
            "timeout": 10000,
        }],
    }],
}


def _normalize(document: Dict[str, Any]) -> CanonicalApi:
    return ArazzoImportSource().normalize(document, include_raw=False)


@pytest.mark.parametrize(
    ("channel_path", "source"),
    [
        ("$sourceDescriptions.events#/channels/signedUp", "events"),
        ("{$sourceDescriptions.events.url}#/channels/signedUp", "events"),
        ("signedUp", None),  # the OAI schema accepts any string; it names no source
    ],
)
def test_a_channel_path_is_a_step_target(channel_path: str, source: Any) -> None:
    target = resolve_step_target({"channelPath": channel_path}, source_names=["events"])
    assert target is not None and target.kind == "channelPath" and target.source_name == source
    assert step_is_async({"channelPath": channel_path}, target=target)


def test_a_channel_path_step_is_not_rejected_as_naming_nothing() -> None:
    validate_arazzo_semantics(_ASYNC_DOC)  # raised ArazzoSemanticError before COA-1.4


def test_an_action_alone_does_not_make_a_step_async() -> None:
    """The OAI schema lets an OpenAPI step carry `action`, so it is not an async signal on its own."""
    step = {"operationId": "createUser", "action": "send"}
    assert not step_is_async(step, target=resolve_step_target(step))


def test_the_async_step_fields_workflow_parameters_and_self_are_kept() -> None:
    api = _normalize(_ASYNC_DOC)
    [step] = api.operations()
    assert {key: step.extras[key] for key in ("channelPath", "action", "correlationId", "timeout")} == {
        "channelPath": "$sourceDescriptions.events#/channels/signedUp",
        "action": "receive",
        "correlationId": "$inputs.email",
        "timeout": 10000,
    }
    assert step.extras["asyncStep"] is True and step.extras["sourceDescription"] == "events"
    assert api.services[0].extras["parameters"] == _ASYNC_DOC["workflows"][0]["parameters"]
    assert api.extras["self"] == _ASYNC_DOC["$self"]
    assert _rebuilt(api) == _ASYNC_DOC


def test_a_summary_only_workflow_is_not_given_a_copied_description() -> None:
    rebuilt = _rebuilt(_normalize(_ASYNC_DOC))
    assert "description" not in rebuilt["workflows"][0]


def test_self_is_not_written_to_a_1_0_document_and_the_loss_is_recorded() -> None:
    document = {**_ASYNC_DOC, "arazzo": "1.0.1", "sourceDescriptions": [
        {"name": "events", "url": "./events.openapi.yaml", "type": "openapi"}]}
    result = ArazzoEmitter().emit(_normalize(document))
    assert "$self" not in yaml.safe_load(result.files[0].content)
    assert any(loss.subject == "self-needs-1-1" for loss in result.losses)
