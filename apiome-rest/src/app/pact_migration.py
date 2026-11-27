"""Importing a Pact Broker or PactFlow workspace — PFX-6.7 (#6959): what an import record *is*.

``apiome pact migrate`` reads a source broker through its REST API and sends what it read to
``POST /v1/tenants/{t}/pact-migration/import`` in batches of :data:`MAX_RECORDS` records. This
module reads and checks such a batch; :mod:`app.pact_migration_store` writes it and
:mod:`app.pact_migration_routes` is the HTTP face.

A record is one thing the source holds, in the order the CLI sends them (pacticipants, environments,
versions oldest first, pacts, verification results, deployments, releases, webhooks):

========================  =====================================================================
``kind``                  fields (``created_at`` on every kind: when the source recorded it)
========================  =====================================================================
``pacticipant``           ``name``, ``repository_url``, ``main_branch``, ``labels``
``version``               ``pacticipant``, ``number``, ``build_url``, ``branches``, ``tags``
                          (``{"name", "created_at"}`` or a string)
``pact``                  ``consumer``, ``provider``, ``consumer_version``, ``content`` (the Pact)
``verification``          ``consumer``, ``provider``, ``consumer_version``, ``number`` and
                          ``result`` (the Pact Broker verification body)
``environment``           ``name``, ``display_name``, ``production``, ``contacts``
``deployment``            ``pacticipant``, ``version``, ``environment``, ``application_instance``
``release``               ``pacticipant``, ``version``, ``environment``
``webhook``               ``uuid`` and ``webhook`` (the Pact Broker webhook body)
========================  =====================================================================

**Every record is answered.** A record that cannot be read is not a failed request: it comes back
``refused`` with a code, a message and a JSON pointer into the batch, and the rest of the batch is
still read. Only an envelope that is not ``{"records": [...]}`` (or holds too many records) refuses
the whole request.

**Keys.** Each record has a natural key (:attr:`ImportRecord.key`) — what makes importing it again
change nothing: a pacticipant's handle, ``<handle>/<number>`` for a version, and so on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field

from .pact_deployments import validate_application_instance
from .pact_environment import EnvironmentInput, parse_environment_request
from .pact_publication import PactPublicationError, PactToStore, prepare_pact
from .pact_webhook import WebhookInput, parse_webhook_request, validate_webhook_uuid
from .pacticipant import (
    PacticipantValidationError,
    slugify_pacticipant_name,
    validate_branch,
    validate_label,
    validate_name,
    validate_slug,
    validate_tag,
    validate_url,
    validate_version_number,
)
from .verification_result import VerificationRequest, parse_verification_request

__all__ = [
    "CODE_MIGRATION_CONFLICT",
    "CODE_MIGRATION_INVALID",
    "CODE_MIGRATION_REFERENCE",
    "KINDS",
    "MAX_RECORDS",
    "OUTCOMES",
    "DeploymentImport",
    "EnvironmentImport",
    "ImportRecord",
    "ImportRequest",
    "MigrationOutcome",
    "MigrationReport",
    "PactImport",
    "PacticipantImport",
    "RefusedRecord",
    "ReleaseImport",
    "TagImport",
    "VerificationImport",
    "VersionImport",
    "WebhookImport",
    "count_outcomes",
    "parse_import_request",
    "parse_timestamp",
]

#: The request or one of its records is malformed (HTTP 422 for the envelope; ``refused`` per record).
CODE_MIGRATION_INVALID = "pact-migration-invalid"
#: The record is already in Apiome with different content (a pact, a deployment).
CODE_MIGRATION_CONFLICT = "pact-migration-conflict"
#: The record names something Apiome does not have (a pact a result verifies, an environment).
CODE_MIGRATION_REFERENCE = "pact-migration-reference-missing"

#: The most records one request may carry.
MAX_RECORDS = 100

#: Every record kind, in the order an import should send them.
KINDS: Tuple[str, ...] = (
    "pacticipant",
    "environment",
    "version",
    "pact",
    "verification",
    "deployment",
    "release",
    "webhook",
)

#: What happened to a record. An import answers ``created``, ``updated`` (it existed; something
#: missing — a label, a tag, a branch — was added), ``unchanged`` or ``refused``; a check answers
#: ``would-create``, ``exists`` or ``refused``.
OUTCOMES: Tuple[str, ...] = ("created", "updated", "unchanged", "refused", "would-create", "exists")

#: How far in the future a source timestamp may be (clock skew) before it is refused.
_FUTURE_SLACK = timedelta(days=1)

#: The most labels one pacticipant record may carry, branches or tags one version record may carry.
_MAX_LIST = 100


class _RecordError(Exception):
    """A record field that cannot be read, with the pointer (relative to the record) and the reason."""

    def __init__(self, pointer: str, message: str, code: str = CODE_MIGRATION_INVALID) -> None:
        super().__init__(message)
        self.pointer = pointer
        self.code = code


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TagImport:
    """A tag of an imported version.

    Attributes:
        name: The tag, checked.
        created_at: When the source tagged the version, or ``None`` (the version's time is used).
    """

    name: str
    created_at: Optional[datetime]


@dataclass(frozen=True)
class PacticipantImport:
    """A pacticipant: ``name`` is the name pacts use; the handle is derived from it.

    Attributes:
        index: Position in the batch.
        name: The name, checked.
        slug: The handle derived from it.
        repository_url: The repository, or ``None``.
        main_branch: The main branch, or ``None``.
        labels: The labels, checked and distinct.
        created_at: When the source registered it.
    """

    index: int
    name: str
    slug: str
    repository_url: Optional[str]
    main_branch: Optional[str]
    labels: Tuple[str, ...]
    created_at: Optional[datetime]
    kind: str = field(default="pacticipant", init=False)

    @property
    def key(self) -> str:
        """The natural key: the handle."""
        return self.slug


@dataclass(frozen=True)
class VersionImport:
    """A pacticipant version with its branches and tags.

    Attributes:
        index: Position in the batch.
        pacticipant: The pacticipant's name.
        number: The version number, checked.
        build_url: The CI build, or ``None``.
        branches: The branches it was recorded on, in source order.
        tags: Its tags.
        created_at: When the source recorded it.
    """

    index: int
    pacticipant: str
    number: str
    build_url: Optional[str]
    branches: Tuple[str, ...]
    tags: Tuple[TagImport, ...]
    created_at: Optional[datetime]
    kind: str = field(default="version", init=False)

    @property
    def key(self) -> str:
        """The natural key: ``<handle>/<number>``."""
        return f"{slugify_pacticipant_name(self.pacticipant)}/{self.number}"


@dataclass(frozen=True)
class PactImport:
    """The pact a consumer version published for a provider.

    Attributes:
        index: Position in the batch.
        consumer_version: The consumer version that published it.
        pact: The checked document (consumer and provider named as the document names them).
        created_at: When the source published it.
    """

    index: int
    consumer_version: str
    pact: PactToStore
    created_at: Optional[datetime]
    kind: str = field(default="pact", init=False)

    @property
    def key(self) -> str:
        """The natural key: ``<provider>/<consumer>/<consumer version>``."""
        return (
            f"{slugify_pacticipant_name(self.pact.provider_name)}/"
            f"{slugify_pacticipant_name(self.pact.consumer_name)}/{self.consumer_version}"
        )


@dataclass(frozen=True)
class VerificationImport:
    """A verification result of the pact a consumer version published.

    Attributes:
        index: Position in the batch.
        consumer: The consumer's name.
        provider: The provider's name.
        consumer_version: The consumer version whose pact was verified.
        number: The result's number on its pact version at the source.
        result: The checked result.
        created_at: When the source recorded it.
    """

    index: int
    consumer: str
    provider: str
    consumer_version: str
    number: int
    result: VerificationRequest
    created_at: Optional[datetime]
    kind: str = field(default="verification", init=False)

    @property
    def key(self) -> str:
        """The natural key: ``<provider>/<consumer>/<consumer version>/<number>``."""
        return (
            f"{slugify_pacticipant_name(self.provider)}/{slugify_pacticipant_name(self.consumer)}/"
            f"{self.consumer_version}/{self.number}"
        )


@dataclass(frozen=True)
class EnvironmentImport:
    """An environment.

    Attributes:
        index: Position in the batch.
        environment: The checked environment.
        created_at: When the source created it.
    """

    index: int
    environment: EnvironmentInput
    created_at: Optional[datetime]
    kind: str = field(default="environment", init=False)

    @property
    def key(self) -> str:
        """The natural key: the name."""
        return self.environment.name


@dataclass(frozen=True)
class DeploymentImport:
    """A version currently deployed to an environment.

    Attributes:
        index: Position in the batch.
        pacticipant: The pacticipant's name.
        version: The deployed version.
        environment: The environment's name.
        application_instance: The instance, or ``None``.
        created_at: When the source recorded the deployment.
    """

    index: int
    pacticipant: str
    version: str
    environment: str
    application_instance: Optional[str]
    created_at: Optional[datetime]
    kind: str = field(default="deployment", init=False)

    @property
    def key(self) -> str:
        """The natural key: ``<handle>/<version>@<environment>[/<instance>]``."""
        instance = f"/{self.application_instance}" if self.application_instance else ""
        return f"{slugify_pacticipant_name(self.pacticipant)}/{self.version}@{self.environment}{instance}"


@dataclass(frozen=True)
class ReleaseImport:
    """A version currently released to (supported in) an environment.

    Attributes:
        index: Position in the batch.
        pacticipant: The pacticipant's name.
        version: The released version.
        environment: The environment's name.
        created_at: When the source recorded the release.
    """

    index: int
    pacticipant: str
    version: str
    environment: str
    created_at: Optional[datetime]
    kind: str = field(default="release", init=False)

    @property
    def key(self) -> str:
        """The natural key: ``<handle>/<version>@<environment>``."""
        return f"{slugify_pacticipant_name(self.pacticipant)}/{self.version}@{self.environment}"


@dataclass(frozen=True)
class WebhookImport:
    """A webhook.

    Attributes:
        index: Position in the batch.
        uuid: The source's uuid, kept when no other workspace uses it; ``None`` to generate one.
        webhook: The checked webhook.
        created_at: When the source created it.
    """

    index: int
    uuid: Optional[str]
    webhook: WebhookInput
    created_at: Optional[datetime]
    kind: str = field(default="webhook", init=False)

    @property
    def key(self) -> str:
        """The natural key: the uuid, else the position in the batch."""
        return self.uuid or f"webhook#{self.index}"


@dataclass(frozen=True)
class RefusedRecord:
    """A record that could not be read.

    Attributes:
        index: Position in the batch.
        kind: Its ``kind``, as sent (``None`` when missing).
        code: Why: :data:`CODE_MIGRATION_INVALID`, or the code of the Pact rule it breaks.
        message: The reason, starting with the JSON pointer of the field.
    """

    index: int
    kind: Optional[str]
    code: str
    message: str

    @property
    def key(self) -> Optional[str]:
        """No key can be read from a refused record."""
        return None


ImportRecord = Union[
    PacticipantImport,
    VersionImport,
    PactImport,
    VerificationImport,
    EnvironmentImport,
    DeploymentImport,
    ReleaseImport,
    WebhookImport,
]


@dataclass(frozen=True)
class ImportRequest:
    """A read batch.

    Attributes:
        source: The source broker the CLI read (for the audit row), or ``None``.
        records: Each record, read or refused, in batch order.
    """

    source: Optional[str]
    records: Tuple[Union[ImportRecord, RefusedRecord], ...]


# ---------------------------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------------------------


class MigrationOutcome(BaseModel):
    """What happened to one record of the batch."""

    index: int = Field(description="The record's position in `records`.")
    kind: Optional[str] = Field(default=None, description="The record's kind, as sent.")
    key: Optional[str] = Field(default=None, description="Its natural key; null when it could not be read.")
    outcome: str = Field(description="`created`, `updated`, `unchanged`, `refused`, `would-create` or `exists`.")
    code: Optional[str] = Field(default=None, description="For `refused`: why, as a code.")
    message: Optional[str] = Field(default=None, description="For `refused`: why, as a sentence.")
    note: Optional[str] = Field(
        default=None, description="Something about how it was imported (a new uuid, a merged handle)."
    )


class MigrationReport(BaseModel):
    """The answer to an import or a check."""

    dry_run: bool = Field(description="True for a check: nothing was written.")
    results: List[MigrationOutcome] = Field(description="One entry per record, in batch order.")
    counts: Dict[str, int] = Field(description="How many records had each outcome.")


def count_outcomes(results: Sequence[MigrationOutcome]) -> Dict[str, int]:
    """Count the outcomes of a batch.

    Args:
        results: The per-record outcomes.

    Returns:
        ``{outcome: count}`` for every outcome that occurred.
    """
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
    return counts


# ---------------------------------------------------------------------------------------------
# Reading fields
# ---------------------------------------------------------------------------------------------


def parse_timestamp(value: Any, pointer: str = "/created_at") -> Optional[datetime]:
    """Read a source timestamp: ISO 8601, a time zone assumed UTC when missing.

    Args:
        value: The value sent, or ``None``.
        pointer: Where it is, for the refusal.

    Returns:
        The aware datetime, or ``None`` when not sent.

    Raises:
        _RecordError: For a value that is not an ISO 8601 date-time, or lies more than a day ahead.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _RecordError(pointer, "must be an ISO 8601 date-time")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _RecordError(pointer, f"'{value}' is not an ISO 8601 date-time") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if moment > datetime.now(timezone.utc) + _FUTURE_SLACK:
        raise _RecordError(pointer, f"'{value}' is in the future")
    return moment


def _text(record: Mapping[str, Any], key: str, *, required: bool = True) -> Optional[str]:
    """A string field, stripped; ``None`` when optional and absent or blank.

    Raises:
        _RecordError: When required and missing, or not a string.
    """
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip() and not required):
        if required:
            raise _RecordError(f"/{key}", "is required")
        return None
    if not isinstance(value, str):
        raise _RecordError(f"/{key}", "must be a string")
    if required and not value.strip():
        raise _RecordError(f"/{key}", "must not be blank")
    return value.strip()


