"""Scenario override settings for the hosted mock (#4454, SIM-4.2).

Scenario definitions live in ``versions.mock_settings`` under the
``"scenarios"`` key and are served at runtime by apiome-mock. This module owns
the author-time contract:

* structural limits (scenario count, name shape, sequence length, total size);
* spec conformance — each canned response is checked against the version's
  generated OpenAPI document (operation exists, status defined, media type
  declared, body matches the response schema) unless the response opts out
  with the explicit ``offSpec`` flag (deliberately broken responses);
* canonicalization into the storage shape read by ``apiome_mock.scenarios``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .mock_data_generator import validate_value
from .mock_engine import MockOperation, extract_operations
from .models import MockScenarioResponseSpec, MockScenarioSpec

MAX_SCENARIOS = 50
"""Maximum named scenarios per version."""

MAX_OPERATIONS_PER_SCENARIO = 100
"""Maximum operation overrides per scenario."""

MAX_SETTINGS_BYTES = 262_144
"""Maximum serialized size (bytes) of the scenarios blob (256 KiB)."""

SCENARIO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
"""Header-safe scenario names: alphanumeric start, then ``[A-Za-z0-9._-]``, max 64 chars."""

_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_RESERVED_HEADERS = frozenset({"content-length", "transfer-encoding", "connection"})


def normalize_operation_key(raw: str) -> Optional[str]:
    """Normalize an operation key to canonical ``"METHOD /template"`` form.

    Mirrors ``apiome_mock.scenarios.normalize_operation_key`` so author-time
    validation and the runtime agree on the key shape. Returns ``None`` when
    ``raw`` is not a ``"method path"`` string.
    """
    parts = raw.strip().split(None, 1)
    if len(parts) != 2:
        return None
    method, path = parts
    if not method.isalpha() or not path.startswith("/"):
        return None
    return f"{method.upper()} {path}"


def _deref(node: Any, spec: Mapping[str, Any]) -> Any:
    """Resolve a local ``$ref`` (``#/...``) one level deep; pass through otherwise."""
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node
    target: Any = spec
    for segment in ref[2:].split("/"):
        if not isinstance(target, dict) or segment not in target:
            return node
        target = target[segment]
    return target


def _response_object_for_status(
    operation: Mapping[str, Any], status: int, spec: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """Locate the operation's response object for ``status`` (exact match only)."""
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return None
    response_obj = responses.get(str(status))
    if response_obj is None:
        return None
    resolved = _deref(response_obj, spec)
    return resolved if isinstance(resolved, dict) else None


def _validate_headers(
    headers: Mapping[str, str], *, context: str, errors: List[str]
) -> None:
    """Reject malformed or reserved header names and control characters in values."""
    for name, value in headers.items():
        if not _HEADER_NAME_PATTERN.match(name):
            errors.append(f"{context}: invalid header name '{name}'.")
        elif name.lower() in _RESERVED_HEADERS:
            errors.append(f"{context}: header '{name}' is managed by the server and cannot be overridden.")
        if "\r" in value or "\n" in value:
            errors.append(f"{context}: header '{name}' value must not contain CR/LF characters.")


def _validate_response_against_spec(
    response: MockScenarioResponseSpec,
    *,
    operation: MockOperation,
    spec: Mapping[str, Any],
    context: str,
    errors: List[str],
) -> None:
    """Check one canned response against the operation's spec response schemas."""
    response_obj = _response_object_for_status(operation.operation, response.status, spec)
    if response_obj is None:
        errors.append(
            f"{context}: status {response.status} is not defined for {operation.key} "
            "(set offSpec to allow a deliberately off-spec response)."
        )
        return

    has_body = "body" in response.model_fields_set
    if not has_body:
        return

    content = response_obj.get("content")
    if not isinstance(content, dict) or not content:
        errors.append(
            f"{context}: {operation.key} status {response.status} declares no response content, "
            "but a body was provided (set offSpec to allow it)."
        )
        return

    media_type = response.media_type or "application/json"
    media_obj = content.get(media_type)
    if media_obj is None:
        declared = ", ".join(sorted(content))
        errors.append(
            f"{context}: media type '{media_type}' is not declared for {operation.key} "
            f"status {response.status} (declared: {declared}; set offSpec to allow it)."
        )
        return

    schema = media_obj.get("schema") if isinstance(media_obj, dict) else None
    if not isinstance(schema, dict):
        return
    validation_error = validate_value(response.body, schema, dict(spec))
    if validation_error is not None:
        errors.append(
            f"{context}: body does not match the {operation.key} status {response.status} "
            f"response schema ({validation_error}); set offSpec to store it anyway."
        )


def validate_mock_scenarios(
    scenarios: Mapping[str, MockScenarioSpec],
    spec: Mapping[str, Any],
) -> List[str]:
    """Validate scenario definitions against structural limits and the OpenAPI spec.

    Args:
        scenarios: Parsed scenario definitions keyed by scenario name.
        spec: The version's generated OpenAPI document.

    Returns:
        A list of human-readable error strings; empty when everything is valid.
    """
    errors: List[str] = []

    if len(scenarios) > MAX_SCENARIOS:
        errors.append(f"At most {MAX_SCENARIOS} scenarios are allowed per version.")

    operations_by_key = {op.key: op for op in extract_operations(dict(spec))}

    for name, scenario in scenarios.items():
        if not SCENARIO_NAME_PATTERN.match(name):
            errors.append(
                f"Scenario name '{name}' is invalid: use 1-64 characters from "
                "[A-Za-z0-9._-], starting with a letter or digit."
            )
        if len(scenario.operations) > MAX_OPERATIONS_PER_SCENARIO:
            errors.append(
                f"Scenario '{name}': at most {MAX_OPERATIONS_PER_SCENARIO} operation overrides are allowed."
            )
        for op_key_raw, override in scenario.operations.items():
            context = f"Scenario '{name}', operation '{op_key_raw}'"
            op_key = normalize_operation_key(op_key_raw)
            if op_key is None:
                errors.append(f"{context}: operation keys must look like 'GET /pets/{{petId}}'.")
                continue
            operation = operations_by_key.get(op_key)
            if operation is None:
                errors.append(f"{context}: no operation {op_key} exists in this version's spec.")
                continue
            for index, response in enumerate(override.responses):
                response_context = f"{context}, response {index + 1}"
                _validate_headers(response.headers, context=response_context, errors=errors)
                if not response.off_spec:
                    _validate_response_against_spec(
                        response,
                        operation=operation,
                        spec=spec,
                        context=response_context,
                        errors=errors,
                    )

    storage = scenarios_to_storage(scenarios)
    serialized_size = len(json.dumps(storage, separators=(",", ":"), default=str).encode("utf-8"))
    if serialized_size > MAX_SETTINGS_BYTES:
        errors.append(
            f"Scenario definitions are too large ({serialized_size} bytes; max {MAX_SETTINGS_BYTES})."
        )

    return errors


def _response_to_storage(response: MockScenarioResponseSpec) -> Dict[str, Any]:
    """Canonicalize one response into the JSONB shape read by apiome-mock."""
    out: Dict[str, Any] = {"status": response.status}
    if response.headers:
        out["headers"] = dict(response.headers)
    if "body" in response.model_fields_set:
        out["body"] = response.body
    if response.media_type:
        out["mediaType"] = response.media_type
    if response.off_spec:
        out["offSpec"] = True
    return out


def scenarios_to_storage(scenarios: Mapping[str, MockScenarioSpec]) -> Dict[str, Any]:
    """Canonicalize scenario definitions into the ``mock_settings.scenarios`` shape.

    Operation keys are normalized to ``"METHOD /template"`` so the runtime's
    exact-match lookup always hits.
    """
    out: Dict[str, Any] = {}
    for name, scenario in scenarios.items():
        operations: Dict[str, Any] = {}
        for op_key_raw, override in scenario.operations.items():
            op_key = normalize_operation_key(op_key_raw) or op_key_raw
            operations[op_key] = {
                "responses": [_response_to_storage(response) for response in override.responses]
            }
        entry: Dict[str, Any] = {"operations": operations}
        if scenario.description:
            entry["description"] = scenario.description
        out[name] = entry
    return out


def scenarios_from_storage(mock_settings: Any) -> Tuple[Dict[str, Any], bool]:
    """Extract the stored ``scenarios`` mapping from a raw ``mock_settings`` value.

    Returns ``(scenarios, valid)`` where ``valid`` is ``False`` when the stored
    blob is not a mapping (the caller should treat it as empty).
    """
    settings: Any = mock_settings
    if settings is None:
        return {}, True
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            return {}, False
    if not isinstance(settings, dict):
        return {}, False
    scenarios = settings.get("scenarios")
    if scenarios is None:
        return {}, True
    if not isinstance(scenarios, dict):
        return {}, False
    return scenarios, True
