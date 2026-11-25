"""The matching engine against the Pact specification test suite — PFX-3.4 (#6934).

Two tables, one runner:

* :data:`SPEC_VECTORS` — every **response** case of the Pact specification test suite, versions
  1 to 4, vendored unchanged under ``tests/fixtures/pact_spec_vectors`` (see its README). Each
  file says whether ``actual`` matches ``expected``; the engine must agree.
* :data:`SUPPLEMENTARY_VECTORS` — cases in the same shape for what the specification suite does
  not exercise: the v3/v4 matchers (``integer``, ``decimal``, ``number``, ``boolean``, ``null``,
  ``include``, ``date`` / ``time`` / ``timestamp``, ``minType`` / ``maxType``, ``arrayContains``,
  ``eachKey`` / ``eachValue``, ``contentType``, ``values``, ``notEmpty``, ``semver``) and
  generators, which verification ignores.

A vector goes through the real pipeline: it becomes a one-interaction pact, the PFX-3.1 compiler
(:func:`app.contract_suite_pact.compile_pact_suite`) compiles it, and the PFX-3.4 engine
(:func:`app.pact_value_match.match_response`) judges ``actual`` against the compiled expectation;
the status is judged from the case's expected status codes, as the runner does.

XML bodies are compared as text, so an XML case that expects a match may fail — but only with a
named mismatch, and an XML case that expects a mismatch must never pass.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pytest

from app.contract_suite_pact import compile_pact_suite
from app.pact_value_match import match_response

#: Where the vendored specification vectors live.
VECTOR_ROOT = Path(__file__).parent / "fixtures" / "pact_spec_vectors"

#: The specification version each vendored directory declares in its pact's metadata.
SPEC_VERSIONS = {"v1": "1.0.0", "v1.1": "1.1.0", "v2": "2.0.0", "v3": "3.0.0", "v4": "4.0"}

#: A 1×1 PNG and the start of a JPEG, as a provider of images returns them.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01])


# =============================================================================================
# Running one vector
# =============================================================================================


def _header(headers: Mapping[str, Any], name: str) -> Optional[str]:
    """A header's value by case-insensitive name, or ``None``."""
    for key, value in headers.items():
        if key.lower() == name:
            return str(value)
    return None


def _actual_content(actual: Mapping[str, Any], v4: bool) -> Tuple[bytes, Optional[str]]:
    """The bytes a provider would send for a vector's ``actual`` response, and their media type.

    Args:
        actual: The vector's ``actual`` object.
        v4: Whether the vector writes Pact 4 bodies (``{content, contentType, encoded}``).

    Returns:
        ``(content, content_type)`` — a missing, ``null`` or ``""`` body is no bytes; a JSON body
        is serialized; a text body is sent as UTF-8; a base64 body is decoded.
    """
    headers = actual.get("headers") or {}
    content_type = _header(headers, "content-type")
    body = actual.get("body")
    encoded: Any = None
    if v4 and isinstance(body, dict) and "content" in body:
        content_type = content_type or body.get("contentType")
        encoded = body.get("encoded")
        body = body.get("content")
    if body is None or body == "":
        return b"", content_type
    if encoded == "base64" and isinstance(body, str):
        return base64.b64decode(body), content_type
    if isinstance(body, str) and "json" not in (content_type or ""):
        return body.encode("utf-8"), content_type
    return json.dumps(body).encode("utf-8"), content_type


