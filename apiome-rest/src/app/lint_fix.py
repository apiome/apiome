"""Deterministic fix capability of the lint rule SPI — GVM-3.1 (#5869).

A lint rule reports ``(path, message)`` and, until this module, nothing else: every finding
had to be repaired by hand. A rule may now carry a **fix** — a pure function that turns one
finding into RFC 6902 JSON Patch operations. No model is involved; the rule author declares
what the fix touches and the engine holds the fix to that declaration.

The pieces:

* :class:`PatchOp` — one RFC 6902 operation (``add`` / ``remove`` / ``replace`` / ``move`` /
  ``copy`` / ``test``).
* :data:`FixFn` — ``fix(document, finding, options) -> Iterable[PatchOp]``. It reads the
  document and the finding and yields operations. Yielding nothing means *this finding has no
  deterministic repair* (a rename that would collide, a value that cannot be derived).
* :func:`plan_rule_fix` — the engine. It runs the rule's fix and **refuses any operation
  outside the declared scope**: by default the finding's own JSON Pointer and its descendants
  (:data:`FIX_SCOPE_FINDING`). A rule whose repair cannot be expressed inside that subtree —
  renaming a component key rewrites every ``$ref`` to it — declares
  :data:`FIX_SCOPE_DOCUMENT`, which the rule catalogue publishes.
* :class:`FixOptions` — what the caller supplies: the ``operationId`` template and the ids of
  the off-by-default fixes it opts into. A fix that is not applied by default
  (``fix_default=False``) plans nothing unless its rule id is opted in.
* :func:`apply_fix_ops` — a small RFC 6902 applier, so a plan can be applied and re-linted.

Fix classes (:data:`FIX_CLASSES`) say what kind of edit a fix makes:

``structural``
    Re-spells something without changing its meaning (``nullable`` → a type array).
``removal``
    Deletes something that carries no information (an unused component, ``required: []``).
``fill-in``
    Adds a value derived from the document itself (an ``operationId`` from method + path).
``rename``
    Changes an identifier's spelling (an ``operationId``'s casing, a schema name).

Descriptions, examples, security schemes and anything else that *invents meaning* are never
fixed here: :func:`fix_owner_for` reports those rules as owned by the ``agent``.

Everything in this module is pure: no I/O, no clock, and no input is mutated.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from .openapi_document_walk import join_pointer
from .schema_lint import LintFinding

__all__ = [
    "AGENT_OWNED_CATEGORIES",
    "AGENT_OWNED_PACKS",
    "DEFAULT_OPERATION_ID_TEMPLATE",
    "FIX_CLASSES",
    "FIX_OWNER_AGENT",
    "FIX_OWNER_ENGINE",
    "FIX_OWNER_HUMAN",
    "FIX_SCOPES",
    "FIX_SCOPE_DOCUMENT",
    "FIX_SCOPE_FINDING",
    "OPERATION_ID_PLACEHOLDERS",
    "FixError",
    "FixFn",
    "FixOptions",
    "FixScopeError",
    "PatchOp",
    "apply_fix_ops",
    "fix_owner_for",
    "path_from_pointer",
    "plan_rule_fix",
    "pointer_for_path",
    "pointer_within",
    "split_pointer",
    "validate_fix_declaration",
    "validate_fix_ops",
]

#: What kind of edit a fix makes, in the order the documentation lists them.
FIX_CLASSES: Tuple[str, ...] = ("structural", "removal", "fill-in", "rename")

#: The default bound: operations may touch the finding's pointer and its descendants only.
FIX_SCOPE_FINDING = "finding"
#: The declared exception: operations may touch any pointer of the document.
FIX_SCOPE_DOCUMENT = "document"
FIX_SCOPES: Tuple[str, ...] = (FIX_SCOPE_FINDING, FIX_SCOPE_DOCUMENT)

#: Who repairs a rule's findings: the deterministic engine (the rule carries a fix) …
FIX_OWNER_ENGINE = "engine"
#: … the governance agent (the repair invents meaning — SAI-1) …
FIX_OWNER_AGENT = "agent"
#: … or a person (everything else).
FIX_OWNER_HUMAN = "human"

#: Rule categories whose repair has to invent meaning (a description, an example, a security
#: scheme). No rule of these categories carries a deterministic fix.
AGENT_OWNED_CATEGORIES: FrozenSet[str] = frozenset({"documentation", "security"})
#: Rule packs owned by the agent whatever their category: repairing a non-conforming example
#: means writing a new example.
AGENT_OWNED_PACKS: FrozenSet[str] = frozenset({"examples"})

#: The RFC 6902 operations a fix may yield.
_PATCH_OPS: Tuple[str, ...] = ("add", "remove", "replace", "move", "copy", "test")
_OPS_WITH_VALUE = frozenset({"add", "replace", "test"})
_OPS_WITH_FROM = frozenset({"move", "copy"})

#: Default ``operationId`` template: ``GET /pets/{petId}`` → ``getPetsPetId``.
DEFAULT_OPERATION_ID_TEMPLATE = "{method}{Path}"
#: Placeholders an ``operationId`` template may use: the HTTP method in lower / Pascal case and
#: the path's words in camel / Pascal case.
OPERATION_ID_PLACEHOLDERS: Tuple[str, ...] = ("method", "Method", "path", "Path")

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class FixError(ValueError):
    """A fix that is malformed, or a patch that does not apply to its document."""


class FixScopeError(FixError):
    """A fix operation that reaches outside the scope its rule declared."""


@dataclass(frozen=True)
class PatchOp:
    """One RFC 6902 JSON Patch operation.

    Attributes:
        op: ``add`` | ``remove`` | ``replace`` | ``move`` | ``copy`` | ``test``.
        path: RFC 6901 JSON Pointer the operation targets.
        value: The value of an ``add`` / ``replace`` / ``test`` (ignored by the others).
        from_pointer: The source pointer of a ``move`` / ``copy`` (RFC 6902 ``from``).
    """

    op: str
    path: str
    value: Any = None
    from_pointer: Optional[str] = None

    @classmethod
    def add(cls, path: str, value: Any) -> "PatchOp":
        """Return an ``add`` of ``value`` at ``path``."""
        return cls("add", path, value=value)

    @classmethod
    def remove(cls, path: str) -> "PatchOp":
        """Return a ``remove`` of ``path``."""
        return cls("remove", path)

    @classmethod
    def replace(cls, path: str, value: Any) -> "PatchOp":
        """Return a ``replace`` of ``path`` with ``value``."""
        return cls("replace", path, value=value)

    @classmethod
    def move(cls, from_pointer: str, path: str) -> "PatchOp":
        """Return a ``move`` of the value at ``from_pointer`` to ``path``."""
        return cls("move", path, from_pointer=from_pointer)

    def as_dict(self) -> Dict[str, Any]:
        """Return the operation as an RFC 6902 object (``op``, ``path``, ``value`` / ``from``)."""
        out: Dict[str, Any] = {"op": self.op, "path": self.path}
        if self.op in _OPS_WITH_FROM:
            out["from"] = self.from_pointer
        if self.op in _OPS_WITH_VALUE:
            out["value"] = copy.deepcopy(self.value)
        return out


@dataclass(frozen=True)
class FixOptions:
    """What the caller of a fix plan supplies.

    Style guides hold no per-rule options yet, so these travel with the request; the plan
    endpoint (GVM-3.2) is where a guide's choices are read and passed in.

    Attributes:
        operation_id_template: Template the missing-``operationId`` fix renders, built from
            the :data:`OPERATION_ID_PLACEHOLDERS`. Validated by :meth:`validate`.
        opt_in: Rule ids whose off-by-default fixes (``fix_default=False``) the caller enables.
    """

    operation_id_template: str = DEFAULT_OPERATION_ID_TEMPLATE
    opt_in: FrozenSet[str] = field(default_factory=frozenset)

    def validate(self) -> "FixOptions":
        """Check the options and return them.

        Returns:
            ``self``, so the call can be chained.

        Raises:
            FixError: When the template uses an unknown placeholder, has unbalanced braces,
                or names no path placeholder (every operation of a method would then
                receive the same id).
        """
        template = self.operation_id_template
        if not isinstance(template, str) or not template.strip():
            raise FixError("the operationId template must be a non-empty string")
        names = _PLACEHOLDER.findall(template)
        unknown = sorted(set(names) - set(OPERATION_ID_PLACEHOLDERS))
        if unknown:
            raise FixError(
                f"unknown operationId template placeholder(s) {unknown}; "
                f"use {list(OPERATION_ID_PLACEHOLDERS)}"
            )
        if "{" in _PLACEHOLDER.sub("", template) or "}" in _PLACEHOLDER.sub("", template):
            raise FixError("the operationId template has unbalanced braces")
        if not {"path", "Path"} & set(names):
            raise FixError("the operationId template must use {path} or {Path}")
        return self


#: A rule's fix: given the document, one of the rule's findings and the caller's options,
#: yield the RFC 6902 operations that repair that finding — or nothing when the finding has
#: no deterministic repair. Must be pure and must not mutate the document.
FixFn = Callable[[Mapping[str, Any], LintFinding, FixOptions], Iterable[PatchOp]]


# ===========================================================================
# Pointers
# ===========================================================================


def split_pointer(pointer: str) -> List[str]:
    """Split an RFC 6901 JSON Pointer into its unescaped reference tokens.

    Args:
        pointer: ``""`` (the whole document) or a pointer starting with ``/``.

    Returns:
        The tokens; empty for the root pointer.

    Raises:
        FixError: When ``pointer`` is not a string or does not start with ``/``.
    """
    if not isinstance(pointer, str):
        raise FixError(f"a JSON Pointer must be a string, not {type(pointer).__name__}")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise FixError(f"a JSON Pointer must be empty or start with '/': {pointer!r}")
    return [token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/")]


def pointer_within(pointer: str, base: str) -> bool:
    """Return whether ``pointer`` is ``base`` or one of its descendants.

    Args:
        pointer: The pointer to test.
        base: The subtree's root pointer (``""`` contains every pointer).

    Returns:
        ``True`` when ``pointer`` addresses ``base`` itself or something beneath it.
    """
    return pointer == base or pointer.startswith(base + "/")


def path_from_pointer(pointer: str) -> str:
    """Return the dotted finding path of a JSON Pointer (``/paths/~1pets/get`` → ``paths./pets.get``).

    Lint findings carry dotted paths; rules that walk a document by pointer use this to report
    in the same notation. :func:`pointer_for_path` is the way back.

    Args:
        pointer: An RFC 6901 pointer.

    Returns:
        The tokens joined with ``.``.
    """
    return ".".join(split_pointer(pointer))


def _resolve_path(node: Any, rest: str) -> Optional[List[str]]:
    """Resolve the dotted ``rest`` against ``node``; ``None`` when it addresses nothing.

    A key may itself contain dots (``/pets.json``, ``api.v1.Pet``), so every key that the
    remaining path starts with is tried, longest first, with backtracking.
    """
    if rest == "":
        return []
    if isinstance(node, Mapping):
        candidates = [
            key
            for key in node
            if isinstance(key, str) and key and (rest == key or rest.startswith(key + "."))
        ]
        for key in sorted(candidates, key=lambda k: (-len(k), k)):
            tail = _resolve_path(node[key], rest[len(key) + 1 :])
            if tail is not None:
                return [key, *tail]
        return None
    if isinstance(node, list):
        head, _, tail_path = rest.partition(".")
        if not head.isdigit() or int(head) >= len(node):
            return None
        tail = _resolve_path(node[int(head)], tail_path)
        return None if tail is None else [head, *tail]
    return None


def pointer_for_path(document: Any, path: str) -> str:
    """Return the JSON Pointer a finding's dotted ``path`` addresses in ``document``.

    Dotted paths are ambiguous on their own — ``paths./pets.json.get`` could split at any dot —
    so the path is resolved against the document it was reported on.

    Args:
        document: The document the finding was reported on.
        path: The finding's dotted path (``components.schemas.Pet``, ``servers.0``).

    Returns:
        The RFC 6901 pointer.

    Raises:
        FixError: When the path addresses nothing in the document.
    """
    tokens = _resolve_path(document, path or "")
    if tokens is None:
        raise FixError(f"finding path {path!r} does not address anything in the document")
    return join_pointer("", *tokens)


# ===========================================================================
# Declaring and planning a fix
# ===========================================================================


def validate_fix_declaration(
    rule_id: str,
    fix: Optional[FixFn],
    fix_class: Optional[str],
    fix_scope: str,
    fix_summary: str,
    category: str,
) -> None:
    """Check that a rule's fix declaration is complete and consistent.

    Called when a :class:`~app.lint_engine.LintRule` is built, so a half-declared fix fails at
    import time rather than when someone asks for a plan.

    Args:
        rule_id: The rule's id (for the error message).
        fix: The rule's fix function, or ``None``.
        fix_class: The declared fix class, or ``None``.
        fix_scope: The declared scope.
        fix_summary: The one-line description of what the fix does.
        category: The rule's category.

    Raises:
        ValueError: When a fix lacks a valid class, scope or summary; when fix metadata is
            declared without a fix; or when a rule of an agent-owned category carries a fix.
    """
    if fix is None:
        if fix_class is not None or fix_summary:
            raise ValueError(f"rule {rule_id!r} declares fix metadata but no fix")
        return
    if fix_class not in FIX_CLASSES:
        raise ValueError(f"rule {rule_id!r}: fix_class must be one of {list(FIX_CLASSES)}")
    if fix_scope not in FIX_SCOPES:
        raise ValueError(f"rule {rule_id!r}: fix_scope must be one of {list(FIX_SCOPES)}")
    if not fix_summary.strip():
        raise ValueError(f"rule {rule_id!r}: a fixable rule must say what its fix does")
    if category in AGENT_OWNED_CATEGORIES:
        raise ValueError(
            f"rule {rule_id!r}: {category} findings are repaired by the agent, not by a fix"
        )


def fix_owner_for(category: str, fixable: bool, pack: str = "") -> str:
    """Return who repairs the findings of a rule.

    Args:
        category: The rule's category.
        fixable: Whether the rule carries a deterministic fix.
        pack: The rule's pack, when known.

    Returns:
        :data:`FIX_OWNER_ENGINE` for a fixable rule, :data:`FIX_OWNER_AGENT` for a rule whose
        repair invents meaning, otherwise :data:`FIX_OWNER_HUMAN`.
    """
    if fixable:
        return FIX_OWNER_ENGINE
    if category in AGENT_OWNED_CATEGORIES or pack in AGENT_OWNED_PACKS:
        return FIX_OWNER_AGENT
    return FIX_OWNER_HUMAN


def validate_fix_ops(
    ops: Sequence[PatchOp], finding_pointer: str, scope: str = FIX_SCOPE_FINDING
) -> None:
    """Check that every operation is well formed and stays inside the declared scope.

    Args:
        ops: The operations a fix yielded.
        finding_pointer: The JSON Pointer of the finding being fixed.
        scope: :data:`FIX_SCOPE_FINDING` (the default bound) or :data:`FIX_SCOPE_DOCUMENT`.

    Raises:
        FixError: For a value that is not a :class:`PatchOp`, an unknown ``op``, a malformed
            pointer, or a ``move`` / ``copy`` without a source.
        FixScopeError: When ``path`` (or the ``from`` of a ``move`` / ``copy``) lies outside
            the finding's subtree and the scope is :data:`FIX_SCOPE_FINDING`.
    """
    for index, op in enumerate(ops):
        if not isinstance(op, PatchOp):
            raise FixError(f"operation {index}: a fix must yield PatchOp values")
        if op.op not in _PATCH_OPS:
            raise FixError(f"operation {index}: op must be one of {list(_PATCH_OPS)}")
        pointers = [op.path]
        if op.op in _OPS_WITH_FROM:
            if op.from_pointer is None:
                raise FixError(f"operation {index}: '{op.op}' needs a source pointer")
            pointers.append(op.from_pointer)
        for pointer in pointers:
            split_pointer(pointer)
            if scope == FIX_SCOPE_FINDING and not pointer_within(pointer, finding_pointer):
                raise FixScopeError(
                    f"operation {index}: {op.op} {pointer!r} is outside the finding's "
                    f"subtree {finding_pointer!r}"
                )


def plan_rule_fix(
    rule: Any,
    document: Mapping[str, Any],
    finding: LintFinding,
    options: Optional[FixOptions] = None,
) -> Tuple[PatchOp, ...]:
    """Plan the fix of one finding and hold it to the scope its rule declared.

    Args:
        rule: The :class:`~app.lint_engine.LintRule` that reported ``finding``.
        document: The document the finding was reported on. Not mutated.
        finding: The finding to repair.
        options: The caller's options; the defaults when omitted.

    Returns:
        The operations, in application order. Empty when the rule has no fix, when its fix is
        off by default and not opted into, or when this finding has no deterministic repair.

    Raises:
        FixError: When the finding belongs to another rule, its path addresses nothing in
            the document, the options are invalid, or an operation is malformed.
        FixScopeError: When an operation reaches outside the declared scope.
    """
    if finding.rule != rule.rule_id:
        raise FixError(f"finding of rule {finding.rule!r} given to rule {rule.rule_id!r}")
    if rule.fix is None:
        return ()
    options = (options or FixOptions()).validate()
    if not rule.fix_default and rule.rule_id not in options.opt_in:
        return ()
    finding_pointer = pointer_for_path(document, finding.path)
    ops = tuple(rule.fix(document, finding, options))
    validate_fix_ops(ops, finding_pointer, rule.fix_scope)
    return ops


# ===========================================================================
# Applying a plan
# ===========================================================================


def _container(document: Any, tokens: Sequence[str], pointer: str) -> Any:
    """Return the container holding the last token of ``tokens``."""
    node = document
    for token in tokens[:-1]:
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise FixError(f"nothing at {pointer!r}")
    if not isinstance(node, (dict, list)):
        raise FixError(f"cannot address {pointer!r}: its parent is not a container")
    return node


def _index(container: List[Any], token: str, pointer: str, *, for_add: bool) -> int:
    """Return the list index ``token`` names (``-`` appends when adding)."""
    if for_add and token == "-":
        return len(container)
    limit = len(container) if for_add else len(container) - 1
    if not token.isdigit() or int(token) > limit:
        raise FixError(f"{pointer!r} is not an index of its array")
    return int(token)


def _get(document: Any, pointer: str) -> Any:
    """Return the value at ``pointer``; the whole document for the root pointer."""
    tokens = split_pointer(pointer)
    if not tokens:
        return document
    container = _container(document, tokens, pointer)
    if isinstance(container, list):
        return container[_index(container, tokens[-1], pointer, for_add=False)]
    if tokens[-1] not in container:
        raise FixError(f"nothing at {pointer!r}")
    return container[tokens[-1]]


def _remove(document: Any, pointer: str) -> Any:
    """Remove and return the value at ``pointer``."""
    tokens = split_pointer(pointer)
    if not tokens:
        raise FixError("the document root cannot be removed")
    container = _container(document, tokens, pointer)
    if isinstance(container, list):
        return container.pop(_index(container, tokens[-1], pointer, for_add=False))
    if tokens[-1] not in container:
        raise FixError(f"nothing at {pointer!r} to remove")
    return container.pop(tokens[-1])


def _add(document: Any, pointer: str, value: Any) -> None:
    """Add ``value`` at ``pointer`` (insert into an array, set a member of an object)."""
    tokens = split_pointer(pointer)
    if not tokens:
        raise FixError("the document root cannot be replaced")
    container = _container(document, tokens, pointer)
    if isinstance(container, list):
        container.insert(_index(container, tokens[-1], pointer, for_add=True), value)
    else:
        container[tokens[-1]] = value


def _replace(document: Any, pointer: str, value: Any) -> None:
    """Replace the existing value at ``pointer`` in place, keeping its position."""
    tokens = split_pointer(pointer)
    if not tokens:
        raise FixError("the document root cannot be replaced")
    container = _container(document, tokens, pointer)
    if isinstance(container, list):
        container[_index(container, tokens[-1], pointer, for_add=False)] = value
    elif tokens[-1] in container:
        container[tokens[-1]] = value
    else:
        raise FixError(f"nothing at {pointer!r} to replace")


def apply_fix_ops(document: Mapping[str, Any], ops: Iterable[PatchOp]) -> Dict[str, Any]:
    """Apply RFC 6902 operations to a copy of ``document``, in order.

    Args:
        document: The document to patch. Not mutated.
        ops: The operations, as planned by :func:`plan_rule_fix`.

    Returns:
        The patched copy.

    Raises:
        FixError: When an operation is malformed, addresses nothing, moves a value into
            itself, or a ``test`` fails.
    """
    out: Dict[str, Any] = copy.deepcopy(dict(document))
    for index, op in enumerate(ops):
        try:
            if op.op == "add":
                _add(out, op.path, copy.deepcopy(op.value))
            elif op.op == "remove":
                _remove(out, op.path)
            elif op.op == "replace":
                _replace(out, op.path, copy.deepcopy(op.value))
            elif op.op in _OPS_WITH_FROM:
                source = op.from_pointer or ""
                if op.op == "move":
                    if op.path != source and pointer_within(op.path, source):
                        raise FixError(f"cannot move {source!r} into itself")
                    _add(out, op.path, _remove(out, source))
                else:
                    _add(out, op.path, copy.deepcopy(_get(out, source)))
            elif op.op == "test":
                if _get(out, op.path) != op.value:
                    raise FixError(f"test failed at {op.path!r}")
            else:
                raise FixError(f"op must be one of {list(_PATCH_OPS)}")
        except FixError as exc:
            raise FixError(f"operation {index}: {exc}") from exc
    return out
