"""
OpenAPI Paths Generator for Python

Generates the OpenAPI paths section from database records.
Handles request bodies with both class references and inline schemas,
parameters, and responses.

The ``openapi_version`` option (default ``3.1.0``) decides how the OpenAPI 3.2 constructs a
project can hold are written (COA-2.5, #7048):

* a ``QUERY`` operation and any other non-standard method (``REPORT``) — the Path Item's ``query``
  field and its ``additionalOperations`` map for 3.2; for 3.1 the ``x-apiome-query-operation`` /
  ``x-apiome-additional-operations`` stashes the importers read back (a 3.1 Path Item allows only
  the fixed verbs and ``x-`` keys);
* a content row flagged ``item_schema`` (a streaming media type) — ``itemSchema`` for 3.2, else the
  ``x-apiome-item-schema`` stash;
* an ``in: querystring`` parameter — written (with ``content``) only for 3.2; a 3.1 Parameter
  Object has no such location, so it is left out.
"""

import json
import re
from typing import Dict, Any, List, Optional

#: The Path Item operation fields every OpenAPI 3.x version has.
FIXED_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: The 3.2 parameter location for the whole query string.
QUERYSTRING_LOCATION = "querystring"

#: Media type of a ``querystring`` parameter's ``content`` when none was stored.
DEFAULT_QUERYSTRING_MEDIA_TYPE = "application/x-www-form-urlencoded"

#: Extensions a 3.1 document carries the 3.2 constructs on (the importers' OA2 stashes).
STASHED_QUERY_OPERATION_EXTENSION = "x-apiome-query-operation"
STASHED_ADDITIONAL_OPERATIONS_EXTENSION = "x-apiome-additional-operations"
STASHED_ITEM_SCHEMA_EXTENSION = "x-apiome-item-schema"


def is_openapi_32(openapi_version: Optional[str]) -> bool:
    """Whether a target OpenAPI version has the 3.2 constructs.

    Args:
        openapi_version: The target version (``3.2.0``, ``3.1.0``); ``None`` means 3.1.

    Returns:
        True for any 3.2.x version.
    """
    return isinstance(openapi_version, str) and re.match(r"^3\.2(\.|$)", openapi_version.strip()) is not None


def _apply_item_schema_keys(content: Dict[str, Any], content_types: List[Dict[str, Any]], is32: bool) -> None:
    """Move each streaming media type's ``schema`` to ``itemSchema`` (3.2) or its stash (3.1).

    The content rows keep an element schema in the same ``class_id`` / ``inline_schema`` columns as
    a body schema; ``item_schema`` says which it is.

    Args:
        content: The built ``content`` map (mutated).
        content_types: The stored content rows.
        is32: Whether the target is OpenAPI 3.2.
    """
    key = "itemSchema" if is32 else STASHED_ITEM_SCHEMA_EXTENSION
    for ct in content_types:
        if ct.get("item_schema") is not True:
            continue
        media = content.get(ct.get("media_type", "application/json"))
        if isinstance(media, dict) and "schema" in media:
            media[key] = media.pop("schema")


def method_takes_request_body(method: str) -> bool:
    """Whether a stored request body is written for an operation of this method.

    POST, PUT and PATCH carry one, as before; so do QUERY and any custom method (#7048).
    GET, HEAD, DELETE, OPTIONS and TRACE do not.

    Args:
        method: The stored method token.

    Returns:
        True when the request body is written.
    """
    upper = (method or "").strip().upper()
    if upper in ("POST", "PUT", "PATCH"):
        return True
    return bool(upper) and upper.lower() not in FIXED_HTTP_METHODS


def parse_json_field(field: Any) -> Any:
    """Parse a JSON field that might be a string or dict."""
    if field is None:
        return None
    if isinstance(field, str):
        try:
            return json.loads(field)
        except json.JSONDecodeError:
            return field
    return field


