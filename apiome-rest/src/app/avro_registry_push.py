"""Push an Avro export to a live Confluent Schema Registry — MFX-19.4 (#3912).

The Avro export (MFX-19.1) writes one ``.avsc`` per named type, each with the subject MFX-19.3's
naming strategy gives it. This module registers those schemas on an upstream registry that speaks
the Confluent Schema Registry REST API (Confluent Platform or Cloud, Karapace, Apicurio's ``ccompat``
API) through an existing ``schema-registry`` connector: the connector's base URL and its stored
credentials, over the same SSRF-guarded client the connector's sync uses
(:class:`~app.schema_registry_connector_source.SchemaRegistrySource`). It is the import connector's
client used in reverse.

**Plan** (:func:`plan_avro_push`). Each emitted file becomes one unit: its subject, its schema text
and the other units it references by name. A schema that names a type of another file is
registered with a Confluent ``references`` entry (``{name, subject, version}``) pointing at that
file's subject, so the units are ordered dependencies first. Two files with the same subject — every
type under ``topic_name`` — cannot be pushed: a subject holds one schema.

**Push** (:func:`push_avro_subjects`), per subject in that order:

1. ``POST /subjects/{s}`` — when the registry already holds this exact schema under the subject,
   the subject is ``already_registered`` with its id and version, and nothing is written;
2. ``POST /compatibility/subjects/{s}/versions/latest?verbose=true`` — the new schema is checked
   against the subject's latest version under the subject's compatibility level; an incompatible
   schema is ``incompatible`` with the registry's messages, and is not registered. A subject the
   registry does not have yet (``404``) has nothing to be compatible with;
3. ``POST /subjects/{s}/versions`` — the schema is registered; its id comes back, and its version
   is read with step 1 again. A dry run stops before this step (``would_register``).

A subject whose dependency did not register is ``skipped``; one the registry refuses is
``failed`` with the registry's message. In a dry run, a subject that references a schema the run
would register cannot be checked (the referenced version does not exist yet): it is
``would_register`` with ``compatibility: unchecked``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from .emitter import EmitResult
from .schema_registry_connector_source import _error_detail
from .ssrf_guard import SSRFError

__all__ = [
    "AvroPushError",
    "AvroPushSubjectResult",
    "AvroPushUnit",
    "plan_avro_push",
    "push_avro_subjects",
]

#: Avro's primitive type names — a type position holding one of these is not a reference.
_PRIMITIVES = frozenset({"null", "boolean", "int", "long", "float", "double", "bytes", "string"})

#: The Avro schema types that define a name.
_NAMED = frozenset({"record", "error", "enum", "fixed"})

#: The registry statuses a dependent can build on.
_LANDED = frozenset({"registered", "already_registered", "would_register"})

PushStatus = Literal["registered", "already_registered", "would_register", "incompatible", "failed", "skipped"]
Compatibility = Literal["compatible", "new_subject", "unchecked"]


class AvroPushError(Exception):
    """A push refused before anything is sent to the registry.

    Args:
        code: A stable error code (``AVRO_PUSH_…``).
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
class AvroPushUnit:
    """One emitted schema to register.

    Attributes:
        subject: The registry subject (MFX-19.3).
        file: The emitted file's path.
        schema: The schema text sent to the registry.
        record: The schema's full name, when it defines one (a top-level union or map does not).
        depends_on: The full names of other units' types this schema references.
    """

    subject: str
    file: str
    schema: str
    record: Optional[str] = None
    depends_on: Sequence[str] = field(default_factory=tuple)


class AvroPushReference(BaseModel):
    """A Confluent schema reference: the referenced type's full name, subject and version."""

    name: str = Field(description="The referenced type's full Avro name.")
    subject: str = Field(description="The subject the referenced schema is registered under.")
    version: Optional[int] = Field(
        default=None,
        description="The registered version referenced; null in a dry run when that schema would be "
        "registered by this push.",
    )


class AvroPushSubjectResult(BaseModel):
    """What the push did for one subject."""

    subject: str = Field(description="The registry subject.")
    file: str = Field(description="The emitted ``.avsc`` file registered under it.")
    record: Optional[str] = Field(default=None, description="The schema's full Avro name, when it has one.")
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
    schema_id: Optional[int] = Field(default=None, description="The registry's global schema id.")
    version: Optional[int] = Field(default=None, description="The subject version holding the schema.")
    references: List[AvroPushReference] = Field(
        default_factory=list, description="The schema references sent with the schema."
    )
    messages: List[str] = Field(
        default_factory=list,
        description="The registry's compatibility messages, error, or why the subject was skipped.",
    )


# ---------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------


def _split_name(name: str, namespace: Optional[str]) -> tuple:
    """``(fullname, namespace)`` of a name as Avro resolves it inside ``namespace``."""
    if "." in name:
        return name, name.rpartition(".")[0]
    return (f"{namespace}.{name}" if namespace else name), namespace


