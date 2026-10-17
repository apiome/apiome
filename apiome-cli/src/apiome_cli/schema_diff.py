"""Client-side structural diff of two published OpenAPI documents (CLI 9.8, ``apiome schema diff``).

``apiome schema diff <tenant>/<project> <v1> <v2>`` fetches both versions from the **public**
``GET /v1/schema/...`` route (no login) and compares them here, in the CLI. It reports *what*
changed, not how bad it is: grading changes as breaking stays with ``apiome versions
compatibility`` (the server's compatibility engine).

Three kinds of change are found, each ``added``, ``removed`` or ``changed``:

* **path** — one operation, labelled ``METHOD /path`` (``POST /refunds``). Path-level keys
  outside the operations (shared ``parameters``, ``summary``…) are reported as ``/path`` alone.
* **class** — one schema under ``components.schemas`` (Apiome classes), by name.
* **property** — one entry of a class's ``properties``, labelled ``Class.property``. Only
  classes present in both versions are compared property by property; the properties of an added
  or removed class are part of that class's change.

A change whose two sides are equal once every ``description`` and ``summary`` is removed is
flagged ``description_only``, which ``--ignore description-only`` drops.

Everything here is pure (no HTTP, no typer): :func:`diff_specs` builds the change list and the
``render_*`` / ``to_*`` functions turn it into the four ``--format`` outputs.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
TOOL_NAME = "apiome schema diff"

#: ``--scope`` values: which part of the documents is compared.
SCOPES = ("paths", "schemas", "all")
#: ``--ignore`` rules this differ understands.
IGNORE_RULES = ("description-only",)
#: ``--format`` values.
FORMATS = ("summary", "unified", "sarif", "json")

KIND_PATH = "path"
KIND_CLASS = "class"
KIND_PROPERTY = "property"
_KIND_ORDER = (KIND_PATH, KIND_CLASS, KIND_PROPERTY)
_ACTION_ORDER = ("added", "removed", "changed")

#: Operation keys of an OpenAPI path item (everything else on a path item is path-level).
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
#: Keys removed before the ``description-only`` comparison.
_PROSE_KEYS = frozenset({"description", "summary"})
#: How many targets the summary lists after each count before ``…``.
_SUMMARY_LIST_MAX = 3


@dataclass(frozen=True)
class Change:
    """One difference between the base and head documents.

    Attributes:
        kind: ``path``, ``class`` or ``property``.
        action: ``added``, ``removed`` or ``changed``.
        target: Human label — ``POST /refunds``, ``Charge`` or ``Charge.amount``.
        pointer: JSON pointer to the node in the document that has it (head, or base if removed).
        description_only: True when only ``description`` / ``summary`` text differs.
    """

    kind: str
    action: str
    target: str
    pointer: str
    description_only: bool = False

    @property
    def rule(self) -> str:
        """SARIF rule id / JSON ``rule``: ``<kind>-<action>`` (``path-added``)."""
        return f"{self.kind}-{self.action}"


def _escape_pointer(token: str) -> str:
    """Escape one JSON-pointer reference token (RFC 6901)."""
    return token.replace("~", "~0").replace("/", "~1")


def strip_prose(value: Any) -> Any:
    """Return *value* with every ``description`` and ``summary`` key removed, recursively."""
    if isinstance(value, Mapping):
        return {k: strip_prose(v) for k, v in value.items() if k not in _PROSE_KEYS}
    if isinstance(value, list):
        return [strip_prose(item) for item in value]
    return value


def _changed(before: Any, after: Any) -> bool | None:
    """Compare two nodes: ``None`` if equal, else whether the difference is prose-only."""
    if before == after:
        return None
    return strip_prose(before) == strip_prose(after)


def _mapping(value: Any) -> Mapping[str, Any]:
    """*value* when it is a mapping, else an empty one (tolerates missing or odd sections)."""
    return value if isinstance(value, Mapping) else {}


def _keyed_changes(
    base: Mapping[str, Any],
    head: Mapping[str, Any],
    *,
    kind: str,
    label: Any,
    pointer: Any,
) -> list[Change]:
    """Diff two name → node maps into added / removed / changed :class:`Change` rows.

    Args:
        base: The base version's map.
        head: The head version's map.
        kind: Change kind for every row.
        label: ``name -> target label``.
        pointer: ``name -> JSON pointer``.
    """
    changes: list[Change] = []
    for name in sorted(set(base) | set(head)):
        if name not in base:
            changes.append(Change(kind, "added", label(name), pointer(name)))
        elif name not in head:
            changes.append(Change(kind, "removed", label(name), pointer(name)))
        else:
            prose_only = _changed(base[name], head[name])
            if prose_only is not None:
                changes.append(Change(kind, "changed", label(name), pointer(name), prose_only))
    return changes


def _operations(paths: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten ``paths`` into ``"METHOD /path" -> operation`` plus ``"/path" -> path-level keys``."""
    flat: dict[str, Any] = {}
    for path, item in _mapping(paths).items():
        item = _mapping(item)
        for method in HTTP_METHODS:
            if method in item:
                flat[f"{method.upper()} {path}"] = item[method]
        shared = {k: v for k, v in item.items() if k not in HTTP_METHODS}
        if shared:
            flat[path] = shared
    return flat