def build_schema_from_inline_properties(inline_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Build schema from inline properties structure."""
    if not inline_schema:
        return {}

    schema: Dict[str, Any] = {}
    raw_properties = inline_schema.get('properties')
    properties = raw_properties if isinstance(raw_properties, list) else []

    # Composition-only: OpenAPI Schema Object with allOf / anyOf / oneOf (no inline property tree)
    for key in ('allOf', 'anyOf', 'oneOf'):
        branches = inline_schema.get(key)
        if isinstance(branches, list) and len(branches) > 0 and len(properties) == 0:
            out: Dict[str, Any] = {}
            if inline_schema.get('description'):
                out['description'] = inline_schema['description']
            out[key] = branches
            return out

    if not properties:
        return inline_schema

    # Build properties object
    schema_props: Dict[str, Any] = {}
    required: List[str] = []

    for prop in properties:
        prop_name = prop.get('name')
        if not prop_name:
            continue

        prop_data = prop.get('data', {})
        prop_schema = dict(prop_data)
        prop_schema.pop('id', None)
        prop_schema.pop('parent_id', None)

        # Handle required
        if prop_schema.get('required') is True:
            required.append(prop_name)
            prop_schema.pop('required', None)
        elif 'required' in prop_schema:
            prop_schema.pop('required', None)

        # Handle nested properties
        if prop_schema.get('type') == 'object' and prop.get('properties'):
            nested_result = build_schema_from_inline_properties({'properties': prop['properties']})
            if 'properties' in nested_result:
                prop_schema['properties'] = nested_result['properties']
            if 'required' in nested_result:
                prop_schema['required'] = nested_result['required']

        # Handle array items with nested properties
        if prop_schema.get('type') == 'array' and prop.get('properties'):
            items_result = build_schema_from_inline_properties({'properties': prop['properties']})
            items_schema = prop_schema.get('items', {})
            if isinstance(items_schema, dict):
                items_schema.update(items_result)
                prop_schema['items'] = items_schema

        schema_props[prop_name] = prop_schema

    schema['type'] = 'object'
    schema['properties'] = schema_props
    if required:
        schema['required'] = required

    return schema


def build_querystring_parameter(param: Dict[str, Any]) -> Dict[str, Any]:
    """Build an OpenAPI 3.2 ``in: querystring`` Parameter Object.

    The whole query string is one value, so the parameter carries ``content`` (the media type in
    ``data.contentMediaType``, default ``application/x-www-form-urlencoded``) instead of ``schema``.

    Args:
        param: The stored parameter (``in_location`` is ``querystring``).

    Returns:
        The Parameter Object.
    """
    data = dict(parse_json_field(param.get('data')) or {})
    result: Dict[str, Any] = {'name': param['name'], 'in': QUERYSTRING_LOCATION}
    if param.get('summary'):
        result['summary'] = param['summary']
    if param.get('description'):
        result['description'] = param['description']
    if data.pop('required', None) is True:
        result['required'] = True
    if data.pop('deprecated', None):
        result['deprecated'] = True
    media_type = data.pop('contentMediaType', None)
    if not isinstance(media_type, str) or not media_type.strip():
        media_type = DEFAULT_QUERYSTRING_MEDIA_TYPE
    media_obj: Dict[str, Any] = {}
    if 'example' in data:
        media_obj['example'] = data.pop('example')
    if 'examples' in data:
        media_obj['examples'] = data.pop('examples')
    for key in ('id', 'parent_id', 'style', 'explode', 'allowReserved', 'allowEmptyValue'):
        data.pop(key, None)
    media_obj['schema'] = data or {'type': 'object'}
    result['content'] = {media_type.strip(): media_obj}
    return result


def build_parameter_for_openapi(param: Dict[str, Any]) -> Dict[str, Any]:
    """Build OpenAPI parameter object from database parameter record."""
    if param.get('in_location') == QUERYSTRING_LOCATION:
        return build_querystring_parameter(param)
    data = parse_json_field(param.get('data')) or {}

    result: Dict[str, Any] = {
        'name': param['name'],
        'in': param['in_location'],
    }

    # Add summary if present (OpenAPI 3.x parameter field)
    if param.get('summary'):
        result['summary'] = param['summary']
    # Add description if present
    if param.get('description'):
        result['description'] = param['description']

    # Extract required flag from data
    is_required = data.get('required') is True or param['in_location'] == 'path'
    if is_required:
        result['required'] = True

    # Build schema from data (excluding non-schema fields)
    schema_data = dict(data)
    schema_data.pop('id', None)
    schema_data.pop('parent_id', None)
    schema_data.pop('required', None)

    # Handle deprecated
    if schema_data.get('deprecated'):
        result['deprecated'] = True
        schema_data.pop('deprecated', None)

    # Handle allowEmptyValue
    if 'allowEmptyValue' in schema_data:
        result['allowEmptyValue'] = schema_data.pop('allowEmptyValue')

    # Handle style and explode
    if 'style' in schema_data:
        result['style'] = schema_data.pop('style')
    if 'explode' in schema_data:
        result['explode'] = schema_data.pop('explode')

    # Handle example(s)
    if 'example' in schema_data:
        result['example'] = schema_data.pop('example')
    if 'examples' in schema_data:
        result['examples'] = schema_data.pop('examples')

    # Build the schema
    if schema_data:
        result['schema'] = schema_data
    else:
        # Default to string if no schema specified
        result['schema'] = {'type': 'string'}

    return result


def build_request_body_for_openapi(request_body: Dict[str, Any], is32: bool = False) -> Dict[str, Any]:
    """Build OpenAPI request body object from database request body record.

    ``is32`` writes a streaming media type's schema as ``itemSchema`` (else as its stash).
    """
    result: Dict[str, Any] = {}

    # Add description if present
    if request_body.get('description'):
        result['description'] = request_body['description']

    # Add required flag
    if request_body.get('required'):
        result['required'] = True

    # Build content types
    content_types = request_body.get('content_types', [])
    if content_types:
        content: Dict[str, Any] = {}

        for ct in content_types:
            media_type = ct.get('media_type', 'application/json')
            media_type_obj: Dict[str, Any] = {}

            # Build schema from class reference or inline schema
            if ct.get('class_id') and ct.get('class_name'):
                media_type_obj['schema'] = {
                    '$ref': f"#/components/schemas/{ct['class_name']}"
                }
            elif ct.get('inline_schema'):
                inline = parse_json_field(ct['inline_schema'])
                media_type_obj['schema'] = build_schema_from_inline_properties(inline)

            # Add encoding if present
            if ct.get('encoding'):
                encoding = parse_json_field(ct['encoding'])
                if encoding:
                    media_type_obj['encoding'] = encoding

            # Add examples if present
            if ct.get('examples'):
                examples = parse_json_field(ct['examples'])
                if examples and isinstance(examples, list):
                    if len(examples) == 1:
                        media_type_obj['example'] = examples[0].get('value')
                    else:
                        examples_obj: Dict[str, Any] = {}
                        for ex in examples:
                            if ex.get('name'):
                                examples_obj[ex['name']] = {
                                    'summary': ex.get('summary'),
                                    'value': ex.get('value'),
                                }
                        if examples_obj:
                            media_type_obj['examples'] = examples_obj

            content[media_type] = media_type_obj

        _apply_item_schema_keys(content, content_types, is32)
        result['content'] = content

    return result


def build_response_for_openapi(response: Dict[str, Any], is32: bool = False) -> Dict[str, Any]:
    """Build OpenAPI response object from database response record.

    ``is32`` writes a streaming media type's schema as ``itemSchema`` (else as its stash).
    """
    result: Dict[str, Any] = {}

    # Add description (required for OpenAPI)
    result['description'] = response.get('description') or f"{response.get('status_code')} response"

    # Check if response has multiple content types
    content_types = response.get('content_types', [])
    if content_types:
        content: Dict[str, Any] = {}

        for ct in content_types:
            media_type = ct.get('media_type', 'application/json')
            media_type_obj: Dict[str, Any] = {}

            # Build schema from class reference or inline schema
            if ct.get('class_id') and ct.get('class_name'):
                media_type_obj['schema'] = {
                    '$ref': f"#/components/schemas/{ct['class_name']}"
                }
            elif ct.get('inline_schema'):
                inline = parse_json_field(ct['inline_schema'])
                media_type_obj['schema'] = build_schema_from_inline_properties(inline)

            # Add examples
            if ct.get('examples'):
                examples = parse_json_field(ct['examples'])
                if examples and isinstance(examples, list):
                    if len(examples) == 1:
                        media_type_obj['example'] = examples[0].get('value')
                    else:
                        examples_obj: Dict[str, Any] = {}
                        for ex in examples:
                            if ex.get('name'):
                                examples_obj[ex['name']] = {
                                    'summary': ex.get('summary'),
                                    'value': ex.get('value'),
                                }
                        if examples_obj:
                            media_type_obj['examples'] = examples_obj

            content[media_type] = media_type_obj

        _apply_item_schema_keys(content, content_types, is32)
        result['content'] = content
    else:
        # Fallback: Single content type or legacy format
        schema: Optional[Dict[str, Any]] = None

        if response.get('class_id') and response.get('class_name'):
            # Reference to existing class
            schema = {
                '$ref': f"#/components/schemas/{response['class_name']}"
            }
        elif response.get('inline_schema'):
            # Inline schema
            inline = parse_json_field(response['inline_schema'])
            schema = build_schema_from_inline_properties(inline)
        elif response.get('data'):
            # Legacy data format - extract schema from it
            data = parse_json_field(response['data'])
            if isinstance(data, dict):
                if data.get('content'):
                    result['content'] = data['content']
                elif data.get('schema'):
                    schema = data['schema']
                elif data.get('$ref'):
                    schema = {'$ref': data['$ref']}

        # Build content object if we have a schema and content wasn't already set
        if schema and 'content' not in result:
            result['content'] = {
                'application/json': {
                    'schema': schema
                }
            }

    # Add headers if present in data
    if response.get('data'):
        data = parse_json_field(response['data'])
        if isinstance(data, dict):
            if data.get('headers'):
                result['headers'] = data['headers']
            if data.get('links'):
                result['links'] = data['links']

    return result


def build_operation_for_openapi(operation: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build OpenAPI operation object from database operation record."""
    options = options or {}
    result: Dict[str, Any] = {}

    # Add operation metadata from description
    description = operation.get('description')
    if description:
        if description.get('summary'):
            result['summary'] = description['summary']
        if options.get('includeDescriptions', True) and description.get('description'):
            result['description'] = description['description']
        # operationId: camelCase (OpenAPI) or snake_case (the database column).
        operation_id = description.get('operationId') or description.get('operation_id')
        if operation_id:
            result['operationId'] = operation_id
        if description.get('tags'):
            tags = parse_json_field(description['tags'])
            if tags and isinstance(tags, list):
                result['tags'] = tags
        if description.get('deprecated'):
            result['deprecated'] = True
        # externalDocs: support both camelCase (OpenAPI) and snake_case (DB)
        external_docs = description.get('externalDocs') or description.get('external_docs')
        if external_docs:
            external_docs = parse_json_field(external_docs)
            if external_docs and external_docs.get('url'):
                result['externalDocs'] = {
                    'url': external_docs['url'],
                    **({'description': external_docs['description']} if external_docs.get('description') else {}),
                }
        # Security requirements (OpenAPI Operation.security)
        # Explicit security: [] = public (no auth); omit = inherit from document
        security = description.get('security')
        if not security and description.get('metadata'):
            metadata = parse_json_field(description['metadata']) if isinstance(description['metadata'], str) else description['metadata']
            if isinstance(metadata, dict):
                security = metadata.get('security')
        if security is not None and isinstance(security, list):
            result['security'] = security  # [] = unsecured (public), non-empty = requirements

        # Security description for documentation (emitted as x-security-description)
        security_desc = description.get('security_description') or description.get('securityDescription')
        if not security_desc and description.get('metadata'):
            metadata = parse_json_field(description['metadata']) if isinstance(description['metadata'], str) else description['metadata']
            if isinstance(metadata, dict):
                security_desc = metadata.get('security_description') or metadata.get('securityDescription') or metadata.get('x-security-description')
        if security_desc and isinstance(security_desc, str) and security_desc.strip():
            result['x-security-description'] = security_desc.strip()

        # x-private: hide from public docs (Swagger/OpenAPI doc generators may omit)
        x_private = description.get('x_private') or description.get('x-private')
        if x_private and (x_private is True or str(x_private).lower() == 'true'):
            result['x-private'] = True

        # Custom x-* extensions: copy any x-* keys from metadata to the operation
        metadata = description.get('metadata')
        if metadata:
            metadata = parse_json_field(metadata) if isinstance(metadata, str) else metadata
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    if key.startswith('x-') and key != 'x-private':
                        result[key] = value

    is32 = is_openapi_32(options.get('openapi_version'))

    # Add parameters (a 3.2 querystring parameter has no 3.1 form and is left out of older targets)
    parameters = [
        p for p in (operation.get('parameters') or [])
        if is32 or p.get('in_location') != QUERYSTRING_LOCATION
    ]
    if parameters:
        result['parameters'] = [build_parameter_for_openapi(p) for p in parameters]

    # Add request body (POST, PUT, PATCH, and QUERY / custom methods)
    request_body = operation.get('requestBody')
    if request_body and method_takes_request_body(operation.get('operation', '')):
        result['requestBody'] = build_request_body_for_openapi(request_body, is32)

    # Add responses
    responses: Dict[str, Any] = {}
    response_list = operation.get('responses', [])
    if response_list:
        for response in response_list:
            status_code = response.get('status_code', '200')
            responses[status_code] = build_response_for_openapi(response, is32)
    else:
        # Default response if none specified (OPTIONS: typical CORS preflight is 204 No Content)
        if operation.get('operation', '').upper() == 'OPTIONS':
            responses['204'] = {
                'description': 'No Content',
            }
        else:
            responses['200'] = {
                'description': 'Successful response'
            }
    result['responses'] = responses

    return result


def build_path_item_for_openapi(path: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build OpenAPI path item object from database path record."""
    options = options or {}
    result: Dict[str, Any] = {}
    exclude_private = options.get('exclude_private', False)

    # Add path-level summary and description
    if path.get('summary'):
        result['summary'] = path['summary']
    if options.get('includeDescriptions', True) and path.get('description'):
        result['description'] = path['description']

    # Add operations (skip those marked x-private when exclude_private is True)
    operations = path.get('operations', [])
    for operation in operations:
        if exclude_private:
            description = operation.get('description') or {}
            if description.get('x_private') or description.get('x-private'):
                continue
        method = operation.get('operation', 'get').lower()
        built = build_operation_for_openapi(operation, options)
        if method in FIXED_HTTP_METHODS:
            result[method] = built
        else:
            _add_non_fixed_operation(
                result, _method_token(operation), built, is_openapi_32(options.get('openapi_version'))
            )

    return result


def _method_token(operation: Dict[str, Any]) -> str:
    """The method token as declared: ``metadata.httpMethod`` from an import, else the stored one."""
    metadata = parse_json_field(operation.get('metadata'))
    if isinstance(metadata, dict) and isinstance(metadata.get('httpMethod'), str) and metadata['httpMethod'].strip():
        return metadata['httpMethod'].strip()
    return str(operation.get('operation', '')).strip()


def _add_non_fixed_operation(path_item: Dict[str, Any], token: str, operation: Dict[str, Any], is32: bool) -> None:
    """Place a QUERY or custom-method operation on a path item.

    OpenAPI 3.2 writes ``query`` and ``additionalOperations[token]``; 3.1 writes the
    ``x-apiome-query-operation`` / ``x-apiome-additional-operations`` stashes.

    Args:
        path_item: The path item being built (mutated).
        token: The method token as sent on the wire.
        operation: The built Operation Object.
        is32: Whether the target is OpenAPI 3.2.
    """
    if token.upper() == 'QUERY':
        path_item['query' if is32 else STASHED_QUERY_OPERATION_EXTENSION] = operation
        return
    map_key = 'additionalOperations' if is32 else STASHED_ADDITIONAL_OPERATIONS_EXTENSION
    existing = path_item.get(map_key)
    operations = existing if isinstance(existing, dict) else {}
    operations[token] = operation
    path_item[map_key] = operations


def generate_paths_for_openapi(paths: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate complete OpenAPI paths object from array of path records."""
    options = options or {}
    result: Dict[str, Any] = {}

    for path in paths:
        pathname = path.get('pathname')
        if pathname:
            result[pathname] = build_path_item_for_openapi(path, options)

    return result
