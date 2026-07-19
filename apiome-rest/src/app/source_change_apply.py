"""Candidate-to-canonical write planning for source apply — DCW-2.3 (#2360).

The apply transaction rewrites a draft revision's canonical rows from a
reviewed candidate document. This module is the **pure planning half**: it
turns a parsed candidate into deterministic write rows for the relational
model (classes/properties, paths/operations/parameters/request bodies/
responses, security schemes, servers), then predicts — without touching the
database — exactly what the server generator will read back from those rows.

That prediction powers the DCW-2.1 fidelity loop:

* anything the relational model does not absorb is re-extracted into the
  preservation envelope against the predicted canonical, so it round-trips
  losslessly instead of disappearing;
* :func:`compare_candidate_to_merged` then proves the merged result
  (predicted canonical + envelope) equals the candidate, tolerating only
  **deterministic generator enrichments** (injected titles, default
  responses, parameter-schema defaults, …) which are reported, never silent.
  Any lost value or altered value fails the apply — the transaction rolls
  back rather than mutate the revision into something the author did not
  write.

Everything here is pure and side-effect free: no DB, no network, inputs are
never mutated. The transaction itself lives in ``database.py``
(``apply_source_change_set``) and the HTTP surface in
``source_review_routes.py``.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .openapi_generator import generate_openapi_spec
from .source_change_review import diff_documents

__all__ = [
    "CanonicalWrites",
    "ClassPropertyWrite",
    "ClassWrite",
    "ContentWrite",
    "FidelityReport",
    "OperationWrite",
    "ParameterWrite",
    "PathWrite",
    "RequestBodyWrite",
    "ResponseWrite",
    "SecuritySchemeWrite",
    "ServerWrite",
    "build_canonical_writes",
    "compare_candidate_to_merged",
    "parameter_key",
    "path_shared_parameters",
    "regenerate_document",
]

#: Methods whose request bodies the generator emits (``paths_generator``
#: only regenerates request bodies for POST/PUT/PATCH; other methods'
#: request bodies round-trip through the preservation envelope instead).
_REQUEST_BODY_METHODS = {"post", "put", "patch"}

_OPERATION_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
    "query",
}

#: Operation keys absorbed into relational columns; everything else on an
#: operation (callbacks, servers, vendor keys, …) is envelope-preserved.
_OPERATION_COLUMN_KEYS = {
    "summary",
    "description",
    "operationId",
    "tags",
    "deprecated",
    "externalDocs",
    "security",
    "parameters",
    "requestBody",
    "responses",
}

#: Parameter keys the generator folds back out of the stored ``data`` blob.
_PARAMETER_DATA_KEYS = (
    "required",
    "deprecated",
    "allowEmptyValue",
    "style",
    "explode",
    "example",
    "examples",
)

#: SQL read-back ordering for parameters: path, query, header, then cookie.
_PARAM_LOCATION_ORDER = {"path": 1, "query": 2, "header": 3}

#: SQL read-back ordering for operations.
_OPERATION_ORDER = {"GET": 1, "POST": 2, "PUT": 3, "PATCH": 4, "DELETE": 5}


class ClassPropertyWrite(BaseModel):
    """One top-level class property row (nested shapes stay inside ``data``)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    is_reference: bool = Field(
        default=False,
        alias="isReference",
        description="True when data carries a $ref (directly or via array "
        "items); reference rows keep a NULL project-property link.",
    )


class ClassWrite(BaseModel):
    """One ``classes`` row rebuilt from ``components.schemas``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: Optional[str] = None
    schema_fields: Dict[str, Any] = Field(
        default_factory=dict,
        alias="schemaFields",
        description="The stored schema column: the source schema minus its "
        "properties/required (those live in property rows).",
    )
    properties: List[ClassPropertyWrite] = Field(default_factory=list)


class ParameterWrite(BaseModel):
    """One ``shared_path_parameter`` row."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    in_location: str = Field(alias="inLocation")
    summary: Optional[str] = None
    description: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ContentWrite(BaseModel):
    """One media-type content row for a request body or response."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    media_type: str = Field(alias="mediaType")
    ref_class_name: Optional[str] = Field(
        default=None,
        alias="refClassName",
        description="Schema $ref target class name, when the schema is a "
        "component reference.",
    )
    inline_schema: Optional[Dict[str, Any]] = Field(default=None, alias="inlineSchema")
    encoding: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Stored example list: [{name?, summary?, value}].",
    )


class RequestBodyWrite(BaseModel):
    """One ``shared_path_request_body`` row plus its content rows."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: Optional[str] = None
    required: bool = False
    contents: List[ContentWrite] = Field(default_factory=list)