def _strings(record: Mapping[str, Any], key: str) -> List[Any]:
    """A list field (absent = empty).

    Raises:
        _RecordError: For a value that is not a list, or is longer than :data:`_MAX_LIST`.
    """
    value = record.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise _RecordError(f"/{key}", "must be an array")
    if len(value) > _MAX_LIST:
        raise _RecordError(f"/{key}", f"must have at most {_MAX_LIST} entries")
    return value


def _checked(pointer: str, check: Any, value: Any) -> Any:
    """Run a registry validator, turning its refusal into a :class:`_RecordError` at ``pointer``."""
    try:
        return check(value)
    except PacticipantValidationError as exc:
        raise _RecordError(pointer, str(exc), exc.code) from exc


def _pacticipant_name(record: Mapping[str, Any], key: str) -> str:
    """A pacticipant name a handle can be derived from.

    Raises:
        _RecordError: When missing, or no handle can be derived.
    """
    name = _text(record, key) or ""
    _checked(f"/{key}", validate_name, name)
    _checked(f"/{key}", validate_slug, slugify_pacticipant_name(name))
    return name


def _document(record: Mapping[str, Any], key: str) -> bytes:
    """A nested JSON object, re-encoded for the Pact parsers that read bytes.

    Raises:
        _RecordError: When missing or not an object.
    """
    value = record.get(key)
    if not isinstance(value, Mapping):
        raise _RecordError(f"/{key}", "must be a JSON object")
    return json.dumps(value).encode("utf-8")


