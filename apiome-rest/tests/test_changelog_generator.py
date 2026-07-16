"""Tests for CTG-1.3 changelog generator (#4469)."""

from __future__ import annotations

import copy
import json

import pytest

from app.change_taxonomy import ClassifiedChange, ClassifiedDiff, classify_openapi_changes
from app.changelog_generator import (
    CHANGELOG_SCHEMA_VERSION,
    aggregate_changelogs,
    aggregate_classified_diffs,
    build_changelog,
    changelog_since,
    path_group_for_pointer,
    render_changelog_json,
    render_changelog_json_text,
    render_changelog_markdown,
)


def _pet_docs() -> tuple[dict, dict]:
    base = {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.0.0", "description": "Pets API"},
        "paths": {
            "/pets": {
                "get": {
                    "summary": "List pets",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["id"],
                }
            }
        },
    }
    return base, copy.deepcopy(base)


def test_path_group_for_pointer() -> None:
    assert path_group_for_pointer("/paths/~1pets/get/responses/200") == "/paths/~1pets"
    assert path_group_for_pointer("/components/schemas/Pet/properties/name") == ("/components/schemas/Pet")
    assert path_group_for_pointer("/servers/0/url") == "/servers"
    assert path_group_for_pointer("/info/description") == "/info"
    assert path_group_for_pointer("/tags/0/description") == "/tags"
    assert path_group_for_pointer("/") == "/"
    assert path_group_for_pointer("") == "/"


def test_empty_classified_diff_produces_empty_changelog() -> None:
    base, head = _pet_docs()
    cl = build_changelog(classify_openapi_changes(base, head), from_version="1.0.0", to_version="1.0.0")
    assert cl.entries == []
    assert cl.max_severity is None
    assert cl.counts["total"] == 0
    assert cl.schema_version == CHANGELOG_SCHEMA_VERSION
    assert cl.from_version == "1.0.0"
    assert cl.to_version == "1.0.0"


