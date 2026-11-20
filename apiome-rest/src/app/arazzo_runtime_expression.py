"""Arazzo runtime expressions and success criteria — COA-1.7 (#7043).

A workflow run (:mod:`app.arazzo_workflow_run`) chains steps together through *runtime
expressions*: a step's parameters and request body read the workflow inputs and earlier steps'
outputs, its outputs read the response it just received, and its ``successCriteria`` are
conditions over that response. This module is the pure half of that: it evaluates expressions
against an :class:`ExpressionContext` and judges criteria, returning the expected-vs-actual
evidence a report shows.

Supported expressions (Arazzo 1.0 / 1.1 "Runtime Expressions"):

* ``$url``, ``$method``, ``$statusCode``;
* ``$request.header.NAME``, ``$request.query.NAME``, ``$request.path.NAME``,
  ``$request.body`` with an optional ``#/json/pointer``;
* ``$response.header.NAME``, ``$response.body`` with an optional ``#/json/pointer``;
* ``$inputs.NAME`` and ``$outputs.NAME`` (a dotted tail or a ``#/pointer`` reads into the value);
* ``$steps.STEP_ID.outputs.NAME`` (same tail rules);
* ``$components.parameters.NAME`` / ``.successActions.NAME`` / ``.failureActions.NAME`` /
  ``.inputs.NAME``.

``$workflows.…`` and ``$sourceDescriptions.…`` name things a single-workflow run does not hold,
so they raise :class:`ExpressionError` rather than evaluating to something misleading.

Criteria: ``simple`` conditions (``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``&&``, ``||``,
``!``, parentheses; number, ``'string'``, ``true``/``false``/``null`` literals; string comparison
is case-insensitive, as the Arazzo specification requires), ``regex`` (a search of the context
value) and ``jsonpath`` (passes when the query over the context value selects anything). ``xpath``
is reported as unsupported, never as passed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "CRITERION_ERROR",
    "CRITERION_FAILED",
    "CRITERION_PASSED",
    "CriterionResult",
    "ExpressionContext",
    "ExpressionError",
    "evaluate_criterion",
    "evaluate_expression",
    "is_status_condition",
    "render_value",
    "resolve_json_pointer",
    "resolve_value",
]

#: A criterion whose condition held.
CRITERION_PASSED = "passed"
#: A criterion whose condition evaluated and did not hold.
CRITERION_FAILED = "failed"
#: A criterion that could not be evaluated (unknown expression, bad regex, unsupported type).
CRITERION_ERROR = "error"

#: A string that is exactly one runtime expression (``$response.body#/id``).
_WHOLE_EXPRESSION = re.compile(r"^\$[A-Za-z][^\s{}]*$")
#: An expression embedded in a string template (``Bearer {$steps.login.outputs.token}``).
_EMBEDDED_EXPRESSION = re.compile(r"\{(\$[A-Za-z][^{}\s]*)\}")
#: A condition that only compares the status code — recorded as a ``status_code`` assertion.
_STATUS_CONDITION = re.compile(r"^\s*\$statusCode\s*(==|!=|<=|>=|<|>)\s*\d{3}\s*$")

#: Bound on rendered evidence values, matching the evidence store's field limits.
_RENDER_LIMIT = 1000


class ExpressionError(ValueError):
    """A runtime expression that cannot be evaluated in the current context.

    The message names the expression and says why, so a report can tell "the response had no
    ``id``" from "this run does not support ``$workflows`` expressions".
    """


@dataclass
class ExpressionContext:
    """Everything a runtime expression can read at one point of a workflow run.

    Attributes:
        inputs: The workflow inputs the run was started with (defaults applied).
        steps: ``{step_id: {output_name: value}}`` for every step that has completed so far.
        outputs: The workflow's own outputs, once evaluated (empty during the steps).
        components: The document's ``components`` object, for ``$components.…`` reads.
        url: The URL of the request just sent (``$url``), when there is one.
        method: The HTTP method just sent (``$method``).
        status_code: The status code just received (``$statusCode``).
        request_headers: Headers of the request just sent (names compared case-insensitively).
        request_query: Query parameters of the request just sent.
        request_path: Path parameters of the request just sent.
        request_body: The request body just sent, parsed.
        response_headers: Headers of the response just received.
        response_body: The response body just received, parsed (raw text when not JSON).
    """

    inputs: Dict[str, Any] = field(default_factory=dict)
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_query: Dict[str, str] = field(default_factory=dict)
    request_path: Dict[str, str] = field(default_factory=dict)
    request_body: Any = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Any = None


@dataclass(frozen=True)
class CriterionResult:
    """The verdict on one success criterion, with the evidence behind it.

    Attributes:
        condition: The condition as written in the document.
        type: ``simple``, ``regex``, ``jsonpath`` or ``xpath``.
        context: The ``context`` expression, for regex and JSONPath criteria.
        outcome: :data:`CRITERION_PASSED`, :data:`CRITERION_FAILED` or :data:`CRITERION_ERROR`.
        expected: What the document requires (the condition, prefixed for regex/JSONPath).
        actual: What was observed — the condition with every expression replaced by its value,
            or the context value a regex/JSONPath was applied to.
        message: Why the criterion failed or could not be evaluated; ``None`` when it passed.
        implicit: ``True`` for the ``2XX`` status check applied to a step that declares no
            criteria of its own.
    """

    condition: str
    type: str
    outcome: str
    expected: str
    actual: Optional[str]
    context: Optional[str] = None
    message: Optional[str] = None
    implicit: bool = False


# =============================================================================================
# Values
# =============================================================================================


def render_value(value: Any, limit: int = _RENDER_LIMIT) -> str:
    """Render a value the way a report quotes it: strings bare, everything else as JSON.

    Args:
        value: Any evaluated value.
        limit: Maximum length; a longer rendering is trimmed and ends with ``…``.

    Returns:
        The rendering.
    """
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            text = str(value)
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Read the value an RFC 6901 JSON Pointer names.

    Args:
        document: The parsed JSON value to read from.
        pointer: The pointer (``""`` or ``"/"``-prefixed; a leading ``#`` is tolerated).

    Returns:
        The value at the pointer.

    Raises:
        ExpressionError: When a segment does not exist or reads into a scalar.
    """
    text = pointer[1:] if pointer.startswith("#") else pointer
    if text == "":
        return document
    if not text.startswith("/"):
        raise ExpressionError(f"JSON Pointer {pointer!r} must start with '/'")
    current = document
    for raw in text.split("/")[1:]:
        segment = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if segment not in current:
                raise ExpressionError(f"JSON Pointer {pointer!r}: no member {segment!r}")
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit() or int(segment) >= len(current):
                raise ExpressionError(f"JSON Pointer {pointer!r}: no index {segment!r}")
            current = current[int(segment)]
        else:
            raise ExpressionError(f"JSON Pointer {pointer!r}: {segment!r} reads into a scalar")
    return current


