"""The compatibility rule catalogue — every rule id XPC-4.1–4.4 emit (XPC-4.5, #5749).

One machine-readable table, served at ``GET /v1/compatibility/rules`` and rendered into the
Compatibility modes docs page by ``scripts/generate_compatibility_rule_catalogue.py``, so CDG-4's
subject API, the docs and the UI all show the same rules with the same severities.

Each entry gives the rule id, the formats that emit it, the **direction** it breaks, its severity
under each compatibility mode (or, for Protobuf, under each buf breaking category) and a one-line
description. Severities are derived from the same grade tables the classifiers use, not restated:

* JSON Schema and Avro rules break a **direction** — ``backward`` (the new schema rejects old
  data) or ``forward`` (the old schema rejects new data). A rule is breaking under the modes that
  check its direction and dangerous otherwise; ``review`` rules are dangerous under every mode. Avro
  rule ids do not carry a direction (the same incompatibility can be found either way), so they are
  listed ``either`` with their worst case per mode.
* AsyncAPI rules carry a **consumer** and a **producer** grade; a mode reads the side it checks
  and drops the other one tier (:func:`app.asyncapi_compatibility_rules.severity_under`).
* Protobuf rules carry a grade per **category** (:mod:`app.proto_breaking_rules`); compatibility
  modes do not apply to them, so their ``severities`` are ``None``.
* ``NONE`` turns checking off: a break is reported dangerous.

Rule ids built from a tool's own rule names (``protobuf.buf-breaking.<buf rule>``) are listed once as
a **family** whose ``rule_id`` is the prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .asyncapi_compatibility_rules import severity_under
from .asyncapi_payload_compatibility import SideFinding, side_rule_id
from .breaking_change import Severity
from .compatibility_policy import COMPATIBILITY_MODES, MODE_NONE, PROTOBUF_CATEGORIES
from .jsonschema_compatibility import _EXACT_CONSTRAINTS, _LOWER_BOUNDS, _UPPER_BOUNDS, mode_directions
from .proto_breaking_rules import (
    _ALL_BREAKING,
    _ALL_DANGEROUS,
    _FILE_BREAKING,
    _JSON_BREAKING,
    _SOURCE_BREAKING,
    COMPATIBLE_RULE_ID,
    category_rule_id,
)

__all__ = [
    "CatalogueEntry",
    "FORMAT_FAMILIES",
    "catalogue",
    "entries_for_format",
    "find_entry",
    "CATALOGUE_DOC_END",
    "CATALOGUE_DOC_START",
    "render_catalogue_markdown",
    "replace_catalogue_section",
]

#: Format family → the format keys that belong to it (a request's ``?format=`` may name either).
FORMAT_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "avro": ("avro",),
    "json-schema": ("json-schema", "jsonschema", "json-schema-2020-12"),
    "protobuf": ("protobuf",),
    "asyncapi": ("asyncapi-2", "asyncapi-3"),
}

_ASYNCAPI = FORMAT_FAMILIES["asyncapi"]
_S, _D, _B = Severity.SAFE, Severity.DANGEROUS, Severity.BREAKING


@dataclass(frozen=True)
class CatalogueEntry:
    """One rule in the catalogue.

    Attributes:
        rule_id: The rule id, or for a family the prefix every id in it starts with.
        family: The format family (``avro`` / ``json-schema`` / ``protobuf`` / ``asyncapi``).
        formats: Every format key whose comparisons can emit the rule (AsyncAPI payloads reuse the
            JSON Schema, Avro and Protobuf rules).
        direction: ``backward`` / ``forward`` / ``either`` / ``review`` for data-schema rules;
            ``consumer`` / ``producer`` / ``both`` for AsyncAPI; ``None`` for Protobuf.
        severities: Severity under each mode in :data:`COMPATIBILITY_MODES`, or ``None`` when modes
            do not apply (Protobuf).
        category: Protobuf only: the least strict category where the rule is at its worst.
        category_severities: Protobuf only: severity under each buf breaking category.
        description: What change the rule reports.
        is_family: Whether ``rule_id`` is a prefix (ids built from a tool's own rule names).
    """

    rule_id: str
    family: str
    formats: Tuple[str, ...]
    direction: Optional[str]
    severities: Optional[Dict[str, str]]
    description: str
    category: Optional[str] = None
    category_severities: Optional[Dict[str, str]] = None
    is_family: bool = False

    def matches(self, rule_id: str) -> bool:
        """Whether ``rule_id`` is this entry's id, or starts with it for a family."""
        if self.is_family:
            return rule_id.startswith(self.rule_id)
        return rule_id == self.rule_id


def _none_grade(backward: Severity) -> Severity:
    """``NONE`` reports what ``BACKWARD`` would, with breaks lowered to dangerous."""
    return _D if backward is _B else backward


def _direction_severities(directions: Sequence[str]) -> Dict[str, str]:
    """Severity per mode for a rule found in ``directions`` (``review`` is dangerous everywhere)."""
    out: Dict[str, str] = {}
    for mode in COMPATIBILITY_MODES:
        if mode == MODE_NONE:
            continue
        checked = mode_directions(mode)
        out[mode] = (_B if any(d in checked for d in directions) else _D).value
    out[MODE_NONE] = _none_grade(Severity(out["BACKWARD"])).value
    return out


def _side_severities(consumer: Severity, producer: Severity) -> Dict[str, str]:
    """Severity per mode for an AsyncAPI rule with per-side grades."""
    finding = SideFinding("", consumer, producer, "")
    out = {mode: severity_under(finding, mode).value for mode in COMPATIBILITY_MODES if mode != MODE_NONE}
    out[MODE_NONE] = _none_grade(Severity(out["BACKWARD"])).value
    return out


def _jsonschema_entries() -> List[CatalogueEntry]:
    """Every ``jsonschema.<direction>.<rule>`` id :mod:`app.jsonschema_compatibility` emits."""
    formats = FORMAT_FAMILIES["json-schema"] + _ASYNCAPI
    rows: List[Tuple[str, str, str]] = [
        ("backward", "closed-property-removed", "A property removed from a closed content model."),
        ("backward", "open-property-added", "A property added to an open content model."),
        ("backward", "additional-properties-closed", "additionalProperties turned from open to closed."),
        ("backward", "required-added", "A property became required."),
        ("backward", "enum-narrowed", "An enum or const value removed, or an enum added."),
        ("backward", "type-narrowed", "A type narrowed, such as number to integer."),
        ("backward", "type-changed", "A type replaced by an unrelated one, such as integer to string."),
        ("backward", "one-of-branch-removed", "A oneOf branch removed."),
        ("backward", "any-of-branch-removed", "An anyOf branch removed."),
        ("backward", "unique-items-tightened", "uniqueItems turned on."),
        ("backward", "schema-rejects-all", "The schema became false and now rejects every value."),
        ("forward", "closed-property-added", "A property added to a closed content model."),
        ("forward", "open-property-removed", "A property removed from an open content model."),
        ("forward", "additional-properties-opened", "additionalProperties turned from closed to open."),
        ("forward", "required-removed", "A property is no longer required."),
        ("forward", "enum-widened", "An enum value added, or the enum removed."),
        ("forward", "type-widened", "A type widened, such as integer to number or null allowed."),
        ("forward", "type-changed", "A type replaced by an unrelated one, such as integer to string."),
        ("forward", "one-of-branch-added", "A oneOf branch added."),
        ("forward", "any-of-branch-added", "An anyOf branch added."),
        ("forward", "unique-items-loosened", "uniqueItems turned off."),
        ("forward", "schema-accepts-values", "The schema stopped being false and now accepts values."),
        ("review", "unmodeled-keyword-changed", "A keyword the check does not model changed, such as not or if."),
        ("review", "ref-changed", "A $ref that points outside the document changed."),
    ]
    for keyword, slug in {**_UPPER_BOUNDS, **_LOWER_BOUNDS}.items():
        rows.append(("backward", f"{slug}-tightened", f"The {keyword} bound tightened or added."))
        rows.append(("forward", f"{slug}-loosened", f"The {keyword} bound loosened or removed."))
    for keyword, slug in _EXACT_CONSTRAINTS.items():
        rows.append(("backward", f"{slug}-tightened", f"A {keyword} added."))
        rows.append(("forward", f"{slug}-loosened", f"A {keyword} removed."))
        rows.append(("backward", f"{slug}-changed", f"A {keyword} replaced by another."))
        rows.append(("forward", f"{slug}-changed", f"A {keyword} replaced by another."))
    entries = [
        CatalogueEntry(
            rule_id=f"jsonschema.{direction}.{slug}",
            family="json-schema",
            formats=formats,
            direction=direction,
            severities=_direction_severities([direction]),
            description=description,
        )
        for direction, slug, description in rows
    ]
    entries.append(
        CatalogueEntry(
            rule_id="jsonschema.compatible",
            family="json-schema",
            formats=FORMAT_FAMILIES["json-schema"],
            direction=None,
            severities={mode: _S.value for mode in COMPATIBILITY_MODES},
            description="The JSON Schema check accepts the change both ways (FULL compatible).",
        )
    )
    return entries


def _avro_entries() -> List[CatalogueEntry]:
    """Every ``avro-compatibility.*`` id: one per Avro incompatibility type, plus ``compatible``."""
    formats = FORMAT_FAMILIES["avro"] + _ASYNCAPI
    rows = [
        ("reader-field-missing-default-value", "A reader field the writer lacks has no default."),
        ("type-mismatch", "Two types that do not resolve; Avro's promotions such as int to long do."),
        ("name-mismatch", "A record, enum or fixed renamed without an alias for the old name."),
        ("missing-enum-symbols", "Writer enum symbols the reader lacks, and the reader's enum has no default."),
        ("missing-union-branch", "A writer union branch no reader branch can read."),
        ("fixed-size-mismatch", "A fixed of another size."),
    ]
    entries = [
        CatalogueEntry(
            rule_id=f"avro-compatibility.{slug}",
            family="avro",
            formats=formats,
            direction="either",
            severities=_direction_severities(["backward", "forward"]),
            description=description,
        )
        for slug, description in rows
    ]
    entries.append(
        CatalogueEntry(
            rule_id="avro-compatibility.compatible",
            family="avro",
            formats=FORMAT_FAMILIES["avro"],
            direction=None,
            severities={mode: _S.value for mode in COMPATIBILITY_MODES},
            description="Avro schema resolution reads the change both ways (FULL compatible).",
        )
    )
    return entries


def _protobuf_entries() -> List[CatalogueEntry]:
    """Every ``protobuf.<category>.<rule>`` id :mod:`app.proto_breaking_rules` emits, plus overlays."""
    formats = FORMAT_FAMILIES["protobuf"] + _ASYNCAPI
    rows = [
        ("reserved-removed", _ALL_DANGEROUS, "A reserved number or name removed."),
        ("reserved-number-reused", _ALL_BREAKING, "A reserved number used again."),
        ("reserved-name-reused", _ALL_BREAKING, "A reserved name used again."),
        ("field-deleted-unreserved", (_D, _B, _B, _B), "A field deleted without reserving its number or name."),
        ("field-deleted", _SOURCE_BREAKING, "A field deleted with its number and name reserved."),
        ("field-renamed", _JSON_BREAKING, "A field renamed, same number and type."),
        ("field-number-reused", _ALL_BREAKING, "A field number now carrying another type."),
        ("json-name-changed", _JSON_BREAKING, "A field's json_name changed."),
        ("type-moved-file", _FILE_BREAKING, "A message or enum moved to another file in the same package."),
        ("package-changed", _ALL_BREAKING, "A message or enum moved to another package."),
        ("enum-value-number-reused", _JSON_BREAKING, "An enum value renamed: its number taken by a new name."),
        ("enum-value-number-changed", _ALL_BREAKING, "An enum value moved to another number."),
        ("oneof-membership-changed", _ALL_BREAKING, "A field moved into, out of or between oneofs."),
        ("cardinality-changed", _ALL_BREAKING, "A field made repeated, or no longer repeated."),
        ("required-changed", _ALL_BREAKING, "A field made required, or no longer required."),
        ("presence-changed", _SOURCE_BREAKING, "optional added to or removed from a proto3 field."),
    ]
    entries = []
    for slug, grades, description in rows:
        rule_id = category_rule_id(slug, grades)
        entries.append(
            CatalogueEntry(
                rule_id=rule_id,
                family="protobuf",
                formats=formats,
                direction=None,
                severities=None,
                category=rule_id.split(".")[1].upper(),
                category_severities={cat: g.value for cat, g in zip(PROTOBUF_CATEGORIES, grades)},
                description=description,
            )
        )
    entries += [
        CatalogueEntry(
            rule_id=COMPATIBLE_RULE_ID,
            family="protobuf",
            formats=FORMAT_FAMILIES["protobuf"],
            direction=None,
            severities=None,
            category_severities={cat: _S.value for cat in PROTOBUF_CATEGORIES},
            description="A change the rules explain without a break, such as a number or name reserved.",
        ),
        CatalogueEntry(
            rule_id="protobuf.buf-breaking.",
            family="protobuf",
            formats=FORMAT_FAMILIES["protobuf"],
            direction=None,
            severities=None,
            category_severities={cat: _B.value for cat in PROTOBUF_CATEGORIES},
            description=(
                "A break buf breaking reported, named after buf's own rule "
                "(protobuf.buf-breaking.field_same_json_name), at the category the diff was graded at."
            ),
            is_family=True,
        ),
        CatalogueEntry(
            rule_id="buf-breaking.wire-compatible",
            family="protobuf",
            formats=FORMAT_FAMILIES["protobuf"],
            direction=None,
            severities=None,
            category_severities={cat: _D.value for cat in PROTOBUF_CATEGORIES},
            description="buf breaking found no break, so a rule's breaking grade was lowered to dangerous.",
        ),
    ]
    return entries


def _asyncapi_entries() -> List[CatalogueEntry]:
    """Every ``asyncapi.<side>.<rule>`` id the AsyncAPI rules emit, plus the ``@asyncapi/diff`` overlay."""
    rows = [
        ("address-changed", _B, _D, "A channel's address or address template changed."),
        ("parameter-added", _B, _D, "An address parameter added without a default."),
        ("parameter-added-with-default", _S, _S, "An address parameter added with a default."),
        ("protocol-changed", _B, _B, "A server's protocol changed."),
        ("binding-changed", _B, _B, "A channel, operation, message or server binding changed."),
        ("action-flipped", _B, _B, "An operation's action flipped between send and receive."),
        ("reply-removed", _B, _D, "An operation's reply removed (AsyncAPI 3)."),
        ("message-removed", _B, _S, "A message removed from a channel's messages."),
        ("message-added", _S, _D, "A message added to a channel's messages."),
        ("schema-format-changed", _B, _B, "A payload's schemaFormat changed to another schema language."),
        ("payload-compatible", _S, _S, "A payload changed in a way its own format accepts both ways."),
        ("server-changed", _D, _D, "A server added, removed or moved."),
        ("security-changed", _D, _D, "A server's or an operation's security changed."),
    ]
    entries = [
        CatalogueEntry(
            rule_id=side_rule_id(slug, consumer, producer),
            family="asyncapi",
            formats=_ASYNCAPI,
            direction=side_rule_id(slug, consumer, producer).split(".")[1],
            severities=_side_severities(consumer, producer),
            description=f"{description} Consumers: {consumer.value}; producers: {producer.value}.",
        )
        for slug, consumer, producer, description in rows
    ]
    entries += [
        CatalogueEntry(
            rule_id="asyncapi-diff.breaking",
            family="asyncapi",
            formats=_ASYNCAPI,
            direction=None,
            severities={mode: (_D if mode == MODE_NONE else _B).value for mode in COMPATIBILITY_MODES},
            description="@asyncapi/diff classified the whole channel or operation as breaking.",
        ),
        CatalogueEntry(
            rule_id="asyncapi-diff.non-breaking",
            family="asyncapi",
            formats=_ASYNCAPI,
            direction=None,
            severities={mode: _S.value for mode in COMPATIBILITY_MODES},
            description="@asyncapi/diff classified the whole channel or operation as non-breaking.",
        ),
    ]
    return entries


def catalogue() -> List[CatalogueEntry]:
    """Return the whole catalogue, grouped by family (Avro, JSON Schema, Protobuf, AsyncAPI), sorted by id.

    Returns:
        Every :class:`CatalogueEntry`.
    """
    out: List[CatalogueEntry] = []
    for group in (_avro_entries(), _jsonschema_entries(), _protobuf_entries(), _asyncapi_entries()):
        out += sorted(group, key=lambda e: e.rule_id)
    return out


def entries_for_format(format_key: Optional[str]) -> List[CatalogueEntry]:
    """Return the catalogue entries a format's comparisons can emit.

    Args:
        format_key: A family (``asyncapi``) or format key (``asyncapi-3``, ``jsonschema``), any case;
            ``None`` / blank for every entry.

    Returns:
        The matching entries, in catalogue order; ``[]`` for a format with no mode-aware rules.
    """
    key = (format_key or "").strip().lower()
    if not key:
        return catalogue()
    keys = FORMAT_FAMILIES.get(key, (key,))
    return [e for e in catalogue() if any(k in e.formats for k in keys)]


def find_entry(rule_id: str) -> Optional[CatalogueEntry]:
    """Return the entry ``rule_id`` belongs to (exact id first, then a family prefix), or ``None``."""
    entries = catalogue()
    exact = next((e for e in entries if not e.is_family and e.matches(rule_id)), None)
    return exact or next((e for e in entries if e.is_family and e.matches(rule_id)), None)


# ===========================================================================
# Docs rendering
# ===========================================================================

#: Markers around the generated section of ``apiome-docs/docs/govern/compatibility-modes.md``.
CATALOGUE_DOC_START = "<!-- compatibility-rule-catalogue:start (generated by apiome-rest/scripts/generate_compatibility_rule_catalogue.py) -->"
CATALOGUE_DOC_END = "<!-- compatibility-rule-catalogue:end -->"

_FAMILY_TITLES = (
    ("avro", "Avro"),
    ("json-schema", "JSON Schema"),
    ("asyncapi", "AsyncAPI"),
    ("protobuf", "Protobuf"),
)


def _cell(severity: Optional[str]) -> str:
    """A severity as the docs tables write it (``Breaking``); an em dash when it does not apply."""
    return severity.capitalize() if severity else "—"


def _rule_cell(entry: CatalogueEntry) -> str:
    return f"`{entry.rule_id}*`" if entry.is_family else f"`{entry.rule_id}`"


def render_catalogue_markdown() -> str:
    """Render the catalogue as the Markdown tables the docs page carries between its markers.

    Returns:
        The section body (without the markers), ending in a newline.
    """
    entries = catalogue()
    lines: List[str] = []
    for family, title in _FAMILY_TITLES:
        rows = [e for e in entries if e.family == family]
        lines += [f"### {title} rules", ""]
        if family == "protobuf":
            lines.append("| Rule id | Category | " + " | ".join(f"`{c}`" for c in PROTOBUF_CATEGORIES) + " | Description |")
            lines.append("| --- | --- | " + " | ".join("---" for _ in PROTOBUF_CATEGORIES) + " | --- |")
            for e in rows:
                grades = e.category_severities or {}
                cells = " | ".join(_cell(grades.get(c)) for c in PROTOBUF_CATEGORIES)
                category = f"`{e.category}`" if e.category else "—"
                lines.append(f"| {_rule_cell(e)} | {category} | {cells} | {e.description} |")
        else:
            lines.append("| Rule id | Breaks | " + " | ".join(f"`{m}`" for m in COMPATIBILITY_MODES) + " | Description |")
            lines.append("| --- | --- | " + " | ".join("---" for _ in COMPATIBILITY_MODES) + " | --- |")
            for e in rows:
                grades = e.severities or {}
                cells = " | ".join(_cell(grades.get(m)) for m in COMPATIBILITY_MODES)
                lines.append(f"| {_rule_cell(e)} | {e.direction or '—'} | {cells} | {e.description} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def replace_catalogue_section(page: str) -> str:
    """Return ``page`` with the text between the catalogue markers replaced by a fresh rendering.

    Args:
        page: The docs page's Markdown.

    Returns:
        The updated page.

    Raises:
        ValueError: If the page does not carry both markers, in order.
    """
    start = page.find(CATALOGUE_DOC_START)
    end = page.find(CATALOGUE_DOC_END)
    if start < 0 or end < start:
        raise ValueError("The page has no compatibility rule catalogue markers")
    head = page[: start + len(CATALOGUE_DOC_START)]
    return f"{head}\n\n{render_catalogue_markdown()}\n{page[end:]}"
