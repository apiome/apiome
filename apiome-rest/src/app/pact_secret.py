"""Workspace secrets for webhooks and verification targets — PFX-6.5 (#6957).

A workspace keeps a named secret (a CI token, an API key, a signing secret) **once**, in the
credential vault, and everything that needs it *refers* to it by name:

* a contract webhook writes ``${user.<name>}`` in its URL path or query, a header, the body, the
  basic-auth credentials, the GitHub token or the signing secret — the PactFlow syntax, so a
  webhook copied from PactFlow keeps working once its secrets are re-entered;
* a verification target sets ``auth.kind`` to ``secret`` and ``auth.ref`` to the name.

The reference is resolved only when the request is sent, so rotating a token is one change and no
webhook or target holds a copy. This module is the pure half — no database, no network:

* the **name** rule (:func:`validate_secret_name`) and the **reference** syntax
  (:func:`secret_reference`, :func:`references_in`, :func:`malformed_references`);
* **reading a request body** (:func:`parse_secret_create`, :func:`parse_secret_update`) without ever
  repeating the value in an error;
* :class:`SecretRecord`, a secret as everyone reads it — which has no field the value could be in.

**Every refusal has a stable code** (:data:`CODE_SECRET_INVALID` …) on :class:`PactSecretError`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_SECRET_IN_USE",
    "CODE_SECRET_INVALID",
    "CODE_SECRET_LIMIT",
    "CODE_SECRET_NAME_TAKEN",
    "CODE_SECRET_NOT_FOUND",
    "CODE_SECRET_VAULT_UNAVAILABLE",
    "MAX_SECRETS_PER_TENANT",
    "MAX_SECRET_VALUE",
    "NAME_PATTERN",
    "REFERENCE_BODY",
    "REFERENCE_PATTERN",
    "PactSecretError",
    "SecretCreate",
    "SecretList",
    "SecretRecord",
    "SecretUpdate",
    "SecretUsage",
    "SecretUser",
    "STATUS_BY_CODE",
    "is_reference",
    "malformed_references",
    "parse_secret_create",
    "parse_secret_update",
    "references_in",
    "secret_reference",
    "validate_secret_name",
]

#: The body is malformed (HTTP 422, with a pointer).
CODE_SECRET_INVALID = "pact-secret-invalid"
#: No such secret in the workspace (HTTP 404).
CODE_SECRET_NOT_FOUND = "pact-secret-not-found"
#: The workspace already has a secret of that name (HTTP 409).
CODE_SECRET_NAME_TAKEN = "pact-secret-name-taken"
#: A webhook or a verification target still refers to the secret (HTTP 409).
CODE_SECRET_IN_USE = "pact-secret-in-use"
#: The workspace already has :data:`MAX_SECRETS_PER_TENANT` secrets (HTTP 409).
CODE_SECRET_LIMIT = "pact-secret-limit-reached"
#: The server has no key to seal or open a secret with (HTTP 503).
CODE_SECRET_VAULT_UNAVAILABLE = "pact-secret-vault-unavailable"

#: The HTTP status of each refusal.
STATUS_BY_CODE: Dict[str, int] = {
    CODE_SECRET_INVALID: 422,
    CODE_SECRET_NOT_FOUND: 404,
    CODE_SECRET_NAME_TAKEN: 409,
    CODE_SECRET_IN_USE: 409,
    CODE_SECRET_LIMIT: 409,
    CODE_SECRET_VAULT_UNAVAILABLE: 503,
}

#: The most secrets one workspace may keep.
MAX_SECRETS_PER_TENANT = 200
#: The longest value a secret may hold (the longest a webhook secret may be).
MAX_SECRET_VALUE = 4096
_MAX_DESCRIPTION = 1000

#: A secret's name: a letter, then letters, digits and underscores; 64 at most (mirrors V450).
NAME_PATTERN = r"[A-Za-z][A-Za-z0-9_]{0,63}"
_NAME = re.compile(rf"^{NAME_PATTERN}$")
#: The inside of a reference's braces: ``user.<name>`` (the name is not a group).
REFERENCE_BODY = rf"user\.{NAME_PATTERN}"
#: A reference to a secret, as a webhook template writes it; group 1 is the name.
REFERENCE_PATTERN = rf"\$\{{user\.({NAME_PATTERN})\}}"
_REFERENCE = re.compile(REFERENCE_PATTERN)
#: Anything that starts like a reference — to find the ones that are not well formed.
_REFERENCE_LIKE = re.compile(r"\$\{user\.([^}]*)\}?")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class PactSecretError(ValueError):
    """A refusal carrying a stable machine code and, when it is about one field, a pointer.

    The message never contains a secret's value.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        pointer: JSON Pointer into the request body, or ``None``.
    """

    def __init__(self, code: str, message: str, *, pointer: Optional[str] = None) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation; never a value.
            pointer: Where the problem is in the request body.
        """
        super().__init__(message)
        self.code = code
        self.pointer = pointer