def test_ordering_breaking_before_non_breaking_before_docs() -> None:
    base, head = _pet_docs()
    # docs-only
    head["info"]["description"] = "Updated Pets API"
    # non-breaking (property added)
    head["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    # breaking (path removed) — also remove the only path after copy of ops
    del head["paths"]["/pets"]

    classified = classify_openapi_changes(base, head)
    cl = build_changelog(classified)

    severities = [e.severity for e in cl.entries]
    assert severities == sorted(severities, key=lambda s: {"breaking": 0, "non-breaking": 1, "docs-only": 2}[s])
    assert cl.entries[0].severity == "breaking"
    assert cl.max_severity == "breaking"
    assert cl.counts["breaking"] >= 1
    assert cl.counts["non-breaking"] >= 1
    assert cl.counts["docs-only"] >= 1


def test_ordering_grouped_by_path_within_severity() -> None:
    """Within the same severity, entries sort by path_group then pointer."""
    changes = [
        ClassifiedChange(
            rule_id="ctg.property_removed",
            severity="breaking",
            pointer="/components/schemas/Zebra/properties/z",
            change_kind="property_removed",
        ),
        ClassifiedChange(
            rule_id="ctg.path_removed",
            severity="breaking",
            pointer="/paths/~1alpha",
            change_kind="path_removed",
        ),
        ClassifiedChange(
            rule_id="ctg.property_removed",
            severity="breaking",
            pointer="/components/schemas/Apple/properties/a",
            change_kind="property_removed",
        ),
        ClassifiedChange(
            rule_id="ctg.path_removed",
            severity="breaking",
            pointer="/paths/~1beta",
            change_kind="path_removed",
        ),
    ]
    cl = build_changelog(ClassifiedDiff(changes=changes, counts={}, max_severity="breaking"))
    groups = [e.path_group for e in cl.entries]
    assert groups == sorted(groups)
    assert cl.entries[0].path_group == "/components/schemas/Apple"
    assert cl.entries[-1].path_group == "/paths/~1beta"


def test_ordering_is_deterministic_across_runs() -> None:
    base, head = _pet_docs()
    head["paths"]["/pets"]["post"] = {"responses": {"201": {"description": "created"}}}
    head["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    head["info"]["description"] = "v2"

    a = render_changelog_json_text(build_changelog(classify_openapi_changes(base, head)))
    b = render_changelog_json_text(build_changelog(classify_openapi_changes(base, head)))
    assert a == b


def test_markdown_renderer_stable_structure() -> None:
    base, head = _pet_docs()
    del head["paths"]["/pets"]
    head["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    head["info"]["description"] = "Changed"

    md = render_changelog_markdown(
        build_changelog(
            classify_openapi_changes(base, head),
            from_version="1.0.0",
            to_version="1.1.0",
        )
    )
    assert md.startswith("# Changelog\n")
    assert "**Since** `1.0.0` → `1.1.0`" in md
    assert "## Breaking changes" in md
    assert "## Non-breaking changes" in md
    assert "## Documentation changes" in md
    # Breaking section appears before non-breaking
    assert md.index("## Breaking changes") < md.index("## Non-breaking changes")
    assert md.index("## Non-breaking changes") < md.index("## Documentation changes")
    assert "`ctg.path_removed`" in md
    assert "`/pets`" in md or "`/paths/~1pets`" in md


def test_markdown_empty() -> None:
    md = render_changelog_markdown(build_changelog(ClassifiedDiff(changes=[])))
    assert "No changes." in md


def test_json_renderer_schema_stable_keys() -> None:
    base, head = _pet_docs()
    del head["paths"]["/pets"]
    cl = build_changelog(
        classify_openapi_changes(base, head),
        from_version="1.0.0",
        to_version="2.0.0",
    )
    payload = render_changelog_json(cl)
    assert payload["schemaVersion"] == CHANGELOG_SCHEMA_VERSION
    assert payload["fromVersion"] == "1.0.0"
    assert payload["toVersion"] == "2.0.0"
    assert payload["maxSeverity"] == "breaking"
    assert set(payload["counts"].keys()) >= {
        "breaking",
        "non-breaking",
        "docs-only",
        "unclassified",
        "total",
    }
    entry = payload["entries"][0]
    assert set(entry.keys()) == {
        "severity",
        "pathGroup",
        "pointer",
        "ruleId",
        "changeKind",
        "summary",
        "before",
        "after",
        "unclassified",
        "fromVersion",
        "toVersion",
    }
    # Text form is sorted-key stable
    text = render_changelog_json_text(cl)
    assert json.loads(text) == payload


def test_aggregate_across_intermediate_versions() -> None:
    """v1.0 → v1.1 (add property) → v1.2 (remove path) aggregates both hops."""
    v1, v11 = _pet_docs()
    v11["info"]["version"] = "1.1.0"
    v11["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}

    v12 = copy.deepcopy(v11)
    v12["info"]["version"] = "1.2.0"
    del v12["paths"]["/pets"]

    cl = changelog_since(
        [
            ("1.0.0", v1),
            ("1.1.0", v11),
            ("1.2.0", v12),
        ]
    )
    assert cl.from_version == "1.0.0"
    assert cl.to_version == "1.2.0"
    assert cl.counts["total"] >= 2
    assert cl.max_severity == "breaking"

    rule_ids = {e.rule_id for e in cl.entries}
    assert "ctg.property_added" in rule_ids
    assert "ctg.path_removed" in rule_ids

    # Per-hop provenance preserved
    hops = {(e.from_version, e.to_version) for e in cl.entries}
    assert ("1.0.0", "1.1.0") in hops
    assert ("1.1.0", "1.2.0") in hops

    # Aggregate still ordered breaking-first
    assert cl.entries[0].severity == "breaking"

    md = render_changelog_markdown(cl)
    assert "**Since** `1.0.0` → `1.2.0`" in md
    assert "1.0.0 → 1.1.0" in md or "1.1.0 → 1.2.0" in md


def test_aggregate_changelogs_and_classified_diffs() -> None:
    v1, v11 = _pet_docs()
    v11["components"]["schemas"]["Pet"]["properties"]["tag"] = {"type": "string"}
    v12 = copy.deepcopy(v11)
    del v12["paths"]["/pets"]

    d1 = classify_openapi_changes(v1, v11)
    d2 = classify_openapi_changes(v11, v12)
    via_diffs = aggregate_classified_diffs([("1.0.0", "1.1.0", d1), ("1.1.0", "1.2.0", d2)])
    via_cls = aggregate_changelogs(
        [
            build_changelog(d1, from_version="1.0.0", to_version="1.1.0"),
            build_changelog(d2, from_version="1.1.0", to_version="1.2.0"),
        ]
    )
    assert render_changelog_json_text(via_diffs) == render_changelog_json_text(via_cls)


def test_changelog_since_single_document_empty() -> None:
    base, _ = _pet_docs()
    cl = changelog_since([("1.0.0", base)])
    assert cl.entries == []
    assert cl.from_version == "1.0.0"
    assert cl.to_version == "1.0.0"


def test_changelog_since_rejects_empty_labels() -> None:
    base, head = _pet_docs()
    with pytest.raises(ValueError, match="non-empty"):
        changelog_since([("", base), ("1.1.0", head)])


def test_unclassified_summary_and_flag() -> None:
    change = ClassifiedChange(
        rule_id="ctg.unclassified",
        severity="breaking",
        pointer="/x",
        unclassified=True,
        change_kind="mystery_kind",
    )
    cl = build_changelog(ClassifiedDiff(changes=[change], counts={}, max_severity="breaking"))
    assert cl.entries[0].unclassified is True
    assert "Unclassified" in cl.entries[0].summary
    md = render_changelog_markdown(cl)
    assert "(unclassified)" in md
