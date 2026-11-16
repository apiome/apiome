"""Compatibility modes on the REST surface — XPC-4.5 (#5749).

The classified diff, the compatibility check and the publish guardrail grade by the project's
compatibility policy (or the request's ``mode`` / ``transitive`` / ``category``) and say so in
``evaluatedUnder``; the style-guide policy endpoints read and write the three V382 settings.

The Avro lineage used throughout::

    v1  {id, email: string}             (email has no default)
    v2  {id, email: string = ""}        (email gains a default)
    v3  {id}                            (email removed) — the head

``v2 → v3`` passes FULL (the removed field had a default), but ``v1 → v3`` fails FORWARD: an old
v1 reader cannot fill ``email`` from v3 data. So a FULL_TRANSITIVE check fails where FULL passes,
and names v1 as the offending revision.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.avro_import_source import AvroImportSource
from app.breaking_publish_guardrail import STATUS_BLOCKED, STATUS_OK, assess_breaking_publish
from app.canonical_model import CanonicalApi
from app.main import app

client = TestClient(app)

_UUID = {
    "v1": "11111111-1111-4111-8111-111111111111",
    "v2": "22222222-2222-4222-8222-222222222222",
    "v3": "33333333-3333-4333-8333-333333333333",
}
_PROJECT = {"id": "proj-1", "slug": "orders-events", "tenant_id": "tenant-1", "metadata": "{}"}
_AVRO = AvroImportSource()
_USER = {"type": "record", "name": "User", "namespace": "com.example", "fields": [{"name": "id", "type": "long"}]}


def _schema(*fields: Dict[str, Any]) -> str:
    return json.dumps({**_USER, "fields": _USER["fields"] + list(fields)})


_SCHEMAS = {
    "v1": _schema({"name": "email", "type": "string"}),
    "v2": _schema({"name": "email", "type": "string", "default": ""}),
    "v3": _schema(),
}
_LABELS = {"v1": "1.0.0", "v2": "2.0.0", "v3": "2.1.0"}


def _model(text: str) -> CanonicalApi:
    return _AVRO.normalize(_AVRO.parse(text, source_label="schema.avsc"))


_MODELS = {_UUID[k]: _model(v) for k, v in _SCHEMAS.items()}


def _models_for(*present: str):
    """A ``canonical_model_for_revision`` stand-in that knows the named revisions."""
    known = {_UUID[k]: _MODELS[_UUID[k]] for k in present}

    def load(_db: Any, _tenant_id: str, revision_id: str) -> Optional[CanonicalApi]:
        return known.get(str(revision_id))

    return load


def _row(key: str) -> Dict[str, Any]:
    return {"id": _UUID[key], "project_id": "proj-1", "version_id": _LABELS[key], "published": True}


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _db(policy: Optional[Dict[str, Any]] = None, prior: Optional[list] = None) -> MagicMock:
    """A db double: the project, the three revisions, a guide policy and a lineage."""
    db = MagicMock()
    db.user_has_permission.return_value = True
    db.get_project_by_slug.return_value = _PROJECT
    db.get_project_by_id.return_value = _PROJECT
    by_label = {_LABELS[k]: _row(k) for k in _LABELS}
    by_id = {_UUID[k]: _row(k) for k in _LABELS}
    db.get_version_by_version_id.side_effect = lambda pid, ver, tid: by_label.get(ver)
    db.get_version_by_id.side_effect = lambda vid, tid: by_id.get(str(vid))
    db.get_assigned_style_guide.return_value = policy
    db.list_prior_revisions_for_transitive_check.return_value = prior or []
    db.get_revision_source_row.return_value = {"source_format": "avro"}
    return db


_V1_ROW = [{"id": _UUID["v1"], "version_id": "1.0.0"}]


# ===========================================================================
# POST /v1/diff/{tenant}/classified
# ===========================================================================


def _classified(db: MagicMock, body: Dict[str, Any], *, present=("v1", "v2", "v3")):
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.canonical_model_for_revision", _models_for(*present)
    ):
        return client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders-events", "version": "1.0.0"},
                "head": {"project": "orders-events", "version": "2.0.0"},
                **body,
            },
        )


def test_the_same_avro_pair_differs_under_backward_and_forward(authed: None) -> None:
    """Acceptance: one Avro pair, two verdicts, and the response names the mode.

    v1 → v3 removes a field that had no default: dangerous under BACKWARD (new readers ignore it),
    breaking under FORWARD (old readers cannot fill it).
    """
    db = _db()
    body = {"head": {"project": "orders-events", "version": "2.1.0"}}
    backward = _classified(db, {**body, "mode": "BACKWARD"}).json()
    forward = _classified(db, {**body, "mode": "forward"}).json()
    assert backward["maxSeverity"] == "non-breaking"
    assert forward["maxSeverity"] == "breaking"
    assert backward["evaluatedUnder"]["mode"] == "BACKWARD"
    assert forward["evaluatedUnder"]["mode"] == "FORWARD"
    assert forward["evaluatedUnder"]["modeApplied"] is True
    assert forward["evaluatedUnder"]["formats"] == ["avro"]
    assert forward["evaluatedUnder"]["ruleset"] == "avro-compatibility"
    assert forward["evaluatedUnder"]["source"]["mode"] == "request"
    (email,) = [c for c in forward["changes"] if c["pointer"] == "/field/com.example.User.email"]
    assert email["ruleId"] == "avro-compatibility.reader-field-missing-default-value"
    assert (email["severity"], email["grade"]) == ("breaking", "breaking")
    assert email["rationale"].startswith("[FORWARD]")
    (bw_email,) = [c for c in backward["changes"] if c["pointer"] == "/field/com.example.User.email"]
    assert bw_email["grade"] == "dangerous"


def test_the_mode_defaults_to_the_projects_policy(authed: None) -> None:
    db = _db(policy={"compatibility_mode": "FORWARD"})
    data = _classified(db, {"head": {"project": "orders-events", "version": "2.1.0"}}).json()
    assert data["evaluatedUnder"]["mode"] == "FORWARD"
    assert data["evaluatedUnder"]["source"]["mode"] == "policy"
    assert data["maxSeverity"] == "breaking"


def test_full_transitive_catches_a_break_against_an_older_revision(authed: None) -> None:
    db = _db(prior=_V1_ROW)
    base = {
        "base": {"project": "orders-events", "version": "2.0.0"},
        "head": {"project": "orders-events", "version": "2.1.0"},
    }
    plain = _classified(db, {**base, "mode": "FULL"}).json()
    assert plain["maxSeverity"] == "non-breaking"
    assert "against" not in plain["changes"][0]

    transitive = _classified(db, {**base, "mode": "FULL_TRANSITIVE"}).json()
    assert transitive["maxSeverity"] == "breaking"
    under = transitive["evaluatedUnder"]
    assert (under["mode"], under["transitive"]) == ("FULL", True)
    assert [(r["versionLabel"], r["role"]) for r in under["comparedRevisions"]] == [
        ("2.0.0", "base"),
        ("1.0.0", "prior"),
    ]
    breaking = [c for c in transitive["changes"] if c["severity"] == "breaking"]
    assert breaking and all(c["against"]["versionLabel"] == "1.0.0" for c in breaking)
    db.list_prior_revisions_for_transitive_check.assert_called()


def test_the_markdown_changelog_says_what_it_was_graded_under(authed: None) -> None:
    db = _db(prior=_V1_ROW)
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.canonical_model_for_revision", _models_for("v1", "v2", "v3")
    ):
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders-events", "version": "2.0.0"},
                "head": {"project": "orders-events", "version": "2.1.0"},
                "mode": "FULL_TRANSITIVE",
            },
            headers={"Accept": "text/markdown"},
        )
    assert r.status_code == 200, r.text
    assert "_Graded under `FULL_TRANSITIVE` by avro-compatibility, against 2.0.0, 1.0.0._" in r.text
    assert "avro-compatibility.reader-field-missing-default-value" in r.text


def test_an_unknown_mode_is_a_400(authed: None) -> None:
    r = _classified(_db(), {"mode": "SIDEWAYS"})
    assert r.status_code == 400
    assert "SIDEWAYS" in r.json()["detail"] or "SIDEWAYS" in r.text


def test_an_inline_avro_head_is_read_with_the_base_format(authed: None) -> None:
    db = _db()
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.canonical_model_for_revision", _models_for("v1")
    ):
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders-events", "version": "1.0.0"},
                "head": {"inline": _SCHEMAS["v3"]},
                "mode": "FORWARD",
            },
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["head"]["source"] == "inline"
    assert data["maxSeverity"] == "breaking"
    assert data["evaluatedUnder"]["modeApplied"] is True


def test_an_unreadable_inline_head_is_a_400(authed: None) -> None:
    with patch("app.classified_diff_routes.db", _db()), patch(
        "app.classified_diff_routes.canonical_model_for_revision", _models_for("v1")
    ):
        r = client.post(
            "/v1/diff/acme/classified",
            json={"base": {"project": "orders-events", "version": "1.0.0"}, "head": {"inline": "{not avro"}},
        )
    assert r.status_code == 400


_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}},
}


def test_an_openapi_pair_reports_the_mode_was_not_applied(authed: None) -> None:
    db = _db()
    db.get_revision_source_row.return_value = {"source_format": None}
    head = copy.deepcopy(_SPEC)
    head["paths"] = {}
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.canonical_model_for_revision", lambda *_a: None
    ), patch("app.classified_diff_routes.openapi_for_revision", side_effect=[_SPEC, head]):
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders-events", "version": "1.0.0"},
                "head": {"project": "orders-events", "version": "2.0.0"},
                "mode": "FORWARD",
            },
        )
    assert r.status_code == 200, r.text
    data = r.json()
    under = data["evaluatedUnder"]
    assert (under["mode"], under["modeApplied"], under["ruleset"], under["formats"]) == (
        "FORWARD",
        False,
        "ctg",
        ["openapi"],
    )
    assert data["maxSeverity"] == "breaking"
    assert all(c["ruleId"].startswith("ctg.") for c in data["changes"])
    assert all("grade" not in c for c in data["changes"])


def test_an_openapi_transitive_diff_compares_earlier_revisions_too(authed: None) -> None:
    db = _db(prior=_V1_ROW)
    db.get_revision_source_row.return_value = {"source_format": None}
    older = copy.deepcopy(_SPEC)
    older["paths"]["/owners"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.canonical_model_for_revision", lambda *_a: None
    ), patch("app.classified_diff_routes.openapi_for_revision", side_effect=[_SPEC, _SPEC, older]):
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "orders-events", "version": "2.0.0"},
                "head": {"project": "orders-events", "version": "2.1.0"},
                "transitive": True,
            },
        )
    data = r.json()
    assert data["maxSeverity"] == "breaking"
    (removed,) = [c for c in data["changes"] if c["severity"] == "breaking"]
    assert removed["against"] == {"revisionId": _UUID["v1"], "versionLabel": "1.0.0"}
    assert data["evaluatedUnder"]["source"]["transitive"] == "request"


# ===========================================================================
# POST /v1/versions/{tenant}/{project}/compatibility
# ===========================================================================


def _compat(db: MagicMock, body: Dict[str, Any], *, present=("v1", "v2", "v3")):
    with patch("app.compatibility_routes.db", db), patch(
        "app.compatibility_routes.canonical_model_for_revision", _models_for(*present)
    ), patch("app.compatibility_routes.enforce_permission"):
        return client.post("/v1/versions/acme/proj-1/compatibility", json=body)


def test_compatibility_check_grades_by_mode(authed: None) -> None:
    pair = {"baseRevisionId": _UUID["v1"], "headRevisionId": _UUID["v3"]}
    backward = _compat(_db(), {**pair, "mode": "BACKWARD"})
    forward = _compat(_db(), {**pair, "mode": "FORWARD"})
    assert backward.status_code == 200, backward.text
    assert backward.json()["overall"] == "unknown"
    assert forward.json()["overall"] == "breaking"
    under = forward.json()["evaluatedUnder"]
    assert (under["mode"], under["modeApplied"], under["ruleset"]) == ("FORWARD", True, "avro-compatibility")
    finding = next(f for f in forward.json()["findings"] if f["category"] == "breaking")
    assert finding["ruleId"] == finding["rule"] == "avro-compatibility.reader-field-missing-default-value"
    assert finding["severity"] == "breaking"


def test_compatibility_check_transitive_names_the_offending_revision(authed: None) -> None:
    pair = {"baseRevisionId": _UUID["v2"], "headRevisionId": _UUID["v3"]}
    plain = _compat(_db(prior=_V1_ROW), {**pair, "mode": "FULL"}).json()
    assert plain["overall"] == "safe"
    transitive = _compat(_db(prior=_V1_ROW), {**pair, "mode": "FULL", "transitive": True}).json()
    assert transitive["overall"] == "breaking"
    offending = [f for f in transitive["findings"] if f["category"] == "breaking"]
    assert offending and offending[0]["against"] == {"revisionId": _UUID["v1"], "versionLabel": "1.0.0"}
    assert transitive["evaluatedUnder"]["transitive"] is True
    assert transitive["reportFingerprint"] != plain["reportFingerprint"]


def test_compatibility_check_409s_on_a_break_the_mode_finds(authed: None) -> None:
    pair = {"baseRevisionId": _UUID["v1"], "headRevisionId": _UUID["v3"]}
    r = _compat(_db(), {**pair, "mode": "FORWARD", "policy": {"http409WhenBreaking": True}})
    assert r.status_code == 409
    assert r.json()["detail"]["report"]["evaluatedUnder"]["mode"] == "FORWARD"


def test_compatibility_check_rejects_an_unknown_category(authed: None) -> None:
    pair = {"baseRevisionId": _UUID["v1"], "headRevisionId": _UUID["v3"]}
    assert _compat(_db(), {**pair, "category": "BYTES"}).status_code == 400


def test_compatibility_check_on_openapi_names_the_native_engine(authed: None) -> None:
    db = _db()
    db.get_revision_source_row.return_value = {"source_format": "openapi"}
    with patch("app.compatibility_routes.db", db), patch(
        "app.compatibility_routes.canonical_model_for_revision", lambda *_a: None
    ), patch("app.compatibility_routes.enforce_permission"), patch(
        "app.compatibility_routes.openapi_for_revision", return_value=_SPEC
    ), patch("app.compatibility_routes.capture_oasdiff_compatibility_evidence"):
        r = client.post(
            "/v1/versions/acme/proj-1/compatibility",
            json={"baseRevisionId": _UUID["v1"], "headRevisionId": _UUID["v3"], "mode": "FULL"},
        )
    assert r.status_code == 200, r.text
    under = r.json()["evaluatedUnder"]
    assert (under["modeApplied"], under["ruleset"], under["formats"]) == (False, "openapi-compatibility", ["openapi"])


# ===========================================================================
# The publish guardrail
# ===========================================================================


def _assess(policy: Dict[str, Any], *, prior: Optional[list] = None, level: str = "block"):
    db = _db(policy=policy, prior=prior)
    db.get_prior_published_baseline_revision_id.return_value = _UUID["v2"]
    with patch("app.breaking_publish_guardrail.db", db), patch(
        "app.breaking_publish_guardrail.canonical_model_for_revision", _models_for("v1", "v2", "v3")
    ):
        return assess_breaking_publish(
            tenant_slug="acme",
            tenant_id="tenant-1",
            project_id="proj-1",
            head_version={"id": _UUID["v3"], "version_id": "2.1.0"},
            policy=level,
            openapi_loader=lambda *_a, **_k: {},
        )


def test_full_policy_publishes_a_change_compatible_with_the_baseline() -> None:
    assessment = _assess({"compatibility_mode": "FULL"})
    assert assessment.status == STATUS_OK
    assert assessment.evaluated_under and assessment.evaluated_under["mode"] == "FULL"
    assert assessment.evaluated_under["modeApplied"] is True


def test_full_transitive_policy_blocks_a_break_against_an_older_revision() -> None:
    """Acceptance: compatible with the base, not with an older revision — publish fails, naming it."""
    assessment = _assess({"compatibility_mode": "FULL", "compatibility_transitive": True}, prior=_V1_ROW)
    assert assessment.status == STATUS_BLOCKED
    assert assessment.breaking is True
    assert assessment.from_version == "2.0.0"
    (change,) = assessment.breaking_changes
    assert change["againstVersion"] == "1.0.0"
    assert change["againstRevisionId"] == _UUID["v1"]
    assert change["ruleId"] == "avro-compatibility.reader-field-missing-default-value"
    assert "earlier revision(s) 1.0.0" in assessment.message()
    payload = assessment.as_payload()
    assert payload["evaluatedUnder"]["transitive"] is True
    assert [r["versionLabel"] for r in payload["evaluatedUnder"]["comparedRevisions"]] == ["2.0.0", "1.0.0"]


def test_the_guardrail_payload_validates_against_its_response_model() -> None:
    from app.models import BreakingPublishGuardrailOut

    assessment = _assess({"compatibility_mode": "FULL", "compatibility_transitive": True}, prior=_V1_ROW)
    out = BreakingPublishGuardrailOut.model_validate(assessment.as_payload()).model_dump(by_alias=True)
    assert out["breakingChanges"][0]["againstVersion"] == "1.0.0"
    assert out["evaluatedUnder"]["mode"] == "FULL"


# ===========================================================================
# Style-guide revisions (the route tests live in test_style_guide_routes.py)
# ===========================================================================


def _guide(**overrides: Any) -> Dict[str, Any]:
    row = {"id": "g-1", "tenant_id": "tenant-1", "name": "Acme REST", "source": "custom", "is_default": False}
    row.update(overrides)
    return row


def test_the_revision_snapshot_freezes_the_compatibility_policy() -> None:
    from app.style_guide_revisions import guide_snapshot

    snapshot = guide_snapshot(
        _guide(compatibility_mode="FORWARD", compatibility_transitive=True, protobuf_breaking_category="WIRE"), []
    )
    assert snapshot["policy"]["compatibilityMode"] == "FORWARD"
    assert snapshot["policy"]["compatibilityTransitive"] is True
    assert snapshot["policy"]["protobufBreakingCategory"] == "WIRE"
    defaults = guide_snapshot(_guide(), [])["policy"]
    assert (defaults["compatibilityMode"], defaults["compatibilityTransitive"], defaults["protobufBreakingCategory"]) == (
        "BACKWARD",
        False,
        "WIRE_JSON",
    )
