"""Unit tests for the maturity-ladder validator and default template — GVM-1.1 (#5854).

:mod:`app.style_guide_ladder` is pure, so these run without a database: the shape rules, the
registry and axis checks (each refusal carries a JSON Pointer), the cumulative rule, the
canonical form and fingerprint, ``ladder_from_row``'s explicit no-ladder case, and the default
Bronze / Silver / Gold template.
"""

from types import SimpleNamespace

import pytest

from app.axis_score import AXIS_KEYS
from app.style_guide_ladder import (
    CODE_AXIS_THRESHOLD_MISSING,
    CODE_DUPLICATE_AXIS,
    CODE_DUPLICATE_LEVEL,
    CODE_DUPLICATE_RULE,
    CODE_EMPTY,
    CODE_INVALID,
    CODE_NOT_CUMULATIVE,
    CODE_UNKNOWN_AXIS,
    CODE_UNKNOWN_RULE,
    LadderValidationError,
    default_ladder_template,
    ladder_content_fingerprint,
    ladder_from_row,
    validate_ladder,
)

RULES = ("naming.schema-pascal-case", "documentation.operation-missing-summary", "security.no-auth")


def _validate(raw):
    return validate_ladder(raw, registered_rule_ids=RULES, axis_keys=AXIS_KEYS)


def _level(key, *, rules=(), axes=(), evidence=(), waivers=False):
    return {
        "key": key,
        "label": key.title(),
        "rules": [{"ruleId": r, "maxSeverity": s} for r, s in rules],
        "axes": list(axes),
        "evidence": list(evidence),
        "waiversSatisfy": waivers,
    }


def _refusal(raw) -> LadderValidationError:
    with pytest.raises(LadderValidationError) as info:
        _validate(raw)
    return info.value


# ---------------------------------------------------------------------------
# Accepted ladders
# ---------------------------------------------------------------------------


def test_a_cumulative_ladder_is_normalized_and_keeps_level_order():
    ladder = _validate(
        {
            "name": "  Maturity ",
            "levels": [
                _level("bronze", rules=[("security.no-auth", "warning"), ("naming.schema-pascal-case", "error")]),
                _level(
                    "silver",
                    rules=[("security.no-auth", "info")],
                    axes=[{"axis": "quality", "minGrade": "B", "minScore": 80.0}],
                    evidence=["review_approved", "review_approved"],
                ),
            ],
        }
    )
    assert ladder["name"] == "Maturity"
    assert [lv["key"] for lv in ladder["levels"]] == ["bronze", "silver"]
    # Rules sorted by id, scores integral, evidence de-duplicated.
    assert [r["ruleId"] for r in ladder["levels"][0]["rules"]] == [
        "naming.schema-pascal-case",
        "security.no-auth",
    ]
    assert ladder["levels"][1]["axes"] == [{"axis": "quality", "minGrade": "B", "minScore": 80}]
    assert ladder["levels"][1]["evidence"] == ["review_approved"]


def test_a_level_may_restate_or_tighten_a_lower_requirement():
    ladder = _validate(
        {
            "name": "L",
            "levels": [
                _level("bronze", rules=[("security.no-auth", "warning")], axes=[{"axis": "quality", "minScore": 70}]),
                _level("silver", rules=[("security.no-auth", "warning")], axes=[{"axis": "quality", "minScore": 70}]),
                _level("gold", rules=[("security.no-auth", "none")], axes=[{"axis": "quality", "minScore": 90}]),
            ],
        }
    )
    assert len(ladder["levels"]) == 3


def test_omitting_a_lower_requirement_inherits_it_rather_than_relaxing_it():
    ladder = _validate(
        {
            "name": "L",
            "levels": [
                _level("bronze", rules=[("security.no-auth", "info")]),
                _level("silver", axes=[{"axis": "security", "minGrade": "A"}]),
            ],
        }
    )
    assert ladder["levels"][1]["rules"] == []


