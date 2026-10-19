"""Confluent-compatible schema registry API (CDG-4.3, #5975).

Kafka serializers — ``confluent-kafka``, ``kafka-avro-serializer``, Spring — speak one HTTP contract;
this router serves it at ``/registry/schema/{tenant}`` over the CDG-4.2 subject model, so a client
points its ``schema.registry.url`` at that base and needs no other change:

* ``GET /subjects`` · ``GET|POST /subjects/{s}/versions`` · ``POST /subjects/{s}`` (lookup) ·
  ``GET /subjects/{s}/versions/{v}`` and ``…/schema`` · ``DELETE /subjects/{s}[?permanent=true]``
* ``GET /schemas/ids/{id}`` · ``…/subjects`` · ``…/versions`` · ``GET /schemas/types``
* ``GET|PUT /config`` and ``/config/{s}`` · ``GET|PUT /mode`` and ``/mode/{s}``
* ``POST /compatibility/subjects/{s}/versions[/{v}]``

Responses use ``application/vnd.schemaregistry.v1+json``; errors use Confluent's body
``{"error_code", "message"}`` and codes (``40401`` subject, ``40402`` version, ``40403`` schema not
found, ``42201`` invalid schema, ``42205`` read-only, …).

**Compatibility.** No XPC-4.x rules have shipped, so a new version under any level but ``NONE`` is
refused with ``422`` / ``error_code`` ``42290`` (``compatibility-rules-unavailable``) instead of being
accepted unchecked; ``/schemas/types?details=true`` says so per type.

**Auth.** Workspace API keys only — no second key system. A Confluent client sends basic auth
``<any-name>:<api-key>`` (the password is the key) or ``Authorization: Bearer <api-key>``;
``X-API-Key`` and a signed-in session work too. A restricted key needs ``registry:read`` for reads
and ``registry:write`` for writes (:mod:`app.auth` allowlist), and the key's user needs the matching
``imports`` permission. Every write is audited (``registry.subject.register|config|delete``).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from . import schema_registry_store as store
from .auth import decode_jwt, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .registry_audit import (
    ACTION_SUBJECT_CONFIG,
    ACTION_SUBJECT_DELETE,
    ACTION_SUBJECT_REGISTER,
    record_registry_audit,
)
from .schema_registry import (
    COMPATIBILITY_LEVELS,
    LEVEL_NONE,
    MODES,
    SCHEMA_TYPE_AVRO,
    SchemaRegistryError,
    compatibility_rules_available,
    registrable_schema_types,
    validate_subject_name,
)
from .schema_registry_service import (
    check_compatibility,
    effective_level,
    lookup_schema,
    register_schema,
    schema_text,
)

router = APIRouter(prefix="/registry/schema", tags=["schema-registry"])

#: The Confluent v1 content type every response carries.
CONFLUENT_MEDIA_TYPE = "application/vnd.schemaregistry.v1+json"

#: Apiome's error code for a check XPC-4.x cannot answer yet (Confluent's 422xx range).
ERROR_COMPATIBILITY_RULES_UNAVAILABLE = 42290

#: Registry refusal code → (HTTP status, Confluent ``error_code``).
_CONFLUENT_CODES: Dict[str, tuple] = {
    "subject-not-found": (404, 40401),
    "version-not-found": (404, 40402),
    "schema-not-found": (404, 40403),
    "subject-soft-deleted": (404, 40404),
    "subject-not-soft-deleted": (404, 40405),
    "subject-level-not-configured": (404, 40408),
    "subject-invalid": (422, 42201),
    "schema-invalid": (422, 42201),
    "schemaType-invalid": (422, 42201),
    "schema-type-unavailable": (422, 42201),
    "references-invalid": (422, 42201),
    "schema-import-failed": (422, 42201),
    "version-invalid": (422, 42202),
    "compatibilityLevel-invalid": (422, 42203),
    "mode-invalid": (422, 42204),
    "subject-read-only": (422, 42205),
    "compatibility-rules-unavailable": (422, ERROR_COMPATIBILITY_RULES_UNAVAILABLE),
}


class ConfluentRegistryError(Exception):
    """An error answered in Confluent's shape (handled by :func:`confluent_error_handler`).

    Attributes:
        status_code: The HTTP status.
        error_code: Confluent's integer ``error_code``.
        message: The human message.
    """

    def __init__(self, status_code: int, error_code: int, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(message)

    @classmethod
    def from_registry(cls, exc: SchemaRegistryError) -> "ConfluentRegistryError":
        """Map a :class:`SchemaRegistryError` onto Confluent's status and code."""
        status, code = _CONFLUENT_CODES.get(exc.code, (exc.status_code, exc.status_code * 100 + 1))
        message = str(exc) if exc.code != "compatibility-rules-unavailable" else f"{exc.code}: {exc}"
        return cls(status, code, message)

    @classmethod
    def from_http(cls, exc: HTTPException) -> "ConfluentRegistryError":
        """Map an auth/permission ``HTTPException`` (``401``/``403``/``404``) onto Confluent's shape."""
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return cls(exc.status_code, exc.status_code * 100 + 1, detail)