class ResponseWrite(BaseModel):
    """One ``shared_path_response`` row (shared per path + status code)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status_code: str = Field(alias="statusCode")
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="headers/links payload, when present."
    )
    contents: List[ContentWrite] = Field(default_factory=list)


class OperationWrite(BaseModel):
    """One ``path_operation`` row with its description and links."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    method: str = Field(description="Lower-case HTTP method key.")
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = Field(default=None, alias="operationId")
    description_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        alias="descriptionMetadata",
        description="path_operation_description.metadata: tags, deprecated, "
        "security, external_docs, and operation-level x-* keys.",
    )
    parameters: List[ParameterWrite] = Field(default_factory=list)
    request_body: Optional[RequestBodyWrite] = Field(default=None, alias="requestBody")
    response_status_codes: List[str] = Field(
        default_factory=list,
        alias="responseStatusCodes",
        description="Status codes this operation links to (rows are shared "
        "per path + status).",
    )


class PathWrite(BaseModel):
    """One ``version_path`` row with its operations and shared responses."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pathname: str
    summary: Optional[str] = None
    description: Optional[str] = None
    operations: List[OperationWrite] = Field(default_factory=list)
    responses: List[ResponseWrite] = Field(
        default_factory=list,
        description="Path-shared response rows, one per status code.",
    )


class SecuritySchemeWrite(BaseModel):
    """One ``version_security_scheme`` row (apiKey schemes only; others
    round-trip through the preservation envelope)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scheme_name: str = Field(alias="schemeName")
    scheme_type: str = Field(alias="schemeType")
    in_location: Optional[str] = Field(default=None, alias="inLocation")
    param_name: Optional[str] = Field(default=None, alias="paramName")
    description: Optional[str] = None


class ServerWrite(BaseModel):
    """One ``version_server`` row."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    url: str
    description: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    sort_order: int = Field(default=0, alias="sortOrder")


class CanonicalWrites(BaseModel):
    """The full deterministic write plan for one candidate document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    classes: List[ClassWrite] = Field(default_factory=list)
    paths: List[PathWrite] = Field(default_factory=list)
    security_schemes: List[SecuritySchemeWrite] = Field(
        default_factory=list, alias="securitySchemes"
    )
    servers: List[ServerWrite] = Field(default_factory=list)


