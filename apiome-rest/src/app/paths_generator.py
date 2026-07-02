"""
OpenAPI Paths Generator for Python

Generates OpenAPI 3.1.0 paths section from database records.
Handles request bodies with both class references and inline schemas,
parameters, and responses.
"""

import json
from typing import Dict, Any, List, Optional


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


def build_parameter_for_openapi(param: Dict[str, Any]) -> Dict[str, Any]:
    """Build OpenAPI parameter object from database parameter record."""
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


def build_request_body_for_openapi(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Build OpenAPI request body object from database request body record."""
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

        result['content'] = content

    return result


def build_response_for_openapi(response: Dict[str, Any]) -> Dict[str, Any]:
    """Build OpenAPI response object from database response record."""
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
        if description.get('operationId'):
            result['operationId'] = description['operationId']
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

    # Add parameters
    parameters = operation.get('parameters', [])
    if parameters:
        result['parameters'] = [build_parameter_for_openapi(p) for p in parameters]

    # Add request body (for POST, PUT, PATCH)
    request_body = operation.get('requestBody')
    if request_body and operation.get('operation', '').upper() in ['POST', 'PUT', 'PATCH']:
        result['requestBody'] = build_request_body_for_openapi(request_body)

    # Add responses
    responses: Dict[str, Any] = {}
    response_list = operation.get('responses', [])
    if response_list:
        for response in response_list:
            status_code = response.get('status_code', '200')
            responses[status_code] = build_response_for_openapi(response)
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
        result[method] = build_operation_for_openapi(operation, options)

    return result


def generate_paths_for_openapi(paths: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate complete OpenAPI paths object from array of path records."""
    options = options or {}
    result: Dict[str, Any] = {}

    for path in paths:
        pathname = path.get('pathname')
        if pathname:
            result[pathname] = build_path_item_for_openapi(path, options)

    return result
