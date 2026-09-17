"""Store rules for provider checks — GNC-2.2 (#4738).

What the HTTP surface cannot isolate: that a verdict is recorded *before* it is published and
survives a provider that refuses it, that the same verdict twice is one check rather than two, that
an identical publish never reaches the provider a second time, that a repository token is resolved
server-side and never stored, and that a webhook's ref update resolves only to bindings that are
still authorized.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from app import comment_store, draft_binding_store, git_import_routes, provider_check_store
from app.provider_check_store import CheckFilters
from app.provider_checks import (
    CODE_BINDING_NOT_FOUND,
    CODE_BINDING_RELEASED,
    CODE_CHECK_NOT_FOUND,
    CODE_INVALID_NAME,
    CODE_PROJECT_NOT_FOUND,
    CODE_PROVIDER_FORBIDDEN,
    CODE_VERSION_NOT_FOUND,
    DEFAULT_CHECK_NAME,
    ORIGIN_API,
    ORIGIN_WEBHOOK,
    OUTCOME_DISPATCHED,
    OUTCOME_FAILED,
    OUTCOME_SUPPRESSED,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    CheckRunUpsert,
    ProviderCheckValidationError,
)
from tests.fake_check_db import FakeCheckDb

TENANT = "8d2e3f40-2222-4aaa-8bbb-000000000001"
PROJECT = "8d2e3f40-2222-4aaa-8bbb-000000000002"
VERSION = "8d2e3f40-2222-4aaa-8bbb-000000000010"
OTHER_VERSION = "8d2e3f40-2222-4aaa-8bbb-000000000011"
REPOSITORY = "8d2e3f40-2222-4aaa-8bbb-000000000020"
BINDING = "8d2e3f40-2222-4aaa-8bbb-000000000030"
OTHER_BINDING = "8d2e3f40-2222-4aaa-8bbb-000000000031"
ALICE = "8d2e3f40-2222-4aaa-8bbb-000000000101"

COMMIT_ONE = "1111111111111111111111111111111111111111"
COMMIT_TWO = "2222222222222222222222222222222222222222"
TOKEN = "ghp_a_real_looking_repository_token_0123456789"


class Provider:
    """An in-memory provider API the adapters publish to.

    Attributes:
        status: The status code to answer with.
        payload: The JSON body to answer with.
        error: An :class:`httpx.HTTPError` raised instead of answering.
        calls: One entry per request: ``(method, url)``.
    """

    def __init__(self) -> None:
        self.status = 201
        self.payload: Dict[str, Any] = {"id": 4242, "html_url": "https://github.com/x/runs/4242"}
        self.error: Optional[Exception] = None
        self.calls: List[Any] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, recording what was asked."""
        self.calls.append((request.method, str(request.url)))
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.payload)

    def factory(self):
        """Return a client factory bound to this provider."""

        def build() -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(self.handle))

        return build


@pytest.fixture
def provider() -> Provider:
    """A provider API that answers in memory."""
    return Provider()


@pytest.fixture
def fake(monkeypatch) -> FakeCheckDb:
    """A seeded store beneath :mod:`app.provider_check_store`, with one bound draft."""
    store = FakeCheckDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_version(PROJECT, OTHER_VERSION, "1.1.0")
    store.add_repository(
        TENANT, REPOSITORY, clone_url="https://github.com/acme/specs", created_by=ALICE
    )
    store.add_member(ALICE, "Alice", "alice@example.com")
    _bind(store, BINDING, VERSION)
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(draft_binding_store, "db", store)
    monkeypatch.setattr(provider_check_store, "db", store)
    monkeypatch.setattr(
        git_import_routes, "resolve_stored_git_token", lambda *a, **k: TOKEN
    )
    return store


def _bind(store: FakeCheckDb, binding_id: str, version_id: str, ref: str = "main") -> None:
    """Seed one active binding directly, as GNC-2.1's bind would have left it."""
    now = store._tick()
    store.bindings[binding_id] = {
        "id": binding_id,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": version_id,
        "repository_id": REPOSITORY,
        "provider": "github",
        "repo_full_name": "acme/specs",
        "repo_url": "https://github.com/acme/specs",
        "ref": ref,
        "path": "spec",
        "commit_sha": COMMIT_ONE,
        "source_digest": "sha256:abc",
        "synchronized_at": now,
        "created_by": ALICE,
        "created_at": now,
        "updated_at": now,
        "released_at": None,
        "released_by": None,
        "release_reason": None,
    }


