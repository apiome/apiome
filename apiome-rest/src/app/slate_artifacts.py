"""Content-addressed, signed Slate build artifacts — APX-3.1 (private-suite#2456).

Acceptance criterion 1 is "every build has content/source/config digests and an immutable
release ID". This module is the part that makes the digests *mean* something.

Three digests, because they answer three different questions:

* ``content`` — what bytes will be served. This is the artifact's identity: two releases
  carrying the same content digest serve identical bytes, which is what lets promotion
  route to an existing artifact instead of rebuilding one (criterion 3).
* ``source`` — what inputs produced them (catalog revision, guides, changelog).
* ``config`` — what build configuration was applied (theme, navigation, generator options).

Keeping them separate is what distinguishes "the same documentation rendered by a newer
generator" from "different documentation". Collapsing them into one digest would make an
unchanged rebuild indistinguishable from a content change, and a rebuild after a theme
tweak indistinguishable from a rewrite.

**Canonicalization.** Every digest is computed over a canonical serialization: mappings are
serialized with sorted keys and no insignificant whitespace, and the content digest is a
Merkle-style fold over ``sorted(path)`` rather than over concatenated bytes. Digesting a
directory in filesystem order would make the digest depend on the order the walker happened
to yield, so an identical rebuild on a different machine would produce a different identity
and every promotion would look like new bytes.

**Signing.** A detached HMAC-SHA256 over the three digests plus the key id. The signature is
verified before an artifact may be routed, so bytes swapped in the object store after the
build cannot silently reach production. Verification uses a constant-time comparison — a
signature check that leaks timing is a signature check an attacker can grind against.

This module is deliberately pure: it does no I/O and knows nothing about the database, so
every rule above is testable without a build worker or a Postgres instance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = [
    "DIGEST_PATTERN",
    "ArtifactDigests",
    "SlateArtifactError",
    "build_manifest",
    "canonical_digest",
    "compute_config_digest",
    "compute_content_digest",
    "compute_source_digest",
    "is_valid_digest",
    "sign_digests",
    "verify_signature",
]

# The wire and storage form of every digest. The database enforces the same shape with a
# CHECK constraint, so a malformed digest cannot be persisted even if this layer is bypassed.
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

# Domain separation tags. Hashing a config mapping and a source mapping that happen to be
# equal must not produce the same digest: without a tag, an attacker who controls one input
# could engineer a collision with the other and make a config change look like no change.
_CONTENT_TAG = b"apiome.slate.artifact.content.v1"
_SOURCE_TAG = b"apiome.slate.artifact.source.v1"
_CONFIG_TAG = b"apiome.slate.artifact.config.v1"
_SIGNATURE_TAG = b"apiome.slate.artifact.signature.v1"


class SlateArtifactError(Exception):
    """A digest or signature was malformed, or signing was attempted without a key.

    Carries a machine-readable ``code`` so the REST layer can map it to a precise
    status without string-matching the message.

    Codes: ``malformed_digest``, ``missing_signing_key``, ``empty_content``.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ArtifactDigests:
    """The three digests every build must produce.

    Frozen because these are an identity, not a working value: an artifact whose digests
    could be reassigned after construction would defeat the point of content addressing.
    """

    content: str
    source: str
    config: str

    def __post_init__(self) -> None:
        """Reject a malformed digest at construction rather than at persistence."""
        for name in ("content", "source", "config"):
            value = getattr(self, name)
            if not is_valid_digest(value):
                raise SlateArtifactError(
                    "malformed_digest",
                    f"{name} digest must match sha256:<64 hex chars>, got {value!r}",
                )

    def as_dict(self) -> Dict[str, str]:
        """Return the digests as a plain mapping for wire and storage use.

        Returns:
            A dict with ``content``, ``source`` and ``config`` keys.
        """
        return {"content": self.content, "source": self.source, "config": self.config}


def is_valid_digest(value: Any) -> bool:
    """Report whether a value is a well-formed ``sha256:``-prefixed digest.

    Args:
        value: The candidate digest.

    Returns:
        True when the value is a string matching :data:`DIGEST_PATTERN`.
    """
    return isinstance(value, str) and bool(DIGEST_PATTERN.match(value))


