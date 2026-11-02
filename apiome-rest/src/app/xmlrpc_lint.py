"""XML-RPC lint pack — MFI-21.6 (#3996).

Native, deterministic quality rules for XML-RPC method descriptions (a ``methodCall``, a
``methodResponse`` or a fault), layered on the canonical lint engine (MFI-4.1
:mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`XmlRpcRulePack` is registered under the ``xmlrpc`` format key, so it runs with the
always-on common pack on every XML-RPC artifact. The rules read only the canonical model
:class:`~app.xmlrpc_normalizer.XmlRpcNormalizer` builds — the operation's kind and fault, the
request message's positional ``xmlrpc_params`` (schema and sample per position) and the response
message's ``xmlrpc_result_schema`` / ``xmlrpc_sample``:

* **xmlrpc.method-name-namespaced** (info) — a ``methodName`` without a ``.``: the convention
  is ``object.method`` (``inventory.reserveStock``), which is what ``system.listMethods``
  consumers group by and what every XML-RPC toolkit dispatches on.
* **xmlrpc.system-method-known** (warning) — a method in the reserved ``system.`` namespace
  that is not one of the introspection or multicall methods (``system.listMethods``,
  ``system.methodSignature``, ``system.methodHelp``, ``system.multicall``,
  ``system.getCapabilities``): toolkits reserve the prefix and may refuse to register it.
* **xmlrpc.response-has-value** (warning) — a ``methodResponse`` with no ``<param>``: the
  specification requires exactly one, and most clients fault on an empty one.
* **xmlrpc.fault-described** (warning) — a fault whose ``faultCode`` is missing or ``0``, or
  whose ``faultString`` is empty: the caller learns that something failed, not what.
* **xmlrpc.nil-extension** (info) — a ``<nil/>`` value: it is the ``nil`` extension, not
  XML-RPC 1.0, and a client without it fails to parse the message.
* **xmlrpc.array-item-type-known** (info) — an empty ``<array>``: nothing says what its items
  are, so the catalog records them as strings.
* **xmlrpc.multicall-calls-wellformed** (warning) — a ``system.multicall`` whose single param is
  not an array of structs each carrying ``methodName`` (a string) and ``params`` (an array).

The pack also publishes :data:`JSON_SCHEMA_FOR_VALUE` and :func:`migration_note`, the
migrate-to-JSON-RPC note the normalizer records on each item (``extras["xmlrpc_migration"]``):
the method as the JSON-RPC 2.0 request it becomes and each XML-RPC value kind as the JSON type it
maps to — so an item can be rewritten as an OpenRPC document (the ``openrpc`` target), which is
the cheap adapter's "how do I leave" answer.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi, MessageRole, Operation
from .lint_engine import LintRule, RulePack

__all__ = [
    "JSON_SCHEMA_FOR_VALUE",
    "SYSTEM_METHODS",
    "XmlRpcRulePack",
    "migration_note",
]

#: The methods the reserved ``system.`` namespace holds: the introspection specification's
#: three, ``system.multicall`` and ``system.getCapabilities``.
SYSTEM_METHODS = frozenset(
    {
        "system.listMethods",
        "system.methodSignature",
        "system.methodHelp",
        "system.multicall",
        "system.getCapabilities",
    }
)

#: The JSON type each XML-RPC value kind becomes in a JSON-RPC 2.0 / OpenRPC rewrite.
JSON_SCHEMA_FOR_VALUE: Mapping[str, Dict[str, Any]] = {
    "int": {"type": "integer"},
    "i4": {"type": "integer"},
    "i8": {"type": "integer", "format": "int64"},
    "boolean": {"type": "boolean"},
    "double": {"type": "number"},
    "string": {"type": "string"},
    "dateTime.iso8601": {"type": "string", "format": "date-time"},
    "base64": {"type": "string", "contentEncoding": "base64"},
    "nil": {"type": "null"},
    "struct": {"type": "object"},
    "array": {"type": "array"},
}


def _operation(api: CanonicalApi) -> Optional[Operation]:
    for service in api.services:
        for operation in service.operations:
            return operation
    return None


def _params(operation: Operation) -> List[Mapping[str, Any]]:
    for message in operation.messages:
        if message.role is MessageRole.REQUEST:
            listed = message.extras.get("xmlrpc_params")
            return [p for p in listed if isinstance(p, Mapping)] if isinstance(listed, list) else []
    return []


def _response(operation: Operation) -> Optional[Mapping[str, Any]]:
    for message in operation.messages:
        if message.role is MessageRole.RESPONSE:
            return message.extras
    return None


def _walk(sample: Any, path: str) -> Iterable[Tuple[str, Any]]:
    """Every ``(path, value)`` of a sample literal, depth first."""
    yield path, sample
    if isinstance(sample, Mapping):
        for name, value in sample.items():
            yield from _walk(value, f"{path}.{name}")
    elif isinstance(sample, list):
        for index, value in enumerate(sample):
            yield from _walk(value, f"{path}[{index}]")


def _samples(operation: Operation) -> Iterable[Tuple[str, Any]]:
    """Every sample value the message carries, with its path."""
    for param in _params(operation):
        if "sample" in param:
            yield from _walk(param["sample"], f"params.{param.get('index', 0)}")
    response = _response(operation)
    if response and "xmlrpc_sample" in response:
        yield from _walk(response["xmlrpc_sample"], "params.0")


def _check_method_name_namespaced(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A method name should be namespaced ``object.method``."""
    operation = _operation(api)
    if operation is None or operation.extras.get("xmlrpc_kind") != "methodCall":
        return
    if "." not in operation.name:
        yield (
            "methodName",
            f"Method '{operation.name}' is not namespaced; the convention is object.method "
            f"('inventory.{operation.name}'), which introspection consumers group by.",
        )


