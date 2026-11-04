"""Push schemas of any format to a Confluent Schema Registry — MFX-19.4 (#3912), MFX-19.6 (#4183).

A Confluent-compatible registry (Confluent Platform or Cloud, Karapace, Apicurio's ``ccompat`` API)
holds **Avro**, **JSON Schema** and **Protobuf** subjects. A push is the same for all three; only the
``schemaType`` sent with each schema, and how a schema names the schemas it references, differ:

* Avro — ``schemaType`` left out (the registry's default), a reference named by the type's full name;
* JSON Schema — ``schemaType: JSON``, a reference named by the ``$ref`` that points at it;
* Protobuf — ``schemaType: PROTOBUF``, a reference named by the ``import`` path.

Each format's plan (:func:`app.avro_registry_push.plan_avro_push`,
:func:`app.schema_registry_push_plans.plan_jsonschema_push`,
:func:`app.schema_registry_push_plans.plan_protobuf_push`) turns an export into
:class:`RegistryPushUnit`\\ s, ordered by :func:`order_by_dependencies` so every schema comes after
the schemas it references. :func:`push_registry_subjects` then pushes them, per subject in order:

1. ``POST /subjects/{s}`` — when the registry already holds this exact schema under the subject, the
   subject is ``already_registered`` with its id and version, and nothing is written;
2. ``PUT /config/{s}`` — only when the push asks for a ``compatibility_level``: the subject's level is
   set before the check (a dry run sets nothing, and says so);
3. ``POST /compatibility/subjects/{s}/versions/latest?verbose=true`` — the schema is checked against the
   subject's latest version under the subject's level; an incompatible schema is ``incompatible`` with
   the registry's messages, and is not registered. A subject with no version yet (``404``) has nothing
   to be compatible with;
4. ``POST /subjects/{s}/versions`` — the schema is registered; its id comes back, and its version is
   read with step 1 again. A dry run stops before this step (``would_register``).

A subject whose dependency did not register is ``skipped``; one the registry refuses is ``failed``
with the registry's message. In a dry run, a subject that references a schema the run would register
cannot be checked (the referenced version does not exist yet): it is ``would_register`` with
``compatibility: unchecked``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from .schema_registry_connector_source import _error_detail
from .ssrf_guard import SSRFError

__all__ = [
    "COMPATIBILITY_LEVELS",
    "CompatibilityLevel",
    "RegistryPushError",
    "RegistryPushReference",
    "RegistryPushSubjectResult",
    "RegistryPushUnit",
    "SchemaType",
    "order_by_dependencies",
    "push_registry_subjects",
]

#: The registry statuses a dependent can build on.
_LANDED = frozenset({"registered", "already_registered", "would_register"})

#: Confluent's subject compatibility levels (``PUT /config/{subject}``).
COMPATIBILITY_LEVELS = (
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FORWARD",
    "FORWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
    "NONE",
)

PushStatus = Literal["registered", "already_registered", "would_register", "incompatible", "failed", "skipped"]
Compatibility = Literal["compatible", "new_subject", "unchecked"]
CompatibilityLevel = Literal[
    "BACKWARD", "BACKWARD_TRANSITIVE", "FORWARD", "FORWARD_TRANSITIVE", "FULL", "FULL_TRANSITIVE", "NONE"
]
#: The registry's ``schemaType`` of a schema.
SchemaType = Literal["AVRO", "JSON", "PROTOBUF"]


class RegistryPushError(Exception):
    """A push refused before anything is sent to the registry.

    Args:
        code: A stable error code (``REGISTRY_PUSH_…``, or ``AVRO_PUSH_…`` for an Avro plan).
        message: What is wrong and how to fix it.
        status_code: The HTTP status the route answers with.
    """

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def http_detail(self) -> Dict[str, str]:
        """``{code, message}`` for an ``HTTPException`` detail."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RegistryPushUnit:
    """One emitted schema to register.

    Attributes:
        subject: The registry subject.
        file: The emitted file's path.
        schema: The schema text sent to the registry.
        schema_type: The registry's ``schemaType`` (``AVRO``, ``JSON`` or ``PROTOBUF``).
        record: The schema's record name, when it has one (see :mod:`app.schema_registry_subjects`).
        references: ``(reference name, referenced subject)`` per schema of this push it references,
            sorted by name. The referenced subject is always an earlier unit of the same plan.
    """

    subject: str
    file: str
    schema: str
    schema_type: SchemaType = "AVRO"
    record: Optional[str] = None
    references: Sequence[Tuple[str, str]] = field(default_factory=tuple)


