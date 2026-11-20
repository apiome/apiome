"""Overlay manager in Versions — COA-2.7 (#7050).

* the overlay engine reports one outcome per action: kind, reusable-action name, how many nodes the
  target matched, how many values it changed, and whether it applied, matched nothing or was refused;
* the export report carries those rows (``report.actions``);
* :func:`app.version_overlay_diff.overlay_value_diff` turns the ledger into before / after rows with
  per-value provenance;
* ``POST …/overlays/preview`` renders the chain with an unsaved draft (appended, or standing in for a
  stored overlay) and writes nothing;
* ``POST …/overlays/apply`` imports the resolved document as a new version through the quality gate
  and the import pipeline, and refuses an empty chain, a chain that changes nothing and a taken label.

The acceptance scenario — an overlay with an ``update``, a ``remove`` and a ``copy`` action,
previewed, then applied — runs end to end over the fake store.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from app.export_overlay import ExportOverlay, apply_export_overlays
from app.openapi_overlay import ACTION_APPLIED, ACTION_INVALID, ACTION_UNMATCHED, apply_overlays
from app.version_overlay_diff import MISSING, overlay_value_diff, resolve_pointer
from tests.test_export_overlay import _BASE, _PARTNER, _openapi_source
from tests.test_version_overlay_routes import BASE, PROJECT, REVISION, USER, client, store, version  # noqa: F401

#: The acceptance overlay: one update, one remove, one copy (Overlay 1.1 added `copy`).
_MANAGER_OVERLAY: Dict[str, Any] = {
    "overlay": "1.1.0",
    "info": {"title": "Partner edition", "version": "1.0.0"},
    "actions": [
        {"target": "$.info", "update": {"title": "Widgets for Partners"}},
        {"target": "$.servers[0]", "remove": True},
        {"target": "$.paths['/widgets'].get", "copy": "$.info.description"},
    ],
}

#: Copy of the base with an object to copy from, so the `copy` action merges an object.
_BASE_WITH_EXTRA: Dict[str, Any] = {
    **_BASE,
    "x-defaults": {"x-owner": "partners"},
}


def _copy_overlay() -> Dict[str, Any]:
    """The acceptance overlay, with its copy reading an object (copy merges like an update)."""
    return {
        **_MANAGER_OVERLAY,
        "actions": [
            _MANAGER_OVERLAY["actions"][0],
            _MANAGER_OVERLAY["actions"][1],
            {"target": "$.paths['/widgets'].get", "copy": "$['x-defaults']"},
        ],
    }


# ---------------------------------------------------------------------------------------
# Engine: per-action outcomes
# ---------------------------------------------------------------------------------------


def test_every_action_reports_its_kind_matches_and_changes() -> None:
    application = apply_overlays(_BASE_WITH_EXTRA, [("partner", _copy_overlay())])
    outcomes = [o.as_dict() for o in application.actions]
    assert [o["kind"] for o in outcomes] == ["update", "remove", "copy"]
    assert [o["status"] for o in outcomes] == [ACTION_APPLIED] * 3
    assert [o["matches"] for o in outcomes] == [1, 1, 1]
    assert outcomes[0]["changes"] == 1  # info.title replaced
    assert outcomes[1]["changes"] == 1  # one server removed
    assert outcomes[2]["changes"] == 1  # x-owner set on the operation
    assert application.document["paths"]["/widgets"]["get"]["x-owner"] == "partners"
    assert application.document["servers"] == []


def test_a_wildcard_target_counts_every_match() -> None:
    doc = {**_BASE, "paths": {"/a": {"get": {"responses": {}}}, "/b": {"get": {"responses": {}}}}}
    overlay = {"overlay": "1.0.0", "info": {"title": "t", "version": "1"}, "actions": [
        {"target": "$.paths.*.get", "update": {"x-team": "core"}},
    ]}
    (outcome,) = apply_overlays(doc, [("o", overlay)]).actions
    assert outcome.matches == 2 and outcome.changes == 2 and outcome.status == ACTION_APPLIED


def test_unmatched_and_invalid_actions_are_reported_not_dropped() -> None:
    overlay = {"overlay": "1.0.0", "info": {"title": "t", "version": "1"}, "actions": [
        {"target": "$.paths['/gadgets']", "update": {"summary": "x"}},
        {"target": "$.info"},  # neither update nor remove
        {"target": "$.info", "copy": "$.servers"},  # copy is 1.1+
    ]}
    outcomes = apply_overlays(_BASE, [("o", overlay)]).actions
    assert [o.status for o in outcomes] == [ACTION_UNMATCHED, ACTION_INVALID, ACTION_INVALID]
    assert [o.matches for o in outcomes] == [0, 0, 0]
    assert outcomes[1].kind == "unknown"
    assert outcomes[2].kind == "copy"


def test_a_copy_that_selects_several_nodes_is_invalid_but_counts_its_targets() -> None:
    overlay = {**_MANAGER_OVERLAY, "actions": [{"target": "$.info", "copy": "$.paths.*"}]}
    doc = {**_BASE, "paths": {"/a": {}, "/b": {}}}
    (outcome,) = apply_overlays(doc, [("o", overlay)]).actions
    assert outcome.status == ACTION_INVALID and outcome.matches == 1 and outcome.changes == 0


def test_a_reusable_action_reports_its_component_name() -> None:
    overlay = {
        "overlay": "1.2.0",
        "info": {"title": "t", "version": "1"},
        "components": {"actions": {"tag-partner": {"fields": {"update": {"x-partner": True}}}}},
        "actions": [{"$ref": "#/components/actions/tag-partner", "target": "$.paths['/widgets'].get"}],
    }
    (outcome,) = apply_overlays(_BASE, [("o", overlay)]).actions
    assert outcome.ref == "tag-partner"
    assert outcome.kind == "update" and outcome.matches == 1 and outcome.status == ACTION_APPLIED


def test_outcomes_stay_out_of_the_fingerprinted_report() -> None:
    application = apply_overlays(_BASE, [("o", _PARTNER)])
    assert "actions" not in application.report()


def test_the_export_report_carries_the_action_rows() -> None:
    _, report = apply_export_overlays(_openapi_source(), [ExportOverlay(name="partner", document=_PARTNER)])
    assert report is not None
    assert [(a.kind, a.matches, a.status) for a in report.actions] == [("update", 1, "applied")] * 2


# ---------------------------------------------------------------------------------------
# Before / after rows
# ---------------------------------------------------------------------------------------


def test_resolve_pointer_handles_escapes_arrays_and_misses() -> None:
    doc = {"paths": {"/a/b": {"get": 1}}, "list": [10, 20], "t~x": 3}
    assert resolve_pointer(doc, "") is doc
    assert resolve_pointer(doc, "/paths/~1a~1b/get") == 1
    assert resolve_pointer(doc, "/list/1") == 20
    assert resolve_pointer(doc, "/t~0x") == 3
    assert resolve_pointer(doc, "/list/9") is MISSING
    assert resolve_pointer(doc, "/list/x") is MISSING
    assert resolve_pointer(doc, "/paths/~1a~1b/get/deeper") is MISSING
    assert resolve_pointer(doc, "no-slash") is MISSING


def test_diff_rows_show_before_after_and_who_changed_each_value() -> None:
    source = _openapi_source(_BASE_WITH_EXTRA)
    _, report = apply_export_overlays(source, [ExportOverlay(name="stored:partner", document=_copy_overlay())])
    application = apply_overlays(_BASE_WITH_EXTRA, [("stored:partner", _copy_overlay())])
    rows = overlay_value_diff(_BASE_WITH_EXTRA, application.document, report.ledger)
    by_pointer = {row["pointer"]: row for row in rows}

    title = by_pointer["/info/title"]
    assert (title["before"], title["after"], title["kind"]) == ("Widgets", "Widgets for Partners", "replaced")
    assert title["changed_by"] == [
        {"overlay": "stored:partner", "action_index": 0, "target": "$.info", "kind": "replaced"}
    ]

    removed = by_pointer["/servers/0"]
    assert removed["before"] == {"url": "https://internal.example.com"}
    assert removed["after_present"] is False and removed["after"] is None

    added = by_pointer["/paths/~1widgets/get/x-owner"]
    assert added["before_present"] is False and added["after"] == "partners"
    assert added["changed_by"][0]["action_index"] == 2


def test_a_value_changed_twice_lists_both_writers_last_one_wins() -> None:
    second = {"overlay": "1.0.0", "info": {"title": "b", "version": "1"}, "actions": [
        {"target": "$.info", "update": {"title": "Final"}},
    ]}
    overlays = [ExportOverlay(name="a", document=_PARTNER), ExportOverlay(name="b", document=second)]
    resolved, report = apply_export_overlays(_openapi_source(), overlays)
    rows = overlay_value_diff(_BASE, resolved.api.raw, report.ledger)
    (title,) = [row for row in rows if row["pointer"] == "/info/title"]
    assert [w["overlay"] for w in title["changed_by"]] == ["a", "b"]
    assert title["after"] == "Final"


# ---------------------------------------------------------------------------------------
# POST …/overlays/preview
# ---------------------------------------------------------------------------------------


@pytest.fixture
def extra_source(monkeypatch):
    """Serve the base with an object to copy from."""
    monkeypatch.setattr("app.version_overlay_routes.load_export_source", lambda *a: _openapi_source(_BASE_WITH_EXTRA))


def test_preview_without_a_draft_matches_get(client, store, version) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    got = client.get(f"{BASE}/preview").json()
    posted = client.post(f"{BASE}/preview", json={}).json()
    assert posted == got
    assert [row["pointer"] for row in got["diff"]] == ["/info/title", "/paths/~1widgets/get/x-partner"]
    assert got["draft"] is None


def test_preview_appends_a_draft_and_writes_nothing(client, store, version, extra_source) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    writes = len(store.calls)
    reply = client.post(f"{BASE}/preview", json={"draft": {"name": "edition", "document": _copy_overlay()}})
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert len(store.calls) == writes
    assert data["draft"] == "draft:edition"
    assert data["report"]["applied"] == ["stored:partner", "draft:edition"]
    draft_rows = [a for a in data["report"]["actions"] if a["overlay"] == "draft:edition"]
    assert [(a["kind"], a["matches"], a["status"]) for a in draft_rows] == [
        ("update", 1, "applied"),
        ("remove", 1, "applied"),
        ("copy", 1, "applied"),
    ]
    assert data["document"]["servers"] == []


def test_preview_puts_a_draft_in_a_stored_overlays_place(client, store, version) -> None:  # noqa: F811
    first = client.post(BASE, json={"name": "partner", "document": _PARTNER}).json()
    client.post(BASE, json={"name": "later", "document": {**_PARTNER, "actions": [
        {"target": "$.info", "update": {"title": "Later"}},
    ]}})
    edited = {**_PARTNER, "actions": [{"target": "$.info", "update": {"summary": "Edited"}}]}
    data = client.post(
        f"{BASE}/preview",
        json={"draft": {"name": "partner v2", "document": edited}, "replace_overlay_id": first["id"]},
    ).json()
    assert data["report"]["applied"] == ["stored:partner v2", "stored:later"]
    assert data["draft"] == "stored:partner v2"
    assert data["document"]["info"]["summary"] == "Edited"
    assert data["document"]["info"]["title"] == "Later"
    assert "x-partner" not in data["document"]["paths"]["/widgets"]["get"]


def test_preview_refusals(client, store, version) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    missing = client.post(
        f"{BASE}/preview", json={"draft": {"name": "x", "document": _PARTNER}, "replace_overlay_id": "nope"}
    )
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "overlay-not-found"
    no_draft = client.post(f"{BASE}/preview", json={"replace_overlay_id": "nope"})
    assert no_draft.status_code == 422 and no_draft.json()["detail"]["code"] == "overlay-draft-missing"
    not_overlay = client.post(f"{BASE}/preview", json={"draft": {"name": "x", "document": {"openapi": "3.1.0"}}})
    assert not_overlay.status_code == 422


def test_preview_works_on_a_published_revision(client, store, version) -> None:  # noqa: F811
    version["published"] = True
    reply = client.post(f"{BASE}/preview", json={"draft": {"name": "x", "document": _PARTNER}})
    assert reply.status_code == 200


# ---------------------------------------------------------------------------------------
# POST …/overlays/apply
# ---------------------------------------------------------------------------------------


@pytest.fixture
def importer(monkeypatch) -> Dict[str, Any]:
    """Fake the quality gate, the import pipeline, labels and the audit log."""
    seen: Dict[str, Any] = {"labels": ["1.0.0"], "gate": [], "imports": [], "audit": []}

    async def _gate(**kwargs):
        seen["gate"].append(kwargs)

    async def _pipeline(adapter, payload):
        seen["imports"].append(payload)
        return SimpleNamespace(state="completed", result=SimpleNamespace(version_record_id="new-rev"), error=None)

    monkeypatch.setattr("app.spec_import_routes._enforce_quality_gate", _gate)
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _pipeline)
    monkeypatch.setattr(
        "app.openapi_version_import.db.get_versions_for_project",
        lambda p, t, *a, **k: [{"version_id": v} for v in seen["labels"]],
    )
    monkeypatch.setattr(
        "app.openapi_version_import.db.get_project_by_id",
        lambda p, t, **k: {"id": p, "name": "Widgets", "slug": "widgets"},
    )
    monkeypatch.setattr(
        "app.version_overlay_routes.db.get_version_source_projection",
        lambda rev, tenant: {"project_slug": "widgets", "format_metadata": {}},
    )
    monkeypatch.setattr(
        "app.version_overlay_routes.db.insert_workflow_audit", lambda *a: seen["audit"].append(a)
    )
    return seen


def test_acceptance_create_preview_apply(client, store, version, extra_source, importer) -> None:  # noqa: F811
    """COA-2.7 acceptance: an overlay with update, remove and copy — preview the diff, apply it."""
    draft = {"name": "Partner edition", "document": _copy_overlay()}
    preview = client.post(f"{BASE}/preview", json={"draft": draft}).json()
    kinds = {row["pointer"]: row["kind"] for row in preview["diff"]}
    assert kinds == {
        "/info/title": "replaced",
        "/servers/0": "removed",
        "/paths/~1widgets/get/x-owner": "set",
    }

    saved = client.post(BASE, json={**draft, "source": "manual"})
    assert saved.status_code == 201 and saved.json()["action_count"] == 3

    applied = client.post(f"{BASE}/apply", json={"version_label": "1.1.0"})
    assert applied.status_code == 201, applied.text
    assert applied.json() == {
        "project_id": PROJECT,
        "version_record_id": "new-rev",
        "version_label": "1.1.0",
        "source_version_record_id": REVISION,
        "overlay_count": 1,
        "change_count": 3,
    }
    (payload,) = importer["imports"]
    assert payload["metadata"]["existing_project_id"] == PROJECT
    assert payload["metadata"]["version"]["version_id"] == "1.1.0"
    assert "Partner edition" in payload["metadata"]["version"]["description"]
    assert payload["filename"] == "widgets-overlaid.json"
    assert importer["gate"][0]["metadata"].version.version_id == "1.1.0"
    (audit,) = importer["audit"]
    assert audit[3] == "version.overlays.applied" and audit[5] == USER
    assert audit[6]["changeCount"] == 3


def test_apply_mints_a_label_when_none_is_given(client, store, version, importer) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    reply = client.post(f"{BASE}/apply")
    assert reply.status_code == 201, reply.text
    assert reply.json()["version_label"] not in ("", "1.0.0")


def test_apply_works_from_a_published_revision(client, store, version, importer) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    version["published"] = True
    assert client.post(f"{BASE}/apply", json={}).status_code == 201


@pytest.mark.parametrize(
    "documents,label,code",
    [
        ([], None, "overlay-chain-empty"),
        ([{"overlay": "1.0.0", "info": {"title": "t", "version": "1"}, "actions": [
            {"target": "$.paths['/gadgets']", "update": {"x": 1}},
        ]}], None, "overlay-no-changes"),
        ([_PARTNER], "1.0.0", "version-exists"),
    ],
)
def test_apply_refusals(client, store, version, importer, documents: List[dict], label, code) -> None:  # noqa: F811
    for index, document in enumerate(documents):
        client.post(BASE, json={"name": f"o{index}", "document": document})
    reply = client.post(f"{BASE}/apply", json={"version_label": label} if label else {})
    assert reply.status_code == 409
    assert reply.json()["detail"]["code"] == code
    assert importer["imports"] == []


def test_apply_reports_a_failed_import(client, store, version, importer, monkeypatch) -> None:  # noqa: F811
    async def _failed(adapter, payload):
        return SimpleNamespace(state="failed", result=None, error=SimpleNamespace(message="bad document"))

    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _failed)
    client.post(BASE, json={"name": "partner", "document": _PARTNER})
    reply = client.post(f"{BASE}/apply", json={})
    assert reply.status_code == 422
    assert reply.json()["detail"]["code"] == "overlay-apply-import-failed"
    assert "bad document" in reply.json()["detail"]["message"]


def test_apply_needs_import_and_project_edit(client, store, version, importer, monkeypatch) -> None:  # noqa: F811
    client.post(BASE, json={"name": "partner", "document": _PARTNER})

    def _deny(_db, _auth, resource, action, **kwargs):
        if resource == "imports":
            raise HTTPException(status_code=403, detail="Forbidden")
        return USER

    monkeypatch.setattr("app.version_overlay_routes.enforce_permission", _deny)
    assert client.post(f"{BASE}/apply", json={}).status_code == 403
    assert importer["imports"] == []