def _names(schema: Any) -> tuple:
    """``(defined, referenced)`` full names of one schema, walked as Avro resolves names."""
    defined: Set[str] = set()
    referenced: Set[str] = set()

    def walk(node: Any, namespace: Optional[str]) -> None:
        if isinstance(node, str):
            if node not in _PRIMITIVES:
                referenced.add(_split_name(node, namespace)[0])
        elif isinstance(node, list):
            for member in node:
                walk(member, namespace)
        elif isinstance(node, Mapping):
            kind = node.get("type")
            if kind in _NAMED and isinstance(node.get("name"), str):
                own_namespace = node.get("namespace") if isinstance(node.get("namespace"), str) else namespace
                fullname, inner = _split_name(node["name"], own_namespace or None)
                defined.add(fullname)
                for entry in node.get("fields") or []:
                    if isinstance(entry, Mapping):
                        walk(entry.get("type"), inner)
            elif kind == "array":
                walk(node.get("items"), namespace)
            elif kind == "map":
                walk(node.get("values"), namespace)
            else:
                walk(kind, namespace)

    walk(schema, None)
    return defined, referenced


def _top_name(schema: Any) -> Optional[str]:
    """The full name a top-level schema defines, if any."""
    if isinstance(schema, Mapping) and schema.get("type") in _NAMED and isinstance(schema.get("name"), str):
        namespace = schema.get("namespace") if isinstance(schema.get("namespace"), str) else None
        return _split_name(schema["name"], namespace or None)[0]
    return None


def _schema_object(content: Any, path: str) -> Any:
    """An emitted file's schema as JSON data (the emitter writes a dict; text is parsed)."""
    if isinstance(content, (bytes, str)):
        try:
            return json.loads(content)
        except ValueError as exc:
            raise AvroPushError("AVRO_PUSH_NOT_AVSC", f"{path} is not an Avro JSON schema (.avsc).") from exc
    return content


def plan_avro_push(emit: EmitResult) -> List[AvroPushUnit]:
    """The units of an Avro export to register, dependencies first.

    Args:
        emit: The Avro emitter's ``.avsc`` output (one file per named type, each with a subject).

    Returns:
        One unit per file, ordered so every schema comes after the schemas it references (ties by
        subject, so the order is deterministic).

    Raises:
        AvroPushError: The export wrote no schema, a file has no subject or is not ``.avsc``, two
            files share a subject, or the references form a cycle.
    """
    if not emit.files:
        raise AvroPushError("AVRO_PUSH_EMPTY", "The Avro export wrote no schema to register.")
    drafts: List[Dict[str, Any]] = []
    owners: Dict[str, str] = {}
    by_subject: Dict[str, str] = {}
    for emitted in emit.files:
        subject = (emitted.subject or "").strip()
        if not subject:
            raise AvroPushError("AVRO_PUSH_NO_SUBJECT", f"{emitted.path} has no registry subject.")
        if subject in by_subject:
            raise AvroPushError(
                "AVRO_PUSH_DUPLICATE_SUBJECT",
                f"{by_subject[subject]} and {emitted.path} both map to subject {subject!r}; a subject holds one "
                "schema. Use subject_naming record_name or topic_record_name, or export one type.",
            )
        by_subject[subject] = emitted.path
        schema = _schema_object(emitted.content, emitted.path)
        defined, referenced = _names(schema)
        record = _top_name(schema)
        for name in defined:
            owners.setdefault(name, subject)
        drafts.append({"subject": subject, "file": emitted.path, "schema": schema, "record": record,
                       "defined": defined, "referenced": referenced})

    units: Dict[str, AvroPushUnit] = {}
    for draft in drafts:
        # Only a name another unit defines at its top level is a cross-subject reference.
        deps = sorted(
            name for name in draft["referenced"] - draft["defined"]
            if owners.get(name) not in (None, draft["subject"])
        )
        units[draft["subject"]] = AvroPushUnit(
            subject=draft["subject"],
            file=draft["file"],
            schema=json.dumps(draft["schema"], ensure_ascii=False, separators=(",", ":")),
            record=draft["record"],
            depends_on=tuple(deps),
        )

    ordered: List[AvroPushUnit] = []
    placed: Set[str] = set()
    pending = sorted(units)
    while pending:
        ready = [s for s in pending if all(owners[d] in placed for d in units[s].depends_on)]
        if not ready:
            raise AvroPushError(
                "AVRO_PUSH_REFERENCE_CYCLE",
                f"The schemas of subjects {', '.join(pending)} reference each other; a registry cannot hold them.",
            )
        for subject in ready:
            ordered.append(units[subject])
            placed.add(subject)
        pending = [s for s in pending if s not in placed]
    return ordered


# ---------------------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------------------


