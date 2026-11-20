"""The first fixable OpenAPI lint rules — GVM-3.1 (#5869).

Thirteen rules over an OpenAPI 3.x document, each carrying a deterministic fix through the
:mod:`app.lint_fix` SPI. They were chosen for being purely syntactic: every fix re-spells,
removes or derives something the document already says. None of them writes a description,
an example or a security scheme.

**These rules run on demand only.** They are registered in the rule catalogue
(:mod:`app.lint_rule_registry`, ``GET /v1/lint/rules``) but are *not* part of
:func:`app.schema_lint.lint_openapi_spec`, so no stored lint report, score, grade or report
fingerprint changes because they exist. :func:`lint_openapi_fixable` evaluates them when a
fix is asked for (the plan endpoint of GVM-3.2), and :func:`plan_openapi_fix` plans the
repair of one finding. The one exception is ``naming.schema-pascal-case``: the rule already
runs in the default lint, and gains a fix here that reports the same finding (same path,
same message, same id).

==========================================  ==========  ===========================================
Rule                                        Fix class   What the fix does
==========================================  ==========  ===========================================
``structure.nullable-keyword``              structural  ``nullable`` → a ``type`` array with null
``structure.schema-example-keyword``        structural  ``example`` → a one-item ``examples`` array
``structure.boolean-exclusive-bound``       structural  boolean exclusive bound → the bound's number
``structure.server-url-trailing-slash``     structural  drops the trailing slash of a server URL
``structure.server-url-scheme-case``        structural  lower-cases a server URL's scheme
``structure.unused-component``              removal     removes a component nothing references
``structure.empty-required``                removal     removes ``required: []``
``structure.duplicate-tag``                 removal     removes a repeated tag declaration
``structure.operation-missing-operation-id``  fill-in   ``operationId`` from method + path
``structure.operation-missing-tags``        fill-in     ``tags`` from the first path segment (opt-in)
``naming.operation-id-camel-case``          rename      re-cases an ``operationId`` to camelCase
``naming.tag-case-mismatch``                rename      re-cases a tag use to its declaration
``naming.schema-pascal-case``               rename      renames a schema and its references (opt-in)
==========================================  ==========  ===========================================

Every check walks the document with :func:`app.openapi_document_walk.walk_document`, so a
keyword is only judged where it *is* that keyword (a property named ``nullable`` is data).
Checks and fixes are pure and never mutate the document.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule
from .lint_fix import (
    FIX_SCOPE_DOCUMENT,
    FixOptions,
    PatchOp,
    path_from_pointer,
    pointer_for_path,
)
from .openapi_document_walk import HTTP_METHODS, Node, join_pointer, resolve_pointer, walk_document
from .schema_lint import OPENAPI_RULES, LintFinding

__all__ = [
    "OPENAPI_FIX_PACK",
    "lint_openapi_fixable",
    "openapi_fix_rule",
    "openapi_fix_rules",
    "plan_openapi_fix",
    "render_operation_id",
]

#: Pack label the catalogue reports for these rules — they are OpenAPI rules.
OPENAPI_FIX_PACK = "openapi"

#: A document check: yield ``(json_pointer, message)`` for each defect.
DocumentCheck = Callable[[Mapping[str, Any]], Iterable[Tuple[str, str]]]

_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WORDS = re.compile(r"[A-Za-z0-9]+")
_URL_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://")
_VERSION = re.compile(r"^(\d+)\.(\d+)")

#: Components sections whose entries are referenced by ``$ref``. ``securitySchemes`` are
#: referenced by name from Security Requirement Objects and are left alone.
_REFERENCED_SECTIONS: Tuple[str, ...] = (
    "schemas",
    "responses",
    "parameters",
    "examples",
    "requestBodies",
    "headers",
    "links",
    "callbacks",
    "pathItems",
    "mediaTypes",
)


# ===========================================================================
# Document helpers
# ===========================================================================


def _openapi_version(document: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    """Return the ``(major, minor)`` of the document's ``openapi`` marker, or ``None``."""
    marker = document.get("openapi") if isinstance(document, Mapping) else None
    match = _VERSION.match(marker) if isinstance(marker, str) else None
    return (int(match.group(1)), int(match.group(2))) if match else None


