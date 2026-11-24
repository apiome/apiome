"""Pact environments and deployment records: what they are — PFX-1.5 (#6918).

can-i-deploy (PFX-1.6) answers "is it safe to deploy this version to *production*?", so the broker
has to know what runs where. Three things record that:

* an **environment** — a place versions run (``test``, ``production``): its name, display name,
  whether it is production, Apiome's *contract required* flag and its contacts;
* a **deployed version** — one deployment of a pacticipant version to an environment, optionally
  to one *application instance* of it. Recording a deployment replaces the version deployed to the
  same environment and instance before it; the replaced deployment stays as history;
* a **released version** — a version released to an environment where several versions are live
  at once (a mobile app, a library), supported until support is recorded as ended.

This module is the pure part — the request bodies, as ``pact-broker create-environment``,
``record-deployment``, ``record-undeployment``, ``record-release`` and ``record-support-ended`` send
them, and the stored records. Persistence is :mod:`app.pact_environment_store`; the routes are
:mod:`app.pact_broker_environment_routes`.

An environment body, as the Pact Broker takes it::

    {"name": "production", "displayName": "Production", "production": true,
     "contacts": [{"name": "Team Ledger", "details": {"emailAddress": "ledger@example.com"}}]}

Apiome adds ``contractRequired`` (default ``false``): can-i-deploy to the environment refuses a
pacticipant that has no contract.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .pact_publication import PactPublicationError
from .pacticipant import MAX_LABEL_LENGTH

__all__ = [
    "CODE_DEPLOYED_VERSION_NOT_FOUND",
    "CODE_DEPLOYMENT_INVALID",
    "CODE_ENVIRONMENT_INVALID",
    "CODE_ENVIRONMENT_NAME_TAKEN",
    "CODE_ENVIRONMENT_NOT_FOUND",
    "CODE_RELEASED_VERSION_NOT_FOUND",
    "MAX_CONTACTS",
    "DeployedVersionRecord",
    "EnvironmentInput",
    "EnvironmentRecord",
    "ReleasedVersionRecord",
    "deployed_version_from_row",
    "environment_from_row",
    "parse_application_instance",
    "parse_environment_request",
    "parse_flag_patch",
    "released_version_from_row",
]

#: The environment body is malformed (HTTP 422, with a pointer).
CODE_ENVIRONMENT_INVALID = "pact-environment-invalid"
#: Another environment of the workspace has this name (HTTP 409).
CODE_ENVIRONMENT_NAME_TAKEN = "pact-environment-name-taken"
#: No such environment (HTTP 404).
CODE_ENVIRONMENT_NOT_FOUND = "pact-environment-not-found"
#: A deployment, undeployment, release or support-ended body is malformed (HTTP 422).
CODE_DEPLOYMENT_INVALID = "pact-deployment-invalid"
#: No such deployed version (HTTP 404).
CODE_DEPLOYED_VERSION_NOT_FOUND = "pact-deployed-version-not-found"
#: No such released version (HTTP 404).
CODE_RELEASED_VERSION_NOT_FOUND = "pact-released-version-not-found"

#: The most contacts one environment may list.
MAX_CONTACTS = 50

#: Mirrors V435: an environment name has no whitespace or control character.
_NAME_FORBIDDEN = re.compile(r"[\s\x00-\x1f\x7f]")
#: Control characters (line breaks included), refused in display names and instances.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _invalid(code: str, pointer: str, message: str) -> PactPublicationError:
    """A refusal of ``code`` locating ``pointer`` in the request body."""
    return PactPublicationError(code, f"{pointer or '(request body)'}: {message}", pointer=pointer)


def _decode(raw: bytes, code: str) -> Any:
    """Decode a JSON body; ``None`` when it is empty.

    Raises:
        PactPublicationError: ``code`` when the body is not JSON.
    """
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid(code, "", f"the request body is not JSON: {exc}") from exc


# ---------------------------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------------------------


class EnvironmentInput(BaseModel):
    """A checked environment body, ready to store (a create or a full replace).

    Attributes:
        name: The name tooling uses (``production``): no whitespace.
        display_name: The name people read; the name itself when not sent.
        production: Whether this is a production environment.
        contract_required: Apiome: whether can-i-deploy here requires a contract.
        contacts: ``[{"name": …, "details": {…}}]``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    production: bool = False
    contract_required: bool = False
    contacts: List[Dict[str, Any]] = Field(default_factory=list)


def _single_line(value: Any, pointer: str, *, required: bool) -> Optional[str]:
    """A trimmed one-line string of at most 255 characters, or ``None`` when absent.

    Raises:
        PactPublicationError: ``pact-environment-invalid`` for anything else.
    """
    if value is None:
        if required:
            raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, "is required")
        return None
    if not isinstance(value, str):
        raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, "must be a string")
    text = value.strip()
    if not text:
        if required:
            raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, "cannot be blank")
        return None
    if _CONTROL.search(text):
        raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, "must be a single line")
    if len(text) > MAX_LABEL_LENGTH:
        raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, f"must be at most {MAX_LABEL_LENGTH} characters")
    return text