async def confluent_error_handler(_request: Request, exc: ConfluentRegistryError) -> JSONResponse:
    """Render a :class:`ConfluentRegistryError` as ``{"error_code", "message"}`` (registered in main)."""
    headers = {"WWW-Authenticate": 'Basic realm="apiome-schema-registry"'} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
        media_type=CONFLUENT_MEDIA_TYPE,
        headers=headers,
    )


def _ok(content: Any) -> JSONResponse:
    """A ``200`` in the Confluent content type."""
    return JSONResponse(content=content, media_type=CONFLUENT_MEDIA_TYPE)


def _registry_error(code: str, message: str, status_code: int = 404) -> ConfluentRegistryError:
    """Build a Confluent error from a registry code."""
    return ConfluentRegistryError.from_registry(SchemaRegistryError(code, message, status_code=status_code))


def api_key_from_basic(authorization: str) -> Optional[str]:
    """Return the password of an HTTP basic ``Authorization`` value — the API key — or ``None``.

    Confluent clients send ``basic.auth.user.info = "<name>:<secret>"``; the name is ignored and the
    secret is the workspace API key.

    Args:
        authorization: The full header value (``Basic <base64>``).

    Returns:
        The API key, or ``None`` when the value is not well-formed basic auth.
    """
    scheme, _, encoded = authorization.strip().partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    _, sep, password = decoded.partition(":")
    return password if sep and password else None


