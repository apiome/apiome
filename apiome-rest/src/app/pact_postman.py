"""Pact → Postman Collection v2.1 — PFX-4.7 (#6944).

A consumer pact records, for each HTTP interaction, the request the consumer sends and the response
it expects. :func:`pact_to_postman` writes that as a Postman Collection v2.1 a provider team can run
in Postman or Newman against a provider build:

* **One request per HTTP interaction**, named by its description, in document order, against a
  ``{{baseUrl}}`` collection variable (its value is the ``base_url`` option, or empty to fill in).
  Method, path, query, headers and the example body are sent as the pact records them; a Pact 4
  body's ``contentType`` becomes a ``Content-Type`` header when the request has none.
* **Provider states** are written into the request's description (``Given: …``): Postman cannot set
  them up, so a run needs the provider in those states first. They are also listed once as a notice.
* **A saved example response** carries the expected status, headers and body.
* **Test scripts** (``tests`` option, on by default) assert the status, each expected header (a
  ``Content-Type`` by media type) and the body with Pact's default rules: an object may carry extra
  keys, an array must have the same length, every other value is equal.

Nothing is dropped silently. What the collection cannot carry is a **notice** with a code, the JSON
Pointer of the entry and a reason:

* message pacts (``messages``, Pact 4 ``Asynchronous/Messages`` and ``Synchronous/Messages``) and
  plugin gRPC calls are **left out** — Postman sends HTTP requests;
* an interaction without a request method, or whose request body is not text, is **left out**;
* a response body or header governed by a **matching rule** is **not asserted** (the test would be
  stricter than the pact), and neither is a response body that is not text;
* request **generators** are **not applied** — the request sends the pact's example values.

Pure: no I/O. The caller reads the pact and checks it with
:func:`app.pact_publication.validate_pact_document` first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from .pact_contract_import import interaction_is_http, pact_specification_version
from .pact_interaction_reader import PactBody, as_dict, media_type_of, read_body, read_headers, read_query
from .pact_plugin_grpc import is_grpc_plugin_interaction

__all__ = [
    "BASE_URL_VARIABLE",
    "CODE_BODY_NOT_ASSERTED",
    "CODE_GENERATORS_NOT_APPLIED",
    "CODE_GRPC_LEFT_OUT",
    "CODE_INTERACTION_INVALID",
    "CODE_MATCHING_RULES_NOT_ASSERTED",
    "CODE_MESSAGE_LEFT_OUT",
    "CODE_PROVIDER_STATES",
    "CODE_REQUEST_BODY_LEFT_OUT",
    "OUTCOME_INFO",
    "OUTCOME_LEFT_OUT",
    "OUTCOME_NOT_APPLIED",
    "OUTCOME_NOT_ASSERTED",
    "POSTMAN_SCHEMA_URL",
    "PactPostmanExport",
    "PactPostmanNotice",
    "pact_to_postman",
]

#: The ``info.schema`` every collection declares.
POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

#: The collection variable request URLs start with.
BASE_URL_VARIABLE = "baseUrl"

#: A message interaction (v3 ``messages``, v4 asynchronous or synchronous messages): left out.
CODE_MESSAGE_LEFT_OUT = "pact-postman-message-left-out"
#: A gRPC call recorded by the protobuf plugin: left out.
CODE_GRPC_LEFT_OUT = "pact-postman-grpc-left-out"
#: An HTTP interaction with no request object or method: left out.
CODE_INTERACTION_INVALID = "pact-postman-interaction-invalid"
#: An HTTP interaction whose request body is not text: left out (Postman's raw body is text).
CODE_REQUEST_BODY_LEFT_OUT = "pact-postman-request-body-left-out"
#: A response body that is not text: kept out of the saved example and not asserted.
CODE_BODY_NOT_ASSERTED = "pact-postman-body-not-asserted"
#: Response values governed by matching rules: not asserted by the test script.
CODE_MATCHING_RULES_NOT_ASSERTED = "pact-postman-matching-rules-not-asserted"
#: Request generators: the request sends the example values instead.
CODE_GENERATORS_NOT_APPLIED = "pact-postman-generators-not-applied"
#: The provider states the exported requests need (information, listed once).
CODE_PROVIDER_STATES = "pact-postman-provider-states"

#: The entry is not in the collection.
OUTCOME_LEFT_OUT = "left-out"
#: The entry is in the collection, but part of the expected response is not checked.
OUTCOME_NOT_ASSERTED = "not-asserted"
#: The entry is in the collection, but a part of the pact has no effect on what it sends.
OUTCOME_NOT_APPLIED = "not-applied"
#: Something to know before running the collection.
OUTCOME_INFO = "info"

#: Media types a body is saved with Postman's ``json`` / ``xml`` raw language for.
_JSON_LANGUAGE = "json"
_XML_LANGUAGE = "xml"
_TEXT_LANGUAGE = "text"

#: The body check of the test scripts: Pact's default (no matching rule) comparison.
_PACT_MATCHES_JS = (
    "function pactMatches(expected, actual) {",
    "  if (Array.isArray(expected)) {",
    "    return Array.isArray(actual) && actual.length === expected.length &&",
    "      expected.every(function (item, index) { return pactMatches(item, actual[index]); });",
    "  }",
    "  if (expected !== null && typeof expected === 'object') {",
    "    return actual !== null && typeof actual === 'object' && !Array.isArray(actual) &&",
    "      Object.keys(expected).every(function (key) {",
    "        return Object.prototype.hasOwnProperty.call(actual, key) && pactMatches(expected[key], actual[key]);",
    "      });",
    "  }",
    "  return expected === actual;",
    "}",
)


@dataclass(frozen=True)
class PactPostmanNotice:
    """Something of the pact the collection does not carry, or a precondition of running it.

    Attributes:
        code: The notice code (``CODE_*``).
        outcome: What happened to the entry (``OUTCOME_*``).
        pointer: JSON Pointer of the pact entry (``/interactions/2``); ``""`` for the whole pact.
        message: The reason, in one sentence.
        description: The interaction's description, when it has one.
        paths: Matching-rule paths or provider-state names the notice is about, if any.
    """

    code: str
    outcome: str
    pointer: str
    message: str
    description: Optional[str] = None
    paths: Tuple[str, ...] = ()

    def as_json(self) -> Dict[str, Any]:
        """The notice as a response object (``paths`` only when there are some)."""
        out: Dict[str, Any] = {
            "code": self.code,
            "outcome": self.outcome,
            "pointer": self.pointer,
            "message": self.message,
        }
        if self.description is not None:
            out["description"] = self.description
        if self.paths:
            out["paths"] = list(self.paths)
        return out


@dataclass
class PactPostmanExport:
    """The collection written from one pact, and what it could not carry.

    Attributes:
        collection: The Postman Collection v2.1 document.
        notices: Every notice, in document order (the provider-states notice last).
        interaction_count: Entries in the pact (interactions and messages).
        exported_count: Requests in the collection.
        left_out_count: Entries left out (each has a ``left-out`` notice).
    """

    collection: Dict[str, Any]
    notices: List[PactPostmanNotice] = field(default_factory=list)
    interaction_count: int = 0
    exported_count: int = 0
    left_out_count: int = 0


def pact_to_postman(
    document: Mapping[str, Any],
    *,
    consumer: str,
    provider: str,
    base_url: Optional[str] = None,
    tests: bool = True,
    description: Optional[str] = None,
) -> PactPostmanExport:
    """Write a pact's HTTP interactions as a Postman Collection v2.1.

    Args:
        document: The parsed, validated Pact document (specification 1–4).
        consumer: The consumer's name, for the collection name.
        provider: The provider's name, likewise.
        base_url: The ``{{baseUrl}}`` value; empty (to fill in) when ``None``.
        tests: Whether each request carries a test script checking the expected response.
        description: The collection description (where the pact came from), if any.

    Returns:
        The :class:`PactPostmanExport`. Never raises for a pact it cannot fully express: what it
        cannot carry becomes a notice.
    """
    writer = _Writer(v4=(pact_specification_version(document) or "").startswith("4"), tests=tests)
    entries = _entries(document)
    for pointer, kind, entry in entries:
        writer.add(pointer, kind, entry)
    writer.report_states()

    info: Dict[str, Any] = {"name": f"Pact: {consumer} → {provider}", "schema": POSTMAN_SCHEMA_URL}
    if description:
        info["description"] = description
    variable: Dict[str, Any] = {"key": BASE_URL_VARIABLE, "value": (base_url or "").rstrip("/")}
    if not base_url:
        variable["description"] = "The provider's base URL: fill in before running."
    collection = {"info": info, "item": writer.items, "variable": [variable]}
    return PactPostmanExport(
        collection=collection,
        notices=writer.notices,
        interaction_count=len(entries),
        exported_count=len(writer.items),
        left_out_count=sum(1 for notice in writer.notices if notice.outcome == OUTCOME_LEFT_OUT),
    )


# =============================================================================================
# Reading the pact
# =============================================================================================


def _entries(document: Mapping[str, Any]) -> List[Tuple[str, str, Any]]:
    """Every interaction and message, in document order, as ``(pointer, array name, entry)``."""
    found: List[Tuple[str, str, Any]] = []
    for kind in ("interactions", "messages"):
        entries = document.get(kind)
        if isinstance(entries, list):
            found.extend((f"/{kind}/{index}", kind, entry) for index, entry in enumerate(entries))
    return found


def _description(entry: Mapping[str, Any]) -> Optional[str]:
    """The interaction's description, or ``None``."""
    value = entry.get("description")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _provider_states(entry: Mapping[str, Any]) -> List[str]:
    """The provider state names of an interaction (v2 ``providerState``, v3/v4 ``providerStates``)."""
    states: List[str] = []
    single = entry.get("providerState")
    if isinstance(single, str) and single.strip():
        states.append(single.strip())
    for state in entry.get("providerStates") or []:
        name = as_dict(state).get("name")
        if isinstance(name, str) and name.strip() and name.strip() not in states:
            states.append(name.strip())
    return states


