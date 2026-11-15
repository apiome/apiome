"""An in-memory stand-in for the broker-binding accessors on ``app.database.db`` — XPC-2.1 (#5735).

The apiome-rest suite runs without a database in CI, so the broker binding tests swap the
``db.*mock_broker_binding*`` accessors (plus the two version lookups the routes make) for this
store. It mirrors the SQL accessors' contract closely enough that a vault bug shows up here too:

* rows come back in the same shape, and ``credential_ciphertext`` is only present on the reads
  that select it (``list_mock_broker_bindings`` and ``get_mock_broker_binding(with_credential=True)``);
* every read and write is scoped by tenant *and* version, like the ``WHERE`` clauses;
* a create never overwrites (``ON CONFLICT DO NOTHING`` → ``None``), and a rotate of a binding
  without a SASL mechanism matches nothing, as the SQL ``AND b.sasl_mechanism IS NOT NULL`` does;
* every call is logged in :attr:`FakeBrokerStore.calls`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

#: The accessors the routes and the vault call; :meth:`FakeBrokerStore.install` patches these.
ACCESSORS = (
    "list_mock_broker_bindings",
    "get_mock_broker_binding",
    "insert_mock_broker_binding",
    "rotate_mock_broker_binding",
    "delete_mock_broker_binding",
    "get_version_by_id",
    "user_owns_version_mock_settings",
)

#: Metadata columns every accessor returns (``_MOCK_BROKER_BINDING_COLUMNS``).
_METADATA = (
    "id",
    "tenant_id",
    "version_id",
    "protocol",
    "bootstrap",
    "tls_enabled",
    "tls_verify",
    "sasl_mechanism",
    "key_version",
    "client_id_prefix",
    "created_by",
    "rotated_by",
    "created_at",
    "rotated_at",
)


class FakeBrokerStore:
    """The broker-binding table and the versions it hangs off, in memory.

    Attributes:
        rows: Stored bindings by id, including ``credential_ciphertext``.
        versions: ``version_id -> project_id`` for the versions that exist.
        owners: Version ids whose mock settings the caller may change (all, by default).
        calls: The name of every accessor called, in order.
    """

    def __init__(self, *, tenant_id: str, versions: Dict[str, str]) -> None:
        self.tenant_id = tenant_id
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.versions = dict(versions)
        self.not_owner: Set[str] = set()
        self.calls: List[str] = []

    def install(self, monkeypatch: Any, db: Any) -> "FakeBrokerStore":
        """Patch the accessors on ``db`` with this store's methods.

        Args:
            monkeypatch: The pytest ``monkeypatch`` fixture.
            db: The ``app.database.db`` singleton.

        Returns:
            ``self``, for chaining.
        """
        for name in ACCESSORS:
            monkeypatch.setattr(db, name, getattr(self, name))
        return self

    # -- helpers ---------------------------------------------------------------------------

    def _metadata(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {column: row.get(column) for column in _METADATA}

    def _find(self, tenant_id: str, version_id: str, binding_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(binding_id))
        if row and row["tenant_id"] == str(tenant_id) and row["version_id"] == str(version_id):
            return row
        return None

    # -- version lookups ---------------------------------------------------------------------

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("get_version_by_id")
        if str(tenant_id) != self.tenant_id or str(version_id) not in self.versions:
            return None
        return {"id": str(version_id), "project_id": self.versions[str(version_id)]}

    def user_owns_version_mock_settings(self, version_id: str, tenant_id: str, user_id: str) -> bool:
        self.calls.append("user_owns_version_mock_settings")
        _ = (tenant_id, user_id)
        return str(version_id) not in self.not_owner

    # -- accessors ---------------------------------------------------------------------------

    def list_mock_broker_bindings(self, tenant_id: str, version_id: str) -> List[Dict[str, Any]]:
        self.calls.append("list_mock_broker_bindings")
        rows = [
            row
            for row in self.rows.values()
            if row["tenant_id"] == str(tenant_id) and row["version_id"] == str(version_id)
        ]
        return [
            {**self._metadata(row), "credential_ciphertext": row["credential_ciphertext"]}
            for row in sorted(rows, key=lambda row: row["protocol"])
        ]

    def get_mock_broker_binding(
        self, tenant_id: str, version_id: str, binding_id: str, *, with_credential: bool = False
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("get_mock_broker_binding")
        row = self._find(tenant_id, version_id, binding_id)
        if row is None:
            return None
        out = self._metadata(row)
        if with_credential:
            out["credential_ciphertext"] = row["credential_ciphertext"]
        return out

    def insert_mock_broker_binding(self, **fields: Any) -> Optional[Dict[str, Any]]:
        self.calls.append("insert_mock_broker_binding")
        taken = any(
            row["version_id"] == str(fields["version_id"]) and row["protocol"] == fields["protocol"]
            for row in self.rows.values()
        )
        if taken:
            return None
        ciphertext = fields["credential_ciphertext"]
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(fields["tenant_id"]),
            "version_id": str(fields["version_id"]),
            "protocol": fields["protocol"],
            "bootstrap": list(fields["bootstrap"]),
            "tls_enabled": fields["tls_enabled"],
            "tls_verify": fields["tls_verify"],
            "sasl_mechanism": fields["sasl_mechanism"],
            "credential_ciphertext": bytes(ciphertext) if ciphertext is not None else None,
            "key_version": fields["key_version"],
            "client_id_prefix": fields["client_id_prefix"],
            "created_by": fields.get("actor_id"),
            "rotated_by": None,
            "created_at": datetime.now(timezone.utc),
            "rotated_at": None,
        }
        self.rows[row["id"]] = row
        return self._metadata(row)

    def rotate_mock_broker_binding(self, **fields: Any) -> Optional[Dict[str, Any]]:
        self.calls.append("rotate_mock_broker_binding")
        row = self._find(fields["tenant_id"], fields["version_id"], fields["binding_id"])
        if row is None or not row["sasl_mechanism"]:
            return None
        row["credential_ciphertext"] = bytes(fields["credential_ciphertext"])
        row["key_version"] = fields["key_version"]
        row["rotated_by"] = fields.get("actor_id")
        row["rotated_at"] = datetime.now(timezone.utc)
        return self._metadata(row)

    def delete_mock_broker_binding(
        self, tenant_id: str, version_id: str, binding_id: str
    ) -> Optional[Dict[str, Any]]:
        self.calls.append("delete_mock_broker_binding")
        row = self._find(tenant_id, version_id, binding_id)
        if row is None:
            return None
        del self.rows[row["id"]]
        return self._metadata(row)
