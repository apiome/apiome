"""Emitted WSDL bundle validation — MFX-14.3 (#3891).

The WSDL emitter (:mod:`app.wsdl_emitter`, MFX-14.1) writes a multi-file bundle: ``<Name>.wsdl``
plus the ``<Name>.xsd`` its ``wsdl:types`` imports, delivered as one zip (MFX-4.2). This module
proves such a bundle is a working web service description *as it will be unpacked* — the
``wsdl`` validator of the emitted-artifact gate (:mod:`app.export_validation`, MFX-5.1). It runs
five checks in order and reports every problem as a :class:`WsdlBundleProblem`:

1. **Root** (``wsdl.bundle-root``) — exactly one member is a WSDL description.
2. **XML** (``wsdl.xml``) — every member is safe, well-formed XML (:func:`app.secure_xml.parse_xml`).
3. **Packaging** (``wsdl.bundle-reference``) — every ``wsdl:import/@location`` and
   ``xs:import`` / ``xs:include`` / ``xs:redefine`` ``schemaLocation`` resolves, relative to the
   member that declares it, to another member of the bundle. A remote URL or a path outside the
   bundle is reported: an unpacked zip has nothing else to resolve against. (The import reader
   is more forgiving — it also matches a bare file name — so this check is stricter than it.)
4. **WS-I Basic Profile** (``wsi.*``) — the same checks the import runs (:func:`app.wsdl_wsi.check_wsi`):
   literal use, one binding style, document/literal parts, unique operation signatures and
   ``soapAction`` s, resolvable imports. A WSDL *source* is exported with its own bindings, so
   a kind of issue (rule) the source description already had when it was imported
   (:func:`inherited_wsi_rules`) is carried over rather than introduced, and is not reported —
   the import's lint already shows it. Every other source is written document/literal wrapped and
   must come out clean.
5. **Structure** (``wsdl.structure``) — the bundle is unpacked into a private temporary folder
   and read by ``xmlschema`` 's WSDL 1.1 reader (:class:`xmlschema.extras.wsdl.Wsdl11Document`),
   which validates the description against the WSDL 1.1 schema, builds every XSD schema (inline
   and imported — an unknown type, a broken facet or a dangling ``ref`` fails here), and resolves
   every message, part element, port type, binding and port reference. Only files inside that
   folder are readable (``allow="sandbox"``); nothing is fetched.
6. **Re-import** (``wsdl.reimport``) — the bundle imports through the WSDL import source
   (:class:`app.wsdl_import_source.WsdlImportSource`), as it would if a user uploaded it.

The structure check needs a well-formed, fully packaged bundle, so checks 4–6 run only when 1–3
pass. ``xmlschema`` reads SOAP 1.1 bindings only: when a description also carries SOAP 1.2 or
HTTP bindings (a WSDL source that had them), its reader checks every binding generically — the
SOAP body rules are then covered by the WS-I checks.
"""

from __future__ import annotations

import posixpath
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Dict, FrozenSet, List, Mapping, Optional

from xmlschema.extras.wsdl import Wsdl11Document

from .canonical_model import CanonicalApi
from .fileset import IntakeFileset
from .import_source import ImportSourceError
from .secure_xml import SecureXmlError, parse_xml
from .wsdl_import_source import WsdlImportSource
from .wsdl_versions import VERSION_1_1, VERSION_2_0, WSDL_1_1_NAMESPACE, WSDL_2_0_NAMESPACE
from .wsdl_wsi import check_wsi
from .zip_bundle import safe_bundle_path

__all__ = [
    "WsdlBundleProblem",
    "bundle_reference_problems",
    "inherited_wsi_rules",
    "reader_file",
    "reader_message",
    "validate_wsdl_bundle",
]

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_SOAP11_NS = "http://schemas.xmlsoap.org/wsdl/soap/"

#: ``(namespace, element local name, location attribute)`` of every reference a bundle must carry.
_REFERENCES = (
    (WSDL_1_1_NAMESPACE, "import", "location"),
    (WSDL_2_0_NAMESPACE, "import", "location"),
    (WSDL_2_0_NAMESPACE, "include", "location"),
    (_XSD_NS, "import", "schemaLocation"),
    (_XSD_NS, "include", "schemaLocation"),
    (_XSD_NS, "redefine", "schemaLocation"),
)

#: Root element → WSDL version, for the two grammars.
_ROOT_VERSIONS = {
    f"{{{WSDL_1_1_NAMESPACE}}}definitions": VERSION_1_1,
    f"{{{WSDL_2_0_NAMESPACE}}}description": VERSION_2_0,
}