def _is_openapi_3(document: Mapping[str, Any]) -> bool:
    """Whether ``document`` is an OpenAPI 3.x document."""
    version = _openapi_version(document)
    return version is not None and version[0] == 3


def _is_31_or_later(document: Mapping[str, Any]) -> bool:
    """Whether ``document`` declares OpenAPI 3.1 or later (JSON Schema 2020-12 schemas)."""
    version = _openapi_version(document)
    return version is not None and version >= (3, 1)


def _nodes(document: Mapping[str, Any], kind: str) -> Iterator[Node]:
    """Yield every object of ``kind`` in the document, in walk order."""
    if isinstance(document, dict):
        for node in walk_document(document):
            if node.kind == kind:
                yield node


def _path_operations(document: Mapping[str, Any]) -> Iterator[Tuple[str, str, str, Dict[str, Any]]]:
    """Yield ``(pointer, method, path, operation)`` for every operation under ``paths``.

    Callback and webhook operations are left out: their key is a runtime expression or a
    webhook name, not a path an identifier or a tag can be derived from.
    """
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                yield join_pointer("/paths", path, method), method, str(path), operation


def _words(text: str) -> List[str]:
    """Split ``text`` into its alphanumeric words."""
    return _WORDS.findall(text)


def _capitalize(word: str) -> str:
    """Upper-case the first letter of ``word``; an all-upper word (``API``) becomes ``Api``."""
    word = word.lower() if word.isupper() else word
    return word[:1].upper() + word[1:]


def _pascal_case(text: str) -> str:
    """Return ``text`` in PascalCase (``pet_store`` → ``PetStore``)."""
    return "".join(_capitalize(word) for word in _words(text))


def _camel_case(text: str) -> str:
    """Return ``text`` in camelCase (``Get_pets`` → ``getPets``)."""
    pascal = _pascal_case(text)
    return pascal[:1].lower() + pascal[1:]


def _finding_node(document: Mapping[str, Any], finding: LintFinding) -> Tuple[str, Any]:
    """Return ``(pointer, value)`` of the object a finding was reported on."""
    pointer = pointer_for_path(document, finding.path)
    return pointer, resolve_pointer(document, pointer)


# ===========================================================================
# 3.0 → 3.1 syntax moves
# ===========================================================================


