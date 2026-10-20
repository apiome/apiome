"""Schema-registry discovery connector: upstream subjects mirrored into the catalog — MFI-12.3 (#3784).

A ``schema-registry`` connector points at a registry that speaks the Confluent Schema Registry REST
API: Confluent Platform or Cloud, Karapace, or Apicurio Registry's compatibility API (base URL
``https://<apicurio>/apis/ccompat/v7``). It runs on the CDG-1.1 connector protocol — one cadence,
quota and ledger with every other connector — and it is **read-only**: nothing is ever written to
the upstream registry.

**Listing** (one inventory row per subject; the remote id is the subject name):

* ``GET /subjects`` — every live subject;
* ``GET /subjects/{s}/versions`` — its live version numbers;
* ``GET /config/{s}?defaultToGlobal=true`` — its compatibility level. A registry that answers
  ``404`` there (no subject-level setting, and no ``defaultToGlobal`` support) falls back to the
  global ``GET /config``, read once per sync.

The row's revision is the latest version number plus a digest of the version list and the level, so
a new version, a deleted version or a changed level all make the subject fresh again.

**Syncing one subject** (only subjects whose revision changed since the last sync — the engine's
``sync_item`` hook) mirrors it into the CDG-4.2 subject model (:mod:`app.schema_registry_store`):

1. **Ownership.** A subject of the same name that this connector does not mirror — registered in
   Apiome, or mirrored by another connector — is never written: the row stays ``discovered`` with
   reason ``subject-name-taken``.
2. **Each upstream version not mirrored yet**, oldest first: ``GET /subjects/{s}/versions/{v}``
   gives the global schema id, type, references and text. **Dedup by schema id:** an id already seen
   this sync, or already mirrored by this connector under any subject, reuses that schema's
   fingerprint and catalog revision with no parse and no import. When the version body carries no
   ``schema`` text, ``GET /schemas/ids/{id}`` supplies it. A new schema is parsed and fingerprinted
   by its import source (:func:`app.schema_registry.fingerprint_schema`); content the workspace
   already holds shares its schema id and revision, and only new content is imported through the
   pipeline as a new revision of the subject's catalog item, labelled with the upstream version
   number and carrying the connector provenance. The local version records the upstream version and
   schema id beside Apiome's own numbers.
3. **Settings.** The upstream compatibility level is copied onto the subject, and the subject naming
   strategy is inferred from the subject name and the schema's record name (Confluent's
   ``TopicNameStrategy`` ``<topic>-key|value``, ``RecordNameStrategy`` ``<record>``,
   ``TopicRecordNameStrategy`` ``<topic>-<record>``) when the subject states none.
4. **Deleted upstream versions** are soft-deleted on the mirror; their catalog revisions stay.

The subject provenance is ``source_ref = registry:<base URL>``. Compatibility checks are not run on
mirrored versions: the upstream registry already admitted them.

**Left ``discovered``, not failed:** a version whose schema refers to other subjects and cannot be
read on its own (``references-unsupported``), and a schema type this deployment cannot read
(``schema-type-unavailable``, Protobuf without the bundled ``buf``). Any other refusal fails the
subject for this run; the versions mirrored before it stay, and the next sync carries on from there.

**Credentials** are optional: ``{"username": "…", "password": "…"}`` is sent as HTTP basic auth
(Confluent Cloud: the API key and secret), ``{"token": "…"}`` as a bearer token. Every request goes
through :func:`app.catalog_connectors.build_connector_http_client`, which re-checks the SSRF rule on
every hop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx

from . import schema_registry_store as subject_store
from .catalog_connector_sync import ConnectorRefreshSource, ItemSyncOutcome, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, build_connector_http_client, connector_provenance_metadata
from .refresh_source import ERROR_CLASS_UNEXPECTED, FetchedDocument, RefreshCandidate, RefreshSourceError
from .schema_registry import (
    COMPATIBILITY_LEVELS,
    SCHEMA_TYPE_AVRO,
    SCHEMA_TYPE_JSON,
    SCHEMA_TYPE_PROTOBUF,
    SCHEMA_TYPES,
    STRATEGY_RECORD,
    STRATEGY_TOPIC,
    STRATEGY_TOPIC_RECORD,
    SchemaRegistryError,
    fingerprint_schema,
    intake_for,
)
from .ssrf_guard import SSRFError

_logger = logging.getLogger(__name__)

__all__ = [
    "KIND",
    "REASON_REFERENCES_UNSUPPORTED",
    "REASON_SCHEMA_TYPE_UNAVAILABLE",
    "REASON_SUBJECT_NAME_TAKEN",
    "SchemaRegistrySource",
    "SubjectState",
    "build_candidate",
    "infer_strategy",
    "normalize_registry_base",
    "parse_compatibility_level",
    "record_name",
    "source_ref",
    "subject_revision",
    "validate_schema_registry_scope",
]

KIND = "schema-registry"

#: The most subjects one sync lists; a larger registry fails the listing rather than syncing part of it.
MAX_SUBJECTS = 10_000

#: The media type Confluent-compatible registries answer with (plain JSON is accepted too).
ACCEPT = "application/vnd.schemaregistry.v1+json, application/vnd.schemaregistry+json, application/json"

#: Error class for a base URL that cannot address a registry.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"
#: Error class for a request the SSRF guard refused (a redirect or re-resolution to a private address).
ERROR_CLASS_ADDRESS_REFUSED = "address-refused"

#: Stable reason codes a subject stays ``discovered`` with (the stored reason is ``"<code>: <why>"``).
REASON_SUBJECT_NAME_TAKEN = "subject-name-taken"
REASON_REFERENCES_UNSUPPORTED = "references-unsupported"
REASON_SCHEMA_TYPE_UNAVAILABLE = "schema-type-unavailable"

#: Finding a sync reports for a compatibility level outside the seven Confluent levels.
FINDING_LEVEL_UNKNOWN = "registry-level-unknown"

_ERROR_DETAIL_MAX = 300
_PROTO_PACKAGE = re.compile(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", re.MULTILINE)
_PROTO_MESSAGE = re.compile(r"^\s*message\s+([A-Za-z_]\w*)", re.MULTILINE)


# ---------------------------------------------------------------------------------------
# Scope validation (run by the routes on every write)
# ---------------------------------------------------------------------------------------


def validate_schema_registry_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check a ``schema-registry`` connector: a base URL and no scope keys.

    Args:
        scope: The connector scope; this kind takes none.
        base_url: The registry URL (for Apicurio, its ``/apis/ccompat/v7`` compatibility API).

    Raises:
        ConnectorError: ``connector-invalid`` for a missing base URL or any scope key.
    """
    if not (base_url or "").strip():
        raise ConnectorError(
            CODE_INVALID,
            "A schema registry connector needs a base URL: the registry's REST address, for example "
            "https://psrc-123.eu-west-1.aws.confluent.cloud or https://apicurio.example.com/apis/ccompat/v7.",
        )
    if scope:
        raise ConnectorError(
            CODE_INVALID, f"A schema-registry connector takes no scope; got {', '.join(sorted(scope))}."
        )


