"""MCP source association: parsing, canonicalization, and pin strength (CLX-3.2, #4856).

An MCP endpoint in the catalog is a URL. This module turns an operator's claim about *where that
server comes from* — a GitHub URL, an npm package, a container image, an MCP registry id — into a
canonical, storable :class:`SourceLink` (the ``apiome.mcp_endpoint_sources`` row, V172).

Pure: no database, no network, no filesystem. Parsing a reference never fetches it. That matters
for more than testability — it means linking a source cannot itself be a way to make Apiome reach
out to an attacker-chosen host.

Two independent axes, never collapsed
-------------------------------------
Every link records two different things, and conflating them would destroy the distinction a
reviewer actually needs:

* **provenance** — *how do we know this association?* An operator typing a URL into a form
  (``operator_declared``) is a much weaker claim than a signed attestation (``attested``), even
  when both name the exact same artifact.
* **verification_state** — *how strongly is the artifact pinned?* A reference to ``main`` or
  ``:latest`` is a moving target: whatever it pointed at when it was read is not necessarily what
  the endpoint runs now, so findings derived from it are **not reproducible** and are
  confidence-downgraded (:func:`confidence_for_link`). A commit sha or an OCI manifest digest is
  immutable, and findings against it are reproducible forever.

These are orthogonal. A hand-declared commit sha is strongly pinned but weakly attributed; a
registry-published branch name is better attributed but not pinned at all. One number cannot say
both, so this module keeps two.

Digests are never invented
--------------------------
:func:`parse_source_reference` derives a digest *only* when the caller's own reference already
contains one — a 40-hex commit, an ``@sha256:…`` image digest, an exact package version. It never
guesses, resolves, or defaults one. A source with no digest is ``unverified``, and the V172 CHECK
constraint ``mcp_endpoint_sources_pinned_needs_digest_check`` makes the alternative unstorable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse

# --- Source kinds -------------------------------------------------------------------------------
# The four ways an MCP server is distributed. Each pins to a different kind of immutable digest,
# which is why they are separate lanes rather than one free-form "source URL".

#: A git repository at a revision. Pinned by a 40-hex commit sha.
SOURCE_GIT = "git"

#: A package-registry package at a version. Pinned by the registry's integrity hash, when published.
SOURCE_PACKAGE = "package"

#: A container image. Pinned by its OCI manifest digest.
SOURCE_IMAGE = "image"

#: An MCP registry server identity. Pinned by the registry's own content digest.
SOURCE_REGISTRY = "registry"

#: Every known source kind, in stable order (mirrors the V172 CHECK constraint).
SOURCE_KINDS: Tuple[str, ...] = (SOURCE_GIT, SOURCE_PACKAGE, SOURCE_IMAGE, SOURCE_REGISTRY)

# --- Provenance ---------------------------------------------------------------------------------
# How the association came to be known. Never inferred from the reference itself.

#: A human linked it. The common case, and the weakest claim: Apiome has only the operator's word.
PROVENANCE_OPERATOR = "operator_declared"

#: The MCP registry that published the server declared this source.
PROVENANCE_REGISTRY = "registry_published"

#: The server itself advertised this source during discovery. Note this is the server's own claim
#: about itself — a compromised server can lie about where it came from, which is exactly why this
#: is a distinct (and not the strongest) provenance value.
PROVENANCE_DISCOVERY = "discovery_advertised"

#: Backed by a verifiable attestation (e.g. a signed SLSA provenance statement).
PROVENANCE_ATTESTED = "attested"

#: Every provenance value, in stable order (mirrors the V172 CHECK constraint).
PROVENANCES: Tuple[str, ...] = (
    PROVENANCE_OPERATOR,
    PROVENANCE_REGISTRY,
    PROVENANCE_DISCOVERY,
    PROVENANCE_ATTESTED,
)

# --- Verification state -------------------------------------------------------------------------

#: A moving reference — a branch, a floating tag, ``latest``. Findings are not reproducible.
VERIFICATION_UNVERIFIED = "unverified"

#: Pinned to an immutable digest. Findings are reproducible against the exact artifact scanned.
VERIFICATION_PINNED = "digest_pinned"

#: Digest-pinned AND the digest is backed by an attestation.
VERIFICATION_ATTESTED = "attested"

#: Every verification state, weakest first (mirrors the V172 CHECK constraint).
VERIFICATION_STATES: Tuple[str, ...] = (
    VERIFICATION_UNVERIFIED,
    VERIFICATION_PINNED,
    VERIFICATION_ATTESTED,
)

# --- Digest algorithms --------------------------------------------------------------------------

DIGEST_SHA1 = "sha1"
DIGEST_SHA256 = "sha256"

#: A git commit sha: exactly 40 lowercase hex characters. Short shas are deliberately NOT accepted —
#: an abbreviated sha is ambiguous, and an ambiguous pin is not a pin.
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

#: An OCI content digest, e.g. ``sha256:abc…`` (64 hex for sha256).
_OCI_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$")

#: An exact, non-range package version (``1.2.3``, ``1.2.3-rc.1``). A range or a dist-tag is not a
#: pin: ``^1.2.3`` and ``latest`` both resolve to different artifacts on different days.
_EXACT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-+]+)?$")

#: A Package URL, e.g. ``pkg:npm/%40scope/name@1.2.3``. Parsed structurally below rather than by one
#: monster regex, so a malformed purl produces a clear error instead of a silent non-match.
_PURL_PREFIX = "pkg:"

#: Reference values that look like a version but pin nothing.
_FLOATING_TAGS = frozenset({"latest", "main", "master", "head", "stable", "edge", "nightly"})

#: URL schemes a git source may use. ``file:`` and friends are rejected: a source reference is a
#: public coordinate, not a path into the host running Apiome.
_GIT_SCHEMES = frozenset({"https", "ssh", "git"})


class SourceReferenceError(ValueError):
    """Raised when a source reference cannot be parsed into a canonical link.

    Rejecting a malformed reference is deliberate: silently storing something unparseable would
    produce an association that no scan could ever resolve, and a source association that resolves
    to nothing is worse than none at all — it looks like coverage.
    """


@dataclass(frozen=True)
class SourceLink:
    """One canonical, storable MCP source association.

    Attributes:
        source_kind: One of :data:`SOURCE_KINDS`.
        locator: The canonical, normalized reference. Normalizing means the same artifact reached
            by two spellings (``git@github.com:o/r.git`` vs ``https://github.com/o/r``) is one row.
        purl: Package URL when the source has one. The only field ever transmitted to an external
            vulnerability database.
        revision: The human-facing reference the operator asked for (branch, tag, semver, image
            tag). May be a moving target — see ``verification_state``.
        digest: The immutable content identity, when the reference carried one. Never invented.
        digest_algorithm: ``sha1`` (git) or ``sha256`` (OCI / registry), or ``None``.
        provenance: How the association is known. Supplied by the caller, never inferred.
        provenance_detail: Supporting detail for the provenance claim (e.g. attestation issuer).
        verification_state: How strongly the artifact is pinned. Derived from whether a digest is
            actually present — never from what the caller asserts.
    """

    source_kind: str
    locator: str
    purl: Optional[str] = None
    revision: Optional[str] = None
    digest: Optional[str] = None
    digest_algorithm: Optional[str] = None
    provenance: str = PROVENANCE_OPERATOR
    provenance_detail: Mapping[str, Any] = field(default_factory=dict)
    verification_state: str = VERIFICATION_UNVERIFIED

    @property
    def is_pinned(self) -> bool:
        """True when the link names an immutable artifact, so findings against it are reproducible."""
        return self.verification_state != VERIFICATION_UNVERIFIED

    def as_dict(self) -> Dict[str, Any]:
        """Return the link as a JSON-ready dict (the wire shape and the V172 column set)."""
        return {
            "source_kind": self.source_kind,
            "locator": self.locator,
            "purl": self.purl,
            "revision": self.revision,
            "digest": self.digest,
            "digest_algorithm": self.digest_algorithm,
            "provenance": self.provenance,
            "provenance_detail": dict(self.provenance_detail),
            "verification_state": self.verification_state,
        }


def _normalize_git_locator(reference: str) -> str:
    """Canonicalize a git remote to ``https://host/owner/repo``.

    Collapses the spellings that all name one repository: scp-style ``git@host:owner/repo.git``,
    an ``ssh://`` or ``git://`` URL, a trailing ``.git``, a trailing slash, and host case. Without
    this, one repository linked twice under two spellings would be two rows and two scans.

    Args:
        reference: The raw git reference.

    Returns:
        The canonical ``https://host/owner/repo`` locator.

    Raises:
        SourceReferenceError: If the reference is not a usable git remote.
    """
    raw = reference.strip()

    # scp-style: git@github.com:owner/repo.git — not a URL, so urlparse cannot see it.
    scp = re.match(r"^(?:[\w.\-]+@)?([\w.\-]+):(?!//)([\w.\-/]+?)(?:\.git)?/?$", raw)
    if scp:
        host, path = scp.group(1), scp.group(2)
        return f"https://{host.lower()}/{path.strip('/')}"

    parsed = urlparse(raw)
    if parsed.scheme not in _GIT_SCHEMES or not parsed.netloc:
        raise SourceReferenceError(
            f"git source must be an https/ssh/git URL or scp-style remote, got {reference!r}"
        )

    # Strip any userinfo (git@, or worse, a token) from the host: credentials must never be stored
    # in a locator, and a locator that differs only by embedded credentials is the same repository.
    host = parsed.netloc.rsplit("@", 1)[-1].lower()
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not path:
        raise SourceReferenceError(f"git source has no repository path: {reference!r}")
    return f"https://{host}/{path}"


def _parse_purl(purl: str) -> Tuple[str, Optional[str]]:
    """Split a Package URL into ``(coordinate, version)``.

    Args:
        purl: e.g. ``pkg:npm/%40scope/name@1.2.3``.

    Returns:
        ``(coordinate_without_version, version_or_None)``.

    Raises:
        SourceReferenceError: If it is not a well-formed purl.
    """
    raw = purl.strip()
    if not raw.startswith(_PURL_PREFIX):
        raise SourceReferenceError(
            f"package source must be a Package URL starting with 'pkg:', got {purl!r}"
        )
    body = raw[len(_PURL_PREFIX) :]
    # Strip qualifiers/subpath before splitting on '@': a qualifier value may legally contain one.
    body = body.split("?", 1)[0].split("#", 1)[0]
    if "/" not in body:
        raise SourceReferenceError(f"Package URL has no package name: {purl!r}")

    coordinate, _, version = body.rpartition("@")
    if not coordinate:
        # No '@' at all: rpartition put everything in `version`.
        return f"{_PURL_PREFIX}{body}", None
    return f"{_PURL_PREFIX}{coordinate}", version or None


def _parse_image_reference(reference: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split an OCI image reference into ``(repository, tag, digest)``.

    Handles ``repo:tag``, ``repo@sha256:…``, and ``repo:tag@sha256:…``. The registry host may carry
    a port (``registry:5000/img:v1``), so the tag is looked for only after the final ``/``.

    Args:
        reference: The image reference.

    Returns:
        ``(repository, tag_or_None, digest_or_None)``.

    Raises:
        SourceReferenceError: If the reference is blank or carries an unsupported digest algorithm.
    """
    raw = reference.strip()
    if not raw:
        raise SourceReferenceError("image source reference is empty")

    digest: Optional[str] = None
    if "@" in raw:
        raw, _, digest_part = raw.partition("@")
        match = _OCI_DIGEST_RE.match(digest_part.strip().lower())
        if not match:
            raise SourceReferenceError(
                f"image digest must be 'sha256:<64 hex>', got {digest_part!r}"
            )
        digest = f"sha256:{match.group(1)}"

    # A ':' before the last '/' is a registry port, not a tag.
    tag: Optional[str] = None
    last_segment_start = raw.rfind("/") + 1
    colon = raw.find(":", last_segment_start)
    if colon != -1:
        tag = raw[colon + 1 :] or None
        raw = raw[:colon]

    repository = raw.strip("/")
    if not repository:
        raise SourceReferenceError(f"image source has no repository: {reference!r}")
    return repository, tag, digest


def parse_source_reference(
    source_kind: str,
    reference: str,
    *,
    revision: Optional[str] = None,
    provenance: str = PROVENANCE_OPERATOR,
    provenance_detail: Optional[Mapping[str, Any]] = None,
    attested: bool = False,
) -> SourceLink:
    """Parse an operator's source reference into a canonical :class:`SourceLink`.

    The pin strength is *derived*, never asserted. A caller cannot claim ``digest_pinned`` for a
    reference that carries no digest: this function inspects what the reference actually contains
    and sets ``verification_state`` from that. ``attested=True`` upgrades a pinned link to
    ``attested`` but can never pin an unpinned one — an attestation over a moving reference still
    does not tell you which artifact is running.

    Args:
        source_kind: One of :data:`SOURCE_KINDS`.
        reference: The reference to parse. Its meaning depends on the kind: a git remote URL, a
            Package URL, an OCI image reference, or an MCP registry server id.
        revision: For git, the branch/tag/commit. Ignored for the other kinds, which carry their
            revision inside the reference itself (a package version, an image tag/digest).
        provenance: How the association is known (:data:`PROVENANCES`). Supplied, never inferred —
            this function cannot tell an operator's guess from a registry's publication.
        provenance_detail: Supporting detail for the provenance claim.
        attested: Whether the digest is attestation-backed. Only upgrades an already-pinned link.

    Returns:
        The canonical :class:`SourceLink`.

    Raises:
        SourceReferenceError: If the kind is unknown or the reference is unparseable.
    """
    if source_kind not in SOURCE_KINDS:
        raise SourceReferenceError(
            f"unknown source kind {source_kind!r}; known kinds: {list(SOURCE_KINDS)}"
        )
    if provenance not in PROVENANCES:
        raise SourceReferenceError(
            f"unknown provenance {provenance!r}; known values: {list(PROVENANCES)}"
        )
    if not reference or not reference.strip():
        raise SourceReferenceError(f"{source_kind} source reference is empty")

    detail = dict(provenance_detail or {})

    if source_kind == SOURCE_GIT:
        link = _git_link(reference, revision, provenance, detail)
    elif source_kind == SOURCE_PACKAGE:
        link = _package_link(reference, provenance, detail)
    elif source_kind == SOURCE_IMAGE:
        link = _image_link(reference, provenance, detail)
    else:
        link = _registry_link(reference, revision, provenance, detail)

    if attested and link.digest:
        return SourceLink(**{**link.__dict__, "verification_state": VERIFICATION_ATTESTED})
    return link


def _git_link(
    reference: str,
    revision: Optional[str],
    provenance: str,
    detail: Dict[str, Any],
) -> SourceLink:
    """Build the link for a git source. Pinned only by a full 40-hex commit sha."""
    locator = _normalize_git_locator(reference)
    rev = (revision or "").strip()

    digest: Optional[str] = None
    algorithm: Optional[str] = None
    if _GIT_COMMIT_RE.match(rev.lower()):
        digest = rev.lower()
        algorithm = DIGEST_SHA1

    return SourceLink(
        source_kind=SOURCE_GIT,
        locator=locator,
        purl=None,
        revision=rev or None,
        digest=digest,
        digest_algorithm=algorithm,
        provenance=provenance,
        provenance_detail=detail,
        verification_state=VERIFICATION_PINNED if digest else VERIFICATION_UNVERIFIED,
    )


def _package_link(
    reference: str, provenance: str, detail: Dict[str, Any]
) -> SourceLink:
    """Build the link for a package source. Pinned only by an exact, non-range version."""
    coordinate, version = _parse_purl(reference)
    canonical = f"{coordinate}@{version}" if version else coordinate

    # A version pins the artifact only when it is exact. A range (``^1.2.3``) or a dist-tag
    # (``latest``) resolves to a different package on a different day, which is not a pin.
    pinned = bool(
        version
        and version.lower() not in _FLOATING_TAGS
        and _EXACT_VERSION_RE.match(version)
    )

    return SourceLink(
        source_kind=SOURCE_PACKAGE,
        locator=canonical,
        purl=canonical,
        revision=version,
        # The version IS the content identity for a registry package: an immutable, exact version is
        # the strongest identity the ecosystem offers without a per-registry integrity hash, and
        # every major registry forbids republishing one.
        digest=version if pinned else None,
        digest_algorithm="version" if pinned else None,
        provenance=provenance,
        provenance_detail=detail,
        verification_state=VERIFICATION_PINNED if pinned else VERIFICATION_UNVERIFIED,
    )


def _image_link(reference: str, provenance: str, detail: Dict[str, Any]) -> SourceLink:
    """Build the link for a container image. Pinned only by an OCI manifest digest."""
    repository, tag, digest = _parse_image_reference(reference)

    # Canonical form prefers the digest: it is what actually identifies the artifact. The tag is
    # kept as `revision` because it is what a human recognizes, but it is not what pins.
    if digest:
        locator = f"{repository}@{digest}"
    elif tag:
        locator = f"{repository}:{tag}"
    else:
        locator = repository

    return SourceLink(
        source_kind=SOURCE_IMAGE,
        locator=locator,
        purl=f"pkg:oci/{repository.rsplit('/', 1)[-1]}@{digest}" if digest else None,
        revision=tag,
        digest=digest,
        digest_algorithm=DIGEST_SHA256 if digest else None,
        provenance=provenance,
        provenance_detail=detail,
        verification_state=VERIFICATION_PINNED if digest else VERIFICATION_UNVERIFIED,
    )


def _registry_link(
    reference: str,
    revision: Optional[str],
    provenance: str,
    detail: Dict[str, Any],
) -> SourceLink:
    """Build the link for an MCP registry identity. Pinned only by an explicit content digest."""
    identity = reference.strip()
    rev = (revision or "").strip()

    digest: Optional[str] = None
    algorithm: Optional[str] = None
    match = _OCI_DIGEST_RE.match(rev.lower())
    if match:
        digest = f"sha256:{match.group(1)}"
        algorithm = DIGEST_SHA256

    return SourceLink(
        source_kind=SOURCE_REGISTRY,
        locator=identity,
        purl=None,
        revision=rev or None,
        digest=digest,
        digest_algorithm=algorithm,
        provenance=provenance,
        provenance_detail=detail,
        verification_state=VERIFICATION_PINNED if digest else VERIFICATION_UNVERIFIED,
    )


# --- Confidence ---------------------------------------------------------------------------------

#: Finding confidence for evidence derived from an immutable, pinned artifact: the exact bytes that
#: produced the finding can be fetched again and the finding reproduced.
CONFIDENCE_HIGH = "high"

#: Finding confidence for evidence derived from a moving reference. The finding was true of whatever
#: the reference resolved to when it was read — which is not necessarily what the endpoint runs now.
#: This is not a statement about the *rule's* accuracy; the rule may be perfectly certain. It is a
#: statement about whether the thing it was certain about is still the thing in production.
CONFIDENCE_MEDIUM = "medium"


def confidence_for_link(link: Optional[SourceLink]) -> str:
    """Confidence to stamp on findings derived from ``link``.

    Args:
        link: The source the evidence came from, or ``None`` for evidence that came from the
            discovery surface rather than from a source artifact (surface evidence is always
            reproducible from the stored snapshot, so it is ``high``).

    Returns:
        :data:`CONFIDENCE_HIGH` for surface evidence or a pinned artifact; :data:`CONFIDENCE_MEDIUM`
        for a moving reference.
    """
    if link is None or link.is_pinned:
        return CONFIDENCE_HIGH
    return CONFIDENCE_MEDIUM


def link_from_row(row: Mapping[str, Any]) -> SourceLink:
    """Rebuild a :class:`SourceLink` from its stored ``mcp_endpoint_sources`` row.

    Args:
        row: The V172 row (needs at least ``source_kind`` and ``locator``).

    Returns:
        The reconstructed link, so a recompute from the database resolves its source exactly as the
        original scan did.
    """
    detail = row.get("provenance_detail")
    return SourceLink(
        source_kind=str(row["source_kind"]),
        locator=str(row["locator"]),
        purl=str(row["purl"]) if row.get("purl") else None,
        revision=str(row["revision"]) if row.get("revision") else None,
        digest=str(row["digest"]) if row.get("digest") else None,
        digest_algorithm=(
            str(row["digest_algorithm"]) if row.get("digest_algorithm") else None
        ),
        provenance=str(row.get("provenance") or PROVENANCE_OPERATOR),
        provenance_detail=dict(detail) if isinstance(detail, Mapping) else {},
        verification_state=str(row.get("verification_state") or VERIFICATION_UNVERIFIED),
    )