class FidelityReport(BaseModel):
    """Outcome of proving merged (canonical + envelope) against the candidate."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ok: bool
    enrichments: List[str] = Field(
        default_factory=list,
        description="Pointers the generator deterministically added "
        "(injected titles, default responses, schema defaults). Reported, "
        "never silent.",
    )
    losses: List[str] = Field(
        default_factory=list,
        description="Candidate pointers missing from the merged result. Any "
        "entry fails the apply.",
    )
    value_changes: List[str] = Field(
        default_factory=list,
        alias="valueChanges",
        description="Pointers whose value the model would alter. Any entry "
        "fails the apply.",
    )


def _is_reference_property(data: Dict[str, Any]) -> bool:
    if "$ref" in data:
        return True
    items = data.get("items")
    return data.get("type") == "array" and isinstance(items, dict) and "$ref" in items


def _class_writes(candidate: Dict[str, Any]) -> List[ClassWrite]:
    components = candidate.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        return []
    writes: List[ClassWrite] = []
    for name in sorted(schemas.keys()):
        schema = schemas[name]
        if not isinstance(schema, dict):
            # Boolean schemas etc. cannot become class rows; the envelope
            # preserves them.
            continue
        stored = {k: v for k, v in schema.items() if k not in ("properties", "required")}
        required = schema.get("required")
        required_names = set(required) if isinstance(required, list) else set()
        properties: List[ClassPropertyWrite] = []
        raw_properties = schema.get("properties")
        if isinstance(raw_properties, dict):
            for prop_name in sorted(raw_properties.keys()):
                prop_schema = raw_properties[prop_name]
                if not isinstance(prop_schema, dict):
                    continue
                data = copy.deepcopy(prop_schema)
                if prop_name in required_names:
                    data["required"] = True
                properties.append(
                    ClassPropertyWrite(
                        name=prop_name,
                        data=data,
                        is_reference=_is_reference_property(data),
                    )
                )
        writes.append(ClassWrite(name=name, schema_fields=stored, properties=properties))
    return writes


def _parameter_write(param: Dict[str, Any]) -> Optional[ParameterWrite]:
    name = param.get("name")
    if not isinstance(name, str) or not name:
        return None
    if "content" in param:
        # Media-type parameters have no relational shape; leaving the row
        # out surfaces an honest fidelity loss instead of a wrong rebuild.
        return None
    schema = param.get("schema")
    data: Dict[str, Any] = copy.deepcopy(schema) if isinstance(schema, dict) else {}
    for key in _PARAMETER_DATA_KEYS:
        if key in param:
            data[key] = copy.deepcopy(param[key])
    return ParameterWrite(
        name=name,
        in_location=param.get("in") or "query",
        summary=param.get("summary"),
        description=param.get("description"),
        data=data,
    )


def _examples_list(media_obj: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if "example" in media_obj:
        return [{"value": copy.deepcopy(media_obj["example"])}]
    examples = media_obj.get("examples")
    if isinstance(examples, dict) and examples:
        listed: List[Dict[str, Any]] = []
        for ex_name in examples.keys():
            entry = examples[ex_name]
            listed.append(
                {
                    "name": ex_name,
                    "summary": entry.get("summary") if isinstance(entry, dict) else None,
                    "value": copy.deepcopy(entry.get("value")) if isinstance(entry, dict) else None,
                }
            )
        return listed
    return None


def _content_write(media_type: str, media_obj: Any) -> Optional[ContentWrite]:
    if not isinstance(media_obj, dict):
        return None
    schema = media_obj.get("schema")
    ref_class: Optional[str] = None
    inline: Optional[Dict[str, Any]] = None
    if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
        match = schema["$ref"]
        prefix = "#/components/schemas/"
        if match.startswith(prefix) and len(schema) == 1:
            ref_class = match[len(prefix):]
        else:
            inline = copy.deepcopy(schema)
    elif isinstance(schema, dict):
        inline = copy.deepcopy(schema)
    encoding = media_obj.get("encoding")
    return ContentWrite(
        media_type=media_type,
        ref_class_name=ref_class,
        inline_schema=inline,
        encoding=copy.deepcopy(encoding) if isinstance(encoding, dict) else None,
        examples=_examples_list(media_obj),
    )


def _request_body_write(
    operation: Dict[str, Any], method: str, pathname: str
) -> Optional[RequestBodyWrite]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content")
    if not isinstance(content, dict) or not content:
        return None
    op_id = operation.get("operationId")
    name = (
        op_id
        if isinstance(op_id, str) and op_id
        else "RequestBody_"
        + method
        + "_"
        + (pathname.lstrip("/").replace("/", "_") or "root")
    )
    contents: List[ContentWrite] = []
    for media_type in sorted(content.keys()):
        write = _content_write(media_type, content[media_type])
        if write is not None:
            contents.append(write)
    return RequestBodyWrite(
        name=name,
        description=body.get("description"),
        required=body.get("required") is True,
        contents=contents,
    )


def _response_write(status_code: str, response: Any) -> Optional[ResponseWrite]:
    if not isinstance(response, dict):
        return None
    data: Dict[str, Any] = {}
    if isinstance(response.get("headers"), dict) and response["headers"]:
        data["headers"] = copy.deepcopy(response["headers"])
    if isinstance(response.get("links"), dict) and response["links"]:
        data["links"] = copy.deepcopy(response["links"])
    contents: List[ContentWrite] = []
    content = response.get("content")
    if isinstance(content, dict):
        for media_type in sorted(content.keys()):
            write = _content_write(media_type, content[media_type])
            if write is not None:
                contents.append(write)
    return ResponseWrite(
        status_code=status_code,
        description=response.get("description"),
        data=data or None,
        contents=contents,
    )


def _operation_description_metadata(operation: Dict[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    tags = operation.get("tags")
    if isinstance(tags, list) and tags:
        metadata["tags"] = copy.deepcopy(tags)
    if operation.get("deprecated") is True:
        metadata["deprecated"] = True
    if isinstance(operation.get("security"), list):
        metadata["security"] = copy.deepcopy(operation["security"])
    external_docs = operation.get("externalDocs")
    if isinstance(external_docs, dict) and external_docs.get("url"):
        metadata["external_docs"] = copy.deepcopy(external_docs)
    for key in operation.keys():
        if key.startswith("x-"):
            metadata[key] = copy.deepcopy(operation[key])
    return metadata


def _path_writes(candidate: Dict[str, Any]) -> List[PathWrite]:
    paths = candidate.get("paths")
    if not isinstance(paths, dict):
        return []
    writes: List[PathWrite] = []
    for pathname in sorted(paths.keys()):
        item = paths[pathname]
        if not isinstance(item, dict):
            continue
        operations: List[OperationWrite] = []
        responses_by_status: Dict[str, ResponseWrite] = {}
        for method in sorted(item.keys()):
            if method.lower() not in _OPERATION_METHODS:
                continue
            operation = item[method]
            if not isinstance(operation, dict):
                continue
            parameters: List[ParameterWrite] = []
            raw_params = operation.get("parameters")
            if isinstance(raw_params, list):
                for raw in raw_params:
                    if isinstance(raw, dict):
                        write = _parameter_write(raw)
                        if write is not None:
                            parameters.append(write)
            request_body = (
                _request_body_write(operation, method, pathname)
                if method.lower() in _REQUEST_BODY_METHODS
                else None
            )
            status_codes: List[str] = []
            raw_responses = operation.get("responses")
            if isinstance(raw_responses, dict):
                for status in sorted(raw_responses.keys()):
                    response_write = _response_write(status, raw_responses[status])
                    if response_write is None:
                        continue
                    status_codes.append(status)
                    # Shared per (path, status); the review blocks candidates
                    # whose operations disagree about a status body, so the
                    # first writer wins here without information loss.
                    responses_by_status.setdefault(status, response_write)
            op_id = operation.get("operationId")
            operations.append(
                OperationWrite(
                    method=method.lower(),
                    summary=operation.get("summary"),
                    description=operation.get("description"),
                    operation_id=op_id if isinstance(op_id, str) else None,
                    description_metadata=_operation_description_metadata(operation),
                    parameters=parameters,
                    request_body=request_body,
                    response_status_codes=status_codes,
                )
            )
        writes.append(
            PathWrite(
                pathname=pathname,
                summary=item.get("summary") if isinstance(item.get("summary"), str) else None,
                description=item.get("description")
                if isinstance(item.get("description"), str)
                else None,
                operations=operations,
                responses=sorted(responses_by_status.values(), key=lambda r: r.status_code),
            )
        )
    return writes


def _security_scheme_writes(candidate: Dict[str, Any]) -> List[SecuritySchemeWrite]:
    components = candidate.get("components")
    schemes = components.get("securitySchemes") if isinstance(components, dict) else None
    if not isinstance(schemes, dict):
        return []
    writes: List[SecuritySchemeWrite] = []
    for name in sorted(schemes.keys()):
        scheme = schemes[name]
        if not isinstance(scheme, dict) or scheme.get("type") != "apiKey":
            # Only apiKey schemes have relational rows today; every other
            # scheme type round-trips through the preservation envelope.
            continue
        writes.append(
            SecuritySchemeWrite(
                scheme_name=name,
                scheme_type="apiKey",
                in_location=scheme.get("in") or "header",
                param_name=scheme.get("name") or name,
                description=scheme.get("description"),
            )
        )
    return writes


def _server_writes(candidate: Dict[str, Any]) -> List[ServerWrite]:
    servers = candidate.get("servers")
    if not isinstance(servers, list):
        return []
    writes: List[ServerWrite] = []
    for index, server in enumerate(servers):
        if not isinstance(server, dict) or not isinstance(server.get("url"), str):
            continue
        variables = server.get("variables")
        writes.append(
            ServerWrite(
                url=server["url"],
                description=server.get("description"),
                variables=copy.deepcopy(variables)
                if isinstance(variables, dict) and variables
                else None,
                sort_order=index,
            )
        )
    return writes


def build_canonical_writes(candidate: Dict[str, Any]) -> CanonicalWrites:
    """Plan the deterministic relational writes for a candidate document.

    Args:
        candidate: The parsed, syntax- and schema-valid candidate document.

    Returns:
        A :class:`CanonicalWrites` plan. Anything the plan does not absorb
        (path-level parameters, non-apiKey security schemes, callbacks,
        vendor keys, …) is intentionally left for the preservation envelope.
    """
    return CanonicalWrites(
        classes=_class_writes(candidate),
        paths=_path_writes(candidate),
        security_schemes=_security_scheme_writes(candidate),
        servers=_server_writes(candidate),
    )


def _sorted_parameter_rows(parameters: List[ParameterWrite]) -> List[ParameterWrite]:
    return sorted(
        parameters,
        key=lambda p: (_PARAM_LOCATION_ORDER.get(p.in_location, 4), p.name),
    )


def parameter_key(parameter: ParameterWrite) -> Tuple[str, str]:
    """The per-path sharing key for a parameter row: (name, in-location)."""
    return (parameter.name, parameter.in_location)


def path_shared_parameters(path: PathWrite) -> Dict[Tuple[str, str], ParameterWrite]:
    """The deduplicated shared parameter rows for one path.

    Parameter rows are shared per path with a unique (name, in) constraint.
    Iterating operations in list order, the first declaration of a key wins —
    the review engine blocks candidates whose operations disagree about a
    shared parameter, so first-wins never loses information here. Both the
    regeneration prediction and the database writer use this same map, so
    they cannot diverge.
    """
    shared: Dict[Tuple[str, str], ParameterWrite] = {}
    for operation in path.operations:
        for parameter in operation.parameters:
            shared.setdefault(parameter_key(parameter), parameter)
    return shared


def _content_row(index: int, content: ContentWrite, class_names: Dict[str, str]) -> Dict[str, Any]:
    class_id = class_names.get(content.ref_class_name) if content.ref_class_name else None
    return {
        "id": f"content-{index}",
        "media_type": content.media_type,
        "class_id": class_id,
        "class_name": content.ref_class_name if class_id else None,
        "inline_schema": copy.deepcopy(content.inline_schema),
        "encoding": copy.deepcopy(content.encoding),
        "examples": copy.deepcopy(content.examples),
    }


def _paths_data_from_writes(
    writes: CanonicalWrites, class_names: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Rows shaped exactly like ``_load_paths_for_version`` would return."""
    paths_data: List[Dict[str, Any]] = []
    for path_index, path in enumerate(writes.paths):
        shared_params = path_shared_parameters(path)
        response_rows: Dict[str, Dict[str, Any]] = {}
        for response in path.responses:
            response_rows[response.status_code] = {
                "id": f"response-{path_index}-{response.status_code}",
                "status_code": response.status_code,
                "description": response.description,
                "data": copy.deepcopy(response.data) if response.data else ({} if not response.contents else None),
                "class_id": None,
                "class_name": None,
                "inline_schema": None,
                "content_types": [
                    _content_row(ct_index, content, class_names)
                    for ct_index, content in enumerate(response.contents)
                ],
            }
        operations: List[Dict[str, Any]] = []
        ordered = sorted(
            path.operations,
            key=lambda op: _OPERATION_ORDER.get(op.method.upper(), 6),
        )
        for op_index, op in enumerate(ordered):
            description_row = {
                "id": f"opdesc-{path_index}-{op_index}",
                "summary": op.summary,
                "description": op.description,
                "operation_id": op.operation_id,
                "tags": copy.deepcopy(op.description_metadata.get("tags")),
                "deprecated": op.description_metadata.get("deprecated"),
                "x_private": op.description_metadata.get("x-private"),
                "external_docs": copy.deepcopy(op.description_metadata.get("external_docs")),
                "metadata": copy.deepcopy(op.description_metadata),
            }
            request_body_row = None
            if op.request_body is not None:
                request_body_row = {
                    "id": f"reqbody-{path_index}-{op_index}",
                    "name": op.request_body.name,
                    "description": op.request_body.description,
                    "required": op.request_body.required,
                    "content_types": [
                        _content_row(ct_index, content, class_names)
                        for ct_index, content in enumerate(op.request_body.contents)
                    ],
                }
            operations.append(
                {
                    "id": f"op-{path_index}-{op_index}",
                    "operation": op.method.upper(),
                    "description": description_row,
                    "parameters": [
                        {
                            "id": f"param-{path_index}-{op_index}-{p_index}",
                            "name": row.name,
                            "in_location": row.in_location,
                            "summary": row.summary,
                            "description": row.description,
                            "data": copy.deepcopy(row.data),
                        }
                        for p_index, row in enumerate(
                            _sorted_parameter_rows(
                                [
                                    shared_params[parameter_key(p)]
                                    for p in op.parameters
                                ]
                            )
                        )
                    ],
                    "requestBody": request_body_row,
                    "responses": [
                        response_rows[status]
                        for status in sorted(op.response_status_codes)
                        if status in response_rows
                    ],
                }
            )
        paths_data.append(
            {
                "id": f"path-{path_index}",
                "pathname": path.pathname,
                "summary": path.summary,
                "description": path.description,
                "operations": operations,
            }
        )
    return paths_data