def test_snake_case_fields_are_accepted():
    ladder = _validate(
        {
            "name": "L",
            "levels": [
                {
                    "key": "bronze",
                    "label": "Bronze",
                    "rules": [{"rule_id": "security.no-auth", "max_severity": "warning"}],
                    "axes": [{"axis": "quality", "min_grade": "C"}],
                    "waivers_satisfy": True,
                }
            ],
        }
    )
    level = ladder["levels"][0]
    assert level["rules"] == [{"ruleId": "security.no-auth", "maxSeverity": "warning"}]
    assert level["axes"] == [{"axis": "quality", "minGrade": "C"}]
    assert level["waiversSatisfy"] is True


def test_a_missing_label_falls_back_to_the_key():
    ladder = _validate({"name": "L", "levels": [{"key": "bronze"}]})
    assert ladder["levels"][0]["label"] == "bronze"


# ---------------------------------------------------------------------------
# The cumulative rule
# ---------------------------------------------------------------------------


def test_a_relaxed_rule_severity_is_refused_naming_the_level_and_rule():
    err = _refusal(
        {
            "name": "L",
            "levels": [
                _level("bronze", rules=[("security.no-auth", "warning")]),
                _level("silver", rules=[("security.no-auth", "error")]),
            ],
        }
    )
    assert err.code == CODE_NOT_CUMULATIVE
    assert err.level == "silver"
    assert err.rule == "security.no-auth"
    assert err.pointer == "/levels/1/rules/0/maxSeverity"
    assert "bronze" in err.message and "silver" in err.message


def test_relaxing_against_any_lower_level_is_refused_not_only_the_previous_one():
    err = _refusal(
        {
            "name": "L",
            "levels": [
                _level("bronze", rules=[("security.no-auth", "info")]),
                _level("silver"),
                _level("gold", rules=[("security.no-auth", "warning")]),
            ],
        }
    )
    assert (err.code, err.level, err.rule) == (CODE_NOT_CUMULATIVE, "gold", "security.no-auth")


def test_a_worse_min_grade_is_refused():
    err = _refusal(
        {
            "name": "L",
            "levels": [
                _level("bronze", axes=[{"axis": "quality", "minGrade": "B"}]),
                _level("silver", axes=[{"axis": "quality", "minGrade": "C"}]),
            ],
        }
    )
    assert (err.code, err.level, err.rule) == (CODE_NOT_CUMULATIVE, "silver", "quality")
    assert err.pointer == "/levels/1/axes/0/minGrade"


def test_a_lower_min_score_is_refused():
    err = _refusal(
        {
            "name": "L",
            "levels": [
                _level("bronze", axes=[{"axis": "quality", "minScore": 80}]),
                _level("silver", axes=[{"axis": "quality", "minScore": 79.5}]),
            ],
        }
    )
    assert (err.code, err.level, err.rule) == (CODE_NOT_CUMULATIVE, "silver", "quality")
    assert err.pointer == "/levels/1/axes/0/minScore"


def test_turning_waivers_back_on_is_refused():
    err = _refusal(
        {
            "name": "L",
            "levels": [_level("bronze", waivers=True), _level("silver"), _level("gold", waivers=True)],
        }
    )
    assert (err.code, err.level, err.rule) == (CODE_NOT_CUMULATIVE, "gold", "waiversSatisfy")


def test_turning_waivers_off_at_a_higher_level_is_a_tightening():
    ladder = _validate({"name": "L", "levels": [_level("bronze", waivers=True), _level("silver")]})
    assert [lv["waiversSatisfy"] for lv in ladder["levels"]] == [True, False]


# ---------------------------------------------------------------------------
# Registry, vocabulary and shape refusals
# ---------------------------------------------------------------------------


def test_an_unknown_rule_id_is_refused_with_a_pointer():
    err = _refusal({"name": "L", "levels": [_level("bronze"), _level("silver", rules=[("made.up", "none")])]})
    assert (err.code, err.pointer, err.level, err.rule) == (
        CODE_UNKNOWN_RULE,
        "/levels/1/rules/0/ruleId",
        "silver",
        "made.up",
    )


