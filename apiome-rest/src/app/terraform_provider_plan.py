"""What a Terraform provider for a contract contains — SDK-4.4 (#4498).

:mod:`app.terraform_provider_generator` writes a Terraform Plugin Framework provider in Go. Before
it writes a line it has to answer one question of the contract: *which operations form a
resource?* This module answers it, once, and hands the renderer a :class:`TerraformProviderPlan`.

**CRUD conventions.** Operations are grouped by path the way REST APIs are usually laid out, and
the way the SIM mock's stateful CRUD (#4453) groups them:

========================  =========================  ==============================
Operation                 Role                       Terraform
========================  =========================  ==============================
``POST   /widgets``       create                     resource ``Create``
``GET    /widgets/{id}``  read                       resource ``Read``, data source
``PUT    /widgets/{id}``  update (``PATCH`` if none) resource ``Update``
``DELETE /widgets/{id}``  delete                     resource ``Delete``
``GET    /widgets``       list                       ``<name>_list`` data source
========================  =========================  ==============================

A group with a read, a create and a delete is a **resource** whose schema is the read's response
type. A group with a read but no create or delete still yields a **data source**. A parent path
(``/orgs/{orgId}/projects``) becomes a required attribute that forces replacement. Without an
update operation every configurable attribute forces replacement.

**``x-terraform`` hints** override the conventions. They are read from the source OpenAPI
document (:attr:`~app.canonical_model.CanonicalApi.raw`), because the canonical model keeps only
the extensions it interprets:

* on an **operation** — ``{"resource": "widget", "operation": "create"}`` assigns it to a resource
  and role; ``false`` or ``{"ignore": true}`` leaves it out without a warning;
* on a **schema** — ``{"resource": "widget"}`` names the resource (``false`` keeps it a data
  source), ``"id"`` names the identifier member, ``"ignore"`` and ``"forceNew"`` list members to
  drop or to make replace-on-change, ``"import": false`` disables ``terraform import``, and
  ``"dataSource": false`` suppresses the data sources.

**Nothing is guessed silently.** An operation that fits no resource or data source, a group that
is missing an operation, a member whose type Terraform cannot express precisely, an invalid hint
and an auth scheme with no provider setting all become a :class:`TerraformWarning` — the
generator's readiness report, carried in the provider README and the client kit manifest.

**Determinism.** Everything walks declaration order and allocates names through
:class:`~app.server_stub_plan.Names`; nothing reads the clock or the environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .canonical_model import CanonicalApi
from .canonical_security import declared_security_schemes
from .server_stub_plan import (
    DEFAULT_MAX_OPERATIONS,
    Names,
    ServerStubPlan,
    StubOperation,
    StubSchema,
    ValueShape,
    build_server_stub_plan,
    snake_case,
    words,
)
from .snippet_render import resolve_server_base

__all__ = [
    "ATTRIBUTE_COMPUTED",
    "ATTRIBUTE_OPTIONAL_COMPUTED",
    "ATTRIBUTE_REQUIRED",
    "HINT_EXTENSION",
    "MAX_NESTING_DEPTH",
    "TerraformAttribute",
    "TerraformAuthSetting",
    "TerraformField",
    "TerraformItemDataSource",
    "TerraformListDataSource",
    "TerraformOperationRef",
    "TerraformProviderPlan",
    "TerraformResource",
    "TerraformWarning",
    "build_terraform_provider_plan",
    "plan_auth_settings",
    "terraform_provider_name",
]

#: The OpenAPI extension spec authors steer the mapping with.
HINT_EXTENSION = "x-terraform"

#: How deep a nested object is expanded into nested attributes before it is held as JSON instead.
#: Terraform schemas nest well, but a contract that nests deeper than this is usually recursive,
#: and a schema has to be finite.
MAX_NESTING_DEPTH = 4

#: An attribute the practitioner must set.
ATTRIBUTE_REQUIRED = "required"
#: An attribute the practitioner may set, and that the API fills in when they do not.
ATTRIBUTE_OPTIONAL_COMPUTED = "optional_computed"
#: An attribute only the API sets.
ATTRIBUTE_COMPUTED = "computed"

#: Names Terraform reserves as meta-arguments; an attribute can never be called one of them.
_RESERVED_ATTRIBUTE_NAMES = frozenset(
    {"count", "depends_on", "for_each", "lifecycle", "provider", "provisioner", "connection"}
)

#: The roles an operation can play in a resource.
_ROLES = ("create", "read", "update", "delete", "list")

#: A ``{name}`` placeholder in a path template.
_PATH_TOKEN = re.compile(r"\{([^{}]+)\}")

#: Scalar shape kind → Terraform value kind.
_SCALAR_KINDS = {"string": "string", "integer": "int", "number": "float", "boolean": "bool"}


# ===========================================================================
# Result shapes
# ===========================================================================


@dataclass(frozen=True)
class TerraformWarning:
    """One readiness finding — something the provider does not cover, and why.

    Attributes:
        code: A stable identifier (``terraform.not-crud-shaped``).
        severity: ``warning`` for something left out, ``info`` for a deliberate choice.
        message: The finding, in a sentence a spec author can act on.
        operation_id: The operation the finding is about, when it is about one.
        key: The canonical operation key, when it is about one.
    """

    code: str
    severity: str
    message: str
    operation_id: Optional[str] = None
    key: Optional[str] = None


@dataclass(frozen=True)
class TerraformField:
    """One Terraform attribute mapped onto one JSON member, recursively.

    Attributes:
        attr: The Terraform attribute name (``snake_case``).
        wire: The JSON member name.
        kind: ``string`` / ``int`` / ``float`` / ``bool`` / ``json`` / ``list`` / ``map`` /
            ``object``. ``json`` is a value Terraform holds as a JSON-encoded string because the
            contract types it too loosely (a union, an untyped object) for a schema.
        elem: The element of a ``list`` or the value of a ``map``.
        fields: The members of an ``object``.
        required: Whether the contract requires the member.
        description: The contract's prose for the member.
        enum: The values the contract permits, when it states a closed set.
        sensitive: Whether the value is a secret (``format: password``).
        format: The JSON Schema ``format`` of a scalar, for the generated examples.
    """

    attr: str
    wire: str
    kind: str
    elem: Optional["TerraformField"] = None
    fields: Tuple["TerraformField", ...] = ()
    required: bool = False
    description: Optional[str] = None
    enum: Tuple[Any, ...] = ()
    sensitive: bool = False
    format: Optional[str] = None


@dataclass(frozen=True)
class TerraformAttribute:
    """One top-level attribute of a resource or data source.

    Attributes:
        field: The attribute's shape and names.
        mode: :data:`ATTRIBUTE_REQUIRED`, :data:`ATTRIBUTE_OPTIONAL_COMPUTED` or
            :data:`ATTRIBUTE_COMPUTED`.
        path_param: The path placeholder the attribute fills, when it fills one. Such an
            attribute is never sent in a body nor read back from a response.
        create: Whether the create request body carries it.
        update: Whether the update request body carries it.
        force_new: Whether changing it replaces the resource.
        is_id: Whether it is the instance identifier.
    """

    field: TerraformField
    mode: str
    path_param: Optional[str] = None
    create: bool = False
    update: bool = False
    force_new: bool = False
    is_id: bool = False

    @property
    def name(self) -> str:
        """The Terraform attribute name."""
        return self.field.attr


@dataclass(frozen=True)
class TerraformOperationRef:
    """One contract operation a resource or data source calls.

    Attributes:
        operation_id: The id a consumer addresses the operation by.
        key: The canonical operation key.
        method: The upper-case HTTP verb.
        path: The path template, rooted at ``/``.
    """

    operation_id: str
    key: str
    method: str
    path: str


@dataclass(frozen=True)
class TerraformResource:
    """One Terraform resource.

    Attributes:
        name: The type-name suffix after the provider name (``widget``).
        schema_name: The contract schema the resource's attributes come from.
        description: The contract's prose for that schema.
        collection_path: Where a create is sent.
        item_path: Where one instance is read, updated and deleted.
        id_attr: The identifier attribute.
        id_param: The identifier's placeholder in :attr:`item_path`.
        operations: Role (``create``/``read``/``update``/``delete``) → the operation.
        attributes: The attributes, in schema order: parents, then members.
        import_parts: The attributes an import ID names, slash-separated; empty when import is
            disabled.
    """

    name: str
    schema_name: str
    description: Optional[str]
    collection_path: str
    item_path: str
    id_attr: str
    id_param: str
    operations: Tuple[Tuple[str, TerraformOperationRef], ...]
    attributes: Tuple[TerraformAttribute, ...]
    import_parts: Tuple[str, ...] = ()

    def operation(self, role: str) -> Optional[TerraformOperationRef]:
        """Return the operation playing ``role``, or ``None``."""
        for candidate, ref in self.operations:
            if candidate == role:
                return ref
        return None


@dataclass(frozen=True)
class TerraformItemDataSource:
    """A data source that reads one instance by the attributes that address it.

    Attributes:
        name: The type-name suffix.
        schema_name: The contract schema it returns.
        description: The contract's prose for that schema.
        item_path: The path it reads.
        operation: The read operation.
        attributes: The lookup attributes (required, filling placeholders) then the members
            (computed).
    """

    name: str
    schema_name: str
    description: Optional[str]
    item_path: str
    operation: TerraformOperationRef
    attributes: Tuple[TerraformAttribute, ...]


@dataclass(frozen=True)
class TerraformListDataSource:
    """A data source that reads every instance of a collection under ``items``.

    Attributes:
        name: The type-name suffix (``widget_list``).
        schema_name: The contract schema each element is.
        description: The contract's prose for that schema.
        collection_path: The path it reads.
        operation: The list operation.
        list_member: The response member holding the array, or ``""`` when the body is the array.
        parents: The parent path-parameter attributes (required).
        item: One element of ``items``.
    """

    name: str
    schema_name: str
    description: Optional[str]
    collection_path: str
    operation: TerraformOperationRef
    list_member: str
    parents: Tuple[TerraformAttribute, ...]
    item: TerraformField


@dataclass(frozen=True)
class TerraformAuthSetting:
    """One security scheme, as provider configuration.

    Attributes:
        scheme: The scheme's name in the contract.
        kind: ``bearer`` / ``basic`` / ``api_key``.
        attributes: The provider attribute names it adds — one, or ``(username, password)``.
        location: Where the credential travels: ``header`` / ``query`` / ``cookie``.
        parameter: The header, query parameter or cookie name.
        description: The contract's prose for the scheme.
    """

    scheme: str
    kind: str
    attributes: Tuple[str, ...]
    location: str = "header"
    parameter: str = "Authorization"
    description: Optional[str] = None


@dataclass(frozen=True)
class TerraformProviderPlan:
    """Everything the renderer needs, resolved once.

    Attributes:
        provider_name: The provider type name every resource type is prefixed with.
        title: The API's title.
        version: The API's version, when stated.
        description: The API's prose.
        base_url: The default endpoint (the first declared server).
        resources: The resources, in declaration order.
        item_data_sources: The single-instance data sources.
        list_data_sources: The collection data sources.
        auth: The provider settings the security schemes become.
        warnings: The readiness report.
        total_operation_count: How many operations the contract declares.
    """

    provider_name: str
    title: str
    version: Optional[str]
    description: Optional[str]
    base_url: str
    resources: Tuple[TerraformResource, ...]
    item_data_sources: Tuple[TerraformItemDataSource, ...]
    list_data_sources: Tuple[TerraformListDataSource, ...]
    auth: Tuple[TerraformAuthSetting, ...]
    warnings: Tuple[TerraformWarning, ...]
    total_operation_count: int


# ===========================================================================
# Names
# ===========================================================================


def terraform_provider_name(*candidates: Optional[str]) -> str:
    """Derive a provider type name from the first usable candidate.

    Terraform reads a resource type's provider from the text before its first underscore, so the
    name is lower-case letters and digits only (``acme-widgets`` → ``acmewidgets``).

    Args:
        *candidates: Names to try in order — typically the project slug, then the API title.

    Returns:
        A legal provider type name; ``api`` as the last resort.
    """
    for candidate in candidates:
        joined = "".join(words(candidate or ""))
        if joined and joined[0].isalpha():
            return joined
        if joined:
            return f"api{joined}"
    return "api"


def _attribute_name(wire: str) -> str:
    """Derive a Terraform attribute name from a JSON member name."""
    name = snake_case(wire, "value")
    return f"{name}_value" if name in _RESERVED_ATTRIBUTE_NAMES else name


def _type_name(source: str) -> str:
    """Derive a resource type-name suffix from a schema or hint name."""
    return snake_case(source, "resource")


# ===========================================================================
# The source document
# ===========================================================================


class _SourceDocument:
    """Reads what the canonical model does not keep from the source OpenAPI document.

    ``x-terraform`` hints, ``readOnly`` members and ``securitySchemes`` live only on
    :attr:`CanonicalApi.raw`. A model imported from something other than OpenAPI has no such
    document, and every lookup answers "nothing stated".
    """

    def __init__(self, raw: Any) -> None:
        """Wrap ``raw`` (the source document, or anything else)."""
        self._raw: Dict[str, Any] = raw if isinstance(raw, dict) else {}
        components = self._raw.get("components")
        schemas = components.get("schemas") if isinstance(components, dict) else None
        if not isinstance(schemas, dict):
            schemas = self._raw.get("definitions")  # Swagger 2.0
        self._schemas: Dict[str, Any] = schemas if isinstance(schemas, dict) else {}

    def operation(self, method: str, path: str) -> Dict[str, Any]:
        """Return the source operation object at ``method path``, or ``{}``."""
        paths = self._raw.get("paths")
        item = paths.get(path) if isinstance(paths, dict) else None
        found = item.get(method.lower()) if isinstance(item, dict) else None
        return found if isinstance(found, dict) else {}

    def schema(self, name: str) -> Dict[str, Any]:
        """Return the source schema object called ``name``, or ``{}``."""
        found = self._schemas.get(name)
        return found if isinstance(found, dict) else {}

    def read_only_members(self, name: str) -> Set[str]:
        """Return the members a schema marks ``readOnly``."""
        properties = self.schema(name).get("properties")
        if not isinstance(properties, dict):
            return set()
        return {
            member for member, spec in properties.items() if isinstance(spec, dict) and spec.get("readOnly") is True
        }

    def security_schemes(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Return ``(name, scheme)`` for every declared security scheme, in declaration order."""
        components = self._raw.get("components")
        schemes = components.get("securitySchemes") if isinstance(components, dict) else None
        if not isinstance(schemes, dict):
            schemes = self._raw.get("securityDefinitions")  # Swagger 2.0
        if not isinstance(schemes, dict):
            return []
        return [(str(name), spec) for name, spec in schemes.items() if isinstance(spec, dict)]

    @property
    def present(self) -> bool:
        """Whether there is a source document at all."""
        return bool(self._raw)


