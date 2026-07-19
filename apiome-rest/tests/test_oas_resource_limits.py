"""Field-for-field pins on the DCW-0.2/DCW-0.1 artifact mirrors — DCW-2.1 (private-suite#2352).

The backend copies of ``oas-resource-limits.json`` and ``oas-capability-matrix.json``
must mirror the designer artifacts field-for-field. These tests pin the versions
and every enforced value, so a drift on either side of the mirror fails CI and
forces a reviewed, simultaneous bump (the DCW-0.1 consumer-pin convention).
"""

from app.oas_resource_limits import (
    capability_for_pointer,
    lexical_exclusions,
    load_capability_matrix_artifact,
    load_resource_limits_artifact,
    resource_limit_values,
    supported_dialects,
)


class TestResourceLimitsMirror:
    def test_limits_version_pin(self):
        assert load_resource_limits_artifact()["limitsVersion"] == "1.0.0"

    def test_limit_values_pin(self):
        values = resource_limit_values()
        assert values.max_document_bytes == 10_485_760
        assert values.max_alias_count == 100
        assert values.max_nesting_depth == 256
        assert values.max_yaml_documents_per_source == 1

    def test_diagnostic_codes_pin(self):
        limits = load_resource_limits_artifact()["limits"]
        assert limits["maxDocumentBytes"]["diagnosticCode"] == "OAS_LIMIT_DOCUMENT_BYTES"
        assert limits["maxAliasCount"]["diagnosticCode"] == "OAS_LIMIT_ALIAS_COUNT"
        assert limits["maxNestingDepth"]["diagnosticCode"] == "OAS_LIMIT_NESTING_DEPTH"
        assert limits["maxYamlDocumentsPerSource"]["diagnosticCode"] == "OAS_MULTIPLE_DOCUMENTS"

    def test_duplicate_key_policy_pin(self):
        policy = load_resource_limits_artifact()["duplicateKeyPolicy"]
        assert policy["policy"] == "reject"
        assert policy["diagnosticCode"] == "OAS_DUPLICATE_KEY"

    def test_violation_posture_is_non_mutating(self):
        posture = load_resource_limits_artifact()["onViolation"]
        assert posture["behavior"] == "structured-diagnostics"
        assert posture["mutation"] == "none"

    def test_backend_is_a_declared_consumer(self):
        assert "backend-parse" in load_resource_limits_artifact()["appliesTo"]


class TestCapabilityMatrixMirror:
    def test_matrix_version_pin(self):
        assert load_capability_matrix_artifact()["matrixVersion"] == "1.0.0"

    def test_supported_dialects_pin(self):
        assert supported_dialects() == ["3.1.0", "3.2.0"]

    def test_lexical_exclusions_pin(self):
        assert lexical_exclusions() == [
            "comments",
            "anchors",
            "key-order",
            "quoting",
            "whitespace",
            "multi-file-layout",
        ]


class TestCapabilityForPointer:
    def test_extension_pointer_resolves_to_extension_capability(self):
        assert capability_for_pointer("3.1.0", "/x-sdk-config") == "preserved-read-only"
        assert capability_for_pointer("3.1.0", "/x-sdk-config/languages/0") == "preserved-read-only"

    def test_family_prefix_match(self):
        assert capability_for_pointer("3.1.0", "/webhooks/widgetCreated") == "preserved-read-only"
        assert capability_for_pointer("3.1.0", "/info/title") == "visual-edit"
        assert capability_for_pointer("3.1.0", "/servers/0/x-region") == "raw-edit"

    def test_longest_prefix_wins(self):
        # /components/links is preserved-read-only even though /components has no
        # blanket family; /components/schemas is visual-edit.
        assert capability_for_pointer("3.1.0", "/components/links/WidgetById") == "preserved-read-only"
        assert capability_for_pointer("3.1.0", "/components/schemas/Widget") == "visual-edit"

    def test_unmatched_pointer_falls_back_to_default(self):
        assert capability_for_pointer("3.1.0", "/nonstandardTopLevel") == "preserved-read-only"

    def test_32_only_families(self):
        assert capability_for_pointer("3.2.0", "/$self") == "raw-edit"

    def test_unknown_dialect_raises(self):
        import pytest

        with pytest.raises(ValueError):
            capability_for_pointer("2.0", "/info")
