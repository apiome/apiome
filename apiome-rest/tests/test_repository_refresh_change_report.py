"""Per-refresh change report via the publication pipeline (RAR-4.3, #3529)."""

from unittest.mock import patch

from app.repository_refresh_change_report import (
    REFRESH_CHANGE_REPORT_ACTION,
    generate_change_report_on_refresh,
)

_EMPTY_CM = {
    "schemaVersion": "1.0",
    "schemas": {"added": [], "removed": [], "modified": []},
    "properties": [],
    "references": [],
    "relationships": [],
    "documentation": [],
    "warnings": [],
    "skipped": [],
}


def _render(change_model, *, baseline_id, baseline_missing=False, from_label="1.0.0"):
    """Shape the 8-tuple build_publication_change_report_render returns."""
    return (
        change_model,
        "header",
        "body",
        "footnote",
        baseline_id,
        None,
        baseline_missing,
        from_label,
    )


def _patches(change_model, *, baseline_id="parent-v", baseline_missing=False):
    return (
        patch("app.repository_refresh_change_report.db"),
        patch(
            "app.repository_refresh_change_report.build_publication_change_report_render",
            return_value=_render(
                change_model, baseline_id=baseline_id, baseline_missing=baseline_missing
            ),
        ),
        patch(
            "app.repository_refresh_change_report._resolve_template_row",
            return_value={"id": "00000000-0000-4000-a000-000000000001"},
        ),
    )


def test_skips_when_version_missing():
    with patch("app.repository_refresh_change_report.db") as mdb:
        mdb.get_version_by_id.return_value = None
        out = generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="parent-v",
            actor_id="uid",
        )
    assert out is None
    mdb.insert_change_report_if_absent.assert_not_called()


def test_skips_when_version_in_other_project():
    with patch("app.repository_refresh_change_report.db") as mdb:
        mdb.get_version_by_id.return_value = {"project_id": "other"}
        out = generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="parent-v",
            actor_id="uid",
        )
    assert out is None
    mdb.insert_change_report_if_absent.assert_not_called()


def test_changed_refresh_persists_report_and_audits_not_noop():
    cm = dict(_EMPTY_CM)
    cm["schemas"] = {"added": [{"name": "New"}], "removed": [], "modified": []}
    p_db, p_render, p_tpl = _patches(cm)
    with p_db as mdb, p_render, p_tpl:
        mdb.get_version_by_id.return_value = {"project_id": "pid", "version_id": "2.0.0"}
        mdb.insert_change_report_if_absent.return_value = {"id": "cr-1"}
        out = generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="parent-v",
            actor_id="uid",
        )

    assert out == {"id": "cr-1"}
    # report keyed to the refresh version, baseline = the parent version
    insert_kwargs = mdb.insert_change_report_if_absent.call_args
    assert insert_kwargs.args[2] == "vid"
    assert insert_kwargs.kwargs["baseline_revision_id"] == "parent-v"
    assert insert_kwargs.kwargs["change_model_json"]["noChanges"] is False

    audit = mdb.insert_workflow_audit.call_args.args
    assert audit[3] == REFRESH_CHANGE_REPORT_ACTION
    assert audit[4] == "success"
    detail = audit[6]
    assert detail["noChanges"] is False
    assert detail["totalChanges"] == 1
    assert detail["changeCounts"]["schemasAdded"] == 1
    assert detail["initialRefresh"] is False


def test_zero_change_refresh_reported_as_noop():
    p_db, p_render, p_tpl = _patches(dict(_EMPTY_CM))
    with p_db as mdb, p_render, p_tpl:
        mdb.get_version_by_id.return_value = {"project_id": "pid", "version_id": "2.0.0"}
        mdb.insert_change_report_if_absent.return_value = {"id": "cr-2"}
        generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="parent-v",
            actor_id="uid",
        )

    # Report still written so the version always links to a report...
    mdb.insert_change_report_if_absent.assert_called_once()
    stored_model = mdb.insert_change_report_if_absent.call_args.kwargs["change_model_json"]
    assert stored_model["noChanges"] is True
    # ...and the audit flags the no-op.
    detail = mdb.insert_workflow_audit.call_args.args[6]
    assert detail["noChanges"] is True
    assert detail["totalChanges"] == 0


def test_initial_refresh_without_parent_uses_empty_baseline():
    p_db, p_render, p_tpl = _patches(dict(_EMPTY_CM), baseline_id=None)
    with p_db as mdb, p_render, p_tpl:
        mdb.get_version_by_id.return_value = {"project_id": "pid", "version_id": "1.0.0"}
        mdb.insert_change_report_if_absent.return_value = {"id": "cr-3"}
        generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="   ",  # blank normalizes to None
            actor_id=None,
        )

    detail = mdb.insert_workflow_audit.call_args.args[6]
    assert detail["initialRefresh"] is True
    assert detail["parentVersionId"] is None
    assert mdb.insert_change_report_if_absent.call_args.kwargs["baseline_revision_id"] is None


def test_failure_is_swallowed_and_audited():
    with patch("app.repository_refresh_change_report.db") as mdb, patch(
        "app.repository_refresh_change_report.build_publication_change_report_render",
        side_effect=RuntimeError("boom"),
    ):
        mdb.get_version_by_id.return_value = {"project_id": "pid", "version_id": "2.0.0"}
        out = generate_change_report_on_refresh(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            refresh_version_id="vid",
            parent_version_id="parent-v",
            actor_id="uid",
        )

    assert out is None
    mdb.insert_change_report_if_absent.assert_not_called()
    audit = mdb.insert_workflow_audit.call_args.args
    assert audit[3] == REFRESH_CHANGE_REPORT_ACTION
    assert audit[4] == "failure"
    assert audit[6]["phase"] == "unexpected"
