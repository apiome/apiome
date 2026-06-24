"""Mock request → response resolution for the Mock Server (#3615, RC1-2.2).

This module is the pure, DB-free core of the mock data plane. Given a frozen OpenAPI document and a
mock instance's configuration, it answers a single question: *for this incoming method + path (and
optional scenario), what status / body / latency should the mock return?*

Responsibilities:

* **Operation matching** — turn the spec's templated paths (``/pets/{petId}``) into matchers and pick
  the operation for a concrete request path, extracting path parameters.
* **Scenario resolution** — apply the active scenario's per-operation overrides (status code,
  latency, response body). Scenarios are selectable per instance and, per request, via the
  ``X-Mock-Scenario`` header. Four built-in templates ship out of the box.
* **Response synthesis** — when a scenario does not hard-code a body, generate a schema-valid example
  from the operation's response schema (see :mod:`app.mock_data_generator`) and validate it.

Keeping this logic free of FastAPI / DB lets it be unit-tested directly against synthetic specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .mock_data_generator import generate_example, validate_value

# Built-in scenario templates always available on every instance. "happy-path" is the implicit
# default: no rules, so every operation returns its generated success response. The others are
# global overrides (operation "*" matches every request) demonstrating the status/latency/body axes.
BUILTIN_SCENARIOS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "happy-path",
        "description": "Default: every operation returns its generated success response.",
        "rules": [],
    },
    {
        "name": "server-error",
        "description": "Every endpoint returns HTTP 500.",
        "rules": [
            {
                "operation": "*",
                "status": 500,
                "body": {"error": {"code": "internal_error", "message": "Simulated server error."}},
            }
        ],
    },
    {
        "name": "not-found",
        "description": "Every endpoint returns HTTP 404.",
        "rules": [
            {
                "operation": "*",
                "status": 404,
                "body": {"error": {"code": "not_found", "message": "Simulated not-found."}},
            }
        ],
    },
    {
        "name": "slow",
        "description": "Every endpoint responds normally but with 1500ms of added latency.",
        "rules": [{"operation": "*", "latency_ms": 1500}],
    },
)

_DEFAULT_SCENARIO_NAME = "happy-path"
# Hard ceiling on injectable latency so a misconfigured scenario cannot hang a worker indefinitely.
MAX_LATENCY_MS = 30_000

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


@dataclass
class MockOperation:
    """One OpenAPI operation flattened out of the spec's ``paths``."""

    method: str  # upper-case HTTP method
    path_template: str  # e.g. "/pets/{petId}"
    operation: Dict[str, Any]  # the raw operation object (responses, requestBody, ...)
    _matcher: re.Pattern = field(repr=False)

    @property
    def key(self) -> str:
        """Canonical "METHOD /template" identifier used to target the operation in scenarios."""
        return f"{self.method} {self.path_template}"


@dataclass
class MockResponse:
    """The resolved answer for one mock request."""

    status: int
    body: Any
    latency_ms: int
    matched: bool
    scenario: str
    operation_key: Optional[str] = None
    validation_error: Optional[str] = None
    media_type: str = "application/json"


def _template_to_regex(template: str) -> re.Pattern:
    """Compile an OpenAPI path template into a full-match regex with named groups per ``{param}``.

    ``/pets/{petId}`` → ``^/pets/(?P<petId>[^/]+)$``. Parameter names are sanitised to valid Python
    group names; a single trailing/leading slash is tolerated.
    """
    normalized = "/" + template.strip("/")
    parts = normalized.split("/")
    pattern_parts: List[str] = []
    for part in parts:
        match = re.fullmatch(r"\{(.+?)\}", part)
        if match:
            group = re.sub(r"\W", "_", match.group(1))
            pattern_parts.append(rf"(?P<{group}>[^/]+)")
        else:
            pattern_parts.append(re.escape(part))
    pattern = "/".join(pattern_parts)
    return re.compile(rf"^{pattern}/?$")


def extract_operations(spec: Dict[str, Any]) -> List[MockOperation]:
    """Flatten ``spec.paths`` into a list of :class:`MockOperation` (one per method+path)."""
    operations: List[MockOperation] = []
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        return operations
    for template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        matcher = _template_to_regex(template)
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations.append(
                MockOperation(
                    method=method.upper(),
                    path_template=template,
                    operation=operation,
                    _matcher=matcher,
                )
            )
    return operations


