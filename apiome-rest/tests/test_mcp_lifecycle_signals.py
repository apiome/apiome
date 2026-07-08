"""Tests for deprecation & lifecycle signal detection (V2-MCP-34.4 / MCAT-20.4, #4658).

The acceptance criteria drive the layout:

* **Signals detected from fixtures** — deprecated/experimental/beta markers planted in a
  capability's annotations, name/title, or description each produce a signal, and the
  aggregate report flags the right capabilities.
* **No signal is not a "stable" claim** — an unmarked capability rolls up to stage
  ``unspecified`` (never ``stable``), and the aggregate "none detected" wording carries an
  explicit disclaimer; ``stable`` is reported only for an explicit annotation declaration.
* **Pure / unit-tested** — determinism (same input → same signals, order, and ids),
  boundary behaviour (no partial-word / substring matches), and the itemization bounds.
"""

import pytest

from app.mcp_lifecycle_signals import (
    KIND_ANNOTATION_FLAG,
    KIND_ANNOTATION_STATUS,
    KIND_NAME_TOKEN,
    MAX_FLAGGED_CAPABILITIES,
    MAX_SCANNED_CHARS,
    MAX_SIGNALS_PER_CAPABILITY,
    SOURCE_ANNOTATIONS,
    SOURCE_DESCRIPTION,
    SOURCE_NAME,
    SOURCE_TITLE,
    STAGE_BETA,
    STAGE_DEPRECATED,
    STAGE_EXPERIMENTAL,
    STAGE_STABLE,
    STAGE_UNSPECIFIED,
    STATUS_DETECTED,
    STATUS_NONE_DETECTED,
    assess_capability_lifecycle,
    detect_lifecycle_signals,
)


def _tool(**overrides):
    """One fixture capability-item dict in the ``mcp_capability_items`` row shape."""
    item = {
        "item_type": "tool",
        "name": "search",
        "title": None,
        "description": None,
        "annotations": None,
    }
    item.update(overrides)
    return item


def _kinds(assessment):
    return [s.kind for s in assessment.signals]


def _matches(assessment):
    return [s.matched for s in assessment.signals]


# --- Signals detected from fixtures (AC 1) ------------------------------------------------------


def test_deprecated_annotation_flag_is_detected():
    a = assess_capability_lifecycle(
        item_type="tool", name="old_search", annotations={"deprecated": True}
    )
    assert a.stage == STAGE_DEPRECATED
    assert _kinds(a) == [KIND_ANNOTATION_FLAG]
    assert a.signals[0].source == SOURCE_ANNOTATIONS
    assert a.signals[0].matched == "deprecated=true"


@pytest.mark.parametrize(
    "value,stage",
    [
        ("deprecated", STAGE_DEPRECATED),
        ("legacy", STAGE_DEPRECATED),
        ("experimental", STAGE_EXPERIMENTAL),
        ("alpha", STAGE_EXPERIMENTAL),
        ("preview", STAGE_EXPERIMENTAL),
        ("beta", STAGE_BETA),
    ],
)
def test_annotation_status_values_map_to_stages(value, stage):
    a = assess_capability_lifecycle(
        item_type="tool", name="search", annotations={"stability": value}
    )
    assert a.stage == stage
    assert _kinds(a) == [KIND_ANNOTATION_STATUS]
    assert a.signals[0].matched == f"stability={value}"


@pytest.mark.parametrize(
    "name,stage,token",
    [
        ("search_beta", STAGE_BETA, "beta"),
        ("searchBeta", STAGE_BETA, "beta"),
        ("v2beta", STAGE_BETA, "beta"),
        ("legacy-export", STAGE_DEPRECATED, "legacy"),
        ("deprecated_fetch", STAGE_DEPRECATED, "deprecated"),
        ("alpha_report", STAGE_EXPERIMENTAL, "alpha"),
        ("experimental.query", STAGE_EXPERIMENTAL, "experimental"),
    ],
)
def test_name_tokens_are_detected(name, stage, token):
    a = assess_capability_lifecycle(item_type="tool", name=name)
    assert a.stage == stage
    assert _kinds(a) == [KIND_NAME_TOKEN]
    assert a.signals[0].matched == token
    assert a.signals[0].source == SOURCE_NAME


def test_title_tokens_are_detected():
    a = assess_capability_lifecycle(item_type="tool", name="search", title="Search (beta)")
    assert a.stage == STAGE_BETA
    assert a.signals[0].source == SOURCE_TITLE
    assert a.signals[0].excerpt == "Search (beta)"