def regenerate_document(
    writes: CanonicalWrites,
    *,
    tenant_slug: str,
    project_slug: str,
    version_string: str,
    project_description: Optional[str],
    revision_metadata: Any = None,
    project_metadata: Any = None,
) -> Dict[str, Any]:
    """Predict the canonical document the generator will emit from a plan.

    Feeds :func:`app.openapi_generator.generate_openapi_spec` with rows shaped
    exactly like the database read-back (same ordering, same column names),
    so the prediction and the eventual export cannot disagree.
    """
    class_rows: List[Dict[str, Any]] = []
    all_properties: Dict[str, List[Dict[str, Any]]] = {}
    class_names: Dict[str, str] = {}
    for index, class_write in enumerate(writes.classes):
        class_id = f"class-{index}"
        class_names[class_write.name] = class_id
        class_rows.append(
            {
                "id": class_id,
                "name": class_write.name,
                "description": class_write.description,
                "schema": copy.deepcopy(class_write.schema_fields),
                "enabled": True,
            }
        )
        all_properties[class_id] = [
            {
                "id": f"prop-{index}-{p_index}",
                "class_id": class_id,
                "property_id": None,
                "name": prop.name,
                "description": prop.description,
                "data": copy.deepcopy(prop.data),
                "parent_id": None,
            }
            for p_index, prop in enumerate(
                sorted(class_write.properties, key=lambda p: p.name)
            )
        ]
    scheme_rows = [
        {
            "scheme_name": scheme.scheme_name,
            "scheme_type": scheme.scheme_type,
            "in_location": scheme.in_location,
            "param_name": scheme.param_name,
            "description": scheme.description,
        }
        for scheme in writes.security_schemes
    ]
    server_rows = [
        {
            "url": server.url,
            "description": server.description,
            "variables": copy.deepcopy(server.variables),
        }
        for server in sorted(writes.servers, key=lambda s: (s.sort_order, s.url))
    ]
    return generate_openapi_spec(
        tenant_slug,
        project_slug,
        version_string,
        class_rows,
        all_properties,
        project_description,
        revision_metadata=revision_metadata,
        project_metadata=project_metadata,
        paths_data=_paths_data_from_writes(writes, class_names),
        security_scheme_rows=scheme_rows,
        server_rows=server_rows,
    )