def registry_auth(
    request: Request,
    tenant: str,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Authenticate a registry call: basic auth, bearer API key, ``X-API-Key`` or a session.

    Everything funnels into :func:`app.auth.validate_authentication`, so tenant matching and the
    ``registry:read`` / ``registry:write`` scope allowlist are enforced exactly as on every route.

    Raises:
        ConfluentRegistryError: ``401`` / ``403`` in Confluent's shape.
    """
    session: Optional[str] = None
    key = x_api_key
    if authorization:
        scheme = authorization.strip().partition(" ")[0].lower()
        if scheme == "basic":
            key = api_key_from_basic(authorization)
            if key is None:
                raise ConfluentRegistryError(401, 40101, "Malformed basic auth credentials.")
        elif scheme == "bearer" and decode_jwt(authorization):
            session = authorization
        elif scheme == "bearer":
            key = authorization.strip().partition(" ")[2].strip()
    try:
        return validate_authentication(request, tenant, session, key)
    except HTTPException as exc:
        raise ConfluentRegistryError.from_http(exc) from exc


def _permit(auth_data: Dict[str, Any], action: str, target: str) -> Optional[str]:
    """Require ``imports:<action>``; return the acting user id."""
    try:
        return enforce_permission(db, auth_data, Resource.IMPORTS, action, target=target)
    except HTTPException as exc:
        raise ConfluentRegistryError.from_http(exc) from exc


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise ConfluentRegistryError(403, 40301, "No tenant context for the schema registry.")
    return str(tenant_id)


def _live_subject(tenant_id: str, subject: str) -> Dict[str, Any]:
    """Return the live subject or raise ``40401``."""
    try:
        validate_subject_name(subject)
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    row = store.get_subject(db, tenant_id, subject)
    if row is None:
        raise _registry_error("subject-not-found", f"Subject '{subject}' not found.")
    return row


def _parse_version(version: str) -> Optional[int]:
    """Parse a version path segment: a positive integer, or ``latest`` / ``-1`` (→ ``None``)."""
    if version in ("latest", "-1"):
        return None
    if version.isdigit() and int(version) >= 1:
        return int(version)
    raise _registry_error("version-invalid", "The specified version is not a valid version id.", 422)


def _version_row(tenant_id: str, subject: str, version: str) -> Dict[str, Any]:
    """Resolve ``subject`` + ``version`` to a live version row, or raise ``40401`` / ``40402``."""
    row = _live_subject(tenant_id, subject)
    number = _parse_version(version)
    if number is None:
        versions = store.list_versions(db, str(row["id"]))
        found = versions[-1] if versions else None
    else:
        found = store.get_version(db, str(row["id"]), number)
    if found is None:
        raise _registry_error("version-not-found", f"Version {version} not found.")
    return found


def _schema_body(row: Dict[str, Any], text: Optional[str]) -> Dict[str, Any]:
    """The shared ``schema`` / ``schemaType`` / ``references`` fields (``schemaType`` omitted for Avro)."""
    body: Dict[str, Any] = {"schema": text or ""}
    if row["schema_type"] != SCHEMA_TYPE_AVRO:
        body["schemaType"] = row["schema_type"]
    if row.get("references"):
        body["references"] = list(row["references"])
    return body


def _schema_args(body: Dict[str, Any]) -> Dict[str, Any]:
    """Read ``schema`` / ``schemaType`` / ``references`` from a request body, or raise ``42201``."""
    if not isinstance(body, dict) or not isinstance(body.get("schema"), str):
        raise _registry_error("schema-invalid", "A request body with a `schema` string is required.", 422)
    schema_type = body.get("schemaType") or SCHEMA_TYPE_AVRO
    references = body.get("references") or []
    return {"schema": body["schema"], "schema_type": schema_type, "references": references}


def _choice(body: Dict[str, Any], field: str, allowed: tuple, code: str) -> str:
    """Read an enumerated field from a config / mode body, or raise its Confluent error."""
    value = body.get(field) if isinstance(body, dict) else None
    if value not in allowed:
        raise _registry_error(code, f"Invalid {field} {value!r}; use one of {', '.join(allowed)}.", 422)
    return str(value)


# --------------------------------------------------------------------------- subjects


@router.get("/{tenant}/subjects")
async def confluent_list_subjects(
    tenant: str,
    deleted: bool = Query(False, description="Include soft-deleted subjects."),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """List subject names (Confluent ``GET /subjects``)."""
    _permit(auth_data, Action.VIEW, "schema-registry")
    return _ok(store.list_subject_names(db, _tenant_id(auth_data), include_deleted=deleted))


@router.get("/{tenant}/subjects/{subject}/versions")
async def confluent_list_versions(
    tenant: str, subject: str, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """List a subject's live version numbers (Confluent ``GET /subjects/{s}/versions``)."""
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    row = _live_subject(_tenant_id(auth_data), subject)
    return _ok([int(v["version"]) for v in store.list_versions(db, str(row["id"]))])


@router.post("/{tenant}/subjects/{subject}/versions")
async def confluent_register(
    tenant: str,
    subject: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Register a schema under a subject and return its id (Confluent ``POST /subjects/{s}/versions``).

    Registering content the subject already holds returns the same id. A new version under a level
    other than ``NONE`` is refused with ``42290`` until XPC-4.x rules exist for the schema type.
    """
    tenant_id = _tenant_id(auth_data)
    actor_id = _permit(auth_data, Action.CREATE, f"subject:{subject}")
    args = _schema_args(body)
    try:
        row = await asyncio.to_thread(
            register_schema, db, tenant_id=tenant_id, actor_id=actor_id, subject=subject, **args
        )
    except SchemaRegistryError as exc:
        record_registry_audit(
            db, auth_data, ACTION_SUBJECT_REGISTER, "failure", namespace=subject, detail={"code": exc.code}
        )
        raise ConfluentRegistryError.from_registry(exc) from exc
    if row.get("created"):
        record_registry_audit(
            db,
            auth_data,
            ACTION_SUBJECT_REGISTER,
            schema_id=str(row["schema_id"]),
            namespace=subject,
            detail={"version": int(row["version"]), "schemaType": row["schema_type"]},
        )
    return _ok({"id": int(row["schema_id"])})


@router.post("/{tenant}/subjects/{subject}")
async def confluent_lookup(
    tenant: str,
    subject: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Find the version of a subject that holds a schema (Confluent ``POST /subjects/{s}``)."""
    tenant_id = _tenant_id(auth_data)
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    args = _schema_args(body)
    try:
        found = await asyncio.to_thread(
            lookup_schema,
            db,
            tenant_id=tenant_id,
            subject=subject,
            schema=args["schema"],
            schema_type=args["schema_type"],
        )
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    if found is None:
        raise _registry_error("schema-not-found", "Schema not found under this subject.")
    return _ok(
        {"subject": subject, "id": int(found["schema_id"]), "version": int(found["version"]),
         **_schema_body(found, args["schema"])}
    )


@router.get("/{tenant}/subjects/{subject}/versions/{version}")
async def confluent_get_version(
    tenant: str, subject: str, version: str, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """Return one version (``latest`` and ``-1`` work) (Confluent ``GET /subjects/{s}/versions/{v}``)."""
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    row = _version_row(_tenant_id(auth_data), subject, version)
    text = await asyncio.to_thread(schema_text, db, row["version_record_id"])
    return _ok({"subject": subject, "id": int(row["schema_id"]), "version": int(row["version"]),
                **_schema_body(row, text)})


@router.get("/{tenant}/subjects/{subject}/versions/{version}/schema")
async def confluent_get_version_schema(
    tenant: str, subject: str, version: str, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> Response:
    """Return only the schema text of one version (Confluent ``…/versions/{v}/schema``)."""
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    row = _version_row(_tenant_id(auth_data), subject, version)
    text = await asyncio.to_thread(schema_text, db, row["version_record_id"])
    return Response(content=text or "", media_type=CONFLUENT_MEDIA_TYPE)


@router.delete("/{tenant}/subjects/{subject}")
async def confluent_delete_subject(
    tenant: str,
    subject: str,
    permanent: bool = Query(False, description="Hard-delete a subject that was soft-deleted first."),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Delete a subject (Confluent ``DELETE /subjects/{s}``); returns the deleted versions.

    A soft delete (``imports:edit``) hides the subject and its versions; ids keep resolving.
    ``?permanent=true`` (``imports:delete``) removes a soft-deleted subject's rows; the catalog item
    revisions are never deleted.
    """
    tenant_id = _tenant_id(auth_data)
    _permit(auth_data, Action.DELETE if permanent else Action.EDIT, f"subject:{subject}")
    try:
        validate_subject_name(subject)
        if permanent:
            versions = store.hard_delete_subject(db, tenant_id, subject)
        else:
            versions = store.soft_delete_subject(db, tenant_id, subject)
            if versions is None and subject in store.list_subject_names(db, tenant_id, include_deleted=True):
                raise SchemaRegistryError("subject-soft-deleted", f"Subject '{subject}' was soft deleted.")
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    if versions is None:
        raise _registry_error("subject-not-found", f"Subject '{subject}' not found.")
    record_registry_audit(
        db, auth_data, ACTION_SUBJECT_DELETE, namespace=subject,
        detail={"permanent": permanent, "versions": versions},
    )
    return _ok(versions)


# --------------------------------------------------------------------------- schemas


@router.get("/{tenant}/schemas/types")
async def confluent_schema_types(
    tenant: str,
    details: bool = Query(False, description="Label each type with what it can be registered under."),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """List the schema types this registry accepts (Confluent ``GET /schemas/types``).

    Only types this deployment can read are listed (Protobuf needs the bundled ``buf``). With
    ``details=true`` each is labelled: ``compatibilityRules`` is ``available`` or ``unavailable``
    (XPC-4.x) and ``registrableUnder`` names the levels a new version can be registered under.
    """
    _permit(auth_data, Action.VIEW, "schema-registry")
    types = list(registrable_schema_types())
    if not details:
        return _ok(types)
    return _ok(
        [
            {
                "schemaType": t,
                "compatibilityRules": "available" if compatibility_rules_available(t) else "unavailable",
                "registrableUnder": list(COMPATIBILITY_LEVELS) if compatibility_rules_available(t) else [LEVEL_NONE],
            }
            for t in types
        ]
    )


def _schema_by_id(tenant_id: str, schema_id: int) -> Dict[str, Any]:
    """Resolve a schema id or raise ``40403``."""
    row = store.get_schema_by_id(db, tenant_id, schema_id)
    if row is None:
        raise _registry_error("schema-not-found", f"Schema {schema_id} not found.")
    return row


@router.get("/{tenant}/schemas/ids/{schema_id}")
async def confluent_schema_by_id(
    tenant: str, schema_id: int, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """Return a schema by id — it resolves after its subjects are deleted (Confluent ``/schemas/ids/{id}``)."""
    _permit(auth_data, Action.VIEW, f"schema:{schema_id}")
    row = _schema_by_id(_tenant_id(auth_data), schema_id)
    text = await asyncio.to_thread(schema_text, db, row["version_record_id"])
    return _ok(_schema_body(row, text))


@router.get("/{tenant}/schemas/ids/{schema_id}/subjects")
async def confluent_schema_subjects(
    tenant: str, schema_id: int, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """List the live subjects holding a schema id (Confluent ``/schemas/ids/{id}/subjects``)."""
    _permit(auth_data, Action.VIEW, f"schema:{schema_id}")
    row = _schema_by_id(_tenant_id(auth_data), schema_id)
    return _ok(sorted({s["subject"] for s in row.get("subjects") or []}))


@router.get("/{tenant}/schemas/ids/{schema_id}/versions")
async def confluent_schema_versions(
    tenant: str, schema_id: int, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """List the live subject versions holding a schema id (Confluent ``/schemas/ids/{id}/versions``)."""
    _permit(auth_data, Action.VIEW, f"schema:{schema_id}")
    row = _schema_by_id(_tenant_id(auth_data), schema_id)
    return _ok(list(row.get("subjects") or []))


# --------------------------------------------------------------------------- config and mode


@router.get("/{tenant}/config")
async def confluent_get_config(tenant: str, auth_data: Dict[str, Any] = Depends(registry_auth)) -> JSONResponse:
    """Return the tenant's default compatibility level (Confluent ``GET /config``)."""
    _permit(auth_data, Action.VIEW, "schema-registry")
    return _ok({"compatibilityLevel": store.get_config(db, _tenant_id(auth_data))["compatibility_level"]})


@router.put("/{tenant}/config")
async def confluent_put_config(
    tenant: str, body: Dict[str, Any] = Body(...), auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """Set the tenant's default compatibility level (Confluent ``PUT /config``)."""
    _permit(auth_data, Action.EDIT, "schema-registry")
    level = _choice(body, "compatibility", COMPATIBILITY_LEVELS, "compatibilityLevel-invalid")
    store.put_config(db, _tenant_id(auth_data), compatibility_level=level, mode=None)
    record_registry_audit(db, auth_data, ACTION_SUBJECT_CONFIG, detail={"compatibility": level})
    return _ok({"compatibility": level})


@router.get("/{tenant}/config/{subject}")
async def confluent_get_subject_config(
    tenant: str,
    subject: str,
    defaultToGlobal: bool = Query(False, description="Fall back to the tenant default."),  # noqa: N803
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Return a subject's compatibility level (Confluent ``GET /config/{s}``)."""
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    tenant_id = _tenant_id(auth_data)
    row = _live_subject(tenant_id, subject)
    if not row.get("compatibility_level") and not defaultToGlobal:
        raise _registry_error(
            "subject-level-not-configured", f"Subject '{subject}' does not have subject-level compatibility configured."
        )
    return _ok({"compatibilityLevel": effective_level(db, tenant_id, row)})


@router.put("/{tenant}/config/{subject}")
async def confluent_put_subject_config(
    tenant: str,
    subject: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Set a subject's compatibility level, creating the subject if needed (Confluent ``PUT /config/{s}``)."""
    actor_id = _permit(auth_data, Action.EDIT, f"subject:{subject}")
    level = _choice(body, "compatibility", COMPATIBILITY_LEVELS, "compatibilityLevel-invalid")
    try:
        validate_subject_name(subject)
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    store.upsert_subject(
        db, _tenant_id(auth_data), subject, strategy=None, compatibility_level=level, mode=None, actor_id=actor_id
    )
    record_registry_audit(db, auth_data, ACTION_SUBJECT_CONFIG, namespace=subject, detail={"compatibility": level})
    return _ok({"compatibility": level})


@router.get("/{tenant}/mode")
async def confluent_get_mode(tenant: str, auth_data: Dict[str, Any] = Depends(registry_auth)) -> JSONResponse:
    """Return the tenant's default mode (Confluent ``GET /mode``)."""
    _permit(auth_data, Action.VIEW, "schema-registry")
    return _ok({"mode": store.get_config(db, _tenant_id(auth_data))["mode"]})


@router.put("/{tenant}/mode")
async def confluent_put_mode(
    tenant: str, body: Dict[str, Any] = Body(...), auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """Set the tenant's default mode, ``READWRITE`` or ``READONLY`` (Confluent ``PUT /mode``)."""
    _permit(auth_data, Action.EDIT, "schema-registry")
    mode = _choice(body, "mode", MODES, "mode-invalid")
    store.put_config(db, _tenant_id(auth_data), compatibility_level=None, mode=mode)
    record_registry_audit(db, auth_data, ACTION_SUBJECT_CONFIG, detail={"mode": mode})
    return _ok({"mode": mode})


@router.get("/{tenant}/mode/{subject}")
async def confluent_get_subject_mode(
    tenant: str, subject: str, auth_data: Dict[str, Any] = Depends(registry_auth)
) -> JSONResponse:
    """Return a subject's mode (Confluent ``GET /mode/{s}``)."""
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    return _ok({"mode": _live_subject(_tenant_id(auth_data), subject)["mode"]})


@router.put("/{tenant}/mode/{subject}")
async def confluent_put_subject_mode(
    tenant: str,
    subject: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Set a subject's mode, creating the subject if needed (Confluent ``PUT /mode/{s}``)."""
    actor_id = _permit(auth_data, Action.EDIT, f"subject:{subject}")
    mode = _choice(body, "mode", MODES, "mode-invalid")
    try:
        validate_subject_name(subject)
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    store.upsert_subject(
        db, _tenant_id(auth_data), subject, strategy=None, compatibility_level=None, mode=mode, actor_id=actor_id
    )
    record_registry_audit(db, auth_data, ACTION_SUBJECT_CONFIG, namespace=subject, detail={"mode": mode})
    return _ok({"mode": mode})


# --------------------------------------------------------------------------- compatibility


async def _compatibility(
    auth_data: Dict[str, Any], subject: str, version: Optional[str], body: Dict[str, Any]
) -> JSONResponse:
    """Shared body of the two compatibility routes."""
    tenant_id = _tenant_id(auth_data)
    _permit(auth_data, Action.VIEW, f"subject:{subject}")
    args = _schema_args(body)
    number: Optional[int] = None
    if version is not None:
        number = _parse_version(version)
        if number is None:
            versions = store.list_versions(db, str(_live_subject(tenant_id, subject)["id"]))
            number = int(versions[-1]["version"]) if versions else None
            if number is None:
                raise _registry_error("version-not-found", f"Version {version} not found.")
    try:
        verdict = await asyncio.to_thread(
            check_compatibility,
            db,
            tenant_id=tenant_id,
            subject=subject,
            schema=args["schema"],
            schema_type=args["schema_type"],
            version=number,
        )
    except SchemaRegistryError as exc:
        raise ConfluentRegistryError.from_registry(exc) from exc
    return _ok(verdict)


@router.post("/{tenant}/compatibility/subjects/{subject}/versions/{version}")
async def confluent_compatibility_version(
    tenant: str,
    subject: str,
    version: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Test a schema against one version (Confluent ``POST /compatibility/subjects/{s}/versions/{v}``)."""
    return await _compatibility(auth_data, subject, version, body)


@router.post("/{tenant}/compatibility/subjects/{subject}/versions")
async def confluent_compatibility_all(
    tenant: str,
    subject: str,
    body: Dict[str, Any] = Body(...),
    auth_data: Dict[str, Any] = Depends(registry_auth),
) -> JSONResponse:
    """Test a schema against the versions the level selects (Confluent ``…/compatibility/subjects/{s}/versions``)."""
    return await _compatibility(auth_data, subject, None, body)


__all__: List[str] = ["router", "ConfluentRegistryError", "confluent_error_handler", "CONFLUENT_MEDIA_TYPE"]