def _invalid(pointer: str, message: str) -> PactSecretError:
    """A ``pact-secret-invalid`` refusal locating ``pointer`` in the request body."""
    return PactSecretError(CODE_SECRET_INVALID, f"{pointer or '(request body)'}: {message}", pointer=pointer)


# ---------------------------------------------------------------------------------------------
# Names and references
# ---------------------------------------------------------------------------------------------


def validate_secret_name(value: Any, pointer: str = "/name") -> str:
    """Return a well-formed secret name, or refuse it.

    Args:
        value: The name sent.
        pointer: Where it is in the body.

    Returns:
        The name, unchanged (names are case-sensitive, as references are).

    Raises:
        PactSecretError: ``pact-secret-invalid``.
    """
    if not isinstance(value, str) or not value:
        raise _invalid(pointer, "is required: a letter, then letters, digits and underscores")
    if not _NAME.match(value):
        raise _invalid(pointer, "must be a letter, then up to 63 letters, digits and underscores")
    return value


def secret_reference(name: str) -> str:
    """How a webhook template refers to the secret ``name``.

    Args:
        name: The secret's name.

    Returns:
        ``${user.<name>}``.
    """
    return "${user.%s}" % name


def is_reference(value: Optional[str]) -> bool:
    """Whether ``value`` is exactly one reference and nothing else.

    Args:
        value: A template string.

    Returns:
        True for ``${user.<name>}`` alone.
    """
    return bool(value) and _REFERENCE.fullmatch(value or "") is not None


def _strings(value: Any) -> List[str]:
    """Every string in a JSON value, keys included, in document order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    if isinstance(value, Mapping):
        return [text for key, item in value.items() for text in (str(key), *_strings(item))]
    return []


def references_in(*values: Any) -> List[str]:
    """The secret names referred to in some template values, distinct, in the order they appear.

    Args:
        *values: Strings, or JSON values whose strings (keys included) are searched.

    Returns:
        The names.
    """
    names: List[str] = []
    for value in values:
        for text in _strings(value):
            for name in _REFERENCE.findall(text):
                if name not in names:
                    names.append(name)
    return names


def malformed_references(value: Any) -> List[str]:
    """The ``${user.…}`` spans in a template value that are not a well-formed reference.

    A template that writes ``${user.my-token}`` or forgets the closing brace would otherwise be
    sent as written; it is refused instead.

    Args:
        value: A string or a JSON value.

    Returns:
        The malformed spans as written (they name a secret, never hold one).
    """
    bad: List[str] = []
    for text in _strings(value):
        for match in _REFERENCE_LIKE.finditer(text):
            if not _REFERENCE.fullmatch(match.group(0)):
                bad.append(match.group(0))
    return bad


# ---------------------------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------------------------


class SecretCreate(BaseModel):
    """A checked ``POST …/pact-secrets`` body.

    Attributes:
        name: The name references use.
        description: What it is for.
        value: The secret itself; sealed before it is stored.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: Optional[str] = None
    value: str = Field(repr=False)


