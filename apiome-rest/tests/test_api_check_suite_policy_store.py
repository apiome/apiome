"""The API change check suite policy store — GNC-3.1 (#4740).

The suite resolves its policy on every evaluation, so the store's two promises are pinned here:
resolution is project → tenant → documented default, and an unreadable policy never stops the
suite — it stands in the default and says so (``degraded``).
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from app import api_check_suite_policy_store as store
from app.api_check_suite import (
    DEFAULT_POLICY,
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_PROJECT,
    POLICY_SOURCE_TENANT,
    REQUIREMENT_OFF,
    REQUIREMENT_REQUIRED,
    CheckSuitePolicyError,
    policy_fingerprint,
)
from tests.fake_suite_db import FakeSuiteDb

TENANT = "3e4f5a60-6666-4aaa-8bbb-000000000001"
PROJECT = "3e4f5a60-6666-4aaa-8bbb-000000000002"
ALICE = "3e4f5a60-6666-4aaa-8bbb-000000000101"


@pytest.fixture
def fake(monkeypatch) -> FakeSuiteDb:
    """An empty store beneath the policy store."""
    database = FakeSuiteDb()
    monkeypatch.setattr(store, "db", database)
    return database


def test_nothing_saved_reads_as_the_documented_default(fake):
    policy = store.load_policy(TENANT, PROJECT)
    assert policy.source == POLICY_SOURCE_DEFAULT
    assert policy.policy == DEFAULT_POLICY
    assert policy.content_fingerprint == policy_fingerprint(DEFAULT_POLICY)
    assert policy.degraded is False


def test_a_blank_tenant_reads_the_default_without_asking_the_database(fake, monkeypatch):
    def forbidden(*_args: Any) -> None:
        raise AssertionError("must not be read")

    monkeypatch.setattr(fake, "get_check_suite_policy", forbidden)
    assert store.load_policy("").source == POLICY_SOURCE_DEFAULT


def test_the_tenant_policy_governs_until_a_project_overrides_it(fake):
    store.save_policy(TENANT, body={"components": {"contract": "required"}}, actor_id=ALICE)
    tenant = store.load_policy(TENANT, PROJECT)
    assert tenant.source == POLICY_SOURCE_TENANT
    assert tenant.policy.requirement("contract") == REQUIREMENT_REQUIRED
    assert tenant.updated_by == ALICE

    store.save_policy(TENANT, project_id=PROJECT, body={"components": {"sdk": "off"}})
    project = store.load_policy(TENANT, PROJECT)
    assert project.source == POLICY_SOURCE_PROJECT
    assert project.policy.requirement("sdk") == REQUIREMENT_OFF
    # An override is a whole policy, not a patch over the tenant's.
    assert project.policy.requirement("contract") != REQUIREMENT_REQUIRED
    # The tenant-wide read never sees a project's override.
    assert store.load_policy(TENANT).source == POLICY_SOURCE_TENANT


def test_saving_stores_the_canonical_body_and_its_fingerprint(fake):
    saved = store.save_policy(TENANT, body={"requiredForPublish": True})
    row = fake.suite_policies[(TENANT, None)]
    assert row["policy"]["requiredForPublish"] is True
    assert set(row["policy"]["components"]) == {"lint", "breaking", "consumers", "contract", "sdk"}
    assert row["content_fingerprint"] == saved.content_fingerprint


def test_an_invalid_body_is_refused_before_anything_is_stored(fake):
    with pytest.raises(CheckSuitePolicyError):
        store.save_policy(TENANT, body={"components": {"lint": "sometimes"}})
    assert fake.suite_policies == {}


def test_a_write_that_returns_no_row_is_an_error_not_a_silent_success(fake, monkeypatch):
    monkeypatch.setattr(fake, "upsert_check_suite_policy", lambda **_kwargs: None)
    with pytest.raises(RuntimeError):
        store.save_policy(TENANT, body={})


def test_an_unreadable_store_degrades_to_the_default_and_says_so(fake, monkeypatch):
    def broken(*_args: Any) -> Optional[dict]:
        raise RuntimeError("db down")

    monkeypatch.setattr(fake, "get_check_suite_policy", broken)
    policy = store.load_policy(TENANT, PROJECT)
    assert policy.source == POLICY_SOURCE_DEFAULT
    assert policy.degraded is True


def test_a_body_this_release_cannot_read_degrades_but_keeps_its_scope(fake):
    fake.suite_policies[(TENANT, PROJECT)] = {
        "id": "row-1",
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "policy": {"components": {"lint": "strictest"}},
        "content_fingerprint": "sha256:future",
        "updated_by": ALICE,
    }
    policy = store.load_policy(TENANT, PROJECT)
    assert policy.degraded is True
    assert policy.source == POLICY_SOURCE_PROJECT
    assert policy.policy_id == "row-1"
    assert policy.policy == DEFAULT_POLICY


def test_clearing_drops_exactly_one_scope(fake):
    store.save_policy(TENANT, body={"components": {"sdk": "required"}})
    store.save_policy(TENANT, project_id=PROJECT, body={})
    assert store.clear_policy(TENANT, project_id=PROJECT) is True
    assert store.clear_policy(TENANT, project_id=PROJECT) is False
    assert store.load_policy(TENANT, PROJECT).source == POLICY_SOURCE_TENANT
    assert store.clear_policy(TENANT) is True
    assert store.load_policy(TENANT, PROJECT).source == POLICY_SOURCE_DEFAULT


def test_the_audit_payload_carries_the_whole_body(fake):
    saved = store.save_policy(TENANT, body={"requiredForPublish": True})
    detail = store.audit_detail(saved)
    assert detail["contentFingerprint"] == saved.content_fingerprint
    assert detail["policy"]["requiredForPublish"] is True
    assert detail["source"] == POLICY_SOURCE_TENANT
