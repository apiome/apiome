"""CDN provider persistence and credential vault — Slate 10.2 (private-suite#120).

Exercises :mod:`app.slate_cdn_store` against the scripted fake connection the cache-store suite
uses, and :mod:`app.slate_cdn_crypto` against a real key map. Asserted:

* **Attaching a provider attaches the edge, in the same transaction.** The provider row, the
  cache policy's ``edge_attached`` / ``edge_provider`` and the ``cdn`` audit entry commit together
  or not at all.
* **Every read is tenant-scoped.**
* **Credentials round-trip only through the vault** — under its own magic, so another vault's
  key cannot open them.
"""

from __future__ import annotations

import base64
import json
import os

import pytest

from app import slate_cdn_crypto
from app.config import settings
from app.slate_cdn_store import (
    SlateCdnStoreError,
    delete_provider,
    get_provider,
    list_dispatches,
    record_dispatch,
    save_provider,
    verified_hosts,
)
from tests.test_slate_cache_store import ENV, SITE, TENANT, db_with


def save(db, *, sealed=(b"cipher", 1), **overrides):
    """Call save_provider with Cloudflare defaults."""
    kwargs = {
        "tenant_id": TENANT,
        "site_id": SITE,
        "environment_id": ENV,
        "provider": "cloudflare",
        "target": "0" * 32,
        "auth_header_name": None,
        "sealed_credential": sealed,
        "purge_on_deploy": True,
        "actor_id": "user-1",
        "actor_name": "ken@example.com",
    }
    kwargs.update(overrides)
    return save_provider(db, **kwargs)


class TestSaveProvider:
    def test_a_new_credential_upserts_and_attaches_the_edge_in_one_commit(self) -> None:
        db, conn = db_with({"id": "p-1", "provider": "cloudflare", "inserted": True})
        written = save(db)
        assert written["id"] == "p-1"
        assert "inserted" not in written
        upsert, edge, audit = conn.statements
        assert "INSERT INTO apiome.slate_cdn_providers" in upsert[0]
        assert "ON CONFLICT (environment_id) DO UPDATE" in upsert[0]
        assert upsert[1][6] == b"cipher" and upsert[1][7] == 1
        assert "edge_attached = TRUE" in edge[0]
        assert edge[1][3] == "cloudflare"
        assert "'cdn'" in audit[0]
        assert audit[1][5] == "CDN provider attached: cloudflare"
        assert "credential replaced" in audit[1][6]
        assert conn.commits == 1 and conn.rollbacks == 0

    def test_an_update_reports_updated_rather_than_attached(self) -> None:
        db, conn = db_with({"id": "p-1", "inserted": False})
        save(db)
        assert conn.statements[2][1][5] == "CDN provider updated: cloudflare"

    def test_keeping_the_credential_updates_without_touching_it(self) -> None:
        db, conn = db_with({"id": "p-1"})
        save(db, sealed=None, purge_on_deploy=False)
        update = conn.statements[0]
        assert update[0].startswith("UPDATE apiome.slate_cdn_providers")
        assert "credential_ciphertext" not in update[0]
        assert "tenant_id = %s::uuid" in update[0]
        assert "credential kept" in conn.statements[2][1][6]
        assert "purge on deploy off" in conn.statements[2][1][6]

    def test_keeping_a_credential_that_does_not_exist_rolls_back(self) -> None:
        db, conn = db_with(None)
        with pytest.raises(SlateCdnStoreError) as caught:
            save(db, sealed=None)
        assert caught.value.code == "provider_not_found"
        assert conn.commits == 0 and conn.rollbacks == 1
        # The edge must not be marked attached when the provider write failed.
        assert len(conn.statements) == 1


class TestDeleteProvider:
    def test_detaching_clears_the_edge_and_audits(self) -> None:
        db, conn = db_with({"provider": "fastly"})
        assert delete_provider(
            db, tenant_id=TENANT, environment_id=ENV, actor_id=None, actor_name="bot"
        )
        delete, edge, audit = conn.statements
        assert delete[0].startswith("DELETE FROM apiome.slate_cdn_providers")
        assert "edge_attached = FALSE, edge_provider = NULL" in edge[0]
        assert audit[1][4] == "automation"
        assert audit[1][5] == "CDN provider detached: fastly"
        assert conn.commits == 1

    def test_detaching_a_lane_without_a_provider_changes_nothing(self) -> None:
        db, conn = db_with(None)
        assert not delete_provider(
            db, tenant_id=TENANT, environment_id=ENV, actor_id=None, actor_name="bot"
        )
        assert len(conn.statements) == 1
        assert conn.commits == 0


