"""Acceptance tests for REPO-3.3 / #2772 — AsyncAPI repository importer.

Covers YAML+JSON intake, action normalization, lossless bindings through the
canonical persistence codec, per-channel ``parse_error`` isolation, and logical
round-trips on Streetlights + Anyway Jobs (normalize → dump/load → emit →
normalize; fingerprints agree).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from app.asyncapi_emitter import AsyncApiEmitter
from app.asyncapi_normalizer import AsyncApiNormalizer
from app.canonical_persistence import dump_canonical_tree, load_canonical_tree
from app.fingerprint import fingerprint
from app.import_ingestion import parse_document

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi"


def _resolve_local_refs(node: Any, root: Dict[str, Any]) -> Any:
    """Inline ``#/…`` `$ref` pointers (sufficient for our committed fixtures)."""
    if isinstance(node, list):
        return [_resolve_local_refs(item, root) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        cur: Any = root
        for part in ref[2:].split("/"):
            cur = cur[part]
        return _resolve_local_refs(copy.deepcopy(cur), root)
    return {k: _resolve_local_refs(v, root) for k, v in node.items()}


def _load_fixture(name: str) -> Dict[str, Any]:
    raw = (_FIXTURES / name).read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    assert isinstance(doc, dict)
    return _resolve_local_refs(doc, doc)


def _logical_fp(model) -> str:
    """Fingerprint with ``raw`` stripped so emit→normalize noise does not matter."""
    cleaned = model.model_copy(update={"raw": None})
    return fingerprint(cleaned).fingerprint


def _logical_surface(model) -> Dict[str, Any]:
    """Compare event-surface identity independent of v2/v3 action spelling."""
    return {
        "channels": sorted(
            (c.address, json.dumps(c.bindings, sort_keys=True)) for c in model.channels
        ),
        "operations": sorted(
            (
                op.kind.value,
                op.channel_ref or "",
                tuple(
                    (
                        m.name or "",
                        json.dumps(m.payload_schema or {}, sort_keys=True),
                        tuple(m.content_types),
                    )
                    for m in op.messages
                ),
            )
            for op in model.operations()
        ),
    }


@pytest.mark.parametrize(
    "fixture",
    ["streetlights_2.6.yaml", "anyway_jobs_3.0.yaml"],
)
def test_yaml_and_json_intake_normalize(fixture: str) -> None:
    doc = _load_fixture(fixture)
    as_yaml = yaml.safe_dump(doc)
    as_json = json.dumps(doc)

    parsed_yaml = parse_document(as_yaml)
    parsed_json = parse_document(as_json)
    assert isinstance(parsed_yaml, dict) and isinstance(parsed_json, dict)

    n = AsyncApiNormalizer()
    from_yaml = n.normalize(_resolve_local_refs(parsed_yaml, parsed_yaml), include_raw=False)
    from_json = n.normalize(_resolve_local_refs(parsed_json, parsed_json), include_raw=False)
    assert _logical_fp(from_yaml) == _logical_fp(from_json)


@pytest.mark.parametrize(
    "fixture",
    ["streetlights_2.6.yaml", "anyway_jobs_3.0.yaml"],
)
def test_round_trip_through_persistence_codec(fixture: str) -> None:
    """normalize → persist-codec (dump/load) is fingerprint-lossless."""
    doc = _load_fixture(fixture)
    n = AsyncApiNormalizer()
    original = n.normalize(doc, include_raw=False)

    persisted = load_canonical_tree(dump_canonical_tree(original))
    assert _logical_fp(persisted) == _logical_fp(original)
    for before, after in zip(original.channels, persisted.channels, strict=True):
        assert after.bindings == before.bindings


def test_anyway_jobs_emit_round_trip_preserves_logical_surface() -> None:
    """Native AsyncAPI 3 → emit 3.1 → normalize keeps the event surface identical."""
    doc = _load_fixture("anyway_jobs_3.0.yaml")
    n = AsyncApiNormalizer()
    original = n.normalize(doc, include_raw=False)
    persisted = load_canonical_tree(dump_canonical_tree(original))
    emitted = AsyncApiEmitter().emit(persisted).document
    reimported = n.normalize(_resolve_local_refs(emitted, emitted), include_raw=False)
    assert _logical_surface(reimported) == _logical_surface(original)


def test_streetlights_emit_round_trip_preserves_logical_surface() -> None:
    """Streetlights v2 → emit 3.1 → normalize keeps addresses/payloads/kind."""
    doc = _load_fixture("streetlights_2.6.yaml")
    n = AsyncApiNormalizer()
    original = n.normalize(doc, include_raw=False)
    persisted = load_canonical_tree(dump_canonical_tree(original))
    emitted = AsyncApiEmitter().emit(persisted).document
    reimported = n.normalize(_resolve_local_refs(emitted, emitted), include_raw=False)
    assert _logical_surface(reimported) == _logical_surface(original)


def test_anyway_jobs_bindings_and_actions() -> None:
    api = AsyncApiNormalizer().normalize(_load_fixture("anyway_jobs_3.0.yaml"), include_raw=False)
    assert api.format == "asyncapi-3"
    posted = next(c for c in api.channels if c.address == "jobs/posted")
    assert posted.bindings["kafka"]["topic"] == "jobs.posted"
    assert posted.bindings["kafka"]["partitions"] == 6
    actions = {op.extras.get("action") for op in api.operations()}
    assert actions == {"send", "receive"}


def test_streetlights_v2_publish_action() -> None:
    api = AsyncApiNormalizer().normalize(_load_fixture("streetlights_2.6.yaml"), include_raw=False)
    assert api.format == "asyncapi-2"
    assert {op.extras.get("action") for op in api.operations()} == {"publish"}
    assert api.operations()[0].kind.value == "publish"


def test_single_channel_parse_error_does_not_abort(monkeypatch) -> None:
    n = AsyncApiNormalizer()
    original = n._channel_v3

    def flaky(name, spec, coercer):
        if name == "jobPosted":
            raise RuntimeError("broken channel")
        return original(name, spec, coercer)

    monkeypatch.setattr(n, "_channel_v3", flaky)
    api = n.normalize(_load_fixture("anyway_jobs_3.0.yaml"), include_raw=False)
    by_key = {c.key: c for c in api.channels}
    assert by_key["jobPosted"].extras["status"] == "parse_error"
    apps = next(c for c in api.channels if c.address == "jobs/{jobId}/applications")
    assert apps.bindings["kafka"]["topic"] == "jobs.applications"
    assert any(op.extras.get("action") == "receive" for op in api.operations())
