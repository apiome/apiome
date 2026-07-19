"""Source-to-model change classification engine — DCW-2.3 (private-suite#2360).

Deterministic diff kinds and grouping, capability-driven unsupported-preserved
classification, structural blockers with explanations, local $ref integrity,
and the change-set digest contract.
"""

import pytest

from app.source_change_review import (
    build_source_change_set,
    change_set_digest,
    diff_documents,
    ref_integrity_errors,
    scope_for_pointer,
)


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


class TestScopeForPointer:
    @pytest.mark.parametrize(
        "pointer,scope,group",
        [
            ("/info/title", "document", "info"),
            ("/servers/0/url", "document", "servers"),
            ("/paths/~1pets", "path", "/pets"),
            ("/paths/~1pets/summary", "path", "/pets"),
            ("/paths/~1pets/get", "operation", "GET /pets"),
            ("/paths/~1pets/get/responses/200", "operation", "GET /pets"),
            ("/paths/~1pets/query", "operation", "QUERY /pets"),
            ("/components/schemas/Pet", "schema", "Pet"),
            ("/components/schemas/Pet/properties/id", "schema", "Pet"),
            ("/components/parameters/Limit", "component", "parameters/Limit"),
            ("/components/responses/NotFound/description", "component", "responses/NotFound"),
            ("/webhooks/newPet", "path", "webhooks newPet"),
            ("/x-vendor", "document", "x-vendor"),
        ],
    )
    def test_mapping(self, pointer, scope, group):
        assert scope_for_pointer(pointer) == (scope, group)


class TestDiffDocuments:
    def test_addition_deletion_update_at_deepest_stable_pointer(self):
        base = {"a": {"b": 1, "c": [1, 2]}, "gone": True}
        cand = {"a": {"b": 2, "c": [1, 2, 3]}, "new": {"x": 1}}
        deltas = {(d["pointer"], d["kind"]) for d in diff_documents(base, cand)}
        assert deltas == {
            ("/a/b", "update"),
            ("/a/c/2", "addition"),
            ("/gone", "deletion"),
            ("/new", "addition"),
        }

    def test_type_change_is_update(self):
        deltas = diff_documents({"a": 1}, {"a": "1"})
        assert [(d["pointer"], d["kind"]) for d in deltas] == [("/a", "update")]

    def test_identical_documents_produce_no_deltas(self):
        doc = _doc()
        assert diff_documents(doc, doc) == []


class TestBuildSourceChangeSet:
    def test_kinds_counts_and_grouping(self):
        base = _doc(components={"schemas": {"Pet": {"type": "object", "title": "Pet"}}})
        cand = _doc(
            paths={
                "/pets": {
                    "get": {"responses": {"200": {"description": "ok"}}},
                }
            },
            components={
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "title": "Pet",
                        "properties": {"id": {"type": "string"}},
                    }
                }
            },
        )
        cs = build_source_change_set(base, cand, "3.1.0")
        by_pointer = {c.pointer: c for c in cs.changes}
        assert by_pointer["/paths/~1pets"].scope == "path"
        assert by_pointer["/paths/~1pets"].kind == "addition"
        assert by_pointer["/components/schemas/Pet/properties"].scope == "schema"
        assert by_pointer["/components/schemas/Pet/properties"].group == "Pet"
        assert cs.counts.total == len(cs.changes)
        assert cs.counts.additions == cs.counts.total
        assert cs.blockers == []

    def test_changes_sorted_deterministically(self):
        base = _doc()
        cand = _doc(
            paths={"/b": {"get": {"responses": {"200": {"description": "ok"}}}}},
            components={"schemas": {"A": {"type": "object"}}},
        )
        cs = build_source_change_set(base, cand, "3.1.0")
        keys = [(c.scope, c.group, c.pointer) for c in cs.changes]
        assert keys == sorted(keys)

    def test_digest_binds_base_and_candidate(self):
        base = _doc()
        cand = _doc(components={"schemas": {"A": {"type": "object"}}})
        cs = build_source_change_set(base, cand, "3.1.0")
        assert cs.change_set_digest == change_set_digest(
            cs.base_digest, cs.candidate_digest
        )
        assert cs.change_set_digest.startswith("sha256:")
        # Any different base yields a different digest.
        other = build_source_change_set(cand, cand, "3.1.0")
        assert other.change_set_digest != cs.change_set_digest