def judge(vector: Mapping[str, Any], spec: str) -> List[str]:
    """Run one vector through the compiler and the engine.

    Args:
        vector: ``{"expected": <pact response>, "actual": <response received>}``.
        spec: The specification version the pact declares (``"3.0.0"``).

    Returns:
        The mismatch messages; empty when the engine finds that ``actual`` matches.
    """
    v4 = spec.startswith("4")
    interaction: Dict[str, Any] = {
        "description": "a vector",
        "request": {"method": "GET", "path": "/"},
        "response": vector["expected"],
    }
    if v4:
        interaction["type"] = "Synchronous/HTTP"
    document = {"interactions": [interaction], "metadata": {"pactSpecification": {"version": spec}}}
    manifest = compile_pact_suite(document, consumer="consumer", provider="provider")
    assert len(manifest.cases) == 1, "every vector compiles to one case"
    case = manifest.cases[0]
    assert case.pact is not None

    actual = vector["actual"]
    content, content_type = _actual_content(actual, v4)
    headers = {str(name): str(value) for name, value in (actual.get("headers") or {}).items()}
    if content_type and _header(headers, "content-type") is None:
        headers["Content-Type"] = content_type
    messages = [mismatch.message for mismatch in match_response(case.pact.response, headers=headers, content=content)]
    status = actual.get("status")
    if status is not None and str(status) not in case.expect.status_codes:
        messages.append(f"status: expected one of {case.expect.status_codes}, got {status}")
    return messages


def _is_xml(vector: Mapping[str, Any]) -> bool:
    """Whether a vector's expected body is XML (compared as text by this engine)."""
    expected = vector.get("expected") or {}
    body = expected.get("body")
    media = (_header(expected.get("headers") or {}, "content-type") or "").lower()
    if isinstance(body, dict) and "contentType" in body:
        media = str(body.get("contentType")).lower()
        body = body.get("content")
    # Some cases declare no content type; their body is still an XML document.
    return "xml" in media or (isinstance(body, str) and body.lstrip().startswith("<"))


# =============================================================================================
# The specification suite
# =============================================================================================


def _spec_vectors() -> List[Any]:
    """Every vendored vector as a ``pytest.param`` named ``<version>/<part>/<file>``."""
    params = []
    for directory, spec in SPEC_VERSIONS.items():
        for path in sorted((VECTOR_ROOT / directory / "response").rglob("*.json")):
            name = f"{directory}/{path.parent.name}/{path.stem}"
            params.append(pytest.param(path, spec, id=name))
    return params


SPEC_VECTORS = _spec_vectors()


def test_the_vendored_suite_is_complete() -> None:
    # 35 (v1) + 43 (v1.1) + 85 (v2) + 97 (v3) + 97 (v4) response cases.
    assert len(SPEC_VECTORS) == 357


@pytest.mark.parametrize(("path", "spec"), SPEC_VECTORS)
def test_the_engine_agrees_with_the_specification_suite(path: Path, spec: str) -> None:
    vector = json.loads(path.read_text(encoding="utf-8-sig"))
    messages = judge(vector, spec)
    if vector["match"] and _is_xml(vector):
        # Stricter on XML, never looser: a failure here names what it could not compare.
        assert all(message.endswith(")") and "(rule: " in message for message in messages)
        return
    assert (not messages) == vector["match"], f"{vector.get('comment')}: {messages}"


def test_the_engine_never_passes_an_xml_case_the_suite_expects_to_fail() -> None:
    failing_xml = [
        (path, spec)
        for path, spec in (param.values for param in SPEC_VECTORS)
        if (vector := json.loads(path.read_text(encoding="utf-8-sig")))["match"] is False and _is_xml(vector)
    ]
    assert failing_xml, "the suite has XML cases that must fail"
    for path, spec in failing_xml:
        assert judge(json.loads(path.read_text(encoding="utf-8-sig")), spec), path.name


# =============================================================================================
# Supplementary vectors: the v3/v4 matchers and generators
# =============================================================================================


def _matchers(value: Any) -> Dict[str, Any]:
    """A Pact 3 rule entry: a matcher, a list of them (``AND``), or an entry written in full."""
    if isinstance(value, dict) and "matchers" in value:
        return dict(value)
    return {"matchers": list(value) if isinstance(value, list) else [value]}


