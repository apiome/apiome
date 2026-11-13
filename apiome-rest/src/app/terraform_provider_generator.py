"""The Terraform provider generator — SDK-4.4 (#4498).

Turns a persisted :class:`~app.canonical_model.CanonicalApi` into a buildable Terraform provider
written in Go on the Terraform Plugin Framework: resources and data sources derived from the
contract's CRUD conventions (and its ``x-terraform`` hints), provider configuration derived from
its security schemes, registry-layout documentation and example ``.tf`` configuration.

**Why here and not behind a generator SPI.** SDK-4.4 was to run under the generator SPI
(SDK-1.2, #4482) on top of the codegen preprocessing pass (SDK-1.3, #4483), and join the SDK-1.4
compile-gate matrix (#4484). All three were closed *not-planned*. Following the precedent the Go
client (SDK-2.4) and the server stubs (SDK-2.5) set, this module is a pure function of the
canonical model, it is called from :mod:`app.sdk_kit`, and its output rides the client kit under
``terraform/``. The SPI's readiness-warning channel did not ship either, so the warnings travel
in the provider's README and in the kit manifest's ``terraform_provider.warnings``.

**How the output is shaped.** :mod:`app.terraform_provider_plan` decides what the provider
contains; this module only writes it. The Go splits in two:

* fixed files (:mod:`app.terraform_provider_runtime`) — one generic resource, two generic data
  sources and a JSON transport, written and compiled as ordinary Go;
* generated files — ``provider.go`` (configuration and auth) and one file per resource and data
  source holding a *spec table* (paths, methods, which attribute travels where) and a schema.

Generated Go uses assignment statements (``attributes["name"] = …``) rather than aligned
composite literals, so the output is ``gofmt``-clean without this module re-implementing gofmt's
alignment rules.

**Three properties are load-bearing**, as for every generated artifact:

*Byte-deterministic.* Declaration order everywhere, names from deterministic allocators, nothing
read from the clock or the environment, and a pinned dependency set — so the kit keeps its
content-addressed ``ETag``.

*It compiles.* ``tests/test_terraform_provider_generator.py`` builds, vets and gofmt-checks a
generated provider whenever a Go toolchain is on ``PATH``, and drives a full
``terraform apply``/``destroy`` cycle against a stateful fake when Terraform is too.

*It never refuses over one bad operation.* An operation that is not CRUD-shaped is reported in
:attr:`TerraformProviderPackage.warnings` and the rest of the provider ships.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .canonical_model import CanonicalApi
from .server_stub_plan import DEFAULT_MAX_OPERATIONS, Names, camel_case, pascal_case
from .snippet_render import license_comment_block
from .terraform_provider_plan import (
    ATTRIBUTE_COMPUTED,
    ATTRIBUTE_OPTIONAL_COMPUTED,
    ATTRIBUTE_REQUIRED,
    HINT_EXTENSION,
    TerraformAttribute,
    TerraformField,
    TerraformItemDataSource,
    TerraformListDataSource,
    TerraformProviderPlan,
    TerraformResource,
    TerraformWarning,
    build_terraform_provider_plan,
    terraform_provider_name,
)
from .terraform_provider_runtime import (
    CLIENT_GO,
    GO_DIRECTIVE,
    GO_MOD_REQUIRES,
    GO_SUM,
    MODULE_PLACEHOLDER,
    PLUGIN_FRAMEWORK_VERSION,
    PLUGIN_GO_VERSION,
    RUNTIME_GO,
)

__all__ = [
    "DEFAULT_NAMESPACE",
    "REGISTRY_HOST",
    "TERRAFORM_PROVIDER_SCHEMA_VERSION",
    "TerraformProviderFile",
    "TerraformProviderPackage",
    "generate_terraform_provider",
    "terraform_module_path",
    "terraform_namespace",
    "terraform_provider_name",
    "terraform_registry_address",
]

#: The addressable shape of the generated provider, recorded in the kit manifest.
TERRAFORM_PROVIDER_SCHEMA_VERSION = "sdk.terraform-provider.v1"

#: The registry host the provider address names.
REGISTRY_HOST = "registry.terraform.io"

#: The registry namespace used when no tenant slug is available.
DEFAULT_NAMESPACE = "apiome"

#: Host used for the module path when a tenant configured no Go module path (IANA-reserved).
_DEFAULT_MODULE_HOST = "example.com"

#: The import path prefix of the Terraform Plugin Framework.
_FRAMEWORK = "github.com/hashicorp/terraform-plugin-framework"

#: A character a registry namespace or module element may not contain.
_UNSAFE_ELEMENT = re.compile(r"[^a-z0-9-]+")

#: Terraform value kind → (schema attribute type, plan-modifier type, plan-modifier package).
_SCALAR_ATTRIBUTES = {
    "string": ("StringAttribute", "String", "stringplanmodifier"),
    "json": ("StringAttribute", "String", "stringplanmodifier"),
    "int": ("Int64Attribute", "Int64", "int64planmodifier"),
    "float": ("Float64Attribute", "Float64", "float64planmodifier"),
    "bool": ("BoolAttribute", "Bool", "boolplanmodifier"),
}

#: Terraform value kind → the framework element type a list or map of it declares.
_ELEMENT_TYPES = {
    "string": "types.StringType",
    "json": "types.StringType",
    "int": "types.Int64Type",
    "float": "types.Float64Type",
    "bool": "types.BoolType",
}

#: Terraform value kind → the Go constant the runtime spells it with.
_RUNTIME_KINDS = {
    "string": "kindString",
    "int": "kindInt",
    "float": "kindFloat",
    "bool": "kindBool",
    "json": "kindJSON",
    "list": "kindList",
    "map": "kindMap",
    "object": "kindObject",
}

#: Example values for a string by its JSON Schema format.
_FORMAT_EXAMPLES = {
    "date-time": "2026-01-01T00:00:00Z",
    "date": "2026-01-01",
    "email": "user@example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "ipv4": "192.0.2.1",
    "hostname": "example.com",
}

#: What the provider's ``headers`` setting is for, in the schema and the docs.
_HEADERS_DESCRIPTION = (
    "Headers sent with every request — a tenant header, or the `X-Mock-Session` that keeps an Apiome mock stateful."
)

#: How many optional attributes a generated resource example sets beside the required ones.
_EXAMPLE_OPTIONAL_ATTRIBUTES = 3


# ===========================================================================
# Result shapes
# ===========================================================================


@dataclass(frozen=True)
class TerraformProviderFile:
    """One file of the generated provider.

    Attributes:
        path: Path relative to the provider root (``main.go``, ``docs/resources/widget.md``).
        text: The file's complete contents, always ending in a newline.
    """

    path: str
    text: str


@dataclass(frozen=True)
class TerraformProviderPackage:
    """A complete generated provider.

    Attributes:
        provider_name: The provider type name every resource type is prefixed with.
        address: The registry address (``registry.terraform.io/acme/widgets``).
        module_path: The ``go.mod`` module path.
        go_version: The ``go`` directive ``go.mod`` declares.
        framework_version: The pinned Terraform Plugin Framework release.
        files: Every generated file, ordered by path.
        plan: What the provider contains, as the planner resolved it.
    """

    provider_name: str
    address: str
    module_path: str
    go_version: str
    framework_version: str
    files: List[TerraformProviderFile] = field(default_factory=list)
    plan: Optional[TerraformProviderPlan] = None

    @property
    def resource_types(self) -> List[str]:
        """The full resource type names, in declaration order."""
        if self.plan is None:
            return []
        return [f"{self.provider_name}_{resource.name}" for resource in self.plan.resources]

    @property
    def data_source_types(self) -> List[str]:
        """The full data source type names, item data sources first."""
        if self.plan is None:
            return []
        return [f"{self.provider_name}_{source.name}" for source in self.plan.item_data_sources] + [
            f"{self.provider_name}_{source.name}" for source in self.plan.list_data_sources
        ]

    @property
    def warnings(self) -> List[TerraformWarning]:
        """The readiness report."""
        return list(self.plan.warnings) if self.plan is not None else []

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


# ===========================================================================
# Coordinates
# ===========================================================================


def _element(value: Optional[str]) -> str:
    """Reduce a value to a lower-case, hyphen-separated path element."""
    return _UNSAFE_ELEMENT.sub("-", (value or "").strip().lower()).strip("-")


def terraform_namespace(*candidates: Optional[str]) -> str:
    """Return the registry namespace: the first candidate that survives sanitizing.

    Args:
        *candidates: Typically the tenant slug.

    Returns:
        A lower-case, hyphen-separated namespace; :data:`DEFAULT_NAMESPACE` as the last resort.
    """
    for candidate in candidates:
        element = _element(candidate)
        if element:
            return element
    return DEFAULT_NAMESPACE


def terraform_registry_address(namespace: str, provider_name: str) -> str:
    """Return the provider's registry address, the source a configuration's ``required_providers`` names."""
    return f"{REGISTRY_HOST}/{namespace}/{provider_name}"


def terraform_module_path(configured_go_module: Optional[str], namespace: str, provider_name: str) -> str:
    """Return the provider's ``go.mod`` module path.

    The registry convention names the repository ``terraform-provider-<name>``. A tenant that
    configured a Go module path for its client (SDK-3.4 ``gomod``) gets the provider as a sibling
    of it — ``github.com/acme/widgets-go`` → ``github.com/acme/terraform-provider-widgets`` — so both
    live under the owner they already publish from. Otherwise the reserved ``example.com`` host is
    used, which can never resolve to somebody's real repository.

    Args:
        configured_go_module: The tenant's configured Go module path, or ``None``.
        namespace: The registry namespace (the fallback owner element).
        provider_name: The provider type name.

    Returns:
        The module path.
    """
    repository = f"terraform-provider-{provider_name}"
    configured = (configured_go_module or "").strip().rstrip("/")
    if configured and "/" in configured:
        return f"{configured.rsplit('/', 1)[0]}/{repository}"
    if configured:
        return f"{configured}/{repository}"
    return f"{_DEFAULT_MODULE_HOST}/{namespace}/{repository}"


# ===========================================================================
# Go text helpers
# ===========================================================================


def _go_string(value: str) -> str:
    """Render ``value`` as a Go interpreted string literal.

    JSON's string escapes are a subset of Go's, and ``ensure_ascii=False`` keeps characters outside
    the Basic Multilingual Plane as UTF-8 rather than as the surrogate pairs Go would reject.
    """
    return json.dumps(value, ensure_ascii=False)


def _go_file(
    package: str,
    body: Sequence[str],
    *,
    std: Sequence[str] = (),
    external: Sequence[str] = (),
    local: Sequence[str] = (),
    aliases: Optional[Dict[str, str]] = None,
    license_header: Optional[str] = None,
    doc: Sequence[str] = (),
) -> str:
    """Assemble one generated ``.go`` file.

    Imports are grouped the way goimports writes them — standard library, third party, this
    module — and sorted by path within each group, which is the order gofmt keeps.

    Args:
        package: The package clause.
        body: The declarations, already rendered.
        std: Standard-library import paths.
        external: Third-party import paths.
        local: Import paths inside the generated module.
        aliases: Import path → alias, for a path whose package name collides.
        license_header: The tenant's licence text (SDK-3.4), as a leading comment block.
        doc: Doc-comment lines attached to the package clause.

    Returns:
        The file text, ending in exactly one newline.
    """
    lines: List[str] = []
    prologue = license_comment_block(license_header, "go")
    if prologue:
        lines += [*prologue.split("\n"), ""]
    lines += ["// Code generated by Apiome. DO NOT EDIT.", ""]
    lines += [*doc, f"package {package}"]
    groups = [sorted(set(group)) for group in (std, external, local) if group]
    if groups:
        lines += ["", "import ("]
        for index, group in enumerate(groups):
            if index:
                lines.append("")
            for path in group:
                alias = (aliases or {}).get(path)
                lines.append(f'\t{alias} "{path}"' if alias else f'\t"{path}"')
        lines.append(")")
    lines += ["", *body]
    return "\n".join(lines).rstrip("\n") + "\n"


def _fixed_file(source: str, module_path: str, license_header: Optional[str]) -> str:
    """Prefix a fixed Go file with the licence header and the generated-code marker."""
    lines: List[str] = []
    prologue = license_comment_block(license_header, "go")
    if prologue:
        lines += [*prologue.split("\n"), ""]
    lines += ["// Code generated by Apiome. DO NOT EDIT.", ""]
    return "\n".join(lines) + source.replace(MODULE_PLACEHOLDER, module_path)


def _sentence(text: Optional[str]) -> str:
    """Collapse prose to one line and make sure it ends like a sentence."""
    collapsed = " ".join((text or "").split())
    if collapsed and collapsed[-1] not in ".!?":
        collapsed += "."
    return collapsed


def _attribute_description(item: TerraformField, *, force_new: bool = False) -> str:
    """Describe an attribute for its schema and its documentation."""
    parts = [_sentence(item.description)] if item.description else []
    if item.enum:
        parts.append("One of " + ", ".join(f"`{value}`" for value in item.enum) + ".")
    if item.kind == "json":
        parts.append("A JSON-encoded value; use `jsonencode()`.")
    if force_new:
        parts.append("Changing it replaces the resource.")
    return " ".join(parts)


# ===========================================================================
# Schemas
# ===========================================================================


class _SchemaWriter:
    """Renders one schema function's body as assignment statements.

    Each nested object's attributes are built into their own local map before the attribute that
    holds them, so no composite literal ever spans several aligned lines.
    """

    def __init__(self, package: str, resource: bool) -> None:
        """Start a writer for ``rschema`` (a resource) or ``dschema`` (a data source)."""
        self.package = package
        self.resource = resource
        self.lines: List[str] = []
        self.imports: Set[str] = set()
        self._locals = Names({"attributes"})

    def _flags(self, mode: str) -> List[str]:
        """Return the presence flags for an attribute mode."""
        if mode == ATTRIBUTE_REQUIRED:
            return ["Required: true"]
        if mode == ATTRIBUTE_OPTIONAL_COMPUTED:
            return ["Optional: true", "Computed: true"]
        return ["Computed: true"]

    def _element_type(self, item: TerraformField) -> str:
        """Return the framework element type of a list or map's element."""
        if item.kind in _ELEMENT_TYPES:
            self.imports.add(f"{_FRAMEWORK}/types")
            return _ELEMENT_TYPES[item.kind]
        assert item.elem is not None
        inner = self._element_type(item.elem)
        container = "ListType" if item.kind == "list" else "MapType"
        return f"types.{container}{{ElemType: {inner}}}"

    def _child_mode(self, parent_mode: str, child: TerraformField) -> str:
        """Return a nested member's mode: computed under a computed parent, else by requiredness."""
        if parent_mode == ATTRIBUTE_COMPUTED or not self.resource:
            return ATTRIBUTE_COMPUTED
        return ATTRIBUTE_REQUIRED if child.required else ATTRIBUTE_OPTIONAL_COMPUTED

    def _nested(self, owner: str, members: Sequence[TerraformField], mode: str) -> str:
        """Render a nested object's attribute map into a local, returning the local's name."""
        rendered = [
            (member, self.expression(member, self._child_mode(mode, member), owner=f"{owner} {member.attr}"))
            for member in members
        ]
        local = self._locals.take(camel_case(f"{owner} attributes", "nestedAttributes"))
        self.lines.append(f"\t{local} := map[string]{self.package}.Attribute{{}}")
        for member, expression in rendered:
            self.lines.append(f"\t{local}[{_go_string(member.attr)}] = {expression}")
        return local

    def expression(
        self, item: TerraformField, mode: str, *, owner: str, force_new: bool = False, modifiers: Sequence[str] = ()
    ) -> str:
        """Return the attribute expression for one field.

        Args:
            item: The field.
            mode: Its presence mode.
            owner: A path naming it, for the locals its nested members are built in.
            force_new: Whether to say in the description that changing it replaces the resource.
            modifiers: Plan modifiers (``RequiresReplace``, ``UseStateForUnknown``) — top-level
                resource attributes only.

        Returns:
            The Go expression.
        """
        settings = self._flags(mode)
        if item.sensitive:
            settings.append("Sensitive: true")
        description = _attribute_description(item, force_new=force_new)
        modifier_type: Optional[Tuple[str, str]] = None
        if item.kind in _SCALAR_ATTRIBUTES:
            type_name, modifier_name, modifier_package = _SCALAR_ATTRIBUTES[item.kind]
            modifier_type = (modifier_name, modifier_package)
        elif item.kind in {"list", "map"} and item.elem is not None and item.elem.kind == "object":
            local = self._nested(owner, item.elem.fields, mode)
            type_name = "ListNestedAttribute" if item.kind == "list" else "MapNestedAttribute"
            settings.insert(0, f"NestedObject: {self.package}.NestedAttributeObject{{Attributes: {local}}}")
            modifier_type = ("List", "listplanmodifier") if item.kind == "list" else ("Map", "mapplanmodifier")
        elif item.kind in {"list", "map"} and item.elem is not None:
            type_name = "ListAttribute" if item.kind == "list" else "MapAttribute"
            settings.insert(0, f"ElementType: {self._element_type(item.elem)}")
            modifier_type = ("List", "listplanmodifier") if item.kind == "list" else ("Map", "mapplanmodifier")
        else:
            local = self._nested(owner, item.fields, mode)
            type_name = "SingleNestedAttribute"
            settings.insert(0, f"Attributes: {local}")
            modifier_type = ("Object", "objectplanmodifier")
        if description:
            settings.append(f"Description: {_go_string(description)}")
        if modifiers and modifier_type is not None:
            modifier_name, modifier_package = modifier_type
            self.imports.add(f"{_FRAMEWORK}/resource/schema/planmodifier")
            self.imports.add(f"{_FRAMEWORK}/resource/schema/{modifier_package}")
            calls = ", ".join(f"{modifier_package}.{call}()" for call in modifiers)
            settings.append(f"PlanModifiers: []planmodifier.{modifier_name}{{{calls}}}")
        return f"{self.package}.{type_name}{{{', '.join(settings)}}}"


