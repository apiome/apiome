"""A provider delivery on a bound ref announces a pending check — GNC-2.2 (#4738).

The ticket's "provider events resolve to an authorized branch binding", met through the repository
webhook endpoint that already exists (REPO-4.3) and the bindings GNC-2.1 wrote. What needs proving
here is the wiring rather than the ingestion or the adapters, both of which have their own suites:
that a verified delivery seeds a check on every authorized binding of the ref it moved, that it
does so outside the tracked-branch gate, that a redelivery seeds nothing new, that a fault in the
check path can never turn a verified delivery into a 500 the provider will retry forever, and that
the acceptance audit says how many checks a delivery announced.

Driven against the same fake store the candidate suite uses, extended with the two check accessors.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

import pytest

from app.provider_checks import DEFAULT_CHECK_NAME, ORIGIN_WEBHOOK, STATE_PENDING
from app.repository_webhook_dispatch import (
    OUTCOME_ENQUEUED,
    OUTCOME_IGNORED,
    REASON_BRANCH_NOT_TRACKED,
    WEBHOOK_ACCEPTED_ACTION,
    ingest_webhook_delivery,
)

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_REPO_ID = "880e8400-e29b-41d4-a716-446655440003"
_SUB_ID = "990e8400-e29b-41d4-a716-446655440004"
_REPO = "octocat/hello-world"
_SECRET = "signing-secret"
_HEAD = "b" * 40


class FakeDb:
    """The ``Database`` surface the dispatcher and the check seeding touch.

    Attributes:
        bindings: Authorized bindings, keyed by ``(repository_id, ref)``.
        checks: Check rows by ``(binding, commit, name)`` — the V265 identity.
        seeded: One entry per check actually seeded.
        published: One entry per check read back for publishing.
    """

    def __init__(
        self,
        *,
        bindings: Optional[Dict[Any, List[str]]] = None,
        tracked_branches=("main",),
    ) -> None:
        self.bindings = bindings or {}
        self.tracked_branches = list(tracked_branches)
        self.checks: Dict[Any, str] = {}
        self.seeded: List[Dict[str, Any]] = []
        self.published: List[str] = []
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
        # GNC-2.1's candidate path; its own suite covers it.
        return []

    def find_authorized_bindings_for_check(self, *, repository_id, ref):
        return [
            {
                "id": binding_id,
                "tenant_id": _TENANT,
                "project_id": "11111111-1111-4111-8111-111111111111",
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

    def get_provider_check_run(self, *, tenant_id, check_id):
        self.published.append(check_id)
        # Returning None stops before the adapter: what this suite tests is the dispatch wiring,
        # and the publish path is driven end to end in tests/test_provider_check_store.py.
        return None

    # -- writes --------------------------------------------------------------------------

    def upsert_provider_check_run(self, **kwargs):
        key = (kwargs["binding_id"], kwargs["commit_sha"], kwargs["name"])
        if key in self.checks:
            # The V265 identity already exists; the row moves rather than fanning out, and the
            # seeded pending state is unchanged, so nothing new is announced.
            return None
        check_id = f"chk-{len(self.checks)}"
        self.checks[key] = check_id
        self.seeded.append(kwargs)
        return {"check_id": check_id, "created": True, "state": kwargs["state"], "attempt": 1}

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
# Seeding
# ---------------------------------------------------------------------------------------------


def test_a_push_to_a_bound_branch_announces_a_pending_check():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    result = _deliver(db, _push())

    assert result.checks_seeded == 1
    seeded = db.seeded[0]
    assert seeded["binding_id"] == "b1"
    assert seeded["commit_sha"] == _HEAD
    assert seeded["state"] == STATE_PENDING
    assert seeded["name"] == DEFAULT_CHECK_NAME
    assert seeded["origin"] == ORIGIN_WEBHOOK
    assert seeded["delivery_id"] == "d-1"
    # The webhook path owns no user identity, so it names no actor at all — the check is
    # attributed to the delivery, which is the only thing that actually caused it.
    assert "created_by" not in seeded


def test_every_draft_bound_to_the_ref_gets_its_own_check():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1", "b2"]})
    assert _deliver(db, _push()).checks_seeded == 2
    assert [row["binding_id"] for row in db.seeded] == ["b1", "b2"]


def test_a_pull_request_announces_the_check_on_its_head_and_names_the_pull_request():
    db = FakeDb(bindings={(_REPO_ID, "feature/x"): ["b1"]})
    result = _deliver(db, _pull_request())

    assert result.checks_seeded == 1
    assert db.seeded[0]["commit_sha"] == "c" * 40
    assert db.seeded[0]["pr_number"] == 42


def test_a_fork_head_is_not_a_ref_of_this_repository_so_nothing_is_announced():
    db = FakeDb(bindings={(_REPO_ID, "feature/x"): ["b1"]})
    assert _deliver(db, _pull_request(head_repo="someone/fork")).checks_seeded == 0
    assert db.seeded == []


def test_a_closed_pull_request_moves_no_code_and_announces_nothing():
    db = FakeDb(bindings={(_REPO_ID, "feature/x"): ["b1"]})
    assert _deliver(db, _pull_request(action="closed")).checks_seeded == 0


def test_a_push_to_a_ref_nothing_is_bound_to_announces_nothing():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    assert _deliver(db, _push(branch="other"), delivery_id="d-2").checks_seeded == 0


# ---------------------------------------------------------------------------------------------
# The gate a check deliberately sits outside
# ---------------------------------------------------------------------------------------------


def test_a_bound_branch_nobody_imported_from_still_gets_its_check():
    # The binding is the review unit, and it need never have been imported from — the same reason
    # GNC-2.1 raises its candidate outside this gate.
    db = FakeDb(bindings={(_REPO_ID, "release/2"): ["b1"]}, tracked_branches=["main"])
    result = _deliver(db, _push(branch="release/2"))

    assert result.outcome == OUTCOME_IGNORED
    assert result.reason == REASON_BRANCH_NOT_TRACKED
    assert result.checks_seeded == 1


# ---------------------------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------------------------


def test_a_redelivery_of_the_same_push_announces_nothing_new():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    first = _deliver(db, _push(), delivery_id="d-1")
    again = _deliver(db, _push(), delivery_id="d-1")

    assert (first.checks_seeded, again.checks_seeded) == (1, 0)
    assert len(db.seeded) == 1


def test_a_second_push_to_the_same_branch_announces_a_check_on_the_new_commit():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    _deliver(db, _push(), delivery_id="d-1")
    result = _deliver(db, _push(sha="d" * 40), delivery_id="d-2")

    assert result.checks_seeded == 1
    assert [row["commit_sha"] for row in db.seeded] == [_HEAD, "d" * 40]


# ---------------------------------------------------------------------------------------------
# Evidence and failure
# ---------------------------------------------------------------------------------------------


def test_the_acceptance_audit_says_how_many_checks_were_announced():
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1", "b2"]})
    _deliver(db, _push())

    accepted = [row for row in db.audits if row["action"] == WEBHOOK_ACCEPTED_ACTION]
    assert accepted and accepted[-1]["detail"]["checksSeeded"] == 2


def test_a_delivery_that_only_announced_a_check_is_still_audited():
    db = FakeDb(bindings={(_REPO_ID, "release/2"): ["b1"]}, tracked_branches=["main"])
    _deliver(db, _push(branch="release/2"))

    accepted = [row for row in db.audits if row["action"] == WEBHOOK_ACCEPTED_ACTION]
    assert accepted and accepted[-1]["detail"]["checksSeeded"] == 1


@pytest.mark.parametrize(
    "method", ["find_authorized_bindings_for_check", "upsert_provider_check_run"]
)
def test_a_check_store_fault_never_fails_the_delivery(method):
    # A 500 here would be retried by the provider forever over something no retry can fix.
    class Broken(FakeDb):
        pass

    def explode(*_args, **_kwargs):
        raise RuntimeError("check store down")

    setattr(Broken, method, explode)
    db = Broken(bindings={(_REPO_ID, "main"): ["b1"]})
    result = _deliver(db, _push())

    assert result.outcome == OUTCOME_ENQUEUED
    assert result.checks_seeded == 0


def test_seeding_can_be_switched_off_for_a_deployment(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "provider_checks_webhook_seed_enabled", False)
    db = FakeDb(bindings={(_REPO_ID, "main"): ["b1"]})
    result = _deliver(db, _push())

    assert result.checks_seeded == 0
    assert db.seeded == []
    # The rest of the delivery is untouched.
    assert result.outcome == OUTCOME_ENQUEUED