@pytest.mark.parametrize(
    "text,stage,phrase",
    [
        ("This tool is deprecated.", STAGE_DEPRECATED, "deprecated"),
        ("Will be removed in v3.", STAGE_DEPRECATED, "will be removed"),
        ("Superseded by search_v2.", STAGE_DEPRECATED, "superseded by"),
        ("No longer supported here.", STAGE_DEPRECATED, "no longer supported"),
        ("An experimental endpoint.", STAGE_EXPERIMENTAL, "experimental"),
        ("Currently in preview for select tenants.", STAGE_EXPERIMENTAL, "in preview"),
        ("Early access feature.", STAGE_EXPERIMENTAL, "early access"),
        ("Search the index (beta).", STAGE_BETA, "(beta)"),
        ("This feature is in beta.", STAGE_BETA, "in beta"),
        ("Public beta of the reranker.", STAGE_BETA, "public beta"),
    ],
)
def test_description_phrases_are_detected(text, stage, phrase):
    a = assess_capability_lifecycle(item_type="tool", name="search", description=text)
    assert a.stage == stage
    assert phrase in _matches(a)
    assert all(s.source == SOURCE_DESCRIPTION for s in a.signals)


def test_description_signals_carry_context_excerpts():
    text = "x" * 200 + " this tool is deprecated " + "y" * 200
    a = assess_capability_lifecycle(item_type="tool", name="t", description=text)
    signal = a.signals[0]
    assert "deprecated" in signal.excerpt
    assert signal.excerpt.startswith("…") and signal.excerpt.endswith("…")
    assert len(signal.excerpt) < 200


def test_aggregate_report_flags_the_right_capabilities():
    report = detect_lifecycle_signals(
        [
            _tool(name="old_search", annotations={"deprecated": True}),
            _tool(name="search_beta"),
            _tool(name="plain", description="Searches the index."),
            _tool(name="lab", description="Experimental — work in progress."),
        ]
    )
    assert report.status == STATUS_DETECTED
    assert report.capabilities_scanned == 4
    assert [c.name for c in report.flagged] == ["old_search", "search_beta", "lab"]
    assert report.stage_counts == {
        STAGE_DEPRECATED: 1,
        STAGE_EXPERIMENTAL: 1,
        STAGE_BETA: 1,
        STAGE_STABLE: 0,
    }
    assert "3 of 4" in report.statement


def test_most_urgent_stage_wins_the_roll_up():
    a = assess_capability_lifecycle(
        item_type="tool",
        name="search_beta",
        description="Deprecated — this beta feature will be removed.",
    )
    # Both beta and deprecated signals exist; deprecated is the badge.
    assert a.stage == STAGE_DEPRECATED
    stages = {s.stage for s in a.signals}
    assert STAGE_BETA in stages and STAGE_DEPRECATED in stages


# --- No signal is not a "stable" claim (AC 3) ----------------------------------------------------


def test_unmarked_capability_is_unspecified_never_stable():
    a = assess_capability_lifecycle(
        item_type="tool", name="search", description="Searches the product index."
    )
    assert a.stage == STAGE_UNSPECIFIED
    assert a.signals == ()


def test_stable_is_reported_only_when_explicitly_declared():
    declared = assess_capability_lifecycle(
        item_type="tool", name="search", annotations={"stability": "stable"}
    )
    assert declared.stage == STAGE_STABLE
    silent = assess_capability_lifecycle(item_type="tool", name="search")
    assert silent.stage == STAGE_UNSPECIFIED


def test_none_detected_statement_disclaims_stability():
    report = detect_lifecycle_signals([_tool(), _tool(name="fetch")])
    assert report.status == STATUS_NONE_DETECTED
    lowered = report.statement.lower()
    assert "no lifecycle signals detected" in lowered
    assert "not a claim that these capabilities are stable" in lowered


def test_empty_surface_reads_as_nothing_to_scan():
    report = detect_lifecycle_signals([])
    assert report.status == STATUS_NONE_DETECTED
    assert report.capabilities_scanned == 0
    assert "no capabilities to scan" in report.statement.lower()
    assert "not a claim" in report.statement.lower()


# --- Purity & determinism -------------------------------------------------------------------------


def test_detection_is_deterministic_with_stable_ids():
    items = [
        _tool(name="old_search", annotations={"deprecated": True}),
        _tool(name="lab_beta", description="In beta — experimental parts remain."),
    ]
    first = detect_lifecycle_signals(items)
    second = detect_lifecycle_signals(items)
    assert first == second
    first_ids = [s.id for c in first.flagged for s in c.signals]
    second_ids = [s.id for c in second.flagged for s in c.signals]
    assert first_ids == second_ids
    assert all(i.startswith("mcp-lifecycle-") for i in first_ids)


def test_signal_ids_are_scoped_to_the_capability():
    a = assess_capability_lifecycle(item_type="tool", name="a_beta")
    b = assess_capability_lifecycle(item_type="tool", name="b_beta")
    assert a.signals[0].id != b.signals[0].id


def test_sources_are_scanned_in_fixed_order():
    a = assess_capability_lifecycle(
        item_type="tool",
        name="legacy_search",
        title="Legacy search (beta)",
        description="This tool is deprecated.",
        annotations={"deprecated": True},
    )
    sources = [s.source for s in a.signals]
    order = (SOURCE_ANNOTATIONS, SOURCE_NAME, SOURCE_TITLE, SOURCE_DESCRIPTION)
    assert sources == sorted(sources, key=order.index)


# --- Boundary behaviour (no substring / false-positive matches) ----------------------------------


