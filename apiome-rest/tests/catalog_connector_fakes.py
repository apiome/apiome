"""In-memory stand-ins for catalog connector storage (CDG-1.1, #5952).

:class:`FakeConnectorStore` replaces every function of :mod:`app.catalog_connector_store` with
the same signature over dicts, so the sync engine and the routes run without Postgres. The live
SQL is covered separately by ``test_catalog_connector_store_live.py``.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

from app import catalog_connector_store as real_store
from app.catalog_connectors import (
    CODE_NAME_TAKEN,
    ITEM_DISCOVERED,
    ITEM_IGNORED,
    ITEM_IMPORTED,
    ITEM_MISSING,
    STATUS_PAUSED,
    ConnectorError,
)
from app.refresh_source import RefreshCandidate

_FUNCTIONS = [name for name in real_store.__all__]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeConnectorStore:
    """Connectors, inventory, credentials and runs, in memory."""

    def __init__(self) -> None:
        self.connectors: Dict[str, Dict[str, Any]] = {}
        self.items: Dict[str, Dict[str, Any]] = {}
        self.credentials: Dict[str, Dict[str, Any]] = {}
        self.runs: Dict[str, Dict[str, Any]] = {}
        self._clock = itertools.count()

    def install(self, monkeypatch) -> "FakeConnectorStore":
        """Patch every store function on the real module (callers look them up at call time)."""
        for name in _FUNCTIONS:
            monkeypatch.setattr(real_store, name, getattr(self, name))
        return self

    # --- helpers --------------------------------------------------------------------

    def add_connector(self, tenant_id: str, **fields: Any) -> Dict[str, Any]:
        """Seed a connector directly."""
        cid = fields.pop("id", None) or str(uuid.uuid4())
        row = {
            "id": cid,
            "tenant_id": tenant_id,
            "kind": "kong-admin",
            "name": f"conn-{cid[:4]}",
            "base_url": None,
            "scope": {},
            "refresh_interval_seconds": None,
            "conflict_policy": "hold-for-review",
            "status": "active",
            "last_run_at": None,
            "created_by": None,
            "created_at": _now(),
            "updated_at": _now(),
            "deleted_at": None,
        }
        row.update(fields)
        self.connectors[cid] = row
        return self._view(row)

    def _view(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        out["has_credentials"] = row["id"] in self.credentials
        return out

    def item(self, connector_id: str, remote_id: str) -> Dict[str, Any]:
        """The inventory row for one remote id."""
        return next(
            i for i in self.items.values() if i["connector_id"] == connector_id and i["remote_id"] == remote_id
        )

    # --- connectors -----------------------------------------------------------------

    def list_connectors(self, db, tenant_id):
        rows = [r for r in self.connectors.values() if r["tenant_id"] == tenant_id and r["deleted_at"] is None]
        return [self._view(r) for r in sorted(rows, key=lambda r: r["name"].lower())]

    def get_connector(self, db, tenant_id, connector_id):
        row = self.connectors.get(str(connector_id))
        if not row or row["tenant_id"] != tenant_id or row["deleted_at"] is not None:
            return None
        return self._view(row)

    def _name_taken(self, tenant_id, name, except_id=None):
        return any(
            r["tenant_id"] == tenant_id
            and r["deleted_at"] is None
            and r["name"].lower() == name.lower()
            and r["id"] != except_id
            for r in self.connectors.values()
        )

    def create_connector(self, db, tenant_id, **fields):
        if self._name_taken(tenant_id, fields["name"]):
            raise ConnectorError(CODE_NAME_TAKEN, "taken")
        return self.add_connector(tenant_id, **fields)

    def update_connector(self, db, tenant_id, connector_id, changes):
        row = self.get_connector(db, tenant_id, connector_id)
        if row is None:
            return None
        if "name" in changes and self._name_taken(tenant_id, changes["name"], except_id=connector_id):
            raise ConnectorError(CODE_NAME_TAKEN, "taken")
        self.connectors[connector_id].update(changes)
        return self.get_connector(db, tenant_id, connector_id)

    def soft_delete_connector(self, db, tenant_id, connector_id):
        row = self.get_connector(db, tenant_id, connector_id)
        if row is None:
            return None
        self.connectors[connector_id].update(deleted_at=_now(), status=STATUS_PAUSED)
        self.credentials.pop(connector_id, None)
        return {"id": connector_id, "name": row["name"], "kind": row["kind"]}

    def list_due_connectors(self, db, *, default_interval_seconds, floor_seconds):
        live = [r for r in self.connectors.values() if r["deleted_at"] is None]
        return [self._view(r) for r in live if r["status"] != STATUS_PAUSED]

    def record_connector_outcome(self, db, connector_id, *, status):
        row = self.connectors[connector_id]
        row["last_run_at"] = _now()
        if status is not None and row["status"] != STATUS_PAUSED:
            row["status"] = status

    # --- credentials ----------------------------------------------------------------

    def put_credentials(self, db, connector_id, *, encrypted_payload, key_version, created_by):
        self.credentials[connector_id] = {
            "encrypted_payload": bytes(encrypted_payload),
            "key_version": key_version,
            "created_by": created_by,
            "replaced_at": _now(),
        }
        return {"connector_id": connector_id, "replaced_at": self.credentials[connector_id]["replaced_at"]}

    def get_sealed_credentials(self, db, connector_id):
        row = self.credentials.get(connector_id)
        return {"encrypted_payload": row["encrypted_payload"], "key_version": row["key_version"]} if row else None

    # --- inventory ------------------------------------------------------------------

    def list_item_rows(self, db, connector_id):
        return [dict(i) for i in self.items.values() if i["connector_id"] == connector_id]

    def list_items(self, db, connector_id, *, status, limit, offset):
        rows = [i for i in self.list_item_rows(db, connector_id) if status is None or i["status"] == status]
        rows.sort(key=lambda i: (i["remote_name"] or i["remote_id"]).lower())
        return rows[offset : offset + limit]

    def count_items(self, db, connector_id, *, status):
        return len([i for i in self.list_item_rows(db, connector_id) if status is None or i["status"] == status])

    def upsert_seen_item(self, db, connector_id, candidate: RefreshCandidate):
        existing = next(
            (
                i
                for i in self.items.values()
                if i["connector_id"] == connector_id and i["remote_id"] == candidate.remote_id
            ),
            None,
        )
        seen = {
            "remote_name": candidate.name,
            "environment": candidate.environment,
            "hosts": list(candidate.hosts),
            "base_path": candidate.base_path,
            "remote_revision": candidate.revision,
            "remote_updated_at": candidate.updated_at,
            "deployment": dict(candidate.deployment or {}),
            "last_seen_at": _now(),
        }
        inserted = existing is None
        if existing is None:
            existing = {
                "id": str(uuid.uuid4()),
                "connector_id": connector_id,
                "remote_id": candidate.remote_id,
                "imported_revision": None,
                "imported_remote_updated_at": None,
                "imported_sha256": None,
                "status": ITEM_DISCOVERED,
                "project_id": None,
                "first_seen_at": _now(),
            }
            self.items[existing["id"]] = existing
        else:
            if existing["status"] != ITEM_IGNORED:
                existing["status"] = ITEM_IMPORTED if existing["project_id"] else ITEM_DISCOVERED
        existing.update(seen)
        return {**existing, "inserted": inserted}

    def mark_missing_items(self, db, connector_id, seen_remote_ids: Iterable[str]):
        seen = set(seen_remote_ids)
        changed = 0
        for item in self.items.values():
            if item["connector_id"] != connector_id or item["remote_id"] in seen:
                continue
            if item["status"] in (ITEM_MISSING, ITEM_IGNORED):
                continue
            item["status"] = ITEM_MISSING
            changed += 1
        return changed

    def mark_item_imported(self, db, item_id, *, project_id, revision, remote_updated_at, content_sha256):
        self.items[item_id].update(
            status=ITEM_IMPORTED,
            project_id=project_id,
            imported_revision=revision,
            imported_remote_updated_at=remote_updated_at,
            imported_sha256=content_sha256,
        )

    # --- runs -----------------------------------------------------------------------

    def start_run(self, db, tenant_id, connector_id, *, trigger, created_by):
        if any(r["connector_id"] == connector_id and r["status"] in ("queued", "running") for r in self.runs.values()):
            return None
        run_id = str(uuid.uuid4())
        row = {
            "id": run_id,
            "tenant_id": tenant_id,
            "connector_id": connector_id,
            "refresh_source": "connector",
            "status": "running",
            "error_class": None,
            "http_status": None,
            "error_message": None,
            "pull_count": 0,
            "run_summary": {"trigger": trigger},
            "created_by": created_by,
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": None,
            "_seq": next(self._clock),
        }
        self.runs[run_id] = row
        return dict(row)

    def finish_run(
        self, db, run_id, *, status, pull_count, summary, error_class=None, http_status=None, error_message=None
    ):
        self.runs[run_id].update(
            status=status,
            pull_count=pull_count,
            run_summary=dict(summary),
            error_class=error_class,
            http_status=http_status,
            error_message=error_message,
            finished_at=_now(),
        )

    def _ledger(self, tenant_id, connector_id, source):
        rows = [
            {
                **r,
                "connector_name": (self.connectors.get(r.get("connector_id") or "") or {}).get("name"),
                "connector_kind": (self.connectors.get(r.get("connector_id") or "") or {}).get("kind"),
            }
            for r in self.runs.values()
            if r["tenant_id"] == tenant_id
            and (connector_id is None or r.get("connector_id") == connector_id)
            and (source is None or r.get("refresh_source") == source)
        ]
        rows.sort(key=lambda r: r["_seq"], reverse=True)
        return rows

    def list_refresh_runs(self, db, tenant_id, *, connector_id, source, limit, offset):
        return self._ledger(tenant_id, connector_id, source)[offset : offset + limit]

    def count_refresh_runs(self, db, tenant_id, *, connector_id, source):
        return len(self._ledger(tenant_id, connector_id, source))

    def add_git_run(self, tenant_id: str, **fields: Any) -> Dict[str, Any]:
        """A Git refresh job on the shared ledger (the sync engine never writes these)."""
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "refresh_source": "git",
            "connector_id": None,
            "repository_id": str(uuid.uuid4()),
            "repository_full_name": "acme/specs",
            "branch": "main",
            "path": "openapi.yaml",
            "status": "succeeded",
            "refresh_reason": "newer-content",
            "error_class": None,
            "http_status": None,
            "error_message": None,
            "pull_count": 1,
            "run_summary": None,
            "created_at": _now(),
            "started_at": _now(),
            "finished_at": _now(),
            "_seq": next(self._clock),
            **fields,
        }
        self.runs[row["id"]] = row
        return row

    def list_runs(self, db, tenant_id, connector_id, *, limit, offset):
        rows = [r for r in self.runs.values() if r["tenant_id"] == tenant_id and r["connector_id"] == connector_id]
        rows.sort(key=lambda r: r["_seq"], reverse=True)
        return [dict(r) for r in rows[offset : offset + limit]]

    def count_runs(self, db, tenant_id, connector_id):
        return len([r for r in self.runs.values() if r["tenant_id"] == tenant_id and r["connector_id"] == connector_id])


class FakeDb:
    """The two database calls the sync engine makes besides the store: audit and quota."""

    def __init__(self) -> None:
        self.audits: List[Dict[str, Any]] = []
        self.quota: List[Dict[str, Any]] = []

    def insert_workflow_audit(self, tenant_id, project_id, version_id, action, outcome, actor_id, detail=None):
        self.audits.append(
            {
                "tenant_id": tenant_id,
                "action": action,
                "outcome": outcome,
                "actor_id": actor_id,
                "detail": detail,
            }
        )

    def increment_repository_quota_window(self, *, tenant_id, metric, window_kind, window_start, amount):
        self.quota.append({"tenant_id": tenant_id, "metric": metric, "window_kind": window_kind, "amount": amount})

    def quota_total(self, metric: str) -> int:
        return sum(q["amount"] for q in self.quota if q["metric"] == metric)

    # Project tags (CDG-1.4: a source's ``after_import`` hook tags the catalog item).
    def get_tags_for_project(self, project_id):
        return [dict(t) for t in getattr(self, "tags", []) if t["project_id"] == project_id]

    def create_tag(self, project_id, name, color="default", description=None):
        self.tags = getattr(self, "tags", [])
        tag = {
            "id": f"tag-{len(self.tags) + 1}",
            "project_id": project_id,
            "name": name,
            "color": color,
            "description": description,
        }
        self.tags.append(tag)
        return tag

    def delete_tag(self, tag_id):
        before = len(getattr(self, "tags", []))
        self.tags = [t for t in getattr(self, "tags", []) if t["id"] != tag_id]
        return len(self.tags) < before


def restore_builtin_sources() -> None:
    """Re-register the sources the app ships (tests that swap in a fake source call this after)."""
    from app import apigee_connector_source as apigee
    from app import aws_apigateway_connector_source as aws
    from app import azure_apim_connector_source as azure
    from app import kong_connector_source as kong
    from app.catalog_connector_sync import register_connector_source

    register_connector_source(
        aws.KIND,
        aws.AwsApiGatewaySource,
        scope_validator=aws.validate_aws_scope,
        connection_check=aws.check_aws_connection,
        accepts_credentials=False,
    )

    register_connector_source(azure.KIND, azure.AzureApimSource, scope_validator=azure.validate_azure_scope)
    register_connector_source(apigee.KIND, apigee.ApigeeSource, scope_validator=apigee.validate_apigee_scope)
    register_connector_source(kong.KIND_KONNECT, kong.KongKonnectSource, scope_validator=kong.validate_konnect_scope)
    register_connector_source(kong.KIND_ADMIN, kong.KongAdminSource, scope_validator=kong.validate_admin_scope)
