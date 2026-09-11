"""The auto-regen worker — SDK-4.3 (#4497).

Three layers, each against an in-memory queue (:mod:`fake_sdk_regen_store`) with V258's claim,
close-out and lease semantics:

* **One job** with the SDK-4.1/4.2 pipelines patched — which steps run, in what order, with what
  pinned version, and what every outcome makes of the job (succeeded, retrying, dead letter,
  cancelled).
* **The sweep** — the matrix: one subscription's failure never blocks another's, a subscription's
  publishes run in order, the lease reaps a lost worker, the kill switch halts everything.
* **End to end** with the *real* pipelines — an in-memory registry transport and the in-memory
  GitHub — asserting the ticket's acceptance criteria: a publish regenerates and delivers every
  active subscription; a failure retries or dead-letters without touching the others; the history
  links the publish to the package version and the pull request; unsubscribing stops future runs.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fake_github_git import DEFAULT_TOKEN, FakeGitHub
from fake_sdk_regen_store import PROJECT, PUBLISHER, REVISION, FakeRegenStore
from test_sdk_distribution import _SPEC, _api
from test_sdk_git_delivery_pipeline import _repository
from test_sdk_publish_pipeline import _accepting, _credential, _settings

from app.export_source import ExportSource, ExportSourceError
from app.sdk_git_delivery_pipeline import DeliveryOutcome
from app.sdk_git_delivery_targets import DeliveryTarget
from app.sdk_publish_pipeline import PublishError, PublishOutcome
from app.sdk_regen_policy import (
    BACKOFF_AFTER_FAILURE_SECONDS,
    ERROR_GIT_TARGET_MISSING,
    ERROR_INTERNAL,
    ERROR_SOURCE_UNAVAILABLE,
    ERROR_SUBSCRIPTION_DISABLED,
    ERROR_UNSUBSCRIBED,
    ERROR_VERSION_MISSING,
    ERROR_VERSION_UNPUBLISHED,
    ERROR_WORKER_LOST,
    EVENT_SDK_REGEN_DEAD_LETTERED,
    MAX_ATTEMPTS,
)
from app.sdk_regen_worker import process_sdk_regen_sweep, reap_lost_jobs, run_claimed_job
from app.sdk_registry_client import RegistryUploadError

_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
_PUBLISH_RUN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_DELIVERY_RUN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_TARGET = DeliveryTarget("cccccccc-cccc-4ccc-8ccc-cccccccccccc", "npm", "repo-1", None, "sdks/ts")


def _source() -> ExportSource:
    """The published revision, as ``load_export_source`` returns it."""
    return ExportSource(
        api=_api(),
        artifact_id=PROJECT,
        version_record_id=REVISION,
        version_label="1.4.2",
        source_text=_SPEC,
        source_format="openapi-3.1",
    )


def _published(**fields: Any) -> PublishOutcome:
    values: Dict[str, Any] = {
        "run_id": _PUBLISH_RUN,
        "status": "published",
        "dry_run": False,
        "ecosystem": "npm",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.3",
        "release_series": "1.4",
        "regen_counter": 3,
        "version_line": "1.4.2",
        "registry_url": "https://registry.npmjs.org",
        "credential_scope": "tenant",
        "artifact_sha256": "f" * 64,
    }
    values.update(fields)
    return PublishOutcome(**values)


def _delivered(**fields: Any) -> DeliveryOutcome:
    values: Dict[str, Any] = {
        "run_id": _DELIVERY_RUN,
        "status": "opened",
        "ecosystem": "npm",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.3",
        "pull_request_number": 12,
        "pull_request_url": "https://github.com/acme/widgets-sdk/pull/12",
    }
    values.update(fields)
    return DeliveryOutcome(**values)


class _Pipelines:
    """The SDK-4.1/4.2 entry points and the revision loader, patched."""

    def __init__(
        self,
        *,
        publish: Any = None,
        deliver: Any = None,
        source: Any = None,
        target: Any = _TARGET,
    ) -> None:
        self.publish = MagicMock(**_effect(publish, _published()))
        self.deliver = MagicMock(**_effect(deliver, _delivered()))
        self.load = MagicMock(**_effect(source, _source()))
        self.target = MagicMock(**_effect(target, _TARGET))
        self._stack = ExitStack()

    def __enter__(self) -> "_Pipelines":
        for name, mock in (
            ("publish", self.publish),
            ("deliver", self.deliver),
            ("load_export_source", self.load),
            ("resolve_target", self.target),
        ):
            self._stack.enter_context(patch(f"app.sdk_regen_worker.{name}", mock))
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stack.close()


def _effect(value: Any, default: Any) -> Dict[str, Any]:
    """``side_effect`` for an exception (or a list), ``return_value`` otherwise."""
    if value is None:
        return {"return_value": default}
    if isinstance(value, BaseException) or isinstance(value, list):
        return {"side_effect": value}
    return {"return_value": value}


def _claim(store: FakeRegenStore, ecosystem: str = "npm") -> Dict[str, Any]:
    """Claim the next due job and check it is the expected ecosystem's."""
    row = store.claim_next_sdk_regen_job("99999999-9999-4999-8999-999999999999")
    assert row is not None and row["ecosystem"] == ecosystem
    return row


