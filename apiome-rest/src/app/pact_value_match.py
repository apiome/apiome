"""Match a live response against a pact's expectation — the verifier's matching engine (PFX-3.2, #6932).

A pact records one example response and the **matching rules** that widen it: "any integer here",
"a string shaped like this", "at least one item like that one". Provider verification passes when
the response a running provider gives satisfies the example *under those rules*. This module is
that judgment and nothing else: an expectation and what was received in, a list of
:class:`Mismatch` out. No HTTP, no database.

How a response is compared
--------------------------
* **Headers.** Every header the pact records must be present (names are case-insensitive). With a
  header rule the value is matched by it; without one it must be equal, ignoring the spacing after
  commas, and a ``Content-Type`` is equal when the media type and every recorded parameter agree
  (a ``charset`` the provider adds is not a mismatch). Headers the pact does not record are ignored.
* **JSON bodies.** The response may carry more than the pact asks for — extra keys are ignored —
  but never less. A value with no rule must be equal; an array with no rule must have the same
  length. A rule is found by the Pact path-weight algorithm (the most specific path wins) and the
  type matchers **cascade** to everything beneath them, so ``$.items`` matched by type makes every
  item match the recorded item's shape.
* **Other bodies.** Compared as text: equal, or matched by a rule on ``$``. XML is text here too:
  rules on its elements are reported, never applied loosely.
* **Empty bodies.** A pact recording an explicitly empty body (``""``, ``null``) accepts only an
  empty response body (PFX-3.4).
* **Binary bodies.** Judged by a ``contentType`` rule on ``$``, which reads the bytes
  (:mod:`app.pact_content_type`); the recorded example is not compared (PFX-3.4).

What is applied
---------------
Every matcher of Pact specifications 2–4, listed with what it checks in
:data:`VERIFIER_MATCHERS` (the table the documentation publishes), combined with ``AND`` or
``OR`` as the pact says. Generators are ignored: they say how a mock or a test fills a value in,
and the matching rules alone decide what a provider may return (the compiler reports each one).
A ``regex`` matches the whole value, as the reference implementations apply it. The Pact
specification test suite (response cases, v1–v4) runs against this engine in
``tests/test_pact_spec_vectors.py``.

**Nothing passes silently.** A rule this engine cannot apply — a date format with a letter it
does not know, a regex that does not compile or runs too long, a rule below ``$`` on a non-JSON
body, a ``contentType`` naming no type — is a mismatch naming the rule, never a pass.

Every mismatch names the field (``path`` as the pact writes it, ``pointer`` as a JSON Pointer into
the response body), the ``rule`` that failed and where the pact declares it (``rule_pointer``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import regex

from .change_taxonomy_enum import json_pointer_escape
from .contract_suite import PactMatchingRuleEntry, PactResponseExpectation
from .pact_content_type import content_type_matches, detect_content_type
from .pact_interaction_reader import is_json_media_type, media_type_of
from .pact_matching_rules import _matcher_kind, parse_matching_rules, parse_path

__all__ = [
    "MAX_MISMATCHES",
    "VERIFIER_MATCHERS",
    "PART_BODY",
    "PART_HEADER",
    "RULE_EQUALITY",
    "RULE_PRESENCE",
    "Mismatch",
    "date_format_pattern",
    "match_body",
    "match_headers",
    "match_response",
    "mismatch_rule",
]

#: A mismatch on a response header.
PART_HEADER = "header"
#: A mismatch in the response body.
PART_BODY = "body"

#: The rule that applies where the pact declares none: the value must equal the example.
RULE_EQUALITY = "equality"
#: The implicit rule that something the pact records must be there at all.
RULE_PRESENCE = "presence"

#: The most mismatches one response reports; a body wrong everywhere is one failure, not thousands.
MAX_MISMATCHES = 50

#: Matchers that compare shape and therefore apply to everything beneath the path they are on.
_TYPE_MATCHERS = frozenset({"type", "mintype", "maxtype", "minmaxtype"})

#: Matchers that cascade from a parent path to the values beneath it.
_CASCADING = _TYPE_MATCHERS | {"equality"}

#: Bounds that keep a consumer-written regex from holding a worker: seconds, and input lengths.
_REGEX_TIMEOUT_SECONDS = 1.0
_REGEX_PATTERN_LIMIT = 2000
_REGEX_SUBJECT_LIMIT = 200_000

#: How long a rendered value in a message may be.
_RENDER_LIMIT = 200

_SEMVER = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"

#: The formats a date, time or timestamp rule means when it states none.
_DEFAULT_FORMATS = {
    "date": "yyyy-MM-dd",
    "time": "HH:mm:ss",
    "timestamp": "yyyy-MM-dd'T'HH:mm:ss",
    "datetime": "yyyy-MM-dd'T'HH:mm:ss",
}


@dataclass(frozen=True)
class VerifierMatcher:
    """One matcher as the verifier applies it — a row of the published supported-rules table.

    Attributes:
        matcher: The ``match`` value as a pact writes it (``minType`` …).
        versions: The Pact specification versions that define it.
        checks: What the verifier checks, in one sentence.
    """

    matcher: str
    versions: str
    checks: str


#: Every matcher the verifier applies, in documentation order. This table **is** the supported-
#: rules table on the hosted-verification page; the tests hold the two, and the compiler's
#: ``KNOWN_MATCHERS``, together.
VERIFIER_MATCHERS: Tuple[VerifierMatcher, ...] = (
    VerifierMatcher("equality", "2, 3, 4", "The value equals the example; stops a type cascade."),
    VerifierMatcher(
        "type",
        "2, 3, 4",
        "The value has the example's JSON type; cascades to every value beneath it, and an array may "
        "have any length with every item like the first example item.",
    ),
    VerifierMatcher("minType", "2, 3, 4", "A `type` match, and an array has at least `min` items."),
    VerifierMatcher("maxType", "2, 3, 4", "A `type` match, and an array has at most `max` items."),
    VerifierMatcher("minMaxType", "3, 4", "A `type` match with both bounds."),
    VerifierMatcher("regex", "2, 3, 4", "The value, as text, matches the whole expression."),
    VerifierMatcher("include", "3, 4", "The value, as text, contains the string."),
    VerifierMatcher("number", "3, 4", "The value is a JSON number."),
    VerifierMatcher("integer", "3, 4", "The value is a number written without a decimal point (`2`, not `2.0`)."),
    VerifierMatcher("decimal", "3, 4", "The value is a number written with a decimal point (`2.5`, `2.0`)."),
    VerifierMatcher("boolean", "3, 4", "The value is `true` or `false`."),
    VerifierMatcher("null", "3, 4", "The value is `null`."),
    VerifierMatcher("date", "3, 4", "The value has the shape of the rule's Java date format (default `yyyy-MM-dd`)."),
    VerifierMatcher("time", "3, 4", "Likewise for a time format (default `HH:mm:ss`)."),
    VerifierMatcher("timestamp", "3, 4", "Likewise for a timestamp format (default `yyyy-MM-dd'T'HH:mm:ss`)."),
    VerifierMatcher("datetime", "4", "The Pact 4 name of `timestamp`."),
    VerifierMatcher("values", "3, 4", "An object whose keys are free and whose values match the example values."),
    VerifierMatcher("eachKey", "4", "Every key of the object satisfies the nested rules."),
    VerifierMatcher("eachValue", "4", "Every value of the object satisfies the nested rules."),
    VerifierMatcher("arrayContains", "4", "For every variant, some item of the array matches it under its own rules."),
    VerifierMatcher("notEmpty", "4", 'The value is not empty (`""`, `[]`, `{}`, `null`) and has the example\'s type.'),
    VerifierMatcher("semver", "4", "The value is a semantic version (`1.2.3`, `1.2.3-rc.1`)."),
    VerifierMatcher(
        "contentType",
        "3, 4",
        "The content's type, detected from its bytes (magic number, then JSON / XML / text), is the "
        "one named. On `$` it reads the whole body; a non-JSON body is then judged by it alone.",
    ),
    VerifierMatcher(
        "statusCode", "4", "The status is in the named class (`success`, `clientError` …) or list of codes."
    ),
)


@dataclass(frozen=True)
class Mismatch:
    """One way a response disagrees with the pact.

    Attributes:
        part: :data:`PART_HEADER` or :data:`PART_BODY`.
        path: The field as a pact names it: a header name, or a JSONPath (``$.items[0].id``).
        pointer: JSON Pointer of the field in the response body (``/items/0/id``; ``""`` is the
            whole body). Empty for a header.
        rule: The matcher that failed (``type``, ``regex`` …), :data:`RULE_EQUALITY` where the
            pact declares none, or :data:`RULE_PRESENCE` for something missing.
        rule_pointer: JSON Pointer of the rule in the pact document; ``None`` for an implicit rule.
        expected: What the pact asks for, rendered.
        actual: What the provider returned, rendered.
        message: One sentence naming the field, the rule and the difference.
    """

    part: str
    path: str
    pointer: str
    rule: str
    rule_pointer: Optional[str]
    expected: Optional[str]
    actual: Optional[str]
    message: str


# =============================================================================================
# Rendering and small helpers
# =============================================================================================

_RULE_SUFFIX = regex.compile(r" \(rule: ([^)\s]+)\)$")


def mismatch_rule(message: Optional[str]) -> Optional[str]:
    """Read the rule back from a mismatch message.

    Every :attr:`Mismatch.message` ends with ``(rule: <name>)``. Evidence stores the message, not
    the mismatch, so a reader of evidence recovers the rule with this.

    Args:
        message: A mismatch message.

    Returns:
        The rule's name, or ``None`` when the message does not end with one.
    """
    found = _RULE_SUFFIX.search(message or "")
    return found.group(1) if found else None


def _render(value: Any) -> str:
    """Render a value for a message, bounded.

    Args:
        value: Any JSON value.

    Returns:
        Compact JSON, cut to :data:`_RENDER_LIMIT` characters.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= _RENDER_LIMIT else text[: _RENDER_LIMIT - 1] + "…"


