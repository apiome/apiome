"""Candidate write planning + fidelity loop — DCW-2.3 (private-suite#2360).

The invariant under test: for any candidate, plan writes, predict the
regenerated canonical, re-extract the preservation envelope against it, merge
— and the merged result must equal the candidate up to reported deterministic
generator enrichments. Losses and value changes must always be caught.
"""

from pathlib import Path

import yaml

from app.preservation_envelope import (
    apply_envelope,
    extract_envelope,
    semantic_fingerprint,
    validate_envelope,
)
from app.source_change_apply import (
    build_canonical_writes,
    compare_candidate_to_merged,
    parameter_key,
    path_shared_parameters,
    regenerate_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "preservation"


def _round_trip(candidate, dialect="3.1.0"):
    """Plan -> predict -> re-extract -> merge; returns (merged, report, env)."""
    writes = build_canonical_writes(candidate)
    regenerated = regenerate_document(
        writes,
        tenant_slug="t",
        project_slug="p",
        version_string="1.0.0",
        project_description="No description provided",
    )
    envelope = extract_envelope(candidate, regenerated, dialect)
    report = validate_envelope(envelope, regenerated)
    assert report.ok, [e.model_dump() for e in report.errors]
    merged, errors = apply_envelope(regenerated, envelope)
    assert errors == []
    return merged, compare_candidate_to_merged(candidate, merged), envelope


def _doc(**overrides):
    base = {
        "openapi": "3.1.0",
        "info": {
            "title": "p API",
            "version": "1.0.0",
            "description": "No description provided",
        },
        "paths": {},
        "components": {"schemas": {}},
    }
    base.update(overrides)
    return base


class TestLosslessRoundTrip:
    def test_schemas_with_properties_required_and_refs(self):
        candidate = _doc(
            components={
                "schemas": {
                    "Toy": {"type": "object", "title": "Toy"},
                    "Pet": {
                        "type": "object",
                        "title": "Pet",
                        "description": "A pet",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string", "maxLength": 50},
                            "toy": {"$ref": "#/components/schemas/Toy"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                }
            }
        )
        merged, report, _env = _round_trip(candidate)
        assert report.ok, report.model_dump(by_alias=True)
        assert report.losses == [] and report.value_changes == []
        assert (
            semantic_fingerprint(merged).fingerprint
            != semantic_fingerprint(_doc()).fingerprint
        )

    def test_operations_parameters_bodies_responses(self):
        candidate = _doc(
            paths={
                "/pets": {
                    "get": {
                        "summary": "List pets",
                        "tags": ["pets"],
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "description": "Page size",
                                "schema": {"type": "integer"},
                            },
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            },
                        ],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Pet"}
                                    }
                                },
                            }
                        },
                    },
                    "post": {
                        "summary": "Create",
                        "requestBody": {
                            "description": "New pet",
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        },
                        "responses": {
                            "201": {
                                "description": "created",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object"}
                                    }
                                },
                            }
                        },
                    },
                }
            },
            components={"schemas": {"Pet": {"type": "object", "title": "Pet"}}},
        )
        merged, report, _env = _round_trip(candidate)
        assert report.ok, report.model_dump(by_alias=True)

    def test_unsupported_constructs_round_trip_via_envelope(self):
        candidate = _doc(
            webhooks={"newPet": {"post": {"responses": {"200": {"description": "ok"}}}}},
            servers=[{"url": "https://api.example.com", "x-region": "eu"}],
            paths={
                "/pets": {
                    "parameters": [
                        {"name": "tenant", "in": "header", "schema": {"type": "string"}}
                    ],
                    "get": {
                        "operationId": "listPets",
                        "deprecated": True,
                        "security": [],
                        "x-rate-limit": 10,
                        "callbacks": {"onEvent": {}},
                        "responses": {"200": {"description": "ok"}},
                    },
                }
            },
            components={
                "schemas": {},
                "securitySchemes": {
                    "key": {"type": "apiKey", "name": "X-Key", "in": "header"},
                    "oauth": {"type": "oauth2", "flows": {}},
                },
            },
        )
        merged, report, envelope = _round_trip(candidate)
        assert report.ok, report.model_dump(by_alias=True)
        pointers = {c.pointer for c in envelope.claims}
        # Constructs the relational model cannot hold are preserved, not lost.
        assert "/webhooks" in pointers
        assert "/paths/~1pets/parameters" in pointers
        assert "/components/securitySchemes/oauth" in pointers
        assert "/paths/~1pets/get/callbacks" in pointers
        assert merged["webhooks"] == candidate["webhooks"]

    def test_golden_fixture_round_trips(self):
        source = yaml.safe_load((FIXTURES / "golden-3.1-source.yaml").read_text())
        merged, report, _env = _round_trip(source)
        assert report.losses == [], report.losses
        # /info is model-owned (generated from project/version records); the
        # review endpoint blocks /info edits before an apply ever runs, so
        # only non-info drift would be a real fidelity failure here.
        non_info = [p for p in report.value_changes if not p.startswith("/info")]
        assert non_info == [], non_info
        assert semantic_fingerprint(merged).fingerprint

    def test_required_order_is_not_semantic(self):
        candidate = _doc(
            components={
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "title": "Pet",
                        "required": ["b", "a"],
                        "properties": {
                            "a": {"type": "string"},
                            "b": {"type": "string"},
                        },
                    }
                }
            }
        )
        _merged, report, _env = _round_trip(candidate)
        assert report.ok, report.model_dump(by_alias=True)