def _header(headers: Mapping[str, str], name: str, expression: str) -> str:
    """Read a header by case-insensitive name."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    raise ExpressionError(f"{expression}: no header {name!r}")


def _member(values: Mapping[str, Any], tail: str, expression: str, what: str) -> Any:
    """Read ``NAME[.deeper][#/pointer]`` out of a name → value map.

    An exact name match wins, so a name that itself contains a dot still resolves; otherwise the
    dotted segments walk into the value.
    """
    tail, _, pointer = tail.partition("#")
    if tail in values:
        value = values[tail]
    else:
        head, *rest = tail.split(".")
        if head not in values:
            raise ExpressionError(f"{expression}: no {what} named {head!r}")
        value = values[head]
        for segment in rest:
            if isinstance(value, Mapping) and segment in value:
                value = value[segment]
            elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
                value = value[int(segment)]
            else:
                raise ExpressionError(f"{expression}: {what} {head!r} has no {segment!r}")
    if pointer:
        try:
            return resolve_json_pointer(value, pointer)
        except ExpressionError as exc:
            raise ExpressionError(f"{expression}: {exc}") from exc
    return value


def _body(body: Any, pointer: Optional[str], expression: str) -> Any:
    """Read a request/response body, optionally at a JSON Pointer."""
    if pointer is None:
        return body
    try:
        return resolve_json_pointer(body, pointer)
    except ExpressionError as exc:
        raise ExpressionError(f"{expression}: {exc}") from exc


def evaluate_expression(expression: str, context: ExpressionContext) -> Any:
    """Evaluate one runtime expression.

    Args:
        expression: The expression, starting with ``$``.
        context: What the expression may read.

    Returns:
        The value it names — for a body pointer, the JSON value at the pointer.

    Raises:
        ExpressionError: When the expression is malformed, unsupported, or names something the
            context does not hold.
    """
    text = expression.strip()
    if text == "$url":
        if context.url is None:
            raise ExpressionError("$url: no request has been sent")
        return context.url
    if text == "$method":
        if context.method is None:
            raise ExpressionError("$method: no request has been sent")
        return context.method
    if text == "$statusCode":
        if context.status_code is None:
            raise ExpressionError("$statusCode: no response has been received")
        return context.status_code

    for prefix, is_request in (("$request.", True), ("$response.", False)):
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix) :]
        if rest == "body" or rest.startswith("body#"):
            pointer = rest[len("body") + 1 :] if "#" in rest else None
            body = context.request_body if is_request else context.response_body
            if not is_request and context.status_code is None:
                raise ExpressionError(f"{text}: no response has been received")
            return _body(body, pointer, text)
        source, _, name = rest.partition(".")
        if not name:
            raise ExpressionError(f"{text}: expected {prefix}header|query|path.NAME or body")
        if source == "header":
            headers = context.request_headers if is_request else context.response_headers
            return _header(headers, name, text)
        if is_request and source == "query":
            if name not in context.request_query:
                raise ExpressionError(f"{text}: no query parameter {name!r}")
            return context.request_query[name]
        if is_request and source == "path":
            if name not in context.request_path:
                raise ExpressionError(f"{text}: no path parameter {name!r}")
            return context.request_path[name]
        raise ExpressionError(f"{text}: unknown source {source!r}")

    if text.startswith("$inputs."):
        return _member(context.inputs, text[len("$inputs.") :], text, "input")
    if text.startswith("$outputs."):
        return _member(context.outputs, text[len("$outputs.") :], text, "workflow output")
    if text.startswith("$steps."):
        step_id, _, rest = text[len("$steps.") :].partition(".")
        if not step_id or not rest.startswith("outputs."):
            raise ExpressionError(f"{text}: expected $steps.STEP_ID.outputs.NAME")
        if step_id not in context.steps:
            raise ExpressionError(f"{text}: step {step_id!r} has not completed in this run")
        return _member(context.steps[step_id], rest[len("outputs.") :], text, "output")
    if text.startswith("$components."):
        kind, _, name = text[len("$components.") :].partition(".")
        group = context.components.get(kind)
        if not isinstance(group, Mapping) or not name:
            raise ExpressionError(f"{text}: the document declares no components.{kind}")
        return _member(group, name, text, f"components.{kind} entry")
    if text.startswith("$workflows.") or text.startswith("$sourceDescriptions."):
        raise ExpressionError(
            f"{text}: a single-workflow run does not evaluate $workflows or "
            "$sourceDescriptions expressions"
        )
    raise ExpressionError(f"{text}: not a runtime expression this run understands")


def resolve_value(value: Any, context: ExpressionContext) -> Any:
    """Resolve every runtime expression inside a parameter value or request payload.

    * a string that is exactly one expression becomes the expression's value (keeping its type,
      so ``$inputs.count`` stays a number);
    * a string with ``{$…}`` placeholders has each replaced by the value's rendering;
    * lists and objects are resolved member by member; anything else is a literal.

    Args:
        value: The value as written in the document.
        context: What the expressions may read.

    Returns:
        The resolved value.

    Raises:
        ExpressionError: When any expression inside cannot be evaluated.
    """
    if isinstance(value, str):
        if _WHOLE_EXPRESSION.match(value):
            return evaluate_expression(value, context)
        if "{$" in value:
            return _EMBEDDED_EXPRESSION.sub(
                lambda match: render_value(evaluate_expression(match.group(1), context), 10_000),
                value,
            )
        return value
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if isinstance(value, Mapping):
        return {key: resolve_value(item, context) for key, item in value.items()}
    return value


# =============================================================================================
# Simple conditions
# =============================================================================================

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|<=|>=|&&|\|\||<|>|!|\(|\))
      | (?P<string>'(?:[^']|'')*')
      | (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
      | (?P<expr>\$[^\s=!<>&|()]+)
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    )""",
    re.VERBOSE,
)

