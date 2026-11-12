import json
from typing import Dict, Any, List, Optional, DefaultDict
from collections import defaultdict
from .paths_generator import generate_paths_for_openapi
from .revision_deprecation import deprecation_payload_for_openapi



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


def _build_children_index(properties: List[Dict[str, Any]]) -> DefaultDict[Optional[str], List[Dict[str, Any]]]:
    """Index properties by parent_id for quick child lookup."""
    index: DefaultDict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for p in properties:
        index[p.get('parent_id')].append(p)
    return index


def _clean_description(data: Dict[str, Any]) -> None:
    """Normalize description if it's null; optionally copy from title."""
    if 'description' in data and data['description'] is None:
        # Remove null descriptions to keep output clean
        data.pop('description', None)
        # If title exists, optionally set it as description for readability
        if 'title' in data and data['title']:
            data['description'] = data['title']


def _build_property_schema(prop: Dict[str, Any], children_index: DefaultDict[Optional[str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Recursively build property schema including inline/nested children."""
    prop_data_raw = prop.get('data')
    prop_data = parse_json_field(prop_data_raw) or {}

    # Work on a shallow copy to avoid mutating input
    prop_schema: Dict[str, Any] = dict(prop_data)
    # Exclude internal DB id from the OpenAPI property definition
    prop_schema.pop('id', None)

    _clean_description(prop_schema)

    # Inline object children if this is an object without $ref
    if prop_schema.get('type') == 'object' and '$ref' not in prop_schema:
        children = children_index.get(prop.get('id'), [])
        if children:
            nested_props: Dict[str, Any] = {}
            nested_required: List[str] = []
            for child in children:
                child_schema = _build_property_schema(child, children_index)
                # Move required flag to parent's required array
                if child_schema.get('required') is True:
                    nested_required.append(child['name'])
                    child_schema.pop('required', None)
                elif child_schema.get('required') is False:
                    child_schema.pop('required', None)
                nested_props[child['name']] = child_schema
            if nested_props:
                prop_schema['properties'] = nested_props
            if nested_required:
                prop_schema['required'] = nested_required
            elif 'required' in prop_schema and not prop_schema['required']:
                # Drop empty required to keep output tidy
                prop_schema.pop('required', None)

    # Arrays: if items is object (or missing) and there are children, inline under items
    if prop_schema.get('type') == 'array':
        children = children_index.get(prop.get('id'), [])
        # If children exist but items missing, infer items as object
        if children and 'items' not in prop_schema:
            prop_schema['items'] = { 'type': 'object' }
        items = prop_schema.get('items')
        # Only inline if items is not a $ref and is (or will be) an object
        if isinstance(items, dict) and '$ref' not in items and (items.get('type') == 'object' or children):
            nested_props: Dict[str, Any] = {}
            nested_required: List[str] = []
            for child in children:
                child_schema = _build_property_schema(child, children_index)
                if child_schema.get('required') is True:
                    nested_required.append(child['name'])
                    child_schema.pop('required', None)
                elif child_schema.get('required') is False:
                    child_schema.pop('required', None)
                nested_props[child['name']] = child_schema
            merged_items = dict(items)
            merged_items.pop('id', None)
            merged_items['type'] = 'object'
            if nested_props:
                merged_items['properties'] = nested_props
            if nested_required:
                merged_items['required'] = nested_required
            else:
                # Ensure no empty required remains
                if 'required' in merged_items and not merged_items['required']:
                    merged_items.pop('required', None)
            prop_schema['items'] = merged_items

    return prop_schema


def build_class_openapi_schema(class_data: Dict[str, Any], properties: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build an OpenAPI schema for a single class with nested/inline properties."""
    class_name = class_data['name']
    class_schema_raw = class_data.get('schema')
    class_schema_parsed = parse_json_field(class_schema_raw) or {}

    # Remove properties/required and internal id from stored class schema
    schema_without_props: Dict[str, Any] = dict(class_schema_parsed)
    schema_without_props.pop('properties', None)
    schema_without_props.pop('required', None)
    schema_without_props.pop('id', None)

    # Base object schema
    schema: Dict[str, Any] = {
        "type": "object",
        "title": class_name,
        **({"description": class_data['description']} if class_data.get('description') else {}),
        **schema_without_props,
        "properties": {},
    }

    # Build children index and process only top-level properties (parent_id is null)
    children_index = _build_children_index(properties)
    top_level_props = children_index.get(None, [])

    required: List[str] = []

    for prop in top_level_props:
        prop_name = prop['name']
        prop_schema = _build_property_schema(prop, children_index)
        # Move property-level required flag to class required
        if prop_schema.get('required') is True:
            required.append(prop_name)
            prop_schema.pop('required', None)
        elif prop_schema.get('required') is False:
            prop_schema.pop('required', None)
        schema['properties'][prop_name] = prop_schema

    # Add required if any
    if required:
        schema['required'] = required

    # Clean up empty properties
    if not schema['properties']:
        schema.pop('properties', None)

    return schema


def _load_paths_for_version(version_id: str) -> List[Dict[str, Any]]:
    """Load all paths with full operation details for a version."""
    # Import db here to avoid circular imports and allow tests to run
    try:
        from .database import db
    except ImportError:
        return []

    if db is None:
        return []

    paths_data = db.get_paths_for_version(version_id)
    paths: List[Dict[str, Any]] = []

    for path_row in paths_data:
        operations_data = db.get_operations_for_path(path_row['id'])
        operations: List[Dict[str, Any]] = []

        for op_row in operations_data:
            # Get operation description
            op_description = db.get_operation_description(op_row['id'])

            # Get parameters
            parameters = db.get_parameters_for_operation(op_row['id'])

            # Get request body
            request_body = db.get_request_body_for_operation(op_row['id'])

            # Get responses
            responses = db.get_responses_for_operation(op_row['id'])

            operation = {
                'id': op_row['id'],
                'operation': op_row['operation'],
                'description': op_description,
                'parameters': parameters,
                'requestBody': request_body,
                'responses': responses,
            }
            operations.append(operation)

        path = {
            'id': path_row['id'],
            'pathname': path_row['pathname'],
            'summary': path_row.get('summary'),
            'description': path_row.get('description'),
            'operations': operations,
        }
        paths.append(path)

    return paths


def _security_schemes_from_rows(scheme_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    security_schemes: Dict[str, Any] = {}
    for row in scheme_rows:
        if row.get("scheme_type") == "apiKey":
            security_schemes[row["scheme_name"]] = {
                "type": "apiKey",
                "name": row.get("param_name") or row["scheme_name"],
                "in": row.get("in_location") or "header",
                **({"description": row["description"]} if row.get("description") else {}),
            }
    return security_schemes


def _merge_project_catalog_metadata_into_info(info: Dict[str, Any], project_metadata: Any) -> None:
    """Apply ``apiome.projects.metadata`` (API Metadata / import parity) into OpenAPI ``info``."""
    meta = parse_json_field(project_metadata)
    if not isinstance(meta, dict) or not meta:
        return
    summary = meta.get("summary")
    if isinstance(summary, str) and summary.strip():
        info["summary"] = summary.strip()
    tos = meta.get("termsOfService") or meta.get("terms_of_service")
    if isinstance(tos, str) and tos.strip():
        info["termsOfService"] = tos.strip()
    contact = meta.get("contact")
    if isinstance(contact, dict):
        ci = {k: contact[k] for k in ("name", "url", "email") if contact.get(k)}
        if ci:
            info["contact"] = ci
    lic = meta.get("license")
    if isinstance(lic, dict):
        li = {k: lic[k] for k in ("name", "identifier", "url") if lic.get(k)}
        if li:
            info["license"] = li

    merged_keys = {"summary", "termsOfService", "terms_of_service", "contact", "license"}
    for key, value in meta.items():
        if key in merged_keys or value is None:
            continue
        info[key] = value


def _servers_from_rows(server_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    servers_list: List[Dict[str, Any]] = []
    for row in server_rows:
        s: Dict[str, Any] = {"url": row.get("url") or ""}
        if row.get("description"):
            s["description"] = row["description"]
        variables = row.get("variables")
        if variables:
            variables = parse_json_field(variables) if isinstance(variables, str) else variables
            if isinstance(variables, dict) and variables:
                s["variables"] = variables
        servers_list.append(s)
    return servers_list


def generate_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    classes: List[Dict[str, Any]],
    all_properties: Dict[str, List[Dict[str, Any]]],
    project_description: Optional[str] = None,
    version_db_id: Optional[str] = None,
    revision_metadata: Any = None,
    project_metadata: Any = None,
    paths_data: Optional[List[Dict[str, Any]]] = None,
    security_scheme_rows: Optional[List[Dict[str, Any]]] = None,
    server_rows: Optional[List[Dict[str, Any]]] = None,
    component_pin_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate a complete OpenAPI 3.1.0 specification for all classes in a version."""

    # Build components/schemas for all classes
    schemas: Dict[str, Any] = {}
    for class_data in classes:
        class_id = class_data['id']
        class_name = class_data['name']
        properties = all_properties.get(class_id, [])
        schemas[class_name] = build_class_openapi_schema(class_data, properties)

    # Use project description if provided and not empty, otherwise use default
    description = project_description if project_description and project_description.strip() else "No description provided"

    # Load paths for this version if version_db_id is provided
    # exclude_private=True so operations marked x-private are hidden from Swagger
    paths: Dict[str, Any] = {}
    resolved_paths_data: List[Dict[str, Any]] = []
    if paths_data is not None:
        resolved_paths_data = paths_data
    elif version_db_id:
        try:
            resolved_paths_data = _load_paths_for_version(version_db_id)
        except Exception as e:
            # Log error but continue - paths are optional
            print(f"Warning: Could not load paths for version {version_id}: {e}")
    if resolved_paths_data:
        paths = generate_paths_for_openapi(resolved_paths_data, options={"exclude_private": True})

    # Load security schemes (API Key header/query/cookie, etc.)
    security_schemes: Dict[str, Any] = {}
    resolved_scheme_rows: List[Dict[str, Any]] = []
    if security_scheme_rows is not None:
        resolved_scheme_rows = security_scheme_rows
    elif version_db_id:
        try:
            from .database import db
            if db:
                resolved_scheme_rows = db.get_security_schemes_for_version(version_db_id)
        except Exception as e:
            print(f"Warning: Could not load security schemes for version {version_id}: {e}")
    security_schemes = _security_schemes_from_rows(resolved_scheme_rows)

    # Load servers (multiple server definitions: url, description, variables)
    resolved_server_rows: List[Dict[str, Any]] = []
    if server_rows is not None:
        resolved_server_rows = server_rows
    elif version_db_id:
        try:
            from .database import db
            if db:
                resolved_server_rows = db.get_servers_for_version(version_db_id)
        except Exception as e:
            print(f"Warning: Could not load servers for version {version_id}: {e}")
    servers_list = _servers_from_rows(resolved_server_rows)

    # Build components
    components: Dict[str, Any] = {"schemas": schemas}
    if security_schemes:
        components["securitySchemes"] = security_schemes

    # Materialize pinned library revisions (DCW-3.1, private-suite#2353) into
    # standard local components sections. Pins are immutable published
    # snapshots, so generation stays deterministic; with no pins the document
    # is untouched. Collision-safe naming never overwrites a local component.
    resolved_pin_rows: List[Dict[str, Any]] = []
    if component_pin_rows is not None:
        resolved_pin_rows = component_pin_rows
    elif version_db_id:
        try:
            from .database import db
            if db:
                resolved_pin_rows = db.get_materializable_pins_for_version(version_db_id)
        except Exception as e:
            print(f"Warning: Could not load component pins for version {version_id}: {e}")
    if resolved_pin_rows:
        from .component_library import materialize_pinned_components

        materialized = materialize_pinned_components(
            {"components": components}, resolved_pin_rows, include_origin=True
        )
        components = materialized.document["components"]

    # Build the OpenAPI specification
    info_block: Dict[str, Any] = {
        "title": f"{project_slug} API",
        "version": version_id,
        "description": description,
    }
    dep_info = deprecation_payload_for_openapi(revision_metadata)
    if dep_info:
        info_block["x-apiome-revision-deprecation"] = dep_info

    _merge_project_catalog_metadata_into_info(info_block, project_metadata)

    openapi_spec: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": info_block,
        "paths": paths,
        "components": components,
    }
    if servers_list:
        openapi_spec["servers"] = servers_list

    meta_parsed = parse_json_field(project_metadata)
    if isinstance(meta_parsed, dict) and meta_parsed:
        openapi_spec["x-metadata"] = meta_parsed

    return openapi_spec


def generate_class_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    class_data: Dict[str, Any],
    properties: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Generate an OpenAPI specification for a single class."""
    class_name = class_data['name']

    schema = build_class_openapi_schema(class_data, properties)

    openapi_spec = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{class_name}",
            "version": version_id,
            "description": f"OpenAPI specification for {tenant_slug}/{project_slug}/{version_id}/{class_name}"
        },
        "paths": {},
        "components": {
            "schemas": {
                class_name: schema
            }
        }
    }

    return openapi_spec
