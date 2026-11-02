"""OData functions and actions → canonical operations — MFI-11.2 (#3777).

:mod:`app.odata_normalizer` maps entity sets onto CRUD operations; this module maps the rest
of an OData service's callable surface:

* **v4 functions and actions** — every overload of a schema-level ``<Function>`` /
  ``<Action>`` (:class:`~app.odata_parser.ODataOperation`, read from CSDL XML or CSDL JSON).
  A function is side-effect free and invoked with ``GET``; an action with ``POST``. A bound
  operation is addressed through an entity set of its binding type
  (``/Bins({key})/Example.NearestBin``); an unbound one through its container import
  (``/NearestBin``), or has no path when nothing imports it.
* **v2/v3 function imports** — the container-level ``<FunctionImport>``, whose signature is
  inline; its HTTP method is ``m:HttpMethod``, else ``POST`` for a v3 ``IsSideEffecting``
  import, else ``GET``.

**Keys.** Overloads share a name, so an operation is keyed by ``(kind, fully-qualified name,
ordered parameter types)`` — ``Function Example.NearestBin(Example.Bin,Edm.Int32)``. The key
changes only when the signature does, which is what lets a diff align an overload across
revisions and report a changed signature as a removal plus an addition.

**Parameters.** A function's parameters are carried in the URL, so each non-binding parameter
becomes a query :class:`~app.canonical_model.Parameter`; an action's travel in the request
body, which the canonical model has no parameter location for, so they are listed on its
request message's ``extras["odata_parameters"]``. The full ordered signature, binding parameter
included, is always on the operation's ``extras["odata_parameter_signature"]``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical_model import (
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    StreamingMode,
    TypeRef,
)
from .normalizer import Keys
from .odata_parser import (
    ODataEntityContainer,
    ODataEntitySet,
    ODataFunctionImport,
    ODataOperation,
    ODataOperationImport,
)

__all__ = [
    "function_import_operations",
    "operation_key",
    "schema_operations",
]

#: Resolves a CSDL type expression (``Edm.Int32``, ``Collection(NS.Bin)``) to a canonical
#: :class:`TypeRef` — the normalizer's own resolver, so operations and types agree.
TypeResolver = Callable[[str], TypeRef]

_JSON = "application/json"


def operation_key(kind: str, qualified_name: str, parameter_types: Sequence[str]) -> str:
    """The stable canonical key of one OData operation overload.

    Args:
        kind: ``Function``, ``Action`` or (v2/v3) ``FunctionImport``.
        qualified_name: The operation's fully-qualified name (``Example.NearestBin``; for a
            v2/v3 import, ``Container.Name``).
        parameter_types: The parameter type expressions in declaration order, the binding
            parameter first for a bound operation.

    Returns:
        ``"{kind} {qualified_name}({type,type,...})"``.
    """
    return f"{kind} {qualified_name}({','.join(parameter_types)})"


def _collection_item(type_expr: str) -> Tuple[str, bool]:
    """``Collection(T)`` → ``(T, True)``; anything else → ``(type_expr, False)``."""
    stripped = type_expr.strip()
    if stripped.startswith("Collection(") and stripped.endswith(")"):
        return stripped[len("Collection(") : -1].strip(), True
    return stripped, False


def _local_name(type_expr: str) -> str:
    return type_expr.rsplit(".", 1)[-1]


def _binding_set(
    binding_type: str, entity_sets: Sequence[ODataEntitySet]
) -> Optional[ODataEntitySet]:
    """The first entity set whose entity type is ``binding_type`` (qualified or simple name).

    Entity sets are compared by qualified name first, then by simple name, because an entity
    set may name its type through a schema alias.
    """
    for entity_set in entity_sets:
        if entity_set.entity_type == binding_type:
            return entity_set
    local = _local_name(binding_type)
    for entity_set in entity_sets:
        if _local_name(entity_set.entity_type) == local:
            return entity_set
    return None


def _http_path(
    operation: ODataOperation,
    qualified_name: str,
    *,
    imports: Mapping[str, ODataOperationImport],
    entity_sets: Sequence[ODataEntitySet],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Where a v4 operation is invoked, and the extras that explain the choice.

    Returns:
        ``(http_path, extras)``. A bound operation resolves through an entity set of its
        binding type (``odata_binding_set``); an unbound one through its import
        (``odata_import``). When neither resolves the path is ``None``.
    """
    if operation.is_bound and operation.parameters:
        binding_type, is_collection = _collection_item(operation.parameters[0].type_expr)
        entity_set = _binding_set(binding_type, entity_sets)
        if entity_set is None:
            return None, {}
        segment = f"/{entity_set.name}" if is_collection else f"/{entity_set.name}({{key}})"
        return f"{segment}/{qualified_name}", {"odata_binding_set": entity_set.name}
    imported = imports.get(qualified_name)
    if imported is None:
        return None, {}
    extras: Dict[str, Any] = {"odata_import": imported.name}
    if imported.entity_set:
        extras["odata_import_entity_set"] = imported.entity_set
    return f"/{imported.name}", extras


