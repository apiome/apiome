"""SSO providers against a live Postgres — EID-1.1 (#5011).

What only the real schema can prove: the V312 constraints (slug shape, one domain per installation,
secret ciphertext and key id both-or-neither, config matching protocol), that admin reads never
select the ciphertext, that only enabled providers' *verified* domains are routable, that the
plugin's fallback model is always empty, and that ``external_auth_providers`` accepts ``sso:<slug>``.

Runs inside one always-rolled-back transaction (the ``tx`` fixture of ``test_usage_index_db``);
V312 is applied inside that transaction when the database does not have it yet, so nothing
persists. Skipped when no database is reachable.
"""

from __future__ import annotations

import pathlib
from typing import Any, Tuple

import psycopg2
import pytest

from app import sso_provider_store as store
from app.sso_metadata import CODE_DOMAIN_CLAIMED, CODE_SLUG_TAKEN, SsoConfigError
from tests import test_usage_index_db as index_db

tx = index_db.tx

pytestmark = pytest.mark.requires_db

MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "apiome-db" / "scripts" / "V312__sso_providers_5011.sql"

OIDC_CONFIG = {"client_id": "apiome", "jwks_uri": "https://idp.example.com/certs"}
SAML_CONFIG = {"idp_entity_id": "https://idp.example.com/saml", "email_source": "nameid"}


@pytest.fixture
def sso(tx: Tuple[Any, Any]):
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.sso_provider') AS t")
    if not cursor.fetchone()["t"]:
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    return db, cursor


def _oidc(db, slug="acme-okta", **extra):
    return store.create_provider(
        db,
        {
            "slug": slug,
            "protocol": "oidc",
            "display_name": "Acme",
            "issuer": "https://idp.example.com",
            "oidc_config": OIDC_CONFIG,
            "client_secret_encrypted": b"\x01ciphertext-bytes",
            "client_secret_key_id": "k1",
            **extra,
        },
        actor="admin",
    )


def _savepoint(cursor, fn):
    """Run ``fn`` expecting it to fail, without aborting the enclosing transaction."""
    cursor.execute("SAVEPOINT expect_failure")
    try:
        fn()
    finally:
        cursor.execute("ROLLBACK TO SAVEPOINT expect_failure")


def test_admin_reads_never_select_the_ciphertext(sso) -> None:
    db, _ = sso
    created = _oidc(db)
    assert created["has_client_secret"] is True
    assert created["has_sp_private_key"] is False
    for row in (created, store.get_provider(db, created["id"]), *store.list_providers(db)):
        assert not any(key.endswith("_encrypted") or key.endswith("_key_id") for key in row)
    assert created["oidc_config"] == OIDC_CONFIG


def test_only_enabled_providers_with_verified_domains_are_routable(sso) -> None:
    db, _ = sso
    provider = _oidc(db)
    store.add_domain(db, provider["id"], "acme.example", token="t1")
    store.add_domain(db, provider["id"], "other.example", token="t2")
    assert store.list_routable_with_secrets(db) == [] or all(
        r["slug"] != "acme-okta" for r in store.list_routable_with_secrets(db)
    )

    store.update_provider(db, provider["id"], {"enabled": True}, actor="admin")
    assert all(r["slug"] != "acme-okta" for r in store.list_routable_with_secrets(db))

    verified = store.verify_domain(db, provider["id"], "acme.example", actor="admin")
    assert verified["verified_at"] is not None and verified["verified_by"] == "admin"
    (routable,) = [r for r in store.list_routable_with_secrets(db) if r["slug"] == "acme-okta"]
    assert routable["domains"] == ["acme.example"]
    assert bytes(routable["client_secret_encrypted"]) == b"\x01ciphertext-bytes"


def test_verification_is_idempotent(sso) -> None:
    db, _ = sso
    provider = _oidc(db)
    store.add_domain(db, provider["id"], "acme.example", token="t")
    first = store.verify_domain(db, provider["id"], "acme.example", actor="admin")
    second = store.verify_domain(db, provider["id"], "acme.example", actor="someone-else")
    assert second["verified_at"] == first["verified_at"]
    assert second["verified_by"] == "admin"