@dataclass(frozen=True)
class _OperationHint:
    """A parsed operation-level ``x-terraform`` hint."""

    ignore: bool = False
    resource: Optional[str] = None
    role: Optional[str] = None


@dataclass(frozen=True)
class _SchemaHint:
    """A parsed schema-level ``x-terraform`` hint."""

    resource: Optional[str] = None
    resource_disabled: bool = False
    id_member: Optional[str] = None
    ignore: Tuple[str, ...] = ()
    force_new: Tuple[str, ...] = ()
    importable: bool = True
    data_sources: bool = True


def _string_list(value: Any) -> Tuple[str, ...]:
    """Read a hint value that should be a list of strings; anything else is empty."""
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, str))
    return ()


# ===========================================================================
# Planning
# ===========================================================================


@dataclass
class _Group:
    """The operations one collection path gathers, by role."""

    key: str
    roles: Dict[str, StubOperation] = field(default_factory=dict)
    hinted_name: Optional[str] = None


def _ref(op: StubOperation) -> TerraformOperationRef:
    """Describe a planned operation for the result."""
    return TerraformOperationRef(operation_id=op.operation_id, key=op.key, method=op.http_method, path=op.path_template)


def _placeholders(path: str) -> List[str]:
    """Return a path template's placeholder names, in order."""
    return _PATH_TOKEN.findall(path)