def _v3(
    match: bool,
    comment: str,
    expected_body: Any,
    rules: Mapping[str, Any],
    actual_body: Any,
    *,
    generators: Optional[Mapping[str, Any]] = None,
) -> Any:
    """A JSON-body vector in Pact 3 form, as a ``pytest.param`` named by its comment."""
    expected: Dict[str, Any] = {
        "headers": {"Content-Type": "application/json"},
        "body": expected_body,
        "matchingRules": {"body": {path: _matchers(m) for path, m in rules.items()}},
    }
    if generators:
        expected["generators"] = generators
    vector = {
        "match": match,
        "comment": comment,
        "expected": expected,
        "actual": {"headers": {"Content-Type": "application/json"}, "body": actual_body},
    }
    return pytest.param(vector, "3.0.0", id=comment)


def _binary(match: bool, comment: str, value: str, content: bytes, *, media: str = "image/jpeg") -> Any:
    """A Pact 4 binary-body vector judged by a ``contentType`` rule on ``$``."""
    vector = {
        "match": match,
        "comment": comment,
        "expected": {
            "headers": {"Content-Type": media},
            "body": {"contentType": media, "encoded": "base64", "content": base64.b64encode(JPEG).decode()},
            "matchingRules": {
                "body": {"$": {"combine": "AND", "matchers": [{"match": "contentType", "value": value}]}}
            },
        },
        "actual": {
            "headers": {"Content-Type": media},
            "body": {"contentType": media, "encoded": "base64", "content": base64.b64encode(content).decode()},
        },
    }
    return pytest.param(vector, "4.0", id=comment)