def _rule_paths(section: Mapping[str, Any], category: str) -> List[str]:
    """The matching-rule paths of one category (``body``, ``header``) of a request or response.

    Reads the Pact 3/4 layout (``matchingRules.body["$.id"]``) and the Pact 2 one
    (``matchingRules["$.body.id"]``, ``["$.headers.Date"]``).

    Args:
        section: The pact ``request`` or ``response``.
        category: ``body`` or ``header``.

    Returns:
        The paths as written, sorted; for headers the header names.
    """
    rules = as_dict(section.get("matchingRules"))
    found = set()
    nested = rules.get(category)
    if isinstance(nested, dict):
        found.update(str(path) for path in nested)
    prefix = "$.body" if category == "body" else "$.headers."
    for key in rules:
        if isinstance(key, str) and key.startswith(prefix):
            found.add(key)
    if category == "header":
        return sorted(path.removeprefix("$.headers.").removeprefix("$.header.") for path in found)
    return sorted(found)


# =============================================================================================
# Writing the collection
# =============================================================================================


def _language(media_type: Optional[str]) -> str:
    """Postman's raw-body language for a media type."""
    if media_type is not None and media_type.endswith(("/json", "+json")):
        return _JSON_LANGUAGE
    if media_type is not None and media_type.endswith(("/xml", "+xml")):
        return _XML_LANGUAGE
    return _TEXT_LANGUAGE


