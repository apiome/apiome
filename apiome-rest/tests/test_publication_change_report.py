"""Publication change report hook (CR-04, #2702)."""

from unittest.mock import patch

from app.database import Database
from app.publication_change_report import EMPTY_BASELINE_OPENAPI, generate_change_report_on_publish

_MIN_CM = {
    "schemaVersion": "1.0.0",
    "schemas": {"added": [], "removed": [], "modified": []},
    "properties": [],
    "references": [],
    "relationships": [],
    "documentation": [],
    "warnings": [],
    "skipped": [],
}


def test_get_prior_published_baseline_revision_id_orders_by_published_at():
    db = Database()
    with patch.object(
        Database,
        "collect_revision_ancestors",
        return_value={"aa", "bb", "cc"},
    ), patch.object(
        Database,
        "execute_query",
        return_value=[{"id": "bb"}],
    ) as eq:
        r = db.get_prior_published_baseline_revision_id("pid", "tid", "cc")
        assert r == "bb"
        q = eq.call_args[0][0]
        assert "ORDER BY v.published_at DESC" in q


def test_generate_change_report_on_publish_skips_when_unpublished():
    with patch("app.publication_change_report.db") as mdb:
        mdb.get_version_by_id.return_value = {"published": False}
        generate_change_report_on_publish(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )
        mdb.insert_change_report_if_absent.assert_not_called()


def test_generate_change_report_on_publish_initial_publication():
    ver = {
        "published": True,
        "version_id": "1.0.0",
        "published_at": None,
        "project_id": "pid",
    }
    cand = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }

    with patch("app.publication_change_report.db") as mdb, patch(
        "app.publication_change_report.openapi_for_revision", return_value=cand
    ), patch("app.publication_change_report.build_change_report", return_value=dict(_MIN_CM)) as mbc, patch(
        "app.publication_change_report.render_from_template_row",
        return_value=("h", "b", "f"),
    ), patch(
        "app.publication_change_report._resolve_template_row",
        return_value={
            "id": "00000000-0000-4000-a000-000000000001",
            "header_template": "x",
            "body_template": "y",
            "footnote_template": "z",
        },
    ):
        mdb.get_version_by_id.return_value = ver
        mdb.get_project_by_id.return_value = {"name": "My Project"}
        mdb.get_prior_published_baseline_revision_id.return_value = None

        generate_change_report_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )

        mbc.assert_called_once()
        assert mbc.call_args[0][0] == EMPTY_BASELINE_OPENAPI
        assert mbc.call_args[0][1] == cand
        mdb.insert_change_report_if_absent.assert_called_once()
        cm = mdb.insert_change_report_if_absent.call_args[1]["change_model_json"]
        assert cm.get("initialPublication") is True
        assert mdb.insert_change_report_if_absent.call_args[1]["baseline_revision_id"] is None


def test_generate_change_report_on_publish_with_baseline():
    ver = {"published": True, "version_id": "2.0.0", "published_at": None}
    base = {"published": True, "version_id": "1.0.0"}
    oa = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }

    def _gv(vid, _tid):
        if vid == "cand":
            return ver
        if vid == "base":
            return base
        return None

    with patch("app.publication_change_report.db") as mdb, patch(
        "app.publication_change_report.openapi_for_revision", return_value=oa
    ), patch("app.publication_change_report.build_change_report", return_value=dict(_MIN_CM)), patch(
        "app.publication_change_report.render_from_template_row",
        return_value=("h", "b", "f"),
    ), patch(
        "app.publication_change_report._resolve_template_row",
        return_value={
            "id": "00000000-0000-4000-a000-000000000001",
            "header_template": "x",
            "body_template": "y",
            "footnote_template": "z",
        },
    ):
        mdb.get_version_by_id.side_effect = _gv
        mdb.get_project_by_id.return_value = {"name": "P"}
        mdb.get_prior_published_baseline_revision_id.return_value = "base"

        generate_change_report_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="cand",
            actor_id="uid",
        )

        mdb.insert_change_report_if_absent.assert_called_once()
        assert mdb.insert_change_report_if_absent.call_args[1]["baseline_revision_id"] == "base"
        cm = mdb.insert_change_report_if_absent.call_args[1]["change_model_json"]
        assert "initialPublication" not in cm


def test_generate_change_report_on_publish_failure_audits():
    with patch("app.publication_change_report.db") as mdb, patch(
        "app.publication_change_report._generate_change_report_on_publish_impl",
        side_effect=RuntimeError("boom"),
    ):
        mdb.get_version_by_id.return_value = {"published": True}
        generate_change_report_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )
        mdb.insert_workflow_audit.assert_called_once()
        assert mdb.insert_workflow_audit.call_args[0][4] == "failure"


def test_generate_change_report_on_publish_missing_baseline_row():
    """baseline_revision_id is non-null but the DB row is gone → distinct label + audit flags."""
    ver = {"published": True, "version_id": "2.0.0", "published_at": None}
    cand = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }

    def _gv(vid, _tid):
        if vid == "cand":
            return ver
        return None  # baseline row missing

    with patch("app.publication_change_report.db") as mdb, patch(
        "app.publication_change_report.openapi_for_revision", return_value=cand
    ), patch(
        "app.publication_change_report.build_change_report", return_value=dict(_MIN_CM)
    ), patch(
        "app.publication_change_report.render_from_template_row",
        return_value=("h", "b", "f"),
    ), patch(
        "app.publication_change_report._resolve_template_row",
        return_value={
            "id": "00000000-0000-4000-a000-000000000001",
            "header_template": "x",
            "body_template": "y",
            "footnote_template": "z",
        },
    ):
        mdb.get_version_by_id.side_effect = _gv
        mdb.get_project_by_id.return_value = {"name": "P"}
        mdb.get_prior_published_baseline_revision_id.return_value = "ghost-base"

        generate_change_report_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="cand",
            actor_id="uid",
        )

        # stored_baseline_id should be None (row was missing)
        call_kwargs = mdb.insert_change_report_if_absent.call_args[1]
        assert call_kwargs["baseline_revision_id"] is None

        # change model should NOT be marked as initial publication
        cm = call_kwargs["change_model_json"]
        assert "initialPublication" not in cm

        # audit should record the requested baseline id and flag the missing row
        audit_detail = mdb.insert_workflow_audit.call_args[0][6]
        assert audit_detail.get("requestedBaselineRevisionId") == "ghost-base"
        assert audit_detail.get("baselineLookupMissing") is True
        assert audit_detail.get("baselineRevisionId") is None
