"""SBOM ingestion and lockfile-derived dependency inventory (CLX-3.2, #4856).

Produces the component inventory of a linked MCP source: what the server is built out of, as
**coordinates only** — name, version, Package URL, declared license. Never file contents, never
source, never manifest text.

That restriction is the "no source exfiltration" acceptance criterion, and it is enforced by shape
rather than by discipline: :class:`SbomComponent` has no field that could hold source, so there is
nothing for a careless caller to put there, and the V172 ``mcp_source_sboms`` table has no column
for it either. Downstream, :mod:`app.mcp_vulnerability` queries a vulnerability database using the
purls this module produces — coordinates leave the process, code never does.

Two origins, kept distinct
--------------------------
* ``operator_supplied`` — a real CycloneDX or SPDX document was uploaded. **Authoritative**: it
  describes what was actually built.
* ``manifest_derived`` — Apiome read the project's lockfiles and inferred the components.
  **Best-effort**: a lockfile says what a build *would* resolve, which is not always what the
  running server actually contains, and a polyglot repository whose second lockfile Apiome cannot
  parse yields a *partial* inventory.

The two are never merged into one number. :attr:`SbomInventory.scanned_manifests` names exactly
which files a derivation read (paths only), so an inventory that covers one of a repository's three
lockfiles is visibly partial rather than quietly presented as complete.

Parsers are tolerant, not credulous
-----------------------------------
A malformed component is skipped and counted in :attr:`SbomInventory.skipped_components`, never
silently dropped and never guessed at. An SBOM with 400 components of which 12 are unparseable
reports 388 components and 12 skipped — it does not report 388 and imply that is all there was.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --- Formats and origins ------------------------------------------------------------------------

#: An ingested CycloneDX document.
FORMAT_CYCLONEDX = "cyclonedx"

#: An ingested SPDX document.
FORMAT_SPDX = "spdx"

#: Components Apiome derived from lockfiles rather than ingested from an SBOM.
FORMAT_MANIFEST = "apiome-manifest"

#: Every inventory format (mirrors the V172 CHECK constraint).
SBOM_FORMATS: Tuple[str, ...] = (FORMAT_CYCLONEDX, FORMAT_SPDX, FORMAT_MANIFEST)

#: An authoritative SBOM document the operator uploaded.
ORIGIN_SUPPLIED = "operator_supplied"

#: A best-effort inventory Apiome derived by reading lockfiles.
ORIGIN_DERIVED = "manifest_derived"

#: Every inventory origin (mirrors the V172 CHECK constraint).
SBOM_ORIGINS: Tuple[str, ...] = (ORIGIN_SUPPLIED, ORIGIN_DERIVED)

#: Ceiling on the components retained from one inventory. A pathological SBOM should not be able to
#: turn one linked source into an unbounded row. The overflow is *counted*, not dropped silently.
MAX_COMPONENTS = 5000


class SbomFormatError(ValueError):
    """Raised when a document does not parse as any SBOM format this module understands.

    Rejecting is deliberate. Accepting an unrecognized document and storing zero components would
    render as "this artifact has no dependencies" — a clean-looking result produced by a parse
    failure, which is the exact confusion the evidence contract exists to prevent.
    """


@dataclass(frozen=True)
class SbomComponent:
    """One dependency, as coordinates.

    There is deliberately no field here that can carry source, file content, or a code snippet.
    The absence is the point: this dataclass is the boundary the no-exfiltration guarantee is
    enforced at.

    Attributes:
        name: Package name.
        version: Package version, when stated.
        purl: Package URL. The join key for vulnerability lookup, and the only value ever sent to an
            external vulnerability database.
        license: Declared license expression / SPDX id, when stated.
        scope: ``runtime`` / ``dev`` / ``optional`` when stated. A vulnerability in a dev-only
            dependency is a genuinely different risk from one in a shipped runtime dependency.
    """

    name: str
    version: Optional[str] = None
    purl: Optional[str] = None
    license: Optional[str] = None
    scope: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Return the component as a JSON-ready dict (the V172 ``components`` element shape)."""
        return {
            "name": self.name,
            "version": self.version,
            "purl": self.purl,
            "license": self.license,
            "scope": self.scope,
        }

    def sort_key(self) -> Tuple[str, str, str]:
        """Stable ordering key, so an inventory renders and fingerprints identically every time."""
        return (self.name, self.version or "", self.purl or "")


