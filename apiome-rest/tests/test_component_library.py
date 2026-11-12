"""Component-library pure domain logic — DCW-3.1 (private-suite#2353).

Payload validation per kind, semver revision ordering (the no-unsafe-downgrade
rule), canonical payload digests, and the deterministic single-file
materializer: stable ordering, collision-safe naming that never overwrites a
local component, optional ``x-apiome-origin`` provenance that can be stripped
without invalidating the document, and security-bundle expansion.
"""

import copy

from app.component_library import (
    KIND_SECTIONS,
    ORIGIN_KEY,
    materialize_pinned_components,
    parse_semver,
    payload_digest,
    semver_greater,
    strip_origin_metadata,
    validate_component_name,
    validate_component_payload,
)


def _row(**overrides):
    row = {
        "kind": "parameter",
        "component_name": "PageParam",
        "local_name": None,
        "revision": "1.0.0",
        "payload": {"name": "page", "in": "query"},
        "component_id": "c-1",
        "revision_id": "r-1",
    }
    row.update(overrides)
    return row


class TestRevisions:
    def test_parse_semver(self):
        assert parse_semver("1.2.3") == (1, 2, 3)
        assert parse_semver("10.0.0") == (10, 0, 0)
        for bad in ("1.2", "1.2.3-beta", "v1.2.3", 1, None, ""):
            assert parse_semver(bad) is None

    def test_no_unsafe_downgrade_rule(self):
        assert semver_greater("1.0.1", "1.0.0")
        assert semver_greater("2.0.0", "1.9.9")
        assert semver_greater("0.1.0", None)
        assert not semver_greater("1.0.0", "1.0.0")
        assert not semver_greater("0.9.9", "1.0.0")
        assert not semver_greater("not-semver", None)
        # Numeric, not lexicographic: 0.10.0 > 0.9.0.
        assert semver_greater("0.10.0", "0.9.0")

    def test_payload_digest_is_canonical(self):
        assert payload_digest({"b": 1, "a": 2}) == payload_digest({"a": 2, "b": 1})
        assert payload_digest({"a": 1}) != payload_digest({"a": 2})
        assert payload_digest({}).startswith("sha256:")


class TestNames:
    def test_component_name_shape(self):
        for good in ("Pet", "page-param", "X_Request.Id", "a" * 128):
            assert validate_component_name(good)
        for bad in ("", "1abc", "-abc", "has space", "a" * 129, None, 7):
            assert not validate_component_name(bad)


class TestPayloadValidation:
    def test_parameter(self):
        assert validate_component_payload("parameter", {"name": "p", "in": "query"}) == []
        codes = [e["code"] for e in validate_component_payload("parameter", {"in": "nowhere"})]
        assert "PARAMETER_NAME_REQUIRED" in codes
        assert "PARAMETER_IN_INVALID" in codes

    def test_path_parameter_requires_required_true(self):
        errors = validate_component_payload("parameter", {"name": "id", "in": "path"})
        assert [e["code"] for e in errors] == ["PARAMETER_PATH_REQUIRED"]
        assert validate_component_payload(
            "parameter", {"name": "id", "in": "path", "required": True}
        ) == []

    def test_header_forbids_name_and_in(self):
        assert validate_component_payload("header", {"schema": {"type": "string"}}) == []
        codes = [e["code"] for e in validate_component_payload("header", {"name": "X", "in": "header"})]
        assert codes == ["HEADER_FORBIDDEN_KEY", "HEADER_FORBIDDEN_KEY"]

    def test_request_body_requires_content(self):
        assert validate_component_payload(
            "requestBody", {"content": {"application/json": {}}}
        ) == []
        codes = [e["code"] for e in validate_component_payload("requestBody", {})]
        assert codes == ["REQUEST_BODY_CONTENT_REQUIRED"]

    def test_response_requires_description(self):
        assert validate_component_payload("response", {"description": "OK"}) == []
        codes = [e["code"] for e in validate_component_payload("response", {})]
        assert codes == ["RESPONSE_DESCRIPTION_REQUIRED"]

    def test_security_bundle(self):
        good = {"schemes": {"apiKeyAuth": {"type": "apiKey", "name": "X-Key", "in": "header"}}}
        assert validate_component_payload("securityBundle", good) == []
        codes = [e["code"] for e in validate_component_payload("securityBundle", {})]
        assert codes == ["SECURITY_BUNDLE_SCHEMES_REQUIRED"]
        codes = [
            e["code"]
            for e in validate_component_payload(
                "securityBundle", {"schemes": {"bad name": {"type": "wrong"}}}
            )
        ]
        assert "SECURITY_SCHEME_NAME_INVALID" in codes
        assert "SECURITY_SCHEME_TYPE_INVALID" in codes

    def test_schema_kind_accepts_any_object(self):
        assert validate_component_payload("schema", {"type": "string"}) == []

    def test_non_object_and_unknown_kind(self):
        assert [e["code"] for e in validate_component_payload("response", "nope")] == [
            "COMPONENT_PAYLOAD_TYPE"
        ]
        assert [e["code"] for e in validate_component_payload("mystery", {})] == [
            "COMPONENT_KIND_INVALID"
        ]