def test_an_unknown_axis_is_refused_with_a_pointer():
    err = _refusal({"name": "L", "levels": [_level("bronze", axes=[{"axis": "vibes", "minGrade": "A"}])]})
    assert (err.code, err.pointer, err.rule) == (CODE_UNKNOWN_AXIS, "/levels/0/axes/0/axis", "vibes")


def test_an_axis_without_a_threshold_is_refused():
    err = _refusal({"name": "L", "levels": [_level("bronze", axes=[{"axis": "quality"}])]})
    assert (err.code, err.pointer) == (CODE_AXIS_THRESHOLD_MISSING, "/levels/0/axes/0")


@pytest.mark.parametrize(
    "raw, code, pointer",
    [
        ({"name": "L", "levels": []}, CODE_EMPTY, "/levels"),
        ({"name": "", "levels": [{"key": "b"}]}, CODE_INVALID, "/name"),
        ({"name": "L", "levels": "bronze"}, CODE_INVALID, "/levels"),
        ({"name": "L", "levels": ["bronze"]}, CODE_INVALID, "/levels/0"),
        ({"name": "L", "levels": [{"label": "No key"}]}, CODE_INVALID, "/levels/0/key"),
        ({"name": "L", "levels": [{"key": "b"}, {"key": "b"}]}, CODE_DUPLICATE_LEVEL, "/levels/1/key"),
        (
            {"name": "L", "levels": [_level("b", rules=[("security.no-auth", "info"), ("security.no-auth", "none")])]},
            CODE_DUPLICATE_RULE,
            "/levels/0/rules/1/ruleId",
        ),
        (
            {"name": "L", "levels": [_level("b", axes=[{"axis": "quality", "minGrade": "A"}] * 2)]},
            CODE_DUPLICATE_AXIS,
            "/levels/0/axes/1/axis",
        ),
        (
            {"name": "L", "levels": [_level("b", rules=[("security.no-auth", "fatal")])]},
            CODE_INVALID,
            "/levels/0/rules/0/maxSeverity",
        ),
        (
            {"name": "L", "levels": [_level("b", axes=[{"axis": "quality", "minGrade": "E"}])]},
            CODE_INVALID,
            "/levels/0/axes/0/minGrade",
        ),
        (
            {"name": "L", "levels": [_level("b", axes=[{"axis": "quality", "minScore": 101}])]},
            CODE_INVALID,
            "/levels/0/axes/0/minScore",
        ),
        (
            {"name": "L", "levels": [_level("b", evidence=["signed_off"])]},
            CODE_INVALID,
            "/levels/0/evidence/0",
        ),
        (
            {"name": "L", "levels": [{"key": "b", "waiversSatisfy": "yes"}]},
            CODE_INVALID,
            "/levels/0/waiversSatisfy",
        ),
    ],
)
def test_malformed_ladders_are_refused_with_a_code_and_pointer(raw, code, pointer):
    err = _refusal(raw)
    assert (err.code, err.pointer) == (code, pointer)


def test_as_detail_carries_code_message_pointer_level_and_rule():
    err = LadderValidationError(CODE_NOT_CUMULATIVE, "msg", "/levels/1", "silver", "r")
    assert err.as_detail() == {
        "code": CODE_NOT_CUMULATIVE,
        "message": "msg",
        "pointer": "/levels/1",
        "level": "silver",
        "rule": "r",
    }
    assert LadderValidationError(CODE_EMPTY, "m", "/levels").as_detail() == {
        "code": CODE_EMPTY,
        "message": "m",
        "pointer": "/levels",
    }


# ---------------------------------------------------------------------------
# Fingerprint and row projection
# ---------------------------------------------------------------------------