@dataclass(frozen=True)
class SbomInventory:
    """The dependency inventory of one pinned source artifact.

    Attributes:
        sbom_format: One of :data:`SBOM_FORMATS`.
        sbom_spec_version: The document's own spec version (e.g. CycloneDX ``1.5``), when stated.
        origin: :data:`ORIGIN_SUPPLIED` (authoritative) or :data:`ORIGIN_DERIVED` (best-effort).
        components: The components, sorted, de-duplicated, and capped at :data:`MAX_COMPONENTS`.
        scanned_manifests: Paths of the lockfiles a derivation read — **paths only, never content**.
            Empty for an ingested SBOM. This is what makes a partial inventory visibly partial.
        skipped_components: Components the parser could not read. Counted, never silently dropped:
            an inventory that quietly discards what it could not parse looks more complete than it is.
        truncated: How many components the :data:`MAX_COMPONENTS` cap excluded.
    """

    sbom_format: str
    origin: str
    components: Tuple[SbomComponent, ...] = ()
    sbom_spec_version: Optional[str] = None
    scanned_manifests: Tuple[str, ...] = ()
    skipped_components: int = 0
    truncated: int = 0

    @property
    def component_count(self) -> int:
        """Number of components retained in this inventory."""
        return len(self.components)

    @property
    def is_authoritative(self) -> bool:
        """True when this inventory came from a real SBOM rather than being inferred from lockfiles."""
        return self.origin == ORIGIN_SUPPLIED

    def purls(self) -> List[str]:
        """Every distinct purl in the inventory, sorted.

        This is exactly the payload :mod:`app.mcp_vulnerability` sends to a vulnerability database —
        and it is the *whole* payload. Nothing else about the source leaves the process.
        """
        return sorted({c.purl for c in self.components if c.purl})

    def fingerprint(self) -> str:
        """Stable hash over the canonicalized component set.

        Two inventories of the same artifact hash equal regardless of the order the source document
        listed things in, so a re-ingest of an unchanged SBOM is detectably unchanged.
        """
        payload = [c.as_dict() for c in self.components]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def as_dict(self) -> Dict[str, Any]:
        """Return the inventory as a JSON-ready dict (the API payload and the V172 row shape)."""
        return {
            "sbom_format": self.sbom_format,
            "sbom_spec_version": self.sbom_spec_version,
            "origin": self.origin,
            "components": [c.as_dict() for c in self.components],
            "component_count": self.component_count,
            "sbom_fingerprint": self.fingerprint(),
            "scanned_manifests": list(self.scanned_manifests),
            "skipped_components": self.skipped_components,
            "truncated": self.truncated,
            "authoritative": self.is_authoritative,
        }


def _finalize(
    components: Iterable[SbomComponent],
    *,
    sbom_format: str,
    origin: str,
    spec_version: Optional[str] = None,
    scanned_manifests: Sequence[str] = (),
    skipped: int = 0,
) -> SbomInventory:
    """De-duplicate, sort, and cap a component list into an :class:`SbomInventory`."""
    unique: Dict[Tuple[str, str, str], SbomComponent] = {}
    for component in components:
        unique.setdefault(component.sort_key(), component)

    ordered = sorted(unique.values(), key=lambda c: c.sort_key())
    truncated = max(0, len(ordered) - MAX_COMPONENTS)

    return SbomInventory(
        sbom_format=sbom_format,
        origin=origin,
        components=tuple(ordered[:MAX_COMPONENTS]),
        sbom_spec_version=spec_version,
        scanned_manifests=tuple(sorted(scanned_manifests)),
        skipped_components=skipped,
        truncated=truncated,
    )


# --- CycloneDX ----------------------------------------------------------------------------------