def _run_one(store: FakeRegenStore, pipelines: _Pipelines, ecosystem: str = "npm") -> Dict[str, Any]:
    """Claim and run one job with the pipelines patched; return the stored job."""
    row = _claim(store, ecosystem)
    with pipelines:
        run_claimed_job(store, row, apiome_version="1.185.0", clock=lambda: _NOW)
    return store.jobs[row["id"]]


def _alerts(store: FakeRegenStore) -> List[Dict[str, Any]]:
    return [payload for _, event, payload in store.webhook_deliveries if event == EVENT_SDK_REGEN_DEAD_LETTERED]


# ============================================================================================
# One job
# ============================================================================================
def test_registry_and_git_publishes_then_delivers_the_version_it_claimed():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert job["status"] == "succeeded"
    publish_call = pipelines.publish.call_args
    assert publish_call.kwargs["dry_run"] is False
    assert publish_call.kwargs["ecosystem"] == "npm"
    context = publish_call.kwargs["context"]
    assert (context.tenant_slug, context.project_slug) == ("acme", "widgets")
    assert (context.version_record_id, context.version_line) == (REVISION, "1.4.2")
    # The publisher is the actor of record; the provenance names the running API.
    assert context.actor_id == PUBLISHER
    assert publish_call.kwargs["apiome_version"] == "1.185.0"
    # The pull request carries exactly the version the publish claimed.
    assert pipelines.deliver.call_args.kwargs["regen_counter"] == 3
    assert pipelines.deliver.call_args.kwargs["target"] == _TARGET
    # History links the publish event to the package and the pull request.
    assert job["publish_run_id"] == _PUBLISH_RUN and job["publish_status"] == "published"
    assert job["package_version"] == "1.4.3" and job["artifact_sha256"] == "f" * 64
    assert job["delivery_run_id"] == _DELIVERY_RUN and job["delivery_status"] == "opened"
    assert job["pull_request_url"].endswith("/pull/12")
    assert job["error_code"] is None and job["next_attempt_at"] is None
    [attempt] = job["attempts"]
    assert attempt["outcome"] == "succeeded"
    assert (attempt["publishRunId"], attempt["deliveryRunId"]) == (_PUBLISH_RUN, _DELIVERY_RUN)
    assert _alerts(store) == []


def test_a_git_subscription_only_delivers_and_records_the_committed_package():
    store = FakeRegenStore()
    store.subscribe("npm", "git")
    store.publish()
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert job["status"] == "succeeded"
    pipelines.publish.assert_not_called()
    # Nothing was claimed, so the delivery takes the version the next publish would.
    assert pipelines.deliver.call_args.kwargs["regen_counter"] is None
    assert (job["package_name"], job["package_version"]) == ("@acme/widgets-sdk", "1.4.3")
    assert job["publish_status"] is None


