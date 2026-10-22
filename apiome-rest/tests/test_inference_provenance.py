"""Inference provenance vocabulary, adapter retrofit, lint rule and publish gate — FMT-8.6 (#5467).

The acceptance criteria, in the order the issue lists them:

* the three-way vocabulary is defined once (:mod:`app.inference_provenance`) and every
  inference-based adapter stamps through it — checked against each adapter's corpus examples;
* the catalog detail read badges and filters by class — each parsed entity carries its class
  and evidence, and the read carries per-class counts;
* a lint rule reports the inferred-construct ratio and can gate publication via a style guide;
* the retrofit covers ``http-file``, ``postman``, the gateway family and EPIC-8.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pytest
from corpus_adapter_support import adapter_for, missing_tools, valid_entries
from corpus_snapshot import run_pipeline

from app.asyncapi_emitter import AsyncApiEmitter
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_parsed_model import derive_catalog_parsed_view, derive_parsed_model
from app.gateway_family import GATEWAY_FAMILY
from app.gateway_family import INFERRED as GATEWAY_INFERRED
from app.import_source import load_builtin_import_sources
from app.inference_provenance import (
    DECLARED,
    INFERENCE_BASED_ADAPTERS,
    INFERRED,
    PROVENANCE_CLASSES,
    PROVENANCE_EVIDENCE_KEY,
    PROVENANCE_KEY,
    SYNTHESIZED,
    iter_construct_provenance,
    non_declared_constructs,
    provenance_evidence,
    provenance_extras,
    provenance_of,
    summarize_provenance,
    without_provenance_stamp,
)
from app.lint_engine import lint_canonical_model, unconditional_rule_packs
from app.lint_rule_registry import builtin_rule_ids
from app.normalizer import get_normalizer
from app.provenance_lint import INFERRED_RATIO_RULE_ID, ProvenanceRulePack, inferred_ratio_message
from app.provenance_publish_gate import converted_source_provenance_violation

load_builtin_import_sources()

RESEED_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V311__style_guide_builtin_reseed_provenance_pack_5467.sql"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(
    *,
    operation_extras: Dict[str, object] | None = None,
    parameter_extras: Dict[str, object] | None = None,
    type_extras: Dict[str, object] | None = None,
    format_key: str = "openapi",
) -> CanonicalApi:
    """A one-service, one-operation, one-parameter, one-message, one-type REST model."""
    operation = Operation(
        key="GET /users/{id}",
        name="getUser",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/users/{id}",
        parameters=[
            Parameter(
                key="GET /users/{id}#path.id",
                name="id",
                location=ParameterLocation.PATH,
                required=True,
                type=TypeRef(name="string", nullable=False),
                extras=dict(parameter_extras or {}),
            )
        ],
        messages=[
            Message(
                key="GET /users/{id}#response.200",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="User", nullable=False),
            )
        ],
        extras=dict(operation_extras or {}),
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format=format_key,
        identity=ApiIdentity(name="users"),
        services=[Service(key="users", name="users", operations=[operation])],
        types=[Type(key="User", name="User", kind=TypeKind.RECORD, extras=dict(type_extras or {}))],
    )


def _corpus_models(format_key: str) -> List[CanonicalApi]:
    """Every runnable valid corpus example of one format, normalized through its adapter."""
    models: List[CanonicalApi] = []
    for entry in valid_entries():
        adapter = adapter_for(entry)
        if getattr(adapter, "format", None) != format_key and adapter.key != format_key:
            continue
        if missing_tools(adapter.key):
            continue
        models.append(run_pipeline(entry, adapter).model)
    return models


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_vocabulary_has_exactly_three_classes() -> None:
    assert PROVENANCE_CLASSES == ("declared", "inferred", "synthesized")
    assert (DECLARED, INFERRED, SYNTHESIZED) == PROVENANCE_CLASSES


def test_provenance_extras_stamps_class_and_trimmed_evidence() -> None:
    assert provenance_extras(INFERRED) == {PROVENANCE_KEY: "inferred"}
    assert provenance_extras(SYNTHESIZED, "  Named by Apiome.  ") == {
        PROVENANCE_KEY: "synthesized",
        PROVENANCE_EVIDENCE_KEY: "Named by Apiome.",
    }
    assert provenance_extras(INFERRED, "   ") == {PROVENANCE_KEY: "inferred"}


def test_provenance_extras_rejects_a_class_outside_the_vocabulary() -> None:
    with pytest.raises(ValueError):
        provenance_extras("observed")


@pytest.mark.parametrize(
    "extras, expected",
    [
        (None, DECLARED),
        ({}, DECLARED),
        ({"provenance": "inferred"}, INFERRED),
        ({"provenance": "synthesized"}, SYNTHESIZED),
        ({"provenance": "declared"}, DECLARED),
        # Other subsystems' own words never claim inference.
        ({"provenance": "operator_declared"}, DECLARED),
        ({"provenance": {"nested": True}}, DECLARED),
    ],
)
def test_provenance_of_defaults_to_declared(extras, expected) -> None:
    assert provenance_of(extras) == expected


def test_evidence_prefers_the_explicit_sentence() -> None:
    extras = {"provenance": "inferred", "provenance_evidence": "From the 200 example.", "sample_count": 3}
    assert provenance_evidence(extras) == "From the 200 example."


def test_evidence_reads_the_inferred_spec_engines_path_template() -> None:
    extras = {
        "provenance": "inferred",
        "inference_evidence": {"template": "/users/{id}", "sample_urls": ["/users/1", "/users/2"]},
    }
    assert provenance_evidence(extras) == "Path template /users/{id} generalized from 2 sample URL(s)."


def test_evidence_reads_a_gateway_regex_pattern_and_a_sample_count() -> None:
    assert provenance_evidence({"provenance": "inferred", "pattern": "~/users/\\d+"}) == (
        "Path recovered from the regex pattern ~/users/\\d+."
    )
    assert provenance_evidence({"provenance": "inferred", "sample_count": 4}) == "Observed in 4 sample(s)."
    assert provenance_evidence({"provenance": "inferred", "sample_count": True}) is None


def test_a_declared_construct_has_no_evidence() -> None:
    assert provenance_evidence({"provenance_evidence": "ignored"}) is None


def test_without_provenance_stamp_keeps_every_other_key() -> None:
    extras = {"provenance": "inferred", "provenance_evidence": "x", "bindings": {"kafka": {}}}
    assert without_provenance_stamp(extras) == {"bindings": {"kafka": {}}}
    assert "provenance" in extras  # the input is not mutated


# ---------------------------------------------------------------------------
# Construct walk and summary
# ---------------------------------------------------------------------------


def test_an_unstamped_model_is_entirely_declared() -> None:
    summary = summarize_provenance(_model())
    assert (summary.declared, summary.inferred, summary.synthesized, summary.total) == (5, 0, 0, 5)
    assert summary.inferred_ratio == 0.0
    assert summarize_provenance(None).total == 0


def test_parts_of_an_inferred_operation_inherit_its_class_and_evidence() -> None:
    api = _model(operation_extras=provenance_extras(INFERRED, "Read from a route table."))
    constructs = {c.kind: c for c in iter_construct_provenance(api)}
    assert constructs["operation"].provenance == INFERRED
    assert constructs["parameter"].provenance == INFERRED
    assert constructs["message"].provenance == INFERRED
    assert constructs["parameter"].evidence == "Read from a route table."
    assert constructs["service"].provenance == DECLARED
    assert constructs["type"].provenance == DECLARED


def test_a_part_stamped_on_its_own_keeps_its_own_class() -> None:
    api = _model(
        operation_extras=provenance_extras(INFERRED),
        parameter_extras=provenance_extras(SYNTHESIZED, "Default supplied."),
    )
    parameter = next(c for c in iter_construct_provenance(api) if c.kind == "parameter")
    assert (parameter.provenance, parameter.evidence) == (SYNTHESIZED, "Default supplied.")


def test_summary_counts_and_ratio() -> None:
    api = _model(
        operation_extras=provenance_extras(INFERRED),
        type_extras=provenance_extras(SYNTHESIZED),
    )
    summary = summarize_provenance(api)
    assert (summary.declared, summary.inferred, summary.synthesized) == (1, 3, 1)
    assert summary.inferred_percent == 60
    assert summary.as_dict() == {
        "declared": 1,
        "inferred": 3,
        "synthesized": 1,
        "total": 5,
        "inferred_ratio": 0.6,
    }
    assert [c.kind for c in non_declared_constructs(api)] == ["operation", "parameter", "message", "type"]


def test_a_non_declared_construct_without_evidence_falls_back_to_the_adapter_description() -> None:
    api = _model(operation_extras=provenance_extras(INFERRED), format_key="nginx")
    operation = next(c for c in iter_construct_provenance(api) if c.kind == "operation")
    assert operation.evidence == INFERENCE_BASED_ADAPTERS["nginx"]


# ---------------------------------------------------------------------------
# Adapter retrofit — http-file, postman, the gateway family, EPIC-8
# ---------------------------------------------------------------------------


def test_every_inference_based_adapter_is_a_registered_normalizer() -> None:
    for format_key in INFERENCE_BASED_ADAPTERS:
        assert get_normalizer(format_key) is not None, format_key


def test_the_retrofit_covers_the_whole_gateway_family() -> None:
    assert set(GATEWAY_FAMILY) <= set(INFERENCE_BASED_ADAPTERS)


@pytest.mark.parametrize("format_key", sorted(INFERENCE_BASED_ADAPTERS))
def test_every_non_declared_construct_carries_evidence(format_key: str) -> None:
    models = _corpus_models(format_key)
    if not models:
        pytest.skip(f"no runnable {format_key} corpus example in this environment")
    for api in models:
        for construct in non_declared_constructs(api):
            assert construct.evidence, f"{format_key}: {construct.kind} {construct.key} has no evidence"


def test_http_file_is_entirely_inferred() -> None:
    models = _corpus_models("http-file")
    assert models
    for api in models:
        summary = summarize_provenance(api)
        assert summary.total and summary.inferred == summary.total


@pytest.mark.parametrize(
    "format_key", sorted(k for k, f in GATEWAY_FAMILY.items() if f.route_provenance == GATEWAY_INFERRED)
)
def test_an_inferred_gateway_flavor_is_entirely_inferred(format_key: str) -> None:
    models = _corpus_models(format_key)
    if not models:
        pytest.skip(f"no runnable {format_key} corpus example in this environment")
    for api in models:
        if "tyk" in api.extras:
            # A Tyk OAS definition is an OpenAPI document — a declaration, not route plumbing.
            assert summarize_provenance(api).inferred == 0
            continue
        summary = summarize_provenance(api)
        assert summary.inferred == summary.total, format_key


def test_a_declared_gateway_flavor_infers_only_regex_recovered_paths() -> None:
    inferred = [c for api in _corpus_models("kong") for c in non_declared_constructs(api)]
    assert inferred, "the Kong corpus carries regex routes"
    assert all(c.provenance == INFERRED for c in inferred)
    assert all(c.evidence and "regex" in c.evidence for c in inferred)


def test_postman_infers_schemas_from_example_bodies_and_declares_requests() -> None:
    models = _corpus_models("postman")
    assert models
    kinds = set()
    for api in models:
        for construct in iter_construct_provenance(api):
            if construct.kind in ("service", "operation", "parameter"):
                assert construct.provenance == DECLARED, construct
            if construct.kind == "type":
                assert construct.provenance == INFERRED, construct
                assert construct.evidence and "example" in construct.evidence
            if construct.provenance == INFERRED:
                kinds.add(construct.kind)
    assert {"type", "message"} <= kinds


@pytest.mark.parametrize("format_key", ["typescript-types", "zod", "trpc", "pydantic", "cue", "pkl", "dhall"])
def test_code_first_sources_declare_or_synthesize_and_never_infer(format_key: str) -> None:
    models = _corpus_models(format_key)
    if not models:
        pytest.skip(f"no runnable {format_key} corpus example in this environment")
    for api in models:
        assert summarize_provenance(api).inferred == 0


@pytest.mark.parametrize("format_key", ["typescript-types", "trpc", "pydantic", "cue", "pkl", "dhall"])
def test_code_first_sources_stamp_the_types_apiome_named(format_key: str) -> None:
    models = _corpus_models(format_key)
    if not models:
        pytest.skip(f"no runnable {format_key} corpus example in this environment")
    synthesized = [c for api in models for c in non_declared_constructs(api)]
    assert synthesized, f"{format_key}: no synthesized type across the corpus"
    assert all(c.kind == "type" and c.provenance == SYNTHESIZED for c in synthesized)


def test_trpc_inline_payload_types_name_their_procedure() -> None:
    models = _corpus_models("trpc")
    if not models:
        pytest.skip("no runnable trpc corpus example in this environment")
    evidence = [c.evidence for api in models for c in non_declared_constructs(api)]
    assert any(e and "of procedure" in e for e in evidence)


def test_typescript_generic_instantiations_are_synthesized() -> None:
    models = _corpus_models("typescript-types")
    if not models:
        pytest.skip("no runnable typescript-types corpus example in this environment")
    evidence = [c.evidence or "" for api in models for c in non_declared_constructs(api)]
    assert any("generic" in e for e in evidence) or any("Named by Apiome" in e for e in evidence)


# ---------------------------------------------------------------------------
# Catalog detail — entity badges and the filter counts
# ---------------------------------------------------------------------------


_POSTMAN_COLLECTION = {
    "info": {
        "name": "Orders",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "Create order",
            "request": {
                "method": "POST",
                "url": {"raw": "https://api.example.com/orders", "host": ["api", "example", "com"], "path": ["orders"]},
                "body": {"mode": "raw", "raw": "{\"sku\": \"A-1\", \"quantity\": 2}"},
            },
        },
        {
            "name": "List orders",
            "request": {
                "method": "GET",
                "url": {"raw": "https://api.example.com/orders", "host": ["api", "example", "com"], "path": ["orders"]},
            },
        },
    ],
}


def _postman_item() -> Dict[str, object]:
    return {
        "id": "cat-postman",
        "source_format": "postman",
        "protocol": None,
        "tool_versions": {},
        "format_metadata": {
            "sourceContent": json.dumps(_POSTMAN_COLLECTION),
            "sourceLabel": "orders.postman_collection.json",
        },
    }


def test_catalog_entities_carry_their_construct_class_and_evidence() -> None:
    parsed, summary = derive_catalog_parsed_view(_postman_item())
    entities = {e["name"]: e for group in parsed for e in group["entities"]}
    assert entities["Create order"]["provenance"] == DECLARED
    assert entities["Create order"]["provenance_evidence"] is None
    assert entities["Order"]["provenance"] == INFERRED
    assert "POST /orders" in entities["Order"]["provenance_evidence"]
    assert summary["inferred"] >= 2  # the Order type and the request message
    assert summary["total"] == summary["declared"] + summary["inferred"] + summary["synthesized"]


def test_the_catalog_view_degrades_to_an_empty_summary_without_a_model() -> None:
    parsed, summary = derive_catalog_parsed_view({"id": "x", "format_metadata": {}})
    assert parsed == []
    assert summary == {"declared": 0, "inferred": 0, "synthesized": 0, "total": 0, "inferred_ratio": 0.0}


def test_entities_of_an_inferred_adapter_fall_back_to_its_description() -> None:
    api = _model(operation_extras=provenance_extras(INFERRED), format_key="nginx")
    operation = next(e for group in derive_parsed_model(api) for e in group["entities"] if e["name"] == "getUser")
    assert operation["provenance_evidence"] == INFERENCE_BASED_ADAPTERS["nginx"]


# ---------------------------------------------------------------------------
# Lint — the inferred-construct ratio
# ---------------------------------------------------------------------------


def test_the_pack_runs_for_every_format_and_is_catalogued_and_seeded() -> None:
    assert any(isinstance(pack, ProvenanceRulePack) for pack in unconditional_rule_packs())
    assert INFERRED_RATIO_RULE_ID in builtin_rule_ids()
    assert f"('{INFERRED_RATIO_RULE_ID}'," in RESEED_MIGRATION.read_text(encoding="utf-8")


def test_the_rule_reports_the_inferred_ratio() -> None:
    api = _model(operation_extras=provenance_extras(INFERRED), type_extras=provenance_extras(SYNTHESIZED))
    findings = [f for f in lint_canonical_model(api).findings if f.rule == INFERRED_RATIO_RULE_ID]
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.severity, finding.category, finding.path) == ("info", "provenance", "api")
    assert finding.message == (
        "60% of this item's constructs are inferred (3 of 5). 1 more are synthesized by Apiome."
    )


@pytest.mark.parametrize(
    "api",
    [_model(), _model(type_extras=provenance_extras(SYNTHESIZED))],
    ids=["declared", "synthesized-only"],
)
def test_the_rule_is_silent_without_an_inferred_construct(api: CanonicalApi) -> None:
    assert not [f for f in lint_canonical_model(api).findings if f.rule == INFERRED_RATIO_RULE_ID]


def test_the_message_omits_the_synthesized_clause_when_there_are_none() -> None:
    assert inferred_ratio_message(13, 0, 21, 62) == "62% of this item's constructs are inferred (13 of 21)."


# ---------------------------------------------------------------------------
# Publish gate
# ---------------------------------------------------------------------------


class _Guide:
    """A compiled guide stand-in that assigns the provenance rule one severity."""

    def __init__(self, severity: str | None) -> None:
        self._severity = severity

    def severity_for(self, rule_id: str):
        return self._severity if rule_id == INFERRED_RATIO_RULE_ID else None


def _db(item: Dict[str, object] | None, conversions: List[Dict[str, object]] | None = None):
    """A database facade holding one conversion of ``item`` into the Project."""
    rows = conversions if conversions is not None else [{"source_project_id": "cat-postman"}]
    return SimpleNamespace(
        get_conversions_for_project=lambda tenant_id, project_id: rows,
        get_catalog_item_by_id=lambda item_id, tenant_id: item if item and item_id == item["id"] else None,
    )


def test_an_error_severity_guide_blocks_a_project_converted_from_an_inferred_source() -> None:
    item = {**_postman_item(), "name": "Orders collection"}
    violation = converted_source_provenance_violation(
        db=_db(item), tenant_id="t", project_id="p", guide=_Guide("error")
    )
    assert violation is not None
    assert violation.rule == INFERRED_RATIO_RULE_ID
    assert violation.source_item_name == "Orders collection"
    assert "of this item's constructs are inferred" in violation.message


@pytest.mark.parametrize("severity", ["info", "warning", None])
def test_the_default_or_a_softer_guide_never_blocks(severity) -> None:
    assert (
        converted_source_provenance_violation(
            db=_db(_postman_item()), tenant_id="t", project_id="p", guide=_Guide(severity)
        )
        is None
    )


def test_a_project_not_converted_from_the_catalog_is_never_blocked() -> None:
    assert (
        converted_source_provenance_violation(
            db=_db(_postman_item(), conversions=[]), tenant_id="t", project_id="p", guide=_Guide("error")
        )
        is None
    )


def test_a_declared_source_is_never_blocked() -> None:
    declared = {
        "id": "cat-postman",
        "source_format": "graphql",
        "format_metadata": {"sourceContent": "type Query { ping: String }", "sourceLabel": "s.graphql"},
    }
    assert (
        converted_source_provenance_violation(db=_db(declared), tenant_id="t", project_id="p", guide=_Guide("error"))
        is None
    )


def test_a_gate_fault_never_blocks_publishing() -> None:
    def boom(*_args):
        raise RuntimeError("database down")

    db = SimpleNamespace(get_conversions_for_project=boom, get_catalog_item_by_id=boom)
    assert converted_source_provenance_violation(db=db, tenant_id="t", project_id="p", guide=_Guide("error")) is None
    assert (
        converted_source_provenance_violation(
            db=_db(_postman_item()), tenant_id="t", project_id="p", guide=SimpleNamespace()
        )
        is None
    )


# ---------------------------------------------------------------------------
# Emitters never leak the stamp
# ---------------------------------------------------------------------------


def test_the_asyncapi_emitter_drops_the_stamp_from_every_object() -> None:
    entry = next(e for e in valid_entries() if e.path.startswith("asyncapi/"))
    api = run_pipeline(entry).model
    stamp = provenance_extras(INFERRED, "Observed on the wire.")
    services = [
        service.model_copy(
            update={
                "operations": [
                    op.model_copy(
                        update={
                            "extras": {**op.extras, **stamp},
                            "messages": [m.model_copy(update={"extras": {**m.extras, **stamp}}) for m in op.messages],
                        }
                    )
                    for op in service.operations
                ]
            }
        )
        for service in api.services
    ]
    channels = [c.model_copy(update={"extras": {**c.extras, **stamp}}) for c in api.channels]
    servers = [s.model_copy(update={"extras": {**s.extras, **stamp}}) for s in api.servers]
    stamped = api.model_copy(update={"services": services, "channels": channels, "servers": servers})
    document = json.dumps(AsyncApiEmitter().emit(stamped).document)
    assert "provenance" not in document
    assert "Observed on the wire." not in document
