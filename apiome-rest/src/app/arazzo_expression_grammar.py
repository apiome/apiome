"""Static Arazzo runtime-expression grammar — GVM-4.4 (#5879).

:mod:`app.arazzo_runtime_expression` *evaluates* expressions during a workflow run; this module
only *parses* them, so the lint pack (:mod:`app.arazzo_structure_rules`) can report a malformed
expression before anything runs — and say exactly where it stops parsing.

The grammar is the Arazzo 1.0 / 1.1 "Runtime Expressions" ABNF::

    expression = ( "$url" / "$method" / "$statusCode" / "$self"
                 / "$request." source / "$response." source / "$message." message-source
                 / "$inputs." name / "$outputs." name / "$steps." name / "$workflows." name
                 / "$sourceDescriptions." name / "$components." name )
    source           = header-reference / query-reference / path-reference / body-reference
    header-reference = "header." token
    query-reference  = "query." name
    path-reference   = "path." name
    body-reference   = "body" [ "#" json-pointer ]
    json-pointer     = *( "/" reference-token )     ; "~" must be followed by "0" or "1"
    token            = 1*tchar                       ; RFC 9110 tchar
    name             = 1*CHAR

``$self`` and ``$message.*`` are the Arazzo 1.1 additions: the document's own URI and the
message an asynchronous step received. ``message-source`` admits ``header`` (``.token`` or a
``#`` pointer) and ``payload`` / ``body`` (an optional ``.name`` tail or ``#`` pointer), the
spellings the shipped 1.1 corpus uses. ``name`` is required to be non-empty: ``$inputs.`` names
nothing, so the grammar's ``*CHAR`` is tightened to ``1*CHAR``. ``$inputs`` and ``$outputs`` on
their own name the whole map — the structured value a 1.1 selector object's ``context`` reads
(Redocly's 1.1 cafe fixture) — and are accepted.

Expressions appear in three shapes, each handled here:

* a whole string (``$response.body#/id``) — :func:`runtime_expression_error`;
* embedded in a template string (``Bearer {$steps.login.outputs.token}``) —
  :func:`embedded_expression_errors`;
* operands of a ``simple`` success-criterion condition (``$statusCode == 200``) —
  :func:`condition_expression_errors`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

__all__ = [
    "ExpressionIssue",
    "condition_expression_errors",
    "embedded_expression_errors",
    "is_whole_expression",
    "runtime_expression_error",
    "string_expression_errors",
]

#: RFC 9110 ``tchar`` — the characters a header ``token`` may use.
_TCHAR = frozenset("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

#: Roots that take no tail at all.
_BARE_ROOTS = ("url", "method", "statusCode", "self")

#: Name roots that may also stand alone, naming the whole map.
_MAP_ROOTS = ("inputs", "outputs")

#: Roots followed by ``.`` and a free-form ``name``.
_NAME_ROOTS = ("inputs", "outputs", "steps", "workflows", "sourceDescriptions", "components")

#: Every root the grammar admits, for the "unknown root" message.
_ALL_ROOTS = _BARE_ROOTS + ("request", "response", "message") + _NAME_ROOTS

#: A string that is exactly one expression — the same test the runner uses to decide that a
#: parameter value is an expression rather than a literal.
_WHOLE = re.compile(r"^\$[A-Za-z][^\s{}]*$")

#: ``{$…}`` placeholders embedded in a template string.
_EMBEDDED = re.compile(r"\{(\$[^{}]*)\}")

#: Expression operands of a simple condition — everything up to whitespace or an operator,
#: exactly as the runner's condition tokenizer reads them.
_CONDITION_OPERAND = re.compile(r"\$[^\s=!<>&|()]+")

#: A single-quoted string literal inside a simple condition (``''`` escapes a quote).
_QUOTED = re.compile(r"'(?:[^']|'')*'")


@dataclass(frozen=True)
class ExpressionIssue:
    """One malformed runtime expression.

    Attributes:
        expression: The expression text as written (without template braces).
        position: Zero-based offset, *within the string that was checked*, of the first
            character the grammar could not accept.
        reason: What the grammar expected at that position.
    """

    expression: str
    position: int
    reason: str

    def describe(self) -> str:
        """Return a one-line human description, e.g. ``'$respons.body' at position 1: …``."""
        return f"{self.expression!r} at position {self.position}: {self.reason}"


def is_whole_expression(text: str) -> bool:
    """Whether ``text`` is written as a single runtime expression (``$`` + letter, no spaces).

    Args:
        text: A string value from the document.

    Returns:
        ``True`` when the runner would evaluate the string as an expression rather than as a
        literal or a template.
    """
    return bool(_WHOLE.match(text.strip()))


def _pointer_error(text: str, start: int) -> Optional[tuple]:
    """Validate a JSON Pointer beginning at ``text[start]`` (just after ``#``).

    Returns:
        ``(offset, reason)`` for the first bad character, or ``None`` when it is valid.
    """
    if start == len(text):
        return None
    if text[start] != "/":
        return start, "a JSON Pointer after '#' must be empty or start with '/'"
    index = start
    while index < len(text):
        if text[index] == "~":
            if index + 1 >= len(text) or text[index + 1] not in "01":
                return index, "'~' in a JSON Pointer must be followed by '0' or '1'"
            index += 2
            continue
        index += 1
    return None


def _token_error(text: str, start: int) -> Optional[tuple]:
    """Validate a header ``token`` (``1*tchar``) from ``text[start]`` to the end."""
    if start == len(text):
        return start, "expected a header name"
    for index in range(start, len(text)):
        if text[index] not in _TCHAR:
            return index, f"{text[index]!r} is not allowed in a header name"
    return None


def _name_error(text: str, start: int, what: str) -> Optional[tuple]:
    """Require a non-empty ``name`` from ``text[start]`` to the end."""
    if start >= len(text):
        return len(text), f"expected {what}"
    return None


def _source_error(text: str, start: int, root: str) -> Optional[tuple]:
    """Validate a ``$request.`` / ``$response.`` ``source`` beginning at ``text[start]``."""
    rest = text[start:]
    if rest == "body" or rest.startswith("body#"):
        return _pointer_error(text, start + 5) if rest.startswith("body#") else None
    for kind, checker in (("header.", _token_error), ("query.", None), ("path.", None)):
        if rest.startswith(kind):
            name_start = start + len(kind)
            if checker is not None:
                return checker(text, name_start)
            return _name_error(text, name_start, f"a {kind[:-1]} parameter name")
    return start, f"expected header.NAME, query.NAME, path.NAME or body after '${root}.'"


def _message_error(text: str, start: int) -> Optional[tuple]:
    """Validate an Arazzo 1.1 ``$message.`` source beginning at ``text[start]``."""
    rest = text[start:]
    if rest.startswith("header."):
        return _token_error(text, start + len("header."))
    if rest.startswith("header#"):
        return _pointer_error(text, start + len("header#"))
    for part in ("payload", "body"):
        if rest == part:
            return None
        if rest.startswith(part + "#"):
            return _pointer_error(text, start + len(part) + 1)
        if rest.startswith(part + "."):
            return _name_error(text, start + len(part) + 1, "a field name")
    return start, "expected header, payload or body after '$message.'"


def runtime_expression_error(expression: str) -> Optional[ExpressionIssue]:
    """Parse one whole runtime expression against the Arazzo grammar.

    Args:
        expression: The expression, starting with ``$`` (surrounding whitespace is ignored for
            parsing; positions count from the first non-blank character).

    Returns:
        ``None`` when the expression parses, else an :class:`ExpressionIssue` whose
        ``position`` is the offset of the first character the grammar rejects.
    """
    text = expression.strip()
    error = _whole_error(text)
    if error is None:
        return None
    position, reason = error
    return ExpressionIssue(expression=text, position=position, reason=reason)


def _whole_error(text: str) -> Optional[tuple]:
    """Return ``(offset, reason)`` for the first grammar violation in ``text``, else ``None``."""
    if not text.startswith("$"):
        return 0, "a runtime expression starts with '$'"
    match = re.match(r"\$([A-Za-z]*)", text)
    root = match.group(1) if match else ""
    after = 1 + len(root)
    if root in _BARE_ROOTS:
        if after != len(text):
            return after, f"'${root}' takes nothing after it"
        return None
    if root not in _ALL_ROOTS:
        known = ", ".join("$" + name for name in _ALL_ROOTS)
        return 1, f"unknown expression root '${root}' (expected one of {known})"
    if after == len(text) and root in _MAP_ROOTS:
        return None
    if after >= len(text) or text[after] != ".":
        return after, f"expected '.' after '${root}'"
    start = after + 1
    if root in ("request", "response"):
        return _source_error(text, start, root)
    if root == "message":
        return _message_error(text, start)
    return _name_error(text, start, f"a name after '${root}.'")


def embedded_expression_errors(text: str) -> List[ExpressionIssue]:
    """Check every ``{$…}`` placeholder embedded in a template string.

    Args:
        text: A string that may contain ``{$expression}`` placeholders.

    Returns:
        One issue per malformed placeholder; positions are offsets into ``text``.
    """
    issues: List[ExpressionIssue] = []
    for match in _EMBEDDED.finditer(text):
        inner = match.group(1)
        error = _whole_error(inner)
        if error is not None:
            offset, reason = error
            issues.append(ExpressionIssue(expression=inner, position=match.start(1) + offset, reason=reason))
    return issues


def string_expression_errors(text: str) -> List[ExpressionIssue]:
    """Check a parameter value, payload member or similar string for expression errors.

    A string written as one whole expression is parsed as such; any other string is a literal
    whose ``{$…}`` placeholders, if any, are parsed individually. A literal with no ``$`` is
    never an error.

    Args:
        text: The string as written in the document.

    Returns:
        The issues found (empty when the string is fine).
    """
    if is_whole_expression(text):
        issue = runtime_expression_error(text)
        if issue is None:
            return []
        leading = len(text) - len(text.lstrip())
        return [ExpressionIssue(issue.expression, issue.position + leading, issue.reason)]
    return embedded_expression_errors(text)


def condition_expression_errors(condition: str) -> List[ExpressionIssue]:
    """Check the expression operands of a ``simple`` success-criterion condition.

    Quoted string literals are blanked out first (keeping offsets), so a ``'$5 off'`` literal
    is not read as an expression.

    Args:
        condition: The condition text, e.g. ``$statusCode == 200 && $response.body#/ok``.

    Returns:
        One issue per malformed operand; positions are offsets into ``condition``.
    """
    blanked = _QUOTED.sub(lambda m: " " * len(m.group(0)), condition)
    issues: List[ExpressionIssue] = []
    for match in _CONDITION_OPERAND.finditer(blanked):
        operand = match.group(0)
        error = _whole_error(operand)
        if error is not None:
            offset, reason = error
            issues.append(ExpressionIssue(expression=operand, position=match.start() + offset, reason=reason))
    return issues
