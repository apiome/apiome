"""Validation of emitted WADL descriptions — MFX-29.3 (#4175).

The WADL export (MFX-29.1) is checked before delivery through the export validator seam (target ``wadl``,
:mod:`app.export_validation`), as it will be unpacked — the ``.wadl`` description and, in the default
``bundle`` layout, its ``.xsd`` grammar. Every problem has its rule (``keyword``), file and location:

1. **XML** (``wadl.xml``) — every file is well-formed, safe XML (no DTD, no entities); and a safe path
   (``wadl.bundle-reference``).
2. **The WADL schema** (``wadl.schema``) — the description validates against the W3C WADL submission schema
   (``http://wadl.dev.java.net/2009/02``, vendored as ``data/wadl_2009_02.xsd``).
3. **The grammar** — every ``<grammars><include href>`` names a file of the export
   (``wadl.bundle-reference``), and each grammar (an included ``.xsd`` or a schema inline in ``<grammars>``)
   is built by an XML Schema 1.0 processor (``wadl.grammar``).
4. **Representations** (``wadl.representation``) — every ``representation/@element`` is a QName whose prefix
   is declared and which names a global element of the grammar.
5. **Re-import** (``wadl.reimport``) — Apiome's WADL importer reads the export back.
"""

from __future__ import annotations

import io
import posixpath
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import xmlschema

from .emitter import EmitResult
from .import_source import ImportSourceError
from .secure_xml import SecureXmlError, parse_xml
from .wsdl_bundle_validation import reader_file, reader_message
from .zip_bundle import safe_bundle_path

__all__ = ["WadlProblem", "check_emitted_wadl", "wadl_schema"]

_WADL_NS = "http://wadl.dev.java.net/2009/02"
_XSD_NS = "http://www.w3.org/2001/XMLSchema"


@dataclass(frozen=True)
class WadlProblem:
    """One broken rule: its ``rule`` (``wadl.<name>``), a message, the file and the location in it."""

    rule: str
    message: str
    file: str = ""
    path: str = ""


@lru_cache(maxsize=1)
def wadl_schema() -> xmlschema.XMLSchema10:
    """The W3C WADL submission schema, as shipped in ``app/data`` (its ``xml.xsd`` import is xmlschema's own)."""
    path = resources.files("app").joinpath("data/wadl_2009_02.xsd")
    with resources.as_file(path) as local:
        return xmlschema.XMLSchema10(str(local), allow="local")


def check_emitted_wadl(emit_result: EmitResult, *, reimport: bool = True) -> List[WadlProblem]:
    """Every rule a WADL export breaks; ``[]`` when it is valid.

    Args:
        emit_result: The WADL emitter's output: one ``.wadl`` file, and its ``.xsd`` grammar in a bundle.
        reimport: Also read the export back through the WADL importer (``wadl.reimport``).

    Returns:
        The problems, in check order. Later checks are skipped when the XML or the WADL schema fails.
    """
    files = {emitted.path: str(emitted.content) for emitted in emit_result.files}
    descriptions = [path for path in files if path.endswith(".wadl")]
    if len(descriptions) != 1:
        return [WadlProblem("wadl.bundle-reference", f"The export must hold one .wadl file, not {len(descriptions)}.")]
    main = descriptions[0]
    problems: List[WadlProblem] = []
    roots: Dict[str, ET.Element] = {}
    for path, text in files.items():
        if safe_bundle_path(path) != path:
            problems.append(WadlProblem("wadl.bundle-reference", f"Unsafe file path {path!r}.", path))
            continue
        try:
            roots[path] = parse_xml(text, source_label=path)
        except SecureXmlError as exc:
            problems.append(WadlProblem("wadl.xml", f"Not well-formed, safe XML: {exc}", path))
    if problems:
        return problems

    problems += [
        WadlProblem("wadl.schema", error.reason or error.message, main, error.path or "")
        # The text, not the parsed tree: QName values (`type="xsd:string"`) need the prefixes the tree drops.
        for error in wadl_schema().iter_errors(xmlschema.XMLResource(files[main], defuse="always", allow="none"))
    ]
    if problems:
        return problems

    grammar = _grammar(main, roots[main], files, problems)
    if grammar is not None:
        problems += _representation_problems(main, files[main], roots[main], grammar)
    if not problems and reimport:
        problems += _reimport_problems(emit_result)
    return problems