class TestBlockers:
    def test_referenced_component_deletion_lists_every_referencing_pointer(self):
        base = _doc(
            components={
                "schemas": {
                    "Pet": {"type": "object"},
                    "Toy": {"type": "object"},
                }
            }
        )
        cand = _doc(
            paths={
                "/pets": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Toy"}
                                    }
                                },
                            }
                        }
                    }
                }
            },
            components={"schemas": {"Pet": {"type": "object"}}},
        )
        cs = build_source_change_set(base, cand, "3.1.0")
        blocker = next(
            b for b in cs.blockers if b.code == "REFERENCED_COMPONENT_DELETION"
        )
        assert blocker.pointer == "/components/schemas/Toy"
        assert blocker.referenced_by == [
            "/paths/~1pets/get/responses/200/content/application~1json/schema/$ref"
        ]
        assert "Toy" in blocker.message

    def test_unreferenced_deletion_is_not_blocked(self):
        base = _doc(components={"schemas": {"Toy": {"type": "object"}}})
        cand = _doc(components={"schemas": {}})
        cs = build_source_change_set(base, cand, "3.1.0")
        assert cs.blockers == []
        assert cs.counts.deletions == 1

    def test_model_owned_info_edit_is_blocked_with_guidance(self):
        base = _doc()
        cand = _doc(
            info={
                "title": "p API",
                "version": "1.0.0",
                "description": "EDITED",
            }
        )
        cs = build_source_change_set(base, cand, "3.1.0")
        blocker = next(b for b in cs.blockers if b.code == "MODEL_OWNED_VALUE")
        assert blocker.pointer == "/info/description"
        assert "metadata inspector" in blocker.message

    def test_model_owned_addition_is_not_blocked(self):
        base = _doc()
        cand = _doc(
            info={
                "title": "p API",
                "version": "1.0.0",
                "description": "No description provided",
                "contact": {"name": "Team"},
            }
        )
        cs = build_source_change_set(base, cand, "3.1.0")
        assert all(b.code != "MODEL_OWNED_VALUE" for b in cs.blockers)

    def test_openapi_dialect_edit_is_blocked(self):
        base = _doc()
        cand = _doc(openapi="3.2.0")
        cs = build_source_change_set(base, cand, "3.1.0")
        assert any(
            b.code == "MODEL_OWNED_VALUE" and b.pointer == "/openapi"
            for b in cs.blockers
        )

    def test_shared_response_collision_blocked_with_explanation(self):
        cand = _doc(
            paths={
                "/pets": {
                    "get": {"responses": {"200": {"description": "list"}}},
                    "post": {"responses": {"200": {"description": "created"}}},
                }
            }
        )
        cs = build_source_change_set(_doc(), cand, "3.1.0")
        blocker = next(b for b in cs.blockers if b.code == "SHARED_RESPONSE_COLLISION")
        assert "GET" in blocker.message and "POST" in blocker.message

    def test_identical_shared_responses_are_fine(self):
        cand = _doc(
            paths={
                "/pets": {
                    "get": {"responses": {"200": {"description": "ok"}}},
                    "post": {"responses": {"200": {"description": "ok"}}},
                }
            }
        )
        cs = build_source_change_set(_doc(), cand, "3.1.0")
        assert all(b.code != "SHARED_RESPONSE_COLLISION" for b in cs.blockers)

    def test_shared_parameter_collision_blocked(self):
        cand = _doc(
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
                            {"name": "limit", "in": "query", "schema": {"type": "string"}}
                        ],
                        "responses": {"204": {"description": "gone"}},
                    },
                }
            }
        )
        cs = build_source_change_set(_doc(), cand, "3.1.0")
        blocker = next(b for b in cs.blockers if b.code == "SHARED_PARAMETER_COLLISION")
        assert "'limit'" in blocker.message


class TestRefIntegrity:
    def test_dangling_local_ref_reported_with_pointer(self):
        cand = _doc(
            components={
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {"toy": {"$ref": "#/components/schemas/Toy"}},
                    }
                }
            }
        )
        errors = ref_integrity_errors(cand)
        assert len(errors) == 1
        assert errors[0].ref == "#/components/schemas/Toy"
        assert errors[0].pointer == "/components/schemas/Pet/properties/toy/$ref"

    def test_resolvable_and_external_refs_pass(self):
        cand = _doc(
            components={
                "schemas": {
                    "Toy": {"type": "object"},
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "toy": {"$ref": "#/components/schemas/Toy"},
                            "ext": {"$ref": "./other.yaml#/Thing"},
                        },
                    },
                }
            }
        )
        assert ref_integrity_errors(cand) == []
