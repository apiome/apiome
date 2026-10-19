"""Consumer bindings: how usage traffic is attributed to a consumer — RDG-1.8 (#5765).

Traffic carries headers, API keys, JWT claims and user agents, not the consumer handles the CTG-4.1
registry knows. A **binding** is the bridge: "a call whose ``x-client-id`` header has this value is
``billing-service``". This module is the pure half — what a binding is, how a bound value is hashed,
and how a usage event is matched to one. :mod:`app.consumer_binding_store` reads and writes them.

**A bound value is never stored or returned.** For a ``header``, ``api_key`` or ``jwt_claim``
binding the caller sends the value once, on create. :func:`hash_bound_value` turns it into
HMAC-SHA256 under a **tenant-scoped key** before anything touches the database, and only the hash
is kept (apiome-db V292). No response carries the value, nor the hash: even a hash of a short
header value is an offline guessing oracle. A ``user_agent`` binding has no value; its ``name`` is
a glob (``billing-service/*``) matched against the scrubbed user agent.

**The tenant key comes from the existing envelope key map.** It is derived with HKDF-SHA256 from a
master key of ``APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS`` (the map ``setup.sh`` generates for
every install), with the tenant id as the HKDF ``info``. Two tenants hashing the same value get
unrelated hashes, and the master key itself is never used directly. A binding records which
master-key version it was hashed under, so rotating the active version does not break existing
bindings.

**The edge sends the same hash.** A usage event's ``consumer_hint`` is ``{kind, hmac}``
(:class:`app.usage_events.ConsumerHint`): the source hashes the value under the same tenant key
(:func:`consumer_hint_hmac`) and the ingest pipeline compares hashes. The raw value never travels.

**Matching is deterministic.** :class:`ConsumerMatcher` tries the event's hint first (an exact
identity), then the user-agent globs, most specific first. A call nothing matches keeps no binding,
and readers report it under the reserved ``anonymous`` consumer — it is counted, never dropped.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import re
from dataclasses import dataclass
from datetime import datetime
from fnmatch import translate
from typing import Any, Dict, List, Literal, Optional, Pattern, Sequence, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .consumer_contract import ANONYMOUS_CONSUMER_SLUG

__all__ = [
    "ANONYMOUS_CONSUMER_SLUG",
    "BINDING_KINDS",
    "CODE_BINDING_EXISTS",
    "CODE_BINDING_INVALID",
    "CODE_BINDING_KEY_UNAVAILABLE",
    "CODE_BINDING_LIMIT",
    "CODE_BINDING_NOT_FOUND",
    "KIND_API_KEY",
    "KIND_HEADER",
    "KIND_JWT_CLAIM",
    "KIND_USER_AGENT",
    "MAX_BINDINGS_PER_CONSUMER",
    "MAX_VALUE_LENGTH",
    "BindingError",
    "BindingInput",
    "BindingRecord",
    "ConsumerMatcher",
    "LiveBinding",
    "active_key_version",
    "binding_record_from_row",
    "consumer_hint_hmac",
    "derive_tenant_key",
    "hash_bound_value",
    "normalize_binding",
]

KIND_HEADER = "header"
KIND_API_KEY = "api_key"
KIND_JWT_CLAIM = "jwt_claim"
KIND_USER_AGENT = "user_agent"

#: Every binding kind, in the order V292's CHECK lists them.
BINDING_KINDS = (KIND_HEADER, KIND_API_KEY, KIND_JWT_CLAIM, KIND_USER_AGENT)

#: The kinds whose value is hashed (every kind but the user-agent glob).
HASHED_KINDS = (KIND_HEADER, KIND_API_KEY, KIND_JWT_CLAIM)

#: The longest bound value accepted on create (a JWT claim or a long API key fits comfortably).
MAX_VALUE_LENGTH = 4096

#: The longest name or glob V292 stores.
MAX_NAME_LENGTH = 256

#: A user-agent glob must name at least this many literal characters, so ``*`` or ``?*`` cannot
#: swallow every call (and every share) a project receives.
MIN_GLOB_LITERALS = 3

#: Live bindings one consumer may hold. Each is a matcher entry on every batch.
MAX_BINDINGS_PER_CONSUMER = 50

CODE_BINDING_EXISTS = "consumer-binding-exists"
CODE_BINDING_INVALID = "consumer-binding-invalid"
CODE_BINDING_KEY_UNAVAILABLE = "consumer-binding-key-unavailable"
CODE_BINDING_LIMIT = "consumer-binding-limit"
CODE_BINDING_NOT_FOUND = "consumer-binding-not-found"

#: HKDF salt: names the purpose, so a key derived here never equals one derived for anything else.
_HKDF_SALT = b"apiome.usage.consumer-binding.v1"

#: An HTTP header name (RFC 9110 ``token``).
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}$")
#: A JWT claim name: printable, no whitespace.
_CLAIM_NAME = re.compile(r"^[!-~]{1,256}$")
#: A user-agent glob: printable ASCII and spaces.
_GLOB = re.compile(r"^[ -~]{1,256}$")
_GLOB_WILDCARDS = re.compile(r"[*?\[\]]")


class BindingError(ValueError):
    """A binding request refused, with the stable code a client branches on.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        status: The HTTP status that matches the kind of refusal.
    """

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        """Build the refusal.

        Args:
            code: The stable code.
            message: What was wrong. Never contains a bound value.
            status: The HTTP status.
        """
        super().__init__(message)
        self.code = code
        self.status = status

    def detail(self) -> Dict[str, str]:
        """The ``{code, message}`` body a route returns."""
        return {"code": self.code, "message": str(self)}


# ---------------------------------------------------------------------------------------------
# Keys and hashes
# ---------------------------------------------------------------------------------------------


def derive_tenant_key(master_key: bytes, tenant_id: str) -> bytes:
    """Derive a tenant's binding key from one envelope master key.

    Args:
        master_key: A 32-byte master key from the envelope key map.
        tenant_id: The tenant the key is for (its id is the HKDF ``info``).

    Returns:
        A 32-byte HMAC key unique to the tenant.
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=f"tenant:{tenant_id.lower()}".encode("utf-8"),
    ).derive(master_key)