class TestReads:
    def test_get_provider_is_tenant_scoped(self) -> None:
        db, conn = db_with({"id": "p-1"})
        assert get_provider(db, tenant_id=TENANT, environment_id=ENV) == {"id": "p-1"}
        query, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert params == (ENV, TENANT)

    def test_verified_hosts_only_lists_verified_domains(self) -> None:
        db, conn = db_with([{"host": "docs.example.com"}, {"host": "www.example.com"}])
        assert verified_hosts(db, tenant_id=TENANT, environment_id=ENV) == [
            "docs.example.com",
            "www.example.com",
        ]
        assert "verification_status = 'verified'" in conn.statements[0][0]
        assert "tenant_id = %s::uuid" in conn.statements[0][0]

    def test_dispatches_are_listed_most_recent_first(self) -> None:
        db, conn = db_with([{"id": "d-2"}, {"id": "d-1"}])
        assert [row["id"] for row in list_dispatches(db, tenant_id=TENANT, environment_id=ENV)] == [
            "d-2",
            "d-1",
        ]
        assert "ORDER BY dispatched_at DESC" in conn.statements[0][0]


class TestRecordDispatch:
    def test_a_dispatch_is_appended_and_committed(self) -> None:
        db, conn = db_with({"id": "d-1"})
        written = record_dispatch(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            release_id="rel-1",
            cache_purge_id=None,
            trigger="deploy",
            provider="cloudflare",
            mode="urls",
            url_count=2,
            sample_urls=("https://d/a", "https://d/b"),
            status="succeeded",
            http_status=200,
            error_code=None,
            error_message=None,
            actor_id="user-1",
            actor_name="ken@example.com",
        )
        assert written == {"id": "d-1"}
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_cdn_purge_dispatches" in query
        assert params[8] == ["https://d/a", "https://d/b"]
        assert conn.commits == 1


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


class TestVault:
    @pytest.fixture
    def keys(self, monkeypatch):
        monkeypatch.setattr(settings, "slate_cdn_credential_encryption_keys", json.dumps({"1": _key()}))
        monkeypatch.setattr(settings, "slate_cdn_credential_active_key_version", None)

    def test_an_unconfigured_vault_refuses_to_seal(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "slate_cdn_credential_encryption_keys", None)
        assert not slate_cdn_crypto.cdn_vault_configured()
        with pytest.raises(slate_cdn_crypto.CdnCredentialEncryptionError):
            slate_cdn_crypto.seal_cdn_credential("tok")

    def test_a_credential_round_trips_and_is_not_stored_in_the_clear(self, keys) -> None:
        ciphertext, version = slate_cdn_crypto.seal_cdn_credential("tok_secret_123")
        assert version == 1
        assert b"tok_secret_123" not in ciphertext
        assert ciphertext.startswith(b"OSCV")
        assert slate_cdn_crypto.unseal_cdn_credential(ciphertext, version) == "tok_secret_123"

    def test_another_key_cannot_open_it(self, keys, monkeypatch) -> None:
        ciphertext, version = slate_cdn_crypto.seal_cdn_credential("tok")
        monkeypatch.setattr(settings, "slate_cdn_credential_encryption_keys", json.dumps({"1": _key()}))
        assert slate_cdn_crypto.unseal_cdn_credential(ciphertext, version) is None

    def test_a_missing_blob_opens_to_none(self, keys) -> None:
        assert slate_cdn_crypto.unseal_cdn_credential(None, 1) is None

    def test_malformed_keys_fail_validation(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "slate_cdn_credential_encryption_keys", "not json")
        with pytest.raises(slate_cdn_crypto.CdnCredentialEncryptionError):
            slate_cdn_crypto.validate_slate_cdn_credential_keys()