def _pact_refusal(exc: PactPublicationError, prefix: str) -> _RecordError:
    """A Pact parser's refusal, its pointer moved under ``prefix``."""
    return _RecordError(prefix + (exc.pointer or ""), str(exc), exc.code)


# ---------------------------------------------------------------------------------------------
# One parser per kind
# ---------------------------------------------------------------------------------------------


def _pacticipant(index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any) -> PacticipantImport:
    """Read a ``pacticipant`` record."""
    name = _pacticipant_name(record, "name")
    main_branch = _text(record, "main_branch", required=False)
    labels: List[str] = []
    for position, label in enumerate(_strings(record, "labels")):
        checked = _checked(f"/labels/{position}", validate_label, label if isinstance(label, str) else None)
        if checked not in labels:
            labels.append(checked)
    return PacticipantImport(
        index=index,
        name=validate_name(name),
        slug=slugify_pacticipant_name(name),
        repository_url=_checked(
            "/repository_url",
            lambda value: validate_url(value, what="repository URL"),
            _text(record, "repository_url", required=False),
        ),
        main_branch=_checked("/main_branch", validate_branch, main_branch) if main_branch else None,
        labels=tuple(labels),
        created_at=created_at,
    )


def _version(index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any) -> VersionImport:
    """Read a ``version`` record."""
    branches: List[str] = []
    for position, branch in enumerate(_strings(record, "branches")):
        checked = _checked(f"/branches/{position}", validate_branch, branch if isinstance(branch, str) else None)
        if checked not in branches:
            branches.append(checked)
    tags: List[TagImport] = []
    for position, tag in enumerate(_strings(record, "tags")):
        name = tag.get("name") if isinstance(tag, Mapping) else tag
        checked = _checked(f"/tags/{position}/name", validate_tag, name if isinstance(name, str) else None)
        when = (
            parse_timestamp(tag.get("created_at"), f"/tags/{position}/created_at") if isinstance(tag, Mapping) else None
        )
        if all(existing.name != checked for existing in tags):
            tags.append(TagImport(name=checked, created_at=when))
    return VersionImport(
        index=index,
        pacticipant=_pacticipant_name(record, "pacticipant"),
        number=_checked("/number", validate_version_number, record.get("number")),
        build_url=_checked(
            "/build_url",
            lambda value: validate_url(value, what="build URL"),
            _text(record, "build_url", required=False),
        ),
        branches=tuple(branches),
        tags=tuple(tags),
        created_at=created_at,
    )


