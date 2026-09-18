"""An in-memory stand-in for the upstream-vault accessors on ``app.database.db`` — AGX-2.2 (#4534).

The apiome-rest suite runs without a database in CI, so the vault's tests swap the seven
``db.*upstream_credential*`` accessors for this store. It mirrors the SQL accessors' contract
closely enough that a vault bug shows up here too:

* rows come back in the same shape, and the ciphertext is only present on the two reads that
  select it (``list_upstream_credentials`` and ``get_upstream_credential_bindings``);
* every read and write is scoped by tenant *and* toolset, like the ``WHERE`` clauses;
* a create never overwrites (``ON CONFLICT DO NOTHING`` → ``None``);
* each accessor holds one lock for its whole body, the way one SQL statement is atomic, so a
  concurrent reader sees a rotation's old row or new row and never a gap;
* every call is logged in :attr:`FakeUpstreamStore.calls`, so a test can assert *which*
  statements an operation issued (a rotation must never delete and re-insert).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: The accessors the vault calls; :meth:`FakeUpstreamStore.install` patches exactly these.
ACCESSORS = (
    "list_upstream_credentials",
    "get_upstream_credential",
    "get_upstream_credential_bindings",
    "insert_upstream_credential",
    "rotate_upstream_credential",
    "delete_upstream_credential",
    "insert_upstream_credential_use",
)

#: Metadata columns every metadata accessor returns (``_UPSTREAM_CREDENTIAL_COLUMNS``).
_METADATA = (
    "id",
    "tenant_id",
    "toolset_id",
    "server_url",
    "kind",
    "api_key_in",
    "api_key_name",
    "key_version",
    "created_by",
    "rotated_by",
    "created_at",
    "rotated_at",
)


class FakeUpstreamStore:
    """The upstream-credential tables, in memory.

    Attributes:
        rows: Stored credentials by id, including ``encrypted_secret``.
        uses: Appended use records, in order.
        calls: The name of every accessor called, in order.
        fail_uses: When ``True``, recording a use raises (to prove auditing is best-effort).
    """

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.uses: List[Dict[str, Any]] = []
        self.calls: List[str] = []
        self.fail_uses = False
        self._lock = threading.Lock()

    def install(self, monkeypatch: Any, db: Any) -> "FakeUpstreamStore":
        """Patch the vault accessors on ``db`` with this store's methods.

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

    def _last_used(self, row: Dict[str, Any]) -> Optional[datetime]:
        stamps = [
            use["used_at"]
            for use in self.uses
            if use["credential_id"] == row["id"]
            and use["tenant_id"] == row["tenant_id"]
            and use["outcome"] == "injected"
        ]
        return max(stamps) if stamps else None

    def _metadata(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = {column: row.get(column) for column in _METADATA}
        out["last_used_at"] = self._last_used(row)
        return out

    def _scoped(self, tenant_id: str, toolset_id: str) -> List[Dict[str, Any]]:
        return [
            row
            for row in self.rows.values()
            if row["tenant_id"] == str(tenant_id) and row["toolset_id"] == str(toolset_id)
        ]

    def _find(self, tenant_id: str, toolset_id: str, credential_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(credential_id))
        if row and row["tenant_id"] == str(tenant_id) and row["toolset_id"] == str(toolset_id):
            return row
        return None

    # -- accessors ---------------------------------------------------------------------------

    def list_upstream_credentials(self, tenant_id: str, toolset_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            self.calls.append("list_upstream_credentials")
            rows = sorted(self._scoped(tenant_id, toolset_id), key=lambda row: row["server_url"])
            return [
                {**self._metadata(row), "encrypted_secret": row["encrypted_secret"]}
                for row in rows
            ]

    def get_upstream_credential(
        self, tenant_id: str, toolset_id: str, credential_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append("get_upstream_credential")
            row = self._find(tenant_id, toolset_id, credential_id)
            return self._metadata(row) if row else None

    def get_upstream_credential_bindings(
        self, tenant_id: str, toolset_id: str
    ) -> List[Dict[str, Any]]:
        with self._lock:
            self.calls.append("get_upstream_credential_bindings")
            return [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "server_url",
                        "kind",
                        "api_key_in",
                        "api_key_name",
                        "encrypted_secret",
                        "key_version",
                    )
                }
                for row in self._scoped(tenant_id, toolset_id)
            ]

    def insert_upstream_credential(self, **fields: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append("insert_upstream_credential")
            taken = any(
                row["server_url"] == fields["server_url"]
                for row in self._scoped(fields["tenant_id"], fields["toolset_id"])
            )
            if taken:
                return None
            row = {
                "id": str(uuid.uuid4()),
                "tenant_id": str(fields["tenant_id"]),
                "toolset_id": str(fields["toolset_id"]),
                "server_url": fields["server_url"],
                "kind": fields["kind"],
                "api_key_in": fields["api_key_in"],
                "api_key_name": fields["api_key_name"],
                "encrypted_secret": bytes(fields["encrypted_secret"]),
                "key_version": fields["key_version"],
                "created_by": fields.get("actor_id"),
                "rotated_by": None,
                "created_at": datetime.now(timezone.utc),
                "rotated_at": None,
            }
            self.rows[row["id"]] = row
            return self._metadata(row)

    def rotate_upstream_credential(self, **fields: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append("rotate_upstream_credential")
            row = self._find(fields["tenant_id"], fields["toolset_id"], fields["credential_id"])
            if row is None:
                return None
            row["encrypted_secret"] = bytes(fields["encrypted_secret"])
            row["key_version"] = fields["key_version"]
            row["rotated_by"] = fields.get("actor_id")
            row["rotated_at"] = datetime.now(timezone.utc)
            return self._metadata(row)

    def delete_upstream_credential(
        self, tenant_id: str, toolset_id: str, credential_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            self.calls.append("delete_upstream_credential")
            row = self._find(tenant_id, toolset_id, credential_id)
            if row is None:
                return None
            del self.rows[row["id"]]
            return self._metadata(row)

    def insert_upstream_credential_use(self, **fields: Any) -> int:
        with self._lock:
            self.calls.append("insert_upstream_credential_use")
            if self.fail_uses:
                raise RuntimeError("use ledger unavailable")
            self.uses.append({**fields, "used_at": datetime.now(timezone.utc)})
            return 1