def _cyclonedx_license(component: Mapping[str, Any]) -> Optional[str]:
    """Extract a license expression from a CycloneDX component's ``licenses`` array."""
    licenses = component.get("licenses")
    if not isinstance(licenses, list):
        return None
    for entry in licenses:
        if not isinstance(entry, Mapping):
            continue
        # CycloneDX allows either {"license": {"id"|"name": ...}} or {"expression": "..."}.
        expression = entry.get("expression")
        if isinstance(expression, str) and expression.strip():
            return expression.strip()
        license_obj = entry.get("license")
        if isinstance(license_obj, Mapping):
            value = license_obj.get("id") or license_obj.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def parse_cyclonedx(document: Mapping[str, Any]) -> SbomInventory:
    """Parse a CycloneDX (1.4–1.6) JSON document into an inventory.

    Only the coordinate fields are read. ``components[].properties``, evidence blocks, and any other
    field that could carry file contents or source paths are deliberately not consulted.

    Args:
        document: The parsed CycloneDX JSON.

    Returns:
        The inventory, origin :data:`ORIGIN_SUPPLIED`.

    Raises:
        SbomFormatError: If the document does not declare ``bomFormat: CycloneDX``.
    """
    if str(document.get("bomFormat") or "").lower() != "cyclonedx":
        raise SbomFormatError("document does not declare bomFormat 'CycloneDX'")

    spec_version = document.get("specVersion")
    raw_components = document.get("components")
    if not isinstance(raw_components, list):
        raw_components = []

    components: List[SbomComponent] = []
    skipped = 0
    for entry in raw_components:
        if not isinstance(entry, Mapping):
            skipped += 1
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            # A component with no name cannot be identified, matched to a vulnerability, or shown to
            # a human. Counted, not invented.
            skipped += 1
            continue
        version = entry.get("version")
        purl = entry.get("purl")
        scope = entry.get("scope")
        components.append(
            SbomComponent(
                name=name.strip(),
                version=str(version).strip() if isinstance(version, (str, int, float)) else None,
                purl=purl.strip() if isinstance(purl, str) and purl.strip() else None,
                license=_cyclonedx_license(entry),
                scope=scope.strip() if isinstance(scope, str) and scope.strip() else None,
            )
        )

    return _finalize(
        components,
        sbom_format=FORMAT_CYCLONEDX,
        origin=ORIGIN_SUPPLIED,
        spec_version=str(spec_version) if spec_version is not None else None,
        skipped=skipped,
    )


# --- SPDX ---------------------------------------------------------------------------------------

#: An SPDX external reference identifying a package by purl.
_SPDX_PURL_TYPE = "purl"