def _pact(
    index: int, record: Mapping[str, Any], created_at: Optional[datetime], *, max_pact_bytes: int, **_: Any
) -> PactImport:
    """Read a ``pact`` record."""
    consumer = _pacticipant_name(record, "consumer")
    provider = _pacticipant_name(record, "provider")
    number = _checked("/consumer_version", validate_version_number, record.get("consumer_version"))
    try:
        pact = prepare_pact(
            _document(record, "content"), consumer_name=consumer, provider_name=provider, max_bytes=max_pact_bytes
        )
    except PactPublicationError as exc:
        raise _pact_refusal(exc, "/content") from exc
    return PactImport(index=index, consumer_version=number, pact=pact, created_at=created_at)


def _verification(
    index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any
) -> VerificationImport:
    """Read a ``verification`` record."""
    number = record.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise _RecordError("/number", "must be a whole number from 1 (the result's number at the source)")
    try:
        result = parse_verification_request(_document(record, "result"))
    except PactPublicationError as exc:
        raise _pact_refusal(exc, "/result") from exc
    _checked("/result/providerApplicationVersion", validate_version_number, result.provider_version)
    if result.report_id:
        raise _RecordError(
            "/result/providerVerificationReportId", "a provider verification report of the source cannot be imported"
        )
    return VerificationImport(
        index=index,
        consumer=_pacticipant_name(record, "consumer"),
        provider=_pacticipant_name(record, "provider"),
        consumer_version=_checked("/consumer_version", validate_version_number, record.get("consumer_version")),
        number=number,
        result=result,
        created_at=created_at,
    )