_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")


@dataclass
class _Token:
    """One lexed piece of a simple condition."""

    kind: str
    text: str
    value: Any = None


def _tokenize(condition: str) -> List[_Token]:
    """Split a simple condition into tokens.

    Raises:
        ExpressionError: On a character no token starts with.
    """
    tokens: List[_Token] = []
    position = 0
    stripped = condition.rstrip()
    while position < len(stripped):
        match = _TOKEN.match(stripped, position)
        if match is None or match.end() == position:
            raise ExpressionError(
                f"cannot read the condition at {stripped[position:position + 20]!r}"
            )
        position = match.end()
        if match.group("op"):
            tokens.append(_Token("op", match.group("op")))
        elif match.group("string") is not None:
            raw = match.group("string")
            tokens.append(_Token("literal", raw, raw[1:-1].replace("''", "'")))
        elif match.group("number"):
            raw = match.group("number")
            number = float(raw) if any(c in raw for c in ".eE") else int(raw)
            tokens.append(_Token("literal", raw, number))
        elif match.group("expr"):
            tokens.append(_Token("expr", match.group("expr")))
        else:
            word = match.group("word")
            literals = {"true": True, "false": False, "null": None}
            if word not in literals:
                raise ExpressionError(f"unknown word {word!r} in the condition")
            tokens.append(_Token("literal", word, literals[word]))
    return tokens