def _record(fake: FakeCheckDb, provider: Provider, **kwargs: Any) -> Any:
    """Record a verdict through the store, defaulting to a published failure."""
    request = CheckRunUpsert(**{"state": STATE_FAIL, "title": "2 breaking changes", **kwargs})
    return provider_check_store.record_check(
        TENANT, ALICE, "pets", "1.0.0", request, client_factory=provider.factory()
    )


def _code_of(call) -> str:
    """Run a store call that must refuse, and return the refusal code."""
    with pytest.raises(ProviderCheckValidationError) as refused:
        call()
    return refused.value.code


def _actions(fake: FakeCheckDb) -> List[str]:
    """The workflow-audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------------------------


def test_a_verdict_is_recorded_against_the_bindings_commit_by_default(fake, provider):
    detail = _record(fake, provider)
    check = detail.check
    assert check.state == STATE_FAIL
    assert check.commit_sha == COMMIT_ONE
    assert check.name == DEFAULT_CHECK_NAME
    assert check.provider == "github"
    assert check.repo_full_name == "acme/specs"
    assert check.ref == "main"
    assert check.version_label == "1.0.0"
    assert check.origin == ORIGIN_API
    assert check.attempt == 1
    assert check.completed_at is not None


def test_a_pending_verdict_has_no_completion_time(fake, provider):
    detail = _record(fake, provider, state=STATE_PENDING)
    assert detail.check.state == STATE_PENDING
    assert detail.check.completed_at is None


def test_a_verdict_can_name_a_commit_other_than_the_bindings(fake, provider):
    detail = _record(fake, provider, commit_sha=COMMIT_TWO)
    assert detail.check.commit_sha == COMMIT_TWO


def test_the_same_verdict_twice_is_one_check(fake, provider):
    first = _record(fake, provider)
    second = _record(fake, provider, state=STATE_PASS)
    assert second.check.id == first.check.id
    assert second.check.state == STATE_PASS
    assert len(fake.check_runs) == 1
    # The attempt counter does not move: this is the same run reporting a later state.
    assert second.check.attempt == 1


def test_a_rerun_advances_the_attempt_counter_on_the_same_row(fake, provider):
    first = _record(fake, provider)
    second = _record(fake, provider, rerun=True)
    assert second.check.id == first.check.id
    assert second.check.attempt == 2


def test_a_different_name_on_the_same_commit_is_a_different_check(fake, provider):
    _record(fake, provider)
    other = _record(fake, provider, name="apiome/lint")
    assert len(fake.check_runs) == 2
    assert other.check.name == "apiome/lint"


def test_a_different_commit_under_the_same_name_is_a_different_check(fake, provider):
    _record(fake, provider)
    _record(fake, provider, commit_sha=COMMIT_TWO)
    assert len(fake.check_runs) == 2


def test_recording_writes_an_audit_row_for_the_verdict_and_for_the_publish(fake, provider):
    _record(fake, provider)
    assert _actions(fake) == ["check.recorded", "check.published"]


def test_an_invalid_check_name_is_refused_before_anything_is_written(fake, provider):
    assert _code_of(lambda: _record(fake, provider, name="has space")) == CODE_INVALID_NAME
    assert fake.check_runs == {}
    assert provider.calls == []


# ---------------------------------------------------------------------------------------------
# What a check may be recorded against
# ---------------------------------------------------------------------------------------------


def test_an_unbound_version_has_nothing_to_report_a_check_against(fake, provider):
    request = CheckRunUpsert(state=STATE_PASS)
    code = _code_of(
        lambda: provider_check_store.record_check(
            TENANT, ALICE, "pets", "1.1.0", request, client_factory=provider.factory()
        )
    )
    assert code == CODE_BINDING_NOT_FOUND


def test_a_binding_whose_registration_is_gone_can_publish_nothing(fake, provider):
    fake.bindings[BINDING]["repository_id"] = None
    assert _code_of(lambda: _record(fake, provider)) == CODE_BINDING_RELEASED
    assert fake.check_runs == {}


def test_a_released_binding_is_history_and_takes_no_checks(fake, provider):
    fake.bindings[BINDING]["released_at"] = fake._tick()
    assert _code_of(lambda: _record(fake, provider)) == CODE_BINDING_NOT_FOUND


def test_an_unknown_project_or_version_is_refused(fake, provider):
    request = CheckRunUpsert()
    assert (
        _code_of(
            lambda: provider_check_store.record_check(TENANT, ALICE, "ghosts", "1.0.0", request)
        )
        == CODE_PROJECT_NOT_FOUND
    )
    assert (
        _code_of(
            lambda: provider_check_store.record_check(TENANT, ALICE, "pets", "9.9.9", request)
        )
        == CODE_VERSION_NOT_FOUND
    )


def test_a_binding_released_between_the_read_and_the_write_refuses_rather_than_writes(
    fake, provider
):
    def release() -> None:
        fake.bindings[BINDING]["released_at"] = fake._tick()

    fake.interleave = release
    assert _code_of(lambda: _record(fake, provider)) == CODE_BINDING_RELEASED
    assert fake.check_runs == {}


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def test_a_recorded_verdict_is_published_and_the_attempt_is_ledgered(fake, provider):
    detail = _record(fake, provider)
    assert len(provider.calls) == 1
    assert detail.deliveries[0].outcome == OUTCOME_DISPATCHED
    assert detail.deliveries[0].status_code == 201
    assert detail.deliveries[0].external_id == "4242"


def test_a_dispatch_writes_the_providers_id_back_so_the_next_publish_moves_it(fake, provider):
    _record(fake, provider, state=STATE_PENDING)
    assert provider.calls[0][0] == "POST"
    _record(fake, provider, state=STATE_PASS)
    # GitHub PATCHes the run it already created rather than stacking a second on the pull request.
    assert provider.calls[1][0] == "PATCH"
    assert provider.calls[1][1].endswith("/check-runs/4242")


def test_recording_survives_a_provider_that_refuses_the_publish(fake, provider):
    provider.status = 403
    provider.payload = {"message": "Resource not accessible"}
    detail = _record(fake, provider)
    # The verdict stands: a check that was recorded and not published is evidence; losing it
    # because a provider had a bad day would be worse than not showing it.
    assert detail.check.state == STATE_FAIL
    assert detail.deliveries[0].outcome == OUTCOME_FAILED
    assert detail.deliveries[0].error_code == CODE_PROVIDER_FORBIDDEN
    assert detail.check.last_publish_outcome == OUTCOME_FAILED


def test_recording_survives_a_provider_that_cannot_be_reached(fake, provider):
    provider.error = httpx.ConnectError("no route to host")
    detail = _record(fake, provider)
    assert detail.check.state == STATE_FAIL
    assert detail.deliveries[0].outcome == OUTCOME_FAILED


def test_publish_false_records_the_verdict_and_sends_nothing(fake, provider):
    detail = _record(fake, provider, publish=False)
    assert detail.check.state == STATE_FAIL
    assert provider.calls == []
    assert detail.deliveries == []


def test_republishing_an_identical_verdict_does_not_reach_the_provider_twice(fake, provider):
    _record(fake, provider, state=STATE_PENDING)
    assert len(provider.calls) == 1
    row = next(iter(fake.check_runs.values()))
    # The same verdict again. The ledger is consulted before the adapter, so the provider is not
    # called at all — being idempotent only in our own tables would still cost the provider a
    # request for every redelivery.
    result = provider_check_store.publish_check(
        fake, fake._check_view(row), repository_id=REPOSITORY, client_factory=provider.factory()
    )
    assert result.outcome == OUTCOME_DISPATCHED
    assert result.ledgered is False
    assert len(provider.calls) == 1
    assert len(fake.check_deliveries) == 1


def test_a_verdict_that_failed_to_publish_is_tried_again(fake, provider):
    provider.status = 503
    _record(fake, provider, state=STATE_PENDING)
    assert len(provider.calls) == 1
    row = next(iter(fake.check_runs.values()))
    provider.status = 201
    # A failure is exactly the case where trying again is right; only a dispatch stops a retry.
    result = provider_check_store.publish_check(
        fake, fake._check_view(row), repository_id=REPOSITORY, client_factory=provider.factory()
    )
    assert result.outcome == OUTCOME_DISPATCHED
    assert len(provider.calls) == 2


def test_a_later_state_of_the_same_check_is_a_new_verdict_and_is_published(fake, provider):
    _record(fake, provider, state=STATE_PENDING)
    _record(fake, provider, state=STATE_PASS)
    # Same check, different verdict: the pull request must see it move.
    assert len(provider.calls) == 2
    assert len(fake.check_deliveries) == 2


def test_a_deployment_with_checks_switched_off_records_but_never_publishes(
    fake, provider, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "provider_checks_enabled", False)
    detail = _record(fake, provider)
    assert detail.check.state == STATE_FAIL
    assert provider.calls == []
    assert detail.deliveries[0].outcome == OUTCOME_SUPPRESSED
    assert detail.deliveries[0].error_code == "check-publishing-disabled"


def test_a_repository_with_no_stored_credential_suppresses_rather_than_tries_anonymously(
    fake, provider, monkeypatch
):
    monkeypatch.setattr(git_import_routes, "resolve_stored_git_token", lambda *a, **k: None)
    detail = _record(fake, provider)
    assert provider.calls == []
    assert detail.deliveries[0].outcome == OUTCOME_SUPPRESSED
    assert detail.deliveries[0].error_code == CODE_PROVIDER_FORBIDDEN


def test_a_provider_with_no_adapter_suppresses_the_publish(fake, provider):
    fake.bindings[BINDING]["provider"] = "gitea"
    detail = _record(fake, provider)
    assert provider.calls == []
    assert detail.deliveries[0].outcome == OUTCOME_SUPPRESSED
    assert detail.deliveries[0].error_code == "check-provider-unsupported"


def test_no_publish_attempt_ever_stores_a_credential(fake, provider):
    provider.status = 403
    provider.payload = {"message": f"token {TOKEN} rejected"}
    _record(fake, provider)
    stored = "".join(
        str(value)
        for row in fake.check_deliveries.values()
        for value in row.values()
    )
    assert TOKEN not in stored
    assert "[repository-token-redacted]" in stored


def test_no_check_row_has_a_field_a_credential_could_occupy(fake, provider):
    detail = _record(fake, provider)
    fields = set(detail.check.model_dump()) | set(detail.deliveries[0].model_dump())
    assert not {field for field in fields if "token" in field or "secret" in field}


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def test_a_projects_checks_come_back_newest_first(fake, provider):
    _record(fake, provider, name="apiome/one")
    _record(fake, provider, name="apiome/two")
    checks, _version = provider_check_store.list_checks(TENANT, "pets", CheckFilters())
    assert [check.name for check in checks] == ["apiome/two", "apiome/one"]


def test_the_list_narrows_by_version_commit_and_state(fake, provider):
    _record(fake, provider, name="apiome/one", state=STATE_PASS)
    _record(fake, provider, name="apiome/two", state=STATE_FAIL, commit_sha=COMMIT_TWO)

    by_state, _ = provider_check_store.list_checks(
        TENANT, "pets", CheckFilters(state=STATE_FAIL)
    )
    assert [check.name for check in by_state] == ["apiome/two"]

    by_commit, _ = provider_check_store.list_checks(
        TENANT, "pets", CheckFilters(commit_sha=COMMIT_ONE)
    )
    assert [check.name for check in by_commit] == ["apiome/one"]

    by_version, version_id = provider_check_store.list_checks(
        TENANT, "pets", CheckFilters(version="1.0.0")
    )
    assert len(by_version) == 2
    assert version_id == VERSION


def test_a_check_of_another_project_is_not_readable_through_this_one(fake, provider):
    detail = _record(fake, provider)
    fake.add_project(TENANT, "8d2e3f40-2222-4aaa-8bbb-000000000003", "birds")
    assert (
        _code_of(lambda: provider_check_store.get_check(TENANT, "birds", detail.check.id))
        == CODE_CHECK_NOT_FOUND
    )


def test_reading_a_check_brings_its_publish_attempts_with_it(fake, provider):
    recorded = _record(fake, provider)
    detail = provider_check_store.get_check(TENANT, "pets", recorded.check.id)
    assert detail.check.id == recorded.check.id
    assert [delivery.outcome for delivery in detail.deliveries] == [OUTCOME_DISPATCHED]


# ---------------------------------------------------------------------------------------------
# Resolving a provider event to an authorized binding
# ---------------------------------------------------------------------------------------------


def test_a_ref_update_resolves_to_the_bindings_of_that_ref(fake):
    rows = provider_check_store.resolve_authorized_bindings(
        fake, repository_id=REPOSITORY, ref="main"
    )
    assert [row["id"] for row in rows] == [BINDING]
    # Everything a publish is addressed by comes back with it.
    assert rows[0]["provider"] == "github"
    assert rows[0]["repo_full_name"] == "acme/specs"


def test_a_ref_update_accepts_the_spelling_a_delivery_actually_sends(fake):
    rows = provider_check_store.resolve_authorized_bindings(
        fake, repository_id=REPOSITORY, ref="refs/heads/main"
    )
    assert [row["id"] for row in rows] == [BINDING]


@pytest.mark.parametrize("ref", ["", "   ", "other"])
def test_a_ref_nothing_is_bound_to_resolves_to_nothing(fake, ref):
    assert provider_check_store.resolve_authorized_bindings(
        fake, repository_id=REPOSITORY, ref=ref
    ) == []


def test_a_released_binding_is_not_an_authorized_target(fake):
    fake.bindings[BINDING]["released_at"] = fake._tick()
    assert provider_check_store.resolve_authorized_bindings(
        fake, repository_id=REPOSITORY, ref="main"
    ) == []


def test_a_binding_whose_registration_is_gone_is_not_an_authorized_target(fake):
    # The registration *is* the credential a verdict would be published with, so without one the
    # binding is not authorized, however live it looks.
    fake.bindings[BINDING]["repository_id"] = None
    assert provider_check_store.resolve_authorized_bindings(
        fake, repository_id=REPOSITORY, ref="main"
    ) == []


# ---------------------------------------------------------------------------------------------
# Seeding from a delivery
# ---------------------------------------------------------------------------------------------


def _seed(fake: FakeCheckDb, provider: Provider, **kwargs: Any) -> int:
    """Seed pending checks for a ref update, as the webhook path does."""
    return provider_check_store.seed_checks_for_ref_update(
        fake,
        **{
            "repository_id": REPOSITORY,
            "ref": "refs/heads/main",
            "commit_sha": COMMIT_TWO,
            "delivery_id": "delivery-1",
            "client_factory": provider.factory(),
            **kwargs,
        },
    )


def test_a_delivery_announces_a_pending_check_on_each_bound_draft(fake, provider):
    assert _seed(fake, provider) == 1
    check = next(iter(fake.check_runs.values()))
    assert check["state"] == STATE_PENDING
    assert check["commit_sha"] == COMMIT_TWO
    assert check["name"] == DEFAULT_CHECK_NAME
    assert check["origin"] == ORIGIN_WEBHOOK
    assert check["delivery_id"] == "delivery-1"
    assert check["created_by"] is None
    assert len(provider.calls) == 1


def test_a_second_draft_bound_to_the_same_ref_gets_its_own_check(fake, provider):
    _bind(fake, OTHER_BINDING, OTHER_VERSION)
    assert _seed(fake, provider) == 2
    assert len(fake.check_runs) == 2


def test_a_redelivery_of_the_same_push_seeds_one_check_and_publishes_once(fake, provider):
    _seed(fake, provider)
    _seed(fake, provider)
    assert len(fake.check_runs) == 1
    # Both the check row and the publish ledger collapse the redelivery.
    assert len(fake.check_deliveries) == 1


def test_a_delivery_records_the_pull_request_it_named(fake, provider):
    _seed(fake, provider, pr_number=7)
    assert next(iter(fake.check_runs.values()))["pr_number"] == 7


def test_a_delivery_for_a_ref_nothing_is_bound_to_seeds_nothing(fake, provider):
    assert _seed(fake, provider, ref="refs/heads/other") == 0
    assert fake.check_runs == {}
    assert provider.calls == []


def test_a_delivery_with_no_commit_seeds_nothing(fake, provider):
    assert _seed(fake, provider, commit_sha="") == 0


def test_seeding_can_be_switched_off_without_switching_off_publishing(
    fake, provider, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "provider_checks_webhook_seed_enabled", False)
    assert _seed(fake, provider) == 0
    assert fake.check_runs == {}


def test_a_seeded_check_links_back_when_a_base_url_is_configured(fake, provider, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "provider_checks_details_base_url", "https://app.apiome.dev/")
    _seed(fake, provider)
    check = next(iter(fake.check_runs.values()))
    assert check["details_url"] == (
        f"https://app.apiome.dev/ade/projects/{PROJECT}/versions/{VERSION}"
    )


def test_a_seeded_check_has_no_link_rather_than_a_broken_one(fake, provider, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "provider_checks_details_base_url", "")
    _seed(fake, provider)
    assert next(iter(fake.check_runs.values()))["details_url"] == ""


def test_seeding_survives_a_provider_that_refuses_every_publish(fake, provider):
    provider.status = 500
    assert _seed(fake, provider) == 1
    assert next(iter(fake.check_runs.values()))["state"] == STATE_PENDING
    assert next(iter(fake.check_deliveries.values()))["outcome"] == OUTCOME_FAILED