def _flag(body: Mapping[str, Any], key: str) -> bool:
    """A boolean field; ``False`` when absent or null.

    Raises:
        PactPublicationError: ``pact-environment-invalid`` for a value that is not true or false.
    """
    value = body.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _invalid(CODE_ENVIRONMENT_INVALID, f"/{key}", "must be true or false")
    return value


def _contacts(value: Any) -> List[Dict[str, Any]]:
    """The ``contacts`` array: each a ``name`` and optional ``details`` object.

    Raises:
        PactPublicationError: ``pact-environment-invalid`` locating the bad contact.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise _invalid(CODE_ENVIRONMENT_INVALID, "/contacts", "must be an array")
    if len(value) > MAX_CONTACTS:
        raise _invalid(CODE_ENVIRONMENT_INVALID, "/contacts", f"list at most {MAX_CONTACTS} contacts")
    contacts: List[Dict[str, Any]] = []
    for index, raw in enumerate(value):
        pointer = f"/contacts/{index}"
        if not isinstance(raw, Mapping):
            raise _invalid(CODE_ENVIRONMENT_INVALID, pointer, "a contact must be an object")
        contact: Dict[str, Any] = {"name": _single_line(raw.get("name"), f"{pointer}/name", required=True)}
        details = raw.get("details")
        if details is not None:
            if not isinstance(details, Mapping):
                raise _invalid(CODE_ENVIRONMENT_INVALID, f"{pointer}/details", "must be an object")
            contact["details"] = dict(details)
        contacts.append(contact)
    return contacts


def parse_environment_request(raw: bytes) -> EnvironmentInput:
    """Read and check an environment body (``POST …/environments`` or ``PUT …/environments/{id}``).

    The Pact Broker's ``EnvironmentSchema``: ``name`` is required and has no whitespace,
    ``displayName`` and the contacts' names are single lines. ``production`` defaults to ``false``
    (``pact-broker create-environment`` always sends it). Fields the broker returns but does not
    take (``uuid``, ``createdAt``, ``_links`` …) are ignored, so a client may send back what it read.

    Args:
        raw: The body.

    Returns:
        The checked environment.

    Raises:
        PactPublicationError: ``pact-environment-invalid`` with the JSON Pointer of the problem.
    """
    body = _decode(raw, CODE_ENVIRONMENT_INVALID)
    if not isinstance(body, Mapping):
        raise _invalid(CODE_ENVIRONMENT_INVALID, "", "the request body must be a JSON object")
    name = _single_line(body.get("name"), "/name", required=True)
    assert name is not None
    if _NAME_FORBIDDEN.search(name):
        raise _invalid(CODE_ENVIRONMENT_INVALID, "/name", "cannot contain spaces")
    display_name = _single_line(body.get("displayName"), "/displayName", required=False)
    return EnvironmentInput(
        name=name,
        display_name=display_name or name,
        production=_flag(body, "production"),
        contract_required=_flag(body, "contractRequired"),
        contacts=_contacts(body.get("contacts")),
    )


class EnvironmentRecord(BaseModel):
    """A stored environment.

    Attributes:
        id: Row id — the ``uuid`` the Pact Broker's API names it by.
        name: The name tooling uses.
        display_name: The name people read.
        production: Whether this is a production environment.
        contract_required: Apiome: whether can-i-deploy here requires a contract.
        contacts: Who to contact about it.
        created_at: When it was created.
        updated_at: When it was last replaced.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    display_name: str
    production: bool = False
    contract_required: bool = False
    contacts: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def environment_from_row(row: Mapping[str, Any], prefix: str = "") -> EnvironmentRecord:
    """Adapt an environment row — or the ``prefix``-ed environment columns of a joined row.

    Args:
        row: The row.
        prefix: The column prefix (``"environment_"`` in a deployment read).

    Returns:
        The record.
    """
    contacts = row.get(f"{prefix}contacts")
    if isinstance(contacts, str):
        contacts = json.loads(contacts)
    return EnvironmentRecord(
        id=str(row.get(f"{prefix}id")),
        name=str(row.get(f"{prefix}name") or ""),
        display_name=str(row.get(f"{prefix}display_name") or row.get(f"{prefix}name") or ""),
        production=bool(row.get(f"{prefix}production")),
        contract_required=bool(row.get(f"{prefix}contract_required")),
        contacts=list(contacts or []),
        created_at=_iso(row.get(f"{prefix}created_at")),
        updated_at=_iso(row.get(f"{prefix}updated_at")),
    )


# ---------------------------------------------------------------------------------------------
# Deployments and releases
# ---------------------------------------------------------------------------------------------