def _number(value: Any) -> Optional[float]:
    """Return ``value`` as a number when it is one, or a string spelling one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _compare(left: Any, operator: str, right: Any) -> bool:
    """Compare two operands the way an Arazzo simple condition does.

    Numbers (and numeric strings, such as a header value) compare numerically; strings compare
    case-insensitively; anything else compares by equality only.

    Raises:
        ExpressionError: When an ordering operator is applied to operands with no order.
    """
    left_number, right_number = _number(left), _number(right)
    if left_number is not None and right_number is not None:
        a: Any = left_number
        b: Any = right_number
    elif isinstance(left, str) and isinstance(right, str):
        a, b = left.lower(), right.lower()
    else:
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        raise ExpressionError(
            f"cannot order {render_value(left)} and {render_value(right)} with {operator}"
        )
    return {
        "==": a == b,
        "!=": a != b,
        "<": a < b,
        "<=": a <= b,
        ">": a > b,
        ">=": a >= b,
    }[operator]


class _ConditionParser:
    """Recursive-descent evaluator for a simple condition.

    Grammar (lowest precedence first)::

        or      := and ("||" and)*
        and     := unary ("&&" unary)*
        unary   := "!" unary | compare
        compare := operand (COMPARISON operand)?
        operand := EXPRESSION | LITERAL | "(" or ")"

    Evaluating also renders the *actual* text — the condition with each expression replaced by
    its value — which is the evidence a failed criterion shows.
    """

    def __init__(self, tokens: List[_Token], context: ExpressionContext) -> None:
        self.tokens = tokens
        self.index = 0
        self.context = context
        self.rendered: List[str] = []

    def _peek(self) -> Optional[_Token]:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> _Token:
        token = self._peek()
        if token is None:
            raise ExpressionError("the condition ends too early")
        self.index += 1
        return token

    def parse(self) -> bool:
        value = self._or()
        if self._peek() is not None:
            raise ExpressionError(f"unexpected {self._peek().text!r} in the condition")
        return bool(value)

    def _or(self) -> Any:
        value = self._and()
        while (token := self._peek()) is not None and token.text == "||":
            self._take()
            self.rendered.append("||")
            right = self._and()
            value = bool(value) or bool(right)
        return value

    def _and(self) -> Any:
        value = self._unary()
        while (token := self._peek()) is not None and token.text == "&&":
            self._take()
            self.rendered.append("&&")
            right = self._unary()
            value = bool(value) and bool(right)
        return value

    def _unary(self) -> Any:
        token = self._peek()
        if token is not None and token.text == "!":
            self._take()
            self.rendered.append("!")
            return not bool(self._unary())
        return self._compare()

    def _compare(self) -> Any:
        left = self._operand()
        token = self._peek()
        if token is not None and token.kind == "op" and token.text in _COMPARISONS:
            self._take()
            self.rendered.append(token.text)
            right = self._operand()
            return _compare(left, token.text, right)
        return left

    def _operand(self) -> Any:
        token = self._take()
        if token.kind == "literal":
            self.rendered.append(token.text)
            return token.value
        if token.kind == "expr":
            value = evaluate_expression(token.text, self.context)
            self.rendered.append(
                "'" + value + "'" if isinstance(value, str) else render_value(value, 200)
            )
            return value
        if token.text == "(":
            self.rendered.append("(")
            value = self._or()
            closing = self._take()
            if closing.text != ")":
                raise ExpressionError("a '(' in the condition is never closed")
            self.rendered.append(")")
            return value
        raise ExpressionError(f"unexpected {token.text!r} in the condition")


def _evaluate_simple(condition: str, context: ExpressionContext) -> Tuple[bool, str]:
    """Evaluate a simple condition.

    Returns:
        ``(held, actual)`` — whether the condition held, and the rendered actual text.

    Raises:
        ExpressionError: When the condition cannot be parsed or an expression cannot be read.
    """
    parser = _ConditionParser(_tokenize(condition), context)
    held = parser.parse()
    return held, " ".join(parser.rendered)


# =============================================================================================
# Criteria
# =============================================================================================


def _criterion_type(raw: Mapping[str, Any]) -> str:
    """Normalise a criterion's ``type`` (a string, or an expression-type object)."""
    declared = raw.get("type")
    if isinstance(declared, Mapping):
        declared = declared.get("type")
    text = str(declared or "simple").strip().lower()
    return text or "simple"