def _canonical_bytes(payload: Any) -> bytes:
    """Serialize a payload to canonical, stable bytes.

    Sorted keys and compact separators, so two structurally equal payloads always produce
    identical bytes regardless of the order their keys were inserted.

    Args:
        payload: Any JSON-serializable value.

    Returns:
        UTF-8 encoded canonical JSON.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def canonical_digest(payload: Any, *, tag: bytes) -> str:
    """Digest an arbitrary payload under a domain-separation tag.

    Args:
        payload: Any JSON-serializable value.
        tag: Domain-separation tag distinguishing this digest's purpose from others.

    Returns:
        The digest in ``sha256:<hex>`` form.
    """
    digest = hashlib.sha256()
    digest.update(tag)
    digest.update(b"\x00")
    digest.update(_canonical_bytes(payload))
    return f"sha256:{digest.hexdigest()}"


def compute_content_digest(files: Mapping[str, bytes]) -> str:
    """Digest the rendered site bytes as a Merkle-style fold over sorted paths.

    Each entry contributes ``len(path) | path | sha256(bytes)``, folded in sorted path
    order. Length-prefixing the path is what stops ``{"a/b": x, "c": y}`` from digesting
    identically to ``{"a": ..., "b/c": ...}`` — without it, path boundaries are ambiguous
    in the hash input and two different site layouts could share an identity.

    Args:
        files: Mapping of site-relative path to rendered bytes.

    Returns:
        The content digest in ``sha256:<hex>`` form.

    Raises:
        SlateArtifactError: When ``files`` is empty. An artifact with no pages is not a
            site, and giving it a digest would make "nothing was built" routable.
    """
    if not files:
        raise SlateArtifactError(
            "empty_content", "A Slate artifact must contain at least one rendered file."
        )

    digest = hashlib.sha256()
    digest.update(_CONTENT_TAG)
    digest.update(b"\x00")
    for path in sorted(files):
        encoded_path = path.encode("utf-8")
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(hashlib.sha256(files[path]).digest())
    return f"sha256:{digest.hexdigest()}"


def compute_source_digest(inputs: Mapping[str, Any]) -> str:
    """Digest the build's source inputs.

    Args:
        inputs: Source identity — catalog revision id, guide revisions, changelog
            revision, and any other content the build consumed.

    Returns:
        The source digest in ``sha256:<hex>`` form.
    """
    return canonical_digest(dict(inputs), tag=_SOURCE_TAG)


def compute_config_digest(config: Mapping[str, Any]) -> str:
    """Digest the build configuration.

    Args:
        config: Theme, navigation, generator options and their versions.

    Returns:
        The config digest in ``sha256:<hex>`` form.
    """
    return canonical_digest(dict(config), tag=_CONFIG_TAG)


def _signing_payload(digests: ArtifactDigests, key_id: str) -> bytes:
    """Build the exact bytes a signature covers.

    The key id is inside the signed payload, not merely stored beside it. Otherwise an
    attacker could keep a valid signature and relabel which key produced it, defeating the
    point of recording the key at all.

    Args:
        digests: The three artifact digests.
        key_id: Identifier of the signing key.

    Returns:
        Canonical bytes to be signed or verified.
    """
    return _SIGNATURE_TAG + b"\x00" + _canonical_bytes(
        {"keyId": key_id, **digests.as_dict()}
    )


def sign_digests(digests: ArtifactDigests, *, key: str, key_id: str) -> str:
    """Produce a detached signature over an artifact's digests.

    Args:
        digests: The three artifact digests.
        key: The signing key.
        key_id: Identifier of the signing key, recorded with the artifact so signatures
            remain verifiable across rotation.

    Returns:
        Hex-encoded HMAC-SHA256 signature.

    Raises:
        SlateArtifactError: When no signing key was supplied. Producing an unsigned
            artifact would leave the activation gate with nothing to verify.
    """
    if not key:
        raise SlateArtifactError(
            "missing_signing_key",
            "Refusing to produce an unsigned Slate artifact: no signing key configured.",
        )
    return hmac.new(
        key.encode("utf-8"), _signing_payload(digests, key_id), hashlib.sha256
    ).hexdigest()


def verify_signature(
    digests: ArtifactDigests, signature: str, *, key: str, key_id: str
) -> bool:
    """Verify a detached artifact signature in constant time.

    Returns False rather than raising for every failure mode — a wrong key, a tampered
    digest, a relabelled key id and a malformed signature are all simply "not verified" to
    the caller. Distinguishing them in the return value would hand an attacker an oracle
    for which part of their forgery was wrong.

    Args:
        digests: The three artifact digests as stored.
        signature: The stored hex-encoded signature.
        key: The key expected to have signed it.
        key_id: The key id recorded with the artifact.

    Returns:
        True when the signature verifies.
    """
    if not key or not signature:
        return False
    try:
        expected = hmac.new(
            key.encode("utf-8"), _signing_payload(digests, key_id), hashlib.sha256
        ).hexdigest()
    except SlateArtifactError:
        return False
    return hmac.compare_digest(expected, signature)


def build_manifest(
    *,
    digests: ArtifactDigests,
    generator: str,
    generator_version: str,
    routes: Sequence[str],
    size_bytes: int,
    dependencies: Optional[Sequence[Mapping[str, Any]]] = None,
    source_inputs: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the artifact manifest / SBOM stored alongside the build.

    The manifest records what produced the artifact and what is in it, so an operator
    investigating a bad release can answer "what changed" without re-running the build.
    Routes are sorted for the same reason the content digest folds sorted paths: a manifest
    whose ordering varies between identical builds invites false diffs.

    Args:
        digests: The three artifact digests.
        generator: Name of the static-site generator that produced the artifact.
        generator_version: Its version, recorded so a generator upgrade is visible as a
            config change rather than an unexplained content change.
        routes: Every route the artifact serves.
        size_bytes: Total artifact size.
        dependencies: Optional dependency inventory (name/version records) for the SBOM.
        source_inputs: Optional record of the source inputs the build consumed.
        config: Optional record of the build configuration applied.

    Returns:
        A JSON-serializable manifest mapping.
    """
    sorted_routes = sorted(routes)
    return {
        "schemaVersion": 1,
        "digests": digests.as_dict(),
        "generator": {"name": generator, "version": generator_version},
        "pageCount": len(sorted_routes),
        "sizeBytes": size_bytes,
        "routes": sorted_routes,
        "dependencies": [dict(item) for item in (dependencies or [])],
        "sourceInputs": dict(source_inputs or {}),
        "config": dict(config or {}),
    }
