"""Collection targets across paradigms — MFX-31.5 (#4293).

What the API-client collection targets — Postman, and its Insomnia and Bruno flavors (the ``insomnia``
and ``bruno`` targets, MFX-31.3) — do with a source of each paradigm, pinned in
``fixtures/collection_targets/cross_paradigm.json`` (regenerate with
``APIOME_REGEN_COLLECTION_TARGETS=1``):

* a **REST** API exports to all three, ``lossy`` (schemas become examples), with one saved request per
  operation, and re-imports through the client's own importer;
* an **RPC** service, a **GraphQL** schema, an **event** API and a **types-only** schema have no HTTP
  operation, so every collection target refuses them — offered greyed out with the reason (the export
  dialog and ``GET …/export/targets``) and refused before a job runs;
* the Postman target's ``flavor`` writes exactly what the matching target writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
from corpus_adapter_support import valid_entries
from corpus_roundtrip import _import_entry

from app.emitter import EmitPreconditionError, coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries
from app.import_source import get_import_source, load_builtin_import_sources
from app.roundtrip_matrix import reimport_emitted

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "collection_targets" / "cross_paradigm.json"

#: One corpus source per paradigm.
SOURCES: Dict[str, str] = {
    "rest": "openapi/30-openapi-3.0-petstore.yaml",
    "rpc": "protobuf/02-grpc-service.proto",
    "graph": "graphql/06-union-types.graphql",
    "event": "asyncapi/01-user-events-2.6.yaml",
    "data_schema": "json-schema/02-product-types.json",
}

#: The collection targets, and the Postman flavor that writes each.
TARGETS: Dict[str, str] = {"postman": "postman", "insomnia": "insomnia", "bruno": "bruno"}


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_import_sources()
    load_builtin_emitters()


def _source(paradigm: str) -> Any:
    path = SOURCES[paradigm]
    entry = next((e for e in valid_entries() if e.path == path), None)
    if entry is None:
        pytest.skip(f"corpus file {path} is not checked out")
    return _import_entry(entry)


def _outcome(api: Any, target: str) -> Dict[str, Any]:
    """The pinned facts of exporting ``api`` to ``target``: its card, and the export or the refusal."""
    card = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == target)
    outcome: Dict[str, Any] = {"available": card.descriptor.available, "tier": card.fidelity.tier}
    try:
        result = get_emitter(target)().emit(api)
    except EmitPreconditionError as exc:
        outcome["refused"] = str(exc)
        return outcome
    back = reimport_emitted(get_import_source(target), result, multi_file=len(result.files) > 1)
    outcome.update(
        files=sorted(emitted.path for emitted in result.files),
        loss_subjects=sorted({loss.subject for loss in result.losses}),
        reimported_operations=sorted(op.key for service in back.services for op in service.operations),
    )
    return outcome


def _measure() -> Dict[str, Any]:
    return {paradigm: {target: _outcome(_source(paradigm), target) for target in TARGETS} for paradigm in SOURCES}


def test_the_cross_paradigm_outcomes_match_the_fixture() -> None:
    measured = _measure()
    if os.environ.get("APIOME_REGEN_COLLECTION_TARGETS"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("target", TARGETS)
def test_a_rest_api_exports_to_every_collection_target(target: str) -> None:
    api = _source("rest")
    outcome = _outcome(api, target)
    assert outcome["available"] and outcome["tier"] == "lossy" and "refused" not in outcome
    http = sorted(op.key for op in api.operations() if op.http_method and op.http_path)
    assert outcome["reimported_operations"] == http


@pytest.mark.parametrize("paradigm", ["rpc", "graph", "event", "data_schema"])
@pytest.mark.parametrize("target", TARGETS)
def test_a_source_with_no_http_operation_is_offered_greyed_out_and_refused(paradigm: str, target: str) -> None:
    api = _source(paradigm)
    card = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == target)
    assert card.descriptor.available is False
    assert "HTTP operation" in (card.descriptor.unavailable_reason or "")
    with pytest.raises(EmitPreconditionError):
        get_emitter(target)().emit(api)


@pytest.mark.parametrize("flavor", ["insomnia", "bruno"])
def test_the_postman_flavor_writes_what_the_target_writes(flavor: str) -> None:
    api = _source("rest")
    postman = get_emitter("postman")
    by_flavor = postman().emit(api, opts=coerce_emit_options(postman, {"flavor": flavor}))
    by_target = get_emitter(flavor)().emit(api)
    assert [(f.path, f.content) for f in by_flavor.files] == [(f.path, f.content) for f in by_target.files]