@pytest.mark.parametrize(
    "name",
    ["alphabet_lookup", "betamax_catalog", "stable_diffusion", "collaborate"],
)
def test_name_substrings_never_match(name):
    a = assess_capability_lifecycle(item_type="tool", name=name)
    assert a.stage == STAGE_UNSPECIFIED


def test_verb_like_words_are_not_lifecycle_signals():
    # "preview"/"sunset"/"beta" describe what these tools *do*, not their lifecycle.
    for description in (
        "Previews a document before printing.",
        "Computes the sunset time for a location.",
        "Samples from a beta distribution.",
        "Renders the alpha channel of an image.",
    ):
        a = assess_capability_lifecycle(item_type="tool", name="t", description=description)
        assert a.stage == STAGE_UNSPECIFIED, description


def test_annotation_flags_require_strict_true():
    for value in ("true", 1, "yes", {}, [True]):
        a = assess_capability_lifecycle(
            item_type="tool", name="t", annotations={"deprecated": value}
        )
        assert a.stage == STAGE_UNSPECIFIED, repr(value)


def test_unknown_annotation_status_values_are_not_signals():
    a = assess_capability_lifecycle(
        item_type="tool", name="t", annotations={"status": "active"}
    )
    assert a.stage == STAGE_UNSPECIFIED


def test_annotation_keys_match_case_insensitively():
    a = assess_capability_lifecycle(
        item_type="tool", name="t", annotations={"Deprecated": True, "Stability": "beta"}
    )
    assert a.stage == STAGE_DEPRECATED
    assert {s.kind for s in a.signals} == {KIND_ANNOTATION_FLAG, KIND_ANNOTATION_STATUS}


def test_longer_phrase_claims_span_over_shorter_overlap():
    a = assess_capability_lifecycle(
        item_type="tool", name="t", description="This is no longer supported."
    )
    deprecated = [s for s in a.signals if s.stage == STAGE_DEPRECATED]
    assert [s.matched for s in deprecated] == ["no longer supported"]


# --- Bounds --------------------------------------------------------------------------------------


def test_per_capability_signal_cap_reports_truncation():
    # Enough distinct markers across sources to exceed the itemization cap.
    description = (
        "Deprecated. Will be removed. Superseded by v2. No longer supported. "
        "Obsolete. Do not use. Experimental. Unstable. In beta. (alpha) Early access."
    )
    a = assess_capability_lifecycle(
        item_type="tool",
        name="legacy_beta_alpha_deprecated_experimental",
        title="Deprecated legacy beta (alpha) experimental",
        description=description,
        annotations={"deprecated": True, "stability": "deprecated"},
    )
    assert len(a.signals) == MAX_SIGNALS_PER_CAPABILITY
    assert a.signals_truncated > 0
    # Truncation never changes the badge — the roll-up covers all hits.
    assert a.stage == STAGE_DEPRECATED


def test_flagged_capability_cap_reports_truncation():
    items = [_tool(name=f"tool_{i}_beta") for i in range(MAX_FLAGGED_CAPABILITIES + 5)]
    report = detect_lifecycle_signals(items)
    assert len(report.flagged) == MAX_FLAGGED_CAPABILITIES
    assert report.flagged_truncated == 5
    # Stage counts still cover every capability, not just the itemized ones.
    assert report.stage_counts[STAGE_BETA] == MAX_FLAGGED_CAPABILITIES + 5


def test_oversized_descriptions_are_bounded_not_rejected():
    text = ("z" * MAX_SCANNED_CHARS) + " this tool is deprecated"
    a = assess_capability_lifecycle(item_type="tool", name="t", description=text)
    # The marker sits beyond the scan bound: not found, still a clean "unspecified".
    assert a.stage == STAGE_UNSPECIFIED
    in_bounds = assess_capability_lifecycle(
        item_type="tool", name="t", description="deprecated " + "z" * MAX_SCANNED_CHARS
    )
    assert in_bounds.stage == STAGE_DEPRECATED


# --- Serialization -------------------------------------------------------------------------------


def test_capability_as_dict_is_json_ready_and_stable():
    a = assess_capability_lifecycle(item_type="tool", name="search_beta")
    payload = a.as_dict()
    assert payload["stage"] == STAGE_BETA
    assert payload["signals_truncated"] == 0
    assert all(
        set(signal) == {"id", "stage", "kind", "source", "matched", "excerpt"}
        for signal in payload["signals"]
    )
    assert payload == assess_capability_lifecycle(item_type="tool", name="search_beta").as_dict()


def test_report_as_dict_is_json_ready():
    report = detect_lifecycle_signals([_tool(name="old", annotations={"deprecated": True})])
    payload = report.as_dict()
    assert payload["status"] == STATUS_DETECTED
    assert payload["capabilities_scanned"] == 1
    assert payload["flagged_truncated"] == 0
    assert payload["stage_counts"][STAGE_DEPRECATED] == 1
    assert payload["flagged"][0]["name"] == "old"
    assert payload["flagged"][0]["stage"] == STAGE_DEPRECATED