def is_status_condition(condition: str) -> bool:
    """Whether a simple condition only compares ``$statusCode`` with a status code.

    Args:
        condition: The condition text.

    Returns:
        ``True`` for ``$statusCode == 200`` and the like — recorded as a ``status_code``
        assertion so evidence readers see the expected status as such.
    """
    return bool(_STATUS_CONDITION.match(condition or ""))


def _jsonpath_matches(condition: str, value: Any) -> bool:
    """Run a JSONPath query over ``value``; it matches when it selects anything.

    Raises:
        ExpressionError: When the query cannot be parsed.
    """
    from jsonpath_ng.exceptions import JsonPathLexerError, JsonPathParserError
    from jsonpath_ng.ext import parse as parse_jsonpath

    try:
        query = parse_jsonpath(condition)
    except (JsonPathLexerError, JsonPathParserError, Exception) as exc:  # noqa: BLE001
        raise ExpressionError(f"cannot parse JSONPath {condition!r}: {exc}") from exc
    return bool(query.find(value))


def evaluate_criterion(
    raw: Any, context: ExpressionContext, *, implicit: bool = False
) -> CriterionResult:
    """Judge one Arazzo Criterion Object against the step's response.

    Args:
        raw: The criterion as written (``{condition, context?, type?}``).
        context: The step's evaluation context (request sent, response received).
        implicit: Mark the result as the run's own ``2XX`` default, not the document's.

    Returns:
        The :class:`CriterionResult`. Never raises — an unreadable criterion is an ``error``
        result, so one bad condition cannot hide the verdicts of its siblings.
    """
    if not isinstance(raw, Mapping) or not isinstance(raw.get("condition"), str):
        return CriterionResult(
            condition=render_value(raw, 200),
            type="simple",
            outcome=CRITERION_ERROR,
            expected=render_value(raw, 200),
            actual=None,
            message="a criterion must be an object with a string condition",
        )
    condition = raw["condition"]
    kind = _criterion_type(raw)
    context_expression = raw.get("context") if isinstance(raw.get("context"), str) else None

    def _error(message: str, *, actual: Optional[str] = None) -> CriterionResult:
        return CriterionResult(
            condition=condition,
            type=kind,
            context=context_expression,
            outcome=CRITERION_ERROR,
            expected=condition if kind == "simple" else f"{kind} {condition}",
            actual=actual,
            message=message,
            implicit=implicit,
        )

    if kind == "simple":
        try:
            held, actual = _evaluate_simple(condition, context)
        except ExpressionError as exc:
            return _error(str(exc))
        return CriterionResult(
            condition=condition,
            type=kind,
            outcome=CRITERION_PASSED if held else CRITERION_FAILED,
            expected=condition,
            actual=actual,
            message=None if held else f"expected {condition}, got {actual}",
            implicit=implicit,
        )

    if kind not in ("regex", "jsonpath"):
        return _error(f"{kind} criteria are not supported by this runner")
    if not context_expression:
        return _error(f"a {kind} criterion needs a context expression")
    try:
        subject = evaluate_expression(context_expression, context)
    except ExpressionError as exc:
        return _error(str(exc))
    actual = render_value(subject)

    if kind == "regex":
        try:
            held = re.search(condition, subject if isinstance(subject, str) else actual) is not None
        except re.error as exc:
            return _error(f"invalid regular expression: {exc}", actual=actual)
    else:
        try:
            held = _jsonpath_matches(condition, subject)
        except ExpressionError as exc:
            return _error(str(exc), actual=actual)
    expected = f"{kind} {condition} on {context_expression}"
    return CriterionResult(
        condition=condition,
        type=kind,
        context=context_expression,
        outcome=CRITERION_PASSED if held else CRITERION_FAILED,
        expected=expected,
        actual=actual,
        message=None if held else f"{context_expression} does not match {kind} {condition!r}",
        implicit=implicit,
    )
