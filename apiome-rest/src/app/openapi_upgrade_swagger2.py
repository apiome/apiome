"""Swagger 2.0 → OpenAPI 3.0 hop of the upgrade assistant — COA-2.6 (#7049).

:func:`upgrade_swagger2_to_30` rewrites a Swagger 2.0 document into OpenAPI 3.0 and records
every rewrite on a :class:`~app.openapi_upgrade_rules.ChangeLog`, so the plan the user reviews
lists each one. Schemas stay in the 3.0 dialect (``nullable``, ``example``) — the next hop
(3.0 → 3.1) moves them to JSON Schema 2020-12.

Unlike the catalog convert passthrough (:func:`app.conversion_passthrough.upgrade_swagger2_to_openapi31`,
which only needs a usable 3.1 document), this hop is built for a reviewed upgrade: it keeps
every ``x-`` extension, maps ``collectionFormat`` (including the ``csv`` default) to
``style``/``explode``, moves response ``examples`` into ``content``, inlines reusable ``body`` /
``formData`` parameters, and names each change. Pointers in the change records are the
Swagger document's own (the input of the hop).

Pure and deterministic: the input is never mutated and the output's key order follows the
input's.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from .conversion_passthrough import _upgrade_security_scheme
from .openapi_document_walk import join_pointer
from .openapi_upgrade_rules import ChangeLog

__all__ = ["OPENAPI_30_UPGRADE_VERSION", "upgrade_swagger2_to_30"]

#: The version string the 2.0 → 3.0 hop writes (the latest 3.0 patch release).
OPENAPI_30_UPGRADE_VERSION = "3.0.4"

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch")

# Swagger reference prefixes and the OpenAPI 3.0 component each one moves to.
_REF_HOMES = (
    ("#/definitions/", "#/components/schemas/"),
    ("#/parameters/", "#/components/parameters/"),
    ("#/responses/", "#/components/responses/"),
)

# Inline keywords of a Swagger parameter / header / items object that belong in a 3.0 schema.
_INLINE_SCHEMA_KEYS = (
    "type",
    "format",
    "items",
    "enum",
    "default",
    "maximum",
    "exclusiveMaximum",
    "minimum",
    "exclusiveMinimum",
    "maxLength",
    "minLength",
    "pattern",
    "maxItems",
    "minItems",
    "uniqueItems",
    "multipleOf",
)

# Parameter keys that stay on a 3.0 Parameter Object unchanged.
_PARAMETER_KEYS = ("name", "in", "description", "required", "deprecated", "allowEmptyValue")

# Operation keys copied unchanged (3.0 has the same meaning).
_OPERATION_KEYS = ("tags", "summary", "description", "externalDocs", "operationId", "deprecated", "security")

# collectionFormat → (style, explode) for query parameters; path / header use ``simple``.
_QUERY_STYLES = {
    "csv": ("form", False),
    "ssv": ("spaceDelimited", False),
    "pipes": ("pipeDelimited", False),
    "multi": ("form", True),
}

_FORM_MEDIA_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def upgrade_swagger2_to_30(document: Dict[str, Any], log: ChangeLog) -> Dict[str, Any]:
    """Return an OpenAPI 3.0 rewrite of a Swagger 2.0 ``document``, recording every change.

    Args:
        document: A parsed Swagger 2.0 document (``swagger: "2.0"``).
        log: The hop's change log; one record per rewrite is appended.

    Returns:
        A new OpenAPI 3.0 document (``openapi`` = :data:`OPENAPI_30_UPGRADE_VERSION`).
    """
    src = copy.deepcopy(document)
    context = _Context(src, log)
    out: Dict[str, Any] = {"openapi": OPENAPI_30_UPGRADE_VERSION}
    log.record(
        "openapi-version",
        "/swagger",
        f"swagger {src.get('swagger')!s} becomes openapi {OPENAPI_30_UPGRADE_VERSION}",
        before={"swagger": src.get("swagger")},
        after={"openapi": OPENAPI_30_UPGRADE_VERSION},
        target_pointer="/openapi",
    )
    for key, value in src.items():
        if key == "info":
            out["info"] = value
        elif key in ("host", "basePath", "schemes"):
            if "servers" not in out:
                servers = context.servers(src.get("schemes"))
                if servers:
                    out["servers"] = servers
        elif key in ("consumes", "produces"):
            continue
        elif key == "paths":
            out["paths"] = context.paths(value)
        elif key in ("definitions", "parameters", "responses", "securityDefinitions"):
            continue
        elif key == "swagger":
            continue
        else:
            # tags, security, externalDocs and every x- extension mean the same in 3.0.
            out[key] = value
    if "paths" not in out:
        out["paths"] = {}
    if any(key in src for key in ("consumes", "produces")):
        log.record(
            "global-media-types",
            "",
            "Document-level consumes / produces were folded into each request body and response",
            before={key: src[key] for key in ("consumes", "produces") if key in src},
        )
    components = context.components()
    if components:
        out["components"] = components
    return out


class _Context:
    """The document-wide state the hop needs: defaults, reusable parameters and the log."""

    def __init__(self, src: Dict[str, Any], log: ChangeLog) -> None:
        self.src = src
        self.log = log
        self.consumes = _media_list(src.get("consumes"))
        self.produces = _media_list(src.get("produces"))
        params = src.get("parameters")
        self.shared_parameters: Dict[str, Any] = params if isinstance(params, dict) else {}

    # -- servers ---------------------------------------------------------------------------

    def servers(self, schemes: Any, pointer: str = "", rule: str = "servers-from-host") -> List[Dict[str, str]]:
        """Build ``servers`` from ``host`` / ``basePath`` and ``schemes``, recording the change.

        Args:
            schemes: The ``schemes`` list in force (document or operation level).
            pointer: Pointer of the object that carried them.
            rule: ``servers-from-host`` (document) or ``operation-schemes-to-servers``.

        Returns:
            The server list; empty when the document names neither a host nor a base path.
        """
        host = self.src.get("host")
        base_path = self.src.get("basePath") or ""
        if not isinstance(base_path, str):
            base_path = ""
        if base_path and not base_path.startswith("/"):
            base_path = "/" + base_path
        before = {key: self.src[key] for key in ("host", "basePath") if key in self.src}
        if schemes is not None:
            before["schemes"] = schemes
        if not isinstance(host, str) or not host.strip():
            if not base_path:
                return []
            servers = [{"url": base_path}]
            self.log.record(
                rule, pointer, f"basePath {base_path} becomes a relative server URL", before=before, after=servers
            )
            return servers
        names = [str(s) for s in schemes if s] if isinstance(schemes, list) and schemes else []
        review = not names
        servers = [{"url": f"{scheme}://{host}{base_path}"} for scheme in (names or ["https"])]
        summary = ", ".join(server["url"] for server in servers)
        if review:
            summary += " (no schemes were declared, so https is assumed)"
        self.log.record(rule, pointer, f"Server URL: {summary}", before=before, after=servers, review=review)
        return servers

    # -- components ------------------------------------------------------------------------

    def components(self) -> Dict[str, Any]:
        """The ``components`` object: schemas, parameters, responses and security schemes."""
        out: Dict[str, Any] = {}
        definitions = self.src.get("definitions")
        if isinstance(definitions, dict) and definitions:
            schemas: Dict[str, Any] = {}
            for name, schema in definitions.items():
                pointer = join_pointer("", "definitions", name)
                target = join_pointer("", "components", "schemas", name)
                self.log.record(
                    "definition-to-component-schema",
                    pointer,
                    f"definitions/{name} moves to components/schemas/{name}",
                    target_pointer=target,
                )
                schemas[name] = self.schema(schema, pointer)
            out["schemas"] = schemas
        parameters: Dict[str, Any] = {}
        for name, param in self.shared_parameters.items():
            pointer = join_pointer("", "parameters", name)
            if isinstance(param, dict) and param.get("in") in ("body", "formData"):
                self.log.record(
                    "body-parameter-inlined",
                    pointer,
                    f"Reusable {param.get('in')} parameter {name} is inlined into each operation that uses it",
                    before={"in": param.get("in")},
                    review=False,
                )
                continue
            target = join_pointer("", "components", "parameters", name)
            self.log.record(
                "parameter-to-component",
                pointer,
                f"parameters/{name} moves to components/parameters/{name}",
                target_pointer=target,
            )
            parameters[name] = self.parameter(param, pointer)
        if parameters:
            out["parameters"] = parameters
        responses = self.src.get("responses")
        if isinstance(responses, dict) and responses:
            converted: Dict[str, Any] = {}
            for name, response in responses.items():
                pointer = join_pointer("", "responses", name)
                self.log.record(
                    "response-to-component",
                    pointer,
                    f"responses/{name} moves to components/responses/{name}",
                    target_pointer=join_pointer("", "components", "responses", name),
                )
                converted[name] = self.response(response, pointer, self.produces)
            out["responses"] = converted
        security = self.src.get("securityDefinitions")
        if isinstance(security, dict) and security:
            schemes: Dict[str, Any] = {}
            for name, scheme in security.items():
                if not isinstance(scheme, dict):
                    continue
                pointer = join_pointer("", "securityDefinitions", name)
                upgraded = _upgrade_security_scheme(scheme)
                for key, value in scheme.items():
                    if key.startswith("x-"):
                        upgraded[key] = value
                self.log.record(
                    "security-definition-to-scheme",
                    pointer,
                    f"securityDefinitions/{name} ({scheme.get('type')}) moves to components/securitySchemes/{name}",
                    before=scheme,
                    after=upgraded,
                    target_pointer=join_pointer("", "components", "securitySchemes", name),
                )
                schemes[name] = upgraded
            out["securitySchemes"] = schemes
        return out

    # -- references ------------------------------------------------------------------------

    def ref(self, value: Any, pointer: str) -> Any:
        """Rewrite one Swagger ``$ref`` to its ``#/components/…`` home, recording the change."""
        if not isinstance(value, str):
            return value
        for old, new in _REF_HOMES:
            if value.startswith(old):
                rewritten = new + value[len(old) :]
                self.log.record(
                    "ref-rewritten",
                    pointer,
                    f"$ref {value} becomes {rewritten}",
                    before={"$ref": value},
                    after={"$ref": rewritten},
                )
                return rewritten
        return value

    # -- schemas ---------------------------------------------------------------------------

    def schema(self, schema: Any, pointer: str) -> Any:
        """Return a 3.0 copy of a Swagger Schema Object (and its subschemas), recording each rewrite."""
        if not isinstance(schema, dict):
            return schema
        out: Dict[str, Any] = {}
        for key, value in schema.items():
            child = join_pointer(pointer, key)
            if key == "$ref":
                out[key] = self.ref(value, pointer)
            elif key in ("properties",) and isinstance(value, dict):
                out[key] = {name: self.schema(sub, join_pointer(child, name)) for name, sub in value.items()}
            elif key == "allOf" and isinstance(value, list):
                out[key] = [self.schema(sub, join_pointer(child, index)) for index, sub in enumerate(value)]
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                out[key] = self.schema(value, child)
            elif key == "discriminator" and isinstance(value, str):
                out[key] = {"propertyName": value}
                self.log.record(
                    "discriminator-to-object",
                    pointer,
                    f"discriminator {value!r} becomes discriminator.propertyName",
                    before={"discriminator": value},
                    after={"discriminator": out[key]},
                )
            elif key == "x-nullable" and isinstance(value, bool):
                if value:
                    out["nullable"] = True
                self.log.record(
                    "x-nullable-to-nullable",
                    pointer,
                    "x-nullable: true becomes nullable: true" if value else "x-nullable: false is removed",
                    before={"x-nullable": value},
                    after={"nullable": True} if value else None,
                )
            else:
                out[key] = value
        if out.get("type") == "file":
            out["type"] = "string"
            out["format"] = "binary"
            self.log.record(
                "file-to-binary",
                pointer,
                "type: file becomes type: string, format: binary",
                before={"type": "file"},
                after={"type": "string", "format": "binary"},
            )
        return out

    # -- parameters ------------------------------------------------------------------------

    def parameter(self, param: Any, pointer: str) -> Any:
        """Return a 3.0 Parameter Object (or a rewritten reference) for a non-body parameter."""
        if not isinstance(param, dict):
            return param
        if "$ref" in param:
            return {**param, "$ref": self.ref(param["$ref"], pointer)}
        out: Dict[str, Any] = {key: param[key] for key in _PARAMETER_KEYS if key in param}
        schema = self.inline_schema(param, pointer)
        if schema:
            out["schema"] = schema
        style = self.collection_style(param, pointer, schema)
        if style is not None:
            out.update(style)
        for key, value in param.items():
            if key.startswith("x-") and key != "x-nullable":
                out[key] = value
        if "x-example" in param and "example" not in out:
            out["example"] = param["x-example"]
        return out

    def inline_schema(self, param: Dict[str, Any], pointer: str) -> Dict[str, Any]:
        """Move a parameter's / header's inline type keywords into a ``schema``, recording it."""
        moved = {key: param[key] for key in _INLINE_SCHEMA_KEYS if key in param}
        if "x-nullable" in param:
            moved["x-nullable"] = param["x-nullable"]
        if not moved:
            return {}
        schema = self.schema(_items_without_collection(moved), pointer)
        self.log.record(
            "parameter-type-to-schema",
            pointer,
            "Inline " + ", ".join(sorted(k for k in moved if k != "x-nullable")) + " move into schema",
            before=moved,
            after={"schema": schema},
        )
        return schema

    def collection_style(self, param: Dict[str, Any], pointer: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map an array parameter's ``collectionFormat`` to ``style``/``explode``; ``None`` when n/a."""
        if schema.get("type") != "array":
            return None
        location = param.get("in")
        declared = param.get("collectionFormat")
        fmt = declared or "csv"
        before = {"collectionFormat": fmt if declared else "csv (default)"}
        if location == "query":
            if fmt not in _QUERY_STYLES:
                self.log.record(
                    "collection-format-to-style",
                    pointer,
                    f"collectionFormat {fmt} has no OpenAPI 3 style; kept as x-collectionFormat",
                    before=before,
                    after={"x-collectionFormat": fmt},
                    review=True,
                )
                return {"x-collectionFormat": fmt}
            style, explode = _QUERY_STYLES[fmt]
            after = {"style": style, "explode": explode}
        elif location in ("path", "header"):
            if fmt != "csv":
                self.log.record(
                    "collection-format-to-style",
                    pointer,
                    f"collectionFormat {fmt} has no {location} style in OpenAPI 3; kept as x-collectionFormat",
                    before=before,
                    after={"x-collectionFormat": fmt},
                    review=True,
                )
                return {"x-collectionFormat": fmt}
            # ``simple`` / no explode is the 3.0 default for path and header parameters.
            if not declared:
                return None
            after = {"style": "simple", "explode": False}
        else:
            return None
        self.log.record(
            "collection-format-to-style",
            pointer,
            f"collectionFormat {before['collectionFormat']} becomes style {after['style']}, "
            f"explode {str(after['explode']).lower()}",
            before=before,
            after=after,
        )
        return after

    def resolve_parameter(self, param: Any) -> Tuple[Any, Optional[str]]:
        """Resolve a ``#/parameters/X`` reference to a body/formData parameter, else return it as is.

        Returns:
            ``(parameter, shared_name)`` — ``shared_name`` is set when the reference was resolved.
        """
        if isinstance(param, dict) and isinstance(param.get("$ref"), str) and param["$ref"].startswith("#/parameters/"):
            name = param["$ref"][len("#/parameters/") :]
            shared = self.shared_parameters.get(name)
            if isinstance(shared, dict) and shared.get("in") in ("body", "formData"):
                return shared, name
        return param, None

    # -- paths -----------------------------------------------------------------------------

    def paths(self, paths: Any) -> Any:
        """Rewrite the ``paths`` object."""
        if not isinstance(paths, dict):
            return {}
        out: Dict[str, Any] = {}
        for path, item in paths.items():
            pointer = join_pointer("", "paths", path)
            out[path] = self.path_item(item, pointer) if isinstance(item, dict) else item
        return out

    def path_item(self, item: Dict[str, Any], pointer: str) -> Dict[str, Any]:
        """Rewrite one Path Item: shared parameters, then each operation (x- keys kept)."""
        out: Dict[str, Any] = {}
        shared_body: List[Tuple[Dict[str, Any], str]] = []
        for key, value in item.items():
            if key == "parameters" and isinstance(value, list):
                kept = []
                for index, param in enumerate(value):
                    param_pointer = join_pointer(pointer, "parameters", index)
                    resolved, _ = self.resolve_parameter(param)
                    if isinstance(resolved, dict) and resolved.get("in") in ("body", "formData"):
                        shared_body.append((resolved, param_pointer))
                    else:
                        kept.append(self.parameter(param, param_pointer))
                if kept:
                    out["parameters"] = kept
            elif key in _HTTP_METHODS and isinstance(value, dict):
                out[key] = self.operation(value, join_pointer(pointer, key), shared_body)
            else:
                out[key] = value
        return out

    def operation(
        self,
        operation: Dict[str, Any],
        pointer: str,
        shared_body: List[Tuple[Dict[str, Any], str]],
    ) -> Dict[str, Any]:
        """Rewrite one Operation: parameters, request body, responses, schemes; x- keys kept."""
        consumes = _media_list(operation.get("consumes")) or self.consumes
        produces = _media_list(operation.get("produces")) or self.produces
        out: Dict[str, Any] = {}
        params: List[Any] = []
        body: Optional[Tuple[Dict[str, Any], str]] = None
        form: List[Tuple[Dict[str, Any], str]] = []
        for resolved, at in shared_body:
            if resolved.get("in") == "body":
                body = (resolved, at)
            else:
                form.append((resolved, at))
        for index, param in enumerate(operation.get("parameters") or []):
            at = join_pointer(pointer, "parameters", index)
            resolved, shared_name = self.resolve_parameter(param)
            location = resolved.get("in") if isinstance(resolved, dict) else None
            if location == "body":
                body = (resolved, at)
            elif location == "formData":
                form.append((resolved, at))
            else:
                params.append(self.parameter(param, at))
        for key, value in operation.items():
            if key in _OPERATION_KEYS or key.startswith("x-"):
                out[key] = value
            elif key == "parameters" and params:
                out["parameters"] = params
            elif key == "schemes":
                servers = self.servers(value, pointer, rule="operation-schemes-to-servers")
                if servers:
                    out["servers"] = servers
            elif key == "responses" and isinstance(value, dict):
                if body is not None or form:
                    out["requestBody"] = self.request_body(body, form, consumes, pointer)
                out["responses"] = {
                    code: self.response(response, join_pointer(pointer, "responses", code), produces)
                    for code, response in value.items()
                }
        if "requestBody" not in out and (body is not None or form):
            out["requestBody"] = self.request_body(body, form, consumes, pointer)
        if "responses" not in out:
            out["responses"] = {}
        return out

    def request_body(
        self,
        body: Optional[Tuple[Dict[str, Any], str]],
        form: List[Tuple[Dict[str, Any], str]],
        consumes: List[str],
        pointer: str,
    ) -> Dict[str, Any]:
        """Build ``requestBody`` from the ``body`` parameter or the ``formData`` parameters."""
        if body is not None:
            param, at = body
            media = consumes or ["application/json"]
            schema = self.schema(param.get("schema") or {}, join_pointer(at, "schema"))
            out: Dict[str, Any] = {}
            if param.get("description"):
                out["description"] = param["description"]
            out["content"] = {mt: {"schema": copy.deepcopy(schema)} for mt in media}
            if param.get("required"):
                out["required"] = True
            for key, value in param.items():
                if key.startswith("x-"):
                    out[key] = value
            self.log.record(
                "body-to-request-body",
                at,
                f"body parameter {param.get('name', 'body')!s} becomes requestBody ({', '.join(media)})",
                before={"in": "body", "name": param.get("name")},
                after={"content": sorted(media)},
                target_pointer=join_pointer(pointer, "requestBody"),
            )
            return out
        properties: Dict[str, Any] = {}
        required: List[str] = []
        has_file = False
        for param, at in form:
            name = str(param.get("name") or "field")
            schema = self.inline_schema(param, at)
            if param.get("type") == "file":
                has_file = True
            if param.get("description"):
                schema["description"] = param["description"]
            if schema.get("type") == "array" and param.get("collectionFormat", "csv") != "csv":
                self.log.record(
                    "collection-format-to-style",
                    at,
                    f"collectionFormat {param['collectionFormat']} on form field {name} has no direct form; "
                    "kept as x-collectionFormat",
                    before={"collectionFormat": param["collectionFormat"]},
                    after={"x-collectionFormat": param["collectionFormat"]},
                    review=True,
                )
                schema["x-collectionFormat"] = param["collectionFormat"]
            properties[name] = schema
            if param.get("required"):
                required.append(name)
        object_schema: Dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            object_schema["required"] = required
        declared = [mt for mt in consumes if mt in _FORM_MEDIA_TYPES]
        media = declared or (["multipart/form-data"] if has_file else ["application/x-www-form-urlencoded"])
        self.log.record(
            "form-data-to-request-body",
            pointer,
            f"{len(form)} formData parameter(s) become a {', '.join(media)} requestBody",
            before={"formData": [str(p.get("name")) for p, _ in form]},
            after={"content": media},
            target_pointer=join_pointer(pointer, "requestBody"),
        )
        return {"content": {mt: {"schema": copy.deepcopy(object_schema)} for mt in media}}

    # -- responses -------------------------------------------------------------------------

    def response(self, response: Any, pointer: str, produces: List[str]) -> Any:
        """Rewrite one Response Object: schema / examples → content, headers → schemas."""
        if not isinstance(response, dict):
            return response
        if "$ref" in response:
            return {**response, "$ref": self.ref(response["$ref"], pointer)}
        out: Dict[str, Any] = {"description": response.get("description", "")}
        media = produces or ["application/json"]
        examples = response.get("examples") if isinstance(response.get("examples"), dict) else {}
        content: Dict[str, Any] = {}
        if isinstance(response.get("schema"), dict):
            schema = self.schema(response["schema"], join_pointer(pointer, "schema"))
            content = {mt: {"schema": copy.deepcopy(schema)} for mt in media}
            self.log.record(
                "response-schema-to-content",
                pointer,
                f"Response schema moves under content ({', '.join(media)})",
                after={"content": list(media)},
            )
        if examples:
            for mt, value in examples.items():
                content.setdefault(mt, {})["example"] = value
            self.log.record(
                "response-examples-to-content",
                pointer,
                "Response examples become content." + ", content.".join(f"{mt}.example" for mt in examples),
                before={"examples": sorted(examples)},
            )
        for key, value in response.items():
            if key == "headers" and isinstance(value, dict):
                out["headers"] = {
                    name: self.header(header, join_pointer(pointer, "headers", name)) for name, header in value.items()
                }
            elif key.startswith("x-"):
                out[key] = value
        if content:
            out["content"] = content
        return out

    def header(self, header: Any, pointer: str) -> Any:
        """Rewrite one Header Object (inline type → schema)."""
        if not isinstance(header, dict):
            return header
        out: Dict[str, Any] = {}
        if "description" in header:
            out["description"] = header["description"]
        schema = self.inline_schema(header, pointer)
        if schema:
            out["schema"] = schema
        for key, value in header.items():
            if key.startswith("x-") and key != "x-nullable":
                out[key] = value
        return out


def _media_list(value: Any) -> List[str]:
    """A Swagger ``consumes`` / ``produces`` value as a list of media types (empty when unset)."""
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _items_without_collection(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Drop ``collectionFormat`` from nested Swagger Items Objects (3.0 schemas have no such key)."""
    out = dict(schema)
    items = out.get("items")
    if isinstance(items, dict):
        out["items"] = _items_without_collection({k: v for k, v in items.items() if k != "collectionFormat"})
    return out