class TestEnrichmentsAreReportedNotSilent:
    def test_generator_injected_title_is_an_enrichment(self):
        candidate = _doc(components={"schemas": {"Pet": {"type": "object"}}})
        _merged, report, _env = _round_trip(candidate)
        assert report.ok
        assert "/components/schemas/Pet/title" in report.enrichments

    def test_default_response_is_an_enrichment(self):
        candidate = _doc(
            paths={"/pets": {"get": {"summary": "List"}}},
        )
        _merged, report, _env = _round_trip(candidate)
        assert report.ok
        assert any(p.startswith("/paths/~1pets/get/responses") for p in report.enrichments)


class TestLossDetection:
    def test_value_drift_is_rejected(self):
        candidate = _doc(components={"schemas": {"Pet": {"type": "object", "title": "Pet"}}})
        merged = {**candidate, "components": {"schemas": {"Pet": {"type": "object", "title": "Renamed"}}}}
        report = compare_candidate_to_merged(candidate, merged)
        assert not report.ok
        assert "/components/schemas/Pet/title" in report.value_changes

    def test_lost_subtree_is_rejected(self):
        candidate = _doc(webhooks={"a": {}})
        merged = _doc()
        report = compare_candidate_to_merged(candidate, merged)
        assert not report.ok
        assert "/webhooks" in report.losses


class TestSharedParameterPlan:
    def test_dedupe_is_first_wins_and_stable(self):
        candidate = _doc(
            paths={
                "/pets": {
                    "get": {
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                        ],
                        "responses": {"200": {"description": "ok"}},
                    },
                    "delete": {
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                        ],
                        "responses": {"204": {"description": "gone"}},
                    },
                }
            }
        )
        writes = build_canonical_writes(candidate)
        path = writes.paths[0]
        shared = path_shared_parameters(path)
        assert list(shared.keys()) == [("limit", "query")]
        for op in path.operations:
            for parameter in op.parameters:
                assert parameter_key(parameter) in shared

    def test_identical_duplicate_parameters_round_trip(self):
        candidate = _doc(
            paths={
                "/pets": {
                    "get": {
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                        ],
                        "responses": {"200": {"description": "ok"}},
                    },
                    "delete": {
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                        ],
                        "responses": {"204": {"description": "gone"}},
                    },
                }
            }
        )
        _merged, report, _env = _round_trip(candidate)
        assert report.ok, report.model_dump(by_alias=True)