def _check_system_method_known(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``system.`` method must be one of the reserved namespace's methods."""
    operation = _operation(api)
    if operation is None or operation.extras.get("xmlrpc_kind") != "methodCall":
        return
    if operation.name.startswith("system.") and operation.name not in SYSTEM_METHODS:
        yield (
            "methodName",
            f"Method '{operation.name}' is in the reserved system. namespace but is not an "
            "introspection or multicall method; toolkits may refuse to register it. Use another "
            "prefix.",
        )


def _check_response_has_value(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``methodResponse`` must carry exactly one param."""
    operation = _operation(api)
    if operation is None or operation.extras.get("xmlrpc_kind") != "methodResponse":
        return
    if _response(operation) is None:
        yield (
            "params",
            "The methodResponse carries no <param>; XML-RPC requires exactly one, and most "
            "clients fault on an empty response.",
        )


def _check_fault_described(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A fault must carry a non-zero ``faultCode`` and a ``faultString``."""
    operation = _operation(api)
    if operation is None or operation.extras.get("xmlrpc_kind") != "fault":
        return
    code, text = operation.extras.get("xmlrpc_fault_code"), operation.extras.get("xmlrpc_fault_string")
    if not code:
        yield ("fault.faultCode", "The fault's faultCode is missing or 0; callers cannot tell faults apart.")
    if not (isinstance(text, str) and text.strip()):
        yield ("fault.faultString", "The fault's faultString is empty; the caller learns nothing about the failure.")


def _check_nil_extension(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``<nil/>`` value relies on the nil extension."""
    operation = _operation(api)
    if operation is None:
        return
    for path, value in _samples(operation):
        if value is None:
            yield (
                path,
                "<nil/> is the nil extension, not XML-RPC 1.0; a client without it fails to parse "
                "the message. Omit the member or use an empty string.",
            )


def _check_array_item_type_known(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """An empty array leaves its item type unknown."""
    operation = _operation(api)
    if operation is None:
        return
    for path, value in _samples(operation):
        if isinstance(value, list) and not value:
            yield (
                path,
                "The <array> is empty, so nothing says what its items are; the catalog records them "
                "as strings. Give the description one element.",
            )


def _check_multicall_calls_wellformed(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A ``system.multicall`` param must be an array of ``{methodName, params}`` structs."""
    operation = _operation(api)
    if operation is None or operation.name != "system.multicall":
        return
    params = _params(operation)
    calls = params[0].get("sample") if params else None
    if len(params) != 1 or not isinstance(calls, list):
        yield ("params.0", "system.multicall takes exactly one param: an array of call structs.")
        return
    for index, call in enumerate(calls):
        if (
            not isinstance(call, Mapping)
            or not isinstance(call.get("methodName"), str)
            or not isinstance(call.get("params"), list)
        ):
            yield (
                f"params.0[{index}]",
                "Each multicall element must be a struct with a methodName string and a params array.",
            )


# --- the migrate-to-JSON-RPC note -------------------------------------------------------------


def _json_for(value: Any) -> Dict[str, Any]:
    """The JSON schema of one parsed XML-RPC value (:class:`~app.xmlrpc_parser.XmlRpcValue`)."""
    kind = getattr(value, "kind", "string")
    schema = dict(JSON_SCHEMA_FOR_VALUE.get(kind, {"type": "string"}))
    if kind == "struct":
        schema["properties"] = {m.name: _json_for(m.value) for m in getattr(value, "members", ())}
    elif kind == "array":
        items = getattr(value, "items", ())
        schema["items"] = _json_for(items[0]) if items else {}
    return schema


def migration_note(source: Any) -> Dict[str, Any]:
    """The migrate-to-JSON-RPC note for a parsed document.

    Args:
        source: The :class:`~app.xmlrpc_parser.XmlRpcDocument` being normalized.

    Returns:
        ``target`` (``openrpc``), a one-line ``summary``, the JSON-RPC 2.0 ``request`` (for a
        call) or ``response`` (for a response or fault) the document becomes, ``value_types``
        (each XML-RPC value kind present with its JSON type) and ``caveats``.
    """
    kind = getattr(source, "kind", "methodCall")
    params = list(getattr(source, "params", ()))
    present: Dict[str, Dict[str, Any]] = {}

    def collect(value: Any) -> None:
        value_kind = getattr(value, "kind", None)
        if value_kind:
            present.setdefault(value_kind, dict(JSON_SCHEMA_FOR_VALUE.get(value_kind, {"type": "string"})))
        for member in getattr(value, "members", ()):
            collect(member.value)
        for item in getattr(value, "items", ()):
            collect(item)

    for value in params:
        collect(value)
    note: Dict[str, Any] = {
        "target": "openrpc",
        "summary": (
            "Rewrite the method as a JSON-RPC 2.0 method described by OpenRPC: positional "
            "params become `params` by position, a struct becomes an object, a fault becomes a "
            "JSON-RPC error."
        ),
        "value_types": present,
        "caveats": [
            "JSON-RPC params are positional or named; XML-RPC's are positional only, so keep the "
            "order and name each param in the OpenRPC description.",
            "dateTime.iso8601 carries no time zone; the JSON-RPC rewrite should state one.",
            "base64 becomes a base64-encoded string; the client decodes it.",
            "A fault's faultCode and faultString become the JSON-RPC error's code and message.",
        ],
    }
    if kind == "methodCall":
        note["request"] = {
            "jsonrpc": "2.0",
            "method": getattr(source, "method_name", None) or "method",
            "params": [_json_for(value) for value in params],
        }
    elif kind == "fault":
        note["response"] = {
            "jsonrpc": "2.0",
            "error": {
                "code": getattr(source, "fault_code", None),
                "message": getattr(source, "fault_string", None),
            },
        }
    else:
        note["response"] = {
            "jsonrpc": "2.0",
            "result": _json_for(params[0]) if params else {},
        }
    return note


class XmlRpcRulePack(RulePack, register=True):
    """Native rules for XML-RPC artifacts (see the module docstring)."""

    format = "xmlrpc"
    pack_id = "xmlrpc"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="xmlrpc.method-name-namespaced",
            category="naming",
            severity="info",
            description="A method name should be namespaced object.method.",
            check=_check_method_name_namespaced,
        ),
        LintRule(
            rule_id="xmlrpc.system-method-known",
            category="naming",
            severity="warning",
            description="A system. method must be an introspection or multicall method.",
            check=_check_system_method_known,
        ),
        LintRule(
            rule_id="xmlrpc.response-has-value",
            category="structure",
            severity="warning",
            description="A methodResponse must carry exactly one param.",
            check=_check_response_has_value,
        ),
        LintRule(
            rule_id="xmlrpc.fault-described",
            category="structure",
            severity="warning",
            description="A fault must carry a non-zero faultCode and a faultString.",
            check=_check_fault_described,
        ),
        LintRule(
            rule_id="xmlrpc.nil-extension",
            category="compatibility",
            severity="info",
            description="A <nil/> value relies on the nil extension.",
            check=_check_nil_extension,
        ),
        LintRule(
            rule_id="xmlrpc.array-item-type-known",
            category="structure",
            severity="info",
            description="An empty array leaves its item type unknown.",
            check=_check_array_item_type_known,
        ),
        LintRule(
            rule_id="xmlrpc.multicall-calls-wellformed",
            category="structure",
            severity="warning",
            description="A system.multicall param must be an array of {methodName, params} structs.",
            check=_check_multicall_calls_wellformed,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the XML-RPC native rules in deterministic execution order."""
        return list(self._RULES)
