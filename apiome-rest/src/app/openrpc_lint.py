"""OpenRPC lint pack — MFI-19.1 (#3979).

Native, deterministic quality rules for OpenRPC service descriptions, layered on the canonical
lint engine (MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`)
is. The :class:`OpenRpcRulePack` is registered under the ``openrpc`` format key, so it runs with
the always-on common pack on every OpenRPC artifact. The rules read only the canonical model
(each method's ordered parameters are the request message's ``extras["openrpc_params"]``):

* **openrpc.unique-method-names** (error) — two methods share a name; the specification
  requires method names to be unique, and a JSON-RPC server can dispatch only one of them.
* **openrpc.unique-param-names** (error) — two parameters of a method share a name; the
  specification forbids it, and a by-name call cannot tell them apart.
* **openrpc.required-params-first** (error) — a required parameter follows an optional one; the
  specification requires every required parameter to come first, or a by-position caller cannot
  omit the optional one.
* **openrpc.reserved-method-name** (warning) — a method name begins with ``rpc.``, which
  JSON-RPC 2.0 reserves for rpc-internal methods (``rpc.discover`` itself is exempt).
* **openrpc.method-described** (info) — a method has neither a summary nor a description.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple

from .canonical_model import CanonicalApi, MessageRole, Operation
from .lint_engine import LintRule, RulePack

__all__ = ["OpenRpcRulePack"]

#: The discovery method a service may describe in its own document.
_DISCOVER_METHOD = "rpc.discover"


def _methods(api: CanonicalApi) -> Iterable[Tuple[str, Operation]]:
    """``(lint path, operation)`` for every method, in key order."""
    for service in sorted(api.services, key=lambda s: s.key):
        for operation in sorted(service.operations, key=lambda o: o.key):
            yield f"services.{service.key}.operations.{operation.key}", operation


def _params(operation: Operation) -> List[Dict[str, Any]]:
    """A method's parameters, in declaration order."""
    return [
        param
        for message in operation.messages
        if message.role is MessageRole.REQUEST
        for param in (message.extras.get("openrpc_params") or [])
        if isinstance(param, dict) and isinstance(param.get("name"), str)
    ]


def _check_unique_method_names(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Method names must be unique within the document."""
    for service in sorted(api.services, key=lambda s: s.key):
        counts = Counter(operation.name for operation in service.operations)
        for name in sorted(n for n, count in counts.items() if count > 1):
            yield (
                f"services.{service.key}",
                f"Method name '{name}' is used by {counts[name]} methods; method names must be "
                "unique, and a JSON-RPC server can dispatch only one of them.",
            )


def _check_unique_param_names(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Parameter names must be unique within a method."""
    for path, operation in _methods(api):
        counts = Counter(param["name"] for param in _params(operation))
        for name in sorted(n for n, count in counts.items() if count > 1):
            yield (
                path,
                f"Parameter name '{name}' is used more than once in '{operation.name}'; a "
                "by-name call cannot tell the parameters apart.",
            )


def _check_required_params_first(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every required parameter must come before the first optional one."""
    for path, operation in _methods(api):
        first_optional = None
        for param in _params(operation):
            if param.get("required") is not True:
                first_optional = first_optional or param["name"]
            elif first_optional is not None:
                yield (
                    path,
                    f"Required parameter '{param['name']}' of '{operation.name}' follows optional "
                    f"parameter '{first_optional}'; move every required parameter first.",
                )


def _check_reserved_method_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Method names beginning with ``rpc.`` are reserved by JSON-RPC 2.0."""
    for path, operation in _methods(api):
        if operation.name.startswith("rpc.") and operation.name != _DISCOVER_METHOD:
            yield (
                path,
                f"Method '{operation.name}' begins with 'rpc.', which JSON-RPC 2.0 reserves for "
                "rpc-internal methods and extensions; rename it.",
            )


def _check_method_described(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every method should have a summary or a description."""
    for path, operation in _methods(api):
        if not operation.description and not operation.extras.get("openrpc_summary"):
            yield (path, f"Method '{operation.name}' has no summary or description.")


class OpenRpcRulePack(RulePack, register=True):
    """Native rules for OpenRPC artifacts (see the module docstring)."""

    format = "openrpc"
    pack_id = "openrpc"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="openrpc.unique-method-names",
            category="structure",
            severity="error",
            description="Method names must be unique.",
            check=_check_unique_method_names,
        ),
        LintRule(
            rule_id="openrpc.unique-param-names",
            category="structure",
            severity="error",
            description="Parameter names must be unique within a method.",
            check=_check_unique_param_names,
        ),
        LintRule(
            rule_id="openrpc.required-params-first",
            category="structure",
            severity="error",
            description="Required parameters must come before optional ones.",
            check=_check_required_params_first,
        ),
        LintRule(
            rule_id="openrpc.reserved-method-name",
            category="naming",
            severity="warning",
            description="Method names must not begin with the reserved 'rpc.' prefix.",
            check=_check_reserved_method_name,
        ),
        LintRule(
            rule_id="openrpc.method-described",
            category="documentation",
            severity="info",
            description="Methods should have a summary or a description.",
            check=_check_method_described,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the OpenRPC native rules in deterministic execution order."""
        return list(self._RULES)