class SecretUpdate(BaseModel):
    """A checked ``PUT …/pact-secrets/{id}`` body.

    Attributes:
        name: The name the client sent back, or ``None``; it must be the stored one.
        description: The new description; ``None`` clears it.
        value: A new value (rotation), or ``None`` to keep the stored one.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = Field(default=None, repr=False)


def _object(raw: bytes) -> Mapping[str, Any]:
    """Read a JSON object body.

    Raises:
        PactSecretError: ``pact-secret-invalid`` for anything else. The message never repeats
            the body, which holds a secret.
    """
    try:
        body = json.loads(raw) if raw and raw.strip() else None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid("", "the request body is not JSON") from exc
    if not isinstance(body, Mapping):
        raise _invalid("", "must be a JSON object")
    return body


def _unknown(body: Mapping[str, Any], allowed: tuple) -> None:
    """Refuse a field the body may not carry, naming it (never its value)."""
    for key in body:
        if key not in allowed:
            raise _invalid(f"/{key}", f"is not a field of a secret; send {', '.join(allowed)}")


def _description(value: Any) -> Optional[str]:
    """A trimmed single-line description of at most 1,000 characters, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("/description", "must be a string")
    text = value.strip()
    if _CONTROL.search(text):
        raise _invalid("/description", "must be a single line")
    if len(text) > _MAX_DESCRIPTION:
        raise _invalid("/description", f"must be at most {_MAX_DESCRIPTION} characters")
    return text or None


def _value(value: Any) -> str:
    """A secret value: one line of 1 to 4,096 characters, not itself a reference.

    The message never repeats the value.
    """
    if not isinstance(value, str) or value == "":
        raise _invalid("/value", "is required: the secret itself, as a string")
    if _CONTROL.search(value) or len(value) > MAX_SECRET_VALUE:
        raise _invalid("/value", f"must be a single line of 1 to {MAX_SECRET_VALUE} characters")
    if _REFERENCE_LIKE.search(value):
        raise _invalid("/value", "cannot refer to another secret; send the value itself")
    return value


def parse_secret_create(raw: bytes) -> SecretCreate:
    """Read and check a ``POST …/pact-secrets`` body: ``name``, ``value``, optional ``description``.

    Args:
        raw: The body.

    Returns:
        The checked secret.

    Raises:
        PactSecretError: ``pact-secret-invalid`` with a pointer to the bad field.
    """
    body = _object(raw)
    _unknown(body, ("name", "description", "value"))
    return SecretCreate(
        name=validate_secret_name(body.get("name")),
        description=_description(body.get("description")),
        value=_value(body.get("value")),
    )


def parse_secret_update(raw: bytes) -> SecretUpdate:
    """Read and check a ``PUT …/pact-secrets/{id}`` body: ``description`` and an optional ``value``.

    The name is not changed by it: references use the name, so it never changes. ``name`` may be
    sent only to repeat the stored one (a client may send back what it read); the store refuses
    another.

    Args:
        raw: The body.

    Returns:
        The checked change.

    Raises:
        PactSecretError: ``pact-secret-invalid`` with a pointer to the bad field.
    """
    body = _object(raw)
    _unknown(body, ("name", "description", "value"))
    value = body.get("value")
    name = body.get("name")
    return SecretUpdate(
        name=None if name is None else validate_secret_name(name),
        description=_description(body.get("description")),
        value=None if value is None else _value(value),
    )


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class SecretUser(BaseModel):
    """Something that refers to a secret.

    Attributes:
        kind: ``webhook`` or ``verification_target``.
        id: Its id (a webhook's ``uuid``, a target's id).
        name: How it is shown: the webhook's description or request, the target's slug.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    id: str
    name: str


class SecretUsage(BaseModel):
    """What refers to a secret.

    Attributes:
        webhooks: The contract webhooks whose templates use it.
        targets: The verification targets whose credential it is.
    """

    model_config = ConfigDict(extra="forbid")

    webhooks: List[SecretUser] = Field(default_factory=list)
    targets: List[SecretUser] = Field(default_factory=list)

    def is_empty(self) -> bool:
        """Whether nothing refers to the secret."""
        return not self.webhooks and not self.targets


class SecretRecord(BaseModel):
    """A stored secret as everyone reads it: never its value.

    Attributes:
        id: The secret's id.
        name: The name references use.
        description: What it is for.
        reference: How a webhook template writes it: ``${user.<name>}``.
        used_by: The webhooks and targets that refer to it.
        value_updated_at: When the value was last set (created or rotated).
        created_at: When it was created.
        updated_at: When it was last changed.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: Optional[str] = None
    reference: str
    used_by: SecretUsage = Field(default_factory=SecretUsage)
    value_updated_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SecretList(BaseModel):
    """The workspace's secrets, by name.

    Attributes:
        secrets: Every secret.
        limit: The most a workspace may keep.
    """

    model_config = ConfigDict(extra="forbid")

    secrets: List[SecretRecord] = Field(default_factory=list)
    limit: int = MAX_SECRETS_PER_TENANT