def _spdx_purl(package: Mapping[str, Any]) -> Optional[str]:
    """Extract a purl from an SPDX package's ``externalRefs``."""
    refs = package.get("externalRefs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        if str(ref.get("referenceType") or "").lower() == _SPDX_PURL_TYPE:
            locator = ref.get("referenceLocator")
            if isinstance(locator, str) and locator.strip():
                return locator.strip()
    return None


def parse_spdx(document: Mapping[str, Any]) -> SbomInventory:
    """Parse an SPDX 2.x JSON document into an inventory.

    Args:
        document: The parsed SPDX JSON.

    Returns:
        The inventory, origin :data:`ORIGIN_SUPPLIED`.

    Raises:
        SbomFormatError: If the document does not declare an ``spdxVersion``.
    """
    spec_version = document.get("spdxVersion")
    if not isinstance(spec_version, str) or not spec_version.upper().startswith("SPDX-"):
        raise SbomFormatError("document does not declare an 'spdxVersion' of the form 'SPDX-2.x'")

    raw_packages = document.get("packages")
    if not isinstance(raw_packages, list):
        raw_packages = []

    components: List[SbomComponent] = []
    skipped = 0
    for entry in raw_packages:
        if not isinstance(entry, Mapping):
            skipped += 1
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            skipped += 1
            continue
        version = entry.get("versionInfo")
        # SPDX writes "NOASSERTION" where a real SBOM would omit the field. Treating that string as a
        # license would be worse than recording nothing, so it is normalized away.
        declared = entry.get("licenseDeclared") or entry.get("licenseConcluded")
        license_value = (
            declared.strip()
            if isinstance(declared, str)
            and declared.strip()
            and declared.strip().upper() != "NOASSERTION"
            else None
        )
        components.append(
            SbomComponent(
                name=name.strip(),
                version=(
                    str(version).strip()
                    if isinstance(version, (str, int, float))
                    and str(version).strip().upper() != "NOASSERTION"
                    else None
                ),
                purl=_spdx_purl(entry),
                license=license_value,
                scope=None,
            )
        )

    return _finalize(
        components,
        sbom_format=FORMAT_SPDX,
        origin=ORIGIN_SUPPLIED,
        spec_version=spec_version,
        skipped=skipped,
    )


def parse_sbom(document: Mapping[str, Any]) -> SbomInventory:
    """Parse a CycloneDX or SPDX document, detecting which it is.

    Args:
        document: The parsed SBOM JSON.

    Returns:
        The inventory.

    Raises:
        SbomFormatError: If the document is neither format.
    """
    if document.get("bomFormat"):
        return parse_cyclonedx(document)
    if document.get("spdxVersion"):
        return parse_spdx(document)
    raise SbomFormatError(
        "unrecognized SBOM: expected a CycloneDX document (with 'bomFormat') or an SPDX document "
        "(with 'spdxVersion')"
    )


# --- Lockfile-derived inventory -----------------------------------------------------------------
# Best-effort, and labelled as such. These parsers read the lockfiles a caller has already fetched;
# they never fetch anything themselves, and they retain only coordinates from what they read.

#: An npm scope-qualified name, e.g. ``@scope/pkg``. purls percent-encode the leading ``@``.
_NPM_SCOPED_RE = re.compile(r"^@([^/]+)/(.+)$")

#: A ``requirements.txt`` pin: ``name==1.2.3``. Only exact pins yield a version — a range does not
#: identify an artifact, and guessing one would be inventing evidence.
_PIP_PIN_RE = re.compile(r"^\s*([A-Za-z0-9._\-]+)\s*==\s*([^\s;#]+)")

#: A ``go.mod`` require line: ``require example.com/mod v1.2.3`` or the same inside a block.
_GOMOD_REQUIRE_RE = re.compile(r"^\s*(?:require\s+)?([\w.\-]+(?:/[\w.\-]+)+)\s+(v[\w.\-+]+)")


def _npm_purl(name: str, version: Optional[str]) -> str:
    """Build an npm purl, percent-encoding the ``@`` of a scoped package as the purl spec requires."""
    scoped = _NPM_SCOPED_RE.match(name)
    coordinate = f"%40{scoped.group(1)}/{scoped.group(2)}" if scoped else name
    return f"pkg:npm/{coordinate}@{version}" if version else f"pkg:npm/{coordinate}"


def _components_from_package_lock(document: Mapping[str, Any]) -> List[SbomComponent]:
    """Derive components from an npm ``package-lock.json`` (lockfileVersion 2/3)."""
    components: List[SbomComponent] = []
    packages = document.get("packages")
    if isinstance(packages, Mapping):
        for path, entry in packages.items():
            # The "" key is the root project itself, not a dependency of it.
            if not path or not isinstance(entry, Mapping):
                continue
            name = entry.get("name") or path.rsplit("node_modules/", 1)[-1]
            if not isinstance(name, str) or not name.strip():
                continue
            version = entry.get("version")
            version_str = str(version).strip() if version else None
            scope = "dev" if entry.get("dev") else "runtime"
            components.append(
                SbomComponent(
                    name=name.strip(),
                    version=version_str,
                    purl=_npm_purl(name.strip(), version_str),
                    license=(
                        str(entry["license"]).strip()
                        if isinstance(entry.get("license"), str)
                        else None
                    ),
                    scope=scope,
                )
            )
    return components


def _components_from_requirements(text: str) -> List[SbomComponent]:
    """Derive components from a pip ``requirements.txt``. Only exact ``==`` pins are recorded."""
    components: List[SbomComponent] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        match = _PIP_PIN_RE.match(stripped)
        if not match:
            # A range or an unpinned name identifies no specific artifact. It is skipped rather than
            # recorded with a guessed version, which would attach real vulnerability findings to a
            # version nobody ever installed.
            continue
        name, version = match.group(1), match.group(2)
        components.append(
            SbomComponent(
                name=name,
                version=version,
                purl=f"pkg:pypi/{name.lower()}@{version}",
                scope="runtime",
            )
        )
    return components


def _components_from_gomod(text: str) -> List[SbomComponent]:
    """Derive components from a ``go.mod``. Indirect requirements are scoped as such."""
    components: List[SbomComponent] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "module ", "go ")):
            continue
        match = _GOMOD_REQUIRE_RE.match(stripped)
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        components.append(
            SbomComponent(
                name=name,
                version=version,
                purl=f"pkg:golang/{name}@{version}",
                scope="optional" if "// indirect" in line else "runtime",
            )
        )
    return components


#: Lockfile basename -> the parser that reads it. Adding an ecosystem means adding one entry here;
#: a lockfile with no entry is reported as *unparsed* rather than ignored (see
#: :func:`derive_inventory`), so an unsupported ecosystem is a visible gap.
_JSON_MANIFESTS = {"package-lock.json": _components_from_package_lock}
_TEXT_MANIFESTS = {
    "requirements.txt": _components_from_requirements,
    "go.mod": _components_from_gomod,
}

