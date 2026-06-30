"""Tests for the GraphQL lint pack (MFI-10.4, #3773).

The acceptance criteria are: **lints SDL**, and **findings are scored**. These tests pin three
layers, all pure (no DB/network/Node — the whole GraphQL toolchain is pure-Python ``graphql-core``):

* the **native rule pack** (:class:`app.graphql_lint.GraphqlRulePack`) — each rule fires on a
  defective schema and a clean, fully documented/named schema produces no ``graphql.*`` findings —
  registered under the ``graphql`` format key. Driven through the *real* MFI-10.1 parser + MFI-10.2
  normalizer so the canonical coordinates the rules emit are the genuine ones;
* the **graphql-eslint mapping** (:func:`app.graphql_lint.eslint_findings`) — ESLint JSON output
  becomes namespaced, severity-folded findings;
* the **merge** — :func:`app.graphql_lint.lint_graphql_result` rolls graphql-eslint + native +
  common into one deterministic score, and :func:`app.graphql_lint.lint_graphql` does it
  end-to-end from raw SDL.
"""

from __future__ import annotations

from typing import Set

import pytest

from app.graphql_lint import (
    GRAPHQL_ESLINT_PLUGIN_PREFIX,
    GRAPHQL_ESLINT_RULE_PREFIX,
    GraphqlRulePack,
    eslint_findings,
    lint_graphql,
    lint_graphql_result,
)
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import GraphQlParseError, build_graphql_schema
from app.lint_engine import available_lint_formats, get_rule_pack, lint_canonical_model
from app.schema_lint import LintResult

# ===========================================================================
# SDL fixtures (real schemas, built + normalized through MFI-10.1 / 10.2)
# ===========================================================================

# Tidy: PascalCase types, camelCase fields/ops/args, UPPER_CASE enum values, every entity
# documented, no deprecation issues — so it yields *no* native ``graphql.*`` finding.
_CLEAN_SDL = '''
"""A tidy blog API."""
type Query {
  """Fetch one post by id."""
  post("""The post id.""" id: ID!): Post
}

"""A blog post."""
type Post {
  """Unique id."""
  id: ID!
  """Its lifecycle status."""
  status: PostStatus!
}

"""Lifecycle states."""
enum PostStatus {
  """Not yet published."""
  DRAFT
  """Visible to everyone."""
  PUBLISHED
}
'''

# Dirty but *valid* schema (it builds): a non-PascalCase enum, a non-camelCase field + operation,
# a non-camelCase argument, a lowercase enum value, and a blank @deprecated reason.
_DIRTY_SDL = '''
"""A dirty API."""
type Query {
  """A good op."""
  good("""ok""" id: ID!): Thing
  """A badly named op."""
  Bad_op("""ok""" BadArg: ID!): Thing
}

"""A thing."""
type Thing {
  """ok"""
  id: ID!
  """A badly named field."""
  Bad_Field: String
  """A legacy field."""
  legacy: String @deprecated(reason: "")
}

"""A badly named enum."""
enum bad_enum {
  """ok"""
  ok
  """ok"""
  GOOD
}
'''

# Valid, well-named, but missing descriptions on an argument and on enum values.
_NODOC_SDL = '''
"""An API."""
type Query {
  """Search."""
  search(term: String!): String
}

"""A colour."""
enum Color {
  RED
  BLUE
}
'''


def _model(sdl: str):
    """Build + normalize raw SDL into the canonical GraphQL model (MFI-10.1 → 10.2)."""
    return GraphQlNormalizer().normalize(build_graphql_schema(sdl))


def _native_rules(result: LintResult) -> Set[str]:
    """The set of *native* ``graphql.*`` rule ids fired (excludes the graphql-eslint namespace)."""
    return {
        f.rule
        for f in result.findings
        if f.rule.startswith("graphql.")
        and not f.rule.startswith(GRAPHQL_ESLINT_RULE_PREFIX)
    }