def normalize_registry_base(url: str) -> str:
    """Return the registry root the API paths are appended to (trailing ``/`` and ``/subjects`` dropped)."""
    base = (url or "").strip().rstrip("/")
    if base.endswith("/subjects"):
        base = base[: -len("/subjects")].rstrip("/")
    return base


def source_ref(registry_url: str) -> str:
    """The subject provenance a mirrored subject records: ``registry:<url>``."""
    return f"registry:{registry_url}"


# ---------------------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SubjectState:
    """What the listing learned about one upstream subject.

    Attributes:
        name: The subject name.
        versions: Its live upstream version numbers, ascending.
        compatibility_level: Its effective upstream level, or ``None`` when the registry gave none
            this sync knows.
    """

    name: str
    versions: Tuple[int, ...]
    compatibility_level: Optional[str]


def parse_compatibility_level(body: Any) -> Tuple[Optional[str], Optional[str]]:
    """Read a ``/config`` answer.

    Confluent and Karapace answer ``GET`` with ``compatibilityLevel`` (``PUT`` echoes
    ``compatibility``); Apicurio's compatibility API does the same. Both keys are read.

    Args:
        body: The decoded JSON body.

    Returns:
        ``(level, unknown)``: the level when it is one of the seven Confluent levels, else ``None``,
        and the raw value when the registry named a level this model does not know.
    """
    if not isinstance(body, Mapping):
        return None, None
    raw = body.get("compatibilityLevel", body.get("compatibility"))
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    level = raw.strip().upper()
    if level in COMPATIBILITY_LEVELS:
        return level, None
    return None, raw.strip()[:64]


