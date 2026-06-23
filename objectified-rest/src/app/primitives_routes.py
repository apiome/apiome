"""
Primitives API Routes

Provides CRUD endpoints for managing primitive type definitions.
All endpoints are tenant-scoped and require authentication via JWT token or API key.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .import_ingestion import IngestionError, ingest_source
from .import_pipeline import VALID_SOURCE_KINDS, build_staged_import
from .models import (
    PrimitiveCreateRequest,
    PrimitiveImportRecord,
    PrimitiveImportRequest,
    PrimitiveImportStageRequest,
    PrimitiveImportStageResult,
    PrimitiveSchema,
    PrimitiveUpdateRequest,
    RegistryHealthResponse,
    UnresolvedRefPrimitive,
    UnresolvedRefsResponse,
)
from .primitives_parser import build_internal_ref_edges
from .primitives_resolver import build_ref_edges
from .primitives_scope import (
    ScopeViolationError,
    enforce_ref_scope,
    is_core_namespace,
    tenant_segment_of,
)
from .schema_validation import (
    REGISTRY_BASE_URL,
    SchemaValidationError,
    derive_base_uri,
    derive_draft,
    derive_schema_id,
    stamp_identity,
    validate_schema_document,
)

router = APIRouter(prefix="/v1/primitives", tags=["primitives"])

# Allowed import source shapes — must match the odb.primitive_imports CHECK
# constraint. Sourced from the pipeline so the staging and legacy paths agree.
VALID_IMPORT_SOURCE_KINDS = VALID_SOURCE_KINDS


def _schema_validation_http_error(errors: List[Dict[str, str]]) -> HTTPException:
    """Build the 422 response for a JSON Schema that fails draft 2020-12 validation (#3452).

    Args:
        errors: Field-level errors from ``schema_validation.validate_schema_document``.

    Returns:
        An ``HTTPException`` whose detail carries a human message plus the structured,
        field-level ``errors`` list so clients can highlight the offending keywords.
    """
    return HTTPException(
        status_code=422,
        detail={
            "message": "Schema is not a valid JSON Schema draft 2020-12 document",
            "errors": errors,
        },
    )


def _scope_violation_http_error(error: ScopeViolationError) -> HTTPException:
    """Build the 422 response for a ``$ref`` that crosses a forbidden scope boundary (#3453).

    Args:
        error: The raised scope violation, carrying its per-ref ``violations`` list.

    Returns:
        An ``HTTPException`` whose detail carries a human message plus the
        structured ``violations`` so clients can highlight the offending ``$ref``.
    """
    return HTTPException(
        status_code=422,
        detail={
            "message": error.message,
            "violations": error.violations,
        },
    )


def resolve_primitive_refs(
    schema: Dict[str, Any], *, base_uri: str, tenant_id: str
) -> List[Dict[str, str]]:
    """Resolve a primitive's relative ``$ref`` edges against the registry (#3456).

    Walks the schema's ``$ref`` values, resolves each against ``base_uri``, and marks
    each edge ``resolved`` / ``unresolved`` by looking the target ``$id`` up in the
    tenant's read scope (system-core ∪ tenant), so resolution honors scope (#3453).

    Args:
        schema: The identity-stamped JSON Schema document of the source primitive.
        base_uri: The source primitive's base URI (relative refs resolve against it).
        tenant_id: The caller's tenant id, scoping target lookups.

    Returns:
        The ``{relative_ref, resolved_target, status}`` edge list to persist on
        ``odb.primitives.refs``.
    """
    def _target_exists(absolute_uri: str) -> bool:
        return db.get_primitive_by_schema_id(absolute_uri, tenant_id) is not None

    return build_ref_edges(schema, base_uri=base_uri, target_exists=_target_exists)


def reconcile_dependents_for_target(schema_id: Optional[str], *, tenant_id: str) -> None:
    """Re-resolve the tenant's dangling edges that point at a now-existing target (#3457).

    The "fixing target clears on re-resolve" half of the acceptance criteria. When a
    primitive is created/imported (or repinned to a new ``$id``), any of the tenant's
    other primitives that held an *unresolved* edge aimed at that ``$id`` are cleared to
    ``resolved`` in place — no manual re-save of the dependent is required. Resolution is
    best-effort: a failure here must not fail the create/update that triggered it (the
    primitive is already persisted), so it is swallowed rather than surfaced.

    Args:
        schema_id: The ``$id`` of the just-persisted primitive (no-op when ``None``).
        tenant_id: The tenant whose dependents may reference the target.
    """
    if not schema_id:
        return
    try:
        db.mark_refs_resolved_to_target(tenant_id, schema_id)
    except Exception:
        # Reconciliation is a convenience pass over already-correct data; the dependent's
        # edge will also re-resolve the next time it is saved or re-resolved explicitly.
        pass


def resolve_primitive_identity(
    schema: Dict[str, Any],
    *,
    name: str,
    namespace: Optional[str],
    base_uri: Optional[str],
    tenant_slug: str,
    is_system: bool = False,
) -> Dict[str, Any]:
    """Validate a schema and derive its persisted JSON Schema 2020-12 identity (#3452).

    Shared by the create, update, and import paths so all three reject invalid schemas
    identically and compute a stable ``$id`` the same way.

    Args:
        schema: The candidate JSON Schema document.
        name: The primitive name (drives the derived ``$id`` leaf).
        namespace: Optional registry namespace path.
        base_uri: Optional explicit base URI (wins over ``namespace``).
        tenant_slug: The tenant slug (used for the default base URI).
        is_system: Whether the primitive is system-core. Core types are held to the
            stricter reference-direction rule (they may not ``$ref`` a tenant
            namespace). A namespace under ``std/`` is also treated as core (#3453).

    Returns:
        A dict with ``schema`` (identity-stamped copy), ``schema_id``, ``draft``,
        and ``base_uri``.

    Raises:
        SchemaValidationError: If ``schema`` is not a valid draft 2020-12 document,
            or is a boolean schema (valid per spec, but a primitive needs an object
            schema to carry a derived ``$id``).
        ScopeViolationError: If a ``$ref`` crosses a forbidden scope boundary
            (core→tenant, or tenant→other-tenant) (#3453).
    """
    if not isinstance(schema, dict):
        raise SchemaValidationError(
            [{"path": "(root)", "message": "Schema must be a JSON object", "keyword": "type"}]
        )

    errors = validate_schema_document(schema)
    if errors:
        raise SchemaValidationError(errors)

    resolved_base = derive_base_uri(namespace, base_uri, tenant_slug)
    schema_id = derive_schema_id(schema, name=name, base_uri=resolved_base)
    draft = derive_draft(schema)

    # Centralized scope/visibility enforcement (#3453): a core type may not reference a
    # tenant namespace, and a tenant type may not reference another tenant's namespace.
    # Core-ness comes from the explicit flag or a std/* placement; the owning tenant is
    # derived from the resolved base URI (e.g. .../types/tenant/acme/... -> tenant/acme).
    base_path = (
        resolved_base[len(REGISTRY_BASE_URL):]
        if resolved_base.startswith(REGISTRY_BASE_URL)
        else None
    )
    is_core = is_system or is_core_namespace(namespace) or is_core_namespace(base_path)
    own_tenant_segment = None if is_core else tenant_segment_of(base_path)
    enforce_ref_scope(
        schema,
        is_core=is_core,
        base_uri=resolved_base,
        own_tenant_segment=own_tenant_segment,
    )

    stamped = stamp_identity(schema, schema_id=schema_id, draft=draft)
    return {
        "schema": stamped,
        "schema_id": schema_id,
        "draft": draft,
        "base_uri": resolved_base,
    }


@router.get("/health", response_model=RegistryHealthResponse)
async def registry_health() -> RegistryHealthResponse:
    """
    Health/ping for the Primitives type-registry layer (#3450).

    Reports whether the registry's storage backend — the shared
    ``objectified-db`` connection backing ``odb.primitives`` — is reachable.
    Like the global ``/health`` endpoint this is intentionally anonymous so
    monitors can probe the registry layer without credentials; every data
    access endpoint below remains authenticated and tenant-scoped.

    Registered before ``GET /{tenant_slug}`` so the literal ``health`` path is
    matched here rather than being captured as a tenant slug.

    Returns:
        Registry health: overall ``status``, the ``objectified-db``
        ``connection`` state, and whether the ``odb.primitives`` storage table
        is present. On failure ``status`` is ``unhealthy`` and ``error`` carries
        the driver message; the endpoint itself still responds 200 so the probe
        is always reachable (mirrors the global ``/health`` contract).
    """
    try:
        probe = db.registry_ping()
        return RegistryHealthResponse(
            status="healthy",
            connection=probe["connection"],
            storage_present=probe["storage_present"],
        )
    except Exception as e:
        return RegistryHealthResponse(
            status="unhealthy",
            connection="disconnected",
            storage_present=False,
            error=str(e),
        )


def determine_category_from_schema(schema: Dict[str, Any]) -> str:
    """
    Determine the category for a JSON Schema definition.

    Handles schemas with:
    - type: Direct type specification
    - anyOf/oneOf: Union types, infers from const values
    - allOf: Intersection types
    - enum: Enumeration values
    - const: Single constant value

    Args:
        schema: The JSON Schema definition

    Returns:
        The category string (e.g., 'string', 'number', 'object')
    """
    # If type is explicitly set, use it
    if 'type' in schema:
        schema_type = schema['type']
        if isinstance(schema_type, str):
            return schema_type
        if isinstance(schema_type, list) and len(schema_type) > 0:
            return schema_type[0]

    # For anyOf/oneOf with const values, infer type from the first const
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            options = schema[key]
            if isinstance(options, list) and len(options) > 0:
                first_option = options[0]
                if isinstance(first_option, dict) and 'const' in first_option:
                    const_value = first_option['const']
                    if isinstance(const_value, str):
                        return 'string'
                    elif isinstance(const_value, bool):
                        return 'boolean'
                    elif isinstance(const_value, int):
                        return 'integer'
                    elif isinstance(const_value, float):
                        return 'number'

    # For enum, check the type of the first value
    if 'enum' in schema:
        enum_values = schema['enum']
        if isinstance(enum_values, list) and len(enum_values) > 0:
            first_value = enum_values[0]
            if isinstance(first_value, str):
                return 'string'
            elif isinstance(first_value, bool):
                return 'boolean'
            elif isinstance(first_value, int):
                return 'integer'
            elif isinstance(first_value, float):
                return 'number'

    # For const, check its type
    if 'const' in schema:
        const_value = schema['const']
        if isinstance(const_value, str):
            return 'string'
        elif isinstance(const_value, bool):
            return 'boolean'
        elif isinstance(const_value, int):
            return 'integer'
        elif isinstance(const_value, float):
            return 'number'

    # Default to object
    return 'object'


@router.get("/{tenant_slug}")
async def list_primitives(
    tenant_slug: str,
    category: Optional[str] = Query(None, description="Filter by category"),
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[PrimitiveSchema]:
    """
    List all primitives for a tenant.

    Supports authentication via:
    - JWT token in Authorization header (Bearer token)
    - API key in X-API-Key header

    Args:
        tenant_slug: The tenant slug
        category: Optional category filter
        auth_data: Authentication data (injected by dependency)

    Returns:
        List of primitives for the tenant
    """
    # Get primitives
    primitives = db.get_primitives_for_tenant(auth_data['tenant_id'], category)

    return [PrimitiveSchema(**p) for p in primitives]


@router.get("/{tenant_slug}/imports")
async def list_primitive_imports(
    tenant_slug: str,
    limit: int = Query(50, ge=1, le=500, description="Max number of records to return"),
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[PrimitiveImportRecord]:
    """
    List primitive import provenance records for a tenant, newest first (#3448).

    Registered before GET /{tenant_slug}/{primitive_id} so the literal `imports`
    path is not captured as a primitive id.

    Args:
        tenant_slug: The tenant slug
        limit: Maximum number of records to return
        auth_data: Authentication data (injected by dependency)

    Returns:
        The tenant's import provenance records.
    """
    records = db.get_primitive_imports(auth_data['tenant_id'], limit)
    return [PrimitiveImportRecord(**r) for r in records]


@router.get("/{tenant_slug}/imports/{import_id}")
async def get_primitive_import(
    tenant_slug: str,
    import_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PrimitiveImportRecord:
    """
    Get a single primitive import provenance record, including its report JSON (#3448).

    Args:
        tenant_slug: The tenant slug
        import_id: The import provenance record id
        auth_data: Authentication data (injected by dependency)

    Returns:
        The provenance record with its full options/report payload.
    """
    record = db.get_primitive_import_by_id(import_id, auth_data['tenant_id'])
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Import record not found: {import_id}"
        )
    return PrimitiveImportRecord(**record)


@router.get("/{tenant_slug}/unresolved", response_model=UnresolvedRefsResponse)
async def list_unresolved_refs(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> UnresolvedRefsResponse:
    """Report the tenant's unresolved relative-``$ref`` edges and counts (#3457).

    A primitive's relative ``$ref`` values are resolved to registry edges on save/import
    and flagged ``resolved`` / ``unresolved`` (#3456). This endpoint aggregates the
    unresolved ones: the two top-level counts feed the registry coverage/stats KPIs
    (#3454), and ``primitives`` is the per-primitive breakdown — each with only its
    unresolved edges — the resolver UI lists (#3470).

    Registered before ``GET /{tenant_slug}/{primitive_id}`` so the literal ``unresolved``
    path is matched here rather than being captured as a primitive id.

    Args:
        tenant_slug: The tenant slug.
        auth_data: Authentication data (injected by dependency).

    Returns:
        ``UnresolvedRefsResponse`` with the total unresolved-edge count, the number of
        affected primitives, and the per-primitive unresolved-edge breakdown.
    """
    tenant_id = auth_data['tenant_id']
    counts = db.count_unresolved_refs(tenant_id)
    rows = db.get_primitives_with_unresolved_refs(tenant_id)

    primitives: List[UnresolvedRefPrimitive] = []
    for row in rows:
        unresolved = [
            edge for edge in (row.get('refs') or [])
            if edge.get('status') == 'unresolved'
        ]
        primitives.append(
            UnresolvedRefPrimitive(
                id=str(row['id']),
                name=row['name'],
                schema_id=row.get('schema_id'),
                namespace=row.get('namespace'),
                base_uri=row.get('base_uri'),
                unresolved_count=len(unresolved),
                unresolved_refs=unresolved,
            )
        )

    return UnresolvedRefsResponse(
        unresolved_ref_count=counts['unresolved_ref_count'],
        affected_primitive_count=counts['affected_primitive_count'],
        primitives=primitives,
    )


@router.get("/{tenant_slug}/{primitive_id}")
async def get_primitive(
    tenant_slug: str,
    primitive_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PrimitiveSchema:
    """
    Get a specific primitive by ID.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        primitive_id: The primitive ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        The primitive details
    """
    # Get primitive
    primitive = db.get_primitive_by_id(primitive_id, auth_data['tenant_id'])

    if not primitive:
        raise HTTPException(
            status_code=404,
            detail=f"Primitive not found: {primitive_id}"
        )

    return PrimitiveSchema(**primitive)


@router.post("/{tenant_slug}")
async def create_primitive(
    tenant_slug: str,
    request: PrimitiveCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PrimitiveSchema:
    """
    Create a new primitive.

    Supports authentication via JWT token or API key.
    When using JWT, the created_by field will be set to the authenticated user.

    Args:
        tenant_slug: The tenant slug
        request: Primitive creation data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The created primitive
    """
    # Strict server-side draft 2020-12 validation + stable $id derivation (#3452).
    try:
        identity = resolve_primitive_identity(
            request.schema,
            name=request.name,
            namespace=request.namespace,
            base_uri=request.base_uri,
            tenant_slug=tenant_slug,
        )
    except SchemaValidationError as e:
        raise _schema_validation_http_error(e.errors)
    except ScopeViolationError as e:
        raise _scope_violation_http_error(e)

    # Resolve relative $ref edges against the registry and persist them (#3456).
    refs = resolve_primitive_refs(
        identity['schema'], base_uri=identity['base_uri'], tenant_id=auth_data['tenant_id']
    )

    try:
        # Get user_id from auth data (will be None for API key auth)
        created_by = get_authenticated_user_id(auth_data)

        # Create primitive
        primitive = db.create_primitive(
            tenant_id=auth_data['tenant_id'],
            name=request.name,
            category=request.category,
            schema=identity['schema'],
            description=request.description,
            tags=request.tags,
            created_by=created_by,
            schema_id=identity['schema_id'],
            draft=identity['draft'],
            namespace=request.namespace,
            base_uri=identity['base_uri'],
            refs=refs,
        )

        # This new type may be the target of other primitives' dangling refs — clear
        # their unresolved flag now that it exists (#3457).
        reconcile_dependents_for_target(
            identity['schema_id'], tenant_id=auth_data['tenant_id']
        )

        return PrimitiveSchema(**primitive)
    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"A primitive with name '{request.name}' already exists in category '{request.category}'"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant_slug}/{primitive_id}")
async def update_primitive(
    tenant_slug: str,
    primitive_id: str,
    request: PrimitiveUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PrimitiveSchema:
    """
    Update an existing primitive.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        primitive_id: The primitive ID
        request: Primitive update data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The updated primitive
    """
    # Check if primitive exists
    existing = db.get_primitive_by_id(primitive_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Primitive not found: {primitive_id}"
        )

    # Prevent updating system primitives
    if existing.get('is_system'):
        raise HTTPException(
            status_code=403,
            detail="Cannot update system primitives"
        )

    # Build updates dict from request
    updates = {}
    if request.name is not None:
        updates['name'] = request.name
    if request.description is not None:
        updates['description'] = request.description
    if request.category is not None:
        updates['category'] = request.category
    if request.tags is not None:
        updates['tags'] = request.tags
    if request.enabled is not None:
        updates['enabled'] = request.enabled
    if request.namespace is not None:
        updates['namespace'] = request.namespace

    # Re-validate and re-derive the JSON Schema 2020-12 identity whenever the schema or
    # its registry placement changes (#3452). Identity is computed against the effective
    # (post-update) name and namespace/base_uri, falling back to the stored values.
    identity_touched = (
        request.schema is not None
        or request.namespace is not None
        or request.base_uri is not None
        or request.name is not None
    )
    if identity_touched:
        schema_doc = request.schema if request.schema is not None else existing['schema']
        effective_name = request.name if request.name is not None else existing['name']
        effective_namespace = (
            request.namespace if request.namespace is not None else existing.get('namespace')
        )
        effective_base_uri = (
            request.base_uri if request.base_uri is not None else existing.get('base_uri')
        )
        try:
            identity = resolve_primitive_identity(
                schema_doc,
                name=effective_name,
                namespace=effective_namespace,
                base_uri=effective_base_uri,
                tenant_slug=tenant_slug,
            )
        except SchemaValidationError as e:
            raise _schema_validation_http_error(e.errors)
        except ScopeViolationError as e:
            raise _scope_violation_http_error(e)
        updates['schema'] = identity['schema']
        updates['schema_id'] = identity['schema_id']
        updates['draft'] = identity['draft']
        updates['base_uri'] = identity['base_uri']
        # Re-resolve relative $ref edges whenever the schema or its base changes (#3456).
        updates['refs'] = resolve_primitive_refs(
            identity['schema'], base_uri=identity['base_uri'], tenant_id=auth_data['tenant_id']
        )

    try:
        # Update primitive
        primitive = db.update_primitive(
            primitive_id,
            auth_data['tenant_id'],
            updates
        )

        if not primitive:
            raise HTTPException(
                status_code=404,
                detail=f"Primitive not found: {primitive_id}"
            )

        # If the schema/placement changed, the (possibly new) $id may now satisfy other
        # primitives' dangling refs — clear their unresolved flag (#3457).
        if identity_touched:
            reconcile_dependents_for_target(
                updates.get('schema_id'), tenant_id=auth_data['tenant_id']
            )

        return PrimitiveSchema(**primitive)
    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="A primitive with that name already exists in the category"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant_slug}/{primitive_id}")
async def delete_primitive(
    tenant_slug: str,
    primitive_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, str]:
    """
    Delete a primitive (soft delete).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        primitive_id: The primitive ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Success message
    """
    # Check if primitive exists
    existing = db.get_primitive_by_id(primitive_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Primitive not found: {primitive_id}"
        )

    # Prevent deleting system primitives
    if existing.get('is_system'):
        raise HTTPException(
            status_code=403,
            detail="Cannot delete system primitives"
        )

    # Delete primitive
    success = db.delete_primitive(primitive_id, auth_data['tenant_id'])

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete primitive"
        )

    return {"message": "Primitive deleted successfully"}


@router.post("/{tenant_slug}/import")
async def import_primitives(
    tenant_slug: str,
    request: PrimitiveImportRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, Any]:
    """
    Import primitives from a JSON Schema document.

    Extracts type definitions from JSON Schema's $defs or definitions
    and creates primitives from them.

    Supports authentication via JWT token or API key.
    When using JWT, the created_by field will be set to the authenticated user.

    Args:
        tenant_slug: The tenant slug
        request: Import request with JSON Schema document
        auth_data: Authentication data (injected by dependency)

    Returns:
        Summary of imported primitives plus the id of the recorded provenance row.
    """
    # Validate the declared source shape against the persisted CHECK constraint.
    if request.source_kind not in VALID_IMPORT_SOURCE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid source_kind '{request.source_kind}'. "
                f"Expected one of: {', '.join(sorted(VALID_IMPORT_SOURCE_KINDS))}"
            )
        )

    # Extract definitions from schema
    definitions = {}

    # Check for $defs (JSON Schema 2020-12)
    if '$defs' in request.schema:
        definitions.update(request.schema['$defs'])

    # Check for definitions (older JSON Schema versions)
    if 'definitions' in request.schema:
        definitions.update(request.schema['definitions'])

    if not definitions:
        raise HTTPException(
            status_code=400,
            detail="No definitions found in JSON Schema. Schema must contain $defs or definitions."
        )

    # Filter definitions if specific ones are requested
    if not request.import_all and request.selected_definitions:
        definitions = {
            k: v for k, v in definitions.items()
            if k in request.selected_definitions
        }

    if not definitions:
        raise HTTPException(
            status_code=400,
            detail="No matching definitions found to import"
        )

    # Get user_id from auth data (will be None for API key auth)
    created_by = get_authenticated_user_id(auth_data)

    # Import each definition as a primitive
    imported = []
    skipped = []
    errors = []

    for def_name, def_schema in definitions.items():
        # Each imported definition goes through the SAME draft 2020-12 validator,
        # $id derivation, and scope enforcement as create/update (#3452, #3453). An
        # invalid or scope-violating definition is rejected with its details and
        # skipped; valid ones are not blocked by it.
        try:
            identity = resolve_primitive_identity(
                def_schema,
                name=def_name,
                namespace=request.target_namespace,
                base_uri=None,
                tenant_slug=tenant_slug,
            )
        except SchemaValidationError as e:
            errors.append({"name": def_name, "error": "invalid_schema", "details": e.errors})
            continue
        except ScopeViolationError as e:
            errors.append({"name": def_name, "error": "scope_violation", "details": e.violations})
            continue

        # Resolve relative $ref edges for the imported definition (#3456), then append
        # its intra-document #/$defs refs as 'internal' edges (#3461) so the committed
        # row carries them for the rewrite stage (#3463). Both kinds share the refs
        # JSONB column; the 'internal' status keeps them out of unresolved aggregates.
        refs = resolve_primitive_refs(
            identity['schema'], base_uri=identity['base_uri'], tenant_id=auth_data['tenant_id']
        )
        refs = refs + build_internal_ref_edges(identity['schema'])

        try:
            # Determine category from schema
            schema_type = determine_category_from_schema(def_schema)

            # Create primitive - the full (identity-stamped) schema with all metadata is
            # stored. source='imported' marks its provenance on odb.primitives (#3448).
            primitive = db.create_primitive(
                tenant_id=auth_data['tenant_id'],
                name=def_name,
                category=schema_type,
                schema=identity['schema'],  # Full schema (x-license, $comment, examples, …) + stamped $id.
                description=def_schema.get('description'),
                tags=def_schema.get('tags', []),
                created_by=created_by,
                source='imported',
                schema_id=identity['schema_id'],
                draft=identity['draft'],
                namespace=request.target_namespace,
                base_uri=identity['base_uri'],
                refs=refs,
            )
            imported.append(primitive['name'])
            # Each imported type may be the target of an earlier definition's ref (within
            # this same batch or a prior import) — clear those unresolved flags (#3457).
            reconcile_dependents_for_target(
                identity['schema_id'], tenant_id=auth_data['tenant_id']
            )
        except Exception as e:
            if "unique constraint" in str(e).lower():
                skipped.append(def_name)
            else:
                errors.append({"name": def_name, "error": str(e)})

    # Build the auditable report and persist a provenance record (#3448).
    report = {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_imported": len(imported),
        "total_skipped": len(skipped),
        "total_errors": len(errors),
    }
    options = {
        "import_all": request.import_all,
        "selected_definitions": request.selected_definitions,
    }

    import_id = None
    try:
        import_record = db.create_primitive_import(
            tenant_id=auth_data['tenant_id'],
            report=report,
            source_kind=request.source_kind,
            source_label=request.source_label,
            target_namespace=request.target_namespace,
            options=options,
            imported_count=len(imported),
            skipped_count=len(skipped),
            error_count=len(errors),
            imported_by=created_by,
        )
        import_id = str(import_record['id'])
    except Exception as e:
        # Provenance is best-effort: a failure here must not lose a successful import,
        # but it is surfaced so the audit gap is visible.
        errors.append({"name": "_provenance", "error": f"Failed to record import provenance: {e}"})

    return {
        "message": "Import completed",
        "import_id": import_id,
        **report,
    }


@router.post("/{tenant_slug}/import/stage", response_model=PrimitiveImportStageResult)
async def stage_import(
    tenant_slug: str,
    request: PrimitiveImportStageRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> PrimitiveImportStageResult:
    """Stage an import through the unified pipeline (#3460).

    The single orchestration path for all source kinds and intake methods: it
    fetches the source (paste / file / url / git), parses it (JSON or YAML),
    detects the candidate types it carries (json-schema / type-def-bundle /
    openapi), records a provenance row on ``odb.primitive_imports`` marked
    ``staged``, and returns the staged candidates.

    Nothing is committed to the registry here — parsing into discrete types
    (#3461/#3462), ``$ref`` rewrite (#3463), and conflict/dedupe review (#3464)
    operate on the staged result in the subsequent pipeline stages. The legacy
    ``POST /{tenant_slug}/import`` (paste, commit) remains supported alongside it.

    Args:
        tenant_slug: The tenant slug.
        request: The staging request (source kind/method + a method locator).
        auth_data: Authentication data (injected by dependency).

    Returns:
        The staged result: detected candidates plus the recorded ``import_id``.

    Raises:
        HTTPException: 400 for an invalid source kind/method or missing locator,
            422 for an unparseable source, 502 for a fetch failure.
    """
    if request.source_kind not in VALID_IMPORT_SOURCE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid source_kind '{request.source_kind}'. "
                f"Expected one of: {', '.join(sorted(VALID_IMPORT_SOURCE_KINDS))}"
            )
        )

    # Ingest (fetch + parse) the source document for the declared method. A bad
    # locator or empty/invalid document is a 400/422; a remote fetch failure is a
    # 502 (the source, not the request, is at fault).
    git_locator = request.git.model_dump() if request.git is not None else None
    try:
        ingested = ingest_source(
            request.source_method,
            content=request.content,
            url=request.url,
            git=git_locator,
            source_label=request.source_label,
        )
    except IngestionError as e:
        # A network/remote failure is a 502; a client-side locator/parse problem is a 400.
        is_remote = request.source_method in ("url", "git") and (
            "fetch" in e.message.lower() or "http" in e.message.lower()
        )
        raise HTTPException(status_code=502 if is_remote else 400, detail=e.message)

    # Detect candidate types and assemble the staged result (pure; no commit).
    try:
        staged = build_staged_import(
            ingested.document,
            source_kind=request.source_kind,
            source_method=request.source_method,
            source_label=ingested.resolved_label,
            target_namespace=request.target_namespace,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Record an auditable provenance row for the staged import (#3448 reuse). The
    # report carries the staged candidates and warnings; counts stay zero because
    # nothing was committed. Best-effort: a record failure must not lose the
    # staged result, but it is surfaced as a warning so the audit gap is visible.
    created_by = get_authenticated_user_id(auth_data)
    import_id = None
    try:
        import_record = db.create_primitive_import(
            tenant_id=auth_data['tenant_id'],
            report=staged.report(),
            source_kind=staged.source_kind,
            source_label=staged.source_label,
            target_namespace=staged.target_namespace,
            options={"source_method": staged.source_method, "staged": True},
            imported_count=0,
            skipped_count=0,
            error_count=0,
            imported_by=created_by,
        )
        import_id = str(import_record['id'])
    except Exception as e:
        staged.warnings.append(f"Failed to record import provenance: {e}")

    return PrimitiveImportStageResult(
        import_id=import_id,
        status=staged.status,
        source_kind=staged.source_kind,
        source_method=staged.source_method,
        source_label=staged.source_label,
        target_namespace=staged.target_namespace,
        detected_count=staged.detected_count,
        candidates=[c.as_dict() for c in staged.candidates],
        warnings=staged.warnings,
    )