# ===========================================================================
# Native rules — a clean schema is silent; each defect fires its rule
# ===========================================================================


def test_clean_schema_has_no_native_graphql_findings() -> None:
    result = lint_canonical_model(_model(_CLEAN_SDL))
    assert not _native_rules(result)
    # A high score: the only residue is the cross-format common pack's response-message
    # description (the normalizer's auto-created GraphQL response message carries none).
    assert result.score >= 95


def test_dirty_schema_surfaces_naming_and_deprecation_rules() -> None:
    fired = _native_rules(lint_canonical_model(_model(_DIRTY_SDL)))
    assert {
        "graphql.naming-type-pascal-case",
        "graphql.naming-field-camel-case",
        "graphql.naming-argument-camel-case",
        "graphql.naming-enum-value-upper-case",
        "graphql.require-deprecation-reason",
    } <= fired


def test_missing_descriptions_fire_require_description_rules() -> None:
    fired = _native_rules(lint_canonical_model(_model(_NODOC_SDL)))
    assert "graphql.argument-missing-description" in fired
    assert "graphql.enum-value-missing-description" in fired


def test_type_naming_rule_targets_the_bad_type_coordinate() -> None:
    result = lint_canonical_model(_model(_DIRTY_SDL))
    type_findings = [f for f in result.findings if f.rule == "graphql.naming-type-pascal-case"]
    assert [f.path for f in type_findings] == ["types.bad_enum"]


def test_field_naming_rule_covers_both_fields_and_operations() -> None:
    result = lint_canonical_model(_model(_DIRTY_SDL))
    paths = {f.path for f in result.findings if f.rule == "graphql.naming-field-camel-case"}
    # A non-camelCase type field and a non-camelCase root operation are both flagged.
    assert "types.Thing.fields.Thing.Bad_Field" in paths
    assert "services.Query.operations.Query.Bad_op" in paths


def test_blank_deprecation_reason_fires_but_default_reason_does_not() -> None:
    # `legacy` has an explicit empty reason → fires; a bare `@deprecated` would get graphql-core's
    # spec-default reason and would NOT fire (the authoritative bare check is graphql-eslint's).
    sdl = '''
    """API.""" type Query { """ok""" a("""ok""" id: ID!): String }
    """T""" type T { """blank""" blank: String @deprecated(reason: "") """def""" defaulted: String @deprecated }
    '''
    result = lint_canonical_model(_model(sdl))
    dep = [f for f in result.findings if f.rule == "graphql.require-deprecation-reason"]
    assert [f.path for f in dep] == ["types.T.fields.T.blank"]


def test_findings_are_deterministic() -> None:
    a = lint_canonical_model(_model(_DIRTY_SDL))
    b = lint_canonical_model(_model(_DIRTY_SDL))
    assert a.report_fingerprint == b.report_fingerprint
    assert a.score == b.score


# ===========================================================================
# Registry
# ===========================================================================


def test_pack_registered_under_graphql_format() -> None:
    pack_cls = get_rule_pack("graphql")
    assert pack_cls is GraphqlRulePack
    assert "graphql" in available_lint_formats()


def test_pack_rule_ids_are_unique_and_namespaced() -> None:
    rule_ids = [r.rule_id for r in GraphqlRulePack().rules()]
    assert rule_ids  # non-empty
    assert len(rule_ids) == len(set(rule_ids))  # unique
    assert all(r.startswith("graphql.") for r in rule_ids)


# ===========================================================================
# graphql-eslint output → canonical findings
# ===========================================================================