SUPPLEMENTARY_VECTORS = [
    # type, minType, maxType (Pact 3 writes min / max on a type matcher)
    _v3(
        True,
        "type matcher accepts a different string",
        {"name": "Ada"},
        {"$.name": {"match": "type"}},
        {"name": "Grace"},
    ),
    _v3(
        False, "type matcher rejects a number for a string", {"name": "Ada"}, {"$.name": {"match": "type"}}, {"name": 7}
    ),
    _v3(True, "minType accepts enough items", {"ids": [1]}, {"$.ids": {"match": "type", "min": 2}}, {"ids": [3, 4, 5]}),
    _v3(False, "minType rejects too few items", {"ids": [1]}, {"$.ids": {"match": "type", "min": 2}}, {"ids": [3]}),
    _v3(
        True, "maxType accepts few enough items", {"ids": [1]}, {"$.ids": {"match": "type", "max": 2}}, {"ids": [3, 4]}
    ),
    _v3(
        False,
        "maxType rejects too many items",
        {"ids": [1]},
        {"$.ids": {"match": "type", "max": 2}},
        {"ids": [1, 2, 3]},
    ),
    _v3(
        False,
        "minType items must be like the example",
        {"ids": [1]},
        {"$.ids": {"match": "type", "min": 1}},
        {"ids": ["x"]},
    ),
    # regex and include
    _v3(
        True,
        "regex matches the whole value",
        {"code": "EUR"},
        {"$.code": {"match": "regex", "regex": "[A-Z]{3}"}},
        {"code": "USD"},
    ),
    _v3(
        False,
        "regex must match the whole value",
        {"code": "EUR"},
        {"$.code": {"match": "regex", "regex": "[A-Z]{3}"}},
        {"code": "USDX"},
    ),
    _v3(
        True,
        "include finds the substring",
        {"s": "hello world"},
        {"$.s": {"match": "include", "value": "world"}},
        {"s": "big world!"},
    ),
    _v3(
        False,
        "include misses the substring",
        {"s": "hello world"},
        {"$.s": {"match": "include", "value": "world"}},
        {"s": "hello"},
    ),
    # number, integer, decimal, boolean, null
    _v3(True, "integer accepts an integer", {"n": 1}, {"$.n": {"match": "integer"}}, {"n": 42}),
    _v3(False, "integer rejects a decimal", {"n": 1}, {"$.n": {"match": "integer"}}, {"n": 4.5}),
    _v3(True, "decimal accepts a decimal", {"n": 1.5}, {"$.n": {"match": "decimal"}}, {"n": 0.25}),
    _v3(False, "decimal rejects an integer", {"n": 1.5}, {"$.n": {"match": "decimal"}}, {"n": 3}),
    _v3(True, "number accepts an integer or a decimal", {"n": 1}, {"$.n": {"match": "number"}}, {"n": 2.5}),
    _v3(False, "number rejects a numeric string", {"n": 1}, {"$.n": {"match": "number"}}, {"n": "2"}),
    _v3(True, "boolean accepts false", {"b": True}, {"$.b": {"match": "boolean"}}, {"b": False}),
    _v3(False, "boolean rejects a string", {"b": True}, {"$.b": {"match": "boolean"}}, {"b": "true"}),
    _v3(True, "null accepts null", {"x": None}, {"$.x": {"match": "null"}}, {"x": None}),
    _v3(False, "null rejects a value", {"x": None}, {"$.x": {"match": "null"}}, {"x": 0}),
    # date, time, timestamp
    _v3(
        True,
        "date with a format",
        {"d": "2026-01-02"},
        {"$.d": {"match": "date", "date": "yyyy-MM-dd"}},
        {"d": "2026-11-25"},
    ),
    _v3(
        False,
        "date in another format",
        {"d": "2026-01-02"},
        {"$.d": {"match": "date", "date": "yyyy-MM-dd"}},
        {"d": "25/11/2026"},
    ),
    _v3(True, "time with a format", {"t": "10:00"}, {"$.t": {"match": "time", "time": "HH:mm"}}, {"t": "23:59"}),
    _v3(
        False,
        "time with seconds when none are expected",
        {"t": "10:00"},
        {"$.t": {"match": "time", "time": "HH:mm"}},
        {"t": "23:59:01"},
    ),
    _v3(
        True,
        "timestamp with an offset",
        {"at": "2026-01-02T03:04:05Z"},
        {"$.at": {"match": "timestamp", "timestamp": "yyyy-MM-dd'T'HH:mm:ssXXX"}},
        {"at": "2026-11-25T08:41:18-07:00"},
    ),
    _v3(
        False,
        "timestamp that is a date",
        {"at": "2026-01-02T03:04:05Z"},
        {"$.at": {"match": "timestamp", "timestamp": "yyyy-MM-dd'T'HH:mm:ssXXX"}},
        {"at": "2026-11-25"},
    ),
    _v3(True, "date with the default format", {"d": "2026-01-02"}, {"$.d": {"match": "date"}}, {"d": "1999-12-31"}),
    # values, notEmpty, semver
    _v3(True, "values ignores keys", {"m": {"a": 1}}, {"$.m": {"match": "values"}}, {"m": {"x": 1, "y": 1}}),
    _v3(False, "values still compares values", {"m": {"a": 1}}, {"$.m": {"match": "values"}}, {"m": {"x": "2"}}),
    _v3(True, "notEmpty accepts a value", {"s": "a"}, {"$.s": {"match": "notEmpty"}}, {"s": "b"}),
    _v3(False, "notEmpty rejects an empty string", {"s": "a"}, {"$.s": {"match": "notEmpty"}}, {"s": ""}),
    _v3(True, "semver accepts a version", {"v": "1.0.0"}, {"$.v": {"match": "semver"}}, {"v": "2.10.3-rc.1"}),
    _v3(False, "semver rejects two parts", {"v": "1.0.0"}, {"$.v": {"match": "semver"}}, {"v": "2.10"}),
    # arrayContains, eachKey, eachValue
    _v3(
        True,
        "arrayContains finds each variant in any order",
        {"events": [{"type": "a", "n": 1}, {"type": "b", "s": "x"}]},
        {
            "$.events": {
                "match": "arrayContains",
                "variants": [
                    {"index": 0, "rules": {"$.n": {"matchers": [{"match": "integer"}]}}},
                    {"index": 1, "rules": {"$.s": {"matchers": [{"match": "type"}]}}},
                ],
            }
        },
        {"events": [{"type": "c"}, {"type": "b", "s": "y"}, {"type": "a", "n": 9}]},
    ),
    _v3(
        False,
        "arrayContains misses a variant",
        {"events": [{"type": "a"}, {"type": "b"}]},
        {"$.events": {"match": "arrayContains", "variants": [{"index": 0, "rules": {}}, {"index": 1, "rules": {}}]}},
        {"events": [{"type": "a"}]},
    ),
    _v3(
        True,
        "eachKey checks every key",
        {"rates": {"EUR": 1.0}},
        {"$.rates": {"match": "eachKey", "rules": [{"match": "regex", "regex": "[A-Z]{3}"}]}},
        {"rates": {"USD": 1.1, "GBP": 0.8}},
    ),
    _v3(
        False,
        "eachKey rejects a key",
        {"rates": {"EUR": 1.0}},
        {"$.rates": {"match": "eachKey", "rules": [{"match": "regex", "regex": "[A-Z]{3}"}]}},
        {"rates": {"usd": 1.1}},
    ),
    _v3(
        True,
        "eachValue checks every value",
        {"tags": {"a": "x"}},
        {"$.tags": {"match": "eachValue", "rules": [{"match": "type"}]}},
        {"tags": {"b": "y", "c": "z"}},
    ),
    _v3(
        False,
        "eachValue rejects a value",
        {"tags": {"a": "x"}},
        {"$.tags": {"match": "eachValue", "rules": [{"match": "type"}]}},
        {"tags": {"b": 1}},
    ),
    # combining and cascading
    _v3(
        True,
        "OR passes when one matcher does",
        {"v": 1},
        {"$.v": {"combine": "OR", "matchers": [{"match": "integer"}, {"match": "null"}]}},
        {"v": None},
    ),
    _v3(
        False,
        "OR fails when no matcher does",
        {"v": 1},
        {"$.v": {"combine": "OR", "matchers": [{"match": "integer"}, {"match": "null"}]}},
        {"v": "one"},
    ),
    _v3(
        True,
        "a type matcher cascades to the items beneath it",
        {"items": [{"id": 1, "name": "a"}]},
        {"$.items": {"match": "type"}},
        {"items": [{"id": 2, "name": "b"}, {"id": 3, "name": "c"}]},
    ),
    # contentType
    _v3(
        True,
        "contentType on a string value",
        {"doc": "{}"},
        {"$.doc": {"match": "contentType", "value": "application/json"}},
        {"doc": '{"a": 1}'},
    ),
    _binary(True, "contentType accepts any JPEG", "image/jpeg", JPEG + b"\x00more"),
    _binary(False, "contentType rejects a PNG for a JPEG", "image/jpeg", PNG),
    _binary(True, "contentType accepts a PNG", "image/png", PNG, media="image/png"),
    _binary(False, "contentType rejects text for an image", "image/png", b"not an image", media="image/png"),
    # generators are ignored on verification
    _v3(
        True,
        "a response generator does not replace the example",
        {"id": 1, "at": "2026-01-02"},
        {"$.id": {"match": "integer"}, "$.at": {"match": "date"}},
        {"id": 99, "at": "2030-12-31"},
        generators={"body": {"$.id": {"type": "RandomInt", "min": 1, "max": 9}, "$.at": {"type": "Date"}}},
    ),
    _v3(
        False,
        "a generator does not loosen the rules",
        {"id": 1},
        {"$.id": {"match": "integer"}},
        {"id": "one"},
        generators={"body": {"$.id": {"type": "RandomInt"}}},
    ),
]


@pytest.mark.parametrize(("vector", "spec"), SUPPLEMENTARY_VECTORS)
def test_the_engine_applies_every_supported_matcher(vector: Mapping[str, Any], spec: str) -> None:
    messages = judge(vector, spec)
    assert (not messages) == vector["match"], f"{vector['comment']}: {messages}"


def test_a_failing_supplementary_vector_names_its_rule() -> None:
    for param in SUPPLEMENTARY_VECTORS:
        vector, spec = param.values
        if not vector["match"]:
            messages = judge(vector, spec)
            assert all("(rule: " in message for message in messages), vector["comment"]
