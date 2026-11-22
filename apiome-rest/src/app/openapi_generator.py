import json
from typing import Dict, Any, List, Optional, DefaultDict
from collections import defaultdict
from .openapi_project_tags import TAG_TAXONOMY_METADATA_KEY, build_document_tags, read_stored_tags
from .paths_generator import generate_paths_for_openapi, is_openapi_32
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


def _clean_description(data: Dict[str, Any], column: Any = None) -> None:
    """Settle a property's description.

    The ``class_properties.description`` column wins over a description inside the property's
    JSON. Without either, the JSON's ``title`` is used; a null description is removed.

    Args:
        data: The property schema being built; changed in place.
        column: The property row's ``description`` column, if the row carries one.
    """
    if isinstance(column, str) and column:
        data['description'] = column
        return
    if data.get('description') is None:
        data.pop('description', None)
        if data.get('title'):
            data['description'] = data['title']


def _required_on_parent(prop: Dict[str, Any]) -> bool:
    """Report whether a property's own stored JSON marks it required on its parent.

    Read from the stored JSON, not from the built schema: an object property with nested children
    has its ``required`` replaced by the list of its required children.
    """
    data = parse_json_field(prop.get('data'))
    return isinstance(data, dict) and data.get('required') is True


def _collect_children(
    children: List[Dict[str, Any]], children_index: DefaultDict[Optional[str], List[Dict[str, Any]]]
) -> tuple:
    """Build the schemas of a property's children.

    Returns:
        ``(properties, required)``: the child schemas by name, and the names of the children
        that are required on their parent.
    """
    nested_props: Dict[str, Any] = {}
    nested_required: List[str] = []
    for child in children:
        child_schema = _build_property_schema(child, children_index)
        if child_schema.get('required') is True or _required_on_parent(child):
            nested_required.append(child['name'])
        if isinstance(child_schema.get('required'), bool):
            child_schema.pop('required', None)
        nested_props[child['name']] = child_schema
    return nested_props, nested_required