def test_a_domain_is_unique_across_the_installation(sso) -> None:
    db, cursor = sso
    first = _oidc(db, slug="acme-one")
    second = _oidc(db, slug="acme-two")
    store.add_domain(db, first["id"], "claimed.example", token="t")

    def claim_again():
        with pytest.raises(SsoConfigError) as caught:
            store.add_domain(db, second["id"], "claimed.example", token="t")
        assert caught.value.code == CODE_DOMAIN_CLAIMED

    _savepoint(cursor, claim_again)


def test_a_slug_is_unique(sso) -> None:
    db, cursor = sso
    _oidc(db)

    def again():
        with pytest.raises(SsoConfigError) as caught:
            _oidc(db)
        assert caught.value.code == CODE_SLUG_TAKEN

    _savepoint(cursor, again)


@pytest.mark.parametrize(
    "sql",
    [
        # A slug too long for `sso:<slug>` in VARCHAR(32), or the wrong shape.
        "INSERT INTO apiome.sso_provider (slug, protocol, display_name, issuer, oidc_config) VALUES ('"
        + "a" * 29
        + "', 'oidc', 'x', 'i', '{}')",
        "INSERT INTO apiome.sso_provider (slug, protocol, display_name, issuer, oidc_config) "
        "VALUES ('Bad Slug', 'oidc', 'x', 'i', '{}')",
        # Config must match the protocol.
        "INSERT INTO apiome.sso_provider (slug, protocol, display_name, issuer, saml_config) "
        "VALUES ('mismatch', 'oidc', 'x', 'i', '{}')",
        # Ciphertext without its key id.
        "INSERT INTO apiome.sso_provider (slug, protocol, display_name, issuer, oidc_config, client_secret_encrypted) "
        "VALUES ('nokey', 'oidc', 'x', 'i', '{}', '\\x01')",
    ],
)
def test_the_constraints_hold(sso, sql) -> None:
    _, cursor = sso

    def run():
        # A too-long slug is stopped by VARCHAR(28) before the CHECK sees it; either refuses it.
        with pytest.raises((psycopg2.errors.CheckViolation, psycopg2.errors.StringDataRightTruncation)):
            cursor.execute(sql)

    _savepoint(cursor, run)


def test_a_domain_must_be_lower_case_and_well_formed(sso) -> None:
    db, cursor = sso
    provider = _oidc(db)

    def run():
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO apiome.sso_provider_domain (provider_id, domain, verification_token) "
                "VALUES (%s, 'Acme.Example', 't')",
                (provider["id"],),
            )

    _savepoint(cursor, run)


def test_deleting_a_provider_takes_its_domains(sso) -> None:
    db, cursor = sso
    provider = _oidc(db)
    store.add_domain(db, provider["id"], "gone.example", token="t")
    assert store.delete_provider(db, provider["id"])["slug"] == "acme-okta"
    cursor.execute("SELECT count(*) AS n FROM apiome.sso_provider_domain WHERE domain = 'gone.example'")
    assert cursor.fetchone()["n"] == 0


def test_the_plugin_fallback_model_is_always_empty(sso) -> None:
    db, cursor = sso
    provider = _oidc(db)
    store.add_domain(db, provider["id"], "acme.example", token="t")
    store.verify_domain(db, provider["id"], "acme.example", actor="admin")
    store.update_provider(db, provider["id"], {"enabled": True}, actor="admin")
    cursor.execute(
        'SELECT count(*) AS n FROM apiome.sso_provider_plugin_stub WHERE "providerId" = %s', ("sso-acme-okta",)
    )
    assert cursor.fetchone()["n"] == 0


def test_identities_accept_the_sso_vocabulary(sso) -> None:
    _, cursor = sso
    cursor.execute("SELECT id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id) "
        "VALUES (%s, 'sso:acme-okta', 'sub-1')",
        (user,),
    )

    def bad():
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id) "
                "VALUES (%s, 'sso:Bad_Slug', 'sub-2')",
                (user,),
            )

    _savepoint(cursor, bad)