def match_operation(
    operations: List[MockOperation], method: str, path: str
) -> Tuple[Optional[MockOperation], Dict[str, str]]:
    """Find the operation matching ``method`` + concrete ``path``; return it and any path params.

    Literal-segment matches are preferred over parameterised ones (``/pets/mine`` beats
    ``/pets/{petId}``) by sorting candidates so templates with fewer parameters win.
    """
    method = method.upper()
    normalized = "/" + path.strip("/")
    candidates: List[Tuple[int, MockOperation, Dict[str, str]]] = []
    for op in operations:
        if op.method != method:
            continue
        m = op._matcher.match(normalized)
        if m:
            param_count = op.path_template.count("{")
            candidates.append((param_count, op, m.groupdict()))
    if not candidates:
        return None, {}
    candidates.sort(key=lambda c: c[0])
    _, op, params = candidates[0]
    return op, params


def normalize_scenarios(raw: Any) -> List[Dict[str, Any]]:
    """Merge user-supplied scenarios with the built-ins, de-duplicating by name (user wins).

    Returns a clean list always containing the built-in templates. Invalid entries are skipped so a
    malformed stored config can never break the data plane.
    """
    merged: Dict[str, Dict[str, Any]] = {s["name"]: dict(s) for s in BUILTIN_SCENARIOS}
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            rules = entry.get("rules")
            merged[name] = {
                "name": name,
                "description": entry.get("description", ""),
                "rules": rules if isinstance(rules, list) else [],
            }
    # Stable order: built-ins first (in declared order), then any custom scenarios.
    ordered = [merged[s["name"]] for s in BUILTIN_SCENARIOS]
    ordered.extend(v for k, v in merged.items() if k not in {s["name"] for s in BUILTIN_SCENARIOS})
    return ordered


def resolve_active_scenario_name(config: Dict[str, Any], header_override: Optional[str]) -> str:
    """Pick the scenario name: ``X-Mock-Scenario`` header wins, else the instance default."""
    if header_override and header_override.strip():
        return header_override.strip()
    name = config.get("active_scenario")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return _DEFAULT_SCENARIO_NAME


