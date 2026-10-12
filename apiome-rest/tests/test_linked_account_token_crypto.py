"""Tests for linked-account token encryption-at-rest (OLO-7.3 follow-up, #4960).

Covers the contract of :mod:`app.linked_account_token_crypto`:

* a token round-trips through the sealed ``enc:v1`` string, and the stored value carries no plaintext,
* a legacy plaintext value still reads (the upgrade path) and is reported as needing a seal,
* sealing fails closed and unsealing fails safe — the ciphertext is never returned as a token,
* key rotation, startup validation, and that tokens never appear in logs,
* the vectors apiome-ui sealed open here (the two implementations share one format),
* the backfill seals plaintext, re-seals old-key rows, is idempotent, and never clobbers a
  token that changed under it, and
* the one REST read path hands its callers the plaintext token.
"""

import base64
import json
import logging
import os
from pathlib import Path

import pytest

from app.config import settings
from app.database import Database
from app.linked_account_token_crypto import (
    KEYS_SETTING,
    SEALED_PREFIX,
    LinkedAccountTokenEncryptionError,
    is_sealed,
    linked_account_token_encryption_configured,
    needs_reseal,
    seal_plaintext_tokens,
    seal_token,
    unseal_token,
    validate_linked_account_token_keys,
)

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "linked_account_token_vectors.json").read_text("utf-8")
)

TOKEN = "gho_test_token_not_a_real_credential_0001"