class RegistryPushReference(BaseModel):
    """A Confluent schema reference: its name, and the subject and version it points at."""

    name: str = Field(
        description="The reference name: the referenced type's full Avro name, the JSON Schema ``$ref`` "
        "pointing at it, or the Protobuf ``import`` path.",
    )
    subject: str = Field(description="The subject the referenced schema is registered under.")
    version: Optional[int] = Field(
        default=None,
        description="The registered version referenced; null in a dry run when that schema would be "
        "registered by this push.",
    )


class RegistryPushSubjectResult(BaseModel):
    """What the push did for one subject."""

    subject: str = Field(description="The registry subject.")
    file: str = Field(description="The emitted file registered under it (``.avsc``, ``.schema.json`` or ``.proto``).")
    schema_type: SchemaType = Field(
        default="AVRO", description="The schema's registry type: ``AVRO``, ``JSON`` or ``PROTOBUF``."
    )
    record: Optional[str] = Field(default=None, description="The schema's record name, when it has one.")
    status: PushStatus = Field(
        description="``registered`` (written now), ``already_registered`` (the registry holds this exact "
        "schema), ``would_register`` (dry run), ``incompatible`` (refused by the subject's compatibility "
        "level), ``failed`` (the registry refused or did not answer) or ``skipped`` (a schema it "
        "references did not register).",
    )
    compatibility: Optional[Compatibility] = Field(
        default=None,
        description="The compatibility check: ``compatible`` with the latest version, ``new_subject`` (no "
        "version to check against) or ``unchecked`` (dry run, a referenced schema is not registered yet).",
    )
    compatibility_level: Optional[CompatibilityLevel] = Field(
        default=None,
        description="The compatibility level the push set on the subject before checking it (in a dry "
        "run, the level it would set); null when the push asked for none.",
    )
    schema_id: Optional[int] = Field(default=None, description="The registry's global schema id.")
    version: Optional[int] = Field(default=None, description="The subject version holding the schema.")
    references: List[RegistryPushReference] = Field(
        default_factory=list, description="The schema references sent with the schema."
    )
    messages: List[str] = Field(
        default_factory=list,
        description="The registry's compatibility messages, error, or why the subject was skipped.",
    )


# ---------------------------------------------------------------------------------------
# Plan ordering
# ---------------------------------------------------------------------------------------


def order_by_dependencies(
    depends_on: Mapping[str, Set[str]],
    cycle_error: Callable[[List[str]], RegistryPushError],
) -> List[str]:
    """Subjects ordered so each comes after every subject it depends on.

    Args:
        depends_on: ``{subject: subjects it references}``; every referenced subject is a key.
        cycle_error: Builds the error raised for the subjects left when the rest form a cycle.

    Returns:
        The subjects, dependencies first; ties are broken by subject, so the order is deterministic.

    Raises:
        RegistryPushError: The references form a cycle (a registry cannot hold one).
    """
    ordered: List[str] = []
    placed: Set[str] = set()
    pending = sorted(depends_on)
    while pending:
        ready = [s for s in pending if depends_on[s] <= placed]
        if not ready:
            raise cycle_error(pending)
        ordered.extend(ready)
        placed.update(ready)
        pending = [s for s in pending if s not in placed]
    return ordered


