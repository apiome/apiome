"""OpenAPI Overlay 1.0 / 1.1 / 1.2 and the ``overlay`` rule pack — GVM-4.1 (#5876).

The acceptance criteria, pinned without a database:

* **each supported marker applies, with a golden provenance** — the declared table
  (:data:`app.openapi_overlay.OVERLAY_READ_VERSIONS`) is evidenced by a corpus fileset per revision
  (34/35 → 1.0, 36 → 1.1, 37 → 1.2), and each set's provenance + findings are pinned in
  ``tests/golden/overlay/<set>.json`` (regenerate with ``APIOME_REGEN_OVERLAY_GOLDENS=1``);
* **a 1.3 marker is refused with the version message** — ``FORMAT_VERSION_UNSUPPORTED``, still
  classified as an overlay (not a format mismatch);
* **each revision's action semantics** — 1.0 append/replace, 1.1 concatenation, primitive targets,
  ``copy``, type checks, 1.2 reusable actions and ``$self``, ``extends`` resolution;
* **the five rules** are in the rule catalogue (``GET /v1/lint/rules``);
* **a bare overlay lint never reports base-dependent rules as clean** — they are ``skipped:
  no-base``; and ``POST /v1/lint/overlay`` serves it.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from corpus_adapter_support import build_fileset
from corpus_loader import FilesetRole, load_corpus
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.lint_rule_registry import builtin_rule_descriptors
from app.main import app
from app.openapi_import_source import OpenApiImportSource
from app.openapi_overlay import (
    FINDING_ACTION_INVALID,
    FINDING_EXTENDS_UNRESOLVED,
    FINDING_TARGET_EXPRESSION_INVALID,
    OVERLAY_READ_VERSIONS,
    SUPPORTED_REVISIONS,
    apply_overlays,
    lint_bare_overlay,
    overlay_lint_findings,
    overlay_revision,
    overlay_version,
)
from app.overlay_lint_rules import BASE_DEPENDENT_RULES, OVERLAY_RULES

_GOLDEN = Path(__file__).resolve().parent / "golden" / "overlay"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "overlay"


def _base() -> Dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.0.0", "description": "base"},
        "servers": [{"url": "http://localhost"}],
        "tags": ["a", "b"],
        "paths": {
            "/pets": {"get": {"summary": "List pets", "deprecated": False, "tags": ["pets"]}},
            "/old": {"get": {"summary": "Old"}},
        },
    }


def _overlay(actions: List[Any], version: str, **extra: Any) -> Dict[str, Any]:
    return {"overlay": version, "info": {"title": "o", "version": "1.0.0"}, "actions": actions, **extra}


def _apply(actions: List[Any], version: str, **extra: Any):
    return apply_overlays(_base(), [("o.yaml", _overlay(actions, version, **extra))])


# ===========================================================================
# Markers and the declared table
# ===========================================================================


@pytest.mark.parametrize(
    ("marker", "revision"),
    [
        ("1.0.0", "1.0"),
        ("1.0.3", "1.0"),
        ("1.1.0", "1.1"),
        ("1.2.0", "1.2"),
        ("1.2", "1.2"),
        ("1.3.0", None),
        ("2.0.0", None),
        ("1", None),
        ("", None),
        (None, None),
    ],
)
def test_a_marker_selects_its_revision_by_major_minor(marker, revision) -> None:
    assert overlay_revision(marker) == revision


def test_the_declared_table_is_1_0_1_1_1_2() -> None:
    assert SUPPORTED_REVISIONS == ("1.0", "1.1", "1.2")
    assert all(r.spec_url.startswith("https://spec.openapis.org/overlay/v") and r.note for r in OVERLAY_READ_VERSIONS)


def _corpus_revisions() -> Dict[str, List[str]]:
    """Read evidence: revision → corpus overlay members that declare it."""
    found: Dict[str, List[str]] = {}
    for entry in load_corpus(format="openapi", feature="overlay"):
        if entry.fileset_role is not FilesetRole.MEMBER or entry.validity_class.value != "valid":
            continue
        import yaml

        revision = overlay_revision(overlay_version(yaml.safe_load(entry.read_text())))
        if revision:
            found.setdefault(revision, []).append(entry.path)
    return found


def test_every_declared_revision_has_a_corpus_overlay() -> None:
    """The FMT-3.8 rule for overlays: a declared revision with no fixture is a false claim."""
    evidence = _corpus_revisions()
    assert sorted(evidence) == list(SUPPORTED_REVISIONS), evidence


@pytest.mark.parametrize("marker", ["1.3.0", "2.0.0"])
def test_an_unsupported_marker_is_a_version_rejection(marker) -> None:
    with pytest.raises(ImportSourceError) as caught:
        apply_overlays(_base(), [("o.yaml", _overlay([{"target": "$.info", "update": {}}], marker))])
    assert caught.value.code == "FORMAT_VERSION_UNSUPPORTED"
    assert "Apiome reads Overlay 1.0, 1.1 and 1.2" in str(caught.value)


def test_a_1_3_fileset_is_refused_with_the_version_message_not_a_format_mismatch() -> None:
    members = {p.name: p.read_text() for p in sorted((_FIXTURES / "1-3-set").iterdir())}
    with pytest.raises(ImportSourceError) as caught:
        OpenApiImportSource().parse_fileset(IntakeFileset.from_members(members, root="openapi.yaml"))
    assert caught.value.code == "FORMAT_VERSION_UNSUPPORTED"
    assert "'1.3.0'" in str(caught.value) and "Apiome reads Overlay 1.0, 1.1 and 1.2" in str(caught.value)


# ===========================================================================
# 1.0 semantics (unchanged)
# ===========================================================================


def test_1_0_appends_an_array_update_as_one_entry_and_replaces_arrays_in_a_merge() -> None:
    result = _apply(
        [
            {"target": "$.servers", "update": [{"url": "a"}, {"url": "b"}]},
            {"target": "$.paths['/pets'].get", "update": {"tags": ["public"]}},
        ],
        "1.0.0",
    )
    assert result.document["servers"][-1] == [{"url": "a"}, {"url": "b"}]
    assert result.document["paths"]["/pets"]["get"]["tags"] == ["public"]


def test_1_0_still_replaces_a_primitive_target() -> None:
    # The 1.0 text limits targets to objects and arrays; Apiome keeps replacing primitives, as it
    # always did and as 1.1 standardised (documented in docs/overlay.md).
    result = _apply([{"target": "$.paths['/pets'].get.deprecated", "update": True}], "1.0.0")
    assert result.document["paths"]["/pets"]["get"]["deprecated"] is True and not result.findings


def test_1_0_refuses_copy_and_reusable_actions() -> None:
    result = _apply(
        [{"target": "$.info", "copy": "$.paths['/old']"}, {"$ref": "#/components/actions/x", "target": "$.info"}],
        "1.0.0",
    )
    assert [f.code for f in result.findings] == [FINDING_ACTION_INVALID, FINDING_ACTION_INVALID]
    assert "1.1 added it" in result.findings[0].message and "1.2 added reusable actions" in result.findings[1].message


# ===========================================================================
# 1.1 semantics
# ===========================================================================


def test_1_1_concatenates_arrays_at_a_target_and_inside_a_merge() -> None:
    result = _apply(
        [
            {"target": "$.servers", "update": [{"url": "a"}, {"url": "b"}]},
            {"target": "$.paths['/pets'].get", "update": {"tags": ["public"]}},
        ],
        "1.1.0",
    )
    assert [s["url"] for s in result.document["servers"]] == ["http://localhost", "a", "b"]
    assert result.document["paths"]["/pets"]["get"]["tags"] == ["pets", "public"]
    assert [(r.pointer, r.kind) for r in result.provenance] == [
        ("/servers/1", "appended"),
        ("/servers/2", "appended"),
        ("/paths/~1pets/get/tags/1", "appended"),
    ]


def test_1_1_an_incompatible_merge_leaves_the_node_untouched() -> None:
    before = copy.deepcopy(_base()["paths"]["/pets"]["get"])
    result = _apply([{"target": "$.paths['/pets'].get", "update": {"summary": "New", "tags": "not-an-array"}}], "1.1.0")
    assert result.document["paths"]["/pets"]["get"] == before
    [finding] = result.findings
    assert finding.code == FINDING_ACTION_INVALID and "/paths/~1pets/get/tags" in finding.message


def test_1_1_a_primitive_target_needs_a_primitive_update() -> None:
    result = _apply([{"target": "$.info.title", "update": {"x": 1}}], "1.1.0")
    assert result.document["info"]["title"] == "Pets"
    assert result.findings[0].code == FINDING_ACTION_INVALID


def test_1_1_matches_must_all_be_the_same_kind() -> None:
    # summary and deprecated are primitives, tags is an array.
    result = _apply([{"target": "$.paths['/pets'].get.*", "update": "x"}], "1.1.0")
    assert result.findings[0].code == FINDING_ACTION_INVALID and "mix of" in result.findings[0].message
    assert result.document["paths"]["/pets"]["get"]["summary"] == "List pets"


def test_1_1_copy_merges_one_source_node() -> None:
    result = _apply(
        [{"target": "$.paths", "update": {"/new": {}}}, {"target": "$.paths['/new']", "copy": "$.paths['/old']"}],
        "1.1.0",
    )
    assert result.document["paths"]["/new"] == {"get": {"summary": "Old"}}


def test_1_1_copy_needs_exactly_one_source() -> None:
    result = _apply([{"target": "$.info", "copy": "$.paths.*"}], "1.1.0")
    assert "selected 2 nodes" in result.findings[0].message


def test_1_1_remove_wins_over_copy_and_copy_over_update() -> None:
    result = _apply(
        [
            {"target": "$.paths['/old']", "remove": True, "copy": "$.info"},
            {"target": "$.info", "copy": "$.paths['/pets'].get", "update": {"title": "ignored"}},
        ],
        "1.1.0",
    )
    assert "/old" not in result.document["paths"]
    assert result.document["info"]["summary"] == "List pets" and result.document["info"]["title"] == "Pets"


def test_an_unparsable_copy_source_is_a_target_expression_finding() -> None:
    result = _apply([{"target": "$.info", "copy": "$.[bad"}], "1.1.0")
    assert result.findings[0].code == FINDING_TARGET_EXPRESSION_INVALID


# ===========================================================================
# 1.2 semantics
# ===========================================================================


def _components(**actions: Any) -> Dict[str, Any]:
    return {"components": {"actions": actions}}


def test_1_2_reusable_actions_expand_with_the_references_target() -> None:
    result = _apply(
        [
            {"$ref": "#/components/actions/tag", "target": "$.paths['/pets'].get"},
            {"$ref": "#/components/actions/drop", "target": "$.paths['/old']"},
        ],
        "1.2.0",
        **_components(tag={"fields": {"update": {"x-public": True}}}, drop={"fields": {"remove": True}}),
    )
    assert result.document["paths"]["/pets"]["get"]["x-public"] is True
    assert "/old" not in result.document["paths"] and not result.findings


@pytest.mark.parametrize(
    ("ref", "components"),
    [
        ("#/components/actions/missing", {}),
        ("#/elsewhere/x", {}),
        ("#/components/actions/bad", {"bad": {"fields": {"target": "$.info", "update": {}}}}),
    ],
)
def test_1_2_a_broken_reference_is_refused(ref, components) -> None:
    result = _apply([{"$ref": ref, "target": "$.info"}], "1.2.0", **_components(**components))
    assert FINDING_ACTION_INVALID in [f.code for f in result.findings]
    assert result.document["info"] == _base()["info"]


def test_1_2_update_and_copy_together_are_refused() -> None:
    result = _apply([{"target": "$.info", "update": {"a": 1}, "copy": "$.paths['/old']"}], "1.2.0")
    assert "both `update` and `copy`" in result.findings[0].message


def test_1_2_a_self_with_a_fragment_is_reported() -> None:
    result = _apply([{"target": "$.info", "update": {}}], "1.2.0", **{"$self": "https://x.example/o.yaml#frag"})
    assert result.findings[0].action_index == -1 and "fragment" in result.findings[0].message


def test_self_before_1_2_is_reported() -> None:
    result = _apply([{"target": "$.info", "update": {}}], "1.1.0", **{"$self": "https://x.example/o.yaml"})
    assert "1.2 added it" in result.findings[0].message


# ===========================================================================
# extends
# ===========================================================================


@pytest.mark.parametrize(
    ("overlay_label", "extends", "self_uri", "resolved"),
    [
        ("o.yaml", "./openapi.yaml", None, True),
        ("overlays/o.yaml", "../openapi.yaml", None, True),
        ("o.yaml", "./other.yaml", None, False),
        ("o.yaml", "https://specs.example.org/api.yaml", None, True),
        ("o.yaml", "https://elsewhere.example.org/api.yaml", None, False),
        ("o.yaml", "../api.yaml", "https://specs.example.org/overlays/o.yaml", True),
    ],
)
def test_extends_is_checked_against_the_base(overlay_label, extends, self_uri, resolved) -> None:
    base = {**_base(), "$self": "https://specs.example.org/api.yaml"}
    extra = {"extends": extends, **({"$self": self_uri} if self_uri else {})}
    overlay = _overlay([{"target": "$.info", "update": {"x": 1}}], "1.2.0", **extra)
    result = apply_overlays(base, [(overlay_label, overlay)], base_path="openapi.yaml")
    codes = [f.code for f in result.findings]
    assert (FINDING_EXTENDS_UNRESOLVED not in codes) is resolved
    assert result.document["info"]["x"] == 1  # applied either way: the tool chooses the target


def test_no_base_path_skips_the_extends_check() -> None:
    overlay = _overlay([{"target": "$.info", "update": {}}], "1.0.0", extends="./nope.yaml")
    assert not apply_overlays(_base(), [("o.yaml", overlay)]).findings


# ===========================================================================
# Golden provenance per revision
# ===========================================================================


@pytest.mark.parametrize("set_name", ["34-overlay-basic-set", "36-overlay-1-1-set", "37-overlay-1-2-set"])
def test_each_revision_applies_with_a_golden_provenance(set_name) -> None:
    [root] = [e for e in load_corpus(format="openapi", feature="overlay-base") if set_name in e.path]
    resolved = OpenApiImportSource().parse_fileset(build_fileset(root), source_label=root.path)
    report = resolved.overlay_report
    pinned = {k: report.get(k) for k in ("applied", "revisions", "provenance", "findings")}
    golden = _GOLDEN / f"{set_name}.json"
    if os.environ.get("APIOME_REGEN_OVERLAY_GOLDENS"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(pinned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert pinned == json.loads(golden.read_text(encoding="utf-8"))
    assert pinned["findings"] == []


# ===========================================================================
# The rule pack
# ===========================================================================


def test_the_five_rules_are_catalogued_under_the_overlay_pack() -> None:
    catalogued = {d.rule_id: d for d in builtin_rule_descriptors() if d.pack == "overlay"}
    assert (
        sorted(catalogued)
        == sorted(OVERLAY_RULES)
        == [
            "overlay.action-invalid",
            "overlay.extends-unresolved",
            "overlay.target-expression-invalid",
            "overlay.unmatched-target",
            "overlay.version-unsupported",
        ]
    )
    assert catalogued["overlay.version-unsupported"].default_severity == "error"
    assert not [d for d in builtin_rule_descriptors() if d.rule_id.startswith("intake.overlay")]


def test_findings_map_onto_their_rules_at_default_severity() -> None:
    result = _apply([{"target": "$.nope", "update": {}}, {"target": "$.[bad", "update": {}}], "1.1.0")
    findings = overlay_lint_findings(result.report())
    assert [(f.rule, f.severity) for f in findings] == [
        ("overlay.unmatched-target", "warning"),
        ("overlay.target-expression-invalid", "warning"),
    ]


# ===========================================================================
# Bare overlay lint
# ===========================================================================


def _status(report) -> Dict[str, Any]:
    return {r["rule_id"]: (r["status"], r["reason"]) for r in report.rules}


def test_a_clean_bare_overlay_passes_structure_and_skips_the_base_rules() -> None:
    report = lint_bare_overlay(
        _overlay([{"target": "$.paths.*.get", "update": {"x": 1}}], "1.1.0", extends="./openapi.yaml")
    )
    status = _status(report)
    assert not report.findings and report.revision == "1.1"
    for rule in BASE_DEPENDENT_RULES:
        assert status[rule] == ("skipped", "no-base")  # never "passed"
    assert status["overlay.action-invalid"] == ("passed", None)
    assert status["overlay.version-unsupported"] == ("passed", None)


def test_a_bare_overlay_reports_structure_and_expression_problems() -> None:
    report = lint_bare_overlay(
        _overlay([{"target": "$.info"}, {"target": "$.[bad", "update": {}}, {"target": "$.x", "copy": "$.y"}], "1.0.0")
    )
    status = _status(report)
    assert status["overlay.action-invalid"][0] == "failed"
    assert status["overlay.target-expression-invalid"][0] == "failed"
    assert status["overlay.unmatched-target"] == ("skipped", "no-base")


def test_a_bare_overlay_with_an_unsupported_version_fails_that_rule_only() -> None:
    report = lint_bare_overlay(_overlay([{"target": "$.info", "update": {}}], "1.3.0"))
    status = _status(report)
    assert status["overlay.version-unsupported"][0] == "failed"
    assert status["overlay.action-invalid"] == ("skipped", "version-unsupported")
    assert [(f.rule, f.severity) for f in overlay_lint_findings(report.as_dict())] == [
        ("overlay.version-unsupported", "error")
    ]


def test_the_route_lints_a_posted_overlay() -> None:
    client = TestClient(app)
    app.dependency_overrides[validate_session_credentials] = lambda: {"user_id": "u", "tenant_id": "t"}
    try:
        text = "overlay: 1.2.0\ninfo: {title: o, version: '1'}\nactions:\n  - target: $.info\n    update: {x: 1}\n"
        response = client.post("/v1/lint/overlay", json={"document": text, "filename": "public.yaml"})
        bad = client.post("/v1/lint/overlay", json={"document": "- a list"})
        broken = client.post("/v1/lint/overlay", json={"document": "{nope"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["version"], body["revision"], body["findings"]) == ("1.2.0", "1.2", [])
    statuses = {r["ruleId"]: (r["status"], r["reason"]) for r in body["rules"]}
    assert statuses["overlay.unmatched-target"] == ("skipped", "no-base")
    assert statuses["overlay.extends-unresolved"] == ("skipped", "no-base")
    assert bad.status_code == 422 and broken.status_code == 422


def test_the_route_needs_a_session() -> None:
    assert TestClient(app).post("/v1/lint/overlay", json={"document": "overlay: 1.0.0"}).status_code in (401, 403)