def _json_type(value: Any) -> str:
    """The JSON type of a value, with integers and decimals both ``number`` (as Pact compares them)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _equal(expected: Any, actual: Any) -> bool:
    """Deep JSON equality that never reads ``true`` as ``1``."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(_equal(expected[k], actual[k]) for k in expected)
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(_equal(e, a) for e, a in zip(expected, actual))
    if isinstance(expected, (dict, list)) or isinstance(actual, (dict, list)):
        return False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return expected == actual
    return type(expected) is type(actual) and expected == actual


def _path_text(tokens: Sequence[Any]) -> str:
    """Concrete tokens as a JSONPath (``$.items[0].id``)."""
    out = ["$"]
    for token in tokens:
        if isinstance(token, int):
            out.append(f"[{token}]")
        elif str(token).isidentifier():
            out.append(f".{token}")
        else:
            escaped = str(token).replace("\\", "\\\\").replace("'", "\\'")
            out.append(f"['{escaped}']")
    return "".join(out)


def _pointer_text(tokens: Sequence[Any]) -> str:
    """Concrete tokens as a JSON Pointer (``/items/0/id``)."""
    return "".join(f"/{json_pointer_escape(str(token))}" for token in tokens)


def _text(value: Any) -> Optional[str]:
    """A scalar as the text a string matcher sees; ``None`` for a container or ``null``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


def _full_match(pattern: str, subject: str) -> Tuple[Optional[bool], Optional[str]]:
    """Match the **whole** of ``subject`` against ``pattern`` without letting either run away.

    Pact's ``regex`` matcher is a full match, as the reference implementations apply it: the
    expression ``alligator named .{4}`` does not match ``alligator named brent`` even though it
    matches a prefix of it (Pact specification test suite, v3/v4 "plain text regex matching that
    does not match"). Anchors the pact writes (``^…$``) are harmless.

    Args:
        pattern: The regular expression, as the pact wrote it.
        subject: The text to match.

    Returns:
        ``(matched, problem)`` — ``matched`` is ``None`` and ``problem`` says why when the
        expression cannot be applied (too long, does not compile, timed out).
    """
    if len(pattern) > _REGEX_PATTERN_LIMIT:
        return None, f"the expression is longer than {_REGEX_PATTERN_LIMIT} characters"
    if len(subject) > _REGEX_SUBJECT_LIMIT:
        return None, f"the value is longer than {_REGEX_SUBJECT_LIMIT} characters"
    try:
        return regex.fullmatch(pattern, subject, timeout=_REGEX_TIMEOUT_SECONDS) is not None, None
    except TimeoutError:
        return None, f"the expression did not finish within {_REGEX_TIMEOUT_SECONDS:g} s"
    except regex.error as exc:
        return None, f"the expression does not compile ({exc})"


# =============================================================================================
# Date and time formats
# =============================================================================================


def _format_letter(letter: str, count: int) -> Optional[str]:
    """The regex one run of a format letter stands for, or ``None`` for a letter not read here."""
    if letter in "yu":
        return r"\d{2}" if count == 2 else r"[+-]?\d{4,}"
    if letter in "ML":
        return (r"\d{1,2}", r"\d{2}", r"[A-Za-z]{3}")[count - 1] if count <= 3 else r"[A-Za-z]+"
    if letter in "dHhkKms":
        return r"\d{1,2}" if count == 1 else r"\d{2}" if count == 2 else None
    if letter == "D":
        return r"\d{1,3}" if count < 3 else r"\d{3}"
    if letter in "Sn":
        return rf"\d{{{count}}}"
    if letter == "a":
        return r"(?:AM|PM|am|pm)"
    if letter == "E":
        return r"[A-Za-z]{3}" if count <= 3 else r"[A-Za-z]+"
    if letter == "Z":
        return r"[+-]\d{4}" if count <= 3 else r"(?:Z|[+-]\d{2}:\d{2})"
    if letter in "Xx":
        offset = (r"[+-]\d{2}(?:\d{2})?", r"[+-]\d{4}", r"[+-]\d{2}:\d{2}")[min(count, 3) - 1]
        return f"(?:Z|{offset})" if letter == "X" else offset
    if letter == "z":
        return r"[A-Za-z][A-Za-z0-9+:/_-]*"
    if letter == "V":
        return r"[A-Za-z][A-Za-z0-9+:/_-]*" if count == 2 else None
    return None


def date_format_pattern(fmt: str) -> Optional[str]:
    """Translate a Java date format (``yyyy-MM-dd'T'HH:mm:ssXXX``) into an anchored regex.

    The translation checks the **shape** of a value — digits where the format has digits, the
    literals in between — not whether the calendar has such a day.

    Args:
        fmt: The ``format`` of a ``date``, ``time``, ``timestamp`` or ``datetime`` rule.

    Returns:
        The regex, or ``None`` when the format uses a letter this engine does not read or leaves a
        quote open.
    """
    out: List[str] = []
    position = 0
    while position < len(fmt):
        char = fmt[position]
        if char == "'":
            end = position + 1
            literal: List[str] = []
            while True:
                if end >= len(fmt):
                    return None
                if fmt[end] == "'":
                    if end + 1 < len(fmt) and fmt[end + 1] == "'":
                        literal.append("'")
                        end += 2
                        continue
                    break
                literal.append(fmt[end])
                end += 1
            out.append(regex.escape("".join(literal) or "'"))
            position = end + 1
        elif char.isascii() and char.isalpha():
            end = position
            while end < len(fmt) and fmt[end] == char:
                end += 1
            piece = _format_letter(char, end - position)
            if piece is None:
                return None
            out.append(piece)
            position = end
        else:
            out.append(regex.escape(char))
            position += 1
    return "^" + "".join(out) + "$"


# =============================================================================================
# Rules
# =============================================================================================


@dataclass(frozen=True)
class _Rule:
    """One matcher ready to apply.

    Attributes:
        kind: The matcher, lowercase.
        matcher: The matcher object as the pact wrote it.
        pointer: JSON Pointer of the matcher in the pact document, when it has one.
    """

    kind: str
    matcher: Mapping[str, Any]
    pointer: Optional[str]


@dataclass(frozen=True)
class _RuleGroup:
    """The matchers filed at one path.

    Attributes:
        steps: The parsed path (property names, indexes, ``None`` for "any child").
        rules: The matchers.
        combine: ``AND`` or ``OR``.
    """

    steps: Tuple[Any, ...]
    rules: Tuple[_Rule, ...]
    combine: str


@dataclass(frozen=True)
class _Resolved:
    """The rule group that governs one location.

    Attributes:
        group: The group.
        exact: Whether the group's path names this very location (``False``: it cascaded down
            from a parent).
    """

    group: _RuleGroup
    exact: bool


def _weight(steps: Sequence[Any], tokens: Sequence[Any]) -> int:
    """The Pact path weight of a rule path against a concrete location.

    Args:
        steps: The parsed rule path.
        tokens: The concrete location.

    Returns:
        ``0`` when the path does not lead to (or above) the location; otherwise the product of 2
        for the root and each exact step and 1 for each wildcard, so the most specific path wins.
    """
    if len(steps) > len(tokens):
        return 0
    weight = 2
    for step, token in zip(steps, tokens):
        if step is None:
            continue
        if step == token and type(step) is type(token):
            weight *= 2
        else:
            return 0
    return weight


class _BodyRules:
    """The body rules of one expectation, resolvable per location."""

    def __init__(self, entries: Sequence[PactMatchingRuleEntry]) -> None:
        """Group the body rules by path.

        Args:
            entries: The expectation's matching rules; only ``body`` rules are read. A rule whose
                path is not a JSONPath is kept under :attr:`unreadable` so it can be reported.
        """
        grouped: Dict[str, List[PactMatchingRuleEntry]] = {}
        for entry in entries:
            if entry.category == PART_BODY:
                grouped.setdefault(entry.path, []).append(entry)
        self.groups: List[_RuleGroup] = []
        self.unreadable: List[PactMatchingRuleEntry] = []
        for path, members in grouped.items():
            steps = parse_path(path)
            if steps is None:
                self.unreadable.extend(members)
                continue
            self.groups.append(
                _RuleGroup(
                    steps=tuple(steps),
                    rules=tuple(_Rule(m.match, m.matcher, m.pointer) for m in members),
                    combine=members[0].combine.upper(),
                )
            )

    def resolve(self, tokens: Sequence[Any]) -> Optional[_Resolved]:
        """Find the rule group that governs a location.

        Args:
            tokens: The concrete location.

        Returns:
            The heaviest group on the location, or — when none is — the heaviest group above it
            whose matchers cascade. ``None`` when the location is governed by plain equality.
        """
        best: Optional[Tuple[int, int, _RuleGroup]] = None
        for group in self.groups:
            weight = _weight(group.steps, tokens)
            if weight == 0:
                continue
            exact = len(group.steps) == len(tokens)
            if not exact and not all(rule.kind in _CASCADING for rule in group.rules):
                continue
            rank = (weight, len(group.steps))
            if best is None or rank > best[:2]:
                best = (weight, len(group.steps), group)
        if best is None:
            return None
        return _Resolved(group=best[2], exact=len(best[2].steps) == len(tokens))


class _BodyMatch:
    """One comparison of a JSON body: the rules, and the mismatches found so far."""

    def __init__(self, rules: _BodyRules, raw: Optional[bytes] = None) -> None:
        """Start a comparison.

        Args:
            rules: The body rules to apply.
            raw: The body received, undecoded — what a ``contentType`` rule on ``$`` inspects.
        """
        self.rules = rules
        self.raw = raw

    # -- reporting ----------------------------------------------------------------------------

    def _miss(
        self,
        tokens: Sequence[Any],
        rule: str,
        rule_pointer: Optional[str],
        expected: Any,
        actual: Any,
        what: str,
        *,
        raw_expected: bool = False,
    ) -> Mismatch:
        """Build a body mismatch.

        Args:
            tokens: The location.
            rule: The matcher that failed.
            rule_pointer: Where the pact declares it.
            expected: What the pact asks for.
            actual: What was received.
            what: The clause after "at <path>: ".
            raw_expected: Whether ``expected`` is already text (a description, not a value).
        """
        path = _path_text(tokens)
        return Mismatch(
            part=PART_BODY,
            path=path,
            pointer=_pointer_text(tokens),
            rule=rule,
            rule_pointer=rule_pointer,
            expected=str(expected) if raw_expected else _render(expected),
            actual=_render(actual),
            message=f"{path}: {what} (rule: {rule})",
        )

    # -- comparison ---------------------------------------------------------------------------

    def compare(self, expected: Any, actual: Any, tokens: Tuple[Any, ...]) -> List[Mismatch]:
        """Compare one value with its example under whatever rule governs its location.

        Args:
            expected: The example at this location.
            actual: The value received there.
            tokens: The location.

        Returns:
            The mismatches at and beneath the location; empty when it matches.
        """
        resolved = self.rules.resolve(tokens)
        if resolved is None:
            return self._structural(expected, actual, tokens, RULE_EQUALITY, None, typed=False)
        outcomes = [self.apply(rule, expected, actual, tokens, exact=resolved.exact) for rule in resolved.group.rules]
        if resolved.group.combine == "OR":
            return [] if any(not found for found in outcomes) else [m for found in outcomes for m in found]
        return [m for found in outcomes for m in found]

    def apply(self, rule: _Rule, expected: Any, actual: Any, tokens: Tuple[Any, ...], *, exact: bool) -> List[Mismatch]:
        """Apply one matcher to one value.

        Args:
            rule: The matcher.
            expected: The example at the location.
            actual: The value received there.
            tokens: The location.
            exact: Whether the matcher is declared on this location (array bounds apply only then).

        Returns:
            The mismatches; empty when the value satisfies the matcher.
        """
        kind, matcher = rule.kind, rule.matcher
        if kind == "equality":
            return self._structural(expected, actual, tokens, kind, rule.pointer, typed=False)
        if kind in _TYPE_MATCHERS:
            return self._typed(rule, expected, actual, tokens, exact=exact)
        if kind == "notempty":
            if actual in (None, "", [], {}):
                return [
                    self._miss(tokens, kind, rule.pointer, "a non-empty value", actual, "is empty", raw_expected=True)
                ]
            return self._structural(expected, actual, tokens, kind, rule.pointer, typed=True)
        if kind == "values":
            return self._values(rule, expected, actual, tokens)
        if kind in ("eachkey", "eachvalue"):
            return self._each(rule, expected, actual, tokens)
        if kind == "arraycontains":
            return self._array_contains(rule, expected, actual, tokens)
        if kind == "contenttype" and not tokens and self.raw is not None:
            # On the whole JSON body: the bytes must be of the type, and the fields are still
            # compared with the example under their own rules.
            problem = _content_type_problem(matcher, self.raw)
            found = (
                []
                if problem is None
                else [self._miss(tokens, kind, rule.pointer, problem[0], actual, problem[1], raw_expected=True)]
            )
            return found + self._structural(expected, actual, tokens, RULE_EQUALITY, None, typed=False)
        problem = _scalar_problem(kind, matcher, actual)
        if problem is None:
            return []
        wanted, what = problem
        return [self._miss(tokens, kind, rule.pointer, wanted, actual, what, raw_expected=True)]

    def _typed(
        self, rule: _Rule, expected: Any, actual: Any, tokens: Tuple[Any, ...], *, exact: bool
    ) -> List[Mismatch]:
        """Apply a type matcher, with its array bounds when it is declared on this location."""
        found = self._structural(expected, actual, tokens, rule.kind, rule.pointer, typed=True)
        if exact and isinstance(actual, list):
            for bound, word, bad in (
                ("min", "at least", lambda n, lim: n < lim),
                ("max", "at most", lambda n, lim: n > lim),
            ):
                limit = rule.matcher.get(bound)
                if isinstance(limit, int) and not isinstance(limit, bool) and bad(len(actual), limit):
                    found.append(
                        self._miss(
                            tokens,
                            rule.kind,
                            rule.pointer,
                            f"{word} {limit} item(s)",
                            f"{len(actual)} item(s)",
                            f"expected {word} {limit} item(s), got {len(actual)}",
                            raw_expected=True,
                        )
                    )
        return found

    def _structural(
        self,
        expected: Any,
        actual: Any,
        tokens: Tuple[Any, ...],
        rule: str,
        rule_pointer: Optional[str],
        *,
        typed: bool,
    ) -> List[Mismatch]:
        """Compare a value with its example by shape, descending into objects and arrays.

        Args:
            expected: The example.
            actual: The value received.
            tokens: The location.
            rule: The rule to name in a mismatch here.
            rule_pointer: Where the pact declares it.
            typed: ``True`` to compare types (an array may then be any length, each item matching
                the example item); ``False`` to compare values (an array must have the same length).

        Returns:
            The mismatches at and beneath the location.
        """
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return [
                    self._miss(
                        tokens,
                        rule,
                        rule_pointer,
                        "an object",
                        actual,
                        f"expected an object, got {_json_type(actual)}",
                        raw_expected=True,
                    )
                ]
            found: List[Mismatch] = []
            for key in expected:
                child = tokens + (str(key),)
                if key not in actual:
                    found.append(
                        Mismatch(
                            part=PART_BODY,
                            path=_path_text(child),
                            pointer=_pointer_text(child),
                            rule=RULE_PRESENCE,
                            rule_pointer=None,
                            expected=_render(expected[key]),
                            actual=None,
                            message=f"{_path_text(child)}: the response has no such field (rule: {RULE_PRESENCE})",
                        )
                    )
                else:
                    found.extend(self.compare(expected[key], actual[key], child))
            return found
        if isinstance(expected, list):
            if not isinstance(actual, list):
                return [
                    self._miss(
                        tokens,
                        rule,
                        rule_pointer,
                        "an array",
                        actual,
                        f"expected an array, got {_json_type(actual)}",
                        raw_expected=True,
                    )
                ]
            found = []
            if not typed and len(expected) != len(actual):
                found.append(
                    self._miss(
                        tokens,
                        rule,
                        rule_pointer,
                        f"{len(expected)} item(s)",
                        f"{len(actual)} item(s)",
                        f"expected {len(expected)} item(s), got {len(actual)}",
                        raw_expected=True,
                    )
                )
            if expected:
                for index, item in enumerate(actual):
                    if index >= len(expected) and not typed:
                        break
                    example = expected[index] if index < len(expected) else expected[0]
                    found.extend(self.compare(example, item, tokens + (index,)))
            return found
        if typed:
            if _json_type(expected) == _json_type(actual):
                return []
            return [
                self._miss(
                    tokens,
                    rule,
                    rule_pointer,
                    f"a value of type {_json_type(expected)}",
                    actual,
                    f"expected {_json_type(expected)} (like {_render(expected)}), "
                    f"got {_json_type(actual)} {_render(actual)}",
                    raw_expected=True,
                )
            ]
        if _equal(expected, actual):
            return []
        return [
            self._miss(
                tokens, rule, rule_pointer, expected, actual, f"expected {_render(expected)}, got {_render(actual)}"
            )
        ]

    def _values(self, rule: _Rule, expected: Any, actual: Any, tokens: Tuple[Any, ...]) -> List[Mismatch]:
        """``values``: an object whose keys are free and whose values match the examples."""
        if not isinstance(actual, dict):
            return [
                self._miss(
                    tokens,
                    rule.kind,
                    rule.pointer,
                    "an object",
                    actual,
                    f"expected an object, got {_json_type(actual)}",
                    raw_expected=True,
                )
            ]
        examples = expected if isinstance(expected, dict) else {}
        template = next(iter(examples.values()), None)
        found: List[Mismatch] = []
        for key, value in actual.items():
            if not examples:
                break
            found.extend(self.compare(examples.get(key, template), value, tokens + (str(key),)))
        return found

    def _each(self, rule: _Rule, expected: Any, actual: Any, tokens: Tuple[Any, ...]) -> List[Mismatch]:
        """``eachKey`` / ``eachValue``: every key, or every value, satisfies the nested matchers."""
        if not isinstance(actual, dict):
            return [
                self._miss(
                    tokens,
                    rule.kind,
                    rule.pointer,
                    "an object",
                    actual,
                    f"expected an object, got {_json_type(actual)}",
                    raw_expected=True,
                )
            ]
        nested = [
            _Rule(_matcher_kind(item), item, rule.pointer)
            for item in rule.matcher.get("rules") or []
            if isinstance(item, dict)
        ]
        if not nested:
            return [
                self._miss(
                    tokens,
                    rule.kind,
                    rule.pointer,
                    "nested rules",
                    actual,
                    "the rule lists no matchers to apply, so it cannot be applied",
                    raw_expected=True,
                )
            ]
        examples = expected if isinstance(expected, dict) else {}
        template = next(iter(examples.values()), None)
        found: List[Mismatch] = []
        for key, value in actual.items():
            child = tokens + (str(key),)
            for inner in nested:
                if rule.kind == "eachkey":
                    problem = _scalar_problem(inner.kind, inner.matcher, str(key), textual=True)
                    if problem is not None:
                        found.append(
                            self._miss(
                                child,
                                rule.kind,
                                rule.pointer,
                                problem[0],
                                str(key),
                                f"the key {problem[1]}",
                                raw_expected=True,
                            )
                        )
                elif not examples and inner.kind in _CASCADING:
                    # With no example value there is no type or value to compare against.
                    continue
                else:
                    found.extend(self.apply(inner, examples.get(key, template), value, child, exact=True))
        return found

    def _array_contains(self, rule: _Rule, expected: Any, actual: Any, tokens: Tuple[Any, ...]) -> List[Mismatch]:
        """``arrayContains``: for every variant, some item of the array matches it."""
        if not isinstance(actual, list):
            return [
                self._miss(
                    tokens,
                    rule.kind,
                    rule.pointer,
                    "an array",
                    actual,
                    f"expected an array, got {_json_type(actual)}",
                    raw_expected=True,
                )
            ]
        variants = [v for v in rule.matcher.get("variants") or [] if isinstance(v, dict)]
        if not variants:
            return [
                self._miss(
                    tokens,
                    rule.kind,
                    rule.pointer,
                    "variants",
                    actual,
                    "the rule lists no variants, so it cannot be applied",
                    raw_expected=True,
                )
            ]
        examples = expected if isinstance(expected, list) else []
        found: List[Mismatch] = []
        for position, variant in enumerate(variants):
            index = variant.get("index", position)
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(examples):
                found.append(
                    self._miss(
                        tokens,
                        rule.kind,
                        rule.pointer,
                        f"variant {position}",
                        actual,
                        f"variant {position} names no example item, so it cannot be applied",
                        raw_expected=True,
                    )
                )
                continue
            entries = [
                PactMatchingRuleEntry(
                    category=PART_BODY,
                    path=r.path,
                    match=r.kind,
                    matcher=dict(r.matcher),
                    combine=r.combine,
                    pointer=r.pointer,
                )
                for r in parse_matching_rules({"body": variant.get("rules") or {}}, rule.pointer or "")
            ]
            inner = _BodyMatch(_BodyRules(entries))
            if not any(not inner.compare(examples[index], item, ()) for item in actual):
                found.append(
                    self._miss(
                        tokens,
                        rule.kind,
                        rule.pointer,
                        examples[index],
                        actual,
                        f"no item matches variant {position} (like {_render(examples[index])})",
                    )
                )
        return found


def _scalar_problem(
    kind: str, matcher: Mapping[str, Any], actual: Any, *, textual: bool = False
) -> Optional[Tuple[str, str]]:
    """Check one value against a matcher that looks only at the value itself.

    Args:
        kind: The matcher, lowercase.
        matcher: The matcher object.
        actual: The value received.
        textual: Whether the value is text by nature (a header value, an object key), so that a
            number or boolean matcher reads the text as one. A JSON string is never a number.

    Returns:
        ``None`` when the value satisfies the matcher; otherwise ``(expected, clause)`` — what was
        wanted, and the clause for the message. A matcher that cannot be applied is a problem too.
    """
    got = f"got {_json_type(actual)} {_render(actual)}"
    if kind == "null":
        return None if actual is None else ("null", f"expected null, {got}")
    if kind == "boolean":
        ok = isinstance(actual, bool) or (textual and actual in ("true", "false"))
        return None if ok else ("a boolean", f"expected a boolean, {got}")
    if kind in ("integer", "decimal", "number"):
        number = actual
        if textual and isinstance(actual, str):
            # A header or a key is text; a number matcher there reads the text as a number.
            try:
                number = int(actual)
            except ValueError:
                try:
                    number = float(actual)
                except ValueError:
                    number = None
        is_number = isinstance(number, (int, float)) and not isinstance(number, bool)
        ok = is_number and (
            kind == "number"
            or (kind == "integer" and isinstance(number, int))
            or (kind == "decimal" and isinstance(number, float))
        )
        article = "an" if kind == "integer" else "a"
        return None if ok else (f"{article} {kind}", f"expected {article} {kind}, {got}")

    text = _text(actual)
    if kind == "regex":
        pattern = matcher.get("regex")
        if not isinstance(pattern, str):
            return ("a regex", "the rule states no regex, so it cannot be applied")
        if text is None:
            return (f"a value matching /{pattern}/", f"expected a value matching /{pattern}/, {got}")
        matched, problem = _full_match(pattern, text)
        if matched is None:
            return (f"a value matching /{pattern}/", f"the regex cannot be applied: {problem}")
        return None if matched else (f"a value matching /{pattern}/", f"expected a value matching /{pattern}/, {got}")
    if kind == "include":
        needle = matcher.get("value")
        if not isinstance(needle, str):
            return ("an included value", "the rule states no value to include, so it cannot be applied")
        ok = text is not None and needle in text
        return (
            None
            if ok
            else (f"a value including {_render(needle)}", f"expected a value including {_render(needle)}, {got}")
        )
    if kind == "semver":
        ok = text is not None and regex.match(_SEMVER, text) is not None
        return None if ok else ("a semantic version", f"expected a semantic version, {got}")
    if kind in _DEFAULT_FORMATS:
        fmt = matcher.get("format") or matcher.get(kind) or _DEFAULT_FORMATS[kind]
        if not isinstance(fmt, str):
            return (f"a {kind}", "the rule's format is not text, so it cannot be applied")
        pattern = date_format_pattern(fmt)
        if pattern is None:
            return (
                f"a {kind} like {fmt}",
                f"the format '{fmt}' uses a pattern letter this verifier does not read, so it cannot be applied",
            )
        ok = isinstance(actual, str) and regex.match(pattern, actual) is not None
        return None if ok else (f"a {kind} like {fmt}", f"expected a {kind} formatted {fmt}, {got}")
    if kind == "contenttype":
        return _content_type_problem(matcher, None if text is None else text.encode("utf-8"))
    return (f"the matcher '{kind}'", f"the matcher '{kind}' is not one this verifier applies, so it cannot be applied")


def _content_type_problem(matcher: Mapping[str, Any], data: Optional[bytes]) -> Optional[Tuple[str, str]]:
    """Check content against a ``contentType`` matcher, by the type its bytes show.

    Args:
        matcher: The matcher object; its ``value`` names the media type.
        data: The content — a whole body, or a string value encoded as UTF-8. ``None`` for a value
            that has no bytes to inspect (an object, an array, ``null``).

    Returns:
        ``None`` when the detected type is the one named; otherwise ``(expected, clause)``.
    """
    wanted = matcher.get("value")
    if not isinstance(wanted, str) or not wanted.strip():
        return ("a content type", "the rule names no content type, so it cannot be applied")
    if data is None:
        return (f"content of type {wanted}", f"expected content of type {wanted}, got a value with no content")
    matched, detected = content_type_matches(data, wanted)
    return None if matched else (f"content of type {wanted}", f"expected content of type {wanted}, detected {detected}")


# =============================================================================================
# Headers
# =============================================================================================


def _normal_header(value: str) -> str:
    """A header value with the spacing around its commas removed."""
    return ",".join(part.strip() for part in value.split(","))


#: Headers whose value is a list of media types with parameters, compared as media types.
_MEDIA_TYPE_HEADERS = frozenset({"content-type", "accept"})


def _media_types_equal(expected: str, actual: str, *, header: str) -> bool:
    """Whether two ``Content-Type`` or ``Accept`` values agree.

    Each comma-separated media type is compared in order with :func:`_content_type_equal`, so
    ``application/json;charset=utf-8`` equals ``application/json; charset=UTF-8``. In ``Accept``
    the media type itself keeps its case (``alligators`` is not ``Alligators``, per the Pact
    specification test suite); only its parameters are compared without it.

    Args:
        expected: The recorded value.
        actual: The value received.
        header: The header's lowercase name.

    Returns:
        Whether both list the same number of media types and each pair agrees.
    """
    wanted = [part for part in expected.split(",") if part.strip()]
    got = [part for part in actual.split(",") if part.strip()]
    if len(wanted) != len(got):
        return False
    for w, g in zip(wanted, got):
        if header == "accept" and w.split(";", 1)[0].strip() != g.split(";", 1)[0].strip():
            return False
        if not _content_type_equal(w, g):
            return False
    return True


def _content_type_equal(expected: str, actual: str) -> bool:
    """Whether two ``Content-Type`` values agree: same media type, every expected parameter present."""

    def parts(value: str) -> Tuple[str, Dict[str, str]]:
        media, *rest = [piece.strip() for piece in value.split(";")]
        params = {}
        for piece in rest:
            name, _, text = piece.partition("=")
            params[name.strip().lower()] = text.strip().strip('"').lower()
        return media.lower(), params

    expected_media, expected_params = parts(expected)
    actual_media, actual_params = parts(actual)
    return expected_media == actual_media and all(actual_params.get(k) == v for k, v in expected_params.items())


def match_headers(
    expected: Mapping[str, str],
    rules: Sequence[PactMatchingRuleEntry],
    actual: Mapping[str, str],
) -> List[Mismatch]:
    """Compare the headers a pact records with the headers a provider returned.

    Args:
        expected: The recorded headers.
        rules: The response's matching rules; only ``header`` rules are read.
        actual: The headers received (several values of one header joined with ``, ``).

    Returns:
        One mismatch per recorded header that is missing or does not match, in name order.
    """
    received = {str(name).lower(): str(value) for name, value in actual.items()}
    by_name: Dict[str, List[PactMatchingRuleEntry]] = {}
    for rule in rules:
        if rule.category == PART_HEADER:
            by_name.setdefault(rule.path.lower(), []).append(rule)

    found: List[Mismatch] = []
    for name in sorted(expected, key=str.lower):
        wanted = expected[name]
        value = received.get(name.lower())
        if value is None:
            found.append(
                Mismatch(
                    PART_HEADER,
                    name,
                    "",
                    RULE_PRESENCE,
                    None,
                    wanted,
                    None,
                    f"header {name}: the response does not carry it (rule: {RULE_PRESENCE})",
                )
            )
            continue
        declared = by_name.get(name.lower())
        if not declared:
            same = (
                _media_types_equal(wanted, value, header=name.lower())
                if name.lower() in _MEDIA_TYPE_HEADERS
                else _normal_header(wanted) == _normal_header(value)
            )
            if not same:
                found.append(
                    Mismatch(
                        PART_HEADER,
                        name,
                        "",
                        RULE_EQUALITY,
                        None,
                        wanted,
                        value,
                        f"header {name}: expected {_render(wanted)}, got {_render(value)} (rule: {RULE_EQUALITY})",
                    )
                )
            continue
        outcomes: List[List[Mismatch]] = []
        for rule in declared:
            problem: Optional[Tuple[Any, str]]
            if rule.match in _TYPE_MATCHERS:
                problem = None  # a header is always text, like its example
            elif rule.match == "equality":
                same = _normal_header(wanted) == _normal_header(value)
                problem = None if same else (wanted, f"expected {_render(wanted)}, got {_render(value)}")
            else:
                problem = _scalar_problem(rule.match, rule.matcher, value, textual=True)
                if problem is not None and "," in value:
                    # A header with several values matches when each value does.
                    parts = [part.strip() for part in value.split(",")]
                    if all(_scalar_problem(rule.match, rule.matcher, part, textual=True) is None for part in parts):
                        problem = None
            outcomes.append(
                []
                if problem is None
                else [
                    Mismatch(
                        PART_HEADER,
                        name,
                        "",
                        rule.match,
                        rule.pointer,
                        problem[0],
                        value,
                        f"header {name}: {problem[1]} (rule: {rule.match})",
                    )
                ]
            )
        if declared[0].combine.upper() == "OR":
            if all(outcomes):
                found.extend(m for group in outcomes for m in group)
        else:
            found.extend(m for group in outcomes for m in group)
    return found


# =============================================================================================
# Bodies
# =============================================================================================


def _decode(content: bytes) -> Optional[str]:
    """A body as text, or ``None`` when it is not UTF-8."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_empty(content: bytes) -> bool:
    """Whether a received body is empty: no bytes, or only whitespace."""
    return not content.strip()


