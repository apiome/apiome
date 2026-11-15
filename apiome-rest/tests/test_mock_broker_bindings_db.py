"""Database accessors for mock broker bindings — XPC-2.1 (#5735).

``execute_query`` is mocked, so no live database is touched: these pin the SQL contract the
in-memory fake mirrors — tenant *and* version scoping on every statement, ``ON CONFLICT DO
NOTHING`` on create, the ciphertext selected only when asked for, a rotation that is one
``UPDATE`` of a SASL binding, and a non-UUID id never reaching SQL.
"""

from unittest.mock import MagicMock

from app.database import Database

_TENANT = "11111111-1111-4111-8111-111111111111"
_VERSION = "55555555-5555-4555-8555-555555555555"
_BINDING = "99999999-9999-4999-8999-999999999999"


def _db(rows=None) -> Database:
    db = Database()
    db.execute_query = MagicMock(return_value=rows if rows is not None else [])
    return db


def _sql(db: Database) -> str:
    return " ".join(db.execute_query.call_args.args[0].split())


def test_list_selects_the_ciphertext_scoped_by_tenant_and_version():
    db = _db([{"id": _BINDING}])
    assert db.list_mock_broker_bindings(_TENANT, _VERSION) == [{"id": _BINDING}]
    sql = _sql(db)
    assert "b.credential_ciphertext" in sql
    assert "WHERE b.tenant_id = %s::uuid AND b.version_id = %s::uuid" in sql
    assert db.execute_query.call_args.args[1] == (_TENANT, _VERSION)


def test_get_selects_the_ciphertext_only_when_asked():
    db = _db([{"id": _BINDING}])
    db.get_mock_broker_binding(_TENANT, _VERSION, _BINDING)
    assert "credential_ciphertext" not in _sql(db)
    db.get_mock_broker_binding(_TENANT, _VERSION, _BINDING, with_credential=True)
    assert "b.credential_ciphertext" in _sql(db)
    assert db.execute_query.call_args.args[1] == (_BINDING, _TENANT, _VERSION)


def test_insert_never_overwrites_and_returns_no_ciphertext():
    db = _db([])
    result = db.insert_mock_broker_binding(
        tenant_id=_TENANT,
        version_id=_VERSION,
        protocol="kafka",
        bootstrap=["broker.example.com:9092"],
        tls_enabled=False,
        tls_verify=True,
        sasl_mechanism=None,
        credential_ciphertext=None,
        key_version=None,
        client_id_prefix="apiome-mock",
        actor_id="not-a-uuid",
    )
    assert result is None
    sql = _sql(db)
    assert "ON CONFLICT (version_id, protocol) DO NOTHING" in sql
    returning = sql.split("RETURNING", 1)[1]
    assert "credential_ciphertext" not in returning
    params = db.execute_query.call_args.args[1]
    assert params[3] == ["broker.example.com:9092"]
    assert params[7] is None  # no ciphertext without SASL
    assert params[-1] is None  # a non-UUID actor is dropped, not cast


def test_rotate_is_one_update_of_a_sasl_binding():
    db = _db([{"id": _BINDING}])
    db.rotate_mock_broker_binding(
        tenant_id=_TENANT,
        version_id=_VERSION,
        binding_id=_BINDING,
        credential_ciphertext=b"OMBB...",
        key_version=2,
    )
    sql = _sql(db)
    assert sql.startswith("UPDATE apiome.mock_broker_bindings AS b")
    assert "AND b.sasl_mechanism IS NOT NULL" in sql
    assert "b.tenant_id = %s::uuid AND b.version_id = %s::uuid" in sql
    assert "credential_ciphertext" not in sql.split("RETURNING", 1)[1]


def test_delete_is_scoped_by_tenant_and_version():
    db = _db([{"id": _BINDING}])
    assert db.delete_mock_broker_binding(_TENANT, _VERSION, _BINDING) == {"id": _BINDING}
    assert "WHERE b.id = %s::uuid AND b.tenant_id = %s::uuid AND b.version_id = %s::uuid" in _sql(db)


def test_a_non_uuid_id_never_reaches_sql():
    db = _db()
    assert db.list_mock_broker_bindings(_TENANT, "v1") == []
    assert db.get_mock_broker_binding(_TENANT, _VERSION, "nope") is None
    assert db.delete_mock_broker_binding("acme", _VERSION, _BINDING) is None
    db.execute_query.assert_not_called()