def _query_parameter(op_key: str, name: str, type_ref: TypeRef, nullable: Optional[bool]) -> Parameter:
    """A URL-carried parameter; required when it is declared non-nullable."""
    return Parameter(
        key=Keys.parameter(op_key, "query", name),
        name=name,
        location=ParameterLocation.QUERY,
        type=type_ref,
        required=nullable is False,
    )


def _with_nullable(type_ref: TypeRef, nullable: Optional[bool]) -> TypeRef:
    """``type_ref`` with the declared nullability applied, when it was declared."""
    if nullable is None:
        return type_ref
    return type_ref.model_copy(update={"nullable": nullable})


def _response(op_key: str, return_type: Optional[str], nullable: Optional[bool], resolve: TypeResolver) -> Message:
    """``200`` with the return type, or ``204`` for an operation that returns nothing."""
    if not return_type:
        return Message(key=f"{op_key}#response", role=MessageRole.RESPONSE, status_code="204")
    return Message(
        key=f"{op_key}#response",
        role=MessageRole.RESPONSE,
        status_code="200",
        content_types=[_JSON],
        payload=_with_nullable(resolve(return_type), nullable),
        extras={"odata_return_type": return_type, "odata_return_nullable": nullable},
    )


def _v4_operation(
    operation: ODataOperation,
    *,
    imports: Mapping[str, ODataOperationImport],
    entity_sets: Sequence[ODataEntitySet],
    resolve: TypeResolver,
) -> Operation:
    """One v4 function or action overload as a canonical operation."""
    qualified_name = f"{operation.namespace}.{operation.name}"
    signature = [parameter.type_expr for parameter in operation.parameters]
    op_key = operation_key(operation.kind, qualified_name, signature)
    is_function = operation.kind == "Function"
    http_path, path_extras = _http_path(
        operation, qualified_name, imports=imports, entity_sets=entity_sets
    )
    request_parameters = operation.parameters[1:] if operation.is_bound else operation.parameters

    parameters: List[Parameter] = []
    messages: List[Message] = []
    if is_function:
        parameters = [
            _query_parameter(
                op_key,
                parameter.name,
                _with_nullable(resolve(parameter.type_expr), parameter.nullable),
                parameter.nullable,
            )
            for parameter in request_parameters
        ]
    elif request_parameters:
        messages.append(
            Message(
                key=f"{op_key}#request",
                role=MessageRole.REQUEST,
                content_types=[_JSON],
                required=True,
                extras={
                    "odata_parameters": [
                        {
                            "name": parameter.name,
                            "type": parameter.type_expr,
                            "nullable": parameter.nullable,
                        }
                        for parameter in request_parameters
                    ]
                },
            )
        )
    messages.append(_response(op_key, operation.return_type, operation.return_nullable, resolve))

    extras: Dict[str, Any] = {
        "odata_kind": operation.kind.lower(),
        "odata_qualified_name": qualified_name,
        "odata_bound": operation.is_bound,
        "odata_parameter_signature": [
            {"name": parameter.name, "type": parameter.type_expr, "nullable": parameter.nullable}
            for parameter in operation.parameters
        ],
        **path_extras,
    }
    if operation.is_composable:
        extras["odata_composable"] = True
    if operation.entity_set_path:
        extras["odata_entity_set_path"] = operation.entity_set_path

    return Operation(
        key=op_key,
        name=operation.name,
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        http_method="GET" if is_function else "POST",
        http_path=http_path,
        parameters=parameters,
        messages=messages,
        extras=extras,
    )