def _body_text(body: PactBody) -> str:
    """A decoded body as the text Postman saves: JSON pretty-printed, text as it is."""
    if isinstance(body.value, str):
        return body.value
    return json.dumps(body.value, indent=2, ensure_ascii=False)


def _status_text(status: int) -> str:
    """The reason phrase of an HTTP status, or the code itself when unknown."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return str(status)


def _js(value: Any) -> str:
    """A value as a JavaScript literal (JSON is one)."""
    return json.dumps(value, ensure_ascii=False)


def _url(path: str, query: Mapping[str, Sequence[str]]) -> Dict[str, Any]:
    """A Postman URL object: ``{{baseUrl}}``, the path segments and the query parameters.

    Args:
        path: The pact request path (``/orders/42``).
        query: Parameter name to its values.

    Returns:
        ``{"raw", "host", "path"[, "query"]}``.
    """
    base = "{{" + BASE_URL_VARIABLE + "}}"
    segments = [segment for segment in path.split("/") if segment]
    pairs = [(name, value) for name, values in query.items() for value in values]
    raw = base + "/" + "/".join(segments) if segments else base + "/"
    if path.endswith("/") and segments:
        raw += "/"
    url: Dict[str, Any] = {"raw": raw, "host": [base], "path": segments}
    if pairs:
        url["raw"] += "?" + "&".join(f"{quote(name, safe='')}={quote(value, safe='')}" for name, value in pairs)
        url["query"] = [{"key": name, "value": value} for name, value in pairs]
    return url


class _Writer:
    """Collects the items and notices of one export (single use)."""

    def __init__(self, *, v4: bool, tests: bool) -> None:
        self._v4 = v4
        self._tests = tests
        self.items: List[Dict[str, Any]] = []
        self.notices: List[PactPostmanNotice] = []
        self._states: List[str] = []

    def _notice(
        self,
        code: str,
        outcome: str,
        pointer: str,
        message: str,
        entry: Mapping[str, Any],
        paths: Sequence[str] = (),
    ) -> None:
        self.notices.append(PactPostmanNotice(code, outcome, pointer, message, _description(entry), tuple(paths)))

    def add(self, pointer: str, kind: str, entry: Any) -> None:
        """Write one pact entry as a request, or report why it is left out.

        Args:
            pointer: The entry's JSON Pointer.
            kind: ``interactions`` or ``messages``.
            entry: The entry.
        """
        data = as_dict(entry)
        if kind == "interactions" and is_grpc_plugin_interaction(data):
            self._notice(
                CODE_GRPC_LEFT_OUT,
                OUTCOME_LEFT_OUT,
                pointer,
                "a gRPC call recorded by the protobuf plugin cannot be sent from Postman's HTTP requests",
                data,
            )
            return
        if kind == "messages" or not interaction_is_http(data):
            self._notice(
                CODE_MESSAGE_LEFT_OUT,
                OUTCOME_LEFT_OUT,
                pointer,
                "a message interaction has no HTTP request for Postman to send",
                data,
            )
            return
        request = as_dict(data.get("request"))
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            self._notice(
                CODE_INTERACTION_INVALID,
                OUTCOME_LEFT_OUT,
                pointer,
                "the interaction has no request method",
                data,
            )
            return
        body = read_body(request, f"{pointer}/request", self._v4)
        if body.problem is not None:
            self._notice(
                CODE_REQUEST_BODY_LEFT_OUT,
                OUTCOME_LEFT_OUT,
                pointer,
                f"the request body cannot be sent as a Postman raw body: {body.problem}",
                data,
            )
            return
        self.items.append(self._item(pointer, data, request, method.strip().upper(), body))

    def _item(
        self, pointer: str, entry: Mapping[str, Any], request: Mapping[str, Any], method: str, body: PactBody
    ) -> Dict[str, Any]:
        """One collection item: the request, its saved example response and its test script."""
        if as_dict(request.get("generators")):
            self._notice(
                CODE_GENERATORS_NOT_APPLIED,
                OUTCOME_NOT_APPLIED,
                pointer,
                "the pact's generators are not applied: the request sends the recorded example values",
                entry,
                sorted(as_dict(request.get("generators"))),
            )
        states = _provider_states(entry)
        for state in states:
            if state not in self._states:
                self._states.append(state)

        headers = read_headers(request)
        header_list = [{"key": name, "value": value} for name, value in headers.values()]
        http: Dict[str, Any] = {
            "method": method,
            "header": header_list,
            "url": _url(str(request.get("path") or "/"), read_query(request)),
        }
        if states:
            http["description"] = "Given: " + "; ".join(states)
        if body.present:
            if body.media_type and "content-type" not in headers:
                header_list.append({"key": "Content-Type", "value": body.media_type})
            media_type = body.media_type or media_type_of(headers.get("content-type", ("", ""))[1])
            if media_type is None and not isinstance(body.value, str):
                media_type = "application/json"
            http["body"] = {
                "mode": "raw",
                "raw": _body_text(body),
                "options": {"raw": {"language": _language(media_type)}},
            }

        name = _description(entry) or f"{method} {request.get('path') or '/'}"
        item: Dict[str, Any] = {"name": name, "request": http}
        response = as_dict(entry.get("response"))
        expected = self._expected(pointer, entry, response)
        item["response"] = [self._example(name, http, expected)]
        if self._tests:
            item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": self._script(expected)}}]
        return item

    def _expected(self, pointer: str, entry: Mapping[str, Any], response: Mapping[str, Any]) -> Dict[str, Any]:
        """What the response must be: status, headers to assert, body to assert, and the example."""
        status = response.get("status")
        code = status if isinstance(status, int) and not isinstance(status, bool) else 200
        headers = read_headers(response)
        header_rules = {name.lower() for name in _rule_paths(response, "header")}
        body_rules = _rule_paths(response, "body")
        body = read_body(response, f"{pointer}/response", self._v4)

        if header_rules or body_rules:
            self._notice(
                CODE_MATCHING_RULES_NOT_ASSERTED,
                OUTCOME_NOT_ASSERTED,
                pointer,
                "the test script does not check values governed by matching rules"
                + (" (the response body is not asserted)" if body_rules else "")
                + "; the saved example shows the recorded values",
                entry,
                [*(f"header {name}" for name in sorted(header_rules)), *body_rules],
            )
        if body.problem is not None:
            self._notice(
                CODE_BODY_NOT_ASSERTED,
                OUTCOME_NOT_ASSERTED,
                pointer,
                f"the response body is not saved or asserted: {body.problem}",
                entry,
            )

        media_type = body.media_type or media_type_of(headers.get("content-type", ("", ""))[1])
        if body.present and body.problem is None and media_type is None and not isinstance(body.value, str):
            media_type = "application/json"
        example_headers = [{"key": name, "value": value} for name, value in headers.values()]
        if body.media_type and "content-type" not in headers:
            example_headers.append({"key": "Content-Type", "value": body.media_type})
        text = _body_text(body) if body.present and body.problem is None else None
        return {
            "code": code,
            "headers": [(name, value) for key, (name, value) in headers.items() if key not in header_rules],
            "body": body if body.present and body.problem is None and not body_rules else None,
            "empty": body.empty and not body_rules,
            "example_headers": example_headers,
            "example_body": text,
            "language": _language(media_type),
        }

    def _example(self, name: str, http: Mapping[str, Any], expected: Mapping[str, Any]) -> Dict[str, Any]:
        """The saved example response: the expected status, headers and body."""
        example: Dict[str, Any] = {
            "name": name,
            "originalRequest": dict(http),
            "status": _status_text(expected["code"]),
            "code": expected["code"],
            "header": expected["example_headers"],
        }
        if expected["example_body"] is not None:
            example["_postman_previewlanguage"] = expected["language"]
            example["body"] = expected["example_body"]
        return example

    def _script(self, expected: Mapping[str, Any]) -> List[str]:
        """The test script lines checking the expected response."""
        code = expected["code"]
        lines = [f"pm.test({_js(f'status is {code}')}, function () {{ pm.response.to.have.status({code}); }});"]
        for name, value in expected["headers"]:
            if name.lower() == "content-type":
                media = media_type_of(value) or ""
                lines.append(
                    f"pm.test({_js(f'header {name}')}, function () {{ pm.expect("
                    f"(pm.response.headers.get({_js(name)}) || '').split(';')[0].trim().toLowerCase())"
                    f".to.eql({_js(media)}); }});"
                )
            else:
                lines.append(
                    f"pm.test({_js(f'header {name}')}, function () {{ pm.expect("
                    f"pm.response.headers.get({_js(name)})).to.eql({_js(value)}); }});"
                )
        body: Optional[PactBody] = expected["body"]
        if body is not None:
            if isinstance(body.value, str):
                lines.append(
                    "pm.test(\"body matches the pact\", function () { pm.expect(pm.response.text())"
                    f".to.eql({_js(body.value)}); }});"
                )
            else:
                lines.extend(_PACT_MATCHES_JS)
                lines.append(
                    "pm.test(\"body matches the pact\", function () { pm.expect(pactMatches("
                    f"{_js(body.value)}, pm.response.json())).to.be.true; }});"
                )
        elif expected["empty"]:
            lines.append("pm.test(\"body is empty\", function () { pm.expect(pm.response.text()).to.eql(''); });")
        return lines

    def report_states(self) -> None:
        """Add the one provider-states notice, when any exported request needs a state."""
        if self._states:
            self.notices.append(
                PactPostmanNotice(
                    CODE_PROVIDER_STATES,
                    OUTCOME_INFO,
                    "",
                    f"{len(self._states)} provider state(s) must be set up on the provider before the run; "
                    "each request's description names its own",
                    None,
                    tuple(self._states),
                )
            )