def hash_bound_value(tenant_key: bytes, value: str) -> str:
    """HMAC-SHA256 of a bound value under a tenant key.

    Args:
        tenant_key: The tenant's derived key (:func:`derive_tenant_key`).
        value: The raw value, exactly as it appears in traffic.

    Returns:
        64 lower-case hex characters — the form V292 and :class:`app.usage_events.ConsumerHint`
        both require.
    """
    return _hmac.new(tenant_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _master_keys() -> Tuple[Dict[int, bytes], Optional[int]]:
    """The configured envelope master keys and the active version.

    Returns:
        ``({version: key}, active version)``; ``({}, None)`` when nothing is configured.

    Raises:
        BindingError: 503 ``consumer-binding-key-unavailable`` when the key map is malformed.
    """
    from .envelope_crypto import EnvelopeEncryptionError
    from .linked_account_token_crypto import master_key_map

    try:
        return master_key_map()
    except EnvelopeEncryptionError as exc:
        raise BindingError(CODE_BINDING_KEY_UNAVAILABLE, str(exc), status=503) from exc


def active_key_version() -> int:
    """The master-key version new hashes are made under.

    Registering a suggested consumer (CDG-3.5) stores the HMAC the edge already sent, which was made
    under the current tenant key, so it records this version.

    Returns:
        The active version.

    Raises:
        BindingError: 503 ``consumer-binding-key-unavailable`` when no master key is configured.
    """
    keys, active = _master_keys()
    if not keys:
        raise BindingError(
            CODE_BINDING_KEY_UNAVAILABLE,
            "consumer bindings need APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS to be configured",
            status=503,
        )
    return active if active is not None else max(keys)


def consumer_hint_hmac(tenant_id: str, value: str, *, key_version: Optional[int] = None) -> Tuple[str, int]:
    """Hash a value the way a binding stores it — what a source puts in ``consumer_hint.hmac``.

    Sources that run inside Apiome (the OTLP receiver, the mock and agent runtimes) see the raw
    header and call this; the raw value then goes no further.

    Args:
        tenant_id: The tenant.
        value: The raw header, API-key or claim value.
        key_version: The master-key version to hash under; the active one when omitted.

    Returns:
        ``(hex HMAC, key version used)``.

    Raises:
        BindingError: 503 ``consumer-binding-key-unavailable`` when no master key is configured
            (or the requested version is not).
    """
    keys, active = _master_keys()
    if not keys:
        raise BindingError(
            CODE_BINDING_KEY_UNAVAILABLE,
            "consumer bindings need APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS to be configured",
            status=503,
        )
    version = key_version if key_version is not None else (active if active is not None else max(keys))
    if version not in keys:
        raise BindingError(
            CODE_BINDING_KEY_UNAVAILABLE, f"master key version {version} is not configured", status=503
        )
    return hash_bound_value(derive_tenant_key(keys[version], tenant_id), value), version


# ---------------------------------------------------------------------------------------------
# Input and output shapes
# ---------------------------------------------------------------------------------------------


class BindingInput(BaseModel):
    """A binding to create.

    Attributes:
        kind: ``header``, ``api_key``, ``jwt_claim`` or ``user_agent``.
        name: The header name, the API-key header name, the JWT claim name, or the user-agent glob.
        value: The value to recognise (not for ``user_agent``). Accepted once, hashed, and never
            stored or returned.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["header", "api_key", "jwt_claim", "user_agent"] = Field(
        description="What identifies the consumer in traffic."
    )
    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_LENGTH,
        description=(
            "The header name (`x-client-id`), the header carrying the API key (`x-api-key`), the "
            "JWT claim (`azp`), or for `user_agent` a glob such as `billing-service/*`."
        ),
    )
    value: Optional[SecretStr] = Field(
        default=None,
        description=(
            "The value to recognise. Required for `header`, `api_key` and `jwt_claim`; refused for "
            "`user_agent`. Hashed before it is stored and never returned."
        ),
    )

    @model_validator(mode="after")
    def _value_matches_kind(self) -> "BindingInput":
        if self.kind == KIND_USER_AGENT and self.value is not None:
            raise ValueError("a user_agent binding takes no value; its name is the glob")
        if self.kind != KIND_USER_AGENT:
            if self.value is None or not self.value.get_secret_value():
                raise ValueError(f"a {self.kind} binding needs the value to recognise")
            if len(self.value.get_secret_value()) > MAX_VALUE_LENGTH:
                raise ValueError(f"the value may be at most {MAX_VALUE_LENGTH} characters")
        return self


def normalize_binding(kind: str, name: str) -> str:
    """Validate and normalize a binding's name for its kind.

    Header names are case-insensitive, so they are stored in lower case; a claim name and a glob
    are kept as written.

    Args:
        kind: The binding kind.
        name: The name or glob as sent.

    Returns:
        The stored form.

    Raises:
        BindingError: 400 ``consumer-binding-invalid`` for a malformed name, or a glob too broad to
            identify one consumer.
    """
    candidate = name.strip()
    if kind in (KIND_HEADER, KIND_API_KEY):
        if not _HEADER_NAME.match(candidate):
            raise BindingError(CODE_BINDING_INVALID, "the header name is not a valid HTTP header name")
        return candidate.lower()
    if kind == KIND_JWT_CLAIM:
        if not _CLAIM_NAME.match(candidate):
            raise BindingError(CODE_BINDING_INVALID, "a JWT claim name is printable and has no whitespace")
        return candidate
    if kind == KIND_USER_AGENT:
        if not _GLOB.match(candidate):
            raise BindingError(CODE_BINDING_INVALID, "a user-agent glob is printable ASCII, at most 256 characters")
        if len(_GLOB_WILDCARDS.sub("", candidate)) < MIN_GLOB_LITERALS:
            raise BindingError(
                CODE_BINDING_INVALID,
                f"a user-agent glob must name at least {MIN_GLOB_LITERALS} literal characters, so it "
                f"cannot match every caller",
            )
        return candidate
    raise BindingError(CODE_BINDING_INVALID, f"unknown binding kind {kind!r}")


class BindingRecord(BaseModel):
    """A stored binding as every response shows it — never with its value or its hash.

    Attributes:
        id: Row id.
        consumer_id: The consumer it attributes traffic to.
        kind: The binding kind.
        name: The header or claim name, or the user-agent glob.
        hashed: Whether a value is bound (every kind but ``user_agent``).
        key_version: The master-key version the value was hashed under.
        last_matched_at: When traffic last matched it.
        created_at: When it was created.
        deleted_at: When it was deleted (it stops matching; history keeps it).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    consumer_id: str
    kind: str
    name: str
    hashed: bool = Field(description="True when a value is bound; the value itself is never returned.")
    key_version: Optional[int] = None
    last_matched_at: Optional[str] = None
    created_at: Optional[str] = None
    deleted_at: Optional[str] = None


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def binding_record_from_row(row: Dict[str, Any]) -> BindingRecord:
    """Adapt a ``usage_consumer_binding`` row. The ``value_hmac`` column is deliberately ignored.

    Args:
        row: The row.

    Returns:
        The record.
    """
    return BindingRecord(
        id=str(row["id"]),
        consumer_id=str(row["consumer_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        hashed=row.get("kind") != KIND_USER_AGENT,
        key_version=row.get("key_version"),
        last_matched_at=_iso(row.get("last_matched_at")),
        created_at=_iso(row.get("created_at")),
        deleted_at=_iso(row.get("deleted_at")),
    )


# ---------------------------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveBinding:
    """One live binding as the ingest matcher needs it.

    Attributes:
        id: The binding id (what ``usage_hourly.consumer_binding_id`` records).
        consumer_id: The consumer.
        kind: The binding kind.
        name: The name or glob.
        value_hmac: The stored hash (``None`` for a user-agent glob).
        created_at: Creation time; the older binding wins a tie.
    """

    id: str
    consumer_id: str
    kind: str
    name: str
    value_hmac: Optional[str]
    created_at: Optional[datetime] = None


def _age_key(binding: LiveBinding) -> Tuple[str, str]:
    """Order bindings oldest first, then by id, so ties always break the same way."""
    return (binding.created_at.isoformat() if binding.created_at else "", binding.id)


class ConsumerMatcher:
    """Attribute a call to one of a project's live bindings.

    Order: the call's ``consumer_hint`` against the hashed bindings of the same kind (the oldest
    binding wins if two carry the same hash under different names), then the scrubbed user agent
    against the globs — most literal characters first, then oldest. Globs match case-insensitively.
    """

    def __init__(self, bindings: Sequence[LiveBinding]) -> None:
        """Index the bindings.

        Args:
            bindings: The project's live bindings.
        """
        self._by_hash: Dict[Tuple[str, str], LiveBinding] = {}
        for binding in sorted(bindings, key=_age_key):
            if binding.kind in HASHED_KINDS and binding.value_hmac:
                self._by_hash.setdefault((binding.kind, binding.value_hmac), binding)
        globs = [b for b in bindings if b.kind == KIND_USER_AGENT]
        globs.sort(key=lambda b: (-len(_GLOB_WILDCARDS.sub("", b.name)), *_age_key(b)))
        self._globs: List[Tuple[Pattern[str], LiveBinding]] = [
            (re.compile(translate(b.name.lower())), b) for b in globs
        ]

    def __bool__(self) -> bool:
        """``False`` when the project has no live binding (every call is anonymous)."""
        return bool(self._by_hash or self._globs)

    def match(
        self, hint_kind: Optional[str], hint_hmac: Optional[str], user_agent: Optional[str]
    ) -> Optional[LiveBinding]:
        """Find the binding a call belongs to.

        Args:
            hint_kind: The event's ``consumer_hint.kind``, if any.
            hint_hmac: The event's ``consumer_hint.hmac``, if any.
            user_agent: The event's scrubbed user agent, if any.

        Returns:
            The binding, or ``None`` — the call is anonymous.
        """
        if hint_kind and hint_hmac:
            found = self._by_hash.get((hint_kind, hint_hmac))
            if found is not None:
                return found
        if user_agent:
            lowered = user_agent.lower()
            for pattern, binding in self._globs:
                if pattern.match(lowered):
                    return binding
        return None