def _parameter_sort_key(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(
            [value.get("in") or "", value.get("name") or ""], separators=(",", ":")
        )
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _normalized(value: Any, key: Optional[str] = None) -> Any:
    """Order-insensitive form for comparison: ``required`` name arrays are
    sorted and ``parameters`` arrays ordered by (in, name), mirroring what the
    relational read-back deterministically does. Everything else is kept
    verbatim — array order stays semantic."""
    if isinstance(value, dict):
        return {k: _normalized(v, k) for k, v in value.items()}
    if isinstance(value, list):
        items = [_normalized(item) for item in value]
        if key == "required" and all(isinstance(item, str) for item in items):
            return sorted(items)
        if key == "parameters" and all(isinstance(item, dict) for item in items):
            return sorted(items, key=_parameter_sort_key)
        return items
    return value


def compare_candidate_to_merged(candidate: Any, merged: Any) -> FidelityReport:
    """Prove the merged result carries the candidate without loss or drift.

    Args:
        candidate: The parsed candidate document.
        merged: The predicted canonical document with the re-extracted
            preservation envelope applied.

    Returns:
        A :class:`FidelityReport`. ``ok`` is True only when every difference
        is a deterministic generator **enrichment** (present in merged,
        absent from the candidate). Losses and value changes always fail.
    """
    deltas = diff_documents(_normalized(candidate), _normalized(merged))
    enrichments: List[str] = []
    losses: List[str] = []
    value_changes: List[str] = []
    for delta in deltas:
        if delta["kind"] == "addition":
            enrichments.append(delta["pointer"])
        elif delta["kind"] == "deletion":
            losses.append(delta["pointer"])
        else:
            value_changes.append(delta["pointer"])
    return FidelityReport(
        ok=not losses and not value_changes,
        enrichments=enrichments,
        losses=losses,
        value_changes=value_changes,
    )