def record_name(schema_type: str, schema: str) -> Optional[str]:
    """Return the fully qualified record name a serializer would derive from ``schema``.

    Args:
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        schema: The schema text.

    Returns:
        Avro: ``namespace.name`` of a named top-level type; JSON Schema: its ``title`` (Confluent's
        JSON serializer names records by title); Protobuf: ``package.FirstMessage``. ``None`` when
        the schema has no such name or cannot be read.
    """
    if schema_type == SCHEMA_TYPE_PROTOBUF:
        message = _PROTO_MESSAGE.search(schema or "")
        if message is None:
            return None
        package = _PROTO_PACKAGE.search(schema or "")
        return f"{package.group(1)}.{message.group(1)}" if package else message.group(1)
    try:
        doc = json.loads(schema)
    except (TypeError, ValueError):
        return None
    if not isinstance(doc, Mapping):
        return None
    if schema_type == SCHEMA_TYPE_JSON:
        title = doc.get("title")
        return title.strip() if isinstance(title, str) and title.strip() else None
    if doc.get("type") not in ("record", "error", "enum", "fixed"):
        return None
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    namespace = doc.get("namespace")
    if "." in name or not isinstance(namespace, str) or not namespace.strip():
        return name.strip()
    return f"{namespace.strip()}.{name.strip()}"


def infer_strategy(subject: str, record: Optional[str]) -> Optional[str]:
    """Infer the subject naming strategy a producer used from the subject name.

    A registry does not store the strategy, so it is read from the shape of the name: the record name
    alone is ``record``, ``<topic>-<record>`` is ``topic_record``, ``<topic>-key`` / ``<topic>-value``
    is ``topic``. Anything else is not stated (``None``).

    Args:
        subject: The subject name.
        record: The schema's record name (:func:`record_name`), if any.

    Returns:
        ``topic``, ``record``, ``topic_record`` or ``None``.
    """
    if record:
        if subject == record:
            return STRATEGY_RECORD
        if subject.endswith(f"-{record}") and len(subject) > len(record) + 1:
            return STRATEGY_TOPIC_RECORD
    if subject.endswith("-key") or subject.endswith("-value"):
        return STRATEGY_TOPIC
    return None


