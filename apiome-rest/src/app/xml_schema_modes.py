"""RELAX NG and DTD output modes of the XSD emitter — MFX-22.3 (#4134).

Some XML tool chains (DocBook-era publishing, configuration formats) read RELAX NG or a DTD rather than
an XML Schema. The XSD emitter (:mod:`app.xsd_emitter`) offers both as output modes. Each mode is
written **from the XSD documents the export builds**, not from the model a second time, so the three
modes share one mapping of types to XML (element names, occurrence, unions as choices, maps as entry
lists) and cannot drift apart — the same arrangement as the JSON Type Definition mode of the JSON
Schema emitter (:func:`app.jsonschema_jtd.jtd_from_bundle`).

**RELAX NG** (:class:`RelaxNgWriter`) — one grammar, ``<Name>.rng`` (XML syntax) or ``<Name>.rnc``
(compact syntax, :func:`relaxng_compact`), with the XSD datatype library:

* every complex type is a ``define`` (its content: a group, a ``choice`` for a union, the base type's
  ``ref`` first for an extension), every named simple type a ``define`` of ``data`` / a ``choice`` of
  ``value`` s, every global element a ``define`` the ``start`` pattern chooses from;
* occurrence is ``optional`` / ``zeroOrMore`` / ``oneOrMore``; other bounds (``2..5``) cannot be stated
  and are widened (``occurrence-bounds``, ``APPROX``);
* facets are datatype ``param`` s (``minLength``, ``pattern``, ``minInclusive`` …) — RELAX NG keeps
  them all; what it cannot carry is an element's ``default`` (``default-dropped``), ``nillable``
  (a nullable value is just optional), and examples;
* namespaces are kept: the grammar's ``ns`` is the main namespace and an element of another carries
  its own ``ns``; descriptions are ``a:documentation`` (``##`` comments in the compact syntax).

**DTD** (:class:`DtdWriter`) — one ``<Name>.dtd``. A DTD has element names and content models only:

* a complex type's content is a content model (``(a, b?, c*)``, ``(a | b)``), a simple value
  ``(#PCDATA)``, an empty type ``EMPTY``, free-form content ``ANY``;
* **no datatypes and no facets**: every typed value is text, and each type, pattern, length, range and
  enumeration on element content is reported (``datatype-dropped``, ``facet-dropped``, ``DROP``);
* element names are global: two elements of one name with different content are declared once, as
  ``ANY`` (``element-merged``, ``APPROX``); attributes are ``CDATA`` (an enumeration of names stays an
  enumeration);
* no namespaces: each element of a namespace declares it as a ``#FIXED`` ``xmlns`` attribute, so an
  instance is valid with a default namespace and without prefixes (an info note).

Both writers record their losses in the export's :class:`~app.emitter.LossTracker`, filed by the
construct they concern (the writer's ``node_keys``), so the fidelity report
(:class:`app.xsd_emitter.XsdFidelityRulePack`) predicts exactly what each mode writes. The losses the
XSD writer recorded in XSD terms (``null-as-nillable``, ``example-as-annotation`` …) are restated for the
mode by :func:`restate_xsd_losses`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .emitter import Loss, LossKind, LossTracker
from .xsd_schema import XSD_NS, XSD_PREFIX, XsdSchemaWriter, comment_safe

__all__ = [
    "DTD_MODE",
    "RELAXNG_ANNOTATIONS_NS",
    "RELAXNG_COMPACT_MODE",
    "RELAXNG_MODE",
    "RELAXNG_NS",
    "XML_SCHEMA_DATATYPES",
    "DtdWriter",
    "RelaxNgWriter",
    "mode_label",
    "relaxng_compact",
    "restate_xsd_losses",
]

#: Output mode values of the XSD emitter's ``mode`` option (``"xsd"`` is the default).
RELAXNG_MODE = "relaxng"
RELAXNG_COMPACT_MODE = "relaxng-compact"
DTD_MODE = "dtd"

RELAXNG_NS = "http://relaxng.org/ns/structure/1.0"
RELAXNG_ANNOTATIONS_NS = "http://relaxng.org/ns/compatibility/annotations/1.0"
#: The XSD datatype library every RELAX NG export uses (``xsd:`` in the compact syntax).
XML_SCHEMA_DATATYPES = "http://www.w3.org/2001/XMLSchema-datatypes"

#: Facets a RELAX NG ``data`` pattern carries as ``param`` s (the XSD datatype library's parameters).
_RNG_PARAMS = (
    "length", "minLength", "maxLength", "pattern", "minInclusive", "maxInclusive", "minExclusive",
    "maxExclusive", "totalDigits", "fractionDigits",
)
#: Facets a DTD cannot state (every one of them).
_DTD_FACETS = _RNG_PARAMS + ("enumeration", "assertion")
#: XSD built-ins a DTD reads as plain text without losing anything.
_TEXT_TYPES = frozenset({"string", "normalizedString", "token", "anySimpleType"})
_ANY_ELEMENT = "any.element"
_ANY_CONTENT = "any.content"


def mode_label(mode: str) -> str:
    """The name of an output mode in report messages (``"RELAX NG"``, ``"DTD"``)."""
    return "DTD" if mode == DTD_MODE else "RELAX NG"


def _tag(node: ET.Element) -> str:
    """A node's tag as text (the XSD writer builds tags as :class:`xml.etree.ElementTree.QName`)."""
    tag = node.tag
    return tag.text if isinstance(tag, ET.QName) else str(tag)