def _find_scenario(scenarios: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for scenario in scenarios:
        if scenario.get("name") == name:
            return scenario
    return None


def _rule_matches(rule: Dict[str, Any], op_key: str, method: str, path_template: str) -> bool:
    """Does a scenario ``rule`` target the given operation?

    A rule targets an operation by either its ``operation`` ("METHOD /template" or "*") or by separate
    ``method`` / ``path`` fields (each "*"-wildcardable). A rule with no targeting fields is global.
    """
    operation = rule.get("operation")
    if isinstance(operation, str):
        op = operation.strip()
        if op == "*":
            return True
        return op.upper() == op_key.upper()
    rule_method = rule.get("method")
    rule_path = rule.get("path")
    if rule_method is None and rule_path is None:
        return True
    method_ok = rule_method in (None, "*") or str(rule_method).upper() == method
    path_ok = rule_path in (None, "*") or str(rule_path) == path_template
    return method_ok and path_ok


def _select_success(operation: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Pick the default success response: lowest 2xx, else ``default``, else 200."""
    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        return 200, None
    success_codes = sorted(
        (int(code) for code in responses if str(code).isdigit() and 200 <= int(code) < 300)
    )
    if success_codes:
        code = success_codes[0]
        return code, responses.get(str(code))
    if "default" in responses:
        return 200, responses.get("default")
    first = sorted(responses.keys())[0]
    status = int(first) if str(first).isdigit() else 200
    return status, responses[first]


def _response_object_for_status(
    operation: Dict[str, Any], status: int
) -> Optional[Dict[str, Any]]:
    """Locate the response object for ``status`` (exact, then ``default``)."""
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    if str(status) in responses:
        return responses[str(status)]
    return responses.get("default")


def _body_from_response_object(
    response_obj: Optional[Dict[str, Any]], spec: Dict[str, Any], seed: int, op_key: str
) -> Tuple[Any, Optional[str], str]:
    """Generate + validate a body from a response object's JSON schema.

    Returns ``(body, validation_error, media_type)``. ``body`` is ``None`` (no content) when the
    response declares no JSON schema, e.g. a ``204``.
    """
    media_type = "application/json"
    if not isinstance(response_obj, dict):
        return None, None, media_type
    content = response_obj.get("content")
    if not isinstance(content, dict) or not content:
        return None, None, media_type
    # Prefer application/json; otherwise take the first declared media type.
    chosen = content.get("application/json")
    if chosen is None:
        media_type, chosen = next(iter(content.items()))
    if not isinstance(chosen, dict):
        return None, None, media_type
    # An author-provided example on the media type takes precedence over synthesis.
    if "example" in chosen:
        return chosen["example"], None, media_type
    examples = chosen.get("examples")
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        value = first.get("value") if isinstance(first, dict) else first
        return value, None, media_type
    schema = chosen.get("schema")
    if not isinstance(schema, dict):
        return None, None, media_type
    body = generate_example(schema, spec, seed=seed, field=op_key)
    error = validate_value(body, schema, spec)
    return body, error, media_type


def resolve_response(
    spec: Dict[str, Any],
    config: Dict[str, Any],
    operations: List[MockOperation],
    method: str,
    path: str,
    *,
    scenario_header: Optional[str] = None,
    seed: int = 0,
) -> MockResponse:
    """Resolve the full mock response for a request.

    Args:
        spec: The frozen OpenAPI document.
        config: The instance ``config`` JSONB (scenarios, active_scenario, seed).
        operations: Pre-extracted operations (see :func:`extract_operations`).
        method: Request HTTP method.
        path: Request path *relative to the mock base URL* (e.g. ``/pets/1``).
        scenario_header: Optional ``X-Mock-Scenario`` per-request override.
        seed: Deterministic generation seed.

    Returns:
        A :class:`MockResponse`. ``matched`` is ``False`` (HTTP 404) when no operation matches.
    """
    scenarios = normalize_scenarios(config.get("scenarios"))
    scenario_name = resolve_active_scenario_name(config, scenario_header)
    scenario = _find_scenario(scenarios, scenario_name)
    if scenario is None:
        # Unknown scenario name → fall back to the default rather than erroring.
        scenario_name = _DEFAULT_SCENARIO_NAME
        scenario = _find_scenario(scenarios, scenario_name)

    op, _params = match_operation(operations, method, path)
    if op is None:
        return MockResponse(
            status=404,
            body={
                "error": {
                    "code": "operation_not_found",
                    "message": f"No mock operation matches {method.upper()} {path}.",
                }
            },
            latency_ms=0,
            matched=False,
            scenario=scenario_name,
        )

    rule = _matching_rule(scenario, op)
    status = _resolve_status(rule, op)
    latency_ms = _resolve_latency(rule)

    if rule is not None and "body" in rule:
        # Scenario hard-codes the body; trust it verbatim (overrides synthesis & validation).
        return MockResponse(
            status=status,
            body=rule["body"],
            latency_ms=latency_ms,
            matched=True,
            scenario=scenario_name,
            operation_key=op.key,
        )

    response_obj = _response_object_for_status(op.operation, status)
    body, validation_error, media_type = _body_from_response_object(
        response_obj, spec, seed, op.key
    )
    return MockResponse(
        status=status,
        body=body,
        latency_ms=latency_ms,
        matched=True,
        scenario=scenario_name,
        operation_key=op.key,
        validation_error=validation_error,
        media_type=media_type,
    )


def _matching_rule(
    scenario: Optional[Dict[str, Any]], op: MockOperation
) -> Optional[Dict[str, Any]]:
    """First rule in ``scenario`` that targets ``op`` (order = author precedence)."""
    if not scenario:
        return None
    rules = scenario.get("rules")
    if not isinstance(rules, list):
        return None
    for rule in rules:
        if isinstance(rule, dict) and _rule_matches(rule, op.key, op.method, op.path_template):
            return rule
    return None


def _resolve_status(rule: Optional[Dict[str, Any]], op: MockOperation) -> int:
    """Scenario rule status if set and valid, else the operation's default success status."""
    if rule is not None:
        candidate = rule.get("status")
        if isinstance(candidate, int) and 100 <= candidate <= 599:
            return candidate
    status, _ = _select_success(op.operation)
    return status


def _resolve_latency(rule: Optional[Dict[str, Any]]) -> int:
    """Clamp a scenario rule's ``latency_ms`` into ``[0, MAX_LATENCY_MS]``."""
    if rule is None:
        return 0
    candidate = rule.get("latency_ms")
    if isinstance(candidate, (int, float)) and candidate > 0:
        return int(min(candidate, MAX_LATENCY_MS))
    return 0
