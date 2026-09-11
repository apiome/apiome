"""An in-memory ``sdk_regen_*`` store for the SDK-4.3 (#4497) worker tests.

It implements exactly the database methods :mod:`app.sdk_regen_worker` calls, with the semantics
V258's SQL has — the claim takes due jobs in order *within* a subscription and skips a subscription
whose earlier job is still in flight; a close-out matches only its own claim token; the lease sweep
dead-letters stale claims once — so the worker's behaviour can be asserted without Postgres. The SQL
itself is covered by ``test_sdk_regen_database.py`` and was exercised against a real V258 database.

It also stands in for the push-webhook tables the dead-letter alert fans out over.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
REVISION = "33333333-3333-4333-8333-333333333333"
PUBLISHER = "88888888-8888-4888-8888-888888888888"

_ACTIVE = ("pending", "running", "retrying")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FakeRegenStore:
    """Subscriptions, runs, jobs, versions and webhook deliveries, in memory.

    Attributes:
        subscriptions: Subscription rows by id.
        runs: Run rows by id.
        jobs: Job rows by id, in insertion order.
        versions: Revision rows by id (``published`` and ``version_id``).
        webhook_subscription_ids: The tenant's active push-webhook subscriptions.
        webhook_deliveries: Every enqueued ``(subscription_id, event_type, payload)``.
        claims: How many claims were attempted.
    """

    subscriptions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    jobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    versions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    webhook_subscription_ids: List[str] = field(default_factory=lambda: ["hook-1"])
    webhook_deliveries: List[Tuple[str, str, Dict[str, Any]]] = field(default_factory=list)
    claims: int = 0
    _sequence: int = 0

    # -- arranging -----------------------------------------------------------------------------

    def subscribe(
        self,
        ecosystem: str,
        delivery_mode: str,
        options: Optional[Dict[str, Any]] = None,
        *,
        active: bool = True,
    ) -> str:
        """Store a subscription and return its id (options default as ``normalize_options`` would)."""
        sub_id = str(uuid.uuid4())
        if options is None:
            options = {"dryRun": False} if "registry" in delivery_mode else {}
        self.subscriptions[sub_id] = {
            "id": sub_id,
            "ecosystem": ecosystem,
            "delivery_mode": delivery_mode,
            "options": dict(options),
            "active": active,
        }
        return sub_id

    def publish(self, version_line: str = "1.4.2", version_id: str = REVISION) -> List[str]:
        """What ``enqueue_sdk_regen_run`` does: a run plus one pending job per active subscription."""
        self.versions.setdefault(version_id, {"id": version_id, "published": True, "version_id": version_line})
        active = [sub for sub in self.subscriptions.values() if sub["active"]]
        if not active:
            return []
        run_id = str(uuid.uuid4())
        self.runs[run_id] = {
            "id": run_id,
            "version_id": version_id,
            "version_line": version_line,
            "published_by": PUBLISHER,
        }
        ids = []
        for sub in sorted(active, key=lambda item: item["ecosystem"]):
            self._sequence += 1
            job_id = str(uuid.uuid4())
            self.jobs[job_id] = {
                "id": job_id,
                "tenant_id": TENANT,
                "project_id": PROJECT,
                "run_id": run_id,
                "subscription_id": sub["id"],
                "ecosystem": sub["ecosystem"],
                "delivery_mode": sub["delivery_mode"],
                "options": dict(sub["options"]),
                "status": "pending",
                "attempt_count": 0,
                "next_attempt_at": _now() - timedelta(seconds=1),
                "claimed_at": None,
                "claim_token": None,
                "publish_run_id": None,
                "publish_status": None,
                "delivery_run_id": None,
                "delivery_status": None,
                "package_name": None,
                "package_version": None,
                "regen_counter": None,
                "artifact_sha256": None,
                "pull_request_number": None,
                "pull_request_url": None,
                "error_step": None,
                "error_code": None,
                "error_message": None,
                "attempts": [],
                "finished_at": None,
                "_sequence": self._sequence,
            }
            ids.append(job_id)
        return ids

    def job(self, ecosystem: str, version_line: Optional[str] = None) -> Dict[str, Any]:
        """The newest job for an ecosystem (optionally of one version)."""
        matches = [
            job
            for job in self.jobs.values()
            if job["ecosystem"] == ecosystem
            and (version_line is None or self.runs[job["run_id"]]["version_line"] == version_line)
        ]
        return matches[-1]

    def make_due(self, job_id: str) -> None:
        """Move a retrying job's backoff into the past."""
        self.jobs[job_id]["next_attempt_at"] = _now() - timedelta(seconds=1)

    def unsubscribe(self, sub_id: str) -> None:
        """What deleting a subscription does: its jobs keep their row, with a NULL reference."""
        del self.subscriptions[sub_id]
        for job in self.jobs.values():
            if job["subscription_id"] == sub_id:
                job["subscription_id"] = None

    # -- the database methods the worker calls ------------------------------------------------

    def claim_next_sdk_regen_job(self, claim_token: str) -> Optional[Dict[str, Any]]:
        self.claims += 1
        now = _now()

        def blocked(job: Dict[str, Any]) -> bool:
            return job["subscription_id"] is not None and any(
                other["subscription_id"] == job["subscription_id"]
                and other["status"] in _ACTIVE
                and other["_sequence"] < job["_sequence"]
                for other in self.jobs.values()
            )

        due = [
            job
            for job in self.jobs.values()
            if job["status"] in ("pending", "retrying")
            and job["next_attempt_at"] is not None
            and job["next_attempt_at"] <= now
            and not blocked(job)
        ]
        if not due:
            return None
        job = min(due, key=lambda item: (item["next_attempt_at"], item["_sequence"]))
        job.update(
            status="running",
            attempt_count=job["attempt_count"] + 1,
            claimed_at=now,
            claim_token=claim_token,
        )
        run = self.runs[job["run_id"]]
        sub = self.subscriptions.get(job["subscription_id"] or "")
        return {
            **self._public(job),
            "version_id": run["version_id"],
            "version_line": run["version_line"],
            "published_by": run["published_by"],
            "tenant_slug": "acme",
            "project_slug": "widgets",
            "subscription_active": sub["active"] if sub else None,
            "subscription_delivery_mode": sub["delivery_mode"] if sub else None,
            "subscription_options": copy.deepcopy(sub["options"]) if sub else None,
        }

    def finish_sdk_regen_job_attempt(
        self, job_id: str, claim_token: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        if job is None or job["claim_token"] != claim_token:
            return None
        lost = job["status"] == "dead_letter" and job["error_code"] == kwargs["worker_lost_code"]
        if job["status"] != "running" and not lost:
            return None
        attempts = list(job["attempts"])
        if len(attempts) >= kwargs["max_attempt_entries"]:
            attempts = attempts[1:]
        attempts.append(kwargs["attempt"])
        for key in (
            "status",
            "next_attempt_at",
            "delivery_mode",
            "options",
            "publish_run_id",
            "publish_status",
            "delivery_run_id",
            "delivery_status",
            "package_name",
            "package_version",
            "regen_counter",
            "artifact_sha256",
            "pull_request_number",
            "pull_request_url",
            "error_step",
            "error_code",
            "error_message",
        ):
            job[key] = kwargs[key]
        job["attempts"] = attempts
        job["finished_at"] = _now() if kwargs["status"] in ("succeeded", "dead_letter", "cancelled") else None
        return self._public(job)

    def save_sdk_regen_job_progress(self, job_id: str, claim_token: str, **columns: Any) -> int:
        job = self.jobs.get(job_id)
        if job is None or job["claim_token"] != claim_token or job["status"] != "running":
            return 0
        job.update(columns)
        return 1

    def reap_stale_sdk_regen_jobs(
        self, *, lease_seconds: int, error_code: str, error_message: str, max_attempt_entries: int
    ) -> List[Dict[str, Any]]:
        cutoff = _now() - timedelta(seconds=lease_seconds)
        reaped = []
        for job in self.jobs.values():
            if job["status"] == "running" and job["claimed_at"] < cutoff:
                job.update(
                    status="dead_letter",
                    next_attempt_at=None,
                    error_step="worker",
                    error_code=error_code,
                    error_message=error_message,
                    finished_at=_now(),
                )
                job["attempts"] = (job["attempts"] + [{"outcome": "dead_letter", "errorCode": error_code}])[
                    -max_attempt_entries:
                ]
                run = self.runs[job["run_id"]]
                reaped.append(
                    {
                        **self._public(job),
                        "version_id": run["version_id"],
                        "version_line": run["version_line"],
                        "project_slug": "widgets",
                    }
                )
        return reaped

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return copy.deepcopy(self.versions.get(version_id))

    def list_active_push_webhook_subscription_ids(self, tenant_id: str) -> List[str]:
        return list(self.webhook_subscription_ids)

    def enqueue_push_webhook_delivery(
        self, tenant_id: str, subscription_id: str, event_type: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.webhook_deliveries.append((subscription_id, event_type, payload))
        return {"id": f"delivery-{len(self.webhook_deliveries)}"}

    # -- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _public(job: Dict[str, Any]) -> Dict[str, Any]:
        """A job as the store returns it (without the fake's own bookkeeping)."""
        return {key: copy.deepcopy(value) for key, value in job.items() if not key.startswith("_")}
