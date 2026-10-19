"""In-memory doubles for the schema registry tests (CDG-4.2 #5974, CDG-4.3 #5975).

:class:`FakeCatalog` stands in for the catalog (items, revisions) and for the import pipeline
(``run_adapter_import_job``: one call → one revision); :class:`FakeStore` keeps the same contract as
:mod:`app.schema_registry_store`, whose SQL is exercised separately (scripted connection + a scratch
database built from V294).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.schema_registry import FINGERPRINT_KIND, SchemaRegistryError

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class FakeCatalog:
    """Catalog items and revisions, plus the ``db`` methods the service calls."""

    def __init__(self) -> None:
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.revisions: Dict[str, Dict[str, Any]] = {}
        self.imports: List[Dict[str, Any]] = []
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def add_item(self, name: str, revisions: List[Dict[str, Any]], *, publishable: bool = False) -> str:
        pid = self._id("item")
        self.projects[pid] = {"id": pid, "name": name, "publishable": publishable, "deleted": False}
        for rev in revisions:
            self.add_revision(pid, **rev)
        return pid

    def add_revision(self, project_id: str, *, label: str, source_format: str, format_metadata: Dict[str, Any]) -> str:
        rid = self._id("rev")
        self.revisions[rid] = {
            "id": rid,
            "project_id": project_id,
            "version_id": label,
            "source_format": source_format,
            "format_metadata": format_metadata,
            "order": self._n,
        }
        return rid

    def item_revisions(self, project_id: str) -> List[Dict[str, Any]]:
        return sorted((r for r in self.revisions.values() if r["project_id"] == project_id), key=lambda r: r["order"])

    # --- db surface ---
    def get_catalog_item_by_id(self, item_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        p = self.projects.get(item_id)
        return p if p and not p["deleted"] and not p["publishable"] else None

    def allocate_version_id(self, project_id: str, base: str) -> str:
        taken = {r["version_id"] for r in self.item_revisions(project_id)}
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def allocate_project_slug(self, tenant_id: str, base: str) -> str:
        return base

    async def run_import(self, adapter: Any, payload: Dict[str, Any]) -> Any:
        """Stand-in for ``run_adapter_import_job``: one call → one revision."""
        self.imports.append(payload)
        meta = payload["metadata"]
        pid = meta["existing_project_id"] or self.add_item(meta["project"]["name"], [])
        content = payload["document_base64"]
        rid = self.add_revision(
            pid,
            label=meta["version"]["version_id"],
            source_format=adapter.key if adapter.key != "grpc" else "protobuf",
            format_metadata={"sourceContent": base64.standard_b64decode(content).decode("utf-8")},
        )
        return SimpleNamespace(
            state="completed", error=None, result=SimpleNamespace(project_id=pid, version_record_id=rid)
        )


class FakeStore:
    """In-memory store with the same contract as :mod:`app.schema_registry_store`."""

    def __init__(self, catalog: FakeCatalog) -> None:
        self.catalog = catalog
        self.config = {"compatibility_level": "BACKWARD", "mode": "READWRITE"}
        self.subjects: List[Dict[str, Any]] = []
        self.schemas: List[Dict[str, Any]] = []
        self.versions: List[Dict[str, Any]] = []

    def get_config(self, db, tenant_id):
        return dict(self.config)

    def get_subject(self, db, tenant_id, name):
        return next((s for s in self.subjects if s["name"] == name and not s["deleted_at"]), None)

    def list_versions(self, db, subject_id):
        return sorted(
            (v for v in self.versions if v["subject_id"] == subject_id and not v["deleted_at"]),
            key=lambda v: v["version"],
        )

    def get_version(self, db, subject_id, version):
        return next((v for v in self.list_versions(db, subject_id) if v["version"] == int(version)), None)

    def next_version_number(self, db, subject_id):
        return max((v["version"] for v in self.versions if v["subject_id"] == subject_id), default=0) + 1

    def find_version_by_fingerprint(self, db, subject_id, schema_type, fingerprint):
        return next(
            (
                v
                for v in self.list_versions(db, subject_id)
                if v["schema_type"] == schema_type and v["fingerprint"] == fingerprint
            ),
            None,
        )

    def get_schema_by_fingerprint(self, db, tenant_id, schema_type, fingerprint):
        return next(
            (s for s in self.schemas if s["schema_type"] == schema_type and s["fingerprint"] == fingerprint), None
        )

    def get_latest_live_revision(self, db, tenant_id, project_id):
        if self.catalog.get_catalog_item_by_id(project_id, tenant_id) is None:
            return None
        revs = self.catalog.item_revisions(project_id)
        return dict(revs[-1]) if revs else None

    def get_revision_source(self, db, version_record_id):
        rev = self.catalog.revisions.get(str(version_record_id))
        return dict(rev) if rev else None

    def list_subject_names(self, db, tenant_id, *, include_deleted=False):
        return sorted({s["name"] for s in self.subjects if include_deleted or not s["deleted_at"]})

    def put_config(self, db, tenant_id, *, compatibility_level, mode):
        if compatibility_level:
            self.config["compatibility_level"] = compatibility_level
        if mode:
            self.config["mode"] = mode
        return dict(self.config)

    def upsert_subject(self, db, tenant_id, name, *, strategy, compatibility_level, mode, actor_id):
        row = self.get_subject(db, tenant_id, name)
        if row is None:
            row = {"id": f"subject-{len(self.subjects) + 1}", "name": name, "strategy": strategy,
                   "compatibility_level": None, "mode": self.config["mode"], "project_id": None,
                   "deleted_at": None, "created_at": NOW, "updated_at": NOW}
            self.subjects.append(row)
        for key, value in (("strategy", strategy), ("compatibility_level", compatibility_level), ("mode", mode)):
            if value is not None:
                row[key] = value
        return row

    def hard_delete_subject(self, db, tenant_id, name):
        if self.get_subject(db, tenant_id, name) is not None:
            raise SchemaRegistryError("subject-not-soft-deleted", "live", status_code=404)
        gone = [s for s in self.subjects if s["name"] == name and s["deleted_at"]]
        if not gone:
            return None
        ids = {s["id"] for s in gone}
        versions = sorted(v["version"] for v in self.versions if v["subject_id"] in ids)
        self.versions = [v for v in self.versions if v["subject_id"] not in ids]
        self.subjects = [s for s in self.subjects if s["id"] not in ids]
        return versions

    def soft_delete_subject(self, db, tenant_id, name):
        subject = self.get_subject(db, tenant_id, name)
        if subject is None:
            return None
        subject["deleted_at"] = NOW
        deleted = [v for v in self.versions if v["subject_id"] == subject["id"] and not v["deleted_at"]]
        for v in deleted:
            v["deleted_at"] = NOW
        return [v["version"] for v in deleted]

    def get_schema_by_id(self, db, tenant_id, schema_id):
        row = next((s for s in self.schemas if s["schema_id"] == schema_id), None)
        if row is None:
            return None
        holders = [
            {"subject": s["name"], "version": v["version"]}
            for v in self.versions
            for s in self.subjects
            if v["subject_id"] == s["id"] and v["schema_id"] == schema_id and not v["deleted_at"] and not s["deleted_at"]
        ]
        holders.sort(key=lambda h: (h["subject"], h["version"]))  # the store's ORDER BY
        return {**row, "subjects": holders}

    def record_version(
        self,
        db,
        *,
        tenant_id,
        subject,
        schema_type,
        fingerprint,
        references,
        project_id,
        version_record_id,
        actor_id,
        strategy=None,
        subject_project_id=None,
        require_empty_subject=False,
    ):
        row = self.get_subject(db, tenant_id, subject)
        if row is None:
            row = {
                "id": f"subject-{len(self.subjects) + 1}",
                "name": subject,
                "strategy": strategy,
                "mode": self.config["mode"],
                "compatibility_level": None,
                "project_id": None,
                "deleted_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.subjects.append(row)
        if require_empty_subject:
            if row["project_id"] and row["project_id"] != subject_project_id:
                raise SchemaRegistryError("subject-attached-elsewhere", "x", status_code=409)
            if any(v["subject_id"] == row["id"] for v in self.versions):
                raise SchemaRegistryError("subject-has-versions", "x", status_code=409)
        if subject_project_id and not row["project_id"]:
            row["project_id"] = subject_project_id
        schema = self.get_schema_by_fingerprint(db, tenant_id, schema_type, fingerprint)
        if schema is None:
            schema = {
                "schema_id": len(self.schemas) + 1,
                "schema_type": schema_type,
                "fingerprint": fingerprint,
                "fingerprint_kind": FINGERPRINT_KIND,
                "project_id": project_id,
                "version_record_id": version_record_id,
                "references": references,
            }
            self.schemas.append(schema)
        existing = next(
            (v for v in self.versions if v["subject_id"] == row["id"] and v["schema_id"] == schema["schema_id"]), None
        )
        if existing:
            existing["deleted_at"] = None
            return {**existing, "created": False, "subject": subject, "subject_id": row["id"]}
        version = {
            "subject_id": row["id"],
            "version": self.next_version_number(db, row["id"]),
            "schema_id": schema["schema_id"],
            "schema_type": schema_type,
            "fingerprint": fingerprint,
            "references": references,
            "project_id": project_id,
            "version_record_id": version_record_id,
            "created_at": NOW,
            "deleted_at": None,
        }
        self.versions.append(version)
        return {**version, "created": True, "subject": subject, "subject_id": row["id"]}