def test_eslint_findings_namespace_strip_and_severity_fold() -> None:
    report = [
        {
            "filePath": "schema.graphql",
            "messages": [
                {
                    "ruleId": f"{GRAPHQL_ESLINT_PLUGIN_PREFIX}naming-convention",
                    "severity": 2,
                    "message": "bad name",
                    "line": 3,
                    "column": 5,
                },
                {
                    "ruleId": f"{GRAPHQL_ESLINT_PLUGIN_PREFIX}require-description",
                    "severity": 1,
                    "message": "no description",
                    "line": 7,
                },
            ],
        }
    ]
    findings = eslint_findings(report)
    assert [f.rule for f in findings] == [
        f"{GRAPHQL_ESLINT_RULE_PREFIX}.naming-convention",
        f"{GRAPHQL_ESLINT_RULE_PREFIX}.require-description",
    ]
    assert [f.severity for f in findings] == ["error", "warning"]
    assert [f.category for f in findings] == ["graphql-eslint", "graphql-eslint"]
    assert findings[0].path == "schema.graphql:3:5"
    assert findings[1].path == "schema.graphql:7"  # column omitted → line only


def test_eslint_findings_fatal_message_and_unknown_severity() -> None:
    report = [
        {
            "filePath": "",
            "messages": [
                {"ruleId": None, "severity": 2, "message": "Parsing error"},
                {"ruleId": "@graphql-eslint/x", "severity": 0, "message": "off"},
            ],
        }
    ]
    findings = eslint_findings(report)
    assert findings[0].rule == f"{GRAPHQL_ESLINT_RULE_PREFIX}.fatal"
    assert findings[0].path == "(sdl)"  # blank filePath falls back
    assert findings[1].severity == "info"  # severity 0 folds to info


def test_eslint_findings_accepts_single_mapping_and_degrades_on_empty() -> None:
    single = {
        "filePath": "s.graphql",
        "messages": [{"ruleId": "@graphql-eslint/no-typename-prefix", "severity": 1, "message": "m"}],
    }
    assert len(eslint_findings(single)) == 1
    # Empty / None / non-iterable inputs contribute nothing (graceful degradation).
    assert eslint_findings(None) == []
    assert eslint_findings([]) == []
    assert eslint_findings("not a report") == []
    assert eslint_findings([{"filePath": "s", "messages": []}]) == []


# ===========================================================================
# Merge entry points
# ===========================================================================


def test_lint_graphql_result_degrades_without_eslint_report() -> None:
    model = _model(_DIRTY_SDL)
    result = lint_graphql_result(model)
    assert _native_rules(result)  # native rules still ran
    assert all(not f.rule.startswith(GRAPHQL_ESLINT_RULE_PREFIX) for f in result.findings)


def test_lint_graphql_result_merges_eslint_into_score() -> None:
    model = _model(_CLEAN_SDL)
    clean = lint_graphql_result(model)
    report = [
        {
            "filePath": "schema.graphql",
            "messages": [
                {
                    "ruleId": "@graphql-eslint/strict-id-in-types",
                    "severity": 2,
                    "message": "needs an id field",
                    "line": 2,
                    "column": 1,
                }
            ],
        }
    ]
    merged = lint_graphql_result(model, report)
    rules = {f.rule for f in merged.findings}
    assert f"{GRAPHQL_ESLINT_RULE_PREFIX}.strict-id-in-types" in rules
    assert merged.score < clean.score  # the external error lowered the score


def test_lint_graphql_end_to_end_from_raw_sdl() -> None:
    clean = lint_graphql(_CLEAN_SDL)
    assert not _native_rules(clean)

    dirty = lint_graphql(_DIRTY_SDL)
    assert _native_rules(dirty)
    assert dirty.score < clean.score


def test_lint_graphql_merges_eslint_report_end_to_end() -> None:
    report = [
        {
            "filePath": "schema.graphql",
            "messages": [
                {"ruleId": "@graphql-eslint/naming-convention", "severity": 2, "message": "m"}
            ],
        }
    ]
    result = lint_graphql(_CLEAN_SDL, eslint_report=report)
    assert any(f.rule == f"{GRAPHQL_ESLINT_RULE_PREFIX}.naming-convention" for f in result.findings)


def test_lint_graphql_raises_on_invalid_sdl() -> None:
    with pytest.raises(GraphQlParseError):
        lint_graphql("type Query { user: DoesNotExist }")