def _xs(local: str) -> str:
    return f"{{{XSD_NS}}}{local}"


def _rng(local: str) -> str:
    return f"{{{RELAXNG_NS}}}{local}"


def _children(node: ET.Element, *locals_: str) -> List[ET.Element]:
    """``node``'s XSD children with one of the local names (all XSD children when none is given)."""
    tags = {_xs(name) for name in locals_}
    return [child for child in node if (not tags and _tag(child).startswith(f"{{{XSD_NS}}}")) or _tag(child) in tags]


def _documentation(node: ET.Element) -> Optional[str]:
    """The node's description: its first ``xs:documentation`` without a ``source`` (examples have one)."""
    for annotation in _children(node, "annotation"):
        for doc in _children(annotation, "documentation"):
            if not doc.get("source") and (doc.text or "").strip():
                return (doc.text or "").strip()
    return None


def _occurrence(node: ET.Element) -> Tuple[int, Optional[int]]:
    """``(minOccurs, maxOccurs)`` of an element (``None`` = unbounded)."""
    low = int(node.get("minOccurs", "1") or 1)
    high_text = node.get("maxOccurs", "1") or "1"
    return low, None if high_text == "unbounded" else int(high_text)


class _XsdIndex:
    """The export's XSD documents, indexed: named types by ``(namespace, name)``, references resolved."""

    def __init__(self, schema: XsdSchemaWriter, documents: Sequence[Tuple[Optional[str], ET.Element]]) -> None:
        self.schema = schema
        self.documents = list(documents)
        self.namespace_of_prefix = {prefix: namespace for namespace, prefix in schema.prefixes.items()}
        self.types: Dict[Tuple[Optional[str], str], ET.Element] = {}
        #: ``(namespace, name)`` of a named type → its type key in the model.
        self.type_keys: Dict[Tuple[Optional[str], str], str] = {}
        for key, name in schema.type_names.items():
            self.type_keys[(schema.type_namespaces.get(key), name)] = key
        for namespace, root in self.documents:
            for node in root:
                if _tag(node) in (_xs("complexType"), _xs("simpleType")) and node.get("name"):
                    self.types[(namespace, node.get("name") or "")] = node

    def resolve(self, qname: str, namespace: Optional[str]) -> Tuple[Optional[str], str]:
        """``(namespace, local)`` of a ``type`` / ``base`` reference; the XSD namespace for a built-in."""
        if ":" in qname:
            prefix, local = qname.split(":", 1)
            if prefix == XSD_PREFIX:
                return XSD_NS, local
            return self.namespace_of_prefix.get(prefix, namespace), local
        return namespace, qname

    def key_of(self, node: ET.Element, fallback: str) -> str:
        """The construct a node was written for (its field), else ``fallback`` (its type, or the root)."""
        return self.schema.node_keys.get(id(node), fallback)

    def global_elements(self) -> List[Tuple[Optional[str], ET.Element]]:
        """Every global ``xs:element``, in document order, with its namespace."""
        return [
            (namespace, node) for namespace, root in self.documents for node in root if _tag(node) == _xs("element")
        ]


def _occurrence_loss(
    losses: LossTracker, label: str, node: ET.Element, key: str, low: int, high: Optional[int]
) -> None:
    """Record a repeat count the target cannot state (anything but ``0..1``, ``0..*``, ``1..*``, ``1``)."""
    if (low, high) in ((0, 1), (1, 1), (0, None), (1, None)):
        return
    widened = "zero or more" if low == 0 else "one or more"
    shown = f"{low}..{'*' if high is None else high}"
    losses.record(
        LossKind.INFERRED, "occurrence-bounds",
        f"{label} has no repeat counts; {node.get('name')!r} ({shown}) of {key!r} is written as {widened}.",
        pointer=key,
    )


def _default_loss(losses: LossTracker, label: str, node: ET.Element, key: str) -> None:
    if node.get("default") is not None:
        losses.record(
            LossKind.NA, "default-dropped",
            f"{label} has no default value for element content; the default {node.get('default')!r} of {key!r} "
            "is not written.",
            pointer=key,
        )


# ---------------------------------------------------------------------------------------------------
# RELAX NG
# ---------------------------------------------------------------------------------------------------