def _operation_pointer(label: str) -> str:
    """JSON pointer for an ``_operations`` key (``POST /refunds`` or ``/refunds``)."""
    method, _, path = label.partition(" ")
    if not path:
        return f"/paths/{_escape_pointer(label)}"
    return f"/paths/{_escape_pointer(path)}/{method.lower()}"


def _schemas(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_mapping(document.get("components")).get("schemas"))


def diff_specs(base: Mapping[str, Any], head: Mapping[str, Any], *, scope: str = "all") -> list[Change]:
    """Compare two OpenAPI documents.

    Args:
        base: The older document (``v1``).
        head: The newer document (``v2``).
        scope: ``paths``, ``schemas`` or ``all`` (see :data:`SCOPES`).

    Returns:
        Changes ordered by kind (paths, classes, properties), then action, then target.

    Raises:
        ValueError: For an unknown *scope*.
    """
    if scope not in SCOPES:
        raise ValueError(f"--scope must be one of {', '.join(SCOPES)}, got {scope!r}")
    changes: list[Change] = []
    if scope in ("paths", "all"):
        changes += _keyed_changes(
            _operations(_mapping(base.get("paths"))),
            _operations(_mapping(head.get("paths"))),
            kind=KIND_PATH,
            label=lambda name: name,
            pointer=_operation_pointer,
        )
    if scope in ("schemas", "all"):
        base_schemas, head_schemas = _schemas(base), _schemas(head)
        changes += _keyed_changes(
            base_schemas,
            head_schemas,
            kind=KIND_CLASS,
            label=lambda name: name,
            pointer=lambda name: f"/components/schemas/{_escape_pointer(name)}",
        )
        for cls in sorted(set(base_schemas) & set(head_schemas)):
            changes += _keyed_changes(
                _mapping(_mapping(base_schemas[cls]).get("properties")),
                _mapping(_mapping(head_schemas[cls]).get("properties")),
                kind=KIND_PROPERTY,
                label=lambda name, cls=cls: f"{cls}.{name}",
                pointer=lambda name, cls=cls: (
                    f"/components/schemas/{_escape_pointer(cls)}/properties/{_escape_pointer(name)}"
                ),
            )
    return sorted(changes, key=_sort_key)


def _sort_key(change: Change) -> tuple[int, int, str]:
    return (_KIND_ORDER.index(change.kind), _ACTION_ORDER.index(change.action), change.target)