@dataclass(frozen=True)
class WsdlBundleProblem:
    """One reason an emitted WSDL bundle is not valid.

    Attributes:
        rule: The check that found it (``wsdl.bundle-reference``, ``wsi.literal-use``…).
        message: What is wrong.
        file: The bundle member it is in, when known.
        path: Where in that member (a WS-I path, or the reference's location), when known.
    """

    rule: str
    message: str
    file: Optional[str] = None
    path: Optional[str] = None


class _GenericBindingWsdl11Document(Wsdl11Document):
    """``xmlschema``'s WSDL 1.1 reader with its SOAP 1.1 binding model switched off.

    The stock reader turns its SOAP 1.1 model on whenever the SOAP 1.1 namespace is declared, and
    then rejects every binding without a ``soap:binding`` — a SOAP 1.2 or HTTP binding next to a
    SOAP 1.1 one is legal WSDL. This variant reads every binding generically (port type, operation
    names, input/output/fault names) and still validates the schema and every other reference.
    """

    @property
    def soap_binding(self) -> bool:
        """Always ``False``: read bindings generically."""
        return False

    @soap_binding.setter
    def soap_binding(self, value: bool) -> None:
        """Ignore the stock reader's assignment (see the class docstring)."""


def inherited_wsi_rules(api: CanonicalApi) -> FrozenSet[str]:
    """The WS-I rules a WSDL source already broke when it was imported (none for other sources).

    The WSDL normalizer records the import's WS-I issues in ``extras["wsdl_wsi_issues"]``
    (MFI-13.4).
    """
    if api.format != "wsdl":
        return frozenset()
    issues = api.extras.get("wsdl_wsi_issues") or []
    return frozenset(str(issue.get("rule")) for issue in issues if isinstance(issue, dict) and issue.get("rule"))


def validate_wsdl_bundle(
    files: Mapping[str, str], *, inherited_rules: Collection[str] = ()
) -> List[WsdlBundleProblem]:
    """Validate an emitted WSDL bundle as it will be delivered and unpacked.

    Args:
        files: Every emitted member's text keyed by its bundle-relative path (``Pets.wsdl``,
            ``Pets.xsd``). A ``single``-layout export is a one-member bundle.
        inherited_rules: WS-I rules the source already broke (:func:`inherited_wsi_rules`); issues
            of these rules are not reported.

    Returns:
        The problems found, in check order; empty when the bundle is valid.
    """
    roots: Dict[str, ET.Element] = {}
    problems: List[WsdlBundleProblem] = []
    for path, text in files.items():
        try:
            roots[path] = parse_xml(text, source_label=path)
        except SecureXmlError as exc:
            problems.append(WsdlBundleProblem("wsdl.xml", f"Not well-formed, safe XML: {exc}", file=path))

    descriptions = [path for path, root in roots.items() if root.tag in _ROOT_VERSIONS]
    if len(descriptions) != 1 and not problems:
        found = ", ".join(sorted(descriptions)) or "none"
        problems.append(
            WsdlBundleProblem(
                "wsdl.bundle-root",
                f"A WSDL bundle carries exactly one WSDL description; found {found}.",
            )
        )
    for path, root in roots.items():
        problems.extend(bundle_reference_problems(path, root, files))
    if problems:
        return problems

    root_path = descriptions[0]
    version = _ROOT_VERSIONS[roots[root_path].tag]
    problems.extend(
        problem for problem in _wsi_problems(root_path, version, files) if problem.rule not in inherited_rules
    )
    if version == VERSION_1_1:
        problems.extend(_structure_problems(root_path, roots[root_path], files))
    if not any(problem.rule == "wsdl.structure" for problem in problems):
        problems.extend(_reimport_problems(root_path, files))
    return problems


def bundle_reference_problems(
    path: str, root: ET.Element, files: Mapping[str, str], *, rule: str = "wsdl.bundle-reference"
) -> List[WsdlBundleProblem]:
    """The imports and includes in ``path`` that do not resolve to another member of the bundle.

    A location resolves relative to the directory of the member that declares it, the way a SOAP
    toolkit reads the unpacked zip. An ``xs:import`` with no ``schemaLocation`` names a namespace,
    not a file, and is left to the WS-I and structure checks. Shared with the standalone XSD export
    check (:mod:`app.xsd_roundtrip`, MFX-22.5), which passes its own ``rule``.

    Args:
        path: The member's bundle path.
        root: Its parsed root element.
        files: Every member, path → text.
        rule: The rule the problems are reported under.

    Returns:
        One problem per unresolved reference.
    """
    problems: List[WsdlBundleProblem] = []
    base = posixpath.dirname(path)
    for namespace, local_name, attribute in _REFERENCES:
        for element in root.iter(f"{{{namespace}}}{local_name}"):
            location = element.get(attribute)
            if location is None:
                continue
            resolved = _resolve(base, location)
            if resolved is None or resolved not in files:
                problems.append(
                    WsdlBundleProblem(
                        rule,
                        f"{local_name} {attribute}={location!r} does not name a file in the bundle; "
                        "every imported description and schema must be packaged with it.",
                        file=path,
                        path=location,
                    )
                )
    return problems