class _RegistryError(Exception):
    """A registry call that failed: the registry's status (``None`` when it did not answer) and message."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class _Registry:
    """The three Confluent calls a push makes, on one SSRF-guarded client."""

    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")

    def _post(self, path: str, body: Mapping[str, Any], params: Optional[Mapping[str, str]] = None) -> tuple:
        """``(status, json body or None)`` of a POST; raises :class:`_RegistryError` when there is no answer."""
        try:
            response = self._client.post(f"{self._base}{path}", json=dict(body), params=dict(params or {}))
        except SSRFError as exc:
            raise _RegistryError(f"Request to the schema registry refused: {exc}") from exc
        except httpx.HTTPError as exc:
            raise _RegistryError(f"The schema registry did not answer POST {path}: {type(exc).__name__}") from exc
        if 200 <= response.status_code < 300:
            try:
                return response.status_code, response.json()
            except ValueError as exc:
                raise _RegistryError(
                    f"The schema registry answered POST {path} with a body that is not JSON.", response.status_code
                ) from exc
        return response.status_code, _error_detail(response)

    @staticmethod
    def _fail(path: str, status: int, detail: Any) -> _RegistryError:
        return _RegistryError(
            f"The schema registry answered {status} to POST {path}" + (f": {detail}" if detail else ""), status
        )

    def lookup(self, subject: str, body: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        """The subject's version holding this exact schema (``{id, version}``), or ``None``."""
        path = f"/subjects/{quote(subject, safe='')}"
        status, data = self._post(path, body)
        if status == 404:
            return None
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail(path, status, data)
        return data

    def check(self, subject: str, body: Mapping[str, Any]) -> tuple:
        """``(compatible, messages)``; ``(None, [])`` when the subject has no version yet."""
        path = f"/compatibility/subjects/{quote(subject, safe='')}/versions/latest"
        status, data = self._post(path, body, {"verbose": "true"})
        if status == 404:
            return None, []
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail(path, status, data)
        messages = data.get("messages")
        return bool(data.get("is_compatible")), [str(m) for m in messages] if isinstance(messages, list) else []

    def register(self, subject: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Register the schema; the registry's answer (``{id}``, sometimes with ``version``)."""
        path = f"/subjects/{quote(subject, safe='')}/versions"
        status, data = self._post(path, body)
        if not 200 <= status < 300 or not isinstance(data, Mapping):
            raise self._fail(path, status, data)
        return data


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _redact(message: str, credentials: Optional[Mapping[str, str]]) -> str:
    """``message`` with every stored credential value removed."""
    for value in (credentials or {}).values():
        if value and len(value) >= 4:
            message = message.replace(value, "[redacted]")
    return message


def push_avro_subjects(
    client: httpx.Client,
    registry_url: str,
    units: Sequence[AvroPushUnit],
    *,
    dry_run: bool = False,
    credentials: Optional[Mapping[str, str]] = None,
) -> List[AvroPushSubjectResult]:
    """Check and register each unit on the registry, in plan order.

    Args:
        client: An SSRF-guarded client carrying the connector's credentials.
        registry_url: The registry's base URL.
        units: The plan from :func:`plan_avro_push`.
        dry_run: Look up and check every subject, but register nothing.
        credentials: The connector's credentials, removed from any registry message reported back.

    Returns:
        One result per unit, in the same order.
    """
    registry = _Registry(client, registry_url)
    owner_of: Dict[str, AvroPushSubjectResult] = {}
    results: List[AvroPushSubjectResult] = []
    for unit in units:
        result = AvroPushSubjectResult(subject=unit.subject, file=unit.file, record=unit.record, status="failed")
        results.append(result)
        if unit.record:
            owner_of[unit.record] = result
        deps = [owner_of[name] for name in unit.depends_on]
        missing = [dep.subject for dep in deps if dep.status not in _LANDED]
        if missing:
            result.status = "skipped"
            result.messages = [f"Not pushed: referenced subject {s!r} did not register." for s in missing]
            continue
        result.references = [
            AvroPushReference(name=name, subject=dep.subject, version=dep.version)
            for name, dep in zip(unit.depends_on, deps)
        ]
        if any(ref.version is None for ref in result.references):
            # Dry run only: a referenced schema would be registered by this push, so its version
            # does not exist yet and the registry can neither look this schema up nor check it.
            result.status, result.compatibility = "would_register", "unchecked"
            result.messages = ["Compatibility not checked: a schema this one references is not registered yet."]
            continue
        body: Dict[str, Any] = {"schema": unit.schema}
        if result.references:
            body["references"] = [ref.model_dump() for ref in result.references]
        try:
            existing = registry.lookup(unit.subject, body)
            if existing is not None:
                result.status = "already_registered"
                result.schema_id, result.version = _int(existing.get("id")), _int(existing.get("version"))
                continue
            compatible, messages = registry.check(unit.subject, body)
            result.compatibility = "new_subject" if compatible is None else "compatible"
            if compatible is False:
                result.status, result.compatibility, result.messages = "incompatible", None, messages
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
            result.messages = [_redact(str(exc), credentials)]
    return results