def test_a_registry_subscription_publishes_and_opens_nothing():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert job["status"] == "succeeded"
    pipelines.deliver.assert_not_called()
    pipelines.target.assert_not_called()
    assert job["regen_counter"] == 3


def test_a_dry_run_subscription_rehearses_and_delivers_unpinned():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git", {"dryRun": True})
    store.publish()
    pipelines = _Pipelines(publish=_published(status="dry_run", dry_run=True, regen_counter=3))

    job = _run_one(store, pipelines)

    assert job["status"] == "succeeded"
    assert pipelines.publish.call_args.kwargs["dry_run"] is True
    # A dry run claimed nothing, so there is nothing to pin.
    assert pipelines.deliver.call_args.kwargs["regen_counter"] is None
    assert job["publish_status"] == "dry_run" and job["regen_counter"] is None
    assert job["options"] == {"dryRun": True}


def test_a_transient_registry_failure_is_retried_later_and_nothing_is_delivered():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    refused = _published(
        status="failed",
        error_code="sdk-publish-registry-refused",
        error_message="registry answered 503",
        retryable=True,
        regen_counter=3,
    )
    pipelines = _Pipelines(publish=refused)

    job = _run_one(store, pipelines)

    assert job["status"] == "retrying"
    assert job["next_attempt_at"] == _NOW + timedelta(seconds=BACKOFF_AFTER_FAILURE_SECONDS[0])
    assert (job["error_step"], job["error_code"]) == ("registry", "sdk-publish-registry-refused")
    assert job["publish_status"] == "failed" and job["publish_run_id"] == _PUBLISH_RUN
    # A failed publish claimed no version.
    assert job["regen_counter"] is None
    pipelines.deliver.assert_not_called()
    assert job["finished_at"] is None
    assert _alerts(store) == []


def test_a_permanent_registry_refusal_is_dead_lettered_at_once_and_alerted():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    missing = PublishError("sdk-publish-credential-missing", "No usable npm credential is stored.")
    pipelines = _Pipelines(publish=missing)

    job = _run_one(store, pipelines)

    assert job["status"] == "dead_letter"
    assert job["attempt_count"] == 1
    assert (job["error_step"], job["error_code"]) == ("registry", "sdk-publish-credential-missing")
    assert job["error_message"] == "No usable npm credential is stored."
    pipelines.deliver.assert_not_called()
    [alert] = _alerts(store)
    assert alert["jobId"] == job["id"] and alert["versionLine"] == "1.4.2"
    assert alert["error"]["code"] == "sdk-publish-credential-missing"
    assert alert["projectSlug"] == "widgets"


def test_a_lost_claim_race_on_the_registry_is_worth_retrying():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()
    race = PublishError("sdk-publish-version-unavailable", "claimed", status_code=409)

    job = _run_one(store, _Pipelines(publish=race))

    assert job["status"] == "retrying"


def test_an_unexplained_publish_fault_is_never_retried_automatically():
    """It may have come after the upload: SDK-4.1 never silently repeats a run that may have published."""
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()

    job = _run_one(store, _Pipelines(publish=RuntimeError("socket closed")))

    assert job["status"] == "dead_letter"
    assert job["error_code"] == ERROR_INTERNAL
    assert "publish history" in job["error_message"]


def test_a_git_subscription_without_a_delivery_target_is_dead_lettered_with_the_fix():
    store = FakeRegenStore()
    store.subscribe("npm", "git")
    store.publish()
    pipelines = _Pipelines(target=[None])  # a one-item side effect: resolve_target finds nothing

    job = _run_one(store, pipelines)

    assert job["status"] == "dead_letter"
    assert (job["error_step"], job["error_code"]) == ("git", ERROR_GIT_TARGET_MISSING)
    assert "Configure one" in job["error_message"]
    pipelines.deliver.assert_not_called()