def _modifiers(attribute: TerraformAttribute) -> List[str]:
    """Return the plan modifiers a top-level resource attribute carries."""
    modifiers: List[str] = []
    if attribute.force_new:
        modifiers.append("RequiresReplace")
    if attribute.mode in {ATTRIBUTE_COMPUTED, ATTRIBUTE_OPTIONAL_COMPUTED}:
        # Without this every computed value reads "(known after apply)" on every plan.
        modifiers.append("UseStateForUnknown")
    return modifiers


def _render_schema_function(
    function: str,
    package: str,
    attributes: Sequence[TerraformAttribute],
    description: str,
    *,
    resource: bool,
) -> Tuple[List[str], Set[str]]:
    """Render ``func <function>() <package>.Schema`` and return its lines and imports."""
    writer = _SchemaWriter(package, resource)
    statements: List[Tuple[str, str]] = []
    for attribute in attributes:
        expression = writer.expression(
            attribute.field,
            attribute.mode,
            owner=attribute.name,
            force_new=attribute.force_new and resource,
            modifiers=_modifiers(attribute) if resource else (),
        )
        statements.append((attribute.name, expression))
    body = [
        f"// {function} returns the Terraform schema.",
        f"func {function}() {package}.Schema {{",
        *writer.lines,
        f"\tattributes := map[string]{package}.Attribute{{}}",
        *(f"\tattributes[{_go_string(name)}] = {expression}" for name, expression in statements),
        f"\treturn {package}.Schema{{Description: {_go_string(description)}, Attributes: attributes}}",
        "}",
    ]
    return body, writer.imports