def _judge_by_root_rules(whole: "_BodyMatch", group: _RuleGroup, expected: Any, content: bytes) -> List[Mismatch]:
    """Judge a non-JSON body by the rules filed on ``$`` alone — how ``contentType`` is applied.

    A ``contentType`` rule inspects the bytes (:func:`app.pact_content_type.detect_content_type`);
    any other rule in the group is applied to the body as text, and cannot be applied to a body
    that is not UTF-8. The recorded example is not compared: it is one instance of the type.

    Args:
        whole: The comparison, for building mismatches.
        group: The rule group on ``$``.
        expected: The recorded body (text), or ``None`` when the pact's example is binary.
        content: The body received, undecoded.

    Returns:
        The mismatches, combined by the group's ``AND`` / ``OR``.
    """
    text = _decode(content)
    outcomes: List[List[Mismatch]] = []
    for rule in group.rules:
        if rule.kind == "contenttype":
            problem = _content_type_problem(rule.matcher, content)
            outcomes.append(
                []
                if problem is None
                else [
                    whole._miss(
                        (),
                        rule.kind,
                        rule.pointer,
                        problem[0],
                        _content_summary(content),
                        problem[1],
                        raw_expected=True,
                    )
                ]
            )
        elif text is None:
            outcomes.append(
                [
                    whole._miss(
                        (),
                        rule.kind,
                        rule.pointer,
                        "text content",
                        _content_summary(content),
                        "the body is not UTF-8 text, so this rule cannot be applied to it",
                        raw_expected=True,
                    )
                ]
            )
        else:
            outcomes.append(whole.apply(rule, expected if isinstance(expected, str) else "", text, (), exact=True))
    if group.combine == "OR":
        return [] if any(not found for found in outcomes) else [m for found in outcomes for m in found]
    return [m for found in outcomes for m in found]


