"""Swagger 2.0 → canonical model normalizer — MFI-30.1 (#4394).

Maps a parsed **Swagger 2.0** document into a :class:`~app.canonical_model.CanonicalApi`
with the same semantic projection as OpenAPI 3.x normalization:

* ``info`` → :class:`~app.canonical_model.ApiIdentity` + title/version/description;
* ``host``/``basePath``/``schemes`` → :class:`~app.canonical_model.Server`;
* ``definitions`` → :class:`~app.canonical_model.Type` (via
  :class:`app.normalizer.SchemaCoercer` with ``#/definitions/`` refs);
* ``paths`` → :class:`~app.canonical_model.Operation`, grouped by first ``tag``;
* ``body``/``formData`` parameters → request :class:`~app.canonical_model.Message`;
* ``responses`` (+ ``produces``) → response/error messages with media types.

Self-registers under ``swagger-2.0`` so :func:`app.normalizer.get_normalizer` and
:class:`app.openapi_import_source.OpenApiImportSource` resolve Swagger documents
without raising.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
)
from .normalizer import Keys, Normalizer, SchemaCoercer, coerce_constraints, normalize_ordering

__all__ = ["Swagger2Normalizer"]

_HTTP_METHODS: Tuple[str, ...] = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
)

_PARAM_LOCATIONS: Dict[str, ParameterLocation] = {
    "path": ParameterLocation.PATH,
    "query": ParameterLocation.QUERY,
    "header": ParameterLocation.HEADER,
}

_DEFAULT_SERVICE = "default"
_DEFINITIONS_REF_PREFIX = "#/definitions/"


class Swagger2Normalizer(Normalizer, register=True):
    """Normalize a parsed Swagger 2.0 document into a :class:`CanonicalApi`."""

    format = "swagger-2.0"
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, dict):
            raise ValueError("Swagger 2.0 source must be a parsed mapping (dict)")
        self._validate_version(source)

        info = source.get("info") or {}
        definitions = source.get("definitions") or {}
        coercer = SchemaCoercer(components=definitions, ref_prefix=_DEFINITIONS_REF_PREFIX)

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=info.get("title") or "Untitled API"),
            version=info.get("version"),
            title=info.get("title"),
            description=info.get("description"),
            servers=self._servers(source),
            services=self._services(source, coercer),
            types=coercer.named_types_from_components(),
            raw=source if include_raw else None,
        )
        return normalize_ordering(api)

    @staticmethod
    def _validate_version(source: Dict[str, Any]) -> None:
        swagger = source.get("swagger")
        if isinstance(swagger, str) and swagger.startswith("2."):
            return
        if isinstance(swagger, (int, float)) and str(swagger).startswith("2"):
            return
        raise ValueError(
            "not a Swagger 2.0 document (missing or unsupported `swagger` version)"
        )

    @staticmethod
    def _servers(source: Dict[str, Any]) -> List[Server]:
        schemes = source.get("schemes") or ["https"]
        host = source.get("host") or "localhost"
        base_path = source.get("basePath") or "/"
        if not isinstance(schemes, list):
            schemes = ["https"]
        return [
            Server(url=f"{scheme}://{host}{base_path}")
            for scheme in schemes
            if isinstance(scheme, str)
        ]

    def _services(self, source: Dict[str, Any], coercer: SchemaCoercer) -> List[Service]:
        tag_descriptions = {
            t["name"]: t.get("description")
            for t in (source.get("tags") or [])
            if isinstance(t, dict) and "name" in t
        }
        by_service: Dict[str, List[Operation]] = {}
        global_consumes = source.get("consumes")
        global_produces = source.get("produces")

        for path, item in (source.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            shared_params = [
                self._resolve_parameter(param, source)
                for param in (item.get("parameters") or [])
            ]
            for method in _HTTP_METHODS:
                op_obj = item.get(method)
                if not isinstance(op_obj, dict):
                    continue
                operation = self._operation(
                    method,
                    path,
                    op_obj,
                    shared_params,
                    coercer,
                    source,
                    global_consumes=global_consumes,
                    global_produces=global_produces,
                )
                service_key = operation.tags[0] if operation.tags else _DEFAULT_SERVICE
                by_service.setdefault(service_key, []).append(operation)

        return [
            Service(
                key=key,
                name=key,
                description=tag_descriptions.get(key),
                operations=ops,
            )
            for key, ops in by_service.items()
        ]

    def _operation(
        self,
        method: str,
        path: str,
        op_obj: Dict[str, Any],
        shared_params: List[Dict[str, Any]],
        coercer: SchemaCoercer,
        source: Dict[str, Any],
        *,
        global_consumes: Any,
        global_produces: Any,
    ) -> Operation:
        op_key = Keys.operation_http(method, path)
        tags = [t for t in (op_obj.get("tags") or []) if isinstance(t, str)]

        extras: Dict[str, Any] = {}
        if op_obj.get("operationId"):
            extras["operationId"] = op_obj["operationId"]
        if op_obj.get("summary"):
            extras["summary"] = op_obj["summary"]

        effective_params = [
            self._resolve_parameter(param, source)
            for param in self._merge_parameters(shared_params, op_obj.get("parameters") or [])
        ]
        consumes = op_obj.get("consumes") or global_consumes
        produces = op_obj.get("produces") or global_produces

        return Operation(
            key=op_key,
            name=op_obj.get("operationId") or op_key,
            kind=OperationKind.REQUEST_RESPONSE,
            description=op_obj.get("description") or op_obj.get("summary"),
            deprecated=bool(op_obj.get("deprecated", False)),
            http_method=method.upper(),
            http_path=path,
            parameters=self._parameters(op_key, effective_params, coercer),
            messages=self._messages(
                op_key, effective_params, op_obj.get("responses") or {}, coercer, consumes, produces
            ),
            tags=tags,
            extras=extras,
        )

    @staticmethod
    def _resolve_parameter(param: Any, source: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(param, dict):
            return {}
        ref = param.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/parameters/"):
            pool = source.get("parameters") or {}
            name = ref.rsplit("/", 1)[-1]
            resolved = pool.get(name) if isinstance(pool, dict) else None
            if isinstance(resolved, dict):
                return Swagger2Normalizer._resolve_parameter(resolved, source)
        return param

    @staticmethod
    def _merge_parameters(
        shared: List[Dict[str, Any]], own: List[Any]
    ) -> List[Dict[str, Any]]:
        merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for param in list(shared) + list(own):
            if isinstance(param, dict) and "name" in param and "in" in param:
                merged[(param["name"], param["in"])] = param
        return list(merged.values())

    def _parameters(
        self, op_key: str, params: List[Dict[str, Any]], coercer: SchemaCoercer
    ) -> List[Parameter]:
        result: List[Parameter] = []
        for param in params:
            location_name = param.get("in")
            if location_name in {"body", "formData"}:
                continue
            location = _PARAM_LOCATIONS.get(location_name or "")
            if location is None:
                continue
            schema = _parameter_schema(param)
            required = bool(param.get("required", False)) or location is ParameterLocation.PATH
            result.append(
                Parameter(
                    key=Keys.parameter(op_key, location.value, param["name"]),
                    name=param["name"],
                    location=location,
                    type=coercer.type_ref(schema, required=required),
                    required=required,
                    default=schema.get("default"),
                    constraints=coerce_constraints(schema),
                    description=param.get("description"),
                    deprecated=bool(param.get("deprecated", False)),
                )
            )
        return result

    def _messages(
        self,
        op_key: str,
        params: List[Dict[str, Any]],
        responses: Dict[str, Any],
        coercer: SchemaCoercer,
        consumes: Any,
        produces: Any,
    ) -> List[Message]:
        messages: List[Message] = []

        request = self._request_message(op_key, params, coercer, consumes)
        if request is not None:
            messages.append(request)

        content_types = _media_types(produces, default=["application/json"])
        for status_code, response in responses.items():
            if not isinstance(response, dict):
                continue
            schema = response.get("schema") if isinstance(response.get("schema"), dict) else {}
            payload, payload_schema = self._payload(schema, coercer)
            messages.append(
                Message(
                    key=Keys.response_message(op_key, str(status_code)),
                    role=self._response_role(str(status_code)),
                    payload=payload,
                    payload_schema=payload_schema,
                    headers=self._response_headers(
                        response.get("headers"), op_key, status_code, coercer
                    ),
                    content_types=content_types if schema else [],
                    status_code=str(status_code),
                    description=response.get("description"),
                )
            )

        return messages

    def _request_message(
        self,
        op_key: str,
        params: List[Dict[str, Any]],
        coercer: SchemaCoercer,
        consumes: Any,
    ) -> Optional[Message]:
        body_params = [p for p in params if p.get("in") == "body"]
        form_params = [p for p in params if p.get("in") == "formData"]

        if body_params:
            body = body_params[0]
            schema = _parameter_schema(body)
            payload, payload_schema = self._payload(schema, coercer)
            return Message(
                key=Keys.request_message(op_key),
                role=MessageRole.REQUEST,
                payload=payload,
                payload_schema=payload_schema,
                content_types=_media_types(consumes, default=["application/json"]),
                description=body.get("description"),
            )

        if form_params:
            has_file = any(p.get("type") == "file" for p in form_params)
            content_type = (
                "multipart/form-data"
                if has_file
                else _media_types(consumes, default=["application/x-www-form-urlencoded"])[0]
            )
            properties: Dict[str, Any] = {}
            required_names: List[str] = []
            for param in form_params:
                properties[param["name"]] = _form_data_property_schema(param)
                if param.get("required"):
                    required_names.append(param["name"])
            schema: Dict[str, Any] = {"type": "object", "properties": properties}
            if required_names:
                schema["required"] = required_names
            return Message(
                key=Keys.request_message(op_key),
                role=MessageRole.REQUEST,
                payload=None,
                payload_schema=schema,
                content_types=[content_type],
            )

        return None

    @staticmethod
    def _response_role(status_code: str) -> MessageRole:
        return MessageRole.ERROR if status_code[:1] in {"4", "5"} else MessageRole.RESPONSE

    @staticmethod
    def _payload(
        schema: Dict[str, Any], coercer: SchemaCoercer
    ) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        if not schema:
            return None, None
        type_ = schema.get("type")
        is_typed_use_site = (
            "$ref" in schema
            or type_ in {"array", "string", "number", "integer", "boolean"}
            or isinstance(type_, list)
        )
        if is_typed_use_site:
            return coercer.type_ref(schema, required=True), None
        return None, schema

    def _response_headers(
        self,
        headers: Optional[Dict[str, Any]],
        op_key: str,
        status_code: Any,
        coercer: SchemaCoercer,
    ) -> List[CanonicalField]:
        if not isinstance(headers, dict):
            return []
        msg_key = Keys.response_message(op_key, str(status_code))
        result: List[CanonicalField] = []
        for name, spec in headers.items():
            if not isinstance(spec, dict):
                continue
            schema = _header_schema(spec)
            result.append(
                CanonicalField(
                    key=Keys.field(msg_key, name),
                    name=name,
                    type=coercer.type_ref(schema, required=bool(spec.get("required", False))),
                    constraints=coerce_constraints(schema),
                    description=spec.get("description"),
                    deprecated=bool(spec.get("deprecated", False)),
                )
            )
        return result


def _media_types(value: Any, *, default: List[str]) -> List[str]:
    if isinstance(value, list):
        types = [item for item in value if isinstance(item, str)]
        if types:
            return sorted(types)
    return list(default)


def _parameter_schema(param: Dict[str, Any]) -> Dict[str, Any]:
    nested = param.get("schema")
    if isinstance(nested, dict):
        return nested

    schema: Dict[str, Any] = {}
    param_type = param.get("type")
    if param_type == "file":
        schema["type"] = "string"
        schema["format"] = "binary"
    elif param_type:
        schema["type"] = param_type

    for key in (
        "format",
        "enum",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "$ref",
    ):
        if key in param:
            schema[key] = param[key]

    items = param.get("items")
    if isinstance(items, dict):
        schema["items"] = _parameter_schema({"schema": items}) if "type" not in items else items

    return schema


def _form_data_property_schema(param: Dict[str, Any]) -> Dict[str, Any]:
    schema = _parameter_schema(param)
    if param.get("type") == "file":
        schema["type"] = "string"
        schema["format"] = "binary"
    return schema


def _header_schema(header_def: Dict[str, Any]) -> Dict[str, Any]:
    nested = header_def.get("schema")
    if isinstance(nested, dict):
        return nested
    schema: Dict[str, Any] = {}
    if "type" in header_def:
        schema["type"] = header_def["type"]
    if "format" in header_def:
        schema["format"] = header_def["format"]
    return schema