def _check_nullable(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """``nullable`` in a document that declares OpenAPI 3.1 or later."""
    if not _is_31_or_later(document):
        return
    for node in _nodes(document, "schema"):
        if "nullable" in node.value:
            yield (
                node.pointer,
                "Schema uses nullable, which OpenAPI 3.1 removed; declare null in type instead.",
            )


def _fix_nullable(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """``nullable: true`` → ``"null"`` in ``type`` (and ``enum``); ``nullable: false`` is dropped.

    A schema with no ``type``, or with a ``$ref`` beside ``nullable``, is left to a person:
    the first needs restructuring into ``anyOf`` and the second changes what the reference
    accepts.
    """
    pointer, schema = _finding_node(document, finding)
    if not isinstance(schema, dict) or "nullable" not in schema:
        return
    nullable = schema["nullable"]
    if nullable is True:
        declared = schema.get("type")
        if "$ref" in schema or not isinstance(declared, (str, list)):
            return
        types = [declared] if isinstance(declared, str) else list(declared)
        if "null" not in types:
            yield PatchOp.replace(join_pointer(pointer, "type"), [*types, "null"])
        enum = schema.get("enum")
        if isinstance(enum, list) and None not in enum:
            yield PatchOp.replace(join_pointer(pointer, "enum"), [*enum, None])
    elif nullable is not False:
        return
    yield PatchOp.remove(join_pointer(pointer, "nullable"))


def _check_schema_example(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """The Schema Object ``example`` keyword in a document that declares 3.1 or later."""
    if not _is_31_or_later(document):
        return
    for node in _nodes(document, "schema"):
        if "example" in node.value:
            yield (
                node.pointer,
                "Schema uses example, which OpenAPI 3.1 deprecates; use an examples array.",
            )


def _fix_schema_example(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """``example: v`` → ``examples: [v]``; nothing when the schema already has ``examples``."""
    pointer, schema = _finding_node(document, finding)
    if not isinstance(schema, dict) or "example" not in schema or "examples" in schema:
        return
    yield PatchOp.add(join_pointer(pointer, "examples"), [schema["example"]])
    yield PatchOp.remove(join_pointer(pointer, "example"))


_EXCLUSIVE_BOUNDS: Tuple[Tuple[str, str], ...] = (
    ("exclusiveMinimum", "minimum"),
    ("exclusiveMaximum", "maximum"),
)


def _check_boolean_exclusive(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A boolean ``exclusiveMinimum`` / ``exclusiveMaximum`` in a 3.1-or-later document."""
    if not _is_31_or_later(document):
        return
    for node in _nodes(document, "schema"):
        keys = [key for key, _ in _EXCLUSIVE_BOUNDS if isinstance(node.value.get(key), bool)]
        if keys:
            yield (
                node.pointer,
                f"Schema uses a boolean {' and '.join(keys)}; OpenAPI 3.1 expects a number.",
            )


def _fix_boolean_exclusive(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """``exclusiveMinimum: true`` + ``minimum: n`` → ``exclusiveMinimum: n``; a lone flag is dropped."""
    pointer, schema = _finding_node(document, finding)
    if not isinstance(schema, dict):
        return
    for exclusive, bound in _EXCLUSIVE_BOUNDS:
        flag = schema.get(exclusive)
        if not isinstance(flag, bool):
            continue
        limit = schema.get(bound)
        if flag and isinstance(limit, (int, float)) and not isinstance(limit, bool):
            yield PatchOp.replace(join_pointer(pointer, exclusive), limit)
            yield PatchOp.remove(join_pointer(pointer, bound))
        else:
            yield PatchOp.remove(join_pointer(pointer, exclusive))


# ===========================================================================
# Server URLs
# ===========================================================================


def _trimmed_url(url: str) -> Optional[str]:
    """Return ``url`` without its trailing slashes, or ``None`` when nothing may be trimmed."""
    trimmed = url.rstrip("/")
    if trimmed == url or not trimmed or trimmed.endswith(":"):
        return None
    return trimmed


def _check_server_trailing_slash(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A server URL that ends in ``/`` (paths start with one, so requests get ``//``)."""
    for node in _nodes(document, "server"):
        url = node.value.get("url")
        if isinstance(url, str) and _trimmed_url(url) is not None:
            yield (node.pointer, f"Server URL '{url}' ends with a slash.")


def _fix_server_trailing_slash(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Drop the trailing slash(es) of the server's ``url``."""
    pointer, server = _finding_node(document, finding)
    url = server.get("url") if isinstance(server, dict) else None
    trimmed = _trimmed_url(url) if isinstance(url, str) else None
    if trimmed is not None:
        yield PatchOp.replace(join_pointer(pointer, "url"), trimmed)


def _lowercased_scheme(url: str) -> Optional[str]:
    """Return ``url`` with a lower-case scheme, or ``None`` when it already is (or has none)."""
    match = _URL_SCHEME.match(url)
    if match is None or match.group(1) == match.group(1).lower():
        return None
    return match.group(1).lower() + url[match.end(1) :]


def _check_server_scheme_case(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A server URL whose scheme is not lower case (``HTTPS://``)."""
    for node in _nodes(document, "server"):
        url = node.value.get("url")
        if isinstance(url, str) and _lowercased_scheme(url) is not None:
            yield (node.pointer, f"Server URL '{url}' has a scheme that is not lower case.")


def _fix_server_scheme_case(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Lower-case the scheme of the server's ``url``."""
    pointer, server = _finding_node(document, finding)
    url = server.get("url") if isinstance(server, dict) else None
    lowered = _lowercased_scheme(url) if isinstance(url, str) else None
    if lowered is not None:
        yield PatchOp.replace(join_pointer(pointer, "url"), lowered)


# ===========================================================================
# References and unused components
# ===========================================================================


def _iter_references(node: Any, pointer: str = "") -> Iterator[Tuple[str, str, str]]:
    """Yield every local reference under ``node`` as ``(pointer, written, target)``.

    Covers ``$ref`` values and discriminator ``mapping`` values. ``written`` is the string as
    it appears; ``target`` is the reference it means — a bare mapping value (``Cat``) means
    ``#/components/schemas/Cat``. The walk is generic on purpose: a ``$ref`` inside example
    data counts as a reference, which can only make a component look *used*.
    """
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str):
            yield join_pointer(pointer, "$ref"), reference, reference
        discriminator = node.get("discriminator")
        mapping = discriminator.get("mapping") if isinstance(discriminator, dict) else None
        if isinstance(mapping, dict):
            for key, written in mapping.items():
                if isinstance(written, str):
                    bare = "/" not in written and "#" not in written
                    target = "#" + join_pointer("/components/schemas", written) if bare else written
                    yield join_pointer(pointer, "discriminator", "mapping", key), written, target
        for key, value in node.items():
            yield from _iter_references(value, join_pointer(pointer, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_references(value, join_pointer(pointer, index))


def _component_of(reference: str) -> Optional[Tuple[str, str]]:
    """Return the ``(section, name)`` a local reference points into, or ``None``."""
    if not reference.startswith("#/components/"):
        return None
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in reference[2:].split("/")]
    return (tokens[1], tokens[2]) if len(tokens) >= 3 else None


def _unused_components(document: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Return the ``(section, name)`` of every component nothing reachable references.

    Reachability starts from everything outside the referenced components sections and
    follows references transitively, so a component used only by an unused component is
    itself unused — which is what makes removing them all in one pass stable. A document
    with no ``paths`` and no ``webhooks`` is a component library and reports nothing.
    """
    components = document.get("components")
    if not isinstance(components, dict):
        return []
    if not document.get("paths") and not document.get("webhooks"):
        return []
    roots = {key: value for key, value in document.items() if key != "components"}
    roots["components"] = {k: v for k, v in components.items() if k not in _REFERENCED_SECTIONS}

    reached: Set[Tuple[str, str]] = set()
    pending: List[Any] = [roots]
    while pending:
        for _pointer, _written, target in _iter_references(pending.pop()):
            component = _component_of(target)
            if component is None or component in reached:
                continue
            reached.add(component)
            section = components.get(component[0])
            if isinstance(section, dict) and component[1] in section:
                pending.append(section[component[1]])

    unused: List[Tuple[str, str]] = []
    for section in _REFERENCED_SECTIONS:
        entries = components.get(section)
        if isinstance(entries, dict):
            unused.extend((section, name) for name in entries if (section, name) not in reached)
    return unused


def _check_unused_component(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A component that no operation, webhook or used component references."""
    for section, name in _unused_components(document):
        yield (
            join_pointer("/components", section, name),
            f"Component '{name}' in components.{section} is never referenced.",
        )


def _fix_unused_component(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Remove the component, when it is still unused."""
    pointer = pointer_for_path(document, finding.path)
    unused = {join_pointer("/components", section, name) for section, name in _unused_components(document)}
    if pointer in unused:
        yield PatchOp.remove(pointer)


# ===========================================================================
# Empty required, duplicate tags
# ===========================================================================


def _check_empty_required(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """``required: []`` — invalid in OpenAPI 3.0 and says nothing in 3.1."""
    for node in _nodes(document, "schema"):
        if node.value.get("required") == []:
            yield (node.pointer, "Schema declares an empty required list.")


def _fix_empty_required(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Remove the empty ``required`` list."""
    pointer, schema = _finding_node(document, finding)
    if isinstance(schema, dict) and schema.get("required") == []:
        yield PatchOp.remove(join_pointer(pointer, "required"))


def _declared_tags(document: Mapping[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    """Return ``(index, tag)`` for every named Tag Object of the top-level ``tags`` list."""
    tags = document.get("tags")
    if not isinstance(tags, list):
        return []
    return [
        (index, tag)
        for index, tag in enumerate(tags)
        if isinstance(tag, dict) and isinstance(tag.get("name"), str)
    ]


def _check_duplicate_tag(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A tag declared more than once in the top-level ``tags`` list."""
    seen: Set[str] = set()
    for index, tag in _declared_tags(document):
        if tag["name"] in seen:
            yield (join_pointer("/tags", index), f"Tag '{tag['name']}' is declared more than once.")
        seen.add(tag["name"])


def _fix_duplicate_tag(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Remove the repeated declaration, when it adds nothing to the first one.

    A duplicate that carries its own description or external docs is left to a person —
    choosing which text survives is not a syntactic decision.
    """
    pointer, duplicate = _finding_node(document, finding)
    if not isinstance(duplicate, dict):
        return
    first = next(
        (tag for _index, tag in _declared_tags(document) if tag["name"] == duplicate.get("name")),
        None,
    )
    if first is None or first is duplicate:
        return
    if all(key in first and first[key] == value for key, value in duplicate.items()):
        yield PatchOp.remove(pointer)


# ===========================================================================
# operationId and tags fill-in
# ===========================================================================


def render_operation_id(template: str, method: str, path: str) -> str:
    """Render an ``operationId`` from a template, an HTTP method and a path.

    Args:
        template: A template over ``{method}``, ``{Method}``, ``{path}`` and ``{Path}``
            (validated by :meth:`app.lint_fix.FixOptions.validate`).
        method: The HTTP method (any case).
        path: The path template, e.g. ``/pets/{petId}``. The root path renders as ``Root``.

    Returns:
        The rendered id, e.g. ``getPetsPetId`` for the default ``{method}{Path}``.
    """
    words = " ".join(_words(path)) or "root"
    values = {
        "method": method.lower(),
        "Method": method[:1].upper() + method[1:].lower(),
        "path": _camel_case(words),
        "Path": _pascal_case(words),
    }
    return re.sub(r"\{([^{}]*)\}", lambda match: values[match.group(1)], template)


def _existing_operation_ids(document: Mapping[str, Any]) -> Set[str]:
    """Return every ``operationId`` the document declares, anywhere."""
    return {
        node.value["operationId"]
        for node in _nodes(document, "operation")
        if isinstance(node.value.get("operationId"), str)
    }


def _has_operation_id(operation: Mapping[str, Any]) -> bool:
    """Whether an operation carries a non-blank ``operationId``."""
    value = operation.get("operationId")
    return isinstance(value, str) and value.strip() != ""


def _generated_operation_ids(document: Mapping[str, Any], template: str) -> Dict[str, str]:
    """Return ``operation pointer → generated operationId`` for every operation missing one.

    Ids are allocated in document order against the ids already present, so two operations
    whose method + path render alike receive distinct ids (``…2``, ``…3``) — and the same
    document always yields the same allocation. An id that is not a usable identifier is
    left out: that operation has no deterministic fill-in under this template.
    """
    taken = _existing_operation_ids(document)
    generated: Dict[str, str] = {}
    for pointer, method, path, operation in _path_operations(document):
        if _has_operation_id(operation):
            continue
        base = render_operation_id(template, method, path)
        if not _IDENTIFIER.match(base):
            continue
        candidate, suffix = base, 2
        while candidate in taken:
            candidate, suffix = f"{base}{suffix}", suffix + 1
        taken.add(candidate)
        generated[pointer] = candidate
    return generated


def _check_missing_operation_id(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """An operation with no ``operationId`` (code generators then invent a name)."""
    for pointer, method, path, operation in _path_operations(document):
        if not _has_operation_id(operation):
            yield (pointer, f"Operation {method.upper()} {path} has no operationId.")


def _fix_missing_operation_id(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Add an ``operationId`` rendered from the method and path by the caller's template."""
    pointer = pointer_for_path(document, finding.path)
    generated = _generated_operation_ids(document, options.operation_id_template).get(pointer)
    if generated is not None:
        yield PatchOp.add(join_pointer(pointer, "operationId"), generated)


def _first_static_segment(path: str) -> Optional[str]:
    """Return the first path segment when it is literal text (``/pets/{id}`` → ``pets``)."""
    segments = [segment for segment in path.split("/") if segment]
    if not segments or "{" in segments[0] or "}" in segments[0]:
        return None
    return segments[0]


def _check_missing_tags(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """An operation with no tags (it lands in the ungrouped bucket of every docs tool)."""
    for pointer, method, path, operation in _path_operations(document):
        tags = operation.get("tags")
        if tags is None or tags == []:
            yield (pointer, f"Operation {method.upper()} {path} has no tags.")


def _fix_missing_tags(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Add ``tags`` holding the first literal path segment; nothing when the path has none."""
    pointer, operation = _finding_node(document, finding)
    if not isinstance(operation, dict) or operation.get("tags"):
        return
    path = next((p for ptr, _m, p, _o in _path_operations(document) if ptr == pointer), None)
    segment = _first_static_segment(path) if path is not None else None
    if segment is not None:
        yield PatchOp.add(join_pointer(pointer, "tags"), [segment])


# ===========================================================================
# Casing
# ===========================================================================


def _linked_operation_ids(document: Mapping[str, Any]) -> Set[str]:
    """Return the ``operationId`` values Link Objects point at."""
    return {
        node.value["operationId"]
        for node in _nodes(document, "link")
        if isinstance(node.value.get("operationId"), str)
    }


def _check_operation_id_case(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """An ``operationId`` that is not camelCase."""
    for node in _nodes(document, "operation"):
        operation_id = node.value.get("operationId")
        if isinstance(operation_id, str) and operation_id.strip() and not _CAMEL_CASE.match(operation_id):
            yield (
                join_pointer(node.pointer, "operationId"),
                f"operationId '{operation_id}' is not camelCase.",
            )


def _fix_operation_id_case(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Re-case the ``operationId`` to camelCase.

    Nothing is planned when the new id would collide with another operation's, or when a
    Link Object refers to the old id — that reference lies outside the finding.
    """
    pointer, operation_id = _finding_node(document, finding)
    if not isinstance(operation_id, str):
        return
    renamed = _camel_case(operation_id)
    if not _CAMEL_CASE.match(renamed) or renamed == operation_id:
        return
    if renamed in _existing_operation_ids(document) or operation_id in _linked_operation_ids(document):
        return
    yield PatchOp.replace(pointer, renamed)


def _declared_tag_spellings(document: Mapping[str, Any]) -> Tuple[Set[str], Dict[str, str]]:
    """Return the declared tag names and a case-folded lookup of their spelling.

    A name declared in two casings (``Pets`` and ``pets``) is ambiguous and is left out of
    the lookup, so no use is rewritten towards either.
    """
    names = [tag["name"] for _index, tag in _declared_tags(document)]
    by_fold: Dict[str, Set[str]] = {}
    for name in names:
        by_fold.setdefault(name.casefold(), set()).add(name)
    lookup = {fold: next(iter(spellings)) for fold, spellings in by_fold.items() if len(spellings) == 1}
    return set(names), lookup


def _check_tag_case(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """An operation tag that differs from its declaration only by letter case."""
    declared, lookup = _declared_tag_spellings(document)
    for node in _nodes(document, "operation"):
        tags = node.value.get("tags")
        if not isinstance(tags, list):
            continue
        for index, tag in enumerate(tags):
            if isinstance(tag, str) and tag not in declared and tag.casefold() in lookup:
                yield (
                    join_pointer(node.pointer, "tags", index),
                    f"Tag '{tag}' is declared as '{lookup[tag.casefold()]}'.",
                )


def _fix_tag_case(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Replace the tag use with the spelling of its declaration."""
    pointer, tag = _finding_node(document, finding)
    declared, lookup = _declared_tag_spellings(document)
    if isinstance(tag, str) and tag not in declared and tag.casefold() in lookup:
        yield PatchOp.replace(pointer, lookup[tag.casefold()])


def _check_schema_pascal_case(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """A component schema name that is not PascalCase — the default lint's own finding."""
    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        return
    for name in sorted(schemas):
        if not _PASCAL_CASE.match(name):
            yield (join_pointer("/components/schemas", name), f"Schema '{name}' is not PascalCase.")


def _fix_schema_pascal_case(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Rename the schema to PascalCase and rewrite every reference to it.

    The references live all over the document, which is why this rule declares the
    ``document`` scope. Nothing is planned when the new name is taken or is not PascalCase.
    References are rewritten first — while pointers under the old name still resolve — and
    the schema is moved last.
    """
    pointer = pointer_for_path(document, finding.path)
    prefix = "/components/schemas/"
    schemas = resolve_pointer(document, "/components/schemas")
    if not pointer.startswith(prefix) or "/" in pointer[len(prefix) :] or not isinstance(schemas, dict):
        return
    old_name = next((name for name in schemas if join_pointer("/components/schemas", name) == pointer), None)
    if old_name is None or _PASCAL_CASE.match(old_name):
        return
    new_name = _pascal_case(old_name)
    if not _PASCAL_CASE.match(new_name) or new_name in schemas:
        return
    old_reference = "#" + pointer
    new_reference = "#" + join_pointer("/components/schemas", new_name)
    for ref_pointer, written, target in _iter_references(document):
        if target != old_reference and not target.startswith(old_reference + "/"):
            continue
        if written == target:
            yield PatchOp.replace(ref_pointer, new_reference + target[len(old_reference) :])
        else:  # a bare discriminator mapping value names the schema itself
            yield PatchOp.replace(ref_pointer, new_name)
    yield PatchOp.move(pointer, join_pointer("/components/schemas", new_name))


# ===========================================================================
# The rules
# ===========================================================================

_DOCUMENT_CHECKS: Dict[str, DocumentCheck] = {}


def _canonical_check(check: DocumentCheck) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """Adapt a document check to the :class:`~app.lint_engine.LintRule` ``check`` signature.

    The check reads the artifact's retained source document and self-gates to nothing when
    there is none or it is not OpenAPI 3.x.
    """

    def run(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        from .example_conformance_lint import source_document

        document = source_document(api)
        if document is None or not _is_openapi_3(document):
            return []
        return [(path_from_pointer(pointer), message) for pointer, message in check(document)]

    return run


def _rule(
    rule_id: str,
    category: str,
    severity: str,
    description: str,
    check: DocumentCheck,
    **fix: Any,
) -> LintRule:
    """Build one fixable rule and remember its document check."""
    _DOCUMENT_CHECKS[rule_id] = check
    return LintRule(
        rule_id=rule_id,
        category=category,
        severity=severity,
        description=description,
        check=_canonical_check(check),
        **fix,
    )


_PASCAL_RULE_ID = "naming.schema-pascal-case"

_RULES: Tuple[LintRule, ...] = (
    _rule(
        "structure.nullable-keyword",
        "structure",
        "warning",
        "OpenAPI 3.1 removed nullable; a 3.1 validator ignores it, so the schema no longer accepts null.",
        _check_nullable,
        fix=_fix_nullable,
        fix_class="structural",
        fix_summary="Adds null to the schema's type (and enum) and removes nullable.",
    ),
    _rule(
        "structure.schema-example-keyword",
        "structure",
        "info",
        "OpenAPI 3.1 deprecates the schema example keyword in favour of the JSON Schema examples array.",
        _check_schema_example,
        fix=_fix_schema_example,
        fix_class="structural",
        fix_summary="Moves example into a one-item examples array.",
    ),
    _rule(
        "structure.boolean-exclusive-bound",
        "structure",
        "warning",
        "In OpenAPI 3.1 exclusiveMinimum and exclusiveMaximum are numbers; a boolean is not a valid bound.",
        _check_boolean_exclusive,
        fix=_fix_boolean_exclusive,
        fix_class="structural",
        fix_summary="Moves the bound's number onto the exclusive keyword, or drops a flag that sets no bound.",
    ),
    _rule(
        "structure.server-url-trailing-slash",
        "structure",
        "info",
        "Paths start with a slash, so a server URL that ends with one yields double-slash request URLs.",
        _check_server_trailing_slash,
        fix=_fix_server_trailing_slash,
        fix_class="structural",
        fix_summary="Removes the trailing slash from the server URL.",
    ),
    _rule(
        "structure.server-url-scheme-case",
        "structure",
        "info",
        "URL schemes are lower case by convention; some clients compare them literally.",
        _check_server_scheme_case,
        fix=_fix_server_scheme_case,
        fix_class="structural",
        fix_summary="Lower-cases the scheme of the server URL.",
    ),
    _rule(
        "structure.unused-component",
        "structure",
        "info",
        "A component nothing references is dead weight in docs, SDKs and reviews.",
        _check_unused_component,
        fix=_fix_unused_component,
        fix_class="removal",
        fix_summary="Removes the unreferenced component.",
    ),
    _rule(
        "structure.empty-required",
        "structure",
        "warning",
        "An empty required list is invalid in OpenAPI 3.0 and states nothing in 3.1.",
        _check_empty_required,
        fix=_fix_empty_required,
        fix_class="removal",
        fix_summary="Removes the empty required list.",
    ),
    _rule(
        "structure.duplicate-tag",
        "structure",
        "warning",
        "Tag names must be unique; a repeated declaration is invalid and renders twice in docs.",
        _check_duplicate_tag,
        fix=_fix_duplicate_tag,
        fix_class="removal",
        fix_summary="Removes a repeated tag declaration that adds nothing to the first.",
    ),
    _rule(
        "structure.operation-missing-operation-id",
        "structure",
        "warning",
        "Without an operationId every code generator invents its own name for the operation.",
        _check_missing_operation_id,
        fix=_fix_missing_operation_id,
        fix_class="fill-in",
        fix_summary="Adds an operationId built from the HTTP method and the path by a configurable template.",
    ),
    _rule(
        "structure.operation-missing-tags",
        "structure",
        "info",
        "An untagged operation falls into the ungrouped section of docs and SDK tools.",
        _check_missing_tags,
        fix=_fix_missing_tags,
        fix_class="fill-in",
        fix_summary="Adds a tag named after the first path segment. Off unless opted in.",
        fix_default=False,
    ),
    _rule(
        "naming.operation-id-camel-case",
        "naming",
        "info",
        "operationId becomes a method name in generated clients; camelCase is idiomatic in most of them.",
        _check_operation_id_case,
        fix=_fix_operation_id_case,
        fix_class="rename",
        fix_summary="Re-cases the operationId to camelCase when no link refers to it and the new id is free.",
    ),
    _rule(
        "naming.tag-case-mismatch",
        "naming",
        "info",
        "A tag used with different letter case than its declaration creates a second group in docs.",
        _check_tag_case,
        fix=_fix_tag_case,
        fix_class="rename",
        fix_summary="Replaces the tag use with the spelling of its declaration.",
    ),
    _rule(
        _PASCAL_RULE_ID,
        OPENAPI_RULES[_PASCAL_RULE_ID][0],
        OPENAPI_RULES[_PASCAL_RULE_ID][1],
        OPENAPI_RULES[_PASCAL_RULE_ID][2],
        _check_schema_pascal_case,
        fix=_fix_schema_pascal_case,
        fix_class="rename",
        wire_visible=True,
        fix_scope=FIX_SCOPE_DOCUMENT,
        fix_summary=(
            "Renames the schema to PascalCase and rewrites every reference to it. "
            "Changes generated type names; never applied unless opted in."
        ),
        fix_default=False,
    ),
)

_RULES_BY_ID: Dict[str, LintRule] = {rule.rule_id: rule for rule in _RULES}

def openapi_fix_rules() -> Tuple[LintRule, ...]:
    """Return the fixable OpenAPI rules, in the order the module documents them."""
    return _RULES


def openapi_fix_rule(rule_id: str) -> Optional[LintRule]:
    """Return the fixable OpenAPI rule with ``rule_id``, or ``None``."""
    return _RULES_BY_ID.get(rule_id)


def lint_openapi_fixable(document: Mapping[str, Any]) -> List[LintFinding]:
    """Evaluate the fixable OpenAPI rules over a document — on demand, never by default.

    This is what a fix plan starts from. It is separate from
    :func:`app.schema_lint.lint_openapi_spec` so that asking "what could be fixed" never
    changes a stored lint report.

    Args:
        document: A parsed OpenAPI 3.x document. Not mutated.

    Returns:
        The findings sorted by ``(path, rule, id)``; empty for anything that is not an
        OpenAPI 3.x document.
    """
    if not isinstance(document, Mapping) or not _is_openapi_3(document):
        return []
    findings: List[LintFinding] = []
    for rule in _RULES:
        for pointer, message in _DOCUMENT_CHECKS[rule.rule_id](document):
            findings.append(
                LintFinding(
                    path=path_from_pointer(pointer),
                    category=rule.category,
                    rule=rule.rule_id,
                    severity=rule.severity,
                    message=message,
                )
            )
    return sorted(findings, key=lambda f: (f.path, f.rule, f.id))


def plan_openapi_fix(
    document: Mapping[str, Any],
    finding: LintFinding,
    options: Optional[FixOptions] = None,
) -> Tuple[PatchOp, ...]:
    """Plan the deterministic fix of one OpenAPI finding.

    Args:
        document: The document the finding was reported on. Not mutated.
        finding: A finding of any OpenAPI rule.
        options: The caller's fix options; the defaults when omitted.

    Returns:
        The RFC 6902 operations in application order. Empty when the finding's rule has no
        fix, the fix needs an opt-in the options do not give, or this finding has no
        deterministic repair.

    Raises:
        app.lint_fix.FixError: When the finding's path addresses nothing in the document or
            the options are invalid.
        app.lint_fix.FixScopeError: When a fix leaves the scope its rule declared.
    """
    rule = _RULES_BY_ID.get(finding.rule)
    return () if rule is None else rule.plan_fix(document, finding, options)