def _grammar(main: str, root: ET.Element, files: Mapping[str, str],
             problems: List[WadlProblem]) -> Optional[Dict[str, bool]]:
    """Build every grammar of the description; the global elements it declares (``{ns}name`` → True).

    Returns ``None`` (with the problems recorded) when a grammar is missing or does not build.
    """
    grammars = root.find(f"{{{_WADL_NS}}}grammars")
    if grammars is None:
        return {}
    sources: List[Tuple[str, str]] = []  # (bundle path, schema text)
    for include in grammars.findall(f"{{{_WADL_NS}}}include"):
        href = include.get("href") or ""
        target = posixpath.normpath(posixpath.join(posixpath.dirname(main), href))
        if target not in files:
            problems.append(WadlProblem("wadl.bundle-reference", f"<grammars><include href={href!r}> names no file "
                                        "of the export.", main, "/application/grammars/include"))
        else:
            sources.append((target, files[target]))
    for index, schema in enumerate(grammars.findall(f"{{{_XSD_NS}}}schema")):
        # An inline grammar keeps the namespace declarations of the description it is in.
        sources.append((f"{main}#grammar{index}", _inline_schema_text(files[main], index)))
    if problems:
        return None
    elements: Dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="wadl-export-") as folder:
        for path, text in files.items():
            target = Path(folder, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for index, (path, text) in enumerate(sources):
            location = Path(folder, path) if "#" not in path else Path(folder, f"inline-grammar-{index}.xsd")
            if "#" in path:
                location.write_text(text, encoding="utf-8")
            try:
                schema = xmlschema.XMLSchema10(str(location), allow="sandbox")
            except Exception as exc:  # noqa: BLE001 — any processor failure means "not a valid grammar"
                problems.append(WadlProblem("wadl.grammar", reader_message(exc, folder),
                                            path.split("#")[0] if "#" in path else reader_file(exc, folder, path)))
                continue
            elements.update({name: True for name in schema.maps.elements})
    return None if problems else elements


def _inline_schema_text(text: str, index: int) -> str:
    """The ``index``-th ``xsd:schema`` inline in the description, with every namespace declared in scope."""
    namespaces: Dict[str, str] = {}
    for _event, (prefix, uri) in ET.iterparse(io.StringIO(text), events=("start-ns",)):
        namespaces.setdefault(prefix, uri)
    root = ET.fromstring(text)
    schema = root.find(f"{{{_WADL_NS}}}grammars").findall(f"{{{_XSD_NS}}}schema")[index]
    for prefix, uri in namespaces.items():
        ET.register_namespace(prefix, uri)
    body = ET.tostring(schema, encoding="unicode")
    # QName values (`type="tns:Pet"`) need their prefixes declared on the schema itself.
    declared = " ".join(f'xmlns:{p}="{u}"' for p, u in namespaces.items() if p and f'xmlns:{p}="' not in body)
    return body.replace(">", f" {declared}>", 1) if declared else body


def _representation_problems(main: str, text: str, root: ET.Element,
                             elements: Mapping[str, bool]) -> List[WadlProblem]:
    """Each ``representation/@element`` that is not a declared global element of the grammar."""
    namespaces: Dict[str, str] = {}
    for _event, (prefix, uri) in ET.iterparse(io.StringIO(text), events=("start-ns",)):
        namespaces.setdefault(prefix, uri)
    problems: List[WadlProblem] = []
    for representation in root.iter(f"{{{_WADL_NS}}}representation"):
        qname = representation.get("element")
        if not qname:
            continue
        prefix, _, local = qname.rpartition(":")
        if prefix not in namespaces:
            problems.append(WadlProblem("wadl.representation", f"The representation element {qname!r} uses the "
                                        f"undeclared prefix {prefix!r}.", main))
        elif f"{{{namespaces[prefix]}}}{local}" not in elements:
            problems.append(WadlProblem("wadl.representation", f"The representation element {qname!r} is not a "
                                        "global element of the grammar.", main))
    return problems


def _reimport_problems(emit_result: EmitResult) -> List[WadlProblem]:
    """Read the export back the way an upload would; a failure is a problem."""
    from .roundtrip_matrix import reimport_emitted
    from .wadl_import_source import WadlImportSource

    try:
        reimport_emitted(WadlImportSource(), emit_result, multi_file=len(emit_result.files) > 1)
    except ImportSourceError as exc:
        return [WadlProblem("wadl.reimport", f"Apiome's WADL importer cannot read the export back: {exc}",
                            emit_result.files[0].path)]
    return []