class RelaxNgWriter:
    """Build one RELAX NG grammar (XML syntax) from the export's XSD documents (single use).

    Args:
        schema: The XSD writer that built the documents (its names, prefixes and ``node_keys``).
        documents: ``(namespace, xs:schema element)`` per document, the main one first.
        losses: Where what RELAX NG cannot carry is recorded.
        main_namespace: The grammar's default namespace (``None``: no namespace).
    """

    label = "RELAX NG"

    def __init__(
        self,
        schema: XsdSchemaWriter,
        documents: Sequence[Tuple[Optional[str], ET.Element]],
        losses: LossTracker,
        main_namespace: Optional[str],
    ) -> None:
        self._index = _XsdIndex(schema, documents)
        self._losses = losses
        self._main_namespace = main_namespace
        self._define_names: Dict[Tuple[Optional[str], str], str] = {}
        self._taken: set[str] = set()
        self._any_used = False
        #: Type key → what it became (``define Pet``).
        self.written: Dict[str, str] = {}

    def build(self) -> ET.Element:
        """The ``grammar`` element."""
        ET.register_namespace("", RELAXNG_NS)
        ET.register_namespace("a", RELAXNG_ANNOTATIONS_NS)
        grammar = ET.Element(_rng("grammar"), {"datatypeLibrary": XML_SCHEMA_DATATYPES})
        if self._main_namespace:
            grammar.set("ns", self._main_namespace)
        for type_id in self._index.types:
            self._define_name(type_id)
        roots = self._index.global_elements()
        start = ET.SubElement(grammar, _rng("start"))
        refs = start if len(roots) <= 1 else ET.SubElement(start, _rng("choice"))
        element_defines: List[Tuple[str, Optional[str], ET.Element]] = []
        for namespace, node in roots:
            name = self._claim(f"{node.get('name')}.element")
            ET.SubElement(refs, _rng("ref"), {"name": name})
            element_defines.append((name, namespace, node))
        if not roots:
            ET.SubElement(start, _rng("notAllowed"))
        for name, namespace, node in element_defines:
            define = ET.SubElement(grammar, _rng("define"), {"name": name})
            define.append(self._element(node, namespace, ROOT_KEY))
        for (namespace, type_name), node in self._index.types.items():
            key = self._index.type_keys.get((namespace, type_name), ROOT_KEY)
            define_name = self._define_names[(namespace, type_name)]
            define = ET.SubElement(grammar, _rng("define"), {"name": define_name})
            _document(define, _documentation(node))
            if _tag(node) == _xs("simpleType"):
                define.append(self._simple(node, namespace, key))
            else:
                for pattern in self._complex_content(node, namespace, key):
                    define.append(pattern)
                if len([child for child in define if _tag(child) != f"{{{RELAXNG_ANNOTATIONS_NS}}}documentation"]) == 0:
                    ET.SubElement(define, _rng("empty"))
            self.written[key] = f"define {define_name}"
        if self._any_used:
            self._append_any(grammar)
        return grammar

    # -- names ------------------------------------------------------------------------------------

    def _claim(self, name: str) -> str:
        candidate, suffix = name, 2
        while candidate in self._taken:
            candidate, suffix = f"{name}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate

    def _define_name(self, type_id: Tuple[Optional[str], str]) -> str:
        if type_id not in self._define_names:
            self._define_names[type_id] = self._claim(type_id[1])
        return self._define_names[type_id]

    # -- patterns ---------------------------------------------------------------------------------

    def _element(self, node: ET.Element, namespace: Optional[str], owner: str) -> ET.Element:
        """An ``xs:element`` (global or local) as an ``element`` pattern, without its occurrence."""
        key = self._index.key_of(node, owner)
        element = ET.Element(_rng("element"), {"name": node.get("name") or "item"})
        if (namespace or None) != (self._main_namespace or None):
            element.set("ns", namespace or "")
        _document(element, _documentation(node))
        _default_loss(self._losses, self.label, node, key)
        for pattern in self._element_content(node, namespace, key):
            element.append(pattern)
        return element

    def _element_content(self, node: ET.Element, namespace: Optional[str], key: str) -> List[ET.Element]:
        """What an element holds: its type's ``ref`` / ``data``, or its inline type."""
        if node.get("type"):
            return [self._type_ref(node.get("type") or "", namespace, key)]
        for inline in _children(node, "simpleType"):
            return [self._simple(inline, namespace, key)]
        for inline in _children(node, "complexType"):
            return self._complex_content(inline, namespace, key) or [ET.Element(_rng("empty"))]
        return [ET.Element(_rng("text"))]

    def _type_ref(self, qname: str, namespace: Optional[str], key: str) -> ET.Element:
        type_namespace, local = self._index.resolve(qname, namespace)
        if type_namespace == XSD_NS:
            if local == "anyType":
                self._any_used = True
                return ET.Element(_rng("ref"), {"name": _ANY_CONTENT})
            return ET.Element(_rng("data"), {"type": local})
        if (type_namespace, local) in self._define_names:
            return ET.Element(_rng("ref"), {"name": self._define_names[(type_namespace, local)]})
        self._losses.record(
            LossKind.INFERRED, "unmapped-type",
            f"{qname!r} is not a type of this export; {key!r} is written as text.", pointer=key,
        )
        return ET.Element(_rng("text"))

    def _simple(self, node: ET.Element, namespace: Optional[str], key: str) -> ET.Element:
        """A ``simpleType`` (its ``restriction``) as ``data`` with params, or a ``choice`` of values."""
        for restriction in _children(node, "restriction"):
            base_namespace, base = self._index.resolve(restriction.get("base") or "string", namespace)
            values = [facet.get("value") or "" for facet in _children(restriction, "enumeration")]
            if base_namespace != XSD_NS:
                return self._type_ref(restriction.get("base") or "", namespace, key)
            if values:
                choice = ET.Element(_rng("choice"))
                for value in values:
                    ET.SubElement(choice, _rng("value"), {"type": base}).text = value
                return choice
            data = ET.Element(_rng("data"), {"type": base})
            for facet in _children(restriction):
                local = _tag(facet).split("}", 1)[1]
                if local in _RNG_PARAMS:
                    ET.SubElement(data, _rng("param"), {"name": local}).text = facet.get("value") or ""
                elif local != "annotation":
                    self._losses.record(
                        LossKind.NA, "facet-dropped",
                        f"RELAX NG has no parameter for the {local} facet; it is not written for {key!r}.",
                        pointer=key,
                    )
            return data
        return ET.Element(_rng("text"))

    def _complex_content(self, node: ET.Element, namespace: Optional[str], key: str) -> List[ET.Element]:
        """A ``complexType``'s content: its particles, then its attributes."""
        patterns: List[ET.Element] = []
        for child in _children(node):
            local = _tag(child).split("}", 1)[1]
            if local in ("sequence", "choice"):
                patterns.extend(self._particle(child, namespace, key))
            elif local == "complexContent":
                for extension in _children(child, "extension"):
                    patterns.append(self._type_ref(extension.get("base") or "", namespace, key))
                    for particle in _children(extension, "sequence", "choice"):
                        patterns.extend(self._particle(particle, namespace, key))
            elif local == "attribute":
                patterns.append(self._attribute(child, namespace, key))
        return patterns

    def _particle(self, node: ET.Element, namespace: Optional[str], key: str) -> List[ET.Element]:
        """A ``sequence`` (its items, in order) or a ``choice`` (one ``choice`` pattern)."""
        items: List[ET.Element] = []
        for child in _children(node):
            local = _tag(child).split("}", 1)[1]
            if local == "element":
                low, high = _occurrence(child)
                child_key = self._index.key_of(child, key)
                _occurrence_loss(self._losses, self.label, child, child_key, low, high)
                items.append(_repeat(self._element(child, namespace, key), low, high))
            elif local == "any":
                self._any_used = True
                items.append(_repeat(ET.Element(_rng("ref"), {"name": _ANY_ELEMENT}), *_occurrence(child)))
            elif local in ("sequence", "choice"):
                items.extend(self._particle(child, namespace, key))
        if _tag(node) == _xs("choice"):
            if not items:
                return [ET.Element(_rng("notAllowed"))]
            choice = ET.Element(_rng("choice"))
            choice.extend(items)
            return [choice]
        return items

    def _attribute(self, node: ET.Element, namespace: Optional[str], owner: str) -> ET.Element:
        key = self._index.key_of(node, owner)
        attribute = ET.Element(_rng("attribute"), {"name": node.get("name") or "attribute"})
        attribute.append(self._type_ref(node.get("type") or f"{XSD_PREFIX}:string", namespace, key))
        if node.get("use") == "required":
            return attribute
        optional = ET.Element(_rng("optional"))
        optional.append(attribute)
        return optional

    def _append_any(self, grammar: ET.Element) -> None:
        """``any.element`` = any element with any attributes and content; ``any.content`` = its content."""
        content = ET.SubElement(grammar, _rng("define"), {"name": _ANY_CONTENT})
        repeat = ET.SubElement(ET.SubElement(content, _rng("zeroOrMore")), _rng("choice"))
        attribute = ET.SubElement(repeat, _rng("attribute"))
        ET.SubElement(attribute, _rng("anyName"))
        ET.SubElement(repeat, _rng("text"))
        ET.SubElement(repeat, _rng("ref"), {"name": _ANY_ELEMENT})
        element = ET.SubElement(ET.SubElement(grammar, _rng("define"), {"name": _ANY_ELEMENT}), _rng("element"))
        ET.SubElement(element, _rng("anyName"))
        ET.SubElement(element, _rng("ref"), {"name": _ANY_CONTENT})