def test_a_transient_git_failure_on_the_last_attempt_is_dead_lettered():
    store = FakeRegenStore()
    store.subscribe("npm", "git")
    store.publish()
    store.jobs[store.job("npm")["id"]]["attempt_count"] = MAX_ATTEMPTS - 1
    flaky = _delivered(status="failed", error_code="sdk-git-delivery-provider-unavailable", retryable=True)

    job = _run_one(store, _Pipelines(deliver=flaky))

    assert job["attempt_count"] == MAX_ATTEMPTS
    assert job["status"] == "dead_letter"
    assert len(_alerts(store)) == 1


def test_a_retry_never_publishes_a_second_version_of_one_publish():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    # Attempt 1 published 1.4.3 (counter 3), then the pull request failed.
    store.jobs[store.job("npm")["id"]].update(
        publish_run_id=_PUBLISH_RUN,
        publish_status="published",
        package_name="@acme/widgets-sdk",
        package_version="1.4.3",
        regen_counter=3,
        delivery_status="failed",
        status="retrying",
        attempt_count=1,
    )
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert job["status"] == "succeeded"
    pipelines.publish.assert_not_called()
    assert pipelines.deliver.call_args.kwargs["regen_counter"] == 3
    assert job["publish_run_id"] == _PUBLISH_RUN and job["package_version"] == "1.4.3"


def test_a_rehearsed_job_retried_after_switching_to_real_publishing_publishes():
    store = FakeRegenStore()
    sub = store.subscribe("npm", "registry_and_git", {"dryRun": True})
    store.publish()
    store.jobs[store.job("npm")["id"]].update(publish_status="dry_run", status="retrying", attempt_count=1)
    store.subscriptions[sub]["options"] = {"dryRun": False}
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert pipelines.publish.call_args.kwargs["dry_run"] is False
    assert job["publish_status"] == "published" and job["options"] == {"dryRun": False}


def test_a_job_runs_with_the_subscription_as_it_is_now():
    """A dead letter retried after its subscription was fixed runs with the fix."""
    store = FakeRegenStore()
    sub = store.subscribe("npm", "registry_and_git")
    store.publish()
    store.subscriptions[sub].update(delivery_mode="git", options={})
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    pipelines.publish.assert_not_called()
    assert job["delivery_mode"] == "git" and job["options"] == {}


@pytest.mark.parametrize(
    ("arrange", "code"),
    [
        (lambda store, sub: store.unsubscribe(sub), ERROR_UNSUBSCRIBED),
        (lambda store, sub: store.subscriptions[sub].update(active=False), ERROR_SUBSCRIPTION_DISABLED),
        (lambda store, sub: store.versions[REVISION].update(published=False), ERROR_VERSION_UNPUBLISHED),
        (lambda store, sub: store.versions.pop(REVISION), ERROR_VERSION_MISSING),
    ],
)
def test_a_job_that_must_not_run_is_cancelled_without_an_alert(arrange, code):
    """Unsubscribing stops future runs; an unpublished version is not delivered."""
    store = FakeRegenStore()
    sub = store.subscribe("npm", "registry_and_git")
    store.publish()
    arrange(store, sub)
    pipelines = _Pipelines()

    job = _run_one(store, pipelines)

    assert job["status"] == "cancelled"
    assert job["error_code"] == code and job["error_step"] is None
    pipelines.publish.assert_not_called()
    pipelines.deliver.assert_not_called()
    assert _alerts(store) == []


def test_a_revision_with_no_reconstructable_source_is_a_dead_letter_and_a_vanished_one_is_cancelled():
    store = FakeRegenStore()
    store.subscribe("npm", "git")
    store.subscribe("pypi", "git")
    store.publish()

    npm = _run_one(store, _Pipelines(source=ExportSourceError("no captured source", status_code=422)))
    pypi = _run_one(
        store, _Pipelines(source=ExportSourceError("gone", status_code=404)), ecosystem="pypi"
    )

    assert (npm["status"], npm["error_step"], npm["error_code"]) == (
        "dead_letter",
        "generate",
        ERROR_SOURCE_UNAVAILABLE,
    )
    assert (pypi["status"], pypi["error_code"]) == ("cancelled", ERROR_VERSION_MISSING)