def _build_property_schema(prop: Dict[str, Any], children_index: DefaultDict[Optional[str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Recursively build property schema including inline/nested children."""
    prop_data_raw = prop.get('data')
    prop_data = parse_json_field(prop_data_raw) or {}

    # Work on a shallow copy to avoid mutating input
    prop_schema: Dict[str, Any] = dict(prop_data)
    # Exclude internal DB id from the OpenAPI property definition
    prop_schema.pop('id', None)

    _clean_description(prop_schema, prop.get('description'))

    # Inline object children if this is an object without $ref
    if prop_schema.get('type') == 'object' and '$ref' not in prop_schema:
        children = children_index.get(prop.get('id'), [])
        if children:
            nested_props, nested_required = _collect_children(children, children_index)
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
            nested_props, nested_required = _collect_children(children, children_index)
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

    # A composed schema (allOf / anyOf / oneOf) is not made an object: its branches say what it
    # is, and ``type: object`` beside ``oneOf`` of scalars would reject every value. The stored
    # schema's own ``type`` is kept either way.
    composed = any(schema_without_props.get(key) for key in ("allOf", "anyOf", "oneOf"))
    schema: Dict[str, Any] = {
        **({} if composed else {"type": "object"}),
        "title": class_name,
        **({"description": class_data['description']} if class_data.get('description') else {}),
        **schema_without_props,
        "properties": {},
    }

    # Build children index and process only top-level properties (parent_id is null)
    children_index = _build_children_index(properties)
    schema['properties'], required = _collect_children(children_index.get(None, []), children_index)

    # Add required if any
    if required:
        schema['required'] = required

    # Clean up empty properties
    if not schema['properties']:
        schema.pop('properties', None)

    return schema


def _load_paths_for_version(version_id: str) -> List[Dict[str, Any]]:
    """Load all paths with full operation details for a version.

    Six statements at most, whatever the size of the spec (DBP-1.6, #7189): see
    :meth:`app.database.Database.load_paths_for_version`.

    Args:
        version_id: The revision (``versions.id``).

    Returns:
        The paths in the shape :func:`app.paths_generator.generate_paths_for_openapi` reads;
        empty when the database is not available.
    """
    # Import db here to avoid circular imports and allow tests to run
    try:
        from .database import db
    except ImportError:
        return []

    if db is None:
        return []

    return db.load_paths_for_version(version_id)


def _security_schemes_from_rows(scheme_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build ``components.securitySchemes`` from ``version_security_scheme`` rows.

    Every scheme type a version can store is written: ``apiKey``, ``http``, ``oauth2``,
    ``openIdConnect``, ``mutualTLS`` and ``custom`` (whose stored JSON is the scheme). A row that
    lacks what its type requires (an ``http`` row with no scheme, an ``oauth2`` row with no flows,
    an ``openIdConnect`` row with no URL) is left out, since the scheme would not be valid.

    Args:
        scheme_rows: Rows with ``scheme_name``, ``scheme_type``, ``in_location``, ``param_name``,
            ``http_scheme``, ``description`` and ``data``.

    Returns:
        The schemes by name, in row order.
    """
    security_schemes: Dict[str, Any] = {}
    for row in scheme_rows:
        name = row["scheme_name"]
        scheme_type = row.get("scheme_type")
        data = parse_json_field(row.get("data"))
        data = data if isinstance(data, dict) else {}
        described = {"description": row["description"]} if row.get("description") else {}
        if scheme_type == "apiKey":
            security_schemes[name] = {
                "type": "apiKey",
                "name": row.get("param_name") or name,
                "in": row.get("in_location") or "header",
                **described,
            }
        elif scheme_type == "http" and row.get("http_scheme"):
            scheme: Dict[str, Any] = {"type": "http", "scheme": row["http_scheme"], **described}
            if data.get("bearerFormat"):
                scheme["bearerFormat"] = data["bearerFormat"]
            security_schemes[name] = scheme
        elif scheme_type == "oauth2":
            flows = data.get("flows")
            if isinstance(flows, dict) and flows:
                security_schemes[name] = {"type": "oauth2", "flows": flows, **described}
        elif scheme_type == "openIdConnect":
            url = data.get("openIdConnectUrl")
            if isinstance(url, str) and url.strip():
                security_schemes[name] = {
                    "type": "openIdConnect",
                    "openIdConnectUrl": url.strip(),
                    **described,
                }
        elif scheme_type == "mutualTLS":
            security_schemes[name] = {"type": "mutualTLS", **described}
        elif scheme_type == "custom":
            declared = data.get("type")
            scheme = {"type": declared.strip() if isinstance(declared, str) and declared.strip() else "apiKey"}
            description = row.get("description") or data.get("description")
            if description:
                scheme["description"] = description
            for key, value in data.items():
                if key not in ("type", "description") and value is not None:
                    scheme[key] = value
            security_schemes[name] = scheme
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

    # The tag list is written as the document's ``tags`` (#7048), not copied into ``info``.
    merged_keys = {
        "summary", "termsOfService", "terms_of_service", "contact", "license", TAG_TAXONOMY_METADATA_KEY,
    }
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
    openapi_version: str = "3.1.0",
    include_private: bool = False,
) -> Dict[str, Any]:
    """Generate a complete OpenAPI specification for all classes in a version.

    ``openapi_version`` (default ``3.1.0``) is the version the document declares. ``3.2.0`` writes
    the OpenAPI 3.2 constructs natively — ``query`` / ``additionalOperations``, ``itemSchema``,
    ``in: querystring`` parameters and the tags' ``summary`` / ``parent`` / ``kind`` — where 3.1
    carries them on ``x-apiome-*`` stashes or leaves them out (#7048, see
    :mod:`app.paths_generator`).

    ``include_private`` (default ``False``) keeps the operations marked ``x-private``, each
    carrying ``x-private: true``. The public document leaves them out; the document workspace
    members read (COA-5.13, #7089) keeps them.
    """
    is32 = is_openapi_32(openapi_version)

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
    # Operations marked x-private are hidden from Swagger unless include_private asks for them
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
        paths = generate_paths_for_openapi(
            resolved_paths_data,
            options={"exclude_private": not include_private, "openapi_version": openapi_version},
        )

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
        "openapi": openapi_version.strip() if is32 else "3.1.0",
        "info": info_block,
        "paths": paths,
        "components": components,
    }
    if servers_list:
        openapi_spec["servers"] = servers_list

    meta_parsed = parse_json_field(project_metadata)
    document_tags = build_document_tags(read_stored_tags(meta_parsed), is32)
    if document_tags:
        openapi_spec["tags"] = document_tags
    if isinstance(meta_parsed, dict):
        meta_parsed = {k: v for k, v in meta_parsed.items() if k != TAG_TAXONOMY_METADATA_KEY}
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