def _environment(index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any) -> EnvironmentImport:
    """Read an ``environment`` record (the Pact Broker body, under snake_case names)."""
    body = {
        "name": record.get("name"),
        "displayName": record.get("display_name"),
        "production": record.get("production", False),
        "contacts": record.get("contacts") or [],
    }
    try:
        environment = parse_environment_request(json.dumps(body).encode("utf-8"))
    except PactPublicationError as exc:
        pointer = {"/displayName": "/display_name"}.get(exc.pointer or "", exc.pointer or "")
        raise _RecordError(pointer, str(exc), exc.code) from exc
    return EnvironmentImport(index=index, environment=environment, created_at=created_at)


def _placement(record: Mapping[str, Any]) -> Tuple[str, str, str]:
    """The pacticipant, version and environment a deployment or release names."""
    return (
        _pacticipant_name(record, "pacticipant"),
        _checked("/version", validate_version_number, record.get("version")),
        _text(record, "environment") or "",
    )


def _deployment(index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any) -> DeploymentImport:
    """Read a ``deployment`` record."""
    pacticipant, version, environment = _placement(record)
    instance = record.get("application_instance")
    if instance is not None and not isinstance(instance, str):
        raise _RecordError("/application_instance", "must be a string")
    try:
        checked = validate_application_instance(instance or None)
    except PactPublicationError as exc:
        raise _RecordError("/application_instance", str(exc)) from exc
    return DeploymentImport(
        index=index,
        pacticipant=pacticipant,
        version=version,
        environment=environment,
        application_instance=checked,
        created_at=created_at,
    )


def _release(index: int, record: Mapping[str, Any], created_at: Optional[datetime], **_: Any) -> ReleaseImport:
    """Read a ``release`` record."""
    pacticipant, version, environment = _placement(record)
    return ReleaseImport(
        index=index, pacticipant=pacticipant, version=version, environment=environment, created_at=created_at
    )