#: Where losses about the whole document are filed.
ROOT_KEY = "$"


def _repeat(pattern: ET.Element, low: int, high: Optional[int]) -> ET.Element:
    """Wrap ``pattern`` for its occurrence: ``optional``, ``zeroOrMore``, ``oneOrMore`` or as is."""
    if high == 1:
        wrapper = "optional" if low == 0 else None
    else:
        wrapper = "zeroOrMore" if low == 0 else "oneOrMore"
    if wrapper is None:
        return pattern
    outer = ET.Element(_rng(wrapper))
    outer.append(pattern)
    return outer


def _document(node: ET.Element, text: Optional[str]) -> None:
    if text:
        ET.SubElement(node, f"{{{RELAXNG_ANNOTATIONS_NS}}}documentation").text = text


# ---------------------------------------------------------------------------------------------------
# RELAX NG compact syntax
# ---------------------------------------------------------------------------------------------------

_RNC_KEYWORDS = frozenset({
    "attribute", "default", "datatypes", "div", "element", "empty", "external", "grammar", "include",
    "inherit", "list", "mixed", "namespace", "notAllowed", "parent", "start", "string", "text", "token",
})


def relaxng_compact(grammar: ET.Element, *, header: Optional[str] = None) -> str:
    """The compact syntax (``.rnc``) of a grammar :class:`RelaxNgWriter` built.

    Args:
        grammar: The ``grammar`` element.
        header: A comment for the first line (``# …``), or ``None``.

    Returns:
        The compact-syntax text.
    """
    default_ns = grammar.get("ns")
    prefixes: Dict[str, str] = {}
    for node in grammar.iter(_rng("element")):
        namespace = node.get("ns")
        if namespace is not None and namespace != default_ns and namespace not in prefixes:
            prefixes[namespace] = f"ns{len(prefixes) + 1}"
    lines: List[str] = []
    if header:
        lines.append(f"# {header}")
    # ``xsd`` is predeclared by the compact syntax; declaring it too keeps stricter readers happy.
    lines.append(f"datatypes xsd = {_rnc_literal(XML_SCHEMA_DATATYPES)}")
    if default_ns:
        lines.append(f"default namespace = {_rnc_literal(default_ns)}")
    for namespace, prefix in prefixes.items():
        lines.append(f"namespace {prefix} = {_rnc_literal(namespace)}")
    if lines:
        lines.append("")
    writer = _RncWriter(prefixes)
    for child in grammar:
        if _tag(child) == _rng("start"):
            lines.append(f"start = {writer.group(child)}")
        elif _tag(child) == _rng("define"):
            for doc in _rnc_docs(child):
                lines.append(doc)
            lines.append(f"{_rnc_identifier(child.get('name') or '')} = {writer.group(child)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class _RncWriter:
    def __init__(self, prefixes: Dict[str, str]) -> None:
        self._prefixes = prefixes

    def group(self, node: ET.Element) -> str:
        """The patterns among ``node``'s children, as one pattern (a group when several)."""
        parts = [self.pattern(child) for child in _patterns(node)]
        if not parts:
            return "empty"
        return parts[0] if len(parts) == 1 else "(" + ", ".join(parts) + ")"

    def pattern(self, node: ET.Element) -> str:
        local = _tag(node).split("}", 1)[1]
        if local in ("optional", "zeroOrMore", "oneOrMore"):
            suffix = {"optional": "?", "zeroOrMore": "*", "oneOrMore": "+"}[local]
            inner = self.group(node)
            return f"{inner}{suffix}" if inner.startswith("(") or _is_primary(inner) else f"({inner}){suffix}"
        if local == "choice":
            parts = [self.pattern(child) for child in _patterns(node)]
            return "(" + " | ".join(parts) + ")" if len(parts) > 1 else (parts[0] if parts else "notAllowed")
        if local == "group":
            return self.group(node)
        if local == "element":
            return f"element {self._name(node)} {{ {self.group(node)} }}"
        if local == "attribute":
            content = self.group(node) if _patterns(node) else "text"
            return f"attribute {self._name(node, attribute=True)} {{ {content} }}"
        if local == "ref":
            return _rnc_identifier(node.get("name") or "")
        if local == "data":
            params = [
                f"{child.get('name')} = {_rnc_literal(child.text or '')}"
                for child in node
                if _tag(child) == _rng("param")
            ]
            base = f"xsd:{node.get('type')}"
            return f"{base} {{ {' '.join(params)} }}" if params else base
        if local == "value":
            return f"xsd:{node.get('type') or 'string'} {_rnc_literal(node.text or '')}"
        return {"text": "text", "empty": "empty", "notAllowed": "notAllowed"}.get(local, "text")

    def _name(self, node: ET.Element, *, attribute: bool = False) -> str:
        if any(_tag(child) == _rng("anyName") for child in node):
            return "*"
        name = node.get("name") or "item"
        namespace = node.get("ns")
        if not attribute and namespace is not None and namespace in self._prefixes:
            return f"{self._prefixes[namespace]}:{name}"
        return _rnc_identifier(name)


def _patterns(node: ET.Element) -> List[ET.Element]:
    """``node``'s pattern children (not names, params or annotations)."""
    skip = {_rng("anyName"), _rng("param"), f"{{{RELAXNG_ANNOTATIONS_NS}}}documentation"}
    return [child for child in node if _tag(child).startswith(f"{{{RELAXNG_NS}}}") and _tag(child) not in skip]


def _is_primary(text: str) -> bool:
    """Whether a pattern can take a ``?`` / ``*`` / ``+`` without parentheses."""
    return bool(re.fullmatch(r"[\\A-Za-z_][\w.\-:]*", text)) or text.startswith(("element ", "attribute "))


def _rnc_docs(node: ET.Element) -> List[str]:
    lines: List[str] = []
    for doc in node.findall(f"{{{RELAXNG_ANNOTATIONS_NS}}}documentation"):
        for line in (doc.text or "").splitlines() or [""]:
            lines.append(f"## {line}".rstrip())
    return lines


def _rnc_identifier(name: str) -> str:
    return f"\\{name}" if name in _RNC_KEYWORDS else name


def _rnc_literal(text: str) -> str:
    """A compact-syntax string literal that holds ``text`` exactly."""
    if '"' not in text and "\n" not in text:
        return f'"{text}"'
    if "'" not in text and "\n" not in text:
        return f"'{text}'"
    if '"""' not in text and not text.endswith('"'):
        return f'"""{text}"""'
    return " ~ ".join(f'"{part}"' if part != '"' else "'\"'" for part in re.split(r'(")', text) if part)


# ---------------------------------------------------------------------------------------------------
# DTD
# ---------------------------------------------------------------------------------------------------


class DtdWriter:
    """Build one DTD from the export's XSD documents (single use).

    Args:
        schema: The XSD writer that built the documents.
        documents: ``(namespace, xs:schema element)`` per document, the main one first.
        losses: Where what a DTD cannot carry is recorded.
    """

    label = "DTD"

    def __init__(
        self,
        schema: XsdSchemaWriter,
        documents: Sequence[Tuple[Optional[str], ET.Element]],
        losses: LossTracker,
    ) -> None:
        self._index = _XsdIndex(schema, documents)
        self._losses = losses
        #: Element name → (content model, namespace, the construct that declared it first, comment).
        self._declared: Dict[str, Tuple[str, Optional[str], str, Optional[str]]] = {}
        self._order: List[str] = []
        self._attributes: Dict[str, List[str]] = {}
        self._reported_types: set[str] = set()
        #: Type key → what it became (``element Pet``, ``text (#PCDATA)``).
        self.written: Dict[str, str] = {}

    def build(self, *, header: Optional[str] = None) -> str:
        """The DTD text."""
        roots = self._index.global_elements()
        for namespace, node in roots:
            self._declare(node, namespace, ROOT_KEY)
        for (namespace, name), node in self._index.types.items():
            key = self._index.type_keys.get((namespace, name))
            if key and key not in self.written:
                self.written[key] = "text (#PCDATA)" if _tag(node) == _xs("simpleType") else f"content of {name}"
            if _tag(node) == _xs("simpleType") and key:
                self._report_simple_type(node, namespace, key)
        if any(namespace for namespace, _ in self._index.documents):
            self._losses.record(
                LossKind.INFERRED, "namespace-as-fixed-xmlns",
                "A DTD has no namespaces; each element declares its namespace as a #FIXED xmlns attribute, so a "
                "document is valid with a default namespace and without prefixes.",
                pointer=ROOT_KEY,
            )
        lines: List[str] = []
        if header:
            lines.append(f"<!-- {comment_safe(header)} -->")
        if roots:
            lines.append(f"<!-- Root element: {roots[0][1].get('name')} -->")
        for name in self._order:
            content, namespace, _key, comment = self._declared[name]
            if comment:
                lines.append(f"<!-- {comment_safe(comment)} -->")
            lines.append(f"<!ELEMENT {name} {content}>")
            attributes = list(self._attributes.get(name, []))
            if namespace:
                attributes.insert(0, f"xmlns CDATA #FIXED {_dtd_literal(namespace)}")
            if attributes:
                lines.append(f"<!ATTLIST {name}")
                lines.extend(f"  {attribute}" for attribute in attributes)
                lines.append(">")
        return "\n".join(lines) + "\n"

    # -- declarations -----------------------------------------------------------------------------

    def _declare(self, node: ET.Element, namespace: Optional[str], owner: str) -> str:
        """Declare an element (and, first, every element its content uses); return its name."""
        name = node.get("name") or "item"
        key = self._index.key_of(node, owner)
        _default_loss(self._losses, self.label, node, key)
        if name in self._declared and self._declared[name][0] == "__pending__":
            return name  # recursion: the declaration in progress covers it
        content, attributes, type_comment = self._content_of(node, namespace, key, pending=name)
        comment = _documentation(node) or type_comment
        if name in self._declared:
            previous, _ns, first_key, first_comment = self._declared[name]
            if previous != content:
                for loss_key in dict.fromkeys((first_key, key)):
                    self._losses.record(
                        LossKind.INFERRED, "element-merged",
                        f"A DTD declares each element name once; {name!r} has different content in different "
                        f"places, so it is declared ANY ({loss_key!r}).",
                        pointer=loss_key,
                    )
                self._declared[name] = ("ANY", namespace, first_key, first_comment)
            return name
        self._declared[name] = (content, namespace, key, comment)
        if attributes:
            self._attributes[name] = attributes
        return name

    def _content_of(
        self, node: ET.Element, namespace: Optional[str], key: str, *, pending: str
    ) -> Tuple[str, List[str], Optional[str]]:
        """``(content model, ATTLIST lines, the type's description)`` of one element declaration."""
        if pending not in self._declared:
            self._declared[pending] = ("__pending__", namespace, key, None)
            self._order.append(pending)
        try:
            if node.get("type"):
                type_namespace, local = self._index.resolve(node.get("type") or "", namespace)
                if type_namespace == XSD_NS:
                    if local == "anyType":
                        return "ANY", [], None
                    self._report_builtin(local, key)
                    return "(#PCDATA)", [], None
                type_node = self._index.types.get((type_namespace, local))
                if type_node is None:
                    return "(#PCDATA)", [], None
                if _tag(type_node) == _xs("simpleType"):
                    return "(#PCDATA)", [], None
                model, attributes = self._complex(type_node, type_namespace, self._type_key(type_namespace, local, key))
                return model, attributes, _documentation(type_node)
            for inline in _children(node, "simpleType"):
                self._report_simple_type(inline, namespace, key)
                return "(#PCDATA)", [], None
            for inline in _children(node, "complexType"):
                model, attributes = self._complex(inline, namespace, key)
                return model, attributes, None
            return "(#PCDATA)", [], None
        finally:
            if self._declared.get(pending, ("",))[0] == "__pending__":
                del self._declared[pending]

    def _type_key(self, namespace: Optional[str], name: str, fallback: str) -> str:
        return self._index.type_keys.get((namespace, name), fallback)

    def _complex(self, node: ET.Element, namespace: Optional[str], key: str) -> Tuple[str, List[str]]:
        """A ``complexType`` as a content model and its attributes."""
        items: List[str] = []
        attributes: List[str] = []
        any_content = False
        choice_model = False
        for child in _children(node):
            local = _tag(child).split("}", 1)[1]
            if local in ("sequence", "choice"):
                part, has_any = self._particle(child, namespace, key)
                any_content = any_content or has_any
                if part:
                    items.append(part)
                    choice_model = choice_model or local == "choice"
            elif local == "complexContent":
                for extension in _children(child, "extension"):
                    base_namespace, base = self._index.resolve(extension.get("base") or "", namespace)
                    base_node = self._index.types.get((base_namespace, base))
                    if base_node is not None:
                        base_model, base_attributes = self._complex(base_node, base_namespace, key)
                        if base_model not in ("EMPTY", "ANY"):
                            items.append(base_model)
                        attributes.extend(base_attributes)
                        any_content = any_content or base_model == "ANY"
                    for particle in _children(extension, "sequence", "choice"):
                        part, has_any = self._particle(particle, namespace, key)
                        any_content = any_content or has_any
                        if part:
                            items.append(part)
            elif local == "attribute":
                attributes.append(self._attribute(child, namespace, key))
        if any_content:
            return "ANY", attributes
        if not items:
            return "EMPTY", attributes
        if len(items) == 1:
            return (items[0] if items[0].startswith("(") else f"({items[0]})"), attributes
        return "(" + ", ".join(items) + ")", attributes

    def _particle(self, node: ET.Element, namespace: Optional[str], key: str) -> Tuple[str, bool]:
        """A ``sequence`` / ``choice`` as a content particle, and whether it allows any element."""
        parts: List[str] = []
        has_any = False
        for child in _children(node):
            local = _tag(child).split("}", 1)[1]
            if local == "element":
                low, high = _occurrence(child)
                child_key = self._index.key_of(child, key)
                _occurrence_loss(self._losses, self.label, child, child_key, low, high)
                name = self._declare(child, namespace, key)
                parts.append(name + _dtd_suffix(low, high))
            elif local == "any":
                has_any = True
            elif local in ("sequence", "choice"):
                part, nested_any = self._particle(child, namespace, key)
                has_any = has_any or nested_any
                if part:
                    parts.append(part)
        if not parts:
            return "", has_any
        separator = " | " if _tag(node) == _xs("choice") else ", "
        return "(" + separator.join(parts) + ")", has_any

    def _attribute(self, node: ET.Element, namespace: Optional[str], owner: str) -> str:
        key = self._index.key_of(node, owner)
        name = node.get("name") or "attribute"
        required = "#REQUIRED" if node.get("use") == "required" else "#IMPLIED"
        type_namespace, local = self._index.resolve(node.get("type") or f"{XSD_PREFIX}:string", namespace)
        type_node = self._index.types.get((type_namespace, local))
        if type_node is not None:
            values = [
                facet.get("value") or ""
                for restriction in _children(type_node, "restriction")
                for facet in _children(restriction, "enumeration")
            ]
            if values and all(re.fullmatch(r"[\w.\-:]+", value) for value in values):
                return f"{name} ({'|'.join(values)}) {required}"
        elif type_namespace == XSD_NS:
            self._report_builtin(local, key)
        return f"{name} CDATA {required}"

    # -- losses -----------------------------------------------------------------------------------

    def _report_builtin(self, builtin: str, key: str) -> None:
        if builtin not in _TEXT_TYPES:
            self._losses.record(
                LossKind.NA, "datatype-dropped",
                f"A DTD has no datatypes; {key!r} ({builtin}) is written as text, so any text is valid.",
                pointer=key,
            )

    def _report_simple_type(self, node: ET.Element, namespace: Optional[str], key: str) -> None:
        """Report a simple type's datatype and facets once per construct."""
        if key in self._reported_types:
            return
        self._reported_types.add(key)
        for restriction in _children(node, "restriction"):
            base_namespace, base = self._index.resolve(restriction.get("base") or "string", namespace)
            locals_ = (_tag(facet).split("}", 1)[1] for facet in _children(restriction))
            facets = sorted({local for local in locals_ if local in _DTD_FACETS})
            if facets:
                self._losses.record(
                    LossKind.NA, "facet-dropped",
                    f"A DTD cannot constrain element text; the {', '.join(facets)} rule(s) of {key!r} are not written.",
                    pointer=key,
                )
            if base_namespace == XSD_NS:
                self._report_builtin(base, key)


def _dtd_suffix(low: int, high: Optional[int]) -> str:
    if high == 1:
        return "?" if low == 0 else ""
    return "*" if low == 0 else "+"


def _dtd_literal(text: str) -> str:
    return f'"{text}"' if '"' not in text else f"'{text}'"


# ---------------------------------------------------------------------------------------------------
# The XSD writer's losses, restated for a mode
# ---------------------------------------------------------------------------------------------------

#: XSD vocabulary in the shared writer's loss messages → how the other modes say it.
_RELABEL = (
    ("an xs:choice", "a choice"),
    ("xs:choice", "choice"),
    ("xs:anyType", "any content"),
    ("xs:any", "any element"),
    ("xs:string", "text"),
    ("XSD element names", "XML element names"),
    ("XSD attribute names", "XML attribute names"),
    ("XSD type names", "XML type names"),
    ("XSD has no", "{label} has no"),
    ("an XSD type", "a {label} type"),
    ("XSD", "{label}"),
)


def restate_xsd_losses(losses: LossTracker, mode: str) -> LossTracker:
    """The XSD writer's losses in the mode's terms (a new tracker; the original is not changed).

    ``null-as-nillable`` becomes ``null-as-optional`` (neither mode has ``xsi:nil``), an example kept as
    ``xs:documentation`` becomes a dropped example, a DTD drops the facet notes the DTD writer restates
    per construct, and every other message names the mode instead of XSD.

    Args:
        losses: The tracker the XSD writer recorded into (before the mode's writer ran).
        mode: ``"relaxng"``, ``"relaxng-compact"`` or ``"dtd"``.

    Returns:
        A tracker holding the restated losses.
    """
    label = mode_label(mode)
    restated = LossTracker()
    for loss in losses.records():
        subject, kind, detail = loss.subject, loss.kind, loss.detail
        if subject == "null-as-nillable":
            subject = "null-as-optional"
            detail = (
                f"{label} has no null; {loss.pointer!r} is written optional, so a null value and an absent one "
                "read the same."
            )
        elif subject == "example-as-annotation":
            subject, kind = "example-dropped", LossKind.NA
            detail = f"{label} has no examples; the example(s) of {loss.pointer!r} are not written."
        elif subject == "unsupported-facet" and mode == DTD_MODE:
            continue  # the DTD writer reports every facet of the construct itself
        else:
            for old, new in _RELABEL:
                detail = detail.replace(old, new.format(label=label))
        restated.record(kind, subject, detail, pointer=loss.pointer)
    return restated


def merge_losses(target: LossTracker, extra: Iterable[Loss]) -> None:
    """Append ``extra`` to ``target`` (the mode writer's own losses after the restated XSD ones)."""
    for loss in extra:
        target.record(loss.kind, loss.subject, loss.detail, pointer=loss.pointer)