def _content_summary(content: bytes) -> str:
    """A body named for a message by its size and detected type, never by its bytes."""
    return f"{len(content)} byte(s) of {detect_content_type(content)}"


def match_body(
    expectation: PactResponseExpectation, content: bytes, content_type: Optional[str] = None
) -> List[Mismatch]:
    """Compare the body a pact records with the body a provider returned.

    Args:
        expectation: The expected response (its body, media type and rules).
        content: The body received, undecoded.
        content_type: The ``Content-Type`` received, when there was one.

    Returns:
        The mismatches, at most :data:`MAX_MISMATCHES`. Empty when the pact records no body (any
        body is then acceptable) or the body matches. A pact that records an **empty** body
        (``""`` or ``null``) accepts only an empty one. A non-JSON body with a ``contentType``
        rule on ``$`` is judged by the rules on ``$`` alone (:func:`_judge_by_root_rules`).
    """
    if not expectation.has_body:
        return []
    rules = _BodyRules(expectation.matching_rules)
    whole = _BodyMatch(rules, content)
    found: List[Mismatch] = [
        whole._miss(
            (),
            entry.match,
            entry.pointer,
            "a JSONPath",
            entry.path,
            f"the rule's path '{entry.path}' is not a JSONPath, so it cannot be applied",
            raw_expected=True,
        )
        for entry in rules.unreadable
    ]
    expected = expectation.body
    if expected == "":
        if not _is_empty(content):
            found.append(
                whole._miss(
                    (),
                    RULE_EQUALITY,
                    None,
                    "an empty body",
                    _content_summary(content),
                    f"expected an empty body, got {len(content)} byte(s)",
                    raw_expected=True,
                )
            )
        return found[:MAX_MISMATCHES]

    as_json = is_json_media_type(expectation.media_type) or (expected is not None and not isinstance(expected, str))
    root = next((group for group in rules.groups if not group.steps), None)
    if not as_json and root is not None and any(rule.kind == "contenttype" for rule in root.rules):
        found.extend(_non_json_field_rules(whole, rules, expectation))
        found.extend(_judge_by_root_rules(whole, root, expected, content))
        return found[:MAX_MISMATCHES]

    if expected is None:
        found.append(
            whole._miss(
                (),
                RULE_EQUALITY,
                None,
                "the recorded body",
                None,
                "the pact's expected body cannot be decoded, so the response body cannot be compared",
                raw_expected=True,
            )
        )
        return found[:MAX_MISMATCHES]

    text = _decode(content)
    if as_json:
        if text is None or not text.strip():
            found.append(
                whole._miss(
                    (), RULE_PRESENCE, None, expected, None, "expected a JSON body, got an empty or binary response"
                )
            )
            return found[:MAX_MISMATCHES]
        try:
            actual = json.loads(text)
        except ValueError:
            found.append(
                whole._miss(
                    (),
                    RULE_EQUALITY,
                    None,
                    "a JSON body",
                    text,
                    f"expected a JSON body, got content that is not JSON (Content-Type: {content_type or 'none'})",
                    raw_expected=True,
                )
            )
            return found[:MAX_MISMATCHES]
        found.extend(whole.compare(expected, actual, ()))
        return found[:MAX_MISMATCHES]

    # A non-JSON body is compared as text; only a rule on the whole body can be applied to it.
    found.extend(_non_json_field_rules(whole, rules, expectation))
    if text is None:
        found.append(
            whole._miss(
                (), RULE_EQUALITY, None, expected, "binary content", "expected text, got content that is not UTF-8"
            )
        )
        return found[:MAX_MISMATCHES]
    found.extend(whole.compare(expected, text, ()))
    return found[:MAX_MISMATCHES]