def _webhook(
    index: int, record: Mapping[str, Any], created_at: Optional[datetime], *, resolve: bool, **_: Any
) -> WebhookImport:
    """Read a ``webhook`` record; the body is checked as ``POST …/webhooks`` checks it."""
    uuid = record.get("uuid")
    if uuid is not None:
        try:
            uuid = validate_webhook_uuid(uuid) if isinstance(uuid, str) else None
        except PactPublicationError as exc:
            raise _RecordError("/uuid", "must be a UUID") from exc
        if uuid is None:
            raise _RecordError("/uuid", "must be a UUID")
    try:
        webhook = parse_webhook_request(_document(record, "webhook"), resolve=resolve)
    except PactPublicationError as exc:
        raise _pact_refusal(exc, "/webhook") from exc
    if webhook.has_secrets() and any(
        value == "**********" for value in (webhook.password, webhook.signing_secret, *webhook.secret_headers.values())
    ):
        raise _RecordError(
            "/webhook",
            "a secret the source redacted (**********) cannot be imported; re-enter it, or leave it out",
        )
    return WebhookImport(index=index, uuid=uuid, webhook=webhook, created_at=created_at)


_PARSERS = {
    "pacticipant": _pacticipant,
    "version": _version,
    "pact": _pact,
    "verification": _verification,
    "environment": _environment,
    "deployment": _deployment,
    "release": _release,
    "webhook": _webhook,
}


def _read_record(index: int, record: Any, *, max_pact_bytes: int, resolve: bool) -> Union[ImportRecord, RefusedRecord]:
    """Read one record of the batch, or say why it cannot be read.

    Args:
        index: Its position in ``records``.
        record: The record as sent.
        max_pact_bytes: The largest Pact document accepted.
        resolve: Whether a webhook URL's host is resolved against the SSRF policy.

    Returns:
        The record, or a :class:`RefusedRecord` whose message starts with the field's pointer.
    """
    base = f"/records/{index}"
    if not isinstance(record, Mapping):
        return RefusedRecord(index, None, CODE_MIGRATION_INVALID, f"{base}: must be a JSON object")
    kind = record.get("kind")
    parser = _PARSERS.get(kind) if isinstance(kind, str) else None
    if parser is None:
        return RefusedRecord(
            index,
            kind if isinstance(kind, str) else None,
            CODE_MIGRATION_INVALID,
            f"{base}/kind: must be one of {', '.join(KINDS)}",
        )
    try:
        created_at = parse_timestamp(record.get("created_at"))
        return parser(index, record, created_at, max_pact_bytes=max_pact_bytes, resolve=resolve)
    except _RecordError as exc:
        return RefusedRecord(index, kind, exc.code, f"{base}{exc.pointer}: {exc}")


def parse_import_request(raw: bytes, *, max_pact_bytes: int, resolve: bool = True) -> ImportRequest:
    """Read an import (or check) batch.

    Args:
        raw: The body: ``{"source": "...", "records": [...]}``.
        max_pact_bytes: The largest Pact document accepted (``settings.pact_max_bytes``).
        resolve: Whether webhook hosts are resolved against the SSRF policy (tests pass ``False``).

    Returns:
        The batch, every record read or refused.

    Raises:
        PactPublicationError: ``pact-migration-invalid`` for a body that is not JSON, not an object,
            has no ``records`` array, or holds more than :data:`MAX_RECORDS` records.
    """
    try:
        body = json.loads(raw) if raw and raw.strip() else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PactPublicationError(CODE_MIGRATION_INVALID, f"the request body is not JSON: {exc}", pointer="") from exc
    if not isinstance(body, Mapping):
        raise PactPublicationError(CODE_MIGRATION_INVALID, "must be a JSON object with records", pointer="")
    records = body.get("records")
    if not isinstance(records, list) or not records:
        raise PactPublicationError(CODE_MIGRATION_INVALID, "/records: must be a non-empty array", pointer="/records")
    if len(records) > MAX_RECORDS:
        raise PactPublicationError(
            CODE_MIGRATION_INVALID,
            f"/records: send at most {MAX_RECORDS} records per request ({len(records)} sent)",
            pointer="/records",
        )
    source = body.get("source")
    if source is not None and (not isinstance(source, str) or len(source) > 2048):
        raise PactPublicationError(
            CODE_MIGRATION_INVALID, "/source: must be a string of at most 2048 characters", pointer="/source"
        )
    return ImportRequest(
        source=source,
        records=tuple(
            _read_record(index, record, max_pact_bytes=max_pact_bytes, resolve=resolve)
            for index, record in enumerate(records)
        ),
    )
