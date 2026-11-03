"""The catalog ``url`` connector source (RAR-6.1b, #6467).

Catalog items imported from a **Document URL** keep the URL on their version (``format_metadata``
``inputKind: "url"``, ``sourceUri``) but nothing ever looked at it again. A ``url`` connector refreshes
them on the connector cadence, through the same sync engine, run ledger and Refresh history as every
other connector (:mod:`app.catalog_connector_sync`). It has two modes:

* **Workspace mode** — no base URL (the connector the V352 backfill creates per tenant, *Catalog
  URLs*). Its inventory is every live URL-sourced catalog item of the tenant, one row per item
  (``remote_id`` = the catalog item id), linked to that item so a change lands as a new revision of
  it. A URL catalog import made later joins on the next run. Only the oldest workspace-mode ``url``
  connector of a tenant acts; any other lists nothing and says why (a finding), so no item is
  refreshed twice.
* **Single-URL mode** — the base URL is a specification URL (the "Specification URL" the add-connector
  form asks for). Its inventory is that one URL; the first run imports it as a new catalog item, and
  later runs refresh it like any connector item.

**One check per item.** Listing re-fetches each URL with ``If-None-Match`` / ``If-Modified-Since``
(:func:`app.url_import_refresh.conditional_headers`), validators kept on the inventory row's
``deployment``:

* **304** — the candidate reports the digest of the content those validators describe (kept beside
  them), so the engine counts it *unchanged* once that content is imported;
* **200** — the candidate's revision is the SHA-256 of the body (kept for :meth:`UrlConnectorSource.fetch`),
  so the engine's RAR-2.2 gate (:func:`app.refresh_source.decide_refresh`) fetches and imports changed
  content as a new revision, and re-anchors identical content without one;
* **an error** — the candidate is marked so the engine fetches it, and :meth:`UrlConnectorSource.fetch`
  raises the stored :class:`~app.refresh_source.RefreshSourceError`: a *failed* item on the run.

**Baseline.** An item with no import anchor yet (a backfilled item's first run) is anchored to what the
first 200 returned, without a new revision — the same "baseline" rule as
:func:`app.url_import_refresh.decide_check` — so introducing the connector never re-imports every item.

**SSRF.** Every URL passes the connector rule of CDG-1.1
(:func:`app.catalog_connectors.connector_base_url_from_settings`), and the request goes through
:func:`app.catalog_connectors.build_connector_http_client`, which re-checks every redirect hop.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .refresh_source import ERROR_CLASS_UNEXPECTED, FetchedDocument, RefreshCandidate, RefreshSourceError
from .url_import_refresh import checksum_bytes, conditional_headers

__all__ = [
    "KIND",
    "WORKSPACE_CONNECTOR_NAME",
    "UrlConnectorSource",
    "list_url_sourced_catalog_items",
]

_logger = logging.getLogger(__name__)

#: The connector kind.
KIND = "url"
#: The name of the workspace-mode connector the V352 backfill creates.
WORKSPACE_CONNECTOR_NAME = "Catalog URLs"
#: Largest document one check reads (the URL-import refresh's own cap).
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
_USER_AGENT = "Apiome-UrlConnector/1.0"
#: The revision a candidate reports when its check failed: never equal to a stored one.
_ERROR_REVISION_PREFIX = "error:"
#: Finding code for a second workspace-mode ``url`` connector, which lists nothing.
FINDING_DUPLICATE_WORKSPACE = "url-workspace-connector-duplicate"
#: Finding code for an item whose stored URL the connector rule refuses.
FINDING_URL_REFUSED = "url-refused"


@dataclass(frozen=True)
class _Check:
    """What one conditional GET found for one inventory entry.

    Attributes:
        status_code: 304, the 2xx, or ``None`` when the check failed.
        body: The document on a 2xx.
        etag: The validators to send next time.
        last_modified: The ``Last-Modified`` validator (kept as sent by the server).
        content_type: The response's ``Content-Type``.
        error: The failure, when the check failed.
    """

    status_code: Optional[int]
    body: bytes = b""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_type: Optional[str] = None
    error: Optional[RefreshSourceError] = None


def list_url_sourced_catalog_items(db: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """Every live catalog item of a tenant whose latest version was imported from a URL.

    That is a **Document URL** import (``inputKind: "url"``), or a revision this connector's
    workspace mode already refreshed (``inputKind: "connector"``, ``connectorKind: "url"`` and the
    item's own id as ``remoteId``) — so an item stays covered after its first refresh. A single-URL
    connector's items (``remoteId`` is the URL) belong to that connector and are left out.

    Args:
        db: Database handle.
        tenant_id: The tenant.

    Returns:
        Rows with ``project_id``, ``name``, ``url`` (the stored ``sourceUri``) and ``source_format``,
        ordered by name.
    """
    return db.execute_query(
        """
        SELECT p.id AS project_id, p.name, v.format_metadata->>'sourceUri' AS url, v.source_format
        FROM apiome.projects p
        JOIN LATERAL (
            SELECT format_metadata, source_format
            FROM apiome.versions
            WHERE project_id = p.id
            ORDER BY created_at DESC
            LIMIT 1
        ) v ON TRUE
        WHERE p.tenant_id = %s::uuid
          AND p.deleted_at IS NULL
          AND p.publishable = FALSE
          AND (
            v.format_metadata->>'inputKind' = 'url'
            OR (
              v.format_metadata->>'inputKind' = 'connector'
              AND v.format_metadata->>'connectorKind' = 'url'
              AND v.format_metadata->>'remoteId' = p.id::text
            )
          )
          AND COALESCE(v.format_metadata->>'sourceUri', '') ~* '^https?://'
        ORDER BY p.name
        """,
        (tenant_id,),
    )


def _parse_last_modified(value: Optional[str]) -> Optional[Any]:
    """An HTTP date as an aware datetime, or ``None`` when absent or unreadable."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class UrlConnectorSource(ConnectorRefreshSource):
    """A ``url`` connector: workspace mode (no base URL) or single-URL mode. See the module docstring.

    Args:
        connector: The connector row (``tenant_id``, ``id``, ``base_url``, ``created_at`` …).
        credentials: Unused: a ``url`` connector stores none.
        client: An HTTP client for tests; the connector's guarded client by default.
    """

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self._client = client
        self._db: Any = None
        self._checks: Dict[str, _Check] = {}
        self._targets: Dict[str, Dict[str, Any]] = {}
        #: Credential-free findings the run records in its summary.
        self.findings: List[Dict[str, Any]] = []

    # -- engine hooks -----------------------------------------------------------------------

    def bind_db(self, db: Any) -> None:
        """Receive the database handle (workspace mode reads the catalog and the inventory)."""
        self._db = db

    @property
    def workspace_mode(self) -> bool:
        """True when the connector has no base URL and covers every URL-sourced catalog item."""
        return not str(self.connector.get("base_url") or "").strip()

    def list_candidates(self) -> Sequence[RefreshCandidate]:
        """Check every URL the connector covers, and describe each as a candidate.

        Returns:
            One candidate per URL: the catalog item (workspace mode) or the specification URL.
        """
        targets = self._list_targets()
        stored = self._stored_inventory()
        candidates: List[RefreshCandidate] = []
        for target in targets:
            remote_id = target["remote_id"]
            self._targets[remote_id] = target
            row = stored.get(remote_id) or {}
            deployment = row.get("deployment") if isinstance(row.get("deployment"), Mapping) else {}
            same_url = deployment.get("url") == target["url"]
            check = self._check(
                target["url"],
                etag=deployment.get("etag") if same_url else None,
                last_modified=deployment.get("lastModified") if same_url else None,
            )
            self._checks[remote_id] = check
            candidates.append(self._candidate(target, row, deployment, check))
        return candidates

    def attach_inventory(self, rows_by_remote_id: Mapping[str, Mapping[str, Any]]) -> None:
        """Link workspace-mode rows to their catalog items and anchor first-seen content (baseline).

        A workspace-mode row backs an existing catalog item, so it is linked to it before the engine
        gates it. A row with no import anchor yet takes the content the check just read as its
        anchor, without a new revision — the URL-import "baseline" rule.
        """
        super().attach_inventory(rows_by_remote_id)
        from . import catalog_connector_store as store

        for remote_id, row in rows_by_remote_id.items():
            target = self._targets.get(remote_id) or {}
            project_id = row.get("project_id") or target.get("project_id")
            check = self._checks.get(remote_id)
            if not project_id or row.get("imported_sha256") or check is None or not check.body:
                continue
            digest = checksum_bytes(check.body)
            store.mark_item_imported(
                self._db,
                str(row["id"]),
                project_id=str(project_id),
                revision=digest,
                remote_updated_at=_parse_last_modified(check.last_modified),
                content_sha256=digest,
            )
            if isinstance(row, dict):
                row.update(
                    project_id=str(project_id),
                    imported_revision=digest,
                    imported_remote_updated_at=_parse_last_modified(check.last_modified),
                    imported_sha256=digest,
                    status="imported",
                )

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """The document the check read, re-read without validators when it only got a 304.

        Raises:
            RefreshSourceError: The check failed, or the re-read did.
        """
        check = self._checks.get(candidate.remote_id)
        target = self._targets.get(candidate.remote_id) or {}
        url = target.get("url") or str(self.connector.get("base_url") or "")
        if check is not None and check.error is not None:
            raise check.error
        if check is None or not check.body:
            check = self._check(url)
            if check.error is not None:
                raise check.error
        return FetchedDocument(
            content=check.body,
            filename=url.rstrip("/").rsplit("/", 1)[-1] or "document",
            import_kind=self._import_kind(check, url, target),
            revision=checksum_bytes(check.body),
            source_uri=url,
        )

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, mode}``."""
        return {**super().describe(), "mode": "workspace" if self.workspace_mode else "url"}

    # -- helpers ----------------------------------------------------------------------------

    def _database(self) -> Any:
        if self._db is None:
            from .database import db

            self._db = db
        return self._db

    def _list_targets(self) -> List[Dict[str, Any]]:
        """The URLs this connector covers: ``remote_id``, ``url``, ``name``, ``project_id``, format."""
        from .catalog_connectors import connector_base_url_from_settings

        if not self.workspace_mode:
            url = str(self.connector.get("base_url")).strip()
            return [{"remote_id": url, "url": url, "name": None, "project_id": None, "source_format": None}]
        if not self._acts_for_workspace():
            return []
        targets: List[Dict[str, Any]] = []
        for item in list_url_sourced_catalog_items(self._database(), str(self.connector["tenant_id"])):
            url = str(item.get("url") or "").strip()
            try:
                url = connector_base_url_from_settings(url)
            except Exception as exc:  # noqa: BLE001 - a refused URL is reported, not fatal
                self.findings.append(
                    {"code": FINDING_URL_REFUSED, "remoteId": str(item["project_id"]), "detail": str(exc)}
                )
                continue
            targets.append(
                {
                    "remote_id": str(item["project_id"]),
                    "url": url,
                    "name": item.get("name"),
                    "project_id": str(item["project_id"]),
                    "source_format": item.get("source_format"),
                }
            )
        return targets

    def _acts_for_workspace(self) -> bool:
        """Whether this is the tenant's oldest live workspace-mode ``url`` connector."""
        rows = self._database().execute_query(
            """
            SELECT id FROM apiome.catalog_connectors
            WHERE tenant_id = %s::uuid AND kind = 'url' AND deleted_at IS NULL
              AND COALESCE(btrim(base_url), '') = ''
            ORDER BY created_at, id
            LIMIT 1
            """,
            (str(self.connector["tenant_id"]),),
        )
        first = str(rows[0]["id"]) if rows else None
        if first is None or first == str(self.connector.get("id")):
            return True
        self.findings.append(
            {
                "code": FINDING_DUPLICATE_WORKSPACE,
                "detail": "Another url connector with no base URL already refreshes this workspace's "
                "URL-sourced catalog items.",
            }
        )
        return False

    def _stored_inventory(self) -> Dict[str, Mapping[str, Any]]:
        """The connector's inventory rows by remote id (their stored validators and anchors)."""
        if self._db is None or not self.connector.get("id"):
            return {}
        from . import catalog_connector_store as store

        try:
            rows = store.list_item_rows(self._db, str(self.connector["id"]))
        except Exception:  # noqa: BLE001 - a dry run has no inventory
            return {}
        return {str(r.get("remote_id")): r for r in rows}

    def _check(self, url: str, *, etag: Optional[str] = None, last_modified: Optional[str] = None) -> _Check:
        """One conditional GET of ``url`` through the connector's guarded client; never raises."""
        from .catalog_connectors import build_connector_http_client, connector_base_url_from_settings

        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, application/yaml, text/yaml, application/xml, text/plain, */*",
            **conditional_headers(etag, last_modified),
        }
        try:
            connector_base_url_from_settings(url)
        except Exception as exc:  # noqa: BLE001 - the connector rule refused the address
            return _Check(
                status_code=None,
                error=RefreshSourceError(f"The URL is not one Apiome fetches: {exc}", error_class="blocked"),
            )
        owned = self._client is None
        http = self._client or build_connector_http_client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
        try:
            with http.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 304:
                    return _Check(status_code=304, etag=etag, last_modified=last_modified)
                if not 200 <= resp.status_code < 300:
                    return _Check(
                        status_code=None,
                        error=RefreshSourceError(
                            f"The URL answered HTTP {resp.status_code}.", http_status=resp.status_code
                        ),
                    )
                chunks: List[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_DOCUMENT_BYTES:
                        return _Check(
                            status_code=None,
                            error=RefreshSourceError(
                                f"The document is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.",
                                error_class=ERROR_CLASS_UNEXPECTED,
                            ),
                        )
                    chunks.append(chunk)
                return _Check(
                    status_code=resp.status_code,
                    body=b"".join(chunks),
                    etag=resp.headers.get("etag"),
                    last_modified=resp.headers.get("last-modified"),
                    content_type=resp.headers.get("content-type"),
                )
        except httpx.HTTPError as exc:
            return _Check(
                status_code=None,
                error=RefreshSourceError(f"The URL could not be reached ({type(exc).__name__})."),
            )
        except RefreshSourceError as exc:
            return _Check(status_code=None, error=exc)
        except Exception as exc:  # noqa: BLE001 - e.g. the guard refusing a redirect hop
            return _Check(
                status_code=None,
                error=RefreshSourceError(f"The URL could not be fetched: {exc}", error_class="blocked"),
            )
        finally:
            if owned:
                http.close()

    def _candidate(
        self,
        target: Mapping[str, Any],
        row: Mapping[str, Any],
        deployment: Mapping[str, Any],
        check: _Check,
    ) -> RefreshCandidate:
        """The candidate for one checked URL (see the module docstring for the three outcomes)."""
        if check.error is not None:
            revision = _ERROR_REVISION_PREFIX + hashlib.sha256(str(check.error).encode()).hexdigest()[:16]
            new_deployment = dict(deployment)
            updated_at = row.get("remote_updated_at")
        elif check.status_code == 304:
            # The validators describe the content whose digest the 200 that stored them recorded.
            revision = deployment.get("sha256") or row.get("imported_revision") or row.get("remote_revision")
            new_deployment = dict(deployment)
            updated_at = row.get("remote_updated_at")
        else:
            revision = checksum_bytes(check.body)
            new_deployment = {
                "url": target["url"],
                "etag": check.etag,
                "lastModified": check.last_modified,
                "sha256": revision,
            }
            updated_at = _parse_last_modified(check.last_modified)
        new_deployment["url"] = target["url"]
        return RefreshCandidate(
            remote_id=str(target["remote_id"]),
            name=target.get("name") or target["url"],
            revision=revision,
            updated_at=updated_at,
            raw={"url": target["url"]},
            deployment=new_deployment,
        )

    def _import_kind(self, check: _Check, url: str, target: Mapping[str, Any]) -> str:
        """The importer for the document: detected from its content, else the item's recorded format."""
        from .format_detection import detect_format
        from .import_source import DetectionInput

        try:
            text = check.body.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        try:
            detection = detect_format(
                DetectionInput(text=text, url=url, content_type=check.content_type, data=check.body)
            )
            if detection.detected is not None and detection.detected.importable and detection.detected.source_key:
                return str(detection.detected.source_key)
        except Exception:  # noqa: BLE001 - detection failing falls back to the recorded format
            _logger.debug("url connector format detection failed url=%s", url, exc_info=True)
        return str(target.get("source_format") or "openapi")


def _factory(connector: Mapping[str, Any], credentials: Optional[Dict[str, str]]) -> UrlConnectorSource:
    """Registry factory: one source per run."""
    return UrlConnectorSource(connector, credentials)


def validate_url_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """A ``url`` connector takes no scope: the base URL (or its absence) says what it covers.

    Args:
        scope: The submitted scope.
        base_url: The submitted base URL, already through the SSRF rule; ``None`` for workspace mode.

    Raises:
        ConnectorError: ``connector-invalid`` when the scope names anything.
    """
    from .catalog_connectors import CODE_INVALID, ConnectorError

    if scope:
        raise ConnectorError(
            CODE_INVALID,
            "A url connector takes no scope: give a specification URL as the base URL, or none to "
            "refresh every catalog item imported from a URL.",
        )


register_connector_source(KIND, _factory, scope_validator=validate_url_scope, accepts_credentials=False)
