"""Avro schema hygiene checks — MFI-12.5 (#3786).

The canonical model keeps what an Avro schema *means*, not how it is written: union branch order,
the exact JSON of a default, aliases on a ``.avsc`` type and a ``doc`` on an anonymous type are all
gone by the time a lint rule could look. Those are exactly the places Avro schemas go wrong, so
this module checks the parsed :class:`~app.avro_parser.AvroDocument` itself (both surfaces,
``.avsc`` and IDL) and records what it finds for the ``avro`` lint pack (:mod:`app.avro_lint`).

Each issue names its rule (Avro 1.12 specification, https://avro.apache.org/docs/1.12.0/specification/):

* **defaults** — ``avro.invalid-default``: a field / parameter default, or an enum's default
  symbol, that is not a value of its type. For a union the default must match the union's
  *first* branch. A reader fills a missing field from its default, so a bad one breaks reads.
* **unions** — ``avro.invalid-union``: a union that directly contains another union, or repeats a
  branch (two of the same unnamed type, or two named types with one full name).
* **optional-union hygiene** (two-branch unions with ``null``) —
  ``avro.optional-union-null-first``: ``[T, "null"]`` with no default; it cannot default to
  ``null`` because a union default must match its first branch.
  ``avro.optional-union-missing-default``: ``["null", T]`` with no default; the field is optional
  in data but not in evolution — readers of older data cannot fill it in.
* **aliases** — ``avro.invalid-alias``: an alias that is not a valid Avro name.
  ``avro.alias-conflict``: an alias that collides with another field's name or alias in the same
  record, or with another named type's full name or alias. ``avro.redundant-alias``: an alias
  equal to the element's own name.
* **doc** — ``avro.doc-ignored``: a ``doc`` that is not a string, or one placed on an anonymous
  type (``{"type": "string", "doc": …}``) rather than on the field, where tools drop it.
  (Missing docs are the common pack's ``common.*-missing-description`` rules.)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .avro_parser import AvroDocument, AvroNamedSchema

__all__ = [
    "MAX_REPORTED_ISSUES",
    "RULE_ALIAS_CONFLICT",
    "RULE_DOC_IGNORED",
    "RULE_INVALID_ALIAS",
    "RULE_INVALID_DEFAULT",
    "RULE_INVALID_UNION",
    "RULE_OPTIONAL_UNION_MISSING_DEFAULT",
    "RULE_OPTIONAL_UNION_NULL_FIRST",
    "RULE_REDUNDANT_ALIAS",
    "HygieneIssue",
    "check_avro_document",
]

RULE_INVALID_DEFAULT = "avro.invalid-default"
RULE_INVALID_UNION = "avro.invalid-union"
RULE_OPTIONAL_UNION_NULL_FIRST = "avro.optional-union-null-first"
RULE_OPTIONAL_UNION_MISSING_DEFAULT = "avro.optional-union-missing-default"
RULE_INVALID_ALIAS = "avro.invalid-alias"
RULE_ALIAS_CONFLICT = "avro.alias-conflict"
RULE_REDUNDANT_ALIAS = "avro.redundant-alias"
RULE_DOC_IGNORED = "avro.doc-ignored"

#: Most issues recorded for one document (the rest are counted, not listed).
MAX_REPORTED_ISSUES = 50

_PRIMITIVES = frozenset({"null", "boolean", "int", "long", "float", "double", "bytes", "string"})
_NAMED = frozenset({"record", "error", "enum", "fixed"})
_INT32 = (-(2**31), 2**31 - 1)
_INT64 = (-(2**63), 2**63 - 1)

#: A simple Avro name (field names, symbols, the last part of a full name).
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class HygieneIssue:
    """One hygiene problem.

    Attributes:
        rule: The ``avro.*`` lint rule that reports it.
        path: Where it is: ``/<full type name>/fields/<field>``, ``/<full type name>/aliases``, or
            ``/messages/<message>/request/<parameter>``.
        message: What is wrong.
    """

    rule: str
    path: str
    message: str

    def as_dict(self) -> Dict[str, str]:
        """The issue as ``{"rule", "path", "message"}``."""
        return {"rule": self.rule, "path": self.path, "message": self.message}


def _full_name(name: str, namespace: Optional[str]) -> str:
    """``name`` qualified by ``namespace`` unless it is already dotted."""
    return name if "." in name or not namespace else f"{namespace}.{name}"


def _type_label(schema: Any) -> str:
    """A short spelling of a schema for messages (``string``, ``array``, ``com.acme.User``)."""
    if isinstance(schema, list):
        return "union"
    if isinstance(schema, Mapping):
        if schema.get("type") in _NAMED and isinstance(schema.get("name"), str):
            return str(schema["name"])
        return str(schema.get("type"))
    return str(schema)


class _Checker:
    """Walks one document and collects its :class:`HygieneIssue` list."""

    def __init__(self, document: AvroDocument) -> None:
        self.document = document
        self.issues: List[HygieneIssue] = []
        self.named: Dict[str, Mapping[str, Any]] = {
            _full_name(item.name, item.namespace): item.schema for item in document.types
        }

    def _add(self, rule: str, path: str, message: str) -> None:
        self.issues.append(HygieneIssue(rule, path, message))

    def resolve(self, name: str, namespace: Optional[str]) -> Optional[Mapping[str, Any]]:
        """The declared named type a reference names (namespace-relative, then as written)."""
        return self.named.get(_full_name(name, namespace)) or self.named.get(name)

    # -- defaults -----------------------------------------------------------------------------

    def default_matches(self, schema: Any, value: Any, namespace: Optional[str], depth: int = 0) -> bool:
        """Whether ``value`` is a valid JSON default for ``schema``.

        Unknown references and over-deep values are given the benefit of the doubt (``True``):
        the check reports only what it can prove.
        """
        if depth > 32:
            return True
        if isinstance(schema, list):
            return not schema or self.default_matches(schema[0], value, namespace, depth + 1)
        if isinstance(schema, str):
            if schema in _PRIMITIVES:
                return _primitive_matches(schema, value)
            target = self.resolve(schema, namespace)
            if target is None:
                return True
            return self.default_matches(dict(target), value, target.get("namespace") or namespace, depth + 1)
        if not isinstance(schema, Mapping):
            return True
        kind = schema.get("type")
        inner_ns = schema.get("namespace") or namespace
        if kind in ("record", "error"):
            if not isinstance(value, Mapping):
                return False
            for field in schema.get("fields") or ():
                if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
                    continue
                if field["name"] in value:
                    if not self.default_matches(field.get("type"), value[field["name"]], inner_ns, depth + 1):
                        return False
                elif "default" not in field:
                    return False
            return True
        if kind == "enum":
            return isinstance(value, str) and value in (schema.get("symbols") or ())
        if kind == "fixed":
            size = schema.get("size")
            return isinstance(value, str) and (not isinstance(size, int) or len(value) == size)
        if kind == "array":
            return isinstance(value, list) and all(
                self.default_matches(schema.get("items"), item, namespace, depth + 1) for item in value
            )
        if kind == "map":
            return isinstance(value, Mapping) and all(
                self.default_matches(schema.get("values"), item, namespace, depth + 1) for item in value.values()
            )
        if isinstance(kind, (str, list)):
            # A primitive written as an object (logical types), or a reference with annotations.
            return self.default_matches(kind, value, namespace, depth + 1)
        return True

    # -- unions -------------------------------------------------------------------------------

    def union(self, branches: List[Any], namespace: Optional[str], path: str) -> None:
        """Report a nested union or a repeated branch."""
        seen: Set[str] = set()
        for branch in branches:
            if isinstance(branch, list):
                self._add(RULE_INVALID_UNION, path, "a union may not directly contain another union.")
                continue
            if isinstance(branch, str):
                key = branch if branch in _PRIMITIVES else _full_name(branch, namespace)
            elif isinstance(branch, Mapping):
                kind = branch.get("type")
                if kind in _NAMED and isinstance(branch.get("name"), str):
                    key = _full_name(branch["name"], branch.get("namespace") or namespace)
                else:
                    key = str(kind)
            else:
                continue
            if key in seen:
                self._add(
                    RULE_INVALID_UNION,
                    path,
                    f"the union repeats `{key}`; a union may hold each unnamed type, and each named type, only once.",
                )
            seen.add(key)

    def walk_type(self, schema: Any, namespace: Optional[str], path: str) -> None:
        """Check the anonymous structure of a field / parameter type (unions, misplaced docs).

        Named types written inline are declarations of their own and are checked as such.
        """
        if isinstance(schema, list):
            self.union(schema, namespace, path)
            for branch in schema:
                if not isinstance(branch, list):
                    self.walk_type(branch, namespace, path)
            return
        if not isinstance(schema, Mapping):
            return
        kind = schema.get("type")
        if kind in _NAMED:
            return
        if "doc" in schema:
            self._add(
                RULE_DOC_IGNORED,
                f"{path}/doc",
                f"`doc` sits on an anonymous `{_type_label(schema)}` type, where Avro tools drop it; "
                f"move it to the field.",
            )
        if kind == "array":
            self.walk_type(schema.get("items"), namespace, path)
        elif kind == "map":
            self.walk_type(schema.get("values"), namespace, path)
        elif isinstance(kind, list):
            self.walk_type(kind, namespace, path)

    # -- fields and parameters ----------------------------------------------------------------

    def slot(
        self, owner: str, name: str, schema: Any, holder: Mapping[str, Any], namespace: Optional[str], path: str
    ) -> None:
        """Check one field or message parameter: type structure, default, optional-union hygiene."""
        self.walk_type(schema, namespace, path)
        has_default = "default" in holder
        if has_default and not self.default_matches(schema, holder["default"], namespace):
            first = " (a union's default must match its first branch)" if isinstance(schema, list) else ""
            self._add(
                RULE_INVALID_DEFAULT,
                f"{path}/default",
                f"{owner} `{name}` has default `{_json(holder['default'])}`, which is not a valid "
                f"`{_type_label(schema[0] if isinstance(schema, list) and schema else schema)}` value{first}.",
            )
        if isinstance(schema, list) and len(schema) == 2 and "null" in schema and not has_default:
            if schema[0] == "null":
                self._add(
                    RULE_OPTIONAL_UNION_MISSING_DEFAULT,
                    path,
                    f'optional {owner} `{name}` has no default; add `"default": null` so readers of '
                    f"data written without it can fill it in.",
                )
            else:
                self._add(
                    RULE_OPTIONAL_UNION_NULL_FIRST,
                    path,
                    f"optional {owner} `{name}` lists `null` last, so it cannot default to null; write "
                    f'it as `["null", {_json(schema[0])}]` with `"default": null`.',
                )

    def aliases(
        self, holder: Mapping[str, Any], *, own: str, path: str, simple: bool, namespace: Optional[str] = None
    ) -> List[str]:
        """Check an ``aliases`` list's names; return the valid, non-redundant ones.

        Args:
            holder: The field or named type carrying ``aliases``.
            own: The field name, or the type's full name.
            path: Where the holder is.
            simple: Field aliases are simple names; type aliases may be dotted full names.
            namespace: The type's namespace, which a relative type alias is read in.
        """
        aliases = holder.get("aliases")
        if aliases is None:
            return []
        if not isinstance(aliases, list):
            self._add(RULE_INVALID_ALIAS, f"{path}/aliases", "`aliases` must be a list of names.")
            return []
        valid: List[str] = []
        for alias in aliases:
            if not isinstance(alias, str) or not _valid_name(alias, simple=simple):
                kind = "a simple name" if simple else "a name or dotted full name"
                self._add(RULE_INVALID_ALIAS, f"{path}/aliases", f"alias `{_json(alias)}` of `{own}` is not {kind}.")
                continue
            if (alias if simple else _full_name(alias, namespace)) == own:
                self._add(RULE_REDUNDANT_ALIAS, f"{path}/aliases", f"alias `{alias}` repeats the name of `{own}`.")
                continue
            valid.append(alias)
        return valid

    def doc(self, holder: Mapping[str, Any], path: str, what: str) -> None:
        """Report a ``doc`` that is not a string."""
        if "doc" in holder and not isinstance(holder["doc"], str):
            self._add(RULE_DOC_IGNORED, f"{path}/doc", f"the `doc` of {what} is not a string, so it is dropped.")

    # -- documents ----------------------------------------------------------------------------

    def named_type(self, item: AvroNamedSchema, type_aliases: Dict[str, str]) -> None:
        """Check one named type: its doc, aliases, enum default and record fields."""
        schema = item.schema
        full = _full_name(item.name, item.namespace)
        path = f"/{full}"
        self.doc(schema, path, f"`{full}`")
        for alias in self.aliases(schema, own=full, path=path, simple=False, namespace=item.namespace):
            qualified = _full_name(alias, item.namespace)
            other = type_aliases.get(qualified)
            if qualified in self.named and qualified != full:
                other = qualified
            if other is not None and other != full:
                self._add(
                    RULE_ALIAS_CONFLICT,
                    f"{path}/aliases",
                    f"alias `{alias}` of `{full}` is also the name or an alias of `{other}`.",
                )
            type_aliases.setdefault(qualified, full)
        kind = schema.get("type")
        if kind == "enum" and "default" in schema:
            symbols = schema.get("symbols") or ()
            if schema["default"] not in symbols:
                self._add(
                    RULE_INVALID_DEFAULT,
                    f"{path}/default",
                    f"enum `{full}` has default `{_json(schema['default'])}`, which is not one of its symbols.",
                )
        if kind not in ("record", "error"):
            return
        names: Dict[str, str] = {}
        fields = [f for f in schema.get("fields") or () if isinstance(f, Mapping) and isinstance(f.get("name"), str)]
        for field in fields:
            names[field["name"]] = field["name"]
        for field in fields:
            name = field["name"]
            field_path = f"{path}/fields/{name}"
            self.doc(field, field_path, f"field `{name}`")
            for alias in self.aliases(field, own=name, path=field_path, simple=True):
                other = names.get(alias)
                if other is not None and other != name:
                    self._add(
                        RULE_ALIAS_CONFLICT,
                        f"{field_path}/aliases",
                        f"alias `{alias}` of field `{name}` is also the name or an alias of field `{other}` "
                        f"in `{full}`.",
                    )
                names.setdefault(alias, name)
            self.slot("field", name, field.get("type"), field, item.namespace, field_path)

    def run(self) -> List[HygieneIssue]:
        """Check every named type, then every IDL message parameter."""
        type_aliases: Dict[str, str] = {}
        for item in self.document.types:
            self.named_type(item, type_aliases)
        protocol = self.document.protocol
        if protocol is not None:
            for message in protocol.messages:
                for parameter in message.request:
                    holder: Dict[str, Any] = {"default": parameter.default} if parameter.has_default else {}
                    self.slot(
                        "parameter",
                        parameter.name,
                        parameter.type,
                        holder,
                        protocol.namespace,
                        f"/messages/{message.name}/request/{parameter.name}",
                    )
        return self.issues


def _primitive_matches(kind: str, value: Any) -> bool:
    """Whether ``value`` is a JSON default for primitive ``kind`` (bytes are JSON strings)."""
    if kind == "null":
        return value is None
    if kind == "boolean":
        return isinstance(value, bool)
    if kind in ("int", "long"):
        low, high = _INT32 if kind == "int" else _INT64
        return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    if kind in ("float", "double"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def _valid_name(name: str, *, simple: bool) -> bool:
    """An Avro name (``simple``) or a dotted full name whose every part is one."""
    parts = [name] if simple else name.split(".")
    return all(_NAME.match(part) for part in parts)


def _json(value: Any) -> str:
    """A compact JSON-ish spelling of a value for messages."""
    try:
        text = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def check_avro_document(document: AvroDocument) -> Tuple[List[HygieneIssue], int]:
    """Run every hygiene check over a parsed Avro document.

    Args:
        document: The parsed ``.avsc`` or IDL document.

    Returns:
        The first :data:`MAX_REPORTED_ISSUES` issues in document order, and how many there were.
    """
    issues = _Checker(document).run()
    return issues[:MAX_REPORTED_ISSUES], len(issues)


def issues_by_rule(issues: Iterable[Mapping[str, Any]], rule: str) -> Iterable[Tuple[str, str]]:
    """``(path, message)`` for the recorded issues of one rule (used by the lint pack)."""
    for issue in issues:
        if isinstance(issue, Mapping) and issue.get("rule") == rule:
            yield str(issue.get("path", "")), str(issue.get("message", ""))
