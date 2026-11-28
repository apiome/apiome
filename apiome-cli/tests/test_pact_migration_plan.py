"""Turning source broker documents into import records — PFX-6.7 (#6959). Pure; no HTTP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiome_cli.client.pact_migration_source import SourceBroker
from apiome_cli.pact_migration_plan import (
    Plan,
    MigrationState,
    add_integration,
    add_placements,
    add_versions,
    add_webhook,
    batches,
    embedded,
    pact_content,
    secret_references,
    source_key,
    verification_body,
)


def test_embedded_reads_both_collection_shapes() -> None:
    assert embedded({"_embedded": {"items": [{"a": 1}, "junk"]}}, "items") == [{"a": 1}]
    assert embedded({"items": [{"a": 2}]}, "other", "items") == [{"a": 2}]
    assert embedded("nope", "items") == []


def test_versions_are_queued_oldest_first_and_unnumbered_ones_noted() -> None:
    plan = Plan()
    add_versions(
        plan,
        "Billing",
        [
            {"number": "3", "createdAt": "2025-03-03"},
            {"number": "1"},
            {"createdAt": "x"},
            {"number": "2", "createdAt": "2025-03-02"},
        ],
    )
    assert [record["number"] for _, record in plan.records["version"]] == [
        "1",
        "2",
        "3",
    ]
    assert plan.findings[0].detail.startswith(
        "the source returned a version without a number"
    )


def test_an_integration_queues_each_pact_once_and_each_result_once() -> None:
    plan = Plan()
    result = {
        "verifiedAt": "2025-03-02",
        "_links": {"self": {"href": "https://b/pact-version/x/verification-results/2"}},
    }
    rows = [
        {
            "consumer": {"version": {"number": v}},
            "pact": {"_links": {"self": {"href": f"https://b/pact/{v}"}}},
            "verificationResult": result,
        }
        for v in ("1", "2")
    ]
    rows.append(
        {
            "consumer": {"version": {"number": "1"}},
            "pact": {"_links": {"self": {"href": "https://b/pact/1"}}},
        }
    )
    to_fetch = add_integration(plan, "Billing", "Ledger", rows)
    assert [key for key, _ in plan.records["pact"]] == [
        "pact:Ledger/Billing/1",
        "pact:Ledger/Billing/2",
    ]
    assert [key for key, _ in plan.records["verification"]] == [
        "verification:Ledger/Billing/1/2"
    ]
    assert to_fetch["verification:Ledger/Billing/1/2"].endswith(
        "/verification-results/2"
    )


def test_documents_lose_the_source_decoration() -> None:
    assert pact_content(
        {"interactions": [], "_links": {}, "_embedded": {}, "createdAt": "x"}
    ) == {"interactions": []}
    body = verification_body(
        {"success": False, "providerVersion": "7", "testResults": [], "_links": {}}
    )
    assert body == {
        "success": False,
        "providerApplicationVersion": "7",
        "testResults": [],
    }


def test_placements_without_a_version_are_noted() -> None:
    plan = Plan()
    add_placements(
        plan,
        "deployment",
        "prod",
        [
            {
                "applicationInstance": "eu",
                "_embedded": {
                    "pacticipant": {"name": "Ledger"},
                    "version": {"number": "7"},
                },
            },
            {"_embedded": {"pacticipant": {"name": "Ledger"}}},
        ],
    )
    assert [key for key, _ in plan.records["deployment"]] == [
        "deployment:Ledger/7/prod/eu"
    ]
    assert "without its pacticipant or version" in plan.findings[0].detail


def test_a_webhook_whose_events_apiome_never_fires_is_not_imported() -> None:
    plan = Plan()
    add_webhook(
        plan,
        "https://b/webhooks/u1",
        {
            "events": [{"name": "pactflow_only"}],
            "request": {"method": "POST", "url": "https://x"},
        },
    )
    assert plan.records["webhook"] == []
    assert any("none of its events" in f.detail for f in plan.findings)


def test_a_redacted_secret_is_sent_for_apiome_to_keep_waiting() -> None:
    """PFX-8.15: the redacted value goes as it is; Apiome makes a secret waiting for its value."""
    plan = Plan()
    add_webhook(
        plan,
        "https://b/webhooks/u1",
        {
            "request": {
                "method": "POST",
                "url": "https://x",
                "username": "ci",
                "password": "**********",
                "headers": {"Authorization": "**********", "Accept": "application/json"},
            },
            "enabled": True,
        },
    )
    ((_, record),) = plan.records["webhook"]
    request = record["webhook"]["request"]
    assert request["password"] == "**********"
    assert request["headers"] == {"Authorization": "**********", "Accept": "application/json"}
    assert record["webhook"]["enabled"] is True  # Apiome turns it off while it waits
    assert record["uuid"] == "u1"
    detail = plan.findings[0].detail
    assert "header Authorization" in detail and "basic-auth password" in detail
    assert "Contracts → Settings → Secrets" in detail


def test_secret_references_are_found_once_each() -> None:
    assert secret_references(
        {"a": "${user.one} ${user.two}", "b": ["${user.one}", "${pactbroker.x}"]}
    ) == ["one", "two"]


def test_source_keys_name_what_identifies_a_record() -> None:
    assert (
        source_key(
            {
                "kind": "release",
                "pacticipant": "L",
                "version": "7",
                "environment": "prod",
            }
        )
        == "release:L/7/prod/"
    )
    assert source_key({"kind": "webhook", "uuid": "u1"}) == "webhook:u1"


def test_batches_respect_the_record_and_byte_limits() -> None:
    items = [(str(i), {"kind": "pact", "content": "x" * 100}) for i in range(5)]
    assert [len(b) for b in batches(items, max_records=2, max_bytes=10_000)] == [
        2,
        2,
        1,
    ]
    assert [len(b) for b in batches(items, max_records=100, max_bytes=300)] == [2, 2, 1]
    assert [len(b) for b in batches(items[:1], max_records=100, max_bytes=1)] == [
        1
    ]  # too big still goes, alone


def test_the_state_file_round_trips_and_refuses_another_migration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    state = MigrationState.load(path, source="https://a", target="acme")
    state.done.update({"pact:L/B/1", "version:B/1"})
    state.save()
    assert MigrationState.load(path, source="https://a", target="acme").done == {
        "pact:L/B/1",
        "version:B/1",
    }
    assert (
        MigrationState.load(path, source="https://a", target="acme", restart=True).done
        == set()
    )
    with pytest.raises(ValueError, match="not this one"):
        MigrationState.load(path, source="https://a", target="other")
    path.write_text("not json")
    with pytest.raises(ValueError, match="not a migration state file"):
        MigrationState.load(path, source="https://a", target="acme")
    path.write_text(json.dumps({"done": "x"}))
    with pytest.raises(ValueError, match="not a migration state file"):
        MigrationState.load(path, source="https://a", target="acme")


def test_links_are_followed_on_the_source_host_only() -> None:
    with SourceBroker("https://broker.example.com/base/", token="t") as broker:
        assert broker.base_url == "https://broker.example.com/base"
        assert (
            broker.url("/pacticipants")
            == "https://broker.example.com/base/pacticipants"
        )
        assert (
            broker.url("http://internal:9292/base/x?page=2")
            == "https://broker.example.com/base/x?page=2"
        )
