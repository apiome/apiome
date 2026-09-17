"""A provider delivery on a bound ref raises a sync candidate — GNC-2.1 (#4737).

The acceptance criterion "ref updates create an auditable sync candidate" is met through the
repository webhook endpoint that already exists (REPO-4.3), so what needs proving here is the
wiring, not the ingestion: which deliveries count as a ref *this repository* moved, that the
candidate is raised whether or not the scan dispatch finds anything to do, that redelivery raises
nothing new, and that the acceptance audit says how many drafts it touched.

Driven against the same kind of fake store the dispatch suite uses, plus the binding accessors.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

import pytest

from app.repository_webhook_dispatch import (
    OUTCOME_ENQUEUED,
    OUTCOME_IGNORED,
    WEBHOOK_ACCEPTED_ACTION,
    _moved_ref,
    ingest_webhook_delivery,
)
from app.repository_webhook_ingest import ParsedWebhookEvent

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_REPO_ID = "880e8400-e29b-41d4-a716-446655440003"
_SUB_ID = "990e8400-e29b-41d4-a716-446655440004"
_REPO = "octocat/hello-world"
_SECRET = "signing-secret"
_HEAD = "b" * 40


class FakeDb:
    """The ``Database`` surface the dispatcher and the binding lookup touch.

    Attributes:
        bindings: Active bindings, keyed by ``(repository_id, ref)``.
        raised: One entry per candidate raised.
        tracked_branches: Branches a stored import spec makes scannable.
    """

    def __init__(self, *, bindings: Optional[Dict[Any, List[str]]] = None, tracked_branches=("main",)) -> None:
        self.bindings = bindings or {}
        self.tracked_branches = list(tracked_branches)
        self.raised: List[Dict[str, Any]] = []
        self.checks: Dict[Any, str] = {}
        self.seeded_checks: List[Dict[str, Any]] = []
        self.seen_deliveries: set = set()
        self.events: List[Dict[str, Any]] = []
        self.audits: List[Dict[str, Any]] = []
        self.scan_jobs: List[Any] = []

    # -- reads ---------------------------------------------------------------------------

    def find_repository_webhook_subscriptions(self, provider, repo_full_name):
        return [
            {
                "id": _SUB_ID,
                "tenant_id": _TENANT,
                "repository_id": _REPO_ID,
                "provider": "github",
                "repo_full_name": _REPO,
                "secret_enc": b"ciphertext",
                "pr_preview_enabled": True,
            }
        ]

    def list_repository_import_spec_branches(self, repository_id):
        return list(self.tracked_branches)

    def find_active_bindings_for_repository_ref(self, *, repository_id, ref):
        return [
            {"id": binding_id, "tenant_id": _TENANT, "project_id": "p", "version_id": f"v-{binding_id}"}
            for binding_id in self.bindings.get((repository_id, ref), [])
        ]

    def find_authorized_bindings_for_check(self, *, repository_id, ref):
        # GNC-2.2 reads the same bindings through its own accessor, because publishing a check
        # needs the provider coordinates the candidate read has no use for.
        return [
            {
                "id": binding_id,
                "tenant_id": _TENANT,
                "project_id": "p",
                "version_id": f"v-{binding_id}",
                "repository_id": repository_id,
                "provider": "github",
                "repo_full_name": _REPO,
                "repo_url": f"https://github.com/{_REPO}",
                "ref": ref,
                "path": "",
                "commit_sha": "a" * 40,
            }
            for binding_id in self.bindings.get((repository_id, ref), [])
        ]

    # -- writes --------------------------------------------------------------------------

    def raise_binding_sync_candidate(self, **kwargs):
        key = (kwargs["binding_id"], kwargs.get("delivery_id"))
        if kwargs.get("delivery_id") and key in self.seen_deliveries:
            return None
        self.seen_deliveries.add(key)
        self.raised.append(kwargs)
        return {"candidate_id": f"c-{len(self.raised)}", "superseded": 0}

    def upsert_provider_check_run(self, **kwargs):
        key = (kwargs["binding_id"], kwargs["commit_sha"], kwargs["name"])
        if key in self.checks:
            return {"check_id": self.checks[key], "created": False, "state": kwargs["state"], "attempt": 1}
        check_id = f"chk-{len(self.checks)}"
        self.checks[key] = check_id
        self.seeded_checks.append(kwargs)
        return {"check_id": check_id, "created": True, "state": kwargs["state"], "attempt": 1}

    def get_provider_check_run(self, *, tenant_id, check_id):
        # The seeded check is never published in this suite: the store's own tests drive the
        # adapters, and the point here is that the dispatch reaches the seeding at all.
        return None

    def record_repository_webhook_event(self, **kwargs):
        row = {"id": f"evt-{len(self.events)}", **kwargs}
        self.events.append(row)
        return row

    def insert_workflow_audit(self, tenant_id, project_id, version_id, action, outcome, actor, detail):
        self.audits.append({"action": action, "outcome": outcome, "detail": detail})

    def enqueue_repository_file_scan_job_if_idle(self, tenant_id, repository_id, branch):
        self.scan_jobs.append((repository_id, branch))
        return f"job-{len(self.scan_jobs)}"

    def mark_repository_poll_due(self, repository_id):
        return True

    def touch_repository_webhook_subscription(self, subscription_id, delivery_id=None):
        return None


@pytest.fixture(autouse=True)
def _secret_always_recovers(monkeypatch):
    """Decrypt the fake ciphertext to the known secret, so tests exercise verification."""
    monkeypatch.setattr(
        "app.repository_webhook_subscriptions.decrypt_signing_secret",
        lambda blob: _SECRET if bytes(blob) == b"ciphertext" else None,
    )


def _signed(payload: dict, delivery_id: str = "d-1") -> tuple:
    """A signed delivery of ``payload``."""
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": ("pull_request" if "pull_request" in payload else "push"),
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }
    return body, headers


def _push(branch: str = "main", sha: str = _HEAD) -> dict:
    """A GitHub push payload."""
    return {
        "ref": f"refs/heads/{branch}",
        "after": sha,
        "repository": {"full_name": _REPO},
        "head_commit": {"id": sha},
    }


def _pull_request(action: str = "synchronize", head_repo: str = _REPO) -> dict:
    """A GitHub pull-request payload."""
    return {
        "action": action,
        "number": 42,
        "repository": {"full_name": _REPO},
        "pull_request": {
            "number": 42,
            "base": {"ref": "main"},
            "head": {"ref": "feature/x", "sha": "c" * 40, "repo": {"full_name": head_repo}},
        },
    }


def _deliver(db: FakeDb, payload: dict, delivery_id: str = "d-1"):
    """Ingest one signed delivery."""
    body, headers = _signed(payload, delivery_id)
    return ingest_webhook_delivery(db, provider="github", raw_body=body, headers=headers)


# ---------------------------------------------------------------------------------------------
# Which deliveries move a ref of this repository
# ---------------------------------------------------------------------------------------------


def test_a_push_moves_the_branch_it_names():
    event = ParsedWebhookEvent(kind="push", repo_full_name=_REPO, branch="main", head_sha=_HEAD)
    assert _moved_ref(event) == ("main", _HEAD)


def test_a_pull_request_moves_its_head_branch_not_its_base():
    event = ParsedWebhookEvent(
        kind="pull_request",
        repo_full_name=_REPO,
        branch="main",
        head_sha=_HEAD,
        action="synchronize",
        pr_number=42,
        pr_head_branch="feature/x",
        pr_head_in_repo=True,
    )
    assert _moved_ref(event) == ("feature/x", _HEAD)


@pytest.mark.parametrize(
    "event",
    [
        # A fork's head is not a ref of this repository.
        ParsedWebhookEvent(
            kind="pull_request",
            repo_full_name=_REPO,
            branch="main",
            head_sha=_HEAD,
            action="synchronize",
            pr_head_branch="feature/x",
            pr_head_in_repo=False,
        ),
        # A closed PR moves no code.
        ParsedWebhookEvent(
            kind="pull_request",
            repo_full_name=_REPO,
            branch="main",
            head_sha=_HEAD,
            action="closed",
            pr_head_branch="feature/x",
            pr_head_in_repo=True,
        ),
        # A delivery that named no commit.
        ParsedWebhookEvent(kind="push", repo_full_name=_REPO, branch="main", head_sha=""),
    ],
)
def test_some_deliveries_move_no_ref_of_this_repository(event):
    assert _moved_ref(event) is None


# ---------------------------------------------------------------------------------------------
# End to end through the ingestion path
# ---------------------------------------------------------------------------------------------


def test_a_push_to_a_bound_branch_raises_one_candidate_per_draft():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1", "b2"]})
    result = _deliver(db, _push())

    assert result.binding_candidates == 2
    assert [row["origin"] for row in db.raised] == ["webhook", "webhook"]
    assert {row["to_commit_sha"] for row in db.raised} == {_HEAD}
    assert {row["delivery_id"] for row in db.raised} == {"d-1"}


def test_a_candidate_is_raised_even_when_the_branch_was_never_imported_from():
    # No import spec for this branch, so the scan dispatch ignores the delivery entirely — but a
    # draft is bound to it, and that is a different question.
    db = FakeDb(bindings={(_REPO_ID, "release/2"): ["b1"]}, tracked_branches=["main"])
    result = _deliver(db, _push(branch="release/2"))

    assert result.outcome == OUTCOME_IGNORED
    assert db.scan_jobs == []
    assert result.binding_candidates == 1


def test_a_push_to_an_unbound_branch_raises_nothing():
    db = FakeDb(bindings={(_REPO_ID, "other"): ["b1"]})
    result = _deliver(db, _push())

    assert result.outcome == OUTCOME_ENQUEUED
    assert result.binding_candidates == 0
    assert db.raised == []


def test_a_pull_request_raises_candidates_on_its_head_branch():
    db = FakeDb(bindings={(_REPO_ID, "feature/x"): ["b1"], (_REPO_ID, "main"): ["b2"]})
    result = _deliver(db, _pull_request())

    assert result.binding_candidates == 1
    assert db.raised[0]["binding_id"] == "b1"


def test_a_redelivery_raises_nothing_new():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    first = _deliver(db, _push(), delivery_id="d-1")
    again = _deliver(db, _push(), delivery_id="d-1")

    assert (first.binding_candidates, again.binding_candidates) == (1, 0)
    assert len(db.raised) == 1


def test_the_acceptance_audit_says_how_many_drafts_were_touched():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1", "b2"]})
    _deliver(db, _push())

    accepted = [row for row in db.audits if row["action"] == WEBHOOK_ACCEPTED_ACTION]
    assert accepted and accepted[-1]["detail"]["bindingCandidates"] == 2


def test_a_delivery_that_only_moved_a_bound_ref_is_still_audited():
    db = FakeDb(bindings={(_REPO_ID, "release/2"): ["b1"]}, tracked_branches=["main"])
    _deliver(db, _push(branch="release/2"))

    accepted = [row for row in db.audits if row["action"] == WEBHOOK_ACCEPTED_ACTION]
    assert accepted and accepted[-1]["detail"]["bindingCandidates"] == 1


def test_a_binding_store_fault_never_fails_the_delivery(monkeypatch):
    class Broken(FakeDb):
        def find_active_bindings_for_repository_ref(self, **kwargs):
            raise RuntimeError("binding store down")

    db = Broken(bindings={(_REPO_ID, "main"): ["b1"]})
    result = _deliver(db, _push())

    assert result.outcome == OUTCOME_ENQUEUED
    assert result.binding_candidates == 0