def normalize_ignore(rules: Iterable[str]) -> list[str]:
    """Validate ``--ignore`` values (any case, ``_`` or ``-``) and return them de-duplicated.

    Raises:
        ValueError: For a rule outside :data:`IGNORE_RULES`.
    """
    normalized: list[str] = []
    for rule in rules:
        value = rule.strip().lower().replace("_", "-")
        if value not in IGNORE_RULES:
            raise ValueError(f"--ignore must be one of {', '.join(IGNORE_RULES)}, got {rule!r}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def apply_ignore(changes: Sequence[Change], ignore: Sequence[str]) -> list[Change]:
    """Drop the changes an ``--ignore`` rule covers (today: ``description-only``)."""
    if "description-only" in ignore:
        return [c for c in changes if not c.description_only]
    return list(changes)


def counts(changes: Sequence[Change]) -> dict[str, dict[str, int]]:
    """``{kind: {action: n}}`` for every kind and action (zeros included)."""
    table = {kind: dict.fromkeys(_ACTION_ORDER, 0) for kind in _KIND_ORDER}
    for change in changes:
        table[change.kind][change.action] += 1
    return table


def _plural(n: int, word: str) -> str:
    if n == 1:
        return word
    return "properties" if word == "property" else f"{word}es" if word == "class" else f"{word}s"


def render_summary(changes: Sequence[Change], *, base_label: str, head_label: str) -> str:
    """The default ``--format summary`` text: one count line per kind and action that occurred.

    Each line lists up to three targets, then ``…``; ends with a pointer to the full formats.
    """
    lines = [f"Comparing {base_label} → {head_label} …"]
    if not changes:
        lines.append("  No differences.")
        return "\n".join(lines)
    sign = {"added": "+", "removed": "-", "changed": "~"}
    for kind in _KIND_ORDER:
        for action in _ACTION_ORDER:
            targets = [c.target for c in changes if c.kind == kind and c.action == action]
            if not targets:
                continue
            shown = ", ".join(targets[:_SUMMARY_LIST_MAX]) + (", …" if len(targets) > _SUMMARY_LIST_MAX else "")
            lines.append(f"  {sign[action]} {len(targets)} {action} {_plural(len(targets), kind)} ({shown})")
    lines.append("")
    lines.append("Use `--format unified` or `--format json` for the full diff.")
    return "\n".join(lines)


def scoped_document(document: Mapping[str, Any], scope: str) -> Any:
    """The part of *document* a ``--scope`` compares (used for the unified text)."""
    if scope == "paths":
        return {"paths": _mapping(document.get("paths"))}
    if scope == "schemas":
        return {"components": {"schemas": _schemas(document)}}
    return document


def render_unified(
    base: Mapping[str, Any],
    head: Mapping[str, Any],
    *,
    base_label: str,
    head_label: str,
    scope: str = "all",
    ignore: Sequence[str] = (),
) -> str:
    """``--format unified``: a unified diff of both documents as sorted, indented JSON.

    Sorting keys makes the text independent of the server's key order, so only real changes show.
    With ``description-only`` ignored, prose keys are removed from both sides first. Empty when
    the documents are identical.
    """
    left, right = scoped_document(base, scope), scoped_document(head, scope)
    if "description-only" in ignore:
        left, right = strip_prose(left), strip_prose(right)

    def text(value: Any) -> list[str]:
        return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").splitlines(keepends=True)

    return "".join(difflib.unified_diff(text(left), text(right), fromfile=base_label, tofile=head_label))


def _change_json(change: Change) -> dict[str, Any]:
    return {
        "kind": change.kind,
        "action": change.action,
        "target": change.target,
        "pointer": change.pointer,
        "rule": change.rule,
        "descriptionOnly": change.description_only,
    }


def to_json(
    changes: Sequence[Change],
    *,
    base: Mapping[str, Any],
    head: Mapping[str, Any],
    scope: str,
    ignore: Sequence[str],
) -> dict[str, Any]:
    """``--format json``: both sides, the options, per-kind counts and every change."""
    return {
        "base": dict(base),
        "head": dict(head),
        "scope": scope,
        "ignore": list(ignore),
        "identical": not changes,
        "counts": counts(changes),
        "changes": [_change_json(c) for c in changes],
    }


def to_sarif(
    changes: Sequence[Change],
    *,
    artifact_uri: str,
    tool_version: str,
    base: Mapping[str, Any],
    head: Mapping[str, Any],
) -> dict[str, Any]:
    """``--format sarif``: a SARIF 2.1.0 log with one ``note`` result per change.

    The differ does not grade changes, so every result is level ``note``; each sits on
    *artifact_uri* (the head version's ``/v1/schema/...`` path) with its JSON pointer as the
    logical location.
    """
    rule_ids = sorted({c.rule for c in changes})
    rules = [
        {
            "id": rule,
            "name": rule,
            "shortDescription": {"text": rule.replace("-", " ")},
            "properties": {"tags": ["api-diff"]},
        }
        for rule in rule_ids
    ]
    results = [
        {
            "ruleId": c.rule,
            "ruleIndex": rule_ids.index(c.rule),
            "level": "note",
            "message": {"text": f"{c.kind} {c.action}: {c.target}" + (" (description only)" if c.description_only else "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": artifact_uri},
                        "region": {"startLine": 1},
                    },
                    "logicalLocations": [{"fullyQualifiedName": c.pointer, "kind": "member"}],
                }
            ],
        }
        for c in changes
    ]
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": tool_version,
                        "informationUri": "https://github.com/apiome/apiome",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {"base": dict(base), "head": dict(head)},
            }
        ],
    }
