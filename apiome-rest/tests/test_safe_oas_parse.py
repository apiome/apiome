"""Backend safe-parse wrapper under the DCW-0.2 limits — DCW-2.1 (private-suite#2352).

Mirrors the designer's ``tests/safe-oas-parse.test.ts`` coverage: duplicate keys
(YAML **and** JSON — the backend closes the documented JSON gap), alias
expansion, nesting depth, circular aliases, oversized and multi-document
sources all fail with structured, non-mutating diagnostics; no failure class
ever raises or returns a partial document.
"""

from app.oas_resource_limits import OasResourceLimitValues, resource_limit_values
from app.safe_oas_parse import safe_oas_parse


def _tight(**overrides) -> OasResourceLimitValues:
    """Artifact limits with per-test overrides (keeps adversarial fixtures tiny)."""
    base = resource_limit_values()
    values = {
        "max_document_bytes": base.max_document_bytes,
        "max_alias_count": base.max_alias_count,
        "max_nesting_depth": base.max_nesting_depth,
        "max_yaml_documents_per_source": base.max_yaml_documents_per_source,
    }
    values.update(overrides)
    return OasResourceLimitValues(**values)


class TestHappyPath:
    def test_valid_yaml_parses(self):
        result = safe_oas_parse("openapi: 3.1.0\ninfo:\n  title: T\n  version: '1'\n")
        assert result.ok
        assert result.diagnostics == []
        assert result.document["openapi"] == "3.1.0"

    def test_valid_json_parses(self):
        result = safe_oas_parse('{"openapi": "3.1.0"}', source_format="json")
        assert result.ok
        assert result.document == {"openapi": "3.1.0"}

    def test_benign_alias_reuse_parses(self):
        text = "base: &b\n  a: 1\nreuse:\n  <<: *b\nother: *b\n"
        result = safe_oas_parse(text)
        assert result.ok
        assert result.document["other"] == {"a": 1}


class TestDocumentBytes:
    def test_oversized_document_rejected_before_parse(self):
        result = safe_oas_parse("a" * 100, limits=_tight(max_document_bytes=10))
        assert not result.ok
        assert result.document is None
        [diag] = result.diagnostics
        assert diag.code == "OAS_LIMIT_DOCUMENT_BYTES"
        assert diag.limit == 10
        assert diag.actual == 100

    def test_multibyte_characters_counted_as_utf8(self):
        result = safe_oas_parse("é" * 6, limits=_tight(max_document_bytes=10))
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_LIMIT_DOCUMENT_BYTES"
        assert result.diagnostics[0].actual == 12


class TestDuplicateKeys:
    def test_yaml_duplicate_key_rejected_with_position(self):
        result = safe_oas_parse("a: 1\nb: 2\na: 3\n")
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_DUPLICATE_KEY"
        assert diag.line == 3
        assert result.document is None

    def test_yaml_nested_duplicate_key_rejected(self):
        result = safe_oas_parse("outer:\n  inner: 1\n  inner: 2\n")
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_DUPLICATE_KEY"

    def test_json_duplicate_key_rejected(self):
        # The designer documents JSON duplicate detection as a gap owned by this
        # backend parser; here it is closed.
        result = safe_oas_parse('{"a": 1, "a": 2}', source_format="json")
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_DUPLICATE_KEY"
        assert "a" in diag.message

    def test_json_nested_duplicate_key_rejected(self):
        result = safe_oas_parse('{"o": {"x": 1, "x": 2}}', source_format="json")
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_DUPLICATE_KEY"


class TestAliasExpansion:
    def test_alias_bomb_rejected(self):
        # Classic billion-laughs shape: each level multiplies the expansion.
        text = (
            "a: &a [x, x, x, x, x, x, x, x, x]\n"
            "b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\n"
            "c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b]\n"
            "d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c]\n"
        )
        result = safe_oas_parse(text)
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_LIMIT_ALIAS_COUNT"
        assert result.document is None

    def test_modest_alias_use_within_bound_parses(self):
        text = "a: &a {k: v}\nb: *a\nc: *a\n"
        result = safe_oas_parse(text)
        assert result.ok

    def test_alias_count_bound_enforced_exactly(self):
        text = "a: &a {k: v}\nb: *a\nc: *a\nd: *a\n"
        result = safe_oas_parse(text, limits=_tight(max_alias_count=2))
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_LIMIT_ALIAS_COUNT"


class TestCircularAliases:
    def test_self_referential_alias_rejected(self):
        result = safe_oas_parse("a: &a\n  self: *a\n")
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_CIRCULAR_ALIAS"
        assert result.document is None


class TestNestingDepth:
    def test_deep_yaml_block_nesting_rejected(self):
        depth = 12
        text = "".join(f"{'  ' * i}k{i}:\n" for i in range(depth)) + f"{'  ' * depth}leaf: 1\n"
        result = safe_oas_parse(text, limits=_tight(max_nesting_depth=8))
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_LIMIT_NESTING_DEPTH"

    def test_deep_json_nesting_rejected(self):
        text = "[" * 12 + "1" + "]" * 12
        result = safe_oas_parse(text, source_format="json", limits=_tight(max_nesting_depth=8))
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_LIMIT_NESTING_DEPTH"

    def test_pathological_depth_caught_by_pre_scan(self):
        text = "[" * 5000 + "]" * 5000
        result = safe_oas_parse(text, source_format="json", limits=_tight(max_nesting_depth=8))
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_LIMIT_NESTING_DEPTH"

    def test_depth_at_limit_parses(self):
        text = '{"a": {"b": {"c": 1}}}'
        result = safe_oas_parse(text, source_format="json", limits=_tight(max_nesting_depth=3))
        assert result.ok


class TestMultipleDocuments:
    def test_multi_document_stream_rejected(self):
        result = safe_oas_parse("---\na: 1\n---\nb: 2\n")
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_MULTIPLE_DOCUMENTS"
        assert diag.actual == 2


class TestSyntaxErrors:
    def test_yaml_syntax_error_structured(self):
        result = safe_oas_parse("a: [1, 2\nb: }{")
        assert not result.ok
        assert result.diagnostics[0].code == "OAS_YAML_SYNTAX"
        assert result.document is None

    def test_json_syntax_error_structured_with_position(self):
        result = safe_oas_parse('{"a": }', source_format="json")
        assert not result.ok
        [diag] = result.diagnostics
        assert diag.code == "OAS_JSON_SYNTAX"
        assert diag.line == 1
        assert diag.col is not None


class TestAllOrNothing:
    def test_failure_carries_no_document(self):
        for text, fmt in [
            ("a: 1\na: 2\n", "yaml"),
            ('{"a": 1, "a": 2}', "json"),
            ("---\na: 1\n---\nb: 2\n", "yaml"),
        ]:
            result = safe_oas_parse(text, source_format=fmt)
            assert not result.ok
            assert result.document is None
            assert len(result.diagnostics) >= 1

    def test_input_text_never_mutated(self):
        text = "a: &a [x]\nb: *a\n"
        snapshot = str(text)
        safe_oas_parse(text)
        assert text == snapshot
