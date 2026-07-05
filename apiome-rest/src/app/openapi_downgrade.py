"""Downgrade an emitted OpenAPI 3.1 document to 3.0 / Swagger 2.0 — MFX-9.1 (#3866).

The reference emitter (:class:`app.openapi_emitter.OpenApiEmitter`) produces an
**OpenAPI 3.1** document. Some consumers still require the older dialects, so this
module offers the two *downgrade* projections the MFX-9.1 acceptance criterion asks
for:

* **OpenAPI 3.0.3** — the same document shape, with the handful of JSON-Schema
  2020-12 constructs 3.0 cannot express rewritten into their 3.0 spellings
  (``type: ["T", "null"]`` → ``nullable: true``; numeric
  ``exclusiveMinimum``/``exclusiveMaximum`` → the draft-4 boolean form; ``const`` →
  a one-value ``enum``) or dropped;
* **Swagger 2.0** — a structural rewrite (``servers`` → ``host``/``basePath``/
  ``schemes``; ``components.schemas`` → ``definitions`` with rewritten ``$ref``\\s;
  ``requestBody`` → a ``body`` parameter + ``consumes``; response ``content`` →
  ``schema`` + ``produces``; parameter/header ``schema`` inlined) into the older,
  less expressive object model.

**Every downgrade is lossy, and the loss is recorded, never silent.** Each
projection walks the document with a :class:`~app.emitter.LossTracker` and records a
:class:`~app.emitter.Loss` for each construct the older dialect cannot carry
faithfully — an :attr:`~app.emitter.LossKind.INFERRED` loss when the construct is
approximated (a numeric ``exclusiveMinimum`` re-expressed as a boolean pair, a
``const`` folded to an ``enum``, one of several content types kept) and an
:attr:`~app.emitter.LossKind.NA` loss when it has no representation at all (a 3.1
``oneOf`` in Swagger 2.0, a ``null`` type, an unsupported JSON-Schema keyword). Those
losses ride back on the :class:`~app.emitter.EmitResult` so the fidelity engine
(MFX-EPIC-2) surfaces what the downgrade cost — the "3.0/2.0 downgrades flagged as
lossy" criterion.

The functions are **pure and deterministic**: they never mutate the input document,
perform no I/O, and emit collections in the input's (already deterministic) order, so
re-downgrading the same document yields a byte-identical result and loss list.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .emitter import LossKind, LossTracker

__all__ = [
    "OPENAPI_30_VERSION",
    "SWAGGER_20_VERSION",
    "downgrade_to_openapi_30",
    "downgrade_to_swagger_2",
]

#: The OpenAPI 3.0 patch version emitted by :func:`downgrade_to_openapi_30`.
OPENAPI_30_VERSION = "3.0.3"
#: The Swagger version string emitted by :func:`downgrade_to_swagger_2`.
SWAGGER_20_VERSION = "2.0"

# The 3.1 (JSON-Schema 2020-12) reference prefix the emitter uses, and its Swagger
# 2.0 equivalent — Swagger keeps its named schemas under ``#/definitions`` instead.
_COMPONENTS_SCHEMAS_PREFIX = "#/components/schemas/"
_DEFINITIONS_PREFIX = "#/definitions/"

# The eight native OpenAPI path-item HTTP methods (shared by 3.x and 2.0 except
# ``trace``, which Swagger 2.0 lacks — handled explicitly below).
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# JSON-Schema 2020-12 keywords with no OpenAPI 3.0 representation: dropped with an
# ``NA`` loss when encountered. (3.0 retains ``oneOf``/``anyOf``/``allOf``/``not``.)
_UNSUPPORTED_30_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$anchor",
        "$defs",
        "$dynamicRef",
        "$dynamicAnchor",
        "contentMediaType",
        "contentEncoding",
        "contentSchema",
        "prefixItems",
        "unevaluatedItems",
        "unevaluatedProperties",
        "patternProperties",
        "propertyNames",
        "contains",
        "minContains",
        "maxContains",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "dependentRequired",
    }
)

# Swagger 2.0 additionally cannot express these draft-4-plus keywords (on top of the
# 3.0 set): the polymorphism combinators other than ``allOf``, and ``const``.
_UNSUPPORTED_SWAGGER2_KEYWORDS = _UNSUPPORTED_30_KEYWORDS | frozenset(
    {"oneOf", "anyOf", "not"}
)

# Sub-schema *maps* (name → schema) and *lists* (array of schemas) a schema object
# nests, walked recursively during a downgrade.
_SUBSCHEMA_MAP_KEYS = ("properties",)
_SUBSCHEMA_LIST_KEYS = ("allOf", "oneOf", "anyOf")


# ===========================================================================
# OpenAPI 3.1 → 3.0.3
# ===========================================================================


def downgrade_to_openapi_30(document: Dict[str, Any], losses: LossTracker) -> Dict[str, Any]:
    """Return an OpenAPI 3.0.3 copy of a 3.1 ``document``, recording losses.

    The document shape is unchanged; only the schema objects are rewritten from
    JSON-Schema 2020-12 into the 3.0 dialect (see the module docstring). The input is
    not mutated.

    Args:
        document: A schema-valid OpenAPI 3.1 document (the emitter's output).
        losses: Tracker the downgrade records each 3.1-only construct's loss on.

    Returns:
        A new dict whose ``openapi`` is :data:`OPENAPI_30_VERSION` and whose schemas
        are 3.0-dialect.
    """
    result = copy.deepcopy(document)
    result["openapi"] = OPENAPI_30_VERSION

    _downgrade_info_30(result, losses)

    schemas = result.get("components", {}).get("schemas")
    if isinstance(schemas, dict):
        for name, schema in list(schemas.items()):
            schemas[name] = _schema_to_30(schema, losses, f"#/components/schemas/{name}")

    paths = result.get("paths")
    if isinstance(paths, dict):
        for path, item in paths.items():
            _downgrade_path_item_schemas_30(item, losses, f"#/paths/{path}")

    return result


def _downgrade_info_30(document: Dict[str, Any], losses: LossTracker) -> None:
    """Drop 3.1-only ``info`` members (``summary``, ``license.identifier``)."""
    info = document.get("info")
    if not isinstance(info, dict):
        return
    if "summary" in info:
        del info["summary"]
        losses.record(
            LossKind.NA,
            "openapi-30-info-summary",
            "OpenAPI 3.0 has no info.summary field; the value was dropped",
            pointer="#/info/summary",
        )
    license_ = info.get("license")
    if isinstance(license_, dict) and "identifier" in license_:
        del license_["identifier"]
        losses.record(
            LossKind.NA,
            "openapi-30-license-identifier",
            "OpenAPI 3.0 has no license.identifier (SPDX) field; it was dropped",
            pointer="#/info/license/identifier",
        )


def _downgrade_path_item_schemas_30(
    item: Any, losses: LossTracker, pointer: str
) -> None:
    """Rewrite every schema reachable from a path item into the 3.0 dialect."""
    if not isinstance(item, dict):
        return
    _downgrade_parameters_schemas_30(item.get("parameters"), losses, pointer)
    for method in _HTTP_METHODS:
        operation = item.get(method)
        if isinstance(operation, dict):
            _downgrade_operation_schemas_30(operation, losses, f"{pointer}/{method}")


def _downgrade_operation_schemas_30(
    operation: Dict[str, Any], losses: LossTracker, pointer: str
) -> None:
    """Rewrite an operation's parameter/body/response schemas into the 3.0 dialect."""
    _downgrade_parameters_schemas_30(operation.get("parameters"), losses, pointer)

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        _downgrade_content_schemas_30(
            request_body.get("content"), losses, f"{pointer}/requestBody/content"
        )

    responses = operation.get("responses")
    if isinstance(responses, dict):
        for status, response in responses.items():
            if not isinstance(response, dict):
                continue
            base = f"{pointer}/responses/{status}"
            _downgrade_content_schemas_30(response.get("content"), losses, f"{base}/content")
            headers = response.get("headers")
            if isinstance(headers, dict):
                for name, header in headers.items():
                    if isinstance(header, dict) and isinstance(header.get("schema"), dict):
                        header["schema"] = _schema_to_30(
                            header["schema"], losses, f"{base}/headers/{name}/schema"
                        )


def _downgrade_parameters_schemas_30(
    parameters: Any, losses: LossTracker, pointer: str
) -> None:
    """Rewrite each parameter's ``schema`` into the 3.0 dialect (in place)."""
    if not isinstance(parameters, list):
        return
    for index, parameter in enumerate(parameters):
        if isinstance(parameter, dict) and isinstance(parameter.get("schema"), dict):
            parameter["schema"] = _schema_to_30(
                parameter["schema"], losses, f"{pointer}/parameters/{index}/schema"
            )


def _downgrade_content_schemas_30(
    content: Any, losses: LossTracker, pointer: str
) -> None:
    """Rewrite each media-type object's ``schema`` into the 3.0 dialect (in place)."""
    if not isinstance(content, dict):
        return
    for media_type, media_obj in content.items():
        if isinstance(media_obj, dict) and isinstance(media_obj.get("schema"), dict):
            media_obj["schema"] = _schema_to_30(
                media_obj["schema"], losses, f"{pointer}/{media_type}/schema"
            )


def _schema_to_30(schema: Any, losses: LossTracker, pointer: str) -> Any:
    """Return a 3.0-dialect copy of a JSON-Schema-2020-12 ``schema``.

    Rewrites nullability (``type`` arrays / bare ``"null"``), numeric exclusive
    bounds, ``const``, and ``examples``; drops JSON-Schema keywords 3.0 lacks. Each
    change is recorded on ``losses``. Recurses into nested subschemas.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        # A reference leaf carries no sibling keywords (per the emitter), so there is
        # nothing 3.1-specific to rewrite.
        return {"$ref": schema["$ref"]}

    result = dict(schema)
    _apply_nullability_30(result, losses, pointer)
    _apply_exclusive_bounds_30(result, losses, pointer)
    _apply_const_and_examples(result, losses, pointer)
    _drop_unsupported_keywords(result, _UNSUPPORTED_30_KEYWORDS, losses, pointer)
    _recurse_subschemas(result, losses, pointer, _schema_to_30)
    return result


def _apply_nullability_30(
    schema: Dict[str, Any], losses: LossTracker, pointer: str
) -> None:
    """Rewrite a 2020-12 ``type`` array / bare ``"null"`` into 3.0 ``nullable``."""
    type_ = schema.get("type")
    if isinstance(type_, list):
        non_null = [entry for entry in type_ if entry != "null"]
        had_null = len(non_null) != len(type_)
        if had_null:
            schema["nullable"] = True
        if len(non_null) == 1:
            schema["type"] = non_null[0]
        elif not non_null:
            # ``type: ["null"]`` — no concrete type is left for 3.0 to carry.
            del schema["type"]
            losses.record(
                LossKind.NA,
                "openapi-30-null-type",
                "OpenAPI 3.0 has no standalone null type; kept only as nullable",
                pointer=pointer,
            )
        else:
            # A genuine multi-type union (e.g. ``["string", "integer"]``): 3.0 admits
            # a single type only, so keep the first and flag the rest as lost.
            schema["type"] = non_null[0]
            losses.record(
                LossKind.INFERRED,
                "openapi-30-multitype",
                "OpenAPI 3.0 admits a single type; kept "
                f"{non_null[0]!r}, dropped {non_null[1:]!r}",
                pointer=pointer,
            )
    elif type_ == "null":
        del schema["type"]
        schema["nullable"] = True
        losses.record(
            LossKind.NA,
            "openapi-30-null-type",
            "OpenAPI 3.0 has no standalone null type; kept only as nullable",
            pointer=pointer,
        )


def _apply_exclusive_bounds_30(
    schema: Dict[str, Any], losses: LossTracker, pointer: str
) -> None:
    """Rewrite numeric ``exclusiveMinimum``/``exclusiveMaximum`` to the draft-4 form.

    JSON Schema 2020-12 makes the exclusive bounds numbers; OpenAPI 3.0 keeps the
    draft-4 boolean flag paired with ``minimum``/``maximum``. The re-expression is
    faithful, so it is recorded as an :attr:`~app.emitter.LossKind.INFERRED`
    approximation, not a drop.
    """
    for exclusive_key, bound_key in (
        ("exclusiveMinimum", "minimum"),
        ("exclusiveMaximum", "maximum"),
    ):
        value = schema.get(exclusive_key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        schema[bound_key] = value
        schema[exclusive_key] = True
        losses.record(
            LossKind.INFERRED,
            "openapi-30-exclusive-bound",
            f"numeric {exclusive_key} re-expressed as the 3.0 boolean form",
            pointer=pointer,
        )


def _apply_const_and_examples(
    schema: Dict[str, Any], losses: LossTracker, pointer: str
) -> None:
    """Fold ``const`` to a single-value ``enum`` and ``examples`` to ``example``.

    Both are 3.0 approximations (:attr:`~app.emitter.LossKind.INFERRED`): the value is
    preserved but in the older keyword. Shared by the 3.0 and Swagger 2.0 walks.
    """
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
        losses.record(
            LossKind.INFERRED,
            "openapi-30-const",
            "const has no pre-3.1 keyword; folded to a single-value enum",
            pointer=pointer,
        )
    examples = schema.get("examples")
    if isinstance(examples, list):
        del schema["examples"]
        if examples and "example" not in schema:
            schema["example"] = examples[0]
        losses.record(
            LossKind.INFERRED,
            "openapi-30-examples",
            "schema-level examples array has no pre-3.1 keyword; kept the first "
            "as example",
            pointer=pointer,
        )


# ===========================================================================
# OpenAPI 3.1 → Swagger 2.0
# ===========================================================================


def downgrade_to_swagger_2(document: Dict[str, Any], losses: LossTracker) -> Dict[str, Any]:
    """Return a Swagger 2.0 rewrite of a 3.1 ``document``, recording losses.

    Restructures the document into the Swagger 2.0 object model (see the module
    docstring) and downgrades every schema into the draft-4 subset Swagger permits.
    The input is not mutated.

    Args:
        document: A schema-valid OpenAPI 3.1 document (the emitter's output).
        losses: Tracker the downgrade records each unrepresentable construct on.

    Returns:
        A new dict whose ``swagger`` is :data:`SWAGGER_20_VERSION`.
    """
    result: Dict[str, Any] = {"swagger": SWAGGER_20_VERSION}

    info = document.get("info")
    if isinstance(info, dict):
        result["info"] = _swagger2_info(info, losses)

    result.update(_swagger2_host(document.get("servers"), losses))

    definitions = _swagger2_definitions(document.get("components"), losses)
    if definitions:
        result["definitions"] = definitions

    result["paths"] = _swagger2_paths(document.get("paths"), losses)
    return result


def _swagger2_info(info: Dict[str, Any], losses: LossTracker) -> Dict[str, Any]:
    """Copy ``info``, dropping the 3.1-only ``summary`` / ``license.identifier``."""
    result = copy.deepcopy(info)
    if "summary" in result:
        del result["summary"]
        losses.record(
            LossKind.NA,
            "swagger2-info-summary",
            "Swagger 2.0 has no info.summary field; the value was dropped",
            pointer="#/info/summary",
        )
    license_ = result.get("license")
    if isinstance(license_, dict) and "identifier" in license_:
        del license_["identifier"]
        losses.record(
            LossKind.NA,
            "swagger2-license-identifier",
            "Swagger 2.0 has no license.identifier (SPDX) field; it was dropped",
            pointer="#/info/license/identifier",
        )
    return result


def _swagger2_host(servers: Any, losses: LossTracker) -> Dict[str, Any]:
    """Project ``servers`` onto Swagger 2.0 ``host``/``basePath``/``schemes``.

    Swagger 2.0 describes a single host, so only the first server's URL is used; any
    further servers, and any server-variable templating, are recorded as losses (the
    variable defaults are substituted so the resulting ``basePath`` is concrete).
    """
    if not isinstance(servers, list) or not servers:
        return {}
    first = servers[0]
    if not isinstance(first, dict) or not isinstance(first.get("url"), str):
        return {}

    url = _resolve_server_url(first, losses)
    parts = urlsplit(url)
    result: Dict[str, Any] = {}
    if parts.scheme:
        result["schemes"] = [parts.scheme]
    if parts.netloc:
        result["host"] = parts.netloc
    base_path = parts.path or "/"
    if not base_path.startswith("/"):
        base_path = "/" + base_path
    result["basePath"] = base_path

    if len(servers) > 1:
        losses.record(
            LossKind.INFERRED,
            "swagger2-multiple-servers",
            f"Swagger 2.0 describes a single host; kept the first of {len(servers)} "
            "servers",
            pointer="#/servers",
        )
    return result


def _resolve_server_url(server: Dict[str, Any], losses: LossTracker) -> str:
    """Substitute a server's variable defaults into its URL (Swagger has no templating)."""
    url = server["url"]
    variables = server.get("variables")
    if not isinstance(variables, dict):
        return url
    for name, spec in variables.items():
        default = spec.get("default") if isinstance(spec, dict) else None
        if isinstance(default, str):
            url = url.replace("{" + name + "}", default)
    losses.record(
        LossKind.INFERRED,
        "swagger2-server-variables",
        "Swagger 2.0 has no server-variable templating; substituted variable defaults",
        pointer="#/servers/0/variables",
    )
    return url


def _swagger2_definitions(components: Any, losses: LossTracker) -> Dict[str, Any]:
    """Rewrite ``components.schemas`` into Swagger 2.0 ``definitions``."""
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return {}
    definitions: Dict[str, Any] = {}
    for name, schema in schemas.items():
        definitions[name] = _schema_to_swagger2(
            schema, losses, f"#/components/schemas/{name}"
        )
    return definitions


def _swagger2_paths(paths: Any, losses: LossTracker) -> Dict[str, Any]:
    """Rewrite the ``paths`` object into Swagger 2.0 operations."""
    result: Dict[str, Any] = {}
    if not isinstance(paths, dict):
        return result
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        result[path] = _swagger2_path_item(item, losses, f"#/paths/{path}")
    return result


def _swagger2_path_item(
    item: Dict[str, Any], losses: LossTracker, pointer: str
) -> Dict[str, Any]:
    """Rewrite one path item, converting each operation to Swagger 2.0 shape."""
    result: Dict[str, Any] = {}
    shared = item.get("parameters")
    if isinstance(shared, list):
        converted = [
            _swagger2_parameter(param, losses, f"{pointer}/parameters/{index}")
            for index, param in enumerate(shared)
        ]
        # Drop parameters with no Swagger 2.0 representation (cookie → ``None``).
        converted = [param for param in converted if param is not None]
        if converted:
            result["parameters"] = converted
    for method in _HTTP_METHODS:
        operation = item.get(method)
        if not isinstance(operation, dict):
            continue
        if method == "trace":
            losses.record(
                LossKind.NA,
                "swagger2-trace-method",
                "Swagger 2.0 has no TRACE operation; the operation was dropped",
                pointer=f"{pointer}/trace",
            )
            continue
        result[method] = _swagger2_operation(operation, losses, f"{pointer}/{method}")
    return result


def _swagger2_operation(
    operation: Dict[str, Any], losses: LossTracker, pointer: str
) -> Dict[str, Any]:
    """Rewrite one Operation Object into Swagger 2.0 shape.

    ``requestBody`` becomes a ``body`` parameter plus ``consumes``; each response's
    ``content`` becomes a ``schema`` plus operation-level ``produces``; parameters and
    headers have their ``schema`` inlined.
    """
    result: Dict[str, Any] = {}
    for key in ("operationId", "summary", "description", "tags", "deprecated"):
        if key in operation:
            result[key] = copy.deepcopy(operation[key])

    parameters: List[Dict[str, Any]] = []
    own = operation.get("parameters")
    if isinstance(own, list):
        for index, param in enumerate(own):
            parameters.append(
                _swagger2_parameter(param, losses, f"{pointer}/parameters/{index}")
            )

    consumes = _swagger2_request_body(
        operation.get("requestBody"), parameters, losses, f"{pointer}/requestBody"
    )
    if consumes:
        result["consumes"] = consumes

    # Drop parameters that had no Swagger 2.0 representation (returned ``None``).
    parameters = [param for param in parameters if param is not None]
    if parameters:
        result["parameters"] = parameters

    produces, responses = _swagger2_responses(
        operation.get("responses"), losses, f"{pointer}/responses"
    )
    if produces:
        result["produces"] = produces
    result["responses"] = responses
    return result


def _swagger2_request_body(
    request_body: Any,
    parameters: List[Dict[str, Any]],
    losses: LossTracker,
    pointer: str,
) -> List[str]:
    """Append a ``body`` parameter for ``requestBody`` and return its ``consumes``.

    Swagger 2.0 models a request body as an ``in: body`` parameter and carries the
    media types on operation-level ``consumes``. A body with several media types keeps
    one schema for all of them, so extra media types are recorded as an approximation.
    """
    if not isinstance(request_body, dict):
        return []
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return []

    media_types = sorted(content)
    chosen = media_types[0]
    media_obj = content[chosen]
    schema = media_obj.get("schema") if isinstance(media_obj, dict) else None

    body_param: Dict[str, Any] = {"name": "body", "in": "body", "required": True}
    if isinstance(request_body.get("description"), str):
        body_param["description"] = request_body["description"]
    if isinstance(schema, dict):
        body_param["schema"] = _schema_to_swagger2(schema, losses, f"{pointer}/schema")
    parameters.append(body_param)

    if len(media_types) > 1:
        losses.record(
            LossKind.INFERRED,
            "swagger2-request-media-types",
            "Swagger 2.0 body parameters share one schema across media types; kept "
            f"{chosen!r}'s schema for all {len(media_types)} consumed types",
            pointer=pointer,
        )
    return media_types


def _swagger2_responses(
    responses: Any, losses: LossTracker, pointer: str
) -> tuple[List[str], Dict[str, Any]]:
    """Rewrite the ``responses`` object; return operation ``produces`` + responses.

    Each response's ``content`` (a media-type → schema map in 3.x) collapses to a
    single Swagger ``schema``, and the union of every response's media types becomes
    the operation-level ``produces``.
    """
    result: Dict[str, Any] = {}
    produces: List[str] = []
    if not isinstance(responses, dict):
        return produces, result

    produced: set = set()
    for status, response in responses.items():
        if not isinstance(response, dict):
            continue
        entry: Dict[str, Any] = {}
        # Swagger 2.0 requires a description on every response.
        entry["description"] = response.get("description") or ""
        content = response.get("content")
        if isinstance(content, dict) and content:
            media_types = sorted(content)
            produced.update(media_types)
            media_obj = content[media_types[0]]
            schema = media_obj.get("schema") if isinstance(media_obj, dict) else None
            if isinstance(schema, dict):
                entry["schema"] = _schema_to_swagger2(
                    schema, losses, f"{pointer}/{status}/content/{media_types[0]}/schema"
                )
            if len(media_types) > 1:
                losses.record(
                    LossKind.INFERRED,
                    "swagger2-response-media-types",
                    "Swagger 2.0 responses carry one schema regardless of media type; "
                    f"kept {media_types[0]!r}'s schema for response {status}",
                    pointer=f"{pointer}/{status}",
                )
        headers = _swagger2_headers(
            response.get("headers"), losses, f"{pointer}/{status}/headers"
        )
        if headers:
            entry["headers"] = headers
        result[status] = entry

    produces = sorted(produced)
    return produces, result


def _swagger2_headers(
    headers: Any, losses: LossTracker, pointer: str
) -> Dict[str, Any]:
    """Rewrite a response ``headers`` map into Swagger 2.0 (schema inlined)."""
    if not isinstance(headers, dict):
        return {}
    result: Dict[str, Any] = {}
    for name, header in headers.items():
        if not isinstance(header, dict):
            continue
        entry: Dict[str, Any] = {}
        if isinstance(header.get("description"), str):
            entry["description"] = header["description"]
        schema = header.get("schema")
        if isinstance(schema, dict):
            entry.update(
                _swagger2_inline_type(schema, losses, f"{pointer}/{name}/schema")
            )
        else:
            entry["type"] = "string"
        result[name] = entry
    return result


def _swagger2_parameter(
    parameter: Any, losses: LossTracker, pointer: str
) -> Optional[Dict[str, Any]]:
    """Rewrite one Parameter Object into Swagger 2.0 shape.

    Non-body parameters carry their type inline (no ``schema`` wrapper). ``cookie``
    parameters have no Swagger 2.0 representation and are dropped (``None``) with a
    loss.
    """
    if not isinstance(parameter, dict):
        return None
    location = parameter.get("in")
    if location == "cookie":
        losses.record(
            LossKind.NA,
            "swagger2-cookie-parameter",
            "Swagger 2.0 has no cookie parameters; "
            f"parameter {parameter.get('name')!r} was dropped",
            pointer=pointer,
        )
        return None

    result: Dict[str, Any] = {
        "name": parameter.get("name"),
        "in": location,
    }
    if parameter.get("required") or location == "path":
        result["required"] = True
    if isinstance(parameter.get("description"), str):
        result["description"] = parameter["description"]

    schema = parameter.get("schema")
    if isinstance(schema, dict):
        result.update(_swagger2_inline_type(schema, losses, f"{pointer}/schema"))
    else:
        result["type"] = "string"
    return result


def _swagger2_inline_type(
    schema: Dict[str, Any], losses: LossTracker, pointer: str
) -> Dict[str, Any]:
    """Flatten a primitive parameter/header ``schema`` into inline Swagger 2.0 keys.

    Swagger 2.0 non-body parameters put ``type``/``format``/``items``/constraints
    directly on the parameter rather than under a ``schema``. A ``$ref`` or object
    type has no such inline form, so it is approximated as a ``string`` with a loss.
    """
    if "$ref" in schema or schema.get("type") in ("object", None):
        losses.record(
            LossKind.INFERRED,
            "swagger2-non-primitive-parameter",
            "Swagger 2.0 non-body parameters must be primitive; approximated a "
            "$ref/object parameter as a string",
            pointer=pointer,
        )
        return {"type": "string"}

    downgraded = _schema_to_swagger2(schema, losses, pointer)
    inline: Dict[str, Any] = {}
    # Only the draft-4 primitive facets are valid inline on a 2.0 parameter.
    for key in (
        "type",
        "format",
        "enum",
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
    ):
        if key in downgraded:
            inline[key] = downgraded[key]
    if downgraded.get("type") == "array" and isinstance(downgraded.get("items"), dict):
        inline["items"] = downgraded["items"]
    return inline


def _schema_to_swagger2(schema: Any, losses: LossTracker, pointer: str) -> Any:
    """Return a Swagger-2.0-dialect (draft-4 subset) copy of a 2020-12 ``schema``.

    Applies the 3.0 nullability/const/examples rewrites, then additionally drops the
    keywords Swagger 2.0 lacks (``oneOf``/``anyOf``/``not`` and the 3.0-unsupported
    set), turns 3.1 ``nullable`` array types into a plain type (2.0 has no nullable),
    and rewrites ``$ref``\\s from ``#/components/schemas`` to ``#/definitions``.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return {"$ref": _rewrite_ref_to_definitions(schema["$ref"])}

    result = dict(schema)
    _apply_nullability_swagger2(result, losses, pointer)
    _apply_exclusive_bounds_30(result, losses, pointer)
    _apply_const_and_examples(result, losses, pointer)
    _drop_unsupported_keywords(result, _UNSUPPORTED_SWAGGER2_KEYWORDS, losses, pointer)
    _recurse_subschemas(result, losses, pointer, _schema_to_swagger2)
    return result


def _apply_nullability_swagger2(
    schema: Dict[str, Any], losses: LossTracker, pointer: str
) -> None:
    """Collapse a 2020-12 ``type`` array to a single type — Swagger 2.0 has no nullable."""
    type_ = schema.get("type")
    if type_ == "null":
        del schema["type"]
        losses.record(
            LossKind.NA,
            "swagger2-null-type",
            "Swagger 2.0 has no null type and no nullable flag; the null type was dropped",
            pointer=pointer,
        )
        return
    if not isinstance(type_, list):
        return
    non_null = [entry for entry in type_ if entry != "null"]
    had_null = len(non_null) != len(type_)
    if non_null:
        schema["type"] = non_null[0]
    else:
        del schema["type"]
    if had_null:
        losses.record(
            LossKind.NA,
            "swagger2-nullable",
            "Swagger 2.0 cannot express nullability; the null type was dropped",
            pointer=pointer,
        )
    if len(non_null) > 1:
        losses.record(
            LossKind.INFERRED,
            "swagger2-multitype",
            "Swagger 2.0 admits a single type; kept "
            f"{non_null[0]!r}, dropped {non_null[1:]!r}",
            pointer=pointer,
        )


def _rewrite_ref_to_definitions(ref: Any) -> Any:
    """Rewrite a ``#/components/schemas/X`` ``$ref`` to Swagger's ``#/definitions/X``."""
    if isinstance(ref, str) and ref.startswith(_COMPONENTS_SCHEMAS_PREFIX):
        return _DEFINITIONS_PREFIX + ref[len(_COMPONENTS_SCHEMAS_PREFIX):]
    return ref


# ===========================================================================
# Shared schema-walk helpers
# ===========================================================================


def _drop_unsupported_keywords(
    schema: Dict[str, Any],
    unsupported: frozenset,
    losses: LossTracker,
    pointer: str,
) -> None:
    """Remove every ``unsupported`` keyword present on ``schema``, recording each drop."""
    for keyword in sorted(unsupported):
        if keyword in schema:
            del schema[keyword]
            losses.record(
                LossKind.NA,
                "downgrade-unsupported-keyword",
                f"the JSON-Schema keyword {keyword!r} has no representation in the "
                "target dialect; it was dropped",
                pointer=f"{pointer}/{keyword}",
            )


def _recurse_subschemas(
    schema: Dict[str, Any],
    losses: LossTracker,
    pointer: str,
    transform: Any,
) -> None:
    """Apply ``transform`` to every nested subschema of ``schema`` (in place).

    Walks the object/array subschema locations (``properties``, ``items``,
    ``additionalProperties``, ``allOf``/``oneOf``/``anyOf``, ``not``) that survive
    into the target dialect; unsupported combinators are already removed before this
    runs, so iterating the remaining keys is safe.
    """
    for key in _SUBSCHEMA_MAP_KEYS:
        nested = schema.get(key)
        if isinstance(nested, dict):
            schema[key] = {
                name: transform(value, losses, f"{pointer}/{key}/{name}")
                for name, value in nested.items()
            }

    for key in _SUBSCHEMA_LIST_KEYS:
        nested = schema.get(key)
        if isinstance(nested, list):
            schema[key] = [
                transform(value, losses, f"{pointer}/{key}/{index}")
                for index, value in enumerate(nested)
            ]

    items = schema.get("items")
    if isinstance(items, dict):
        schema["items"] = transform(items, losses, f"{pointer}/items")

    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        schema["additionalProperties"] = transform(
            additional, losses, f"{pointer}/additionalProperties"
        )

    not_schema = schema.get("not")
    if isinstance(not_schema, dict):
        schema["not"] = transform(not_schema, losses, f"{pointer}/not")