class TestMaterializer:
    def test_every_kind_lands_in_its_standard_section(self):
        rows = [
            _row(kind="parameter", component_name="P", payload={"name": "p", "in": "query"}),
            _row(kind="header", component_name="H", payload={"schema": {}}, revision_id="r-h"),
            _row(kind="requestBody", component_name="B", payload={"content": {}}, revision_id="r-b"),
            _row(kind="response", component_name="R", payload={"description": "ok"}, revision_id="r-r"),
            _row(kind="schema", component_name="S", payload={"type": "string"}, revision_id="r-s"),
        ]
        result = materialize_pinned_components({}, rows)
        components = result.document["components"]
        assert set(components) == {"parameters", "headers", "requestBodies", "responses", "schemas"}
        assert components["parameters"]["P"]["name"] == "p"
        assert components["schemas"]["S"]["type"] == "string"
        assert all(entry.collided is False for entry in result.entries)

    def test_never_overwrites_local_components(self):
        document = {"components": {"schemas": {"Pet": {"type": "object", "local": True}}}}
        before = copy.deepcopy(document)
        result = materialize_pinned_components(
            document, [_row(kind="schema", component_name="Pet", payload={"type": "string"})]
        )
        # The input document is never mutated, and the local Pet survives.
        assert document == before
        schemas = result.document["components"]["schemas"]
        assert schemas["Pet"] == {"type": "object", "local": True}
        assert schemas["Pet_2"]["type"] == "string"
        assert [c.name for c in result.collisions] == ["Pet_2"]
        assert result.collisions[0].requested_name == "Pet"

    def test_materialization_is_deterministic(self):
        rows = [
            _row(component_name="Zed", revision_id="r-z"),
            _row(component_name="Alpha", revision_id="r-a"),
            _row(component_name="Alpha", revision_id="r-b", revision="2.0.0"),
        ]
        first = materialize_pinned_components({}, list(rows))
        second = materialize_pinned_components({}, list(reversed(rows)))
        assert first.document == second.document
        assert [e.as_dict() for e in first.entries] == [e.as_dict() for e in second.entries]
        # Sorted processing: Alpha 1.0.0, Alpha 2.0.0 (renamed), then Zed.
        assert [e.name for e in first.entries] == ["Alpha", "Alpha_2", "Zed"]

    def test_local_name_override_wins(self):
        result = materialize_pinned_components(
            {}, [_row(component_name="PageParam", local_name="Page")]
        )
        assert list(result.document["components"]["parameters"]) == ["Page"]

    def test_origin_metadata_optional_and_strippable(self):
        rows = [_row()]
        with_origin = materialize_pinned_components({}, rows, include_origin=True)
        entry = with_origin.document["components"]["parameters"]["PageParam"]
        assert entry[ORIGIN_KEY] == {
            "library": "PageParam",
            "revision": "1.0.0",
            "componentId": "c-1",
            "revisionId": "r-1",
        }

        without_origin = materialize_pinned_components({}, rows, include_origin=False)
        assert ORIGIN_KEY not in without_origin.document["components"]["parameters"]["PageParam"]

        # Stripping origin from the materialized document yields exactly the
        # origin-free document: valid without the metadata (re-import rule).
        stripped = with_origin.document
        assert strip_origin_metadata(stripped) == 1
        assert stripped == without_origin.document

    def test_security_bundle_expands_into_individual_schemes(self):
        payload = {
            "schemes": {
                "apiKeyAuth": {"type": "apiKey", "name": "X-Key", "in": "header"},
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        }
        document = {"components": {"securitySchemes": {"bearerAuth": {"type": "http", "local": True}}}}
        result = materialize_pinned_components(
            document, [_row(kind="securityBundle", component_name="AuthBundle", payload=payload)]
        )
        schemes = result.document["components"]["securitySchemes"]
        # Local bearerAuth survives; the bundle's scheme gets a collision-safe name.
        assert schemes["bearerAuth"] == {"type": "http", "local": True}
        assert schemes["bearerAuth_2"]["scheme"] == "bearer"
        assert schemes["apiKeyAuth"]["type"] == "apiKey"
        assert schemes["apiKeyAuth"][ORIGIN_KEY]["library"] == "AuthBundle"
        assert [c.requested_name for c in result.collisions] == ["bearerAuth"]

    def test_empty_pins_leave_document_untouched(self):
        document = {"openapi": "3.1.0", "components": {"schemas": {}}}
        result = materialize_pinned_components(document, [])
        assert result.document == document
        assert result.entries == []

    def test_malformed_rows_are_skipped(self):
        result = materialize_pinned_components(
            {},
            [
                _row(payload="not-a-dict"),
                _row(kind="unknown-kind", revision_id="r-x"),
                _row(kind="securityBundle", payload={"schemes": "nope"}, revision_id="r-y"),
            ],
        )
        assert result.entries == []

    def test_kind_sections_cover_all_kinds(self):
        assert set(KIND_SECTIONS.values()) == {
            "parameters",
            "headers",
            "requestBodies",
            "responses",
            "securitySchemes",
            "schemas",
        }