def _b64_key() -> str:
    """A fresh base64-encoded 32-byte AES-256 master key."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _configure(monkeypatch, keys, active=None):
    """Point the vault at ``keys`` (a version→base64 dict, or ``None``) with ``active`` version."""
    monkeypatch.setattr(
        settings,
        "linked_account_token_encryption_keys",
        json.dumps(keys) if keys is not None else None,
    )
    monkeypatch.setattr(settings, "linked_account_token_active_key_version", active)


@pytest.fixture
def single_key(monkeypatch):
    """Configure exactly one master key (version 1)."""
    keys = {"1": _b64_key()}
    _configure(monkeypatch, keys)
    return keys


@pytest.fixture
def two_keys(monkeypatch):
    """Configure two master keys with version 2 active."""
    keys = {"1": _b64_key(), "2": _b64_key()}
    _configure(monkeypatch, keys, active=2)
    return keys


@pytest.fixture
def unconfigured(monkeypatch):
    """No master key configured."""
    _configure(monkeypatch, None)


# --------------------------------------------------------------------------------------------------
# Seal / unseal
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("token", [TOKEN, "glpat-x", "t", "ünïcode-tøken", "a:b:c", "x" * 4096])
def test_round_trip(single_key, token):
    sealed = seal_token(token)
    assert sealed.startswith(f"{SEALED_PREFIX}1:")
    assert is_sealed(sealed)
    assert unseal_token(sealed) == token


def test_sealed_value_carries_no_plaintext(single_key):
    sealed = seal_token(TOKEN)
    assert TOKEN not in sealed
    assert TOKEN.encode() not in base64.b64decode(sealed.rsplit(":", 1)[1])


def test_same_token_seals_to_different_values(single_key):
    assert seal_token(TOKEN) != seal_token(TOKEN)


@pytest.mark.parametrize("bad", ["", None, 12])
def test_seal_rejects_a_non_token(single_key, bad):
    with pytest.raises(ValueError):
        seal_token(bad)


def test_seal_fails_closed_when_unconfigured(unconfigured):
    assert linked_account_token_encryption_configured() is False
    with pytest.raises(LinkedAccountTokenEncryptionError) as exc:
        seal_token(TOKEN)
    assert KEYS_SETTING in str(exc.value)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_unseal_of_nothing_is_none(single_key, empty):
    assert unseal_token(empty) is None


def test_legacy_plaintext_reads_unchanged(single_key):
    assert is_sealed(TOKEN) is False
    assert unseal_token(TOKEN) == TOKEN


def test_legacy_plaintext_reads_without_any_key(unconfigured):
    assert unseal_token(TOKEN) == TOKEN


def test_sealed_value_without_its_key_is_absent_not_ciphertext(single_key, monkeypatch):
    sealed = seal_token(TOKEN)
    _configure(monkeypatch, None)
    assert unseal_token(sealed) is None
    _configure(monkeypatch, {"1": _b64_key()})  # a different key under the same version
    assert unseal_token(sealed) is None


@pytest.mark.parametrize(
    "mangle",
    [
        lambda s: s[:-4] + ("AAAA" if not s.endswith("AAAA") else "BBBB"),  # tampered tail
        lambda s: s.replace(":1:", ":2:", 1),  # re-tagged to another key-version
        lambda s: s.replace(":1:", ":x:", 1),  # non-integer version
        lambda s: s.rsplit(":", 1)[0] + ":not base64!",  # malformed body
        lambda s: s.rsplit(":", 1)[0] + ":" + base64.b64encode(b"short").decode(),
        lambda s: SEALED_PREFIX + "1",  # no body at all
    ],
)
def test_tampered_or_malformed_value_is_absent(two_keys, monkeypatch, mangle):
    monkeypatch.setattr(settings, "linked_account_token_active_key_version", 1)
    sealed = seal_token(TOKEN)
    assert unseal_token(mangle(sealed)) is None


def test_blob_from_another_vault_does_not_open(single_key, monkeypatch):
    from app.mcp_credential_crypto import seal_credential_payload

    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", settings.linked_account_token_encryption_keys
    )
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    blob, version = seal_credential_payload({"token": TOKEN})
    foreign = f"{SEALED_PREFIX}{version}:{base64.b64encode(blob).decode()}"
    assert unseal_token(foreign) is None


# --------------------------------------------------------------------------------------------------
# Rotation, validation, logging
# --------------------------------------------------------------------------------------------------
def test_rotation_keeps_old_rows_readable(monkeypatch):
    keys = {"1": _b64_key()}
    _configure(monkeypatch, keys)
    old = seal_token(TOKEN)
    assert needs_reseal(old) is False

    keys["2"] = _b64_key()
    _configure(monkeypatch, keys)  # active defaults to the highest version
    assert unseal_token(old) == TOKEN
    assert needs_reseal(old) is True
    fresh = seal_token(TOKEN)
    assert fresh.startswith(f"{SEALED_PREFIX}2:")
    assert needs_reseal(fresh) is False


def test_needs_reseal(single_key, monkeypatch):
    assert needs_reseal(TOKEN) is True  # legacy plaintext
    assert needs_reseal(None) is False
    assert needs_reseal("") is False
    assert needs_reseal(SEALED_PREFIX + "x:???") is False  # malformed: nothing to re-seal from
    _configure(monkeypatch, None)
    assert needs_reseal(TOKEN) is False  # nothing to seal with


def test_validate_accepts_unconfigured_and_valid(unconfigured, monkeypatch):
    validate_linked_account_token_keys()
    _configure(monkeypatch, {"1": _b64_key()})
    validate_linked_account_token_keys()


@pytest.mark.parametrize(
    "raw, active",
    [
        ("not json", None),
        ("[]", None),
        (json.dumps({"1": "c2hvcnQ="}), None),
        (json.dumps({"one": base64.b64encode(os.urandom(32)).decode()}), None),
        (json.dumps({"1": base64.b64encode(os.urandom(32)).decode()}), 7),
    ],
)
def test_validate_rejects_a_misconfigured_key_map(monkeypatch, raw, active):
    monkeypatch.setattr(settings, "linked_account_token_encryption_keys", raw)
    monkeypatch.setattr(settings, "linked_account_token_active_key_version", active)
    with pytest.raises(LinkedAccountTokenEncryptionError):
        validate_linked_account_token_keys()


def test_tokens_and_keys_never_reach_the_logs(single_key, monkeypatch, caplog):
    sealed = seal_token(TOKEN)
    key = single_key["1"]
    with caplog.at_level(logging.DEBUG):
        unseal_token(sealed[:-4] + "AAAA")
        unseal_token(SEALED_PREFIX + "x:y")
        _configure(monkeypatch, {"1": _b64_key()})
        unseal_token(sealed)
    assert caplog.records, "the failures above should have been logged"
    assert TOKEN not in caplog.text
    assert key not in caplog.text
    assert sealed not in caplog.text


# --------------------------------------------------------------------------------------------------
# Cross-language vectors (sealed by apiome-ui and by this module)
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("vector", VECTORS["typescript"] + VECTORS["python"], ids=lambda v: v["token"])
def test_opens_the_shared_vectors(monkeypatch, vector):
    _configure(monkeypatch, VECTORS["keys"])
    assert vector["sealed"].startswith(f"{SEALED_PREFIX}{vector['key_version']}:")
    assert unseal_token(vector["sealed"]) == vector["token"]


def test_vectors_cover_both_implementations():
    assert len(VECTORS["typescript"]) >= 2 and len(VECTORS["python"]) >= 2


# --------------------------------------------------------------------------------------------------
# Backfill / rotation sweep
# --------------------------------------------------------------------------------------------------
class FakeLinkedAccounts:
    """An in-memory ``external_auth_providers`` speaking the two calls the backfill makes."""

    def __init__(self, rows):
        self.rows = {row["id"]: dict(row) for row in rows}
        self.writes = 0
        self.before_write = None

    def execute_query(self, _query, params):
        after, _, limit = params
        ids = sorted(i for i in self.rows if after is None or i > after)
        return [
            dict(self.rows[i])
            for i in ids
            if self.rows[i]["access_token"] is not None or self.rows[i]["refresh_token"] is not None
        ][:limit]

    def _execute_write(self, query, params):
        if self.before_write:
            self.before_write(self)
        new_value, row_id, expected = params
        column = "access_token" if "SET access_token" in query else "refresh_token"
        assert f"AND {column} = %s" in query, "the write must be a compare-and-set"
        if self.rows[row_id][column] != expected:
            return 0
        self.rows[row_id][column] = new_value
        self.writes += 1
        return 1


def _row(n, access=None, refresh=None):
    return {"id": f"00000000-0000-0000-0000-{n:012d}", "access_token": access, "refresh_token": refresh}


def test_backfill_seals_plaintext_and_is_idempotent(single_key):
    already = seal_token("already-sealed")
    store = FakeLinkedAccounts(
        [
            _row(1, access="plain-access-1", refresh="plain-refresh-1"),
            _row(2, access="plain-pat-2"),
            _row(3, access=already),
            _row(4),
            _row(5, access="", refresh="plain-refresh-5"),
        ]
    )
    summary = seal_plaintext_tokens(store, batch_size=2)
    assert summary == {
        "rows_scanned": 4,
        "tokens_sealed": 4,
        "tokens_resealed": 0,
        "tokens_unreadable": 0,
        "tokens_skipped": 0,
    }
    rows = list(store.rows.values())
    assert unseal_token(rows[0]["access_token"]) == "plain-access-1"
    assert unseal_token(rows[0]["refresh_token"]) == "plain-refresh-1"
    assert unseal_token(rows[1]["access_token"]) == "plain-pat-2"
    assert rows[2]["access_token"] == already
    assert rows[4]["access_token"] == ""
    assert unseal_token(rows[4]["refresh_token"]) == "plain-refresh-5"
    assert all(
        value is None or value == "" or is_sealed(value)
        for row in rows
        for value in (row["access_token"], row["refresh_token"])
    )

    again = seal_plaintext_tokens(store, batch_size=2)
    assert again["tokens_sealed"] == 0 and again["tokens_resealed"] == 0
    assert store.writes == 4


def test_backfill_dry_run_writes_nothing(single_key):
    store = FakeLinkedAccounts([_row(1, access="plain", refresh="plain-r")])
    summary = seal_plaintext_tokens(store, dry_run=True)
    assert summary["tokens_sealed"] == 2
    assert store.writes == 0
    assert store.rows[_row(1)["id"]]["access_token"] == "plain"


def test_backfill_reseals_rows_on_an_old_key(monkeypatch):
    keys = {"1": _b64_key()}
    _configure(monkeypatch, keys)
    old = seal_token(TOKEN)
    keys["2"] = _b64_key()
    _configure(monkeypatch, keys)
    store = FakeLinkedAccounts([_row(1, access=old)])
    summary = seal_plaintext_tokens(store)
    assert summary["tokens_resealed"] == 1 and summary["tokens_sealed"] == 0
    resealed = store.rows[_row(1)["id"]]["access_token"]
    assert resealed.startswith(f"{SEALED_PREFIX}2:")
    assert unseal_token(resealed) == TOKEN


def test_backfill_leaves_unreadable_rows_untouched(single_key, monkeypatch):
    lost = seal_token(TOKEN)
    _configure(monkeypatch, {"1": _b64_key()})  # the key that sealed it is gone
    store = FakeLinkedAccounts([_row(1, access=lost)])
    summary = seal_plaintext_tokens(store)
    assert summary["tokens_unreadable"] == 1
    assert store.writes == 0
    assert store.rows[_row(1)["id"]]["access_token"] == lost


def test_backfill_does_not_clobber_a_token_replaced_mid_run(single_key):
    store = FakeLinkedAccounts([_row(1, access="old-plain")])
    row_id = _row(1)["id"]
    replacement = seal_token("users-new-pat")

    def user_saves_a_new_pat(fake):
        fake.rows[row_id]["access_token"] = replacement

    store.before_write = user_saves_a_new_pat
    summary = seal_plaintext_tokens(store)
    assert summary["tokens_skipped"] == 1 and summary["tokens_sealed"] == 0
    assert store.rows[row_id]["access_token"] == replacement


def test_backfill_refuses_to_run_unconfigured(unconfigured):
    store = FakeLinkedAccounts([_row(1, access="plain")])
    with pytest.raises(LinkedAccountTokenEncryptionError) as exc:
        seal_plaintext_tokens(store)
    assert KEYS_SETTING in str(exc.value)
    assert store.rows[_row(1)["id"]]["access_token"] == "plain"


def test_backfill_script_reports_counts_only(single_key, monkeypatch, capsys):
    from app.seal_linked_account_tokens import main

    store = FakeLinkedAccounts([_row(1, access="plain-secret-token")])
    assert main(["--dry-run"], database=store) == 0
    assert store.writes == 0
    assert main([], database=store) == 0
    out = capsys.readouterr().out
    assert '"tokens_sealed": 1' in out
    assert "plain-secret-token" not in out

    _configure(monkeypatch, None)
    assert main([], database=store) == 1
    assert KEYS_SETTING in capsys.readouterr().err


def test_backfill_command_exits_nonzero_when_a_token_is_unreadable(single_key, monkeypatch, capsys):
    from app.seal_linked_account_tokens import main

    lost = seal_token(TOKEN)
    _configure(monkeypatch, {"1": _b64_key()})
    assert main([], database=FakeLinkedAccounts([_row(1, access=lost)])) == 1
    assert '"tokens_unreadable": 1' in capsys.readouterr().out


# --------------------------------------------------------------------------------------------------
# The REST read path
# --------------------------------------------------------------------------------------------------
def _database_returning(monkeypatch, rows):
    """A ``Database`` whose ``execute_query`` returns ``rows`` without touching Postgres."""
    database = Database.__new__(Database)
    monkeypatch.setattr(database, "execute_query", lambda _q, _p=None: rows, raising=False)
    return database


def test_linked_account_reader_returns_the_plaintext_token(single_key, monkeypatch):
    sealed = seal_token(TOKEN)
    database = _database_returning(
        monkeypatch, [{"id": "a", "user_id": "u", "provider": "github", "access_token": sealed}]
    )
    row = database.get_external_auth_provider_for_user("a", "u")
    assert row == {"id": "a", "user_id": "u", "provider": "github", "access_token": TOKEN}


def test_linked_account_reader_still_reads_legacy_plaintext(unconfigured, monkeypatch):
    database = _database_returning(
        monkeypatch, [{"id": "a", "user_id": "u", "provider": "github", "access_token": TOKEN}]
    )
    assert database.get_external_auth_provider_for_user("a", "u")["access_token"] == TOKEN


def test_linked_account_reader_never_returns_ciphertext(single_key, monkeypatch):
    sealed = seal_token(TOKEN)
    database = _database_returning(
        monkeypatch, [{"id": "a", "user_id": "u", "provider": "github", "access_token": sealed}]
    )
    _configure(monkeypatch, None)
    assert database.get_external_auth_provider_for_user("a", "u")["access_token"] is None


def test_linked_account_reader_passes_through_a_missing_account(single_key, monkeypatch):
    assert _database_returning(monkeypatch, []).get_external_auth_provider_for_user("a", "u") is None