def test_equal_ladders_fingerprint_equally_regardless_of_rule_order():
    pairs = [("security.no-auth", "info"), ("naming.schema-pascal-case", "none")]
    a = _validate({"name": "L", "levels": [_level("b", rules=pairs)]})
    b = _validate({"name": "L", "levels": [_level("b", rules=list(reversed(pairs)))]})
    assert ladder_content_fingerprint(a) == ladder_content_fingerprint(b)


def test_the_fingerprint_moves_when_a_level_changes():
    a = _validate({"name": "L", "levels": [_level("b", rules=[("security.no-auth", "info")])]})
    b = _validate({"name": "L", "levels": [_level("b", rules=[("security.no-auth", "none")])]})
    assert ladder_content_fingerprint(a) != ladder_content_fingerprint(b)


def test_ladder_from_row_is_explicit_about_no_ladder():
    assert ladder_from_row(None) is None
    assert ladder_from_row({"name": "L", "levels": []}) is None
    assert ladder_from_row({"name": "L", "levels": "x"}) is None
    assert ladder_from_row({"name": "L", "levels": [{"key": "b"}], "id": "x"}) == {
        "name": "L",
        "levels": [{"key": "b"}],
    }


# ---------------------------------------------------------------------------
# Default template
# ---------------------------------------------------------------------------


def _descriptors():
    return [
        SimpleNamespace(rule_id="documentation.a", category="documentation"),
        SimpleNamespace(rule_id="naming.b", category="naming"),
        SimpleNamespace(rule_id="security.c", category="security"),
    ]


def test_the_default_template_is_bronze_silver_gold():
    ladder = default_ladder_template(_descriptors())
    bronze, silver, gold = ladder["levels"]
    assert [lv["key"] for lv in ladder["levels"]] == ["bronze", "silver", "gold"]
    # Bronze: no errors except documentation.
    assert bronze["rules"] == [
        {"ruleId": "naming.b", "maxSeverity": "warning"},
        {"ruleId": "security.c", "maxSeverity": "warning"},
    ]
    # Silver: quality >= B and no errors at all.
    assert silver["rules"] == [{"ruleId": "documentation.a", "maxSeverity": "warning"}]
    assert silver["axes"] == [{"axis": "quality", "minGrade": "B"}]
    # Gold: quality >= A, security assessed and clean, review approved.
    assert gold["rules"] == [{"ruleId": "security.c", "maxSeverity": "none"}]
    assert gold["axes"] == [
        {"axis": "quality", "minGrade": "A"},
        {"axis": "security", "minGrade": "A"},
    ]
    assert gold["evidence"] == ["review_approved"]


def test_the_default_template_validates_against_the_real_registry():
    ladder = default_ladder_template()
    assert len(ladder["levels"]) == 3
    assert all(lv["rules"] for lv in ladder["levels"])


# ---------------------------------------------------------------------------
# waiversSatisfy default (GVM-1.2, #5855)
# ---------------------------------------------------------------------------


def test_waivers_satisfy_defaults_to_true_except_on_the_top_level():
    ladder = _validate({"name": "L", "levels": [{"key": "bronze"}, {"key": "silver"}, {"key": "gold"}]})
    assert [lv["waiversSatisfy"] for lv in ladder["levels"]] == [True, True, False]


def test_a_single_level_ladder_defaults_waivers_off():
    ladder = _validate({"name": "L", "levels": [{"key": "bronze"}]})
    assert ladder["levels"][0]["waiversSatisfy"] is False


def test_an_explicit_waivers_satisfy_wins_over_the_default():
    ladder = _validate(
        {"name": "L", "levels": [{"key": "bronze", "waiversSatisfy": False}, {"key": "gold", "waiversSatisfy": False}]}
    )
    assert [lv["waiversSatisfy"] for lv in ladder["levels"]] == [False, False]


def test_the_default_template_takes_the_top_level_waiver_default():
    levels = default_ladder_template(_descriptors())["levels"]
    assert [lv["waiversSatisfy"] for lv in levels] == [True, True, False]
