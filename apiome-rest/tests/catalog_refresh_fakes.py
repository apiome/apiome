"""In-memory stand-in for :mod:`app.catalog_refresh_store` (MFI-31.1, #4398).

:meth:`FakeRefreshStore.install` patches every store function the routes, the check runner and
the sweep call, so their tests run without Postgres. Due-selection mirrors the SQL in
``list_due``: scheduled cadences only, not backing off, last check at least one cadence old,
tenant switch on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app import catalog_refresh_store
from app.catalog_refresh import CADENCE_SECONDS


class FakeRefreshStore:
    """Rows keyed by project id, plus the per-tenant kill switch."""

    KEEP_CREDENTIAL = catalog_refresh_store.KEEP_CREDENTIAL

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.tenant_enabled: Dict[str, bool] = {}
        self.now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

    # -- seeding -----------------------------------------------------------------------

    def add(self, project_id: str, tenant_id: str, **overrides: Any) -> Dict[str, Any]:
        """Seed a row with sensible defaults (daily GraphQL, never checked)."""
        row: Dict[str, Any] = {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "cadence": "daily",
            "adapter_key": "graphql",
            "endpoint": "https://api.example.com/graphql",
            "options": {},
            "auth_type": "none",
            "encrypted_payload": None,
            "key_version": None,
            "status": "never",
            "last_checked_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_fingerprint": None,
            "consecutive_failures": 0,
            "next_check_after": None,
            "keep_versions": 50,
            "created_at": self.now,
            "updated_at": self.now,
        }
        row.update(overrides)
        self.rows[project_id] = row
        return row

    def _public(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in row.items() if k not in ("encrypted_payload", "key_version")}
        out["has_credential"] = row.get("encrypted_payload") is not None
        return out

    # -- store API ---------------------------------------------------------------------

    def get_refresh(self, db: Any, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(project_id)
        return self._public(row) if row and row["tenant_id"] == tenant_id else None

    def get_refresh_for_check(self, db: Any, project_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(project_id)
        return (
            {**self._public(row), "encrypted_payload": row["encrypted_payload"], "key_version": row["key_version"]}
            if row
            else None
        )

    def upsert_refresh(
        self,
        db: Any,
        *,
        project_id,
        tenant_id,
        cadence,
        adapter_key,
        endpoint,
        options,
        credential=catalog_refresh_store.KEEP_CREDENTIAL,
        user_id=None,
        keep_versions=None,
    ) -> Dict[str, Any]:
        row = self.rows.get(project_id) or self.add(project_id, tenant_id, adapter_key=adapter_key, endpoint=endpoint)
        if (row["adapter_key"], row["endpoint"]) != (adapter_key, endpoint):
            row.update(status="never", last_fingerprint=None, last_error=None)
        row.update(
            cadence=cadence,
            adapter_key=adapter_key,
            endpoint=endpoint,
            options=dict(options or {}),
            consecutive_failures=0,
            next_check_after=None,
        )
        if keep_versions is not None:
            row["keep_versions"] = keep_versions
        if credential is not catalog_refresh_store.KEEP_CREDENTIAL:
            if credential is None:
                row.update(auth_type="none", encrypted_payload=None, key_version=None)
            else:
                row.update(auth_type=credential[0], encrypted_payload=credential[1], key_version=credential[2])
        return self._public(row)

    def delete_refresh(self, db: Any, project_id: str, tenant_id: str) -> bool:
        row = self.rows.get(project_id)
        if row and row["tenant_id"] == tenant_id:
            del self.rows[project_id]
            return True
        return False

    def list_due(self, db: Any, *, limit: int = 200) -> List[Dict[str, Any]]:
        due = []
        for row in self.rows.values():
            seconds = CADENCE_SECONDS.get(row["cadence"])
            if seconds is None or not self.tenant_enabled.get(row["tenant_id"], True):
                continue
            if row["next_check_after"] is not None and row["next_check_after"] > self.now:
                continue
            if row["last_checked_at"] is not None and row["last_checked_at"] > self.now - timedelta(seconds=seconds):
                continue
            due.append(self.get_refresh_for_check(db, row["project_id"]))
        return due[:limit]

    def record_success(self, db: Any, project_id: str, *, status: str, fingerprint: str) -> None:
        self.rows[project_id].update(
            status=status,
            last_fingerprint=fingerprint,
            last_checked_at=self.now,
            last_success_at=self.now,
            last_error=None,
            consecutive_failures=0,
            next_check_after=None,
        )

    def record_failure(self, db: Any, project_id: str, *, error: str, backoff_seconds: float) -> None:
        row = self.rows[project_id]
        row.update(
            status="failed",
            last_error=error,
            last_checked_at=self.now,
            last_failure_at=self.now,
            consecutive_failures=row["consecutive_failures"] + 1,
            next_check_after=self.now + timedelta(seconds=backoff_seconds),
        )

    def get_tenant_refresh_enabled(self, db: Any, tenant_id: str) -> bool:
        return self.tenant_enabled.get(tenant_id, True)

    def set_tenant_refresh_enabled(self, db: Any, tenant_id: str, enabled: bool) -> bool:
        self.tenant_enabled[tenant_id] = bool(enabled)
        return bool(enabled)

    # -- wiring ------------------------------------------------------------------------

    def install(self, monkeypatch) -> "FakeRefreshStore":
        """Patch the real store module's functions with this fake's methods."""
        for name in (
            "get_refresh",
            "get_refresh_for_check",
            "upsert_refresh",
            "delete_refresh",
            "list_due",
            "record_success",
            "record_failure",
            "get_tenant_refresh_enabled",
            "set_tenant_refresh_enabled",
        ):
            monkeypatch.setattr(catalog_refresh_store, name, getattr(self, name))
        return self