def _convention_role(op: StubOperation) -> Optional[Tuple[str, str]]:
    """Return ``(collection path, role)`` for an operation the conventions recognize, or ``None``."""
    segments = [segment for segment in op.path_template.strip("/").split("/") if segment]
    method = op.http_method
    last_is_param = bool(segments) and re.fullmatch(r"\{[^{}]+\}", segments[-1]) is not None
    if last_is_param:
        collection = "/" + "/".join(segments[:-1])
        role = {"GET": "read", "PUT": "update", "PATCH": "update", "DELETE": "delete"}.get(method)
        return (collection, role) if role else None
    collection = "/" + "/".join(segments)
    role = {"POST": "create", "GET": "list"}.get(method)
    return (collection, role) if role else None


class _Planner:
    """Resolves one canonical model into a :class:`TerraformProviderPlan`."""

    def __init__(self, api: CanonicalApi, stub: ServerStubPlan, provider_name: str) -> None:
        """Plan ``api`` from its already-resolved server stub plan."""
        self._api = api
        self._stub = stub
        self._source = _SourceDocument(api.raw)
        self._provider_name = provider_name
        self._type_names = Names()
        self._schema_hints: Dict[str, _SchemaHint] = {}
        #: Required header name → the operations requiring it, for the ``headers`` finding.
        self.required_headers: Dict[str, List[str]] = {}
        self.warnings: List[TerraformWarning] = []
        self.resources: List[TerraformResource] = []
        self.item_data_sources: List[TerraformItemDataSource] = []
        self.list_data_sources: List[TerraformListDataSource] = []

    # -- reporting --------------------------------------------------------

    def _warn(
        self,
        code: str,
        message: str,
        op: Optional[StubOperation] = None,
        severity: str = "warning",
        *,
        operation_id: Optional[str] = None,
        key: Optional[str] = None,
    ) -> None:
        """Record one readiness finding.

        Args:
            code: The finding's code, without the ``terraform.`` prefix.
            message: The finding, in a sentence a spec author can act on.
            op: The planned operation it is about, when there is one.
            severity: ``warning`` or ``info``.
            operation_id: The operation id, for an operation that was never planned.
            key: The canonical key, for an operation that was never planned.
        """
        self.warnings.append(
            TerraformWarning(
                code=f"terraform.{code}",
                severity=severity,
                message=message,
                operation_id=op.operation_id if op else operation_id,
                key=op.key if op else key,
            )
        )

    # -- hints ------------------------------------------------------------

    def _operation_hint(self, op: StubOperation) -> _OperationHint:
        """Parse an operation's ``x-terraform`` hint, reporting one that cannot be honoured."""
        raw = self._source.operation(op.http_method, op.path_template).get(HINT_EXTENSION)
        if raw is None:
            return _OperationHint()
        if raw is False:
            return _OperationHint(ignore=True)
        if not isinstance(raw, dict):
            self._warn(
                "invalid-hint",
                f"`{HINT_EXTENSION}` on {op.http_method} {op.path_template} must be an object or false; it was "
                "ignored.",
                op,
            )
            return _OperationHint()
        if raw.get("ignore") is True:
            return _OperationHint(ignore=True)
        resource = raw.get("resource")
        role = raw.get("operation")
        if resource is None and role is None:
            return _OperationHint()
        if not isinstance(resource, str) or not resource.strip() or role not in _ROLES:
            self._warn(
                "invalid-hint",
                f"`{HINT_EXTENSION}` on {op.http_method} {op.path_template} needs a `resource` name and an "
                f"`operation` of {', '.join(_ROLES)}; it was ignored.",
                op,
            )
            return _OperationHint()
        return _OperationHint(resource=_type_name(resource), role=role)

    def _schema_hint(self, schema: StubSchema) -> _SchemaHint:
        """Return a schema's parsed ``x-terraform`` hint, parsing (and reporting) it only once."""
        if schema.key not in self._schema_hints:
            self._schema_hints[schema.key] = self._parse_schema_hint(schema)
        return self._schema_hints[schema.key]

    def _parse_schema_hint(self, schema: StubSchema) -> _SchemaHint:
        """Parse a schema's ``x-terraform`` hint, reporting one that cannot be honoured."""
        raw = self._source.schema(schema.source_name).get(HINT_EXTENSION)
        if raw is None:
            return _SchemaHint()
        if not isinstance(raw, dict):
            self._warn(
                "invalid-hint", f"`{HINT_EXTENSION}` on schema {schema.source_name} must be an object; it was ignored."
            )
            return _SchemaHint()
        resource = raw.get("resource")
        id_member = raw.get("id")
        return _SchemaHint(
            resource=_type_name(resource) if isinstance(resource, str) and resource.strip() else None,
            resource_disabled=resource is False,
            id_member=id_member if isinstance(id_member, str) and id_member else None,
            ignore=_string_list(raw.get("ignore")),
            force_new=_string_list(raw.get("forceNew")),
            importable=raw.get("import") is not False,
            data_sources=raw.get("dataSource") is not False,
        )

    # -- shapes -----------------------------------------------------------

    def _record(self, shape: Optional[ValueShape]) -> Optional[StubSchema]:
        """Return the record schema a shape names, following aliases, or ``None``."""
        seen: Set[str] = set()
        while shape is not None and shape.kind == "ref" and shape.ref and shape.ref not in seen:
            seen.add(shape.ref)
            schema = self._stub.schema_by_key(shape.ref)
            if schema is None:
                return None
            if schema.kind == "record":
                return schema
            if schema.kind != "alias":
                return None
            shape = schema.target
        return None

    def _list_element(self, shape: Optional[ValueShape]) -> Optional[Tuple[StubSchema, str]]:
        """Return ``(element schema, member)`` for a list response, or ``None``.

        The body may be the array itself (member ``""``) or an object with exactly one member that
        is an array of records — the ``{"items": [...]}`` envelope.
        """
        if shape is None:
            return None
        if shape.kind == "array":
            element = self._record(shape.item)
            return (element, "") if element is not None else None
        envelope = self._record(shape)
        if envelope is None:
            return None
        arrays = [
            member for member in envelope.fields if member.shape.kind == "array" and self._record(member.shape.item)
        ]
        if len(arrays) != 1:
            return None
        element = self._record(arrays[0].shape.item)
        return (element, arrays[0].wire_name) if element is not None else None

    def _field(
        self,
        wire: str,
        shape: ValueShape,
        *,
        attr: Optional[str] = None,
        required: bool = False,
        description: Optional[str] = None,
        depth: int = 0,
        visiting: Tuple[str, ...] = (),
    ) -> TerraformField:
        """Express one value as a :class:`TerraformField`.

        A record becomes a nested object, a list or map of anything expressible becomes a list or
        map, and everything Terraform cannot type precisely — a union, an untyped value, a record
        nested past :data:`MAX_NESTING_DEPTH` or referring back to itself — is held as JSON.
        """
        name = attr or _attribute_name(wire)
        enum = tuple(shape.enum)
        if not enum and shape.constraints is not None and shape.constraints.enum:
            enum = tuple(shape.constraints.enum)
        common = {"attr": name, "wire": wire, "required": required, "description": description}
        if shape.kind in _SCALAR_KINDS:
            return TerraformField(
                kind=_SCALAR_KINDS[shape.kind],
                enum=enum,
                sensitive=shape.format == "password",
                format=shape.format,
                **common,
            )
        if shape.kind in {"array", "map"} and shape.item is not None:
            element = self._field("", shape.item, attr="", depth=depth + 1, visiting=visiting)
            if element.kind == "json" or (
                element.kind in {"list", "map"} and element.elem and element.elem.kind == "object"
            ):
                return TerraformField(kind="json", **common)
            return TerraformField(kind="list" if shape.kind == "array" else "map", elem=element, **common)
        if shape.kind == "ref" and shape.ref:
            schema = self._stub.schema_by_key(shape.ref)
            if schema is None:
                return TerraformField(kind="json", **common)
            if schema.kind == "enum":
                kind = "int" if schema.enum_value_kind == "integer" else "string"
                return TerraformField(
                    kind=kind,
                    enum=tuple(value for _member, value in schema.enum_members),
                    **{**common, "description": description or schema.description},
                )
            if schema.kind == "map" and schema.target is not None:
                # A named map's ``target`` is its *value* shape, not the map itself.
                element = self._field("", schema.target, attr="", depth=depth + 1, visiting=visiting + (shape.ref,))
                if element.kind == "json" or (
                    element.kind in {"list", "map"} and element.elem and element.elem.kind == "object"
                ):
                    return TerraformField(kind="json", **{**common, "description": description or schema.description})
                return TerraformField(
                    kind="map", elem=element, **{**common, "description": description or schema.description}
                )
            if schema.kind in {"alias", "scalar"} and schema.target is not None:
                return self._field(
                    wire,
                    schema.target,
                    attr=name,
                    required=required,
                    description=description or schema.description,
                    depth=depth,
                    visiting=visiting + (shape.ref,),
                )
            if schema.kind == "record" and schema.fields and depth < MAX_NESTING_DEPTH and shape.ref not in visiting:
                names = Names()
                members = tuple(
                    self._field(
                        member.wire_name,
                        member.shape,
                        attr=names.take(_attribute_name(member.wire_name)),
                        required=member.required,
                        description=member.description,
                        depth=depth + 1,
                        visiting=visiting + (shape.ref,),
                    )
                    for member in schema.fields
                )
                return TerraformField(
                    kind="object", fields=members, **{**common, "description": description or schema.description}
                )
        return TerraformField(kind="json", **common)

    def _report_json(self, owner: str, fields: Sequence[TerraformField], prefix: str = "") -> None:
        """Report every member held as JSON, so a spec author knows where the schema is loose."""
        for item in fields:
            path = f"{prefix}{item.attr}"
            if item.kind == "json":
                self._warn(
                    "json-attribute",
                    f"`{owner}.{path}` is held as a JSON-encoded string: the contract types it as a union, "
                    "an untyped value or a recursive structure, which a Terraform schema cannot express.",
                    severity="info",
                )
            elif item.kind == "object":
                self._report_json(owner, item.fields, f"{path}.")
            elif item.elem is not None and item.elem.kind == "object":
                self._report_json(owner, item.elem.fields, f"{path}[*].")

    # -- grouping ---------------------------------------------------------

    def _groups(self) -> Tuple[List[_Group], List[StubOperation]]:
        """Group operations by collection, applying operation hints; return the leftovers too."""
        groups: Dict[str, _Group] = {}
        order: List[str] = []
        unclaimed: List[StubOperation] = []

        def group(key: str) -> _Group:
            if key not in groups:
                groups[key] = _Group(key=key)
                order.append(key)
            return groups[key]

        hinted: List[Tuple[StubOperation, _OperationHint]] = []
        for op in self._stub.operations:
            hint = self._operation_hint(op)
            if hint.ignore:
                self._warn(
                    "operation-ignored",
                    f"{op.http_method} {op.path_template} is excluded by its `{HINT_EXTENSION}` hint.",
                    op,
                    severity="info",
                )
                continue
            if hint.resource:
                hinted.append((op, hint))
                continue
            convention = _convention_role(op)
            if convention is None:
                unclaimed.append(op)
                continue
            collection, role = convention
            target = group(f"path:{collection}")
            existing = target.roles.get(role)
            if existing is not None:
                # Two candidates for one role can only be PUT and PATCH. PUT is the update: Terraform
                # sends the whole configuration, which is a replacement, not a partial patch.
                if op.http_method == "PUT":
                    unclaimed.append(existing)
                    target.roles[role] = op
                else:
                    unclaimed.append(op)
                continue
            target.roles[role] = op

        for op, hint in hinted:
            # A hinted operation joins the group whose read already names the same resource, so a
            # hint can complete a conventional group as well as assemble a new one.
            target = next(
                (candidate for candidate in groups.values() if self._group_name(candidate) == hint.resource), None
            )
            if target is None:
                target = group(f"hint:{hint.resource}")
                target.hinted_name = hint.resource
            assert hint.role is not None
            displaced = target.roles.get(hint.role)
            if displaced is not None and displaced is not op:
                unclaimed.append(displaced)
            target.roles[hint.role] = op
        return [groups[key] for key in order], unclaimed

    def _group_name(self, group: _Group) -> Optional[str]:
        """Return the resource name a group would get, from hints or its read's schema."""
        if group.hinted_name:
            return group.hinted_name
        read = group.roles.get("read")
        schema = self._record(read.success.shape) if read else None
        if schema is None:
            return None
        return self._schema_hint(schema).resource or _type_name(schema.source_name)

    # -- resources --------------------------------------------------------

    def _unsupplied(self, op: StubOperation) -> List[str]:
        """Return the required query and cookie parameters no attribute supplies.

        A required *header* does not disqualify an operation: the provider's ``headers`` setting
        sends it on every request, so it is collected for one ``info`` finding instead.
        """
        for param in op.header_params:
            if param.required and param.default is None:
                self.required_headers.setdefault(param.wire_name, []).append(op.operation_id)
        return [
            f"{param.location} parameter `{param.wire_name}`"
            for param in (op.query_params + op.cookie_params)
            if param.required and param.default is None
        ]

    def _parents(self, collection_path: str, op: StubOperation, names: Names) -> List[TerraformAttribute]:
        """Build one required, replace-on-change attribute per parent path placeholder."""
        shapes = {param.wire_name: param for param in op.path_params}
        parents: List[TerraformAttribute] = []
        for placeholder in _placeholders(collection_path):
            param = shapes.get(placeholder)
            kind = "int" if param is not None and param.shape.kind == "integer" else "string"
            parents.append(
                TerraformAttribute(
                    field=TerraformField(
                        attr=names.take(_attribute_name(placeholder)),
                        wire=placeholder,
                        kind=kind,
                        required=True,
                        description=(param.description if param else None)
                        or f"The `{placeholder}` the collection is addressed by.",
                    ),
                    mode=ATTRIBUTE_REQUIRED,
                    path_param=placeholder,
                    force_new=True,
                )
            )
        return parents

    def _id_member(self, schema: StubSchema, hint: _SchemaHint, id_param: str) -> Optional[str]:
        """Pick the member that identifies an instance: the hint, the placeholder's name, ``id``."""
        members = {member.wire_name for member in schema.fields}
        for candidate in (hint.id_member, id_param, "id"):
            if candidate and candidate in members:
                return candidate
        return None

    def _body_record(self, op: Optional[StubOperation]) -> Optional[StubSchema]:
        """Return the record a request body is, or ``None`` when it has none or is not JSON."""
        if op is None or op.body is None or not op.body.is_json:
            return None
        return self._record(op.body.shape)

    def _plan_resource(
        self, group: _Group, schema: StubSchema, hint: _SchemaHint, name: str
    ) -> Optional[TerraformResource]:
        """Build the resource for a complete group, or report why it cannot be one."""
        read = group.roles["read"]
        create = group.roles["create"]
        delete = group.roles["delete"]
        update = group.roles.get("update")
        item_path = read.path_template
        item_placeholders = _placeholders(item_path)
        if not item_placeholders:
            self._warn(
                "not-crud-shaped",
                f"{read.http_method} {item_path} has no placeholder to address one `{name}` by.",
                read,
            )
            return None
        id_param = item_placeholders[-1]
        collection_path = create.path_template
        parent_placeholders = _placeholders(collection_path)
        for op in (update, delete):
            if op is not None and _placeholders(op.path_template) != item_placeholders:
                self._warn(
                    "not-crud-shaped",
                    f"{op.http_method} {op.path_template} addresses a `{name}` differently from {read.http_method} "
                    f"{item_path}.",
                    op,
                )
                return None
        if item_placeholders[:-1] != parent_placeholders:
            self._warn(
                "not-crud-shaped",
                f"{create.http_method} {collection_path} and {read.http_method} {item_path} do not share their parent "
                "path.",
                create,
            )
            return None
        for op in (create, read, update, delete):
            if op is None:
                continue
            missing = self._unsupplied(op)
            if missing:
                self._warn(
                    "unsupplied-parameter",
                    f"`{name}` is not a resource: {op.http_method} {op.path_template} requires "
                    + ", ".join(missing)
                    + ", which no resource attribute supplies.",
                    op,
                )
                return None

        id_member = self._id_member(schema, hint, id_param)
        if id_member is None:
            self._warn(
                "no-id-attribute",
                f"`{name}` is not a resource: schema {schema.source_name} has no member that identifies an instance "
                f"(looked for {', '.join(repr(c) for c in (hint.id_member, id_param, 'id') if c)}). Name one with "
                f'`{HINT_EXTENSION}: {{"id": "<member>"}}`.',
                read,
            )
            return None
        id_shape = next(member.shape for member in schema.fields if member.wire_name == id_member)
        id_kind = self._field(id_member, id_shape).kind
        if id_kind not in {"string", "int"}:
            self._warn(
                "no-id-attribute",
                f"`{name}` is not a resource: its identifier `{id_member}` is not a string or an integer.",
                read,
            )
            return None
        created = self._record(create.success.shape)
        if created is None or id_member not in {member.wire_name for member in created.fields}:
            self._warn(
                "create-returns-no-id",
                f"`{name}` is not a resource: {create.http_method} {collection_path} does not answer with a body "
                f"carrying `{id_member}`, so a new instance cannot be addressed.",
                create,
            )
            return None

        create_body = self._body_record(create)
        update_body = self._body_record(update)
        create_members = {member.wire_name: member for member in create_body.fields} if create_body else {}
        update_members = {member.wire_name for member in update_body.fields} if update_body else set()
        read_only = self._source.read_only_members(schema.source_name)
        ignored = set(hint.ignore)
        force_new = set(hint.force_new)
        known_members = {member.wire_name for member in schema.fields} | set(create_members)
        for member in sorted((ignored | force_new) - known_members):
            self._warn(
                "invalid-hint",
                f"`{HINT_EXTENSION}` on schema {schema.source_name} names `{member}`, which it does not declare.",
            )

        names = Names()
        parents = self._parents(collection_path, create, names)
        parent_wires = {parent.path_param for parent in parents}
        attributes: List[TerraformAttribute] = list(parents)
        id_attr = ""
        members = list(schema.fields) + [
            member for wire, member in create_members.items() if wire not in {m.wire_name for m in schema.fields}
        ]
        for member in members:
            wire = member.wire_name
            if wire in ignored or wire in parent_wires:
                continue
            is_id = wire == id_member
            body_member = create_members.get(wire)
            if is_id:
                # The identifier is assigned by the API unless the create body is a distinct schema
                # that requires the caller to supply it (``PUT /buckets/{name}``-style).
                supplied = body_member is not None and create_body is not schema and body_member.required
                mode = ATTRIBUTE_REQUIRED if supplied else ATTRIBUTE_COMPUTED
                sent = supplied
            elif wire in read_only or body_member is None:
                mode, sent = ATTRIBUTE_COMPUTED, False
            else:
                mode = ATTRIBUTE_REQUIRED if body_member.required else ATTRIBUTE_OPTIONAL_COMPUTED
                sent = True
            # An update whose body is not a record sends nothing, so every sent member replaces.
            updated = sent and not is_id and wire in update_members
            replaces = mode != ATTRIBUTE_COMPUTED and (wire in force_new or update is None or (sent and not updated))
            terraform_field = self._field(
                wire,
                member.shape,
                attr=names.take(_attribute_name(wire)),
                required=member.required,
                description=member.description,
            )
            attribute = TerraformAttribute(
                field=terraform_field,
                mode=mode,
                create=sent,
                update=updated,
                force_new=replaces,
                is_id=is_id,
            )
            if is_id:
                id_attr = terraform_field.attr
            attributes.append(attribute)

        operations = tuple(
            (role, _ref(op))
            for role, op in (("create", create), ("read", read), ("update", update), ("delete", delete))
            if op is not None
        )
        resource = TerraformResource(
            name=name,
            schema_name=schema.source_name,
            description=schema.description,
            collection_path=collection_path,
            item_path=item_path,
            id_attr=id_attr,
            id_param=id_param,
            operations=operations,
            attributes=tuple(attributes),
            import_parts=tuple(parent.name for parent in parents) + (id_attr,) if hint.importable else (),
        )
        self._report_json(f"{self._provider_name}_{name}", [attribute.field for attribute in attributes])
        if not hint.importable:
            self._warn(
                "import-disabled",
                f"`{self._provider_name}_{name}` cannot be imported: its schema's `{HINT_EXTENSION}` hint disables it.",
                severity="info",
            )
        return resource

    def _plan_item_data_source(
        self, read: StubOperation, schema: StubSchema, name: str, hint: _SchemaHint
    ) -> Optional[TerraformItemDataSource]:
        """Build the single-instance data source over a read operation."""
        missing = self._unsupplied(read)
        if missing:
            self._warn(
                "unsupplied-parameter",
                f"No `{name}` data source: {read.http_method} {read.path_template} requires "
                + ", ".join(missing)
                + ".",
                read,
            )
            return None
        placeholders = _placeholders(read.path_template)
        if not placeholders:
            return None
        names = Names()
        shapes = {param.wire_name: param for param in read.path_params}
        id_member = self._id_member(schema, hint, placeholders[-1])
        attributes: List[TerraformAttribute] = []
        claimed: Set[str] = set()
        for placeholder in placeholders:
            member = id_member if placeholder == placeholders[-1] and id_member else None
            shape_kind = (
                "int"
                if shapes.get(placeholder) is not None and shapes[placeholder].shape.kind == "integer"
                else "string"
            )
            if member is not None:
                id_field = next(m for m in schema.fields if m.wire_name == member)
                shape_kind = self._field(member, id_field.shape).kind
                if shape_kind not in {"string", "int"}:
                    shape_kind = "string"
            attributes.append(
                TerraformAttribute(
                    field=TerraformField(
                        attr=names.take(_attribute_name(member or placeholder)),
                        wire=member or placeholder,
                        kind=shape_kind,
                        required=True,
                        description=(shapes[placeholder].description if placeholder in shapes else None)
                        or f"The `{placeholder}` to look up.",
                    ),
                    mode=ATTRIBUTE_REQUIRED,
                    path_param=placeholder,
                )
            )
            if member:
                claimed.add(member)
        ignored = set(hint.ignore)
        for member in schema.fields:
            if member.wire_name in claimed or member.wire_name in ignored:
                continue
            attributes.append(
                TerraformAttribute(
                    field=self._field(
                        member.wire_name,
                        member.shape,
                        attr=names.take(_attribute_name(member.wire_name)),
                        required=member.required,
                        description=member.description,
                    ),
                    mode=ATTRIBUTE_COMPUTED,
                )
            )
        return TerraformItemDataSource(
            name=name,
            schema_name=schema.source_name,
            description=schema.description,
            item_path=read.path_template,
            operation=_ref(read),
            attributes=tuple(attributes),
        )

    def _plan_list_data_source(self, op: StubOperation, name: str) -> Optional[TerraformListDataSource]:
        """Build the collection data source over a list operation, or report why there is none."""
        listed = self._list_element(op.success.shape)
        if listed is None:
            self._warn(
                "not-crud-shaped",
                f"{op.http_method} {op.path_template} does not answer with a list of records, so it is not a list "
                "data source.",
                op,
            )
            return None
        missing = self._unsupplied(op)
        if missing:
            self._warn(
                "unsupplied-parameter",
                f"No `{name}_list` data source: {op.http_method} {op.path_template} requires "
                + ", ".join(missing)
                + ".",
                op,
            )
            return None
        element, member = listed
        names = Names({"items"})
        parents = self._parents(op.path_template, op, names)
        item = self._field("", ValueShape(kind="ref", ref=element.key), attr="items")
        if item.kind != "object":
            return None
        ignored = set(self._schema_hint(element).ignore)
        if ignored:
            item = TerraformField(
                attr=item.attr,
                wire=item.wire,
                kind=item.kind,
                fields=tuple(member for member in item.fields if member.wire not in ignored),
                description=item.description,
            )
        return TerraformListDataSource(
            name=self._type_names.take(f"{name}_list"),
            schema_name=element.source_name,
            description=element.description,
            collection_path=op.path_template,
            operation=_ref(op),
            list_member=member,
            parents=tuple(
                TerraformAttribute(field=parent.field, mode=ATTRIBUTE_REQUIRED, path_param=parent.path_param)
                for parent in parents
            ),
            item=item,
        )

    def plan(self) -> None:
        """Plan every resource and data source, and report everything left out."""
        bound = {op.key for op in self._api.operations() if op.http_method and op.http_path}
        for skipped in self._stub.skipped:
            if skipped.key in bound:
                # The stub plan's operation cap, not a missing binding.
                self._warn(
                    "truncated",
                    f"{skipped.operation_id} was not considered: the provider covers the first "
                    f"{len(self._stub.operations)} HTTP operations of the contract.",
                    operation_id=skipped.operation_id,
                    key=skipped.key,
                )
                continue
            self._warn(
                "no-http-binding",
                f"{skipped.operation_id} ({skipped.key}) has no HTTP method and path, so no resource or data source "
                "can call it.",
                operation_id=skipped.operation_id,
                key=skipped.key,
            )
        groups, unclaimed = self._groups()
        for group in groups:
            self._plan_group(group, unclaimed)
        for header, operation_ids in self.required_headers.items():
            distinct = sorted(set(operation_ids))
            self._warn(
                "required-header",
                f"`{header}` is required by {', '.join(distinct)}; set it in the provider's `headers`.",
                severity="info",
            )
        for op in unclaimed:
            self._warn(
                "not-crud-shaped",
                f"{op.http_method} {op.path_template} is not a create, read, update, delete or list of a "
                "collection, so no resource or data source calls it. Assign it with "
                f'`{HINT_EXTENSION}: {{"resource": "<name>", "operation": "<role>"}}` if it is one.',
                op,
            )

    def _plan_group(self, group: _Group, unclaimed: List[StubOperation]) -> None:
        """Turn one group into a resource and/or data sources, reporting what is left over."""
        read = group.roles.get("read")
        listed = group.roles.get("list")
        schema = self._record(read.success.shape) if read else None
        if read is not None and schema is None:
            self._warn(
                "no-resource-schema",
                f"{read.http_method} {read.path_template} does not answer with a record schema, so no "
                "resource or data source reads it.",
                read,
            )
        hint = self._schema_hint(schema) if schema is not None else _SchemaHint()
        base_name = self._group_name(group) if schema is not None else None
        if base_name is None and listed is not None:
            element = self._list_element(listed.success.shape)
            base_name = _type_name(element[0].source_name) if element else None
        if base_name is None:
            if listed is not None:
                self._plan_list_data_source(listed, "")  # reports why it is not one
            self._report_leftovers(group, set(), unclaimed, resource_planned=False, hint=hint)
            return

        # One name serves the resource and its data sources; Terraform keeps the two kinds in
        # separate namespaces, so ``acme_widget`` can be both.
        name = self._type_names.take(base_name)
        claimed: Set[str] = set()
        resource: Optional[TerraformResource] = None
        if schema is not None and read is not None:
            missing_roles = [role for role in ("create", "delete") if role not in group.roles]
            if hint.resource_disabled:
                self._warn(
                    "resource-disabled",
                    f"Schema {schema.source_name} is read-only in Terraform: its `{HINT_EXTENSION}` hint disables the "
                    "resource.",
                    read,
                    severity="info",
                )
            elif missing_roles:
                self._warn(
                    "incomplete-resource",
                    f"`{name}` is a data source only: the contract has no {' or '.join(missing_roles)} operation for "
                    "it.",
                    read,
                )
            else:
                resource = self._plan_resource(group, schema, hint, name)
            if resource is not None:
                self.resources.append(resource)
                claimed.update(
                    group.roles[role].key for role in ("create", "read", "update", "delete") if role in group.roles
                )
            if hint.data_sources:
                data_source = self._plan_item_data_source(read, schema, name, hint)
                if data_source is not None:
                    self.item_data_sources.append(data_source)
                    claimed.add(read.key)
        if listed is not None and hint.data_sources:
            # Reported by _plan_list_data_source when it is not one, so it is claimed either way.
            list_data_source = self._plan_list_data_source(listed, name)
            if list_data_source is not None:
                self.list_data_sources.append(list_data_source)
            claimed.add(listed.key)
        self._report_leftovers(group, claimed, unclaimed, resource_planned=resource is not None, hint=hint)

    def _report_leftovers(
        self,
        group: _Group,
        claimed: Set[str],
        unclaimed: List[StubOperation],
        *,
        resource_planned: bool,
        hint: _SchemaHint,
    ) -> None:
        """Report the operations of a group that no resource or data source ended up calling."""
        for role, op in group.roles.items():
            if op.key in claimed or op in unclaimed:
                continue
            if role in {"read", "list"} and not hint.data_sources:
                self._warn(
                    "operation-ignored",
                    f"{op.http_method} {op.path_template} has no data source: its schema's `{HINT_EXTENSION}` hint "
                    "disables them.",
                    op,
                    severity="info",
                )
            elif role in {"create", "update", "delete"} and not resource_planned:
                self._warn(
                    "not-crud-shaped",
                    f"{op.http_method} {op.path_template} belongs to no resource, so Terraform does not call it.",
                    op,
                )