def test_an_over_long_pipeline_code_is_bounded_rather_than_losing_the_failure():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()

    job = _run_one(store, _Pipelines(publish=PublishError("x" * 300, "refused")))

    assert job["status"] == "dead_letter" and len(job["error_code"]) == 64


def test_an_attempt_whose_claim_was_taken_away_is_not_recorded_or_alerted():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()
    row = _claim(store)
    # Reaped, retried by a person, and reclaimed by another worker since.
    store.jobs[row["id"]]["claim_token"] = "00000000-0000-4000-8000-000000000000"

    with _Pipelines(publish=PublishError("sdk-publish-credential-missing", "none")):
        assert run_claimed_job(store, row, clock=lambda: _NOW) is None
    assert _alerts(store) == []


# ============================================================================================
# The sweep
# ============================================================================================
def _sweep(store: FakeRegenStore, pipelines: Optional[_Pipelines] = None, **settings: Any) -> int:
    values = {"sdk_regen_enabled": True, "sdk_regen_batch_size": 10, "sdk_regen_lease_seconds": 1800}
    values.update(settings)
    with ExitStack() as stack:
        for key, value in values.items():
            stack.enter_context(patch(f"app.config.settings.{key}", value))
        if pipelines is not None:
            stack.enter_context(pipelines)
        return process_sdk_regen_sweep(store)


def test_one_subscriptions_failure_never_blocks_the_others_in_the_matrix():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry")
    store.publish()

    def publish(api, *, ecosystem, **_kwargs):
        if ecosystem == "npm":
            raise PublishError("sdk-publish-credential-missing", "No npm credential.")
        return _published(ecosystem="pypi", package_name="acme-widgets", package_version="1.4.3")

    pipelines = _Pipelines()
    pipelines.publish.side_effect = publish

    assert _sweep(store, pipelines) == 2
    assert store.job("npm")["status"] == "dead_letter"
    assert store.job("pypi")["status"] == "succeeded"
    assert [alert["ecosystem"] for alert in _alerts(store)] == ["npm"]


