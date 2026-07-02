"""Canonical fingerprint SPI: stable hash over the normalized model — MFI-3.1 (#3742).

Change detection across every importable format must work *uniformly* (one
fingerprint mechanism for REST, RPC, event, graph, and data-schema artifacts) yet
still respect each format's own notion of identity. This module provides both:

* **A format-agnostic semantic fingerprint** — :func:`canonical_fingerprint`,
  a SHA-256 over a *canonicalized* projection of a
  :class:`~app.canonical_model.CanonicalApi`. Canonicalization sorts the
  identity-keyed collections (reusing :func:`app.normalizer.normalize_ordering`),
  drops everything that is documentation or presentation rather than contract
  (descriptions/titles and the native ``raw`` AST), and serializes with stable
  key ordering and separators. The result is invariant to the source's
  declaration order and to doc-only edits, but flips on any structural change —
  exactly what versioning (MFI-3.4) and diff (MFI-3.2) need.

* **A per-format hook for special hashes** — the :class:`FingerprintHasher` SPI
  and its registry, mirroring the normalizer registry in :mod:`app.normalizer`.
  Some formats define a canonical hash of their own that captures format-specific
  identity better than the structural projection can: Avro's **Parsing Canonical
  Form** (PCF) CRC-64-AVRO / SHA-256, a protobuf ``FileDescriptorSet`` hash, or
  XSD QName canonicalization. A format epic registers a hasher under its format
  key; :func:`fingerprint` then returns *both* the always-present semantic
  fingerprint and, when a hasher is registered, that format-specific hash.

The semantic fingerprint and a format's special hash answer *different*
questions and are intentionally kept side by side (see ``docs/fingerprint_spi.md``):
Avro PCF, for instance, strips defaults, aliases, and ``doc`` so that two schemas
that differ only in those resolve to the *same* PCF — which is correct for Avro
read/write resolution but wrong for "did anything about this artifact change",
which the semantic fingerprint answers.

The module is **pure**: no DB, no network. It takes an in-memory model and
returns hex digests, so it is cheap to call anywhere (import pipeline, version
roll, diff) and trivially deterministic.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field

from .canonical_model import CanonicalApi
from .normalizer import normalize_ordering

__all__ = [
    "FINGERPRINT_ALGORITHM",
    "canonical_payload",
    "canonical_fingerprint",
    "FingerprintResult",
    "fingerprint",
    "FingerprintHasher",
    "register_fingerprint_hasher",
    "get_fingerprint_hasher",
    "available_fingerprint_formats",
]


# Identifier of the format-agnostic algorithm, recorded alongside every digest so
# a stored fingerprint can be re-validated by (and migrated between) algorithm
# versions. Bump the trailing version when the canonicalization rules below change
# in a way that would alter digests for unchanged models.
FINGERPRINT_ALGORITHM = "sha256-canonical-v1"


# Canonical-model keys that are documentation/presentation, not contract: they are
# removed before hashing so a description- or comment-only edit does not flip the
# fingerprint. ``raw`` is the native source AST (comment- and order-laden, kept on
# the model only for round-tripping and per-format lint) and is likewise excluded.
_DESCRIPTIVE_KEYS = frozenset({"description", "title", "raw"})

# Canonical-model keys whose *values* are opaque bags or arbitrary literals: they
# are kept verbatim (semantic) but **not** recursed into, so a user value that
# happens to be a dict with a ``description`` member, or a format-specific
# attribute parked in ``extras``, is never mistaken for a canonical doc field and
# stripped. ``extras``/``bindings`` are format-fidelity bags; ``payload_schema``
# is an inline JSON-Schema body; ``default``/``value``/``enum`` are literal data.
_OPAQUE_KEYS = frozenset(
    {"extras", "bindings", "payload_schema", "default", "value", "enum"}
)


def _scrub(node: Any) -> Any:
    """Return a copy of a dumped-model ``node`` with descriptive keys removed.

    The walk is *structure-aware*: it strips keys named in
    :data:`_DESCRIPTIVE_KEYS` only where they are canonical-model attributes, and
    it treats :data:`_OPAQUE_KEYS` as leaves — their values are carried through
    untouched rather than recursed into — so semantic data that merely *contains*
    a ``description``-named member is preserved.

    Args:
        node: A node of ``CanonicalApi.model_dump()`` output (dict, list, or leaf).

    Returns:
        The scrubbed node. Ordering of list elements is preserved (it is either
        semantically meaningful or already normalized by
        :func:`~app.normalizer.normalize_ordering`); dict key ordering is
        irrelevant because the final serialization sorts keys.
    """
    if isinstance(node, dict):
        scrubbed: Dict[str, Any] = {}
        for key, value in node.items():
            if key in _DESCRIPTIVE_KEYS:
                continue
            scrubbed[key] = value if key in _OPAQUE_KEYS else _scrub(value)
        return scrubbed
    if isinstance(node, list):
        return [_scrub(item) for item in node]
    return node


def canonical_payload(api: CanonicalApi) -> Dict[str, Any]:
    """Return the canonicalized projection of ``api`` that gets hashed.

    The projection is the model with (1) its identity-keyed collections sorted by
    :func:`~app.normalizer.normalize_ordering` and (2) descriptive/presentation
    keys removed by :func:`_scrub`. It is returned (rather than only its digest)
    so callers — and tests — can inspect exactly what the fingerprint is taken
    over, and so MFI-3.2's diff can reuse the same canonical view.

    Args:
        api: The canonical model to project. Not mutated (ordering deep-copies).

    Returns:
        A JSON-serializable dict: the structural contract of the artifact, free of
        documentation and declaration-order noise.
    """
    return _scrub(normalize_ordering(api).model_dump())


def canonical_fingerprint(api: CanonicalApi) -> str:
    """Compute the format-agnostic semantic SHA-256 fingerprint of ``api``.

    Two models with the same contract — regardless of how the source ordered its
    paths/types or what descriptions it carried — hash identically; any structural
    change (a field added/removed/retyped, a constraint changed, a default
    changed, an operation's verb/route changed, …) changes the hash.

    Args:
        api: The canonical model to fingerprint.

    Returns:
        A 64-character lowercase hex SHA-256 digest over the
        :func:`canonical_payload`, serialized with sorted keys and compact
        separators for byte-stable output across runs and machines.
    """
    serialized = json.dumps(
        canonical_payload(api),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ===========================================================================
# Per-format hash hook SPI + registry
# ===========================================================================


class FingerprintHasher(ABC):
    """Service-provider contract for a format-specific artifact hash.

    A format whose ecosystem defines its own canonical hash registers a hasher so
    that, alongside the always-present semantic fingerprint, callers can obtain
    the *format's* notion of identity. The classic example is Avro's Parsing
    Canonical Form (PCF): a hash that intentionally strips defaults, aliases, and
    ``doc`` to capture read/write compatibility rather than textual identity.

    A hasher must be **deterministic and side-effect free**: given the same model
    it returns the same digest, performs no I/O, and derives its hash only from
    the model (typically from ``api.raw`` or a re-rendered canonical form). It
    declares the :attr:`format` key it applies to and a stable :attr:`algorithm`
    label recorded next to the digest.

    Subclasses register via the ``register=True`` flag
    (``class AvroPcfHasher(FingerprintHasher, register=True): ...``) or
    :func:`register_fingerprint_hasher`, and are looked up by ``format`` with
    :func:`get_fingerprint_hasher`.
    """

    #: Source format key this hasher applies to, e.g. ``"avro"`` — matched against
    #: :attr:`app.canonical_model.CanonicalApi.format`.
    format: ClassVar[str] = ""

    #: Stable identifier of the hashing algorithm, recorded on the result, e.g.
    #: ``"avro-parsing-canonical-form-sha256"``.
    algorithm: ClassVar[str] = ""

    def __init_subclass__(cls, *, register: bool = False, **kwargs: Any) -> None:
        """Optionally self-register a concrete subclass in the hasher registry.

        Args:
            register: When ``True``, the subclass is added to the registry under
                its :attr:`format` key as soon as it is defined.
        """
        super().__init_subclass__(**kwargs)
        if register:
            register_fingerprint_hasher(cls)

    @abstractmethod
    def hash(self, api: CanonicalApi) -> str:
        """Return this format's special hash of ``api`` as a hex string.

        Args:
            api: The canonical model whose format equals this hasher's
                :attr:`format`.

        Returns:
            A hex digest under this hasher's :attr:`algorithm`.
        """
        raise NotImplementedError


# Format-key → hasher-class registry. A format epic registers its hasher here so
# :func:`fingerprint` can attach a format-specific hash without this module
# importing every format package.
_HASHER_REGISTRY: Dict[str, type[FingerprintHasher]] = {}


def register_fingerprint_hasher(
    cls: type[FingerprintHasher],
) -> type[FingerprintHasher]:
    """Register a concrete :class:`FingerprintHasher` under its ``format`` key.

    Args:
        cls: A concrete :class:`FingerprintHasher` subclass with a non-empty
            ``format`` and ``algorithm``.

    Returns:
        ``cls`` unchanged, so this can also be used as a class decorator.

    Raises:
        ValueError: If ``cls.format`` or ``cls.algorithm`` is empty, or a
            *different* class is already registered under the same format key
            (re-registering the same class is a no-op, so module re-import is
            safe).
    """
    key = cls.format
    if not key:
        raise ValueError(
            f"{cls.__name__} must set a non-empty `format` to register"
        )
    if not cls.algorithm:
        raise ValueError(
            f"{cls.__name__} must set a non-empty `algorithm` to register"
        )
    existing = _HASHER_REGISTRY.get(key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"fingerprint hasher for format {key!r} already registered to "
            f"{existing.__name__}; cannot re-register to {cls.__name__}"
        )
    _HASHER_REGISTRY[key] = cls
    return cls


def get_fingerprint_hasher(
    format_key: str,
) -> Optional[type[FingerprintHasher]]:
    """Return the hasher class registered for ``format_key``, or ``None``."""
    return _HASHER_REGISTRY.get(format_key)


def available_fingerprint_formats() -> List[str]:
    """Return the sorted format keys that have a registered hasher."""
    return sorted(_HASHER_REGISTRY)


class FingerprintResult(BaseModel):
    """The fingerprints computed for one artifact version.

    The semantic :attr:`fingerprint` is always present and is what change
    detection and diff key on. :attr:`format_hash` is populated only when a
    :class:`FingerprintHasher` is registered for the artifact's format, and
    carries that format's special hash (e.g. Avro PCF) for compatibility-oriented
    comparisons. Persisted as JSONB alongside the version row by MFI-3.4.
    """

    fingerprint: str = Field(
        description="Format-agnostic semantic SHA-256 over the canonical model.",
    )
    algorithm: str = Field(
        default=FINGERPRINT_ALGORITHM,
        description="Identifier of the semantic-fingerprint algorithm.",
    )
    format: str = Field(
        description="The artifact's source format key (``CanonicalApi.format``).",
    )
    format_hash: Optional[str] = Field(
        default=None,
        description="Format-specific special hash, when a hasher is registered "
        "for ``format`` (e.g. Avro Parsing Canonical Form); otherwise ``None``.",
    )
    format_algorithm: Optional[str] = Field(
        default=None,
        description="Algorithm label of ``format_hash`` (e.g. "
        "``avro-parsing-canonical-form-sha256``); ``None`` when no hasher applies.",
    )


def fingerprint(api: CanonicalApi) -> FingerprintResult:
    """Fingerprint ``api`` with the semantic hash plus any per-format hash.

    Always computes the format-agnostic :func:`canonical_fingerprint`. If a
    :class:`FingerprintHasher` is registered for ``api.format``, also computes and
    attaches that format's special hash and its algorithm label.

    Args:
        api: The canonical model to fingerprint.

    Returns:
        A :class:`FingerprintResult` carrying the semantic fingerprint and,
        when applicable, the format-specific hash.
    """
    result = FingerprintResult(
        fingerprint=canonical_fingerprint(api),
        algorithm=FINGERPRINT_ALGORITHM,
        format=api.format,
    )
    hasher_cls = get_fingerprint_hasher(api.format)
    if hasher_cls is not None:
        hasher = hasher_cls()
        result.format_hash = hasher.hash(api)
        result.format_algorithm = hasher_cls.algorithm
    return result