# ===========================================================================
# Auth
# ===========================================================================

#: Canonical scheme identifiers (:mod:`app.canonical_security`) → provider setting kind, for a
#: model with no source document to read ``securitySchemes`` from.
_CANONICAL_SCHEME_KINDS = {
    "authorization": "bearer",
    "bearer": "bearer",
    "oauth2": "bearer",
    "openIdConnect": "bearer",
    "basic": "basic",
    "apiKey": "api_key",
}


def _plan_auth(
    api: CanonicalApi, source: _SourceDocument, warn: Callable[[str, str], None]
) -> List[TerraformAuthSetting]:
    """Map the contract's security schemes onto provider settings.

    Args:
        api: The canonical model, for the fallback scheme identifiers.
        source: The source document, whose ``securitySchemes`` are preferred.
        warn: The planner's warning sink, for a scheme with no provider setting.

    Returns:
        The settings, in declaration order.
    """
    names = Names({"endpoint", "headers"})
    settings: List[TerraformAuthSetting] = []
    declared = source.security_schemes()
    if not declared:
        declared = [(scheme, {"x-canonical": scheme}) for scheme in declared_security_schemes(api)]
    for scheme_name, spec in declared:
        canonical = spec.get("x-canonical")
        scheme_type = str(spec.get("type") or "")
        http_scheme = str(spec.get("scheme") or "").lower()
        description = spec.get("description") if isinstance(spec.get("description"), str) else None
        prefix = snake_case(scheme_name, "auth")
        if canonical is not None:
            kind = _CANONICAL_SCHEME_KINDS.get(str(canonical))
            location, parameter = ("header", "X-API-Key") if kind == "api_key" else ("header", "Authorization")
        elif scheme_type == "http" and http_scheme == "bearer" or scheme_type in {"oauth2", "openIdConnect"}:
            kind, location, parameter = "bearer", "header", "Authorization"
        elif scheme_type == "http" and http_scheme == "basic" or scheme_type == "basic":
            kind, location, parameter = "basic", "header", "Authorization"
        elif scheme_type == "apiKey" and spec.get("in") in {"header", "query", "cookie"} and spec.get("name"):
            kind, location, parameter = "api_key", str(spec["in"]), str(spec["name"])
        else:
            kind, location, parameter = None, "header", ""
        if kind is None:
            warn(
                "unsupported-auth",
                f"Security scheme `{scheme_name}` has no provider setting; send its credential with the provider's "
                "`headers` instead.",
            )
            continue
        if kind == "basic":
            attributes: Tuple[str, ...] = (
                names.take("username") if not names.taken("username") else names.take(f"{prefix}_username"),
                names.take("password") if not names.taken("password") else names.take(f"{prefix}_password"),
            )
        else:
            preferred = "token" if kind == "bearer" else "api_key"
            attributes = (names.take(preferred) if not names.taken(preferred) else names.take(f"{prefix}_{preferred}"),)
        settings.append(
            TerraformAuthSetting(
                scheme=scheme_name,
                kind=kind,
                attributes=attributes,
                location=location,
                parameter=parameter,
                description=description,
            )
        )
    return settings