def test_a_subscriptions_publishes_are_regenerated_in_order():
    """1.4.2 waiting to retry holds back 1.4.3 for npm only — never pypi."""
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry")
    store.publish("1.4.2")
    store.publish("1.4.3", version_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd")

    def publish(api, *, ecosystem, context, **_kwargs):
        if ecosystem == "npm" and context.version_record_id == REVISION:
            return _published(status="failed", error_code="sdk-publish-registry-refused", retryable=True)
        return _published(ecosystem=ecosystem)

    pipelines = _Pipelines()
    pipelines.publish.side_effect = publish
    pipelines.load.side_effect = lambda tenant, project, version: _source().model_copy(
        update={"version_record_id": version}
    )

    assert _sweep(store, pipelines) == 3
    assert store.job("npm", "1.4.2")["status"] == "retrying"
    assert store.job("npm", "1.4.3")["status"] == "pending"
    assert store.job("pypi", "1.4.2")["status"] == "succeeded"
    assert store.job("pypi", "1.4.3")["status"] == "succeeded"


def test_the_batch_size_bounds_a_tick_and_the_rest_stay_queued():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry")
    store.publish()

    assert _sweep(store, _Pipelines(), sdk_regen_batch_size=1) == 1
    assert sorted(job["status"] for job in store.jobs.values()) == ["pending", "succeeded"]


def test_the_kill_switch_halts_the_whole_tick():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()
    pipelines = _Pipelines()

    assert _sweep(store, pipelines, sdk_regen_enabled=False) == 0
    assert store.claims == 0
    pipelines.publish.assert_not_called()


def test_a_worker_lost_mid_job_is_dead_lettered_and_alerted_never_retried():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.publish()
    row = _claim(store)
    store.jobs[row["id"]]["claimed_at"] = datetime.now(timezone.utc) - timedelta(hours=2)
    pipelines = _Pipelines()

    assert _sweep(store, pipelines) == 0
    job = store.jobs[row["id"]]
    assert (job["status"], job["error_step"], job["error_code"]) == ("dead_letter", "worker", ERROR_WORKER_LOST)
    pipelines.publish.assert_not_called()
    [alert] = _alerts(store)
    assert alert["error"]["code"] == ERROR_WORKER_LOST and alert["versionLine"] == "1.4.2"


def test_a_worker_lost_after_publishing_leaves_the_publish_on_the_job_so_a_retry_only_delivers():
    """A package on a registry cannot be taken back: the dead letter must say so, and a retry must
    deliver that version rather than publish another."""
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    row = _claim(store)

    # The worker publishes, then dies during the pull request (here: the process is killed).
    pipelines = _Pipelines(deliver=SystemExit("killed"))
    with pipelines, pytest.raises(SystemExit):
        run_claimed_job(store, row, clock=lambda: _NOW)
    job = store.jobs[row["id"]]
    assert job["status"] == "running"
    assert (job["publish_status"], job["regen_counter"]) == ("published", 3)

    # The lease sweep dead-letters it, still carrying the publish, and the alert says so.
    job["claimed_at"] = datetime.now(timezone.utc) - timedelta(hours=2)
    assert reap_lost_jobs(store, lease_seconds=60) == 1
    [alert] = _alerts(store)
    assert alert["publishStatus"] == "published" and alert["packageVersion"] == "1.4.3"

    # A person retries it: it delivers the version already published, and publishes nothing.
    job.update(status="pending", attempt_count=0, next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    retry = _Pipelines()
    finished = _run_one(store, retry)
    assert finished["status"] == "succeeded"
    retry.publish.assert_not_called()
    assert retry.deliver.call_args.kwargs["regen_counter"] == 3


def test_progress_is_not_saved_for_a_registry_only_job_or_a_failed_publish():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry_and_git")
    store.publish()
    saves: List[str] = []
    store.save_sdk_regen_job_progress = lambda job_id, token, **kw: saves.append(job_id) or 1  # type: ignore[method-assign]

    _run_one(store, _Pipelines())
    _run_one(store, _Pipelines(publish=PublishError("sdk-publish-credential-missing", "none")), "pypi")

    assert saves == []


def test_a_progress_write_that_fails_does_not_fail_the_delivery():
    store = FakeRegenStore()
    store.subscribe("npm", "registry_and_git")
    store.publish()
    store.save_sdk_regen_job_progress = MagicMock(side_effect=RuntimeError("db blip"))  # type: ignore[method-assign]

    job = _run_one(store, _Pipelines())

    assert job["status"] == "succeeded" and job["publish_status"] == "published"


def test_the_lease_sweep_and_the_claim_never_crash_a_tick():
    broken = MagicMock()
    broken.reap_stale_sdk_regen_jobs.side_effect = RuntimeError("db down")
    broken.claim_next_sdk_regen_job.side_effect = RuntimeError("db down")
    assert reap_lost_jobs(broken, lease_seconds=60) == 0
    assert _sweep(broken) == 0


def test_a_job_that_cannot_be_recorded_does_not_stop_the_next_one():
    store = FakeRegenStore()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry")
    store.publish()
    real_finish = store.finish_sdk_regen_job_attempt
    calls: List[str] = []

    def finish(job_id, token, **kwargs):
        calls.append(job_id)
        if len(calls) == 1:
            raise RuntimeError("connection reset")
        return real_finish(job_id, token, **kwargs)

    store.finish_sdk_regen_job_attempt = finish  # type: ignore[method-assign]

    assert _sweep(store, _Pipelines()) == 2
    statuses = sorted(job["status"] for job in store.jobs.values())
    # The first stays running for the lease to reap; the second was recorded.
    assert statuses == ["running", "succeeded"]


# ============================================================================================
# End to end, with the real SDK-4.1 and SDK-4.2 pipelines
# ============================================================================================
class _PublishLedger:
    """``sdk_publish_runs`` for the real publish pipeline — the counter advances with each claim."""

    def __init__(self) -> None:
        self.claimed: List[Dict[str, Any]] = []

    def next(self, *_args: Any) -> int:
        return len(self.claimed)

    def insert(self, **kwargs: Any) -> Dict[str, Any]:
        self.claimed.append(kwargs)
        return {"id": f"{_PUBLISH_RUN[:-1]}{len(self.claimed)}", **kwargs}

    def finish(self, run_id: str, tenant_id: str, **kwargs: Any) -> Dict[str, Any]:
        return {"id": run_id, **kwargs}


def _real_pipelines(ledger: _PublishLedger) -> ExitStack:
    """Patch only the stores beneath the real pipelines, never the pipelines themselves."""
    stack = ExitStack()
    deliveries: List[Dict[str, Any]] = []
    for target, value in (
        ("app.sdk_publish_pipeline.load_settings", MagicMock(return_value=_settings())),
        ("app.sdk_publish_pipeline.credential_encryption_configured", MagicMock(return_value=True)),
        (
            "app.sdk_publish_pipeline.resolve_credential",
            MagicMock(side_effect=lambda tenant, ecosystem, project_id: _credential(ecosystem)),
        ),
        ("app.sdk_publish_pipeline.db.next_sdk_publish_counter", ledger.next),
        ("app.sdk_publish_pipeline.db.insert_sdk_publish_run", ledger.insert),
        ("app.sdk_publish_pipeline.db.finish_sdk_publish_run", ledger.finish),
        (
            "app.sdk_git_delivery_pipeline.db.insert_sdk_git_delivery_run",
            lambda **kw: deliveries.append(kw) or {"id": f"{_DELIVERY_RUN[:-1]}{len(deliveries)}"},
        ),
        ("app.sdk_git_delivery_pipeline.db.finish_sdk_git_delivery_run", MagicMock(return_value={})),
        ("app.sdk_git_delivery_pipeline.db.get_tenant_repository", MagicMock(return_value=_repository())),
        (
            "app.sdk_git_delivery_pipeline.db.get_external_auth_provider_for_user",
            MagicMock(return_value={"id": "l", "provider": "github", "access_token": DEFAULT_TOKEN}),
        ),
        ("app.sdk_regen_worker.load_export_source", MagicMock(return_value=_source())),
        ("app.sdk_regen_worker.resolve_target", MagicMock(return_value=_TARGET)),
    ):
        stack.enter_context(patch(target, value))
    return stack


def _e2e_sweep(store: FakeRegenStore, github: FakeGitHub, ledger: _PublishLedger, transport) -> int:
    """One tick of the real worker over the real pipelines, with in-memory stores and remotes."""
    with _real_pipelines(ledger), patch("app.config.settings.sdk_regen_enabled", True), patch(
        "app.config.settings.sdk_regen_batch_size", 10
    ):
        return process_sdk_regen_sweep(
            store,
            publish_transport=transport,
            git_client_factory=github.client_factory,
            apiome_version="1.185.0",
        )


def _github() -> FakeGitHub:
    github = FakeGitHub()
    github.seed({"README.md": "# widgets sdk\n"})
    return github


def test_e2e_a_publish_regenerates_publishes_and_opens_a_pull_request_on_the_same_version():
    store, github, ledger = FakeRegenStore(), _github(), _PublishLedger()
    transport, uploaded = _accepting()
    store.subscribe("npm", "registry_and_git")
    store.publish()

    assert _e2e_sweep(store, github, ledger, transport) == 1

    job = store.job("npm")
    assert job["status"] == "succeeded", job["error_message"]
    # The registry received 1.4.0 …
    assert uploaded["distribution"].package_version == "1.4.0"
    assert job["publish_status"] == "published" and job["package_version"] == "1.4.0"
    # … and the pull request carries 1.4.0 too, even though the ledger has moved on to counter 1.
    assert ledger.next() == 1
    [pull] = github.open_pulls()
    package = json.loads(github.files_at(pull.head)["sdks/ts/package.json"])
    assert package["version"] == "1.4.0"
    assert job["delivery_status"] == "opened"
    assert job["pull_request_url"] == f"https://github.com/acme/widgets-sdk/pull/{pull.number}"


def test_e2e_a_transient_github_failure_retries_the_delivery_without_publishing_again():
    store, github, ledger = FakeRegenStore(), _github(), _PublishLedger()
    transport, _ = _accepting()
    upload = MagicMock(side_effect=transport)
    store.subscribe("npm", "registry_and_git")
    store.publish()
    github.fault("GET", r"/git/ref/heads/main$", 502, "Bad Gateway")

    _e2e_sweep(store, github, ledger, upload)
    job = store.job("npm")
    assert (job["status"], job["error_step"]) == ("retrying", "git")
    assert job["publish_status"] == "published" and upload.call_count == 1

    store.make_due(job["id"])
    _e2e_sweep(store, github, ledger, upload)

    job = store.job("npm")
    assert job["status"] == "succeeded"
    assert upload.call_count == 1, "a retry must never publish a second version"
    [pull] = github.open_pulls()
    assert json.loads(github.files_at(pull.head)["sdks/ts/package.json"])["version"] == "1.4.0"
    assert [attempt["outcome"] for attempt in job["attempts"]] == ["retrying", "succeeded"]
    # The failed attempt stays linked to the delivery run it wrote.
    assert job["attempts"][0]["deliveryStatus"] == "failed"


def test_e2e_a_failure_quoting_the_token_never_lands_on_the_job():
    store, github, ledger = FakeRegenStore(), _github(), _PublishLedger()
    transport, _ = _accepting()
    store.subscribe("npm", "git")
    store.publish()
    github.fault("GET", r"/widgets-sdk$", 403, f"token {DEFAULT_TOKEN} lacks access")

    _e2e_sweep(store, github, ledger, transport)

    job = store.job("npm")
    assert job["status"] == "dead_letter"
    assert DEFAULT_TOKEN not in json.dumps(job, default=str)
    assert DEFAULT_TOKEN not in json.dumps(store.webhook_deliveries, default=str)


def test_e2e_a_registry_outage_retries_and_the_other_ecosystem_ships():
    store, github, ledger = FakeRegenStore(), _github(), _PublishLedger()
    store.subscribe("npm", "registry")
    store.subscribe("pypi", "registry")
    store.publish()
    accepting, _ = _accepting()

    def transport(distribution, credential):
        if distribution.package_name == "@acme/widgets-sdk":
            raise RegistryUploadError("registry answered 503", http_status=503, retryable=True)
        return accepting(distribution, credential)

    _e2e_sweep(store, github, ledger, transport)

    assert store.job("npm")["status"] == "retrying"
    assert store.job("npm")["error_code"] == "sdk-publish-registry-refused"
    assert store.job("pypi")["status"] == "succeeded"
    assert store.job("pypi")["package_name"] == "acme-widgets"


def test_e2e_unsubscribing_stops_future_runs_without_touching_what_was_delivered():
    store, github, ledger = FakeRegenStore(), _github(), _PublishLedger()
    transport, _ = _accepting()
    sub = store.subscribe("npm", "git")
    store.publish("1.4.2")
    _e2e_sweep(store, github, ledger, transport)
    delivered = store.job("npm", "1.4.2")
    assert delivered["status"] == "succeeded"
    pulls_before = [(pull.number, pull.state) for pull in github.pulls]

    # Published again, then unsubscribed before the worker reached it.
    store.publish("1.4.3", version_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    store.unsubscribe(sub)
    writes_before = len(github.written())
    _e2e_sweep(store, github, ledger, transport)

    assert store.job("npm", "1.4.3")["status"] == "cancelled"
    assert len(github.written()) == writes_before
    assert [(pull.number, pull.state) for pull in github.pulls] == pulls_before
    # The past job keeps everything it recorded.
    assert store.jobs[delivered["id"]]["pull_request_url"] == delivered["pull_request_url"]
    # And a later publish queues nothing at all.
    assert store.publish("1.4.4", version_id="ffffffff-ffff-4fff-8fff-ffffffffffff") == []