def subject_revision(versions: Sequence[int], level: Optional[str]) -> str:
    """The inventory revision of a subject: ``v<latest>`` plus a digest of its versions and level."""
    digest = hashlib.sha256(
        json.dumps({"versions": sorted(versions), "level": level}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    latest = max(versions) if versions else 0
    return f"v{latest}+sha256.{digest}"


def build_candidate(state: SubjectState, *, registry_url: str) -> RefreshCandidate:
    """Turn a listed subject into an inventory candidate.

    Args:
        state: The subject as listed.
        registry_url: The registry root (recorded on the row's deployment metadata).

    Returns:
        The candidate: remote id and name = the subject, revision = :func:`subject_revision`, and
        ``deployment`` = the registry URL, versions and level (credential-free).
    """
    deployment: Dict[str, Any] = {
        "registryUrl": registry_url,
        "subject": state.name,
        "versions": list(state.versions),
        "latestVersion": max(state.versions) if state.versions else None,
        "compatibilityLevel": state.compatibility_level,
    }
    return RefreshCandidate(
        remote_id=state.name,
        name=state.name,
        revision=subject_revision(state.versions, state.compatibility_level),
        raw={"subject": state.name, "versions": list(state.versions)},
        deployment={k: v for k, v in deployment.items() if v is not None},
    )


def _error_detail(response: httpx.Response) -> str:
    """The human part of a registry error body (Confluent ``{"error_code", "message"}``)."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:_ERROR_DETAIL_MAX]
    if not isinstance(body, Mapping):
        return ""
    parts = [str(body[k]) for k in ("message", "detail", "title") if isinstance(body.get(k), str) and body.get(k)]
    if body.get("error_code") is not None:
        parts.insert(0, f"error_code {body['error_code']}")
    return ": ".join(dict.fromkeys(parts))[:_ERROR_DETAIL_MAX]


def _subject_path(subject: str) -> str:
    return f"/subjects/{quote(subject, safe='')}"


@dataclass(frozen=True)
class _MirroredSchema:
    """A schema this sync (or an earlier one) already holds for an upstream schema id."""

    schema_type: str
    fingerprint: str
    project_id: str
    version_record_id: str
    record: Optional[str] = None


class _DiscoveredError(Exception):
    """A subject that stays ``discovered``, with its reason."""


# ---------------------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------------------


class SchemaRegistrySource(ConnectorRefreshSource):
    """``schema-registry``: the subjects of an upstream schema registry, mirrored into the catalog.

    Args:
        connector: The connector row.
        credentials: ``{"username", "password"}`` and/or ``{"token"}``, or ``None``.
        transport: An httpx transport override (tests drive a fake registry through it).
    """

    #: Schema subjects are not APIs a gateway serves: no shadow-API notification for new subjects.
    reports_shadow_apis = False

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self._transport = transport
        self._subjects: Dict[str, SubjectState] = {}
        self._by_schema_id: Dict[int, _MirroredSchema] = {}
        self._texts: Dict[int, str] = {}
        self.findings: List[Dict[str, Any]] = []

    @property
    def registry_url(self) -> str:
        return normalize_registry_base(str(self.connector.get("base_url") or ""))

    @property
    def tenant_id(self) -> str:
        return str(self.connector["tenant_id"])

    @property
    def connector_id(self) -> str:
        return str(self.connector["id"])

    # --- HTTP -------------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        """An SSRF-guarded client with the connector's credentials."""
        creds = self.credentials or {}
        headers = {"Accept": ACCEPT}
        token = str(creds.get("token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        kwargs: Dict[str, Any] = {"headers": headers, "timeout": 30.0}
        username = str(creds.get("username") or "")
        if username and not token:
            kwargs["auth"] = httpx.BasicAuth(username, str(creds.get("password") or ""))
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return build_connector_http_client(**kwargs)

    def _get_json(
        self, client: httpx.Client, path: str, params: Optional[Mapping[str, Any]] = None, *, allow_404: bool = False
    ) -> Any:
        """GET ``{registry}{path}`` and decode its JSON body.

        Args:
            client: The client from :meth:`_client`.
            path: The API path (already percent-encoded).
            params: Query parameters.
            allow_404: Return ``None`` instead of raising when the registry answers ``404``.

        Raises:
            RefreshSourceError: The registry answered non-2xx, did not answer, the SSRF guard
                refused the address, or the body is not JSON.
        """
        try:
            response = client.get(f"{self.registry_url}{path}", params=dict(params or {}))
        except SSRFError as exc:
            raise RefreshSourceError(
                f"Request to the schema registry refused: {exc}", error_class=ERROR_CLASS_ADDRESS_REFUSED
            ) from exc
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"The schema registry did not answer GET {path}: {type(exc).__name__}") from exc
        if response.status_code == 404 and allow_404:
            return None
        if not 200 <= response.status_code < 300:
            detail = _error_detail(response)
            raise RefreshSourceError(
                f"The schema registry answered {response.status_code} to GET {path}"
                + (f": {detail}" if detail else ""),
                http_status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RefreshSourceError(
                f"The schema registry answered GET {path} with a body that is not JSON.",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            ) from exc

    # --- listing ------------------------------------------------------------------------

    def list_candidates(self) -> List[RefreshCandidate]:
        """List every subject with its versions and compatibility level (see the module docstring)."""
        if not self.registry_url:
            raise RefreshSourceError(
                "A schema registry connector needs a base URL.", error_class=ERROR_CLASS_INVALID_CONFIGURATION
            )
        self.findings = []
        client = self._client()
        try:
            names = self._get_json(client, "/subjects")
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                raise RefreshSourceError(
                    "The schema registry answered GET /subjects with an unexpected body (not a list of names).",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
            if len(names) > MAX_SUBJECTS:
                raise RefreshSourceError(
                    f"The schema registry lists {len(names)} subjects; a connector syncs at most {MAX_SUBJECTS}.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
            global_level: List[Optional[str]] = []  # read lazily, at most once
            states: Dict[str, SubjectState] = {}
            for name in dict.fromkeys(n for n in names if n.strip()):
                versions = self._get_json(client, f"{_subject_path(name)}/versions", allow_404=True)
                if versions is None:
                    continue  # deleted between the two calls
                if not isinstance(versions, list):
                    raise RefreshSourceError(
                        f"The schema registry answered GET /subjects/{name}/versions with an unexpected body.",
                        error_class=ERROR_CLASS_UNEXPECTED,
                    )
                # ``type(v) is int``: JSON ``true`` would pass ``isinstance(v, int)`` as version 1.
                numbers = tuple(sorted({v for v in versions if type(v) is int and v >= 1}))
                if not numbers:
                    continue
                level = self._subject_level(client, name, global_level)
                states[name] = SubjectState(name=name, versions=numbers, compatibility_level=level)
        finally:
            client.close()
        self._subjects = states
        return [build_candidate(state, registry_url=self.registry_url) for state in states.values()]

    def _subject_level(self, client: httpx.Client, subject: str, global_level: List[Optional[str]]) -> Optional[str]:
        """A subject's effective level: its own, else the registry's global level."""
        body = self._get_json(client, f"/config/{quote(subject, safe='')}", {"defaultToGlobal": "true"}, allow_404=True)
        if body is None:
            if not global_level:
                global_body = self._get_json(client, "/config", allow_404=True)
                global_level.append(self._level_from(global_body, subject=None))
            return global_level[0]
        return self._level_from(body, subject=subject)

    def _level_from(self, body: Any, *, subject: Optional[str]) -> Optional[str]:
        """Parse a ``/config`` body, reporting a level this model does not know as a finding."""
        level, unknown = parse_compatibility_level(body)
        if unknown is not None:
            self.findings.append(
                {
                    "code": FINDING_LEVEL_UNKNOWN,
                    "severity": "warning",
                    "remoteId": subject,
                    "level": unknown,
                    "message": f"unknown compatibility level `{unknown}`"
                    + (f" on subject `{subject}`" if subject else " (registry default)")
                    + "; the subject keeps its stored level",
                }
            )
        return level

    def _state(self, candidate: RefreshCandidate) -> SubjectState:
        state = self._subjects.get(candidate.remote_id)
        if state is None:
            raise RefreshSourceError(
                f"Subject {candidate.remote_id} was not in this sync's inventory.", error_class=ERROR_CLASS_UNEXPECTED
            )
        return state

    def explain_unchanged(self, candidate: RefreshCandidate) -> str:
        """The run summary's reason for a subject that was not re-synced."""
        state = self._subjects.get(candidate.remote_id)
        latest = max(state.versions) if state and state.versions else "?"
        return f"No new or deleted version and the same compatibility level (latest version {latest})."

    # --- fetching -----------------------------------------------------------------------

    def _version(self, client: httpx.Client, subject: str, version: int) -> Dict[str, Any]:
        """``GET /subjects/{s}/versions/{v}``: ``{id, schemaType, references, schema}`` (schema may be absent).

        Raises:
            RefreshSourceError: The registry refused, or the body names no schema id.
        """
        body = self._get_json(client, f"{_subject_path(subject)}/versions/{int(version)}")
        if not isinstance(body, Mapping) or type(body.get("id")) is not int:
            raise RefreshSourceError(
                f"The schema registry answered GET /subjects/{subject}/versions/{version} with no schema id.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return dict(body)

    def _schema_text(self, client: httpx.Client, schema_id: int, body: Mapping[str, Any]) -> Tuple[str, int]:
        """The schema text of ``schema_id``: from the version body, this sync's cache, or ``/schemas/ids/{id}``.

        Returns:
            ``(text, pulls)`` — ``pulls`` is 1 when ``/schemas/ids/{id}`` was called.
        """
        text = body.get("schema")
        if isinstance(text, str) and text.strip():
            self._texts[schema_id] = text
            return text, 0
        if schema_id in self._texts:
            return self._texts[schema_id], 0
        by_id = self._get_json(client, f"/schemas/ids/{int(schema_id)}")
        text = by_id.get("schema") if isinstance(by_id, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise RefreshSourceError(
                f"The schema registry answered GET /schemas/ids/{schema_id} with no schema text.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        self._texts[schema_id] = text
        return text, 1

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """The subject's latest schema (the engine syncs subjects with :meth:`sync_item` instead)."""
        state = self._state(candidate)
        latest = max(state.versions)
        client = self._client()
        try:
            body = self._version(client, state.name, latest)
            text, _ = self._schema_text(client, int(body["id"]), body)
        finally:
            client.close()
        schema_type = str(body.get("schemaType") or SCHEMA_TYPE_AVRO).upper()
        key, filename = intake_for(schema_type if schema_type in SCHEMA_TYPES else SCHEMA_TYPE_AVRO, state.name)
        return FetchedDocument(
            content=text.encode("utf-8"),
            filename=filename,
            import_kind=key,
            revision=str(latest),
            source_uri=self._version_uri(state.name, latest),
        )

    def _version_uri(self, subject: str, version: int) -> str:
        return f"{self.registry_url}{_subject_path(subject)}/versions/{int(version)}"

    # --- syncing one subject ------------------------------------------------------------

    def sync_item(
        self, db: Any, candidate: RefreshCandidate, row: Mapping[str, Any], actor_id: Optional[str]
    ) -> ItemSyncOutcome:
        """Mirror one upstream subject (see the module docstring).

        Args:
            db: Database handle.
            candidate: The subject's candidate.
            row: Its inventory row.
            actor_id: Who asked; the sweep passes ``None`` and the connector's creator is used.

        Returns:
            The outcome: the subject's catalog item and the pulls made, or the reason the subject
            stays ``discovered``.

        Raises:
            RefreshSourceError: The registry refused a request.
            SchemaRegistryError: A schema could not be read or imported (counted as a failure).
        """
        state = self._state(candidate)
        actor = actor_id or self.connector.get("created_by")
        local = subject_store.get_subject(db, self.tenant_id, state.name)
        if local is not None and str(local.get("source_connector_id") or "") != self.connector_id:
            return ItemSyncOutcome(
                discovered_reason=(
                    f"{REASON_SUBJECT_NAME_TAKEN}: a subject named {state.name!r} already exists in this "
                    "workspace (registered in Apiome or mirrored by another connector); it was left unchanged."
                ),
                pulls=0,
            )
        mirrored = set()
        if local is not None:
            mirrored = {
                int(v["upstream_version"])
                for v in subject_store.list_versions(db, str(local["id"]))
                if v.get("upstream_version")
            }

        pulls = 0
        strategy: Optional[str] = None
        last_project_id: Optional[str] = None
        client = self._client()
        try:
            for version in state.versions:
                if version in mirrored:
                    continue
                body = self._version(client, state.name, version)
                pulls += 1
                try:
                    recorded, used = self._mirror_version(db, client, state, version, body, actor)
                except _DiscoveredError as reason:
                    return ItemSyncOutcome(
                        discovered_reason=str(reason),
                        project_id=self._subject_item(db, state.name, last_project_id),
                        pulls=pulls,
                    )
                pulls += used
                last_project_id = str(recorded["project_id"])
                strategy = recorded.get("strategy") or strategy
        finally:
            client.close()

        subject = subject_store.get_subject(db, self.tenant_id, state.name)
        if subject is None:  # nothing to mirror (every version was already there and the subject is gone)
            return ItemSyncOutcome(project_id=None, pulls=pulls)
        subject_store.update_mirrored_subject(
            db, str(subject["id"]), compatibility_level=state.compatibility_level, strategy=strategy
        )
        retired = subject_store.retire_mirrored_versions(db, str(subject["id"]), state.versions)
        if retired:
            _logger.info(
                "schema registry mirror retired versions connector_id=%s subject=%s versions=%s",
                self.connector_id,
                state.name,
                retired,
            )
        return ItemSyncOutcome(project_id=self._subject_item(db, state.name, last_project_id, subject), pulls=pulls)

    def _subject_item(
        self, db: Any, name: str, fallback: Optional[str], subject: Optional[Mapping[str, Any]] = None
    ) -> Optional[str]:
        """The catalog item a subject's inventory row links to.

        Args:
            db: Database handle.
            name: The subject name.
            fallback: The item of the last version mirrored this sync, if any.
            subject: The subject row when the caller already read it.

        Returns:
            The subject's backing item, else ``fallback``, else the item of its latest version.
        """
        subject = subject or subject_store.get_subject(db, self.tenant_id, name)
        if subject and subject.get("project_id"):
            return str(subject["project_id"])
        if fallback:
            return fallback
        if subject:
            versions = subject_store.list_versions(db, str(subject["id"]))
            if versions:
                return str(versions[-1]["project_id"])
        return None

    def _mirror_version(
        self,
        db: Any,
        client: httpx.Client,
        state: SubjectState,
        version: int,
        body: Mapping[str, Any],
        actor_id: Optional[str],
    ) -> Tuple[Dict[str, Any], int]:
        """Record one upstream version on the mirrored subject, importing its schema only when new.

        Returns:
            ``(version row, extra pulls)`` — the row from
            :func:`app.schema_registry_store.record_version` plus the inferred ``strategy``.

        Raises:
            _DiscoveredError: The schema cannot be read standalone (references) or its type is unavailable.
            SchemaRegistryError: Any other parse or import refusal.
        """
        from .schema_registry_service import _import_revision, _live_catalog_item_id

        schema_id = int(body["id"])
        references = body.get("references") if isinstance(body.get("references"), list) else []
        schema_type = str(body.get("schemaType") or SCHEMA_TYPE_AVRO).upper()
        if schema_type not in SCHEMA_TYPES:
            raise SchemaRegistryError(
                "schemaType-invalid", f"Version {version} has schema type {schema_type!r}, which Apiome cannot hold."
            )
        mirror = {
            "connector_id": self.connector_id,
            "source_ref": source_ref(self.registry_url),
            "upstream_version": version,
            "upstream_schema_id": schema_id,
        }
        pulls = 0
        held = self._by_schema_id.get(schema_id) or self._held_schema(db, schema_id)
        subject_project_id: Optional[str] = None
        if held is None:
            text, pulls = self._schema_text(client, schema_id, body)
            try:
                parsed = fingerprint_schema(schema_type, text, state.name)
            except SchemaRegistryError as exc:
                if exc.code == "schema-type-unavailable":
                    raise _DiscoveredError(f"{REASON_SCHEMA_TYPE_UNAVAILABLE}: {exc}") from exc
                if references:
                    named = ", ".join(
                        str(r.get("subject") or r.get("name")) for r in references if isinstance(r, Mapping)
                    )
                    raise _DiscoveredError(
                        f"{REASON_REFERENCES_UNSUPPORTED}: version {version} refers to other subjects ({named}) "
                        "and cannot be read on its own yet."
                    ) from exc
                raise
            known = subject_store.get_schema_by_fingerprint(db, self.tenant_id, parsed.schema_type, parsed.fingerprint)
            if known is not None:
                project_id, version_record_id = str(known["project_id"]), str(known["version_record_id"])
            else:
                local = subject_store.get_subject(db, self.tenant_id, state.name)
                backing = _live_catalog_item_id(db, self.tenant_id, local.get("project_id") if local else None)
                revision = _import_revision(
                    db,
                    tenant_id=self.tenant_id,
                    actor_id=actor_id,
                    subject=state.name,
                    schema=text,
                    adapter_key=parsed.adapter_key,
                    filename=parsed.filename,
                    existing_project_id=backing,
                    version_number=version,
                    connector_source=connector_provenance_metadata(
                        self.connector,
                        remote_id=state.name,
                        remote_revision=str(version),
                        remote_name=state.name,
                        source_uri=self._version_uri(state.name, version),
                    ),
                )
                project_id, version_record_id = revision["project_id"], revision["version_record_id"]
                subject_project_id = project_id
            held = _MirroredSchema(
                schema_type=parsed.schema_type,
                fingerprint=parsed.fingerprint,
                project_id=project_id,
                version_record_id=version_record_id,
                record=record_name(parsed.schema_type, text),
            )
            self._by_schema_id[schema_id] = held
        strategy = infer_strategy(state.name, held.record)
        recorded = subject_store.record_version(
            db,
            tenant_id=self.tenant_id,
            subject=state.name,
            schema_type=held.schema_type,
            fingerprint=held.fingerprint,
            references=list(references),
            project_id=held.project_id,
            version_record_id=held.version_record_id,
            actor_id=actor_id,
            strategy=strategy,
            subject_project_id=subject_project_id,
            mirror=mirror,
        )
        return {**recorded, "strategy": strategy}, pulls

    def _held_schema(self, db: Any, schema_id: int) -> Optional[_MirroredSchema]:
        """A schema id this connector mirrored in an earlier sync, without its record name."""
        row = subject_store.find_mirrored_schema(db, self.tenant_id, self.connector_id, schema_id)
        if row is None:
            return None
        held = _MirroredSchema(
            schema_type=str(row["schema_type"]),
            fingerprint=str(row["fingerprint"]),
            project_id=str(row["project_id"]),
            version_record_id=str(row["version_record_id"]),
        )
        self._by_schema_id[schema_id] = held
        return held

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, registryUrl}``."""
        return {**super().describe(), "registryUrl": self.registry_url}


register_connector_source(KIND, SchemaRegistrySource, scope_validator=validate_schema_registry_scope)