def schema_operations(
    operations: Sequence[ODataOperation],
    *,
    container: Optional[ODataEntityContainer],
    resolve: TypeResolver,
) -> List[Operation]:
    """Every v4 function and action overload of a document as canonical operations.

    Args:
        operations: The overloads of every schema, in document order.
        container: The service's entity container — its entity sets address bound operations
            and its imports address unbound ones. ``None`` leaves every path unresolved.
        resolve: The normalizer's type resolver.

    Returns:
        One operation per overload, in the order given.
    """
    imports: Dict[str, ODataOperationImport] = {}
    entity_sets: Tuple[ODataEntitySet, ...] = ()
    if container is not None:
        entity_sets = container.entity_sets
        for imported in container.operation_imports:
            imports.setdefault(imported.operation, imported)
    return [
        _v4_operation(operation, imports=imports, entity_sets=entity_sets, resolve=resolve)
        for operation in operations
    ]


def _function_import_method(function_import: ODataFunctionImport) -> str:
    """``m:HttpMethod``, else ``POST`` for a v3 side-effecting import, else ``GET``."""
    annotations = dict(function_import.annotations)
    method = annotations.get("m:HttpMethod")
    if method and method.strip():
        return method.strip().upper()
    if str(annotations.get("IsSideEffecting", "")).strip().lower() == "true":
        return "POST"
    return "GET"


def function_import_operations(
    container: ODataEntityContainer, *, resolve: TypeResolver
) -> List[Operation]:
    """A v2/v3 container's ``<FunctionImport>`` service operations as canonical operations.

    Every parameter of a v2/v3 service operation is carried in the URL, whatever the method,
    so each becomes a query parameter.

    Args:
        container: The entity container.
        resolve: The normalizer's type resolver.

    Returns:
        One operation per import, in document order.
    """
    operations: List[Operation] = []
    for function_import in container.function_imports:
        qualified_name = f"{container.name}.{function_import.name}"
        op_key = operation_key(
            "FunctionImport",
            qualified_name,
            [parameter.type_expr or "" for parameter in function_import.parameters],
        )
        method = _function_import_method(function_import)
        extras: Dict[str, Any] = {
            "odata_kind": "function_import",
            "odata_qualified_name": qualified_name,
            "odata_parameter_signature": [
                {"name": parameter.name, "type": parameter.type_expr}
                for parameter in function_import.parameters
            ],
        }
        if function_import.entity_set:
            extras["odata_import_entity_set"] = function_import.entity_set
        operations.append(
            Operation(
                key=op_key,
                name=function_import.name,
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.NONE,
                http_method=method,
                http_path=f"/{function_import.name}",
                parameters=[
                    _query_parameter(
                        op_key,
                        parameter.name,
                        _with_nullable(resolve(parameter.type_expr), parameter.nullable)
                        if parameter.type_expr
                        else TypeRef(name="string", nullable=True),
                        parameter.nullable,
                    )
                    for parameter in function_import.parameters
                ],
                messages=[
                    _response(op_key, function_import.return_type, None, resolve),
                ],
                extras=extras,
            )
        )
    return operations