def plan_auth_settings(api: CanonicalApi) -> Tuple[List[TerraformAuthSetting], List[str]]:
    """Map the contract's security schemes onto credential settings, outside a provider plan.

    The same mapping the provider's settings come from, shared with the SDK-4.5 MCP server
    generator (:mod:`app.mcp_server_generator`, #4499), which reads each setting from an
    environment variable instead, so both artifacts agree on what a credential is called.

    Args:
        api: The canonical model.

    Returns:
        ``(settings, unsupported)`` — the settings in declaration order, and the names of the
        schemes that have none (mutual TLS, an API key with no name).
    """
    source = _SourceDocument(api.raw)
    settings = _plan_auth(api, source, lambda code, message: None)
    covered = {setting.scheme for setting in settings}
    declared = [name for name, _spec in source.security_schemes()] or declared_security_schemes(api)
    unsupported = [name for name in declared if name not in covered]
    return settings, unsupported


def build_terraform_provider_plan(
    api: CanonicalApi,
    *,
    provider_name: Optional[str] = None,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> TerraformProviderPlan:
    """Resolve which resources and data sources a provider for ``api`` contains.

    Args:
        api: The canonical model.
        provider_name: The provider type name. Defaults to one derived from the API's identity
            name, then its title.
        max_operations: How many operations are considered; the rest are reported.

    Returns:
        The :class:`TerraformProviderPlan`. Building it twice from the same model yields equal
        plans.
    """
    stub = build_server_stub_plan(api, max_operations=max_operations)
    name = terraform_provider_name(provider_name, api.identity.name if api.identity else None, api.title)
    planner = _Planner(api, stub, name)
    planner.plan()
    auth = _plan_auth(api, planner._source, lambda code, message: planner._warn(code, message))
    base_url, _placeholders_unused = resolve_server_base(api)
    return TerraformProviderPlan(
        provider_name=name,
        title=stub.title,
        version=stub.version,
        description=stub.description,
        base_url=base_url,
        resources=tuple(planner.resources),
        item_data_sources=tuple(planner.item_data_sources),
        list_data_sources=tuple(planner.list_data_sources),
        auth=tuple(auth),
        warnings=tuple(planner.warnings),
        total_operation_count=stub.total_operation_count,
    )
