"""Policy packs freeze the guide's maturity ladder — GVM-1.1 (#5854).

:func:`app.lint_policy_service.snapshot_style_guide_policy` reads the live ladder beside the
rules and gates, passes it to the insert, and folds it into the pack fingerprint; a guide with
no ladder stores ``ladder=None`` and keeps the fingerprint it had before ladders existed.
"""

from unittest.mock import MagicMock, patch

from app.database import Database
from app.lint_policy_service import snapshot_style_guide_policy
from app.models import style_guide_policy_version_out_from_row
from app.policy_evaluate import policy_content_fingerprint

TENANT = "00000000-0000-4000-8000-0000000000a1"
GUIDE = "00000000-0000-4000-8000-0000000000c1"

LEVELS = [
    {
        "key": "bronze",
        "label": "Bronze",
        "rules": [{"ruleId": "naming.schema-pascal-case", "maxSeverity": "warning"}],
        "axes": [{"axis": "quality", "minGrade": "C"}],
        "evidence": [],
        "waiversSatisfy": True,
    }
]


def _snapshot(ladder_row):
    guide = {"id": GUIDE, "axis_gates": None, "required_coverage": None, "ci_outcomes": None}
    with patch("app.lint_policy_service.db.get_style_guide_by_id", return_value=guide), patch(
        "app.lint_policy_service.db.get_style_guide_rules", return_value=[]
    ), patch(
        "app.lint_policy_service.db.get_style_guide_ladder", return_value=ladder_row
    ), patch(
        "app.lint_policy_service.db.insert_style_guide_policy_version",
        return_value={"id": "pv"},
    ) as insert:
        snapshot_style_guide_policy(GUIDE, TENANT)
    return insert.call_args.kwargs


def test_a_pack_freezes_the_ladder_and_its_fingerprint_moves():
    without = _snapshot(None)
    with_ladder = _snapshot({"name": "Maturity", "levels": LEVELS, "id": "x"})

    assert without["ladder"] is None
    assert with_ladder["ladder"] == {"name": "Maturity", "levels": LEVELS}
    assert with_ladder["content_fingerprint"] != without["content_fingerprint"]


def test_a_pack_without_a_ladder_keeps_its_pre_ladder_fingerprint():
    kwargs = _snapshot(None)
    assert kwargs["content_fingerprint"] == policy_content_fingerprint(
        rules_snapshot=[],
        axis_gates={},
        required_coverage=["quality"],
        ci_outcomes=kwargs["ci_outcomes"],
    )


def test_insert_policy_version_stores_the_ladder_as_jsonb_or_null():
    db = Database.__new__(Database)
    db.execute_query = MagicMock(return_value=[{"id": "pv"}])
    common = dict(
        guide_id=GUIDE,
        tenant_id=TENANT,
        rules_snapshot=[],
        axis_gates={},
        required_coverage=["quality"],
        ci_outcomes={},
        content_fingerprint="f",
    )
    ladder = {"name": "Maturity", "levels": LEVELS}
    db.insert_style_guide_policy_version(**common, ladder=ladder)
    query, params = db.execute_query.call_args.args
    assert "ladder" in query
    assert params[8].adapted == ladder

    db.insert_style_guide_policy_version(**common)
    assert db.execute_query.call_args.args[1][8] is None


def test_the_policy_version_projection_exposes_the_frozen_ladder():
    row = {
        "id": "pv",
        "guide_id": GUIDE,
        "version_number": 3,
        "content_fingerprint": "f",
        "ladder": {"name": "Maturity", "levels": LEVELS},
    }
    out = style_guide_policy_version_out_from_row(row).model_dump(by_alias=True)
    assert out["ladder"]["name"] == "Maturity"
    assert out["ladder"]["levels"][0]["rules"] == [
        {"ruleId": "naming.schema-pascal-case", "maxSeverity": "warning"}
    ]
    assert out["ladder"]["levels"][0]["waiversSatisfy"] is True

    no_ladder = style_guide_policy_version_out_from_row({**row, "ladder": None})
    assert no_ladder.model_dump(by_alias=True)["ladder"] is None