def _resolve(base: str, location: str) -> Optional[str]:
    """``location`` as a bundle path relative to ``base``, or ``None`` for a URL or an escape."""
    if not location or "://" in location or location.startswith(("/", "\\")) or ":" in location.split("/")[0]:
        return None
    resolved = posixpath.normpath(posixpath.join(base, location))
    if resolved == ".." or resolved.startswith("../"):
        return None
    return resolved


def _wsi_problems(root_path: str, version: str, files: Mapping[str, str]) -> List[WsdlBundleProblem]:
    """The WS-I Basic Profile issues of the description (every one, not only the first page)."""
    issues, total = check_wsi(files[root_path], version=version, members=files, source_label=root_path)
    problems = [
        WsdlBundleProblem(issue.rule, issue.message, file=root_path, path=issue.path) for issue in issues
    ]
    if total > len(issues):
        problems.append(
            WsdlBundleProblem("wsi.truncated", f"{total - len(issues)} more WS-I issues not listed.", file=root_path)
        )
    return problems


def _structure_problems(root_path: str, root: ET.Element, files: Mapping[str, str]) -> List[WsdlBundleProblem]:
    """Read the unpacked bundle with ``xmlschema``'s WSDL 1.1 reader (schemas and references)."""
    for path in files:
        if safe_bundle_path(path) != path:
            return [WsdlBundleProblem("wsdl.bundle-reference", f"Unsafe bundle path {path!r}.", file=path)]
    reader = _GenericBindingWsdl11Document if _mixes_bindings(root) else Wsdl11Document
    with tempfile.TemporaryDirectory(prefix="wsdl-bundle-") as folder:
        for path, text in files.items():
            target = Path(folder, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        try:
            reader(str(Path(folder, root_path)), allow="sandbox")
        except Exception as exc:  # noqa: BLE001 — any reader failure means "not a valid description"
            file = reader_file(exc, folder, root_path)
            return [WsdlBundleProblem("wsdl.structure", reader_message(exc, folder), file=file)]
    return []


def _mixes_bindings(root: ET.Element) -> bool:
    """Whether a description has a binding that is not SOAP 1.1 (see :class:`_GenericBindingWsdl11Document`)."""
    for binding in root.iter(f"{{{WSDL_1_1_NAMESPACE}}}binding"):
        if binding.find(f"{{{_SOAP11_NS}}}binding") is None:
            return True
    return False


def reader_message(exc: Exception, folder: str) -> str:
    """The reader's error as one line: its reason (or first line), without the temporary folder."""
    message = str(getattr(exc, "message", "") or "") or str(exc).strip().splitlines()[0]
    reason = getattr(exc, "reason", None)
    text = f"{message}: {reason}" if reason and str(reason) not in message else message
    return text.replace(Path(folder).as_uri() + "/", "").replace(folder + "/", "")


def reader_file(exc: Exception, folder: str, root_path: str) -> str:
    """The bundle member the reader's error is in (the schema URL it names), else the root document.

    ``xmlschema`` names the failing schema document in ``schema_url`` (a parse error) or ``url``.
    """
    url = getattr(exc, "schema_url", None) or getattr(exc, "url", None) or ""
    prefix = Path(folder).as_uri() + "/"
    return url[len(prefix):] if isinstance(url, str) and url.startswith(prefix) else root_path


def _reimport_problems(root_path: str, files: Mapping[str, str]) -> List[WsdlBundleProblem]:
    """Import the bundle the way an upload would; a failure is a problem."""
    source = WsdlImportSource()
    try:
        fileset = IntakeFileset.from_members(dict(files), root=root_path)
        source.normalize(source.parse_fileset(fileset, source_label=root_path), include_raw=False)
    except (ImportSourceError, ValueError) as exc:
        return [WsdlBundleProblem("wsdl.reimport", f"The bundle does not import: {exc}", file=root_path)]
    return []