#: Every lockfile basename this module can derive components from.
SUPPORTED_MANIFESTS: Tuple[str, ...] = tuple(
    sorted({*_JSON_MANIFESTS, *_TEXT_MANIFESTS})
)


def derive_inventory(
    documents: Mapping[str, str],
) -> Tuple[SbomInventory, Tuple[str, ...]]:
    """Derive a best-effort inventory from lockfiles the caller has already read.

    Takes text that is already in hand — it never fetches, and it retains only coordinates from what
    it is given. The manifest *text* does not survive this call: only names, versions, purls, and
    licenses do.

    Args:
        documents: ``{path: text}`` for the lockfiles to read. Paths may be nested
            (``services/api/go.mod``); the basename selects the parser.

    Returns:
        ``(inventory, unparsed_paths)``. ``unparsed_paths`` names files that looked like manifests
        but could not be read — malformed JSON, or an ecosystem with no parser. They are returned
        rather than swallowed so the caller can report the inventory as *partial*: an inventory
        derived from two of a repository's three lockfiles is not the repository's dependency set,
        and must not be presented as one.
    """
    components: List[SbomComponent] = []
    scanned: List[str] = []
    unparsed: List[str] = []

    for path, text in sorted(documents.items()):
        basename = path.rsplit("/", 1)[-1]

        if basename in _JSON_MANIFESTS:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                unparsed.append(path)
                continue
            if not isinstance(parsed, Mapping):
                unparsed.append(path)
                continue
            components.extend(_JSON_MANIFESTS[basename](parsed))
            scanned.append(path)
        elif basename in _TEXT_MANIFESTS:
            components.extend(_TEXT_MANIFESTS[basename](text))
            scanned.append(path)
        else:
            unparsed.append(path)

    inventory = _finalize(
        components,
        sbom_format=FORMAT_MANIFEST,
        origin=ORIGIN_DERIVED,
        scanned_manifests=scanned,
    )
    return inventory, tuple(sorted(unparsed))


def inventory_row(
    inventory: SbomInventory,
    *,
    source_id: str,
    subject_digest: str,
) -> Dict[str, Any]:
    """Build the ``mcp_source_sboms`` row (V172) for an inventory.

    Args:
        inventory: The inventory to persist.
        source_id: The ``mcp_endpoint_sources`` row it belongs to.
        subject_digest: The immutable artifact digest this inventory describes. An SBOM is a
            statement about a *specific artifact*, so it is keyed by digest: re-scanning at a new
            commit writes a new row rather than mutating one that is still the true inventory of the
            old commit.

    Returns:
        A column-name -> value dict ready for the persistence layer.
    """
    return {
        "source_id": source_id,
        "subject_digest": subject_digest,
        "sbom_format": inventory.sbom_format,
        "sbom_spec_version": inventory.sbom_spec_version,
        "origin": inventory.origin,
        "components": [c.as_dict() for c in inventory.components],
        "component_count": inventory.component_count,
        "sbom_fingerprint": inventory.fingerprint(),
        "scanned_manifests": list(inventory.scanned_manifests),
    }


def inventory_from_row(row: Mapping[str, Any]) -> SbomInventory:
    """Rebuild an :class:`SbomInventory` from its stored V172 row.

    Args:
        row: The ``mcp_source_sboms`` row.

    Returns:
        The reconstructed inventory, so a recompute from the database sees exactly the component set
        the original scan did.
    """
    raw = row.get("components")
    components: List[SbomComponent] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            components.append(
                SbomComponent(
                    name=name,
                    version=entry.get("version"),
                    purl=entry.get("purl"),
                    license=entry.get("license"),
                    scope=entry.get("scope"),
                )
            )

    manifests = row.get("scanned_manifests")
    return SbomInventory(
        sbom_format=str(row.get("sbom_format") or FORMAT_MANIFEST),
        origin=str(row.get("origin") or ORIGIN_DERIVED),
        components=tuple(sorted(components, key=lambda c: c.sort_key())),
        sbom_spec_version=(
            str(row["sbom_spec_version"]) if row.get("sbom_spec_version") else None
        ),
        scanned_manifests=tuple(manifests) if isinstance(manifests, list) else (),
    )
