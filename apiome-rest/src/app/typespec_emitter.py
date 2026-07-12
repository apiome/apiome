"""TypeSpec emitter: canonical model → TypeSpec `.tsp` — MFX-27.1.

The inverse of :class:`app.typespec_normalizer.TypeSpecNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    OperationKind,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .typespec_parser import parse_typespec

__all__ = ["TypeSpecEmitOptions", "TypeSpecEmitter", "TypeSpecFidelityRulePack", "validate_typespec_document"]

_CANONICAL_TO_TYPESPEC: Dict[str, str] = {
    "bool": "boolean",
    "string": "string",
    "i32": "int32",
    "i64": "int64",
    "float": "float32",
    "double": "float64",
    "bytes": "bytes",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class TypeSpecFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for TypeSpec export."""

    target_label = "TypeSpec"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class TypeSpecEmitOptions(EmitOptions):
    """Per-target options for :class:`TypeSpecEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a header comment in the generated TypeSpec document.",
    )
    include_http_imports: bool = Field(
        default=True,
        description="Emit standard `@typespec/http` and `@typespec/rest` imports when absent.",
    )


class TypeSpecEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Microsoft TypeSpec `.tsp` document."""

    key = "typespec"
    format = "typespec"
    label = "TypeSpec"
    description = "Export as a Microsoft TypeSpec API definition (.tsp)."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = TypeSpecEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return TypeSpecFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[TypeSpecEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, TypeSpecEmitOptions)
            else TypeSpecEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _TypeSpecWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _TypeSpecWriter:
    def __init__(self, api: CanonicalApi, options: TypeSpecEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._enums = api.extras.get("typespec_enums") or []
        self._models = api.extras.get("typespec_models") or []
        self._interfaces = api.extras.get("typespec_interfaces") or []
        self._imports = api.extras.get("typespec_imports") or []
        self._usings = api.extras.get("typespec_usings") or []
        self._namespace = api.extras.get("typespec_namespace") or api.identity.namespace
        self._service_title = api.extras.get("typespec_service_title") or api.identity.name
        self.output_path = _output_path(api)

    def render(self) -> str:
        if isinstance(self._enums, list) and self._enums:
            return self._render_from_extras()
        return self._render_from_canonical()

    def _render_from_extras(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._service_title or "Exported API"
            lines.extend(
                [
                    f"// Generated TypeSpec for {title}",
                    "//",
                ]
            )

        imports = list(self._imports) if isinstance(self._imports, list) else []
        if self._options.include_http_imports and not any("@typespec/" in item for item in imports):
            imports = ['import "@typespec/http";', 'import "@typespec/rest";', *imports]
        for import_line in imports:
            lines.append(str(import_line).rstrip(";") + ";")

        usings = list(self._usings) if isinstance(self._usings, list) else []
        if self._options.include_http_imports and not usings:
            usings = ["TypeSpec.Http", "TypeSpec.Rest"]
        for using in usings:
            lines.append(f"using {using};")
        if imports or usings:
            lines.append("")

        if self._service_title:
            lines.append(f'@service(#{{ title: "{self._service_title}" }})')
        if self._namespace:
            lines.append(f"namespace {self._namespace};")
            lines.append("")

        for enum_data in self._enums:
            if not isinstance(enum_data, dict):
                continue
            self._append_enum(lines, enum_data)

        for model_data in self._models:
            if not isinstance(model_data, dict):
                continue
            self._append_model(lines, model_data)

        for interface_data in self._interfaces:
            if not isinstance(interface_data, dict):
                continue
            self._append_interface(lines, interface_data)

        return "\n".join(lines).rstrip() + "\n"

    def _render_from_canonical(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._service_title or "Exported API"
            lines.extend([f"// Generated TypeSpec for {title}", "//", ""])
        if self._options.include_http_imports:
            lines.extend(
                [
                    'import "@typespec/http";',
                    'import "@typespec/rest";',
                    "using TypeSpec.Http;",
                    "using TypeSpec.Rest;",
                    "",
                ]
            )
        if self._service_title:
            lines.append(f'@service(#{{ title: "{self._service_title}" }})')
        namespace = self._namespace or "Exported"
        lines.append(f"namespace {namespace};")
        lines.append("")

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            if type_.kind is TypeKind.ENUM:
                self._append_enum(
                    lines,
                    {
                        "name": type_.name,
                        "values": [value.name for value in type_.enum_values],
                        "documentation": type_.description,
                    },
                )
            elif type_.kind is TypeKind.RECORD:
                self._append_model(
                    lines,
                    {
                        "name": type_.name,
                        "documentation": type_.description,
                        "fields": [
                            {
                                "name": field.name,
                                "type": self._render_type_ref(field.type, field=field),
                                "optional": field.type.nullable is not False,
                                "decorators": (
                                    ["@key"]
                                    if field.extras.get("typespec_key")
                                    else []
                                ),
                                "documentation": field.description,
                            }
                            for field in type_.fields
                        ],
                    },
                )

        for service in self._api.services:
            route_prefix = None
            if isinstance(service.extras, dict):
                route_prefix = service.extras.get("typespec_route_prefix")
            self._append_interface(
                lines,
                {
                    "name": service.name,
                    "route_prefix": route_prefix,
                    "operations": [
                        {
                            "name": operation.name,
                            "verb": (operation.http_method or "get").lower(),
                            "return_type": self._payload_type_name(operation),
                            "is_array_return": self._payload_is_array(operation),
                            "documentation": operation.description,
                            "parameters": self._operation_parameters(operation),
                        }
                        for operation in service.operations
                    ],
                },
            )

        return "\n".join(lines).rstrip() + "\n"

    def _append_enum(self, lines: List[str], enum_data: dict) -> None:
        name = str(enum_data.get("name", "Enum"))
        if enum_data.get("documentation"):
            lines.append(f"/// {enum_data['documentation']}")
        lines.append(f"enum {name} {{")
        for value in enum_data.get("values", []):
            lines.append(f"  {value},")
        lines.append("}")
        lines.append("")
        self.tracker.record(name, Provenance.SOURCE)

    def _append_model(self, lines: List[str], model_data: dict) -> None:
        name = str(model_data.get("name", "Model"))
        if model_data.get("documentation"):
            lines.append(f"/// {model_data['documentation']}")
        lines.append(f"model {name} {{")
        for field in model_data.get("fields", []):
            if not isinstance(field, dict):
                continue
            if field.get("documentation"):
                lines.append(f"  /// {field['documentation']}")
            decorators = field.get("decorators") or []
            for decorator in decorators:
                lines.append(f"  {decorator}")
            optional = "?" if field.get("optional") else ""
            lines.append(f"  {field.get('name', 'field')}{optional}: {field.get('type', 'string')};")
        lines.append("}")
        lines.append("")
        self.tracker.record(name, Provenance.SOURCE)

    def _append_interface(self, lines: List[str], interface_data: dict) -> None:
        name = str(interface_data.get("name", "Service"))
        route_prefix = interface_data.get("route_prefix")
        if route_prefix:
            lines.append(f'@route("{route_prefix}")')
        if interface_data.get("documentation"):
            lines.append(f"/// {interface_data['documentation']}")
        lines.append(f"interface {name} {{")
        for operation in interface_data.get("operations", []):
            if not isinstance(operation, dict):
                continue
            if operation.get("documentation"):
                lines.append(f"  /// {operation['documentation']}")
            verb = str(operation.get("verb", "get")).lower()
            params = self._render_parameters(operation.get("parameters", []))
            return_type = str(operation.get("return_type", "void"))
            if operation.get("is_array_return"):
                return_type = f"{return_type}[]"
            lines.append(
                f"  @{verb} {operation.get('name', 'operation')}({params}): {return_type};"
            )
        lines.append("}")
        lines.append("")
        self.tracker.record(name, Provenance.SOURCE)

    def _render_parameters(self, parameters: Any) -> str:
        if not isinstance(parameters, list):
            return ""
        rendered: List[str] = []
        for param in parameters:
            if not isinstance(param, dict):
                continue
            location = str(param.get("location", "query"))
            prefix = {
                "path": "@path ",
                "query": "@query ",
                "header": "@header ",
                "body": "@body ",
            }.get(location, "")
            rendered.append(f"{prefix}{param.get('name', 'param')}: {param.get('type', 'string')}")
        return ", ".join(rendered)

    def _render_type_ref(self, ref: TypeRef, *, field: Optional[CanonicalField] = None) -> str:
        if field is not None:
            stored = field.extras.get("typespec_type")
            if isinstance(stored, str) and stored:
                return stored
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"{inner}[]"
        if ref.name:
            mapped = _CANONICAL_TO_TYPESPEC.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target is not None:
                return target.name
            return ref.name.split(".")[-1]
        return "string"

    def _payload_type_name(self, operation) -> str:
        for message in operation.messages:
            if message.role is MessageRole.RESPONSE and message.payload is not None:
                return self._render_type_ref(message.payload)
        return "void"

    def _payload_is_array(self, operation) -> bool:
        for message in operation.messages:
            if message.role is MessageRole.RESPONSE and message.payload is not None:
                return message.payload.item is not None
        return False

    def _operation_parameters(self, operation) -> List[dict]:
        parameters: List[dict] = []
        for param in operation.parameters:
            parameters.append(
                {
                    "name": param.name,
                    "type": self._render_type_ref(param.type),
                    "location": (
                        param.extras.get("typespec_location")
                        if isinstance(param.extras, dict)
                        else None
                    )
                    or param.location.value,
                }
            )
        for message in operation.messages:
            if message.role is MessageRole.REQUEST and message.payload is not None:
                parameters.append(
                    {
                        "name": "body",
                        "type": self._render_type_ref(message.payload),
                        "location": "body",
                    }
                )
        return parameters


def _output_path(api: CanonicalApi) -> str:
    namespace = api.identity.namespace or api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace).strip("_") or "api"
    return f"{safe}.tsp"


def validate_typespec_document(content: str) -> None:
    """Validate TypeSpec text by re-parsing it."""
    parse_typespec(content)