def duplicate_subject_error(
    code: str, first: str, second: str, subject: str, *, error_type: type = RegistryPushError
) -> RegistryPushError:
    """The refusal for two files on one subject (``topic_name`` with several schemas).

    Args:
        code: The error code (``REGISTRY_PUSH_DUPLICATE_SUBJECT`` or ``AVRO_PUSH_DUPLICATE_SUBJECT``).
        first: The file that took the subject first.
        second: The file that maps to it too.
        subject: The subject they share.
        error_type: :class:`RegistryPushError` or a subclass of it.

    Returns:
        The error to raise.
    """
    return error_type(
        code,
        f"{first} and {second} both map to subject {subject!r}; a subject holds one schema. Use "
        "subject_naming record_name or topic_record_name, or export one type.",
    )


# ---------------------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------------------


class _RegistryError(Exception):
    """A registry call that failed: the registry's status (``None`` when it did not answer) and message."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class _Registry:
    """The Confluent calls a push makes, on one SSRF-guarded client."""

    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    def _send(
        self, method: str, path: str, body: Mapping[str, Any], params: Optional[Mapping[str, str]] = None
    ) -> tuple:
        """``(status, json body or None)`` of a call; raises :class:`_RegistryError` when there is no answer."""
        try:
            response = self._client.request(
                method, f"{self._base}{path}", json=dict(body), params=dict(params or {})
            )
        except SSRFError as exc:
            raise _RegistryError(f"Request to the schema registry refused: {exc}") from exc
        except httpx.HTTPError as exc:
            raise _RegistryError(
                f"The schema registry did not answer {method} {path}: {type(exc).__name__}"
            ) from exc
        if 200 <= response.status_code < 300:
            try:
                return response.status_code, response.json()
            except ValueError as exc:
                raise _RegistryError(
                    f"The schema registry answered {method} {path} with a body that is not JSON.",
                    response.status_code,
                ) from exc
        return response.status_code, _error_detail(response)

    @staticmethod
    def _fail(method: str, path: str, status: int, detail: Any) -> _RegistryError:
        return _RegistryError(
            f"The schema registry answered {status} to {method} {path}" + (f": {detail}" if detail else ""),
            status,
        )

    def lookup(self, subject: str, body: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """The subject's version holding this exact schema (``{id, version}``), or ``None``."""
        path = f"/subjects/{quote(subject, safe='')}"
        status, data = self._send("POST", path, body)
        if status == 404:
            return None
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail("POST", path, status, data)
        return data

    def set_level(self, subject: str, level: str) -> None:
        """Set the subject's compatibility level."""
        path = f"/config/{quote(subject, safe='')}"
        status, data = self._send("PUT", path, {"compatibility": level})
        if not 200 <= status < 300:
            raise self._fail("PUT", path, status, data)

    def check(self, subject: str, body: Mapping[str, Any]) -> tuple:
        """``(compatible, messages)``; ``(None, [])`` when the subject has no version yet."""
        path = f"/compatibility/subjects/{quote(subject, safe='')}/versions/latest"
        status, data = self._send("POST", path, body, {"verbose": "true"})
        if status == 404:
            return None, []
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail("POST", path, status, data)
        messages = data.get("messages")
        return bool(data.get("is_compatible")), [str(m) for m in messages] if isinstance(messages, list) else []

    def register(self, subject: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Register the schema; the registry's answer (``{id}``, sometimes with ``version``)."""
        path = f"/subjects/{quote(subject, safe='')}/versions"
        status, data = self._send("POST", path, body)
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail("POST", path, status, data)
        return data


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _redact(message: str, credentials: Optional[Mapping[str, str]]) -> str:
    """``message`` with every stored credential value removed."""
    for value in (credentials or {}).values():
        if value and len(value) >= 4:
            message = message.replace(value, "[redacted]")
    return message


def _request_body(unit: RegistryPushUnit, references: Sequence[RegistryPushReference]) -> Dict[str, Any]:
    """The schema as the registry takes it: ``schemaType`` only for a non-Avro schema (Avro is the default)."""
    body: Dict[str, Any] = {"schema": unit.schema}
    if unit.schema_type != "AVRO":
        body["schemaType"] = unit.schema_type
    if references:
        body["references"] = [ref.model_dump() for ref in references]
    return body


def push_registry_subjects(
    client: httpx.Client,
    registry_url: str,
    units: Sequence[RegistryPushUnit],
    *,
    dry_run: bool = False,
    compatibility_level: Optional[str] = None,
    credentials: Optional[Mapping[str, str]] = None,
) -> List[RegistryPushSubjectResult]:
    """Check and register each unit on the registry, in plan order.

    Args:
        client: An SSRF-guarded client carrying the connector's credentials.
        registry_url: The registry's base URL.
        units: A plan, dependencies first (every referenced subject is an earlier unit).
        dry_run: Look up and check every subject, but write nothing (no level, no schema).
        compatibility_level: A level from :data:`COMPATIBILITY_LEVELS` to set on each subject the push
            registers, before its check; ``None`` keeps each subject's level as the registry has it.
        credentials: The connector's credentials, removed from any registry message reported back.

    Returns:
        One result per unit, in the same order.

    Raises:
        ValueError: ``compatibility_level`` is not a Confluent level.
    """
    if compatibility_level is not None and compatibility_level not in COMPATIBILITY_LEVELS:
        raise ValueError(f"compatibility_level must be one of {', '.join(COMPATIBILITY_LEVELS)}")
    registry = _Registry(client, registry_url)
    by_subject: Dict[str, RegistryPushSubjectResult] = {}
    results: List[RegistryPushSubjectResult] = []
    for unit in units:
        result = RegistryPushSubjectResult(
            subject=unit.subject, file=unit.file, schema_type=unit.schema_type, record=unit.record,
            status="failed",
        )
        results.append(result)
        by_subject[unit.subject] = result
        deps = [(name, by_subject[subject]) for name, subject in unit.references]
        missing = [dep.subject for _, dep in deps if dep.status not in _LANDED]
        if missing:
            result.status = "skipped"
            result.messages = [f"Not pushed: referenced subject {s!r} did not register." for s in missing]
            continue
        result.references = [
            RegistryPushReference(name=name, subject=dep.subject, version=dep.version) for name, dep in deps
        ]
        if any(ref.version is None for ref in result.references):
            # Dry run only: a referenced schema would be registered by this push, so its version
            # does not exist yet and the registry can neither look this schema up nor check it.
            result.status, result.compatibility = "would_register", "unchecked"
            result.compatibility_level = compatibility_level
            result.messages = ["Compatibility not checked: a schema this one references is not registered yet."]
            continue
        body = _request_body(unit, result.references)
        try:
            existing = registry.lookup(unit.subject, body)
            if existing is not None:
                result.status = "already_registered"
                result.schema_id, result.version = _int(existing.get("id")), _int(existing.get("version"))
                continue
            if compatibility_level is not None:
                result.compatibility_level = compatibility_level
                if dry_run:
                    result.messages.append(
                        f"Compatibility level {compatibility_level} would be set; this check used the "
                        "subject's current level."
                    )
                else:
                    registry.set_level(unit.subject, compatibility_level)
            compatible, messages = registry.check(unit.subject, body)
            result.compatibility = "new_subject" if compatible is None else "compatible"
            if compatible is False:
                result.status, result.compatibility = "incompatible", None
                result.messages.extend(messages)
                continue
            if dry_run:
                result.status = "would_register"
                continue
            registered = registry.register(unit.subject, body)
            result.schema_id = _int(registered.get("id"))
            result.version = _int(registered.get("version"))
            if result.version is None:
                landed = registry.lookup(unit.subject, body) or {}
                result.version = _int(landed.get("version"))
            result.status = "registered"
        except _RegistryError as exc:
            # 409 on register is Confluent's "incompatible with an earlier schema".
            result.status = "incompatible" if exc.status == 409 else "failed"
            if exc.status == 409:
                result.compatibility = None
            result.messages.append(_redact(str(exc), credentials))
    return results