def _list_schema_attributes(source: TerraformListDataSource) -> List[TerraformAttribute]:
    """Return a list data source's attributes: its parents, then the computed ``items`` list."""
    items = TerraformField(
        attr="items",
        wire="items",
        kind="list",
        elem=source.item,
        description=f"Every {source.schema_name} the collection holds.",
    )
    return [*source.parents, TerraformAttribute(field=items, mode=ATTRIBUTE_COMPUTED)]


# ===========================================================================
# Spec tables
# ===========================================================================


def _field_literal(item: TerraformField, indent: str, *, named: bool = True) -> List[str]:
    """Render a runtime ``field`` literal, one nested member per line.

    Args:
        item: The field.
        indent: The indentation of the literal's first line.
        named: Whether to write ``attr``/``wire`` (an element of a list or map has neither).

    Returns:
        The literal's lines; the first carries no indentation (the caller places it), the last
        ends with the closing brace.
    """
    parts: List[str] = []
    if named:
        parts += [f"attr: {_go_string(item.attr)}", f"wire: {_go_string(item.wire)}"]
    parts.append(f"kind: {_RUNTIME_KINDS[item.kind]}")
    if item.elem is not None and item.kind in {"list", "map"}:
        element = _field_literal(item.elem, indent, named=False)
        if len(element) > 1:
            return [f"field{{{', '.join(parts)}, elem: &{element[0]}", *element[1:-1], f"{element[-1]}}}"]
        parts.append(f"elem: &{element[0]}")
    if item.kind == "object":
        lines = [f"field{{{', '.join(parts)}, fields: []field{{"]
        for member in item.fields:
            member_lines = _field_literal(member, indent + "\t")
            first = member_lines[0][len("field") :]
            lines.append(f"{indent}\t{first}")
            lines += member_lines[1:]
            lines[-1] += ","
        lines.append(f"{indent}}}}}")
        return lines
    return [f"field{{{', '.join(parts)}}}"]


def _attribute_literals(attributes: Sequence[TerraformAttribute], indent: str = "\t\t") -> List[str]:
    """Render a runtime ``[]attribute`` body, one attribute per line (nested members below it)."""
    lines: List[str] = []
    for attribute in attributes:
        extras: List[str] = []
        if attribute.path_param:
            extras.append(f"pathParam: {_go_string(attribute.path_param)}")
        if attribute.create:
            extras.append("create: true")
        if attribute.update:
            extras.append("update: true")
        suffix = "".join(f", {extra}" for extra in extras)
        literal = _field_literal(attribute.field, indent)
        literal[0] = f"{indent}{{field: {literal[0]}"
        literal[-1] = f"{literal[-1]}{suffix}}},"
        lines += literal
    return lines


# ===========================================================================
# Files
# ===========================================================================


@dataclass
class _Identifiers:
    """The Go identifiers generated for one resource or data source."""

    constructor: str
    spec: str
    schema: str


def _render_resource_file(
    resource: TerraformResource, ids: _Identifiers, provider_name: str, license_header: Optional[str]
) -> TerraformProviderFile:
    """Render ``internal/provider/resource_<name>.go``."""
    type_name = f"{provider_name}_{resource.name}"
    description = (
        _sentence(resource.description) or f"A {resource.schema_name}, managed through {resource.collection_path}."
    )
    schema_lines, imports = _render_schema_function(
        ids.schema, "rschema", resource.attributes, description, resource=True
    )
    spec = [
        f"// {ids.spec} describes how {type_name} maps onto the API.",
        f"func {ids.spec}() resourceSpec {{",
        f"\tspec := resourceSpec{{typeName: {_go_string(resource.name)}}}",
        f"\tspec.collectionPath = {_go_string(resource.collection_path)}",
        f"\tspec.itemPath = {_go_string(resource.item_path)}",
        f"\tspec.idAttr = {_go_string(resource.id_attr)}",
        f"\tspec.idParam = {_go_string(resource.id_param)}",
    ]
    for role in ("create", "read", "update", "delete"):
        operation = resource.operation(role)
        if operation is not None:
            spec.append(f"\tspec.{role}Method = {_go_string(operation.method)}")
    if resource.import_parts:
        spec.append(f"\tspec.importParts = []string{{{', '.join(_go_string(part) for part in resource.import_parts)}}}")
    spec += ["\tspec.attributes = []attribute{", *_attribute_literals(resource.attributes), "\t}", "\treturn spec", "}"]
    operations = ", ".join(f"{role} `{ref.method} {ref.path}`" for role, ref in resource.operations)
    body = [
        f"// {ids.constructor} returns the {type_name} resource ({operations}).",
        f"func {ids.constructor}() resource.Resource {{",
        f"\treturn newResource({ids.spec}(), {ids.schema})",
        "}",
        "",
        *spec,
        "",
        *schema_lines,
    ]
    return TerraformProviderFile(
        path=f"internal/provider/resource_{resource.name}.go",
        text=_go_file(
            "provider",
            body,
            external=[f"{_FRAMEWORK}/resource", f"{_FRAMEWORK}/resource/schema", *imports],
            aliases={f"{_FRAMEWORK}/resource/schema": "rschema"},
            license_header=license_header,
        ),
    )


def _render_item_data_source_file(
    source: TerraformItemDataSource, ids: _Identifiers, provider_name: str, license_header: Optional[str]
) -> TerraformProviderFile:
    """Render ``internal/provider/data_source_<name>.go`` for a single-instance data source."""
    type_name = f"{provider_name}_{source.name}"
    description = _sentence(source.description) or f"Reads one {source.schema_name} from {source.item_path}."
    schema_lines, imports = _render_schema_function(
        ids.schema, "dschema", source.attributes, description, resource=False
    )
    body = [
        f"// {ids.constructor} returns the {type_name} data source (`{source.operation.method} "
        f"{source.operation.path}`).",
        f"func {ids.constructor}() datasource.DataSource {{",
        f"\treturn &itemDataSource{{spec: {ids.spec}(), schema: {ids.schema}}}",
        "}",
        "",
        f"// {ids.spec} describes how {type_name} maps onto the API.",
        f"func {ids.spec}() itemDataSourceSpec {{",
        f"\tspec := itemDataSourceSpec{{typeName: {_go_string(source.name)}}}",
        f"\tspec.itemPath = {_go_string(source.item_path)}",
        "\tspec.attributes = []attribute{",
        *_attribute_literals(source.attributes),
        "\t}",
        "\treturn spec",
        "}",
        "",
        *schema_lines,
    ]
    return _data_source_file(source.name, body, imports, license_header)


def _render_list_data_source_file(
    source: TerraformListDataSource, ids: _Identifiers, provider_name: str, license_header: Optional[str]
) -> TerraformProviderFile:
    """Render ``internal/provider/data_source_<name>.go`` for a collection data source."""
    type_name = f"{provider_name}_{source.name}"
    description = f"Reads every {source.schema_name} from {source.collection_path}."
    schema_lines, imports = _render_schema_function(
        ids.schema, "dschema", _list_schema_attributes(source), description, resource=False
    )
    item = _field_literal(source.item, "\t")
    item[0] = f"\tspec.item = {item[0]}"
    body = [
        f"// {ids.constructor} returns the {type_name} data source (`{source.operation.method} "
        f"{source.operation.path}`).",
        f"func {ids.constructor}() datasource.DataSource {{",
        f"\treturn &listDataSource{{spec: {ids.spec}(), schema: {ids.schema}}}",
        "}",
        "",
        f"// {ids.spec} describes how {type_name} maps onto the API.",
        f"func {ids.spec}() listDataSourceSpec {{",
        f"\tspec := listDataSourceSpec{{typeName: {_go_string(source.name)}}}",
        f"\tspec.collectionPath = {_go_string(source.collection_path)}",
        f"\tspec.listMember = {_go_string(source.list_member)}",
    ]
    if source.parents:
        body += ["\tspec.parents = []attribute{", *_attribute_literals(source.parents), "\t}"]
    body += [*item, "\treturn spec", "}", "", *schema_lines]
    return _data_source_file(source.name, body, imports, license_header)


def _data_source_file(
    name: str, body: List[str], imports: Set[str], license_header: Optional[str]
) -> TerraformProviderFile:
    """Assemble a data source file with its imports."""
    return TerraformProviderFile(
        path=f"internal/provider/data_source_{name}.go",
        text=_go_file(
            "provider",
            body,
            external=[f"{_FRAMEWORK}/datasource", f"{_FRAMEWORK}/datasource/schema", *imports],
            aliases={f"{_FRAMEWORK}/datasource/schema": "dschema"},
            license_header=license_header,
        ),
    )


def _environment_variable(provider_name: str, attribute: str) -> str:
    """Return the environment variable a provider setting falls back to."""
    return f"{provider_name.upper()}_{attribute.upper()}"


def _render_provider_file(
    plan: TerraformProviderPlan,
    module_path: str,
    user_agent: str,
    constructors: Tuple[List[str], List[str]],
    license_header: Optional[str],
) -> TerraformProviderFile:
    """Render ``internal/provider/provider.go``: configuration, auth and registration."""
    name = plan.provider_name
    std = {"context", "os"}
    resources, data_sources = constructors
    endpoint_text = (
        f"The API base URL. Defaults to `{plan.base_url}`; falls back to the "
        f"`{_environment_variable(name, 'endpoint')}` environment variable."
    )
    schema = [
        "\tattributes := map[string]schema.Attribute{}",
        '\tattributes["endpoint"] = schema.StringAttribute{Optional: true, Description: '
        f"{_go_string(endpoint_text)}}}",
        '\tattributes["headers"] = schema.MapAttribute{Optional: true, ElementType: types.StringType, Description: '
        f"{_go_string(_HEADERS_DESCRIPTION)}}}",
    ]
    configure = [
        '\tendpoint, diags := setting(ctx, req, "endpoint", '
        + _go_string(_environment_variable(name, "endpoint"))
        + ")",
        "\tresp.Diagnostics.Append(diags...)",
        '\tif endpoint == "" {',
        "\t\tendpoint = defaultEndpoint",
        "\t}",
        '\tc := &client.Client{BaseURL: endpoint, UserAgent: userAgent + "/" + p.version, Headers: '
        "map[string]string{}, Query: map[string]string{}, Cookies: map[string]string{}}",
        "",
        "\tvar headers types.Map",
        '\tresp.Diagnostics.Append(req.Config.GetAttribute(ctx, path.Root("headers"), &headers)...)',
        "\tif !headers.IsNull() && !headers.IsUnknown() {",
        "\t\tconfigured := map[string]string{}",
        "\t\tresp.Diagnostics.Append(headers.ElementsAs(ctx, &configured, false)...)",
        "\t\tfor key, value := range configured {",
        "\t\t\tc.Headers[key] = value",
        "\t\t}",
        "\t}",
    ]
    locals = Names({"c", "ctx", "req", "resp", "p", "diags", "endpoint", "headers", "configured", "key", "value"})
    for setting in plan.auth:
        variables = [locals.take(camel_case(attribute, "credential")) for attribute in setting.attributes]
        for attribute in setting.attributes:
            sensitive = attribute != setting.attributes[0] or setting.kind != "basic"
            label = {
                "bearer": "The bearer token",
                "basic": "The HTTP Basic username" if attribute == setting.attributes[0] else "The HTTP Basic password",
                "api_key": f"The API key, sent as {setting.location} `{setting.parameter}`",
            }[setting.kind]
            text = (
                f"{label} for the `{setting.scheme}` security scheme; falls back to the "
                f"`{_environment_variable(name, attribute)}` environment variable."
            )
            flags = "Optional: true, Sensitive: true" if sensitive else "Optional: true"
            schema.append(
                f"\tattributes[{_go_string(attribute)}] = schema.StringAttribute{{{flags}, Description: "
                f"{_go_string(text)}}}"
            )
        configure.append("")
        for attribute, variable in zip(setting.attributes, variables):
            configure += [
                f"\t{variable}, diags := setting(ctx, req, {_go_string(attribute)}, "
                f"{_go_string(_environment_variable(name, attribute))})",
                "\tresp.Diagnostics.Append(diags...)",
            ]
        first = variables[0]
        configure.append(f'\tif {first} != "" {{')
        if setting.kind == "bearer":
            configure.append(f'\t\tc.Headers[{_go_string(setting.parameter)}] = "Bearer " + {first}')
        elif setting.kind == "basic":
            std.add("encoding/base64")
            configure.append(
                '\t\tc.Headers["Authorization"] = "Basic " + '
                f'base64.StdEncoding.EncodeToString([]byte({first}+":"+{variables[1]}))'
            )
        else:
            target = {"header": "Headers", "query": "Query", "cookie": "Cookies"}[setting.location]
            configure.append(f"\t\tc.{target}[{_go_string(setting.parameter)}] = {first}")
        configure.append("\t}")

    description = _sentence(plan.description) or f"Manages {plan.title} through its API."
    body = [
        "// defaultEndpoint is the first server the contract declares.",
        f"const defaultEndpoint = {_go_string(plan.base_url)}",
        "",
        "// userAgent prefixes the provider version in every request's User-Agent.",
        f"const userAgent = {_go_string(user_agent)}",
        "",
        f"// apiProvider is the {name} provider.",
        "type apiProvider struct {",
        "\tversion string",
        "}",
        "",
        "var _ provider.Provider = (*apiProvider)(nil)",
        "",
        "// New returns the provider constructor providerserver.Serve expects.",
        "func New(version string) func() provider.Provider {",
        "\treturn func() provider.Provider {",
        "\t\treturn &apiProvider{version: version}",
        "\t}",
        "}",
        "",
        "// Metadata names the provider; every resource type is prefixed with this name.",
        "func (p *apiProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp "
        "*provider.MetadataResponse) {",
        f"\tresp.TypeName = {_go_string(name)}",
        "\tresp.Version = p.version",
        "}",
        "",
        "// Schema declares the provider configuration.",
        "func (p *apiProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {",
        *schema,
        f"\tresp.Schema = schema.Schema{{Description: {_go_string(description)}, Attributes: attributes}}",
        "}",
        "",
        "// setting returns a configured string, falling back to an environment variable.",
        "func setting(ctx context.Context, req provider.ConfigureRequest, name, env string) (string, "
        "diag.Diagnostics) {",
        "\tvar value types.String",
        "\tdiags := req.Config.GetAttribute(ctx, path.Root(name), &value)",
        "\tif !value.IsNull() && !value.IsUnknown() {",
        "\t\treturn value.ValueString(), diags",
        "\t}",
        "\treturn os.Getenv(env), diags",
        "}",
        "",
        "// Configure builds the API client every resource and data source sends through.",
        "func (p *apiProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp "
        "*provider.ConfigureResponse) {",
        *configure,
        "",
        "\tresp.DataSourceData = c",
        "\tresp.ResourceData = c",
        "}",
        "",
        "// Resources lists the resources derived from the contract's CRUD operation groups.",
        "func (p *apiProvider) Resources(_ context.Context) []func() resource.Resource {",
        "\treturn []func() resource.Resource{",
        *(f"\t\t{constructor}," for constructor in resources),
        "\t}",
        "}",
        "",
        "// DataSources lists the data sources derived from the contract's read and list operations.",
        "func (p *apiProvider) DataSources(_ context.Context) []func() datasource.DataSource {",
        "\treturn []func() datasource.DataSource{",
        *(f"\t\t{constructor}," for constructor in data_sources),
        "\t}",
        "}",
    ]
    return TerraformProviderFile(
        path="internal/provider/provider.go",
        text=_go_file(
            "provider",
            body,
            std=sorted(std),
            external=[
                f"{_FRAMEWORK}/datasource",
                f"{_FRAMEWORK}/diag",
                f"{_FRAMEWORK}/path",
                f"{_FRAMEWORK}/provider",
                f"{_FRAMEWORK}/provider/schema",
                f"{_FRAMEWORK}/resource",
                f"{_FRAMEWORK}/types",
            ],
            local=[f"{module_path}/internal/client"],
            license_header=license_header,
            doc=[f"// Package provider is the generated Terraform provider for {plan.title}."],
        ),
    )


def _render_main(address: str, module_path: str, license_header: Optional[str]) -> TerraformProviderFile:
    """Render ``main.go``, which serves the provider over the plugin protocol."""
    body = [
        '// version is set by the release build: go build -ldflags "-X main.version=1.2.3".',
        'var version = "dev"',
        "",
        "func main() {",
        "\tvar debug bool",
        '\tflag.BoolVar(&debug, "debug", false, "run the provider with support for debuggers such as delve")',
        "\tflag.Parse()",
        "",
        "\terr := providerserver.Serve(context.Background(), provider.New(version), "
        f"providerserver.ServeOpts{{Address: {_go_string(address)}, Debug: debug}})",
        "\tif err != nil {",
        "\t\tlog.Fatal(err.Error())",
        "\t}",
        "}",
    ]
    return TerraformProviderFile(
        path="main.go",
        text=_go_file(
            "main",
            body,
            std=["context", "flag", "log"],
            external=[f"{_FRAMEWORK}/providerserver"],
            local=[f"{module_path}/internal/provider"],
            license_header=license_header,
            doc=[f"// Command terraform-provider serves the {address} Terraform provider."],
        ),
    )


def _render_go_mod(module_path: str) -> TerraformProviderFile:
    """Render ``go.mod`` with the pinned dependency set."""
    text = "\n".join(
        [
            f"module {module_path}",
            "",
            f"go {GO_DIRECTIVE}",
            "",
            "require (",
            f"\t{_FRAMEWORK} {PLUGIN_FRAMEWORK_VERSION}",
            f"\tgithub.com/hashicorp/terraform-plugin-go {PLUGIN_GO_VERSION}",
            ")",
            "",
            GO_MOD_REQUIRES.rstrip("\n"),
            "",
        ]
    )
    return TerraformProviderFile(path="go.mod", text=text)


# ===========================================================================
# Examples and documentation
# ===========================================================================


def _hcl_string(value: str) -> str:
    """Render ``value`` as an HCL string literal (``${`` and ``%{`` are escaped)."""
    return json.dumps(value, ensure_ascii=False).replace("${", "$${").replace("%{", "%%{")


def _hcl_value(item: TerraformField, indent: str = "  ") -> str:
    """Return an example HCL value for a field."""
    if item.enum:
        first = item.enum[0]
        return _hcl_string(str(first)) if item.kind in {"string", "json"} else json.dumps(first)
    if item.kind == "string":
        return _hcl_string(_FORMAT_EXAMPLES.get(item.format or "", "example"))
    if item.kind == "int":
        return "1"
    if item.kind == "float":
        return "1.5"
    if item.kind == "bool":
        return "true"
    if item.kind == "json":
        return "jsonencode({})"
    if item.kind == "list" and item.elem is not None:
        return f"[{_hcl_value(item.elem, indent)}]"
    if item.kind == "map" and item.elem is not None:
        return f"{{ key = {_hcl_value(item.elem, indent)} }}"
    members = [member for member in item.fields if member.required] or list(item.fields[:1])
    inner = indent + "  "
    pairs = [(member.attr, _hcl_value(member, inner)) for member in members]
    return "\n".join(["{", *_hcl_assignments(pairs, inner), f"{indent}}}"])


def _example_attributes(attributes: Sequence[TerraformAttribute]) -> List[TerraformAttribute]:
    """Pick the attributes an example sets: every required one, then a few optional scalars."""
    required = [attribute for attribute in attributes if attribute.mode == ATTRIBUTE_REQUIRED]
    optional = [
        attribute
        for attribute in attributes
        if attribute.mode == ATTRIBUTE_OPTIONAL_COMPUTED and attribute.field.kind in {"string", "int", "float", "bool"}
    ][:_EXAMPLE_OPTIONAL_ATTRIBUTES]
    return required + optional


def _hcl_assignments(pairs: Sequence[Tuple[str, str]], indent: str = "  ") -> List[str]:
    """Render ``name = value`` lines the way ``terraform fmt`` aligns them.

    ``terraform fmt`` aligns the ``=`` of a run of consecutive single-line assignments; a
    multi-line value ends the run, so it is written unpadded and starts a new one after it.
    """
    lines: List[str] = []
    run: List[Tuple[str, str]] = []

    def flush() -> None:
        width = max((len(name) for name, _ in run), default=0)
        lines.extend(f"{indent}{name.ljust(width)} = {value}" for name, value in run)
        run.clear()

    for name, value in pairs:
        if "\n" in value:
            flush()
            lines.append(f"{indent}{name} = {value}")
        else:
            run.append((name, value))
    flush()
    return lines


def _hcl_block(kind: str, type_name: str, label: str, attributes: Sequence[TerraformAttribute]) -> str:
    """Render one ``resource``/``data`` block."""
    lines = [f'{kind} "{type_name}" "{label}" {{']
    lines += _hcl_assignments([(attribute.name, _hcl_value(attribute.field)) for attribute in attributes])
    lines.append("}")
    return "\n".join(lines) + "\n"


def _provider_example(plan: TerraformProviderPlan, address: str) -> str:
    """Render ``examples/provider/provider.tf``."""
    lines = [
        "terraform {",
        "  required_providers {",
        f"    {plan.provider_name} = {{",
        f'      source = "{address}"',
        "    }",
        "  }",
        "}",
        "",
        f'provider "{plan.provider_name}" {{',
        f"  endpoint = {_hcl_string(plan.base_url)}",
    ]
    for setting in plan.auth:
        for attribute in setting.attributes:
            lines.append(f'  # {attribute} = "..." # or set {_environment_variable(plan.provider_name, attribute)}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _type_label(item: TerraformField) -> str:
    """Return the documentation type label tfplugindocs would print."""
    labels = {"string": "String", "json": "String, JSON", "int": "Number", "float": "Number", "bool": "Boolean"}
    if item.kind in labels:
        return labels[item.kind]
    if item.kind == "object":
        return "Attributes"
    assert item.elem is not None
    if item.elem.kind == "object":
        return "Attributes List" if item.kind == "list" else "Attributes Map"
    container = "List" if item.kind == "list" else "Map"
    return f"{container} of {_type_label(item.elem)}"


def _schema_docs(attributes: Sequence[Tuple[TerraformField, str, bool]], heading: str = "## Schema") -> List[str]:
    """Render a tfplugindocs-style schema section, with one nested section per nested object."""
    lines = [heading, ""]
    nested: List[Tuple[str, TerraformField, str]] = []
    sections = (
        ("Required", ATTRIBUTE_REQUIRED),
        ("Optional", ATTRIBUTE_OPTIONAL_COMPUTED),
        ("Read-Only", ATTRIBUTE_COMPUTED),
    )
    for title, mode in sections:
        members = [(item, force_new) for item, item_mode, force_new in attributes if item_mode == mode]
        if not members:
            continue
        lines += [f"### {title}", ""]
        for item, force_new in members:
            description = _attribute_description(item, force_new=force_new)
            anchor = ""
            target = (
                item
                if item.kind == "object"
                else item.elem
                if item.elem is not None and item.elem.kind == "object"
                else None
            )
            if target is not None:
                anchor = f" (see [below for nested schema](#nestedatt--{item.attr}))"
                nested.append((item.attr, target, mode))
            lines.append(f"- `{item.attr}` ({_type_label(item)}){(' ' + description) if description else ''}{anchor}")
        lines.append("")
    for name, target, mode in nested:
        lines += [f'<a id="nestedatt--{name}"></a>', f"### Nested Schema for `{name}`", ""]
        child_mode = ATTRIBUTE_COMPUTED if mode == ATTRIBUTE_COMPUTED else None
        children = [
            (member, child_mode or (ATTRIBUTE_REQUIRED if member.required else ATTRIBUTE_OPTIONAL_COMPUTED), False)
            for member in target.fields
        ]
        for title, section_mode in sections:
            members = [member for member, member_mode, _ in children if member_mode == section_mode]
            if not members:
                continue
            lines += [f"{title}:", ""]
            for member in members:
                description = _attribute_description(member)
                lines.append(f"- `{member.attr}` ({_type_label(member)}){(' ' + description) if description else ''}")
            lines.append("")
    return lines


def _front_matter(title: str, description: str) -> List[str]:
    """Render the YAML front matter the Terraform Registry reads."""
    return [
        "---",
        f'page_title: "{title}"',
        'subcategory: ""',
        "description: |-",
        f"  {description or title}",
        "---",
        "",
    ]


def _resource_doc(resource: TerraformResource, provider_name: str, example: str) -> str:
    """Render ``docs/resources/<name>.md``."""
    type_name = f"{provider_name}_{resource.name}"
    description = _sentence(resource.description) or f"Manages a {resource.schema_name}."
    import_id = "/".join(f"<{part}>" for part in resource.import_parts)
    lines = [
        *_front_matter(f"{type_name} Resource - terraform-provider-{provider_name}", description),
        f"# {type_name} (Resource)",
        "",
        description,
        "",
        "| Operation | Request |",
        "| --- | --- |",
        *(f"| {role} | `{ref.method} {ref.path}` |" for role, ref in resource.operations),
        "",
        "## Example Usage",
        "",
        "```terraform",
        example.rstrip("\n"),
        "```",
        "",
        *_schema_docs([(attribute.field, attribute.mode, attribute.force_new) for attribute in resource.attributes]),
    ]
    if resource.import_parts:
        lines += [
            "## Import",
            "",
            "Import is supported using the following syntax:",
            "",
            "```shell",
            f'terraform import {type_name}.example "{import_id}"',
            "```",
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _data_source_doc(
    name: str,
    provider_name: str,
    description: str,
    example: str,
    attributes: Sequence[TerraformAttribute],
    request: str,
) -> str:
    """Render ``docs/data-sources/<name>.md``."""
    type_name = f"{provider_name}_{name}"
    lines = [
        *_front_matter(f"{type_name} Data Source - terraform-provider-{provider_name}", description),
        f"# {type_name} (Data Source)",
        "",
        description,
        "",
        f"Reads `{request}`.",
        "",
        "## Example Usage",
        "",
        "```terraform",
        example.rstrip("\n"),
        "```",
        "",
        *_schema_docs([(attribute.field, attribute.mode, False) for attribute in attributes]),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _provider_doc(plan: TerraformProviderPlan, example: str) -> str:
    """Render ``docs/index.md``."""
    name = plan.provider_name
    description = _sentence(plan.description) or f"Manages {plan.title} through its API."
    lines = [
        *_front_matter(f"{name} Provider", description),
        f"# {name} Provider",
        "",
        description,
        "",
        "## Example Usage",
        "",
        "```terraform",
        example.rstrip("\n"),
        "```",
        "",
        "## Schema",
        "",
        "### Optional",
        "",
        f"- `endpoint` (String) The API base URL. Defaults to `{plan.base_url}`; falls back to "
        f"`{_environment_variable(name, 'endpoint')}`.",
        f"- `headers` (Map of String) {_HEADERS_DESCRIPTION}",
    ]
    for setting in plan.auth:
        for attribute in setting.attributes:
            lines.append(
                f"- `{attribute}` "
                f"(String{', Sensitive' if setting.kind != 'basic' or attribute != setting.attributes[0] else ''}) "
                f"Credential for the `{setting.scheme}` security scheme; falls back to "
                f"`{_environment_variable(name, attribute)}`."
            )
    return "\n".join(lines).rstrip("\n") + "\n"


def _readme(
    plan: TerraformProviderPlan,
    address: str,
    module_path: str,
    license_header: Optional[str],
    revision: Optional[str],
) -> str:
    """Render the provider's ``README.md``: build, configure, what it covers and what it does not."""
    name = plan.provider_name
    lines = [
        f"# terraform-provider-{name}",
        "",
        f"A Terraform provider for **{plan.title}**"
        + (f" {plan.version}" if plan.version else "")
        + ", generated by Apiome from the published contract on the Terraform Plugin Framework "
        f"(`{PLUGIN_FRAMEWORK_VERSION}`).",
        "",
    ]
    if license_header:
        lines += ["## Licence", "", "```", license_header.strip(), "```", ""]
    lines += [
        "## Build and try it locally",
        "",
        f"Requires Go {GO_DIRECTIVE.rsplit('.', 1)[0]}+ and Terraform 1.0+.",
        "",
        "```bash",
        "go build -o bin/ .",
        "```",
        "",
        "Point Terraform at the binary with a development override in `~/.terraformrc`, then run "
        "`terraform plan` in any configuration (no `terraform init` needed):",
        "",
        "```hcl",
        "provider_installation {",
        "  dev_overrides {",
        f'    "{address}" = "/absolute/path/to/bin"',
        "  }",
        "  direct {}",
        "}",
        "```",
        "",
        "`examples/` holds a configuration per resource and data source; `docs/` is in the layout the "
        "Terraform Registry publishes.",
        "",
        "## Configure",
        "",
        "| Setting | Environment variable | Purpose |",
        "| --- | --- | --- |",
        f"| `endpoint` | `{_environment_variable(name, 'endpoint')}` | API base URL (default `{plan.base_url}`). |",
        "| `headers` | — | Headers sent with every request. |",
    ]
    for setting in plan.auth:
        for attribute in setting.attributes:
            lines.append(
                f"| `{attribute}` | `{_environment_variable(name, attribute)}` | `{setting.scheme}` credential "
                f"({setting.kind.replace('_', ' ')}). |"
            )
    lines += [
        "",
        "To run it against an Apiome mock, set `endpoint` to the mock's URL and send a session so the "
        'mock keeps state between calls: `headers = { "X-Mock-Session" = "terraform" }`.',
        "",
        "## Resources",
        "",
    ]
    if plan.resources:
        lines += ["| Resource | Schema | Operations | Import |", "| --- | --- | --- | --- |"]
        for resource in plan.resources:
            operations = "<br>".join(f"{role}: `{ref.method} {ref.path}`" for role, ref in resource.operations)
            lines.append(
                f"| `{name}_{resource.name}` | `{resource.schema_name}` | {operations} | "
                + (f"`{'/'.join(resource.import_parts)}`" if resource.import_parts else "disabled")
                + " |"
            )
    else:
        lines.append("The contract has no create/read/delete operation group, so the provider has no resources.")
    lines += ["", "## Data sources", ""]
    sources = [(source.name, f"{source.operation.method} {source.operation.path}") for source in plan.item_data_sources]
    sources += [
        (source.name, f"{source.operation.method} {source.operation.path}") for source in plan.list_data_sources
    ]
    if sources:
        lines += ["| Data source | Reads |", "| --- | --- |"]
        lines += [f"| `{name}_{source}` | `{request}` |" for source, request in sources]
    else:
        lines.append("The contract has no read or list operation that answers with a record.")
    lines += [
        "",
        "## Readiness",
        "",
    ]
    warnings = [warning for warning in plan.warnings if warning.severity == "warning"]
    notes = [warning for warning in plan.warnings if warning.severity != "warning"]
    if not plan.warnings:
        lines.append("Every operation in the contract is covered.")
    for heading, items in (("Not covered", warnings), ("Notes", notes)):
        if items:
            lines += [f"**{heading}**", ""]
            lines += [f"- `{item.code}` — {item.message}" for item in items]
            lines.append("")
    lines += [
        "",
        f"## Steering the mapping with `{HINT_EXTENSION}`",
        "",
        f"Add `{HINT_EXTENSION}` to the OpenAPI document and republish:",
        "",
        '- on an operation: `{"resource": "widget", "operation": "create"}` assigns it a resource and a role '
        "(`create`, `read`, `update`, `delete`, `list`); `false` leaves it out;",
        '- on a schema: `{"resource": "widget", "id": "uuid", "ignore": ["etag"], "forceNew": ["region"], '
        '"import": false, "dataSource": false}` names the resource, its identifier, members to drop or to '
        "replace on change, and turns import or the data sources off.",
        "",
        "---",
        "",
        f"Generated by Apiome `{TERRAFORM_PROVIDER_SCHEMA_VERSION}` · module `{module_path}` · address `{address}`"
        + (f" · revision `{revision}`" if revision else "")
        + ".",
        "",
    ]
    return "\n".join(lines)


# ===========================================================================
# Entry point
# ===========================================================================


def generate_terraform_provider(
    api: CanonicalApi,
    *,
    provider_name: Optional[str] = None,
    namespace: Optional[str] = None,
    module_path: Optional[str] = None,
    license_header: Optional[str] = None,
    user_agent: Optional[str] = None,
    revision: Optional[str] = None,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> TerraformProviderPackage:
    """Generate a complete Terraform provider from a canonical model.

    The result is a pure function of its arguments: nothing here reads the clock, the environment
    or the filesystem, so two calls with the same model and the same branding produce
    byte-identical files.

    Args:
        api: The canonical model to generate from.
        provider_name: The provider type name. Defaults to one derived from the API's identity name,
            then its title.
        namespace: The registry namespace (typically the tenant slug).
        module_path: The ``go.mod`` module path. Defaults to
            ``example.com/<namespace>/terraform-provider-<name>``.
        license_header: A tenant's resolved licence text (SDK-3.4), rendered at the top of every
            ``.go`` file and quoted in the README.
        user_agent: A tenant's resolved user-agent (SDK-3.4); the provider version is appended.
        revision: The published revision the provider was generated from, recorded in the README.
        max_operations: How many operations are considered; the rest are reported.

    Returns:
        The :class:`TerraformProviderPackage`.
    """
    plan = build_terraform_provider_plan(api, provider_name=provider_name, max_operations=max_operations)
    name = plan.provider_name
    resolved_namespace = terraform_namespace(namespace)
    address = terraform_registry_address(resolved_namespace, name)
    resolved_module = (module_path or "").strip() or terraform_module_path(None, resolved_namespace, name)

    files: List[TerraformProviderFile] = [
        _render_go_mod(resolved_module),
        TerraformProviderFile(path="go.sum", text=GO_SUM),
        _render_main(address, resolved_module, license_header),
        TerraformProviderFile(
            path="internal/client/client.go", text=_fixed_file(CLIENT_GO, resolved_module, license_header)
        ),
        TerraformProviderFile(
            path="internal/provider/runtime.go", text=_fixed_file(RUNTIME_GO, resolved_module, license_header)
        ),
        TerraformProviderFile(
            path="terraform-registry-manifest.json",
            text=json.dumps({"version": 1, "metadata": {"protocol_versions": ["6.0"]}}, indent=2) + "\n",
        ),
    ]

    resource_ids = Names()
    data_source_ids = Names()
    resource_constructors: List[str] = []
    data_source_constructors: List[str] = []
    provider_example = _provider_example(plan, address)
    files.append(TerraformProviderFile(path="examples/provider/provider.tf", text=provider_example))
    files.append(TerraformProviderFile(path="docs/index.md", text=_provider_doc(plan, provider_example)))

    for resource in plan.resources:
        stem = resource_ids.take(pascal_case(resource.name, "Resource"))
        ids = _Identifiers(constructor=f"new{stem}Resource", spec=f"spec{stem}Resource", schema=f"schema{stem}Resource")
        resource_constructors.append(ids.constructor)
        files.append(_render_resource_file(resource, ids, name, license_header))
        type_name = f"{name}_{resource.name}"
        example = _hcl_block("resource", type_name, "example", _example_attributes(resource.attributes))
        files.append(TerraformProviderFile(path=f"examples/resources/{type_name}/resource.tf", text=example))
        if resource.import_parts:
            import_id = "/".join(f"<{part}>" for part in resource.import_parts)
            files.append(
                TerraformProviderFile(
                    path=f"examples/resources/{type_name}/import.sh",
                    text=f'terraform import {type_name}.example "{import_id}"\n',
                )
            )
        files.append(
            TerraformProviderFile(
                path=f"docs/resources/{resource.name}.md", text=_resource_doc(resource, name, example)
            )
        )

    for source in plan.item_data_sources:
        stem = data_source_ids.take(pascal_case(source.name, "Source"))
        ids = _Identifiers(
            constructor=f"new{stem}DataSource", spec=f"spec{stem}DataSource", schema=f"schema{stem}DataSource"
        )
        data_source_constructors.append(ids.constructor)
        files.append(_render_item_data_source_file(source, ids, name, license_header))
        type_name = f"{name}_{source.name}"
        lookups = [attribute for attribute in source.attributes if attribute.path_param]
        example = _hcl_block("data", type_name, "example", lookups)
        files.append(TerraformProviderFile(path=f"examples/data-sources/{type_name}/data-source.tf", text=example))
        description = _sentence(source.description) or f"Reads one {source.schema_name}."
        files.append(
            TerraformProviderFile(
                path=f"docs/data-sources/{source.name}.md",
                text=_data_source_doc(
                    source.name,
                    name,
                    description,
                    example,
                    source.attributes,
                    f"{source.operation.method} {source.operation.path}",
                ),
            )
        )

    for listing in plan.list_data_sources:
        stem = data_source_ids.take(pascal_case(listing.name, "Source"))
        ids = _Identifiers(
            constructor=f"new{stem}DataSource", spec=f"spec{stem}DataSource", schema=f"schema{stem}DataSource"
        )
        data_source_constructors.append(ids.constructor)
        files.append(_render_list_data_source_file(listing, ids, name, license_header))
        type_name = f"{name}_{listing.name}"
        example = _hcl_block("data", type_name, "example", listing.parents)
        files.append(TerraformProviderFile(path=f"examples/data-sources/{type_name}/data-source.tf", text=example))
        files.append(
            TerraformProviderFile(
                path=f"docs/data-sources/{listing.name}.md",
                text=_data_source_doc(
                    listing.name,
                    name,
                    f"Reads every {listing.schema_name}.",
                    example,
                    _list_schema_attributes(listing),
                    f"{listing.operation.method} {listing.operation.path}",
                ),
            )
        )

    agent = (user_agent or "").strip() or f"terraform-provider-{name}"
    files.append(
        _render_provider_file(
            plan, resolved_module, agent, (resource_constructors, data_source_constructors), license_header
        )
    )
    files.append(
        TerraformProviderFile(path="README.md", text=_readme(plan, address, resolved_module, license_header, revision))
    )
    files.sort(key=lambda item: item.path)

    return TerraformProviderPackage(
        provider_name=name,
        address=address,
        module_path=resolved_module,
        go_version=GO_DIRECTIVE,
        framework_version=PLUGIN_FRAMEWORK_VERSION,
        files=files,
        plan=plan,
    )