def parse_application_instance(raw: bytes) -> Optional[str]:
    """Read the application instance of a ``record-deployment`` body.

    ``pact-broker record-deployment`` sends ``{"applicationInstance": "eu-1", "target": "eu-1"}``
    (``target`` is the deprecated name, read when ``applicationInstance`` is absent) or ``{}``. A
    blank instance is the environment's only, unnamed instance, as the broker treats it.

    Args:
        raw: The body (may be empty).

    Returns:
        The instance, or ``None`` for the unnamed one.

    Raises:
        PactPublicationError: ``pact-deployment-invalid`` for a body that is not an object, or an
            instance that is not a one-line string of at most 255 characters.
    """
    body = _decode(raw, CODE_DEPLOYMENT_INVALID)
    if body is None:
        return None
    if not isinstance(body, Mapping):
        raise _invalid(CODE_DEPLOYMENT_INVALID, "", "the request body must be a JSON object")
    key = "applicationInstance" if body.get("applicationInstance") is not None else "target"
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(CODE_DEPLOYMENT_INVALID, f"/{key}", "must be a string")
    text = value.strip()
    if _CONTROL.search(text) or len(text) > MAX_LABEL_LENGTH:
        raise _invalid(
            CODE_DEPLOYMENT_INVALID, f"/{key}", f"must be a single line of at most {MAX_LABEL_LENGTH} characters"
        )
    return text or None


def parse_flag_patch(raw: bytes, field: str) -> bool:
    """Read the merge patch ``record-undeployment`` and ``record-support-ended`` send.

    ``{"currentlyDeployed": false}`` ends a deployment and ``{"currentlySupported": false}`` ends
    support. Setting the flag back to ``true`` is refused, as the broker refuses it: a deployment is
    recorded again, not revived. A patch without the field changes nothing.

    Args:
        raw: The body (``application/merge-patch+json``, or any JSON).
        field: ``currentlyDeployed`` or ``currentlySupported``.

    Returns:
        ``True`` when the patch ends the deployment or support, ``False`` when it changes nothing.

    Raises:
        PactPublicationError: ``pact-deployment-invalid`` for a body that is not an object, or a
            value of the field that is not ``false``.
    """
    body = _decode(raw, CODE_DEPLOYMENT_INVALID)
    if body is None:
        return False
    if not isinstance(body, Mapping):
        raise _invalid(CODE_DEPLOYMENT_INVALID, "", "the request body must be a JSON object")
    if field not in body or body[field] is None:
        return False
    if body[field] is True:
        raise _invalid(
            CODE_DEPLOYMENT_INVALID,
            f"/{field}",
            f"cannot be set to true; record the {'deployment' if field == 'currentlyDeployed' else 'release'} again",
        )
    if body[field] is not False:
        raise _invalid(CODE_DEPLOYMENT_INVALID, f"/{field}", "must be false")
    return True


class DeployedVersionRecord(BaseModel):
    """A stored deployment.

    Attributes:
        id: Row id — the ``uuid`` the Pact Broker's API names it by.
        pacticipant_slug: The deployed pacticipant's handle.
        pacticipant_name: Its display name.
        version_number: The deployed version.
        environment: The environment deployed to.
        application_instance: The instance deployed to; ``None`` for the unnamed one.
        currently_deployed: Whether it is still deployed.
        undeployed_at: When it stopped being deployed.
        created_at: When the deployment was recorded.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    environment: EnvironmentRecord
    application_instance: Optional[str] = None
    currently_deployed: bool = True
    undeployed_at: Optional[str] = None
    created_at: Optional[str] = None


class ReleasedVersionRecord(BaseModel):
    """A stored release.

    Attributes:
        id: Row id — the ``uuid`` the Pact Broker's API names it by.
        pacticipant_slug: The released pacticipant's handle.
        pacticipant_name: Its display name.
        version_number: The released version.
        environment: The environment released to.
        currently_supported: Whether it is still supported.
        support_ended_at: When support ended.
        created_at: When the release was first recorded.
        updated_at: When it was last recorded again or its support ended.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    environment: EnvironmentRecord
    currently_supported: bool = True
    support_ended_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def deployed_version_from_row(row: Mapping[str, Any]) -> DeployedVersionRecord:
    """Adapt a deployment read (the row, its pacticipant, version and ``environment_`` columns)."""
    return DeployedVersionRecord(
        id=str(row.get("id")),
        pacticipant_slug=str(row.get("pacticipant_slug") or ""),
        pacticipant_name=str(row.get("pacticipant_name") or ""),
        version_number=str(row.get("version_number") or ""),
        environment=environment_from_row(row, "environment_"),
        application_instance=row.get("application_instance"),
        currently_deployed=bool(row.get("currently_deployed")),
        undeployed_at=_iso(row.get("undeployed_at")),
        created_at=_iso(row.get("created_at")),
    )


def released_version_from_row(row: Mapping[str, Any]) -> ReleasedVersionRecord:
    """Adapt a release read (the row, its pacticipant, version and ``environment_`` columns)."""
    return ReleasedVersionRecord(
        id=str(row.get("id")),
        pacticipant_slug=str(row.get("pacticipant_slug") or ""),
        pacticipant_name=str(row.get("pacticipant_name") or ""),
        version_number=str(row.get("version_number") or ""),
        environment=environment_from_row(row, "environment_"),
        currently_supported=bool(row.get("currently_supported")),
        support_ended_at=_iso(row.get("support_ended_at")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )
