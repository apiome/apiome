"""Publication version changelog hook (CTG-3.1, #4475)."""

from unittest.mock import MagicMock, patch

from app.changelog_generator import Changelog
from app.publication_changelog import (
    backfill_latest_version_changelogs,
    generate_version_changelog_on_publish,
    initial_publication_changelog_json,
)


def test_initial_publication_changelog_json_marker():
    payload = initial_publication_changelog_json(to_version="1.0.0")
    assert payload["initialPublication"] is True
    assert payload["toVersion"] == "1.0.0"
    assert payload["fromVersion"] is None
    assert payload["entries"] == []
    assert payload["maxSeverity"] is None


def test_generate_version_changelog_skips_when_unpublished():
    with patch("app.publication_changelog.db") as mdb:
        mdb.get_version_by_id.return_value = {"published": False}
        generate_version_changelog_on_publish(
            tenant_slug="t",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )
        mdb.upsert_version_changelog.assert_not_called()


def test_generate_version_changelog_initial_publication():
    ver = {"published": True, "version_id": "1.0.0", "project_id": "pid"}

    with patch("app.publication_changelog.db") as mdb:
        mdb.get_version_by_id.return_value = ver
        mdb.get_prior_published_baseline_revision_id.return_value = None

        generate_version_changelog_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )

        mdb.upsert_version_changelog.assert_called_once()
        kwargs = mdb.upsert_version_changelog.call_args[1]
        assert kwargs["status"] == "initial"
        assert kwargs["baseline_revision_id"] is None
        assert kwargs["changelog_json"]["initialPublication"] is True
        assert kwargs["changelog_json"]["toVersion"] == "1.0.0"
        assert kwargs["max_severity"] is None

        mdb.insert_workflow_audit.assert_called_once()
        assert mdb.insert_workflow_audit.call_args[0][3] == "version.changelog.classified"
        assert mdb.insert_workflow_audit.call_args[0][4] == "success"
        detail = mdb.insert_workflow_audit.call_args[0][6]
        assert detail["status"] == "initial"
        assert detail["initialPublication"] is True


def test_generate_version_changelog_with_baseline():
    ver = {"published": True, "version_id": "2.0.0"}
    base = {"published": True, "version_id": "1.0.0"}
    oa = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }
    classified = MagicMock()
    changelog = Changelog(
        entries=[],
        counts={
            "breaking": 0,
            "non-breaking": 0,
            "docs-only": 0,
            "unclassified": 0,
            "total": 0,
        },
        max_severity=None,
        from_version="1.0.0",
        to_version="2.0.0",
    )

    def _gv(vid, _tid):
        if vid == "cand":
            return ver
        if vid == "base":
            return base
        return None

    with patch("app.publication_changelog.db") as mdb, patch(
        "app.publication_changelog.openapi_for_revision", return_value=oa
    ), patch(
        "app.publication_changelog.classify_openapi_changes", return_value=classified
    ) as mcls, patch(
        "app.publication_changelog.build_changelog", return_value=changelog
    ) as mbc, patch(
        "app.publication_changelog.render_changelog_json",
        return_value={"schemaVersion": "ctg.changelog.v1", "entries": []},
    ) as mren:
        mdb.get_version_by_id.side_effect = _gv
        mdb.get_prior_published_baseline_revision_id.return_value = "base"

        generate_version_changelog_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="cand",
            actor_id="uid",
        )

        mcls.assert_called_once()
        mbc.assert_called_once()
        assert mbc.call_args[1]["from_version"] == "1.0.0"
        assert mbc.call_args[1]["to_version"] == "2.0.0"
        mren.assert_called_once_with(changelog)

        kwargs = mdb.upsert_version_changelog.call_args[1]
        assert kwargs["status"] == "ready"
        assert kwargs["baseline_revision_id"] == "base"
        assert kwargs["changelog_json"]["schemaVersion"] == "ctg.changelog.v1"
        assert mdb.insert_workflow_audit.call_args[0][4] == "success"
        detail = mdb.insert_workflow_audit.call_args[0][6]
        assert detail["status"] == "ready"
        assert detail["baselineRevisionId"] == "base"


def test_generate_version_changelog_failure_upserts_failed_and_audits():
    with patch("app.publication_changelog.db") as mdb, patch(
        "app.publication_changelog._generate_version_changelog_on_publish_impl",
        side_effect=RuntimeError("boom"),
    ):
        generate_version_changelog_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )

        mdb.upsert_version_changelog.assert_called_once()
        kwargs = mdb.upsert_version_changelog.call_args[1]
        assert kwargs["status"] == "failed"
        assert kwargs["error"] == "boom"
        assert kwargs["changelog_json"] is None

        mdb.insert_workflow_audit.assert_called_once()
        assert mdb.insert_workflow_audit.call_args[0][3] == "version.changelog.classified"
        assert mdb.insert_workflow_audit.call_args[0][4] == "failure"


def test_generate_version_changelog_failure_does_not_raise():
    with patch("app.publication_changelog.db") as mdb, patch(
        "app.publication_changelog._generate_version_changelog_on_publish_impl",
        side_effect=RuntimeError("boom"),
    ):
        mdb.upsert_version_changelog.side_effect = RuntimeError("db down")
        mdb.insert_workflow_audit.side_effect = RuntimeError("audit down")
        # Must not raise even when failure bookkeeping fails
        generate_version_changelog_on_publish(
            tenant_slug="ten",
            tenant_id="tid",
            project_id="pid",
            published_revision_id="vid",
            actor_id="uid",
        )


def test_backfill_latest_version_changelogs_counts_statuses():
    candidates = [
        {
            "tenant_id": "t1",
            "tenant_slug": "ten",
            "project_id": "p1",
            "published_revision_id": "r1",
        },
        {
            "tenant_id": "t1",
            "tenant_slug": "ten",
            "project_id": "p2",
            "published_revision_id": "r2",
        },
        {
            "tenant_id": "t1",
            "tenant_slug": "ten",
            "project_id": "p3",
            "published_revision_id": "r3",
        },
    ]

    def _get_changelog(revision_id, _tid, _pid):
        return {
            "r1": {"status": "ready"},
            "r2": {"status": "initial"},
            "r3": {"status": "failed", "error": "nope"},
        }[revision_id]

    with patch("app.publication_changelog.db") as mdb, patch(
        "app.publication_changelog.generate_version_changelog_on_publish"
    ) as gen:
        mdb.list_projects_needing_changelog_backfill.return_value = candidates
        mdb.get_version_changelog.side_effect = _get_changelog

        summary = backfill_latest_version_changelogs(limit=10)

        assert summary["processed"] == 3
        assert summary["ready"] == 1
        assert summary["initial"] == 1
        assert summary["failed"] == 1
        assert len(summary["failures"]) == 1
        assert summary["failures"][0]["revisionId"] == "r3"
        assert gen.call_count == 3
        mdb.list_projects_needing_changelog_backfill.assert_called_once_with(limit=10)
