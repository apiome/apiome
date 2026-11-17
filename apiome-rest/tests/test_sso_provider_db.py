"""SSO providers against a live Postgres — EID-1.1 (#5011), EID-1.2 (#5012).

What only the real schema can prove: the V312 constraints (slug shape, secret ciphertext and key id
both-or-neither, config matching protocol), V393's domain rules (a provider lists a domain once, an
unverified domain reserves nothing, a verified one is unique installation-wide), that admin reads
never select the ciphertext, that a workspace reads only its own providers, that only enabled
providers' *verified* domains are routable, that the plugin's fallback model is always empty, and
that ``external_auth_providers`` accepts ``sso:<slug>``.

Runs inside one always-rolled-back transaction (the ``tx`` fixture of ``test_usage_index_db``);
V312 and V393 are applied inside that transaction when the database does not have them yet, so
nothing persists. Skipped when no database is reachable.
"""

from __future__ import annotations

import pathlib
from typing import Any, Tuple

import psycopg2
import pytest

from app import sso_provider_store as store
from app.sso_metadata import CODE_DOMAIN_CLAIMED, CODE_DOMAIN_EXISTS, CODE_SLUG_TAKEN, SsoConfigError
from tests import test_usage_index_db as index_db

tx = index_db.tx

pytestmark = pytest.mark.requires_db

_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "apiome-db" / "scripts"
MIGRATION = _SCRIPTS / "V312__sso_providers_5011.sql"
DOMAIN_MIGRATION = _SCRIPTS / "V393__sso_domain_verification_5012.sql"

OIDC_CONFIG = {"client_id": "apiome", "jwks_uri": "https://idp.example.com/certs"}
SAML_CONFIG = {"idp_entity_id": "https://idp.example.com/saml", "email_source": "nameid"}


@pytest.fixture
def sso(tx: Tuple[Any, Any]):
    db, cursor = tx
    cursor.execute("SELECT to_regclass('apiome.sso_provider') AS t")
    if not cursor.fetchone()["t"]:
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    cursor.execute("SELECT to_regclass('apiome.sso_provider_domain_verified_uq') AS i")
    if not cursor.fetchone()["i"]:
        cursor.execute(DOMAIN_MIGRATION.read_text(encoding="utf-8"))
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


def test_an_unverified_domain_reserves_nothing_and_a_verified_one_is_unique(sso) -> None:
    db, cursor = sso
    first = _oidc(db, slug="acme-one")
    second = _oidc(db, slug="acme-two")
    third = _oidc(db, slug="acme-three")
    store.add_domain(db, first["id"], "claimed.example", token="t1")
    # Unverified: a second provider may list it too.
    store.add_domain(db, second["id"], "claimed.example", token="t2")
    assert store.domain_verified_elsewhere(db, first["id"], "claimed.example") is False

    store.verify_domain(db, second["id"], "claimed.example", actor="owner-2")
    assert store.domain_verified_elsewhere(db, first["id"], "claimed.example") is True
    assert store.domain_verified_elsewhere(db, second["id"], "claimed.example") is False

    def verify_late():
        with pytest.raises(SsoConfigError) as caught:
            store.verify_domain(db, first["id"], "claimed.example", actor="owner-1")
        assert caught.value.code == CODE_DOMAIN_CLAIMED

    _savepoint(cursor, verify_late)

    with pytest.raises(SsoConfigError) as caught:
        store.add_domain(db, third["id"], "claimed.example", token="t3")
    assert caught.value.code == CODE_DOMAIN_CLAIMED

    # Once the holder lets go, the domain can be proved by someone else.
    assert store.remove_domain(db, second["id"], "claimed.example") is True
    assert store.verify_domain(db, first["id"], "claimed.example", actor="owner-1")["verified_at"] is not None


def test_a_provider_lists_a_domain_once(sso) -> None:
    db, cursor = sso
    provider = _oidc(db)
    store.add_domain(db, provider["id"], "acme.example", token="t")

    def again():
        with pytest.raises(SsoConfigError) as caught:
            store.add_domain(db, provider["id"], "acme.example", token="t")
        assert caught.value.code == CODE_DOMAIN_EXISTS

    _savepoint(cursor, again)


def test_a_workspace_reads_only_its_own_providers(sso) -> None:
    db, cursor = sso
    mine = index_db._tenant(cursor)["tenant"]
    theirs = index_db._tenant(cursor)["tenant"]
    own = _oidc(db, slug="acme-mine", tenant_id=mine)
    other = _oidc(db, slug="acme-theirs", tenant_id=theirs)
    store.add_domain(db, other["id"], "theirs.example", token="t")

    listed = store.list_providers(db, tenant_id=mine)
    assert [row["slug"] for row in listed] == ["acme-mine"]
    assert listed[0]["domains"] == []
    assert store.get_provider(db, own["id"], tenant_id=mine)["slug"] == "acme-mine"
    assert store.get_provider(db, other["id"], tenant_id=mine) is None


def test_members_who_signed_in_through_a_provider_are_counted(sso) -> None:
    db, cursor = sso
    tenant = index_db._tenant(cursor)["tenant"]
    provider = _oidc(db, slug="acme-count", tenant_id=tenant)
    assert store.count_linked_members(db, tenant, provider["slug"]) == 0

    cursor.execute("SELECT id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (tenant, user),
    )
    cursor.execute(
        "INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id) "
        "VALUES (%s, 'sso:acme-count', 'sub-count') ON CONFLICT DO NOTHING",
        (user,),
    )
    assert store.count_linked_members(db, tenant, provider["slug"]) == 1
    # A member of another workspace with the same identity is not this workspace's.
    assert store.count_linked_members(db, index_db._tenant(cursor)["tenant"], provider["slug"]) == 0


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