def _non_json_field_rules(
    whole: "_BodyMatch", rules: _BodyRules, expectation: PactResponseExpectation
) -> List[Mismatch]:
    """Report every rule below ``$`` of a body that is not JSON: it addresses a field there is none of.

    XML bodies are compared as text (their field rules land here too), so a rule on an XML
    element is reported, never silently passed.

    Args:
        whole: The comparison, for building mismatches.
        rules: The body rules.
        expectation: The expected response, for its media type.

    Returns:
        One mismatch per such rule.
    """
    return [
        whole._miss(
            (),
            rule.kind,
            rule.pointer,
            "a JSON body",
            media_type_of(expectation.media_type) or "text",
            "the rule addresses a field of a body that is not JSON, so it cannot be applied",
            raw_expected=True,
        )
        for group in rules.groups
        if group.steps
        for rule in group.rules
    ]


def match_response(
    expectation: PactResponseExpectation,
    *,
    headers: Mapping[str, str],
    content: bytes,
) -> List[Mismatch]:
    """Compare a provider's response with what a pact expects, status aside.

    The status is judged by the runner from the case's own expectation (it also carries Pact 4
    ``statusCode`` rules); this compares everything else.

    Args:
        expectation: The expected response.
        headers: The headers received.
        content: The body received, undecoded.

    Returns:
        Header mismatches, then body mismatches; at most :data:`MAX_MISMATCHES` in all.
    """
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}
    found = match_headers(expectation.headers, expectation.matching_rules, lowered)
    found.extend(match_body(expectation, content, lowered.get("content-type")))
    return found[:MAX_MISMATCHES]
