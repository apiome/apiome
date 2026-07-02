import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import bcrypt
import numpy as np
import psycopg2
from psycopg2.extras import Json, RealDictCursor

from .config import WEBHOOK_MAX_DELIVERY_ATTEMPTS, settings
from .jsonschema_generator import generate_class_jsonschema_spec
from .push_webhook_crypto import encrypt_signing_secret
from .revision_deprecation import (
    coerce_metadata,
    effective_sunset_string,
    is_uuid_string,
    successor_revision_id_from_metadata,
)
from .revision_lifecycle import prepare_version_metadata_update, sql_effective_lifecycle_expr

_logger = logging.getLogger(__name__)


def _deep_equal(a: Any, b: Any) -> bool:
    """Recursive equality for JSON-like values."""
    if type(a) != type(b):
        return False
    if a is None or isinstance(a, (str, int, float, bool)):
        return a == b
    if isinstance(a, dict):
        if set(a) != set(b):
            return False
        return all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_deep_equal(x, y) for x, y in zip(a, b))
    return False


def format_mcp_version_tag(discovered_at: datetime) -> str:
    """Build the human-readable UTC date/time tag for an MCP version snapshot (#3671).

    Produces a compact, minute-precision ISO-8601-style label such as ``2026-06-26T14:03Z``
    from the moment a discovery ran. The value is normalized to UTC so the tag is stable and
    comparable regardless of the server clock's timezone, matching the SQL backfill format in
    migration V131 (``YYYY-MM-DD"T"HH24:MI"Z"`` over ``discovered_at AT TIME ZONE 'UTC'``).

    Args:
        discovered_at: When the discovery that produced the snapshot ran. A naive datetime is
            assumed to already be UTC; an aware one is converted to UTC.

    Returns:
        The base date/time tag (without any collision suffix).
    """
    dt = discovered_at if discovered_at.tzinfo is not None else discovered_at.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


class StaleHeadPushError(Exception):
    """Branch tip changed after the client's base revision check (optimistic lock, #2566)."""

    def __init__(self, current_tip_revision_id: str):
        self.current_tip_revision_id = current_tip_revision_id
        super().__init__("stale head")


class BranchNotFoundError(Exception):
    """Branch row disappeared between head-resolution and the transactional FOR UPDATE lock."""

    def __init__(self, branch_id: str):
        self.branch_id = branch_id
        super().__init__(f"branch not found: {branch_id}")


class BranchDefaultConflictError(Exception):
    """Concurrent default-branch promotion conflicted with unique default-per-project invariant."""


def _compute_delta(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute top-level delta: keys added, removed, or changed.
    Removed keys appear as key: None. If nothing changed, returns {}.
    """
    delta = {}
    all_keys = set(old) | set(new)
    for k in all_keys:
        if k not in new:
            delta[k] = None
        elif k not in old or not _deep_equal(old[k], new[k]):
            delta[k] = new[k]
    return delta


class Database:
    """Database connection and query manager."""

    def __init__(self):
        self.connection = None

    def connect(self):
        """Establish database connection."""
        if not self.connection or self.connection.closed:
            try:
                self.connection = psycopg2.connect(
                    settings.effective_database_url,
                    cursor_factory=RealDictCursor,
                )
            except psycopg2.OperationalError as e:
                err_s = str(e).lower()
                if "does not exist" in err_s and "database" in err_s:
                    db_name = settings.postgres_db
                    raise psycopg2.OperationalError(
                        f"{e}\n\n"
                        "PostgreSQL has no database with that name yet. Create it, then apply migrations "
                        "from apiome-db/scripts (see apiome-db/docs/README.md). Example:\n"
                        f"  psql -U {settings.postgres_user} -h {settings.postgres_host} "
                        f"-p {settings.postgres_port} -c 'CREATE DATABASE {db_name};'\n"
                        "If you use DATABASE_URL, the database name is the path segment after the last '/'."
                    ) from e
                raise
        return self.connection

    def close(self):
        """Close database connection."""
        if self.connection and not self.connection.closed:
            self.connection.close()

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results.

        Commits on success so the shared connection returns to IDLE. Leaving
        reads in "idle in transaction" holds locks, blocks VACUUM, and causes
        subsequent writers that toggle ``conn.autocommit`` to crash with
        ``set_session cannot be used inside a transaction``.
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
            conn.commit()
            return rows
        except Exception as e:
            conn.rollback()
            raise e

    def _begin_tx(self, conn) -> bool:
        """Flush any dangling transaction, then enter manual-commit mode.

        Psycopg2 implements ``conn.autocommit = X`` via ``set_session``, which
        raises when the connection is not IDLE. Any prior statement on the
        shared connection (direct ``conn.cursor()`` usage that didn't commit)
        can leave us in ``INTRANS`` or ``INERROR``. Rolling back first is safe
        and idempotent and restores a clean starting point for the new tx.

        Returns the previous autocommit value so the caller can restore it
        in ``finally``.
        """
        if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            conn.rollback()
        prev = conn.autocommit
        conn.autocommit = False
        return prev

    def get_version_by_slugs(self, tenant_slug: str, project_slug: str, version_id: str) -> Optional[Dict[str, Any]]:
        """Get version information by tenant, project, and version slugs."""
        query = """
            SELECT v.id, v.version_id, v.visibility, v.published,
                   p.description as project_description, p.metadata as project_metadata,
                   v.metadata
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            JOIN apiome.tenants t ON p.tenant_id = t.id
            WHERE t.slug = %s
              AND p.slug = %s
              AND v.version_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND t.deleted_at IS NULL
        """
        results = self.execute_query(query, (tenant_slug, project_slug, version_id))
        return results[0] if results else None

    def get_classes_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all classes for a specific version."""
        query = """
            SELECT id, version_id, name, description, schema, enabled
            FROM apiome.classes
            WHERE version_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """
        return self.execute_query(query, (version_id,))

    def get_class_by_name(self, version_id: str, class_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific class by name for a version."""
        query = """
            SELECT id, version_id, name, description, schema, enabled
            FROM apiome.classes
            WHERE version_id = %s AND name = %s AND deleted_at IS NULL
        """
        results = self.execute_query(query, (version_id, class_name))
        return results[0] if results else None

    def get_properties_for_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get all properties for a specific class."""
        query = """
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   cp.primitive_id, cp.primitive_ref,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM apiome.class_properties cp
            LEFT JOIN apiome.properties p ON cp.property_id = p.id
            WHERE cp.class_id = %s
            ORDER BY cp.parent_id NULLS FIRST, cp.name ASC
        """
        return self.execute_query(query, (class_id,))

    def get_classes_with_properties_and_tags_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all classes for a version with their properties and tags in bulk."""
        # Query 1: Get all classes for the version
        classes_query = """
            SELECT id, version_id, name, description, schema, enabled, canvas_metadata, created_at, updated_at
            FROM apiome.classes
            WHERE version_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """
        classes = self.execute_query(classes_query, (version_id,))

        if not classes:
            return []

        class_ids = [c['id'] for c in classes]

        if not class_ids:
            return []

        # Query 2: Get all properties for all classes
        # Use IN clause with tuple for proper UUID handling
        placeholders = ','.join(['%s'] * len(class_ids))
        properties_query = f"""
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   cp.primitive_id, cp.primitive_ref,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM apiome.class_properties cp
            LEFT JOIN apiome.properties p ON cp.property_id = p.id
            WHERE cp.class_id IN ({placeholders})
            ORDER BY cp.class_id, cp.parent_id NULLS FIRST, cp.name ASC
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(properties_query, tuple(class_ids))
                properties = cursor.fetchall()
        except Exception as e:
            conn.rollback()
            raise e

        # Query 3: Get all tags for all classes
        tags_query = f"""
            SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
                   t.name as tag_name, t.color as tag_color, t.description as tag_description,
                   t.project_id
            FROM apiome.class_tags ct
            JOIN apiome.tags t ON ct.tag_id = t.id
            WHERE ct.class_id IN ({placeholders})
            ORDER BY ct.class_id, t.name ASC
        """
        try:
            with conn.cursor() as cursor:
                cursor.execute(tags_query, tuple(class_ids))
                tags = cursor.fetchall()
        except Exception as e:
            conn.rollback()
            raise e

        # Group properties and tags by class_id
        properties_by_class = {}
        for prop in properties:
            class_id = prop['class_id']
            if class_id not in properties_by_class:
                properties_by_class[class_id] = []
            properties_by_class[class_id].append(prop)

        tags_by_class = {}
        for tag in tags:
            class_id = tag['class_id']
            if class_id not in tags_by_class:
                tags_by_class[class_id] = []
            tags_by_class[class_id].append(tag)

        # Combine classes with their properties and tags
        result = []
        for cls in classes:
            result.append({
                **cls,
                'properties': properties_by_class.get(cls['id'], []),
                'tags': tags_by_class.get(cls['id'], [])
            })

        return result

    def get_class_with_properties_and_tags(self, class_id: str) -> Optional[Dict[str, Any]]:
        """Get a single class with its properties and tags."""
        # Query 1: Get the class
        class_query = """
            SELECT id, version_id, name, description, schema, enabled, canvas_metadata, created_at, updated_at
            FROM apiome.classes
            WHERE id = %s AND deleted_at IS NULL
        """
        classes = self.execute_query(class_query, (class_id,))

        if not classes:
            return None

        cls = classes[0]

        # Query 2: Get all properties for this class
        properties_query = """
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   cp.primitive_id, cp.primitive_ref,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM apiome.class_properties cp
            LEFT JOIN apiome.properties p ON cp.property_id = p.id
            WHERE cp.class_id = %s
            ORDER BY cp.parent_id NULLS FIRST, cp.name ASC
        """
        properties = self.execute_query(properties_query, (class_id,))

        # Query 3: Get all tags for this class
        tags_query = """
            SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
                   t.name as tag_name, t.color as tag_color, t.description as tag_description,
                   t.project_id
            FROM apiome.class_tags ct
            JOIN apiome.tags t ON ct.tag_id = t.id
            WHERE ct.class_id = %s
            ORDER BY t.name ASC
        """
        tags = self.execute_query(tags_query, (class_id,))

        return {
            **cls,
            'properties': properties,
            'tags': tags
        }

    # ==================== Class CRUD Operations ====================

    def get_version_for_tenant(self, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        """Get a version by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT v.id, v.version_id, v.project_id, v.visibility, v.published,
                   p.name as project_name, p.slug as project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        """
        results = self.execute_query(query, (version_id, tenant_id))
        return results[0] if results else None

    def get_versions_for_tenant(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all versions for a tenant."""
        query = """
            SELECT v.id, v.version_id, v.project_id, v.visibility, v.published,
                   p.name as project_name, p.slug as project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
            ORDER BY p.name, v.version_id
        """
        return self.execute_query(query, (tenant_id,))

    def get_class_by_id(self, class_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific class by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT c.id, c.version_id, c.name, c.description, c.schema, c.enabled,
                   c.created_at, c.updated_at
            FROM apiome.classes c
            JOIN apiome.versions v ON c.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE c.id = %s
              AND p.tenant_id = %s
              AND c.deleted_at IS NULL
        """
        results = self.execute_query(query, (class_id, tenant_id))
        return results[0] if results else None

    def get_classes_for_tenant_version(self, tenant_id: str, version_id: str) -> List[Dict[str, Any]]:
        """Get all classes for a specific version, ensuring it belongs to the tenant."""
        query = """
            SELECT c.id, c.version_id, c.name, c.description, c.schema, c.enabled,
                   c.created_at, c.updated_at
            FROM apiome.classes c
            JOIN apiome.versions v ON c.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE c.version_id = %s
              AND p.tenant_id = %s
              AND c.deleted_at IS NULL
            ORDER BY c.name ASC
        """
        return self.execute_query(query, (version_id, tenant_id))

    def create_class(
        self,
        version_id: str,
        name: str,
        schema: Dict[str, Any],
        description: Optional[str] = None,
        enabled: bool = True
    ) -> Dict[str, Any]:
        """Create a new class."""
        import json
        query = """
            INSERT INTO apiome.classes
            (version_id, name, description, schema, enabled)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, version_id, name, description, schema, enabled,
                      created_at, updated_at
        """
        schema_json = json.dumps(schema)

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (version_id, name, description, schema_json, enabled)
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_class(
        self,
        class_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an existing class, ensuring it belongs to the tenant."""
        import json

        # First verify the class belongs to the tenant
        existing = self.get_class_by_id(class_id, tenant_id)
        if not existing:
            return None

        # Build dynamic update query
        update_fields = []
        params = []

        if 'name' in updates and updates['name'] is not None:
            update_fields.append("name = %s")
            params.append(updates['name'])
        if 'description' in updates and updates['description'] is not None:
            update_fields.append("description = %s")
            params.append(updates['description'])
        if 'schema' in updates and updates['schema'] is not None:
            update_fields.append("schema = %s")
            params.append(json.dumps(updates['schema']))
        if 'enabled' in updates and updates['enabled'] is not None:
            update_fields.append("enabled = %s")
            params.append(updates['enabled'])
        if 'canvas_metadata' in updates and updates['canvas_metadata'] is not None:
            update_fields.append("canvas_metadata = %s")
            params.append(json.dumps(updates['canvas_metadata']))

        if not update_fields:
            # Nothing to update, return current class
            return existing

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(class_id)

        query = f"""
            UPDATE apiome.classes
            SET {', '.join(update_fields)}
            WHERE id = %s AND deleted_at IS NULL
            RETURNING id, version_id, name, description, schema, enabled, canvas_metadata,
                      created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_class(self, class_id: str, tenant_id: str) -> bool:
        """Delete a class (soft delete), ensuring it belongs to the tenant."""
        # First verify the class belongs to the tenant
        existing = self.get_class_by_id(class_id, tenant_id)
        if not existing:
            return False

        query = """
            UPDATE apiome.classes
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id = %s AND deleted_at IS NULL
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (class_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def add_property_to_class(
        self,
        class_id: str,
        property_id: Optional[str],
        name: str,
        description: Optional[str],
        data: Dict[str, Any],
        parent_id: Optional[str] = None,
        primitive_id: Optional[str] = None,
        primitive_ref: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a property to a class.

        Args:
            primitive_id: Optional FK to the apiome.primitives row this property is bound
                to (the resolved target of a registry $ref). Read by the Designer (#3448).
            primitive_ref: Optional registry $ref string persisted alongside primitive_id.
        """
        import json

        if not name or not name.strip():
            raise ValueError('Property name is required')

        # Validate: either property_id must be set, or data must contain $ref
        has_ref = data and (data.get('$ref') or (data.get('type') == 'array' and data.get('items', {}).get('$ref')))
        if not property_id and not has_ref:
            raise ValueError('Property must have either a library reference (property_id) or a schema $ref')

        query = """
            INSERT INTO apiome.class_properties
                (class_id, property_id, name, description, data, parent_id, primitive_id, primitive_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, class_id, property_id, name, description, data, parent_id,
                      primitive_id, primitive_ref
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (class_id, property_id, name.strip(), description, json.dumps(data),
                     parent_id, primitive_id, primitive_ref)
                )
                result = cursor.fetchone()
                # Binding a property to a registry type counts as a use of that
                # primitive (#3475 — increment usage via the existing usage_count
                # pattern). Done in the same transaction so the count and the
                # binding commit atomically.
                if primitive_id:
                    cursor.execute(
                        "UPDATE apiome.primitives SET usage_count = usage_count + 1 WHERE id = %s",
                        (primitive_id,)
                    )
                conn.commit()
                # Parse JSON data if it's a string
                if result and isinstance(result.get('data'), str):
                    result['data'] = json.loads(result['data'])
                return result
        except Exception as e:
            conn.rollback()
            # Check for unique constraint violation
            if "unique constraint" in str(e).lower() or "23505" in str(e):
                raise ValueError('A property with this name already exists at this level')
            raise e

    def update_class_property(
        self,
        class_property_id: str,
        class_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a class property, ensuring it belongs to the class and tenant."""
        import json

        # First verify the class property belongs to a class that belongs to the tenant.
        # Also fetch the current primitive binding so we can tell whether this update
        # newly binds the property to a primitive (for the usage_count increment, #3475).
        verify_query = """
            SELECT cp.id, cp.class_id, cp.primitive_id
            FROM apiome.class_properties cp
            JOIN apiome.classes c ON cp.class_id = c.id
            JOIN apiome.versions v ON c.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE cp.id = %s
              AND c.id = %s
              AND p.tenant_id = %s
        """
        verify_result = self.execute_query(verify_query, (class_property_id, class_id, tenant_id))
        if not verify_result:
            return None
        old_primitive_id = verify_result[0].get('primitive_id')

        # Build dynamic update query
        update_fields = []
        params = []

        if 'name' in updates and updates['name'] is not None:
            update_fields.append("name = %s")
            params.append(updates['name'].strip())
        if 'description' in updates:
            update_fields.append("description = %s")
            params.append(updates['description'])
        if 'data' in updates and updates['data'] is not None:
            update_fields.append("data = %s")
            params.append(json.dumps(updates['data']))
        # Property→primitive binding (#3448). These accept None so a binding can be cleared.
        if 'primitive_id' in updates:
            update_fields.append("primitive_id = %s")
            params.append(updates['primitive_id'])
        if 'primitive_ref' in updates:
            update_fields.append("primitive_ref = %s")
            params.append(updates['primitive_ref'])

        if not update_fields:
            # Nothing to update, return current property
            return self.execute_query(
                "SELECT id, class_id, property_id, name, description, data, parent_id, primitive_id, primitive_ref FROM apiome.class_properties WHERE id = %s",
                (class_property_id,)
            )[0] if self.execute_query("SELECT id FROM apiome.class_properties WHERE id = %s", (class_property_id,)) else None

        params.append(class_property_id)

        query = f"""
            UPDATE apiome.class_properties
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, class_id, property_id, name, description, data, parent_id,
                      primitive_id, primitive_ref
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                # If this update binds the property to a *different* primitive than
                # before, count it as a new use of that primitive (#3475). Comparing
                # against the prior value keeps repeated saves of an unchanged binding
                # from inflating usage_count. Same transaction as the update.
                if 'primitive_id' in updates:
                    new_primitive_id = updates['primitive_id']
                    if new_primitive_id and str(new_primitive_id) != str(old_primitive_id):
                        cursor.execute(
                            "UPDATE apiome.primitives SET usage_count = usage_count + 1 WHERE id = %s",
                            (new_primitive_id,)
                        )
                conn.commit()
                if result and isinstance(result.get('data'), str):
                    result['data'] = json.loads(result['data'])
                return result
        except Exception as e:
            conn.rollback()
            # Check for unique constraint violation
            if "unique constraint" in str(e).lower() or "23505" in str(e):
                raise ValueError('A property with this name already exists at this level')
            raise e

    def delete_class_property(
        self,
        class_property_id: str,
        class_id: str,
        tenant_id: str
    ) -> bool:
        """Delete a class property, ensuring it belongs to the class and tenant."""
        # First verify the class property belongs to a class that belongs to the tenant
        verify_query = """
            SELECT cp.id
            FROM apiome.class_properties cp
            JOIN apiome.classes c ON cp.class_id = c.id
            JOIN apiome.versions v ON c.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE cp.id = %s
              AND c.id = %s
              AND p.tenant_id = %s
        """
        verify_result = self.execute_query(verify_query, (class_property_id, class_id, tenant_id))
        if not verify_result:
            return False

        query = """
            DELETE FROM apiome.class_properties
            WHERE id = %s
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (class_property_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Validate an API key and return tenant information.
        Uses the same key_prefix format as the UI (first 12 chars + '...') for lookup,
        then verifies the full key against the stored bcrypt key_hash.

        Args:
            api_key: The API key to validate

        Returns:
            Dict with tenant_id and tenant info if valid, None otherwise
        """
        if not api_key or len(api_key) < 12:
            return None

        # Match UI format: key_prefix is first 12 characters + '...'
        key_prefix = api_key[:12] + '...'

        query_with_creator = """
            SELECT ak.id, ak.tenant_id, ak.created_by_user_id, ak.key_hash, ak.expires_at, ak.enabled,
                   t.id as tenant_id, t.slug as tenant_slug, t.name as tenant_name
            FROM apiome.api_keys ak
            JOIN apiome.tenants t ON ak.tenant_id = t.id
            WHERE ak.key_prefix = %s
              AND ak.deleted_at IS NULL
              AND ak.enabled = true
              AND t.deleted_at IS NULL
              AND t.enabled = true
              AND (ak.expires_at IS NULL OR ak.expires_at > CURRENT_TIMESTAMP)
        """
        query_legacy = """
            SELECT ak.id, ak.tenant_id, ak.key_hash, ak.expires_at, ak.enabled,
                   t.id as tenant_id, t.slug as tenant_slug, t.name as tenant_name
            FROM apiome.api_keys ak
            JOIN apiome.tenants t ON ak.tenant_id = t.id
            WHERE ak.key_prefix = %s
              AND ak.deleted_at IS NULL
              AND ak.enabled = true
              AND t.deleted_at IS NULL
              AND t.enabled = true
              AND (ak.expires_at IS NULL OR ak.expires_at > CURRENT_TIMESTAMP)
        """
        try:
            results = self.execute_query(query_with_creator, (key_prefix,))
        except Exception as e:
            root = e.__cause__ if getattr(e, "__cause__", None) else e
            pgcode = getattr(root, "pgcode", None)
            msg_l = str(e).lower()
            if pgcode == "42703" or ("created_by_user_id" in msg_l and "does not exist" in msg_l):
                results = self.execute_query(query_legacy, (key_prefix,))
            else:
                raise

        if not results:
            return None

        # Verify the full key against the stored bcrypt hash
        api_key_bytes = api_key.encode('utf-8')
        for row in results:
            key_hash = row['key_hash']
            if isinstance(key_hash, str):
                key_hash = key_hash.encode('utf-8')
            try:
                if bcrypt.checkpw(api_key_bytes, key_hash):
                    api_key_data = dict(row)
                    # Update last_used_at
                    try:
                        update_query = "UPDATE apiome.api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s"
                        conn = self.connect()
                        with conn.cursor() as cursor:
                            cursor.execute(update_query, (api_key_data['id'],))
                            conn.commit()
                    except Exception:
                        pass  # Don't fail if we can't update last_used_at
                    return api_key_data
            except (ValueError, TypeError):
                continue

        return None

    def get_fallback_creator_user_id_for_tenant(self, tenant_id: str) -> Optional[str]:
        """
        When an API key has no created_by_user_id (legacy rows), attribute writes to the first
        tenant administrator if any, otherwise the first tenant member.
        """
        admin_q = """
            SELECT user_id::text AS user_id
            FROM apiome.tenant_administrators
            WHERE tenant_id = %s::uuid
            ORDER BY created_at ASC
            LIMIT 1
        """
        rows = self.execute_query(admin_q, (tenant_id,))
        if rows:
            uid = rows[0].get("user_id")
            if uid:
                return str(uid)
        member_q = """
            SELECT user_id::text AS user_id
            FROM apiome.tenant_users
            WHERE tenant_id = %s::uuid
            ORDER BY created_at ASC
            LIMIT 1
        """
        rows = self.execute_query(member_q, (tenant_id,))
        if rows:
            uid = rows[0].get("user_id")
            if uid:
                return str(uid)
        return None

    def count_tenants_for_user(self, user_id: str) -> int:
        """Count enabled, non-deleted tenants the user belongs to (member or administrator)."""
        query = """
            SELECT COUNT(DISTINCT t.id)::int AS c
            FROM apiome.tenants t
            INNER JOIN (
                SELECT tenant_id FROM apiome.tenant_users WHERE user_id = %s::uuid
                UNION
                SELECT tenant_id FROM apiome.tenant_administrators WHERE user_id = %s::uuid
            ) access ON access.tenant_id = t.id
            WHERE t.deleted_at IS NULL
              AND t.enabled IS TRUE
        """
        rows = self.execute_query(query, (user_id, user_id))
        if not rows:
            return 0
        c = rows[0].get("c")
        return int(c) if c is not None else 0

    def list_tenants_for_user_page(
        self, user_id: str, limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        """
        List tenants for a user with role ``admin`` (tenant administrator) or ``member``.
        Ordered by slug ascending.
        """
        query = """
            SELECT t.id::text AS id, t.slug, t.name,
                   CASE WHEN ta.user_id IS NOT NULL THEN 'admin' ELSE 'member' END AS role
            FROM apiome.tenants t
            INNER JOIN (
                SELECT tenant_id, user_id FROM apiome.tenant_users WHERE user_id = %s::uuid
                UNION
                SELECT tenant_id, user_id FROM apiome.tenant_administrators WHERE user_id = %s::uuid
            ) access ON access.tenant_id = t.id AND access.user_id = %s::uuid
            LEFT JOIN apiome.tenant_administrators ta
              ON ta.tenant_id = t.id AND ta.user_id = access.user_id
            WHERE t.deleted_at IS NULL AND t.enabled IS TRUE
            ORDER BY t.slug ASC
            LIMIT %s OFFSET %s
        """
        return self.execute_query(query, (user_id, user_id, user_id, limit, offset))

    def get_tenant_row_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Return tenant id/slug/name/created_at if slug exists and is active."""
        query = """
            SELECT t.id::text AS id, t.slug, t.name, t.created_at
            FROM apiome.tenants t
            WHERE t.slug = %s AND t.deleted_at IS NULL AND t.enabled IS TRUE
            LIMIT 1
        """
        rows = self.execute_query(query, (slug,))
        return rows[0] if rows else None

    def get_tenant_usage_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Aggregate member, project, and version counts for tenant detail (#3198)."""
        query = """
            SELECT
              (SELECT COUNT(*)::int FROM apiome.tenant_users tu WHERE tu.tenant_id = %s) AS members_count,
              (SELECT COUNT(*)::int FROM apiome.projects p
                 WHERE p.tenant_id = %s AND p.deleted_at IS NULL) AS projects_count,
              (SELECT COUNT(*)::int
                 FROM apiome.versions v
                 INNER JOIN apiome.projects p ON v.project_id = p.id
                 WHERE p.tenant_id = %s AND p.deleted_at IS NULL) AS versions_count,
              (SELECT COUNT(*)::int
                 FROM apiome.versions v
                 INNER JOIN apiome.projects p ON v.project_id = p.id
                 WHERE p.tenant_id = %s AND p.deleted_at IS NULL AND v.published IS TRUE)
                AS published_versions_count
        """
        rows = self.execute_query(query, (tenant_id, tenant_id, tenant_id, tenant_id))
        if not rows:
            return {
                "members_count": 0,
                "projects_count": 0,
                "versions_count": 0,
                "published_versions_count": 0,
            }
        return dict(rows[0])

    def get_tags_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all tags for a specific project."""
        query = """
            SELECT id, project_id, name, color, description, created_at, updated_at
            FROM apiome.tags
            WHERE project_id = %s
            ORDER BY name ASC
        """
        return self.execute_query(query, (project_id,))

    def get_tags_for_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get all tags assigned to a specific class."""
        query = """
            SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
                   t.name as tag_name, t.color as tag_color, t.description as tag_description
            FROM apiome.class_tags ct
            JOIN apiome.tags t ON ct.tag_id = t.id
            WHERE ct.class_id = %s
            ORDER BY t.name ASC
        """
        return self.execute_query(query, (class_id,))

    def create_tag(self, project_id: str, name: str, color: str = "default", description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new tag."""
        query = """
            INSERT INTO apiome.tags (project_id, name, color, description)
            VALUES (%s, %s, %s, %s)
            RETURNING id, project_id, name, color, description, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (project_id, name, color, description))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_tag(self, tag_id: str, name: Optional[str] = None, color: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        """Update an existing tag."""
        # Build dynamic update query
        updates = []
        params = []

        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if color is not None:
            updates.append("color = %s")
            params.append(color)
        if description is not None:
            updates.append("description = %s")
            params.append(description)

        if not updates:
            # Nothing to update, just return current tag
            return self.get_tag_by_id(tag_id)

        params.append(tag_id)
        query = f"""
            UPDATE apiome.tags
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING id, project_id, name, color, description, created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_tag(self, tag_id: str) -> bool:
        """Delete a tag (will cascade delete class_tags due to FK constraint)."""
        query = "DELETE FROM apiome.tags WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (tag_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def assign_tag_to_class(self, class_id: str, tag_id: str) -> Dict[str, Any]:
        """Assign a tag to a class."""
        query = """
            INSERT INTO apiome.class_tags (class_id, tag_id)
            VALUES (%s, %s)
            ON CONFLICT (class_id, tag_id) DO NOTHING
            RETURNING id, class_id, tag_id, created_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (class_id, tag_id))
                result = cursor.fetchone()
                conn.commit()
                # If conflict, fetch existing record
                if result is None:
                    cursor.execute(
                        "SELECT id, class_id, tag_id, created_at FROM apiome.class_tags WHERE class_id = %s AND tag_id = %s",
                        (class_id, tag_id)
                    )
                    result = cursor.fetchone()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def remove_tag_from_class(self, class_id: str, tag_id: str) -> bool:
        """Remove a tag from a class."""
        query = "DELETE FROM apiome.class_tags WHERE class_id = %s AND tag_id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (class_id, tag_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def get_security_schemes_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all security schemes for a version (OpenAPI components.securitySchemes)."""
        query = """
            SELECT id, version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data
            FROM apiome.version_security_scheme
            WHERE version_id = %s
            ORDER BY scheme_name
        """
        return self.execute_query(query, (version_id,))

    def get_servers_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all server definitions for a version (OpenAPI servers array)."""
        query = """
            SELECT id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at
            FROM apiome.version_server
            WHERE version_id = %s
            ORDER BY sort_order, url
        """
        return self.execute_query(query, (version_id,))

    def get_paths_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all paths for a specific version."""
        query = """
            SELECT
                id,
                pathname,
                metadata->>'summary' as summary,
                metadata->>'description' as description
            FROM apiome.version_path
            WHERE version_id = %s
            ORDER BY pathname
        """
        return self.execute_query(query, (version_id,))

    def get_operations_for_path(self, version_path_id: str) -> List[Dict[str, Any]]:
        """Get all operations for a specific path."""
        query = """
            SELECT id, version_path_id, operation, metadata, created_at, updated_at
            FROM apiome.path_operation
            WHERE version_path_id = %s
            ORDER BY CASE operation
                WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
                WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
            END
        """
        return self.execute_query(query, (version_path_id,))

    def get_operation_description(self, path_operation_id: str) -> Optional[Dict[str, Any]]:
        """Get operation description."""
        query = """
            SELECT
                id,
                summary,
                description,
                operation_id,
                metadata->'tags' as tags,
                (metadata->>'deprecated')::boolean as deprecated,
                (metadata->>'x-private')::boolean as x_private,
                metadata->'external_docs' as external_docs,
                metadata
            FROM apiome.path_operation_description
            WHERE path_operation_id = %s
            LIMIT 1
        """
        results = self.execute_query(query, (path_operation_id,))
        return results[0] if results else None

    def get_parameters_for_operation(self, path_operation_id: str) -> List[Dict[str, Any]]:
        """Get all parameters linked to an operation."""
        query = """
            SELECT spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
            FROM apiome.shared_path_parameter spp
            INNER JOIN apiome.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
            WHERE popl.path_operation_id = %s
            ORDER BY CASE spp.in_location
                WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4
            END, spp.name
        """
        return self.execute_query(query, (path_operation_id,))

    def get_request_body_for_operation(self, path_operation_id: str) -> Optional[Dict[str, Any]]:
        """Get request body linked to an operation with content types."""
        query = """
            SELECT rb.id, rb.name, rb.description, rb.required,
                COALESCE(json_agg(json_build_object(
                    'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
                    'class_name', c.name, 'inline_schema', rbc.inline_schema,
                    'encoding', rbc.encoding, 'examples', rbc.examples
                )) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
            FROM apiome.shared_path_request_body rb
            INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
            LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
            LEFT JOIN apiome.classes c ON rbc.class_id = c.id
            WHERE link.path_operation_id = %s
            GROUP BY rb.id
        """
        results = self.execute_query(query, (path_operation_id,))
        return results[0] if results else None

    def get_responses_for_operation(self, path_operation_id: str) -> List[Dict[str, Any]]:
        """Get all responses linked to an operation with content types."""
        query = """
            SELECT
                spr.id,
                spr.status_code,
                spr.description,
                spr.data,
                spr.class_id,
                c.name as class_name,
                spr.inline_schema,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', rc.id,
                            'media_type', rc.media_type,
                            'class_id', rc.class_id,
                            'class_name', rc_class.name,
                            'inline_schema', rc.inline_schema,
                            'examples', rc.examples
                        )
                    ) FILTER (WHERE rc.id IS NOT NULL),
                    '[]'
                ) as content_types
            FROM apiome.shared_path_response spr
            INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
            LEFT JOIN apiome.classes c ON spr.class_id = c.id
            LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
            LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
            WHERE porl.path_operation_id = %s
            GROUP BY spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name, spr.inline_schema
            ORDER BY spr.status_code
        """
        return self.execute_query(query, (path_operation_id,))

    def registry_ping(self) -> Dict[str, Any]:
        """Probe the Primitives type-registry storage backend (#3450).

        The registry lives in the existing ``apiome-db`` database, backed
        by the ``apiome.primitives`` table (see ROADMAP_TYPE_REGISTRY_GOVERNANCE.md
        §1a — single database, no separate registry DB). This runs a single
        lightweight query that both confirms the shared connection is actually
        live (not merely an object that claims to be open) and reports whether
        the registry's storage table is present.

        Returns:
            A dict with:
              - ``connection``: ``"connected"`` when the query succeeds.
              - ``storage_present``: ``True`` when ``apiome.primitives`` exists.

        Raises:
            Exception: Propagated from the driver when the apiome-db
            connection cannot be established or the probe query fails, so the
            caller can report an unhealthy registry layer.
        """
        rows = self.execute_query(
            "SELECT to_regclass('apiome.primitives') IS NOT NULL AS storage_present"
        )
        storage_present = bool(rows and rows[0].get("storage_present"))
        return {"connection": "connected", "storage_present": storage_present}

    def get_primitives_for_tenant(self, tenant_id: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List the primitives a tenant may read: system-core ∪ the tenant's own (#3453).

        Read scope is ``is_system = true`` (shared system-core types, visible to every
        tenant) unioned with ``tenant_id = <caller>`` (the tenant's private types). A
        different tenant's private types are never returned, so Tenant A cannot read
        Tenant B's custom types. System-core types are seeded per tenant, so a tenant
        that already owns a core row would otherwise see it twice; ``DISTINCT ON
        (category, name)`` collapses those, preferring the caller's own row.

        Args:
            tenant_id: The caller's tenant id (scopes visibility).
            category: Optional category filter.

        Returns:
            The visible primitives, ordered by category then name.
        """
        query = """
            SELECT DISTINCT ON (category, name)
                   id, tenant_id, name, description, category, schema, tags,
                   created_by, is_system, is_public, usage_count, source,
                   schema_id, draft, namespace, base_uri, refs,
                   created_at, updated_at
            FROM apiome.primitives
            WHERE (tenant_id = %s OR is_system = true)
        """
        params = [tenant_id]

        if category:
            query += " AND category = %s"
            params.append(category)

        # Within each (category, name) group prefer the caller's own row over a
        # foreign system-core copy; the leading keys satisfy DISTINCT ON.
        query += " ORDER BY category, name, (tenant_id = %s) DESC"
        params.append(tenant_id)
        return self.execute_query(query, tuple(params))

    def get_primitive_by_id(self, primitive_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a primitive by ID within the tenant's read scope: system-core ∪ own (#3453).

        Returns the row when it is the tenant's own or a shared system-core type; a
        different tenant's private type resolves to ``None`` (cross-tenant isolation).
        System-core rows are read-only — the route layer rejects writes to them — so
        returning one here for a read does not grant write access.

        Args:
            primitive_id: The primitive id.
            tenant_id: The caller's tenant id (scopes visibility).

        Returns:
            The primitive row, or None when missing or not visible to the tenant.
        """
        query = """
            SELECT id, tenant_id, name, description, category, schema, tags,
                   created_by, is_system, is_public, usage_count, source,
                   schema_id, draft, namespace, base_uri, refs,
                   created_at, updated_at
            FROM apiome.primitives
            WHERE id = %s AND (tenant_id = %s OR is_system = true)
        """
        results = self.execute_query(query, (primitive_id, tenant_id))
        return results[0] if results else None

    def get_primitive_by_schema_id(
        self, schema_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve a primitive by its JSON Schema ``$id`` within the tenant's read scope (#3456).

        Backs relative ``$ref`` resolution: a resolved absolute registry URI is matched
        against ``apiome.primitives.schema_id``. Scope is the same as the other reads —
        system-core ∪ the caller's own — so a tenant resolves only to shared system-core
        or its own types, never to another tenant's private type (honoring #3453). When
        system-core types are seeded per tenant, the caller's own copy is preferred.

        Args:
            schema_id: The absolute ``$id`` to resolve (the ref's resolved target URI).
            tenant_id: The caller's tenant id (scopes visibility).

        Returns:
            The matching primitive row, or None when no visible type has that ``$id``.
        """
        query = """
            SELECT id, tenant_id, name, description, category, schema, tags,
                   created_by, is_system, is_public, usage_count, source,
                   schema_id, draft, namespace, base_uri, refs,
                   created_at, updated_at
            FROM apiome.primitives
            WHERE schema_id = %s AND (tenant_id = %s OR is_system = true)
            ORDER BY (tenant_id = %s) DESC
            LIMIT 1
        """
        results = self.execute_query(query, (schema_id, tenant_id, tenant_id))
        return results[0] if results else None

    def create_primitive(
        self,
        tenant_id: str,
        name: str,
        category: str,
        schema: Dict[str, Any],
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        source: str = 'human',
        schema_id: Optional[str] = None,
        draft: str = '2020-12',
        namespace: Optional[str] = None,
        base_uri: Optional[str] = None,
        refs: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Create a new primitive.

        Args:
            source: Provenance of the primitive — 'human' (authored in-app, default)
                or 'imported' (created by an import). Stored on apiome.primitives.source.
            schema_id: The computed JSON Schema ``$id`` for the primitive (#3452).
            draft: The JSON Schema dialect/draft, default '2020-12' (#3452).
            namespace: Optional registry namespace path locating the primitive (#3452).
            base_uri: Optional namespace base URI the ``$id`` was computed against (#3452).
            refs: Resolved relative-``$ref`` edges for the schema, each
                ``{relative_ref, resolved_target, status}`` (#3456). Defaults to ``[]``.
        """
        query = """
            INSERT INTO apiome.primitives
            (tenant_id, name, description, category, schema, tags, created_by, source,
             schema_id, draft, namespace, base_uri, refs)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, name, description, category, schema, tags,
                      created_by, is_system, is_public, usage_count, source,
                      schema_id, draft, namespace, base_uri, refs,
                      created_at, updated_at
        """

        import json
        schema_json = json.dumps(schema)
        refs_json = json.dumps(refs or [])

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (tenant_id, name, description, category, schema_json, tags or [],
                     created_by, source, schema_id, draft, namespace, base_uri, refs_json)
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_primitive(
        self,
        primitive_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an existing primitive, ensuring it belongs to the tenant."""
        import json

        # Build dynamic update query
        update_fields = []
        params = []

        if 'name' in updates and updates['name'] is not None:
            update_fields.append("name = %s")
            params.append(updates['name'])
        if 'description' in updates and updates['description'] is not None:
            update_fields.append("description = %s")
            params.append(updates['description'])
        if 'category' in updates and updates['category'] is not None:
            update_fields.append("category = %s")
            params.append(updates['category'])
        if 'schema' in updates and updates['schema'] is not None:
            update_fields.append("schema = %s")
            params.append(json.dumps(updates['schema']))
        if 'tags' in updates and updates['tags'] is not None:
            update_fields.append("tags = %s")
            params.append(updates['tags'])
        if 'enabled' in updates and updates['enabled'] is not None:
            update_fields.append("enabled = %s")
            params.append(updates['enabled'])
        # JSON Schema 2020-12 registry identity columns (#3452). Re-derived by the
        # route whenever the schema or registry placement changes.
        if 'schema_id' in updates and updates['schema_id'] is not None:
            update_fields.append("schema_id = %s")
            params.append(updates['schema_id'])
        if 'draft' in updates and updates['draft'] is not None:
            update_fields.append("draft = %s")
            params.append(updates['draft'])
        if 'namespace' in updates and updates['namespace'] is not None:
            update_fields.append("namespace = %s")
            params.append(updates['namespace'])
        if 'base_uri' in updates and updates['base_uri'] is not None:
            update_fields.append("base_uri = %s")
            params.append(updates['base_uri'])
        # Resolved relative-$ref edges, re-derived by the route whenever the schema or
        # registry placement changes (#3456). May be an empty list (no edges), so the
        # presence of the key — not its truthiness — drives the write.
        if 'refs' in updates and updates['refs'] is not None:
            update_fields.append("refs = %s")
            params.append(json.dumps(updates['refs']))

        if not update_fields:
            # Nothing to update, return current primitive
            return self.get_primitive_by_id(primitive_id, tenant_id)

        params.extend([primitive_id, tenant_id])
        query = f"""
            UPDATE apiome.primitives
            SET {', '.join(update_fields)}
            WHERE id = %s AND tenant_id = %s
            RETURNING id, tenant_id, name, description, category, schema, tags,
                      created_by, is_system, is_public, usage_count, source,
                      schema_id, draft, namespace, base_uri, refs,
                      created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_primitive(self, primitive_id: str, tenant_id: str) -> bool:
        """Delete a primitive, ensuring it belongs to the tenant."""
        query = """
            DELETE FROM apiome.primitives
            WHERE id = %s AND tenant_id = %s AND is_system = false
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (primitive_id, tenant_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def increment_primitive_usage(self, primitive_id: str) -> None:
        """Increment the usage count for a primitive."""
        query = "UPDATE apiome.primitives SET usage_count = usage_count + 1 WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (primitive_id,))
                conn.commit()
        except Exception:
            pass  # Don't fail if we can't increment usage

    # ============== Unresolved-$ref detection, flags & counts (#3457) ==============
    #
    # A primitive's relative ``$ref`` edges live in the ``refs`` JSONB column, each
    # ``{relative_ref, resolved_target, status}`` with status resolved|unresolved (#3456).
    # The aggregates below summarize the unresolved edges for the registry overview KPIs
    # (#3454) and the resolver UI (#3470); ``mark_refs_resolved_to_target`` clears the
    # unresolved flag on dependents once the referenced target is created (re-resolve).
    #
    # Scope note: system-core primitives are seeded *per tenant* (one ``apiome.primitives``
    # row per tenant, with ``is_system = true``), so the tenant's own ``tenant_id`` rows
    # already include a copy of every visible system type. The aggregates therefore scope
    # to ``tenant_id = <caller>`` alone — adding ``OR is_system = true`` would re-count
    # every *other* tenant's system copies. Unresolved edges only ever occur on a tenant's
    # authored/imported types anyway (the std/v0 seed resolves fully).

    def count_unresolved_refs(self, tenant_id: str) -> Dict[str, int]:
        """Count the tenant's unresolved ``$ref`` edges and the primitives carrying them (#3457).

        Aggregates over the ``refs`` JSONB column of the tenant's primitives, feeding the
        registry overview KPIs (#3454) and the resolver UI (#3470).

        Args:
            tenant_id: The caller's tenant id (scopes the aggregate — see section note).

        Returns:
            ``{"unresolved_ref_count": int, "affected_primitive_count": int}`` —
            the total number of unresolved edges and the number of distinct primitives
            that have at least one. Both are ``0`` when nothing is unresolved.
        """
        query = """
            SELECT
                COUNT(*) FILTER (WHERE edge->>'status' = 'unresolved')
                    AS unresolved_ref_count,
                COUNT(DISTINCT p.id) FILTER (WHERE edge->>'status' = 'unresolved')
                    AS affected_primitive_count
            FROM apiome.primitives p
            LEFT JOIN LATERAL jsonb_array_elements(p.refs) AS edge ON true
            WHERE p.tenant_id = %s
        """
        results = self.execute_query(query, (tenant_id,))
        row = results[0] if results else {}
        return {
            "unresolved_ref_count": int(row.get("unresolved_ref_count") or 0),
            "affected_primitive_count": int(row.get("affected_primitive_count") or 0),
        }

    def get_registry_coverage_stats(self, tenant_id: str) -> Dict[str, int]:
        """Aggregate registry coverage KPIs for the Primitives overview (#3454).

        Type counts use the tenant's own ``apiome.primitives`` rows (system-core types are
        seeded per tenant). Property bindings count ``class_properties`` rows in the
        tenant's projects that carry a ``primitive_id`` or ``primitive_ref``.

        Args:
            tenant_id: The caller's tenant id.

        Returns:
            Counts for core/tenant/imported types, bindings, unresolved refs, and namespaces.
        """
        query = """
            WITH type_counts AS (
                SELECT
                    COUNT(*) FILTER (WHERE is_system) AS core_type_count,
                    COUNT(*) FILTER (WHERE NOT is_system) AS tenant_type_count,
                    COUNT(*) FILTER (WHERE source = 'imported') AS imported_count,
                    COUNT(DISTINCT namespace) FILTER (WHERE namespace IS NOT NULL)
                        AS namespace_count
                FROM apiome.primitives
                WHERE tenant_id = %s
            ),
            binding_counts AS (
                SELECT
                    COUNT(*) AS properties_bound_count,
                    COUNT(DISTINCT cp.class_id) AS bound_class_count
                FROM apiome.class_properties cp
                JOIN apiome.classes c ON cp.class_id = c.id
                JOIN apiome.versions v ON c.version_id = v.id
                JOIN apiome.projects p ON v.project_id = p.id
                WHERE p.tenant_id = %s
                  AND (cp.primitive_id IS NOT NULL OR cp.primitive_ref IS NOT NULL)
            ),
            unresolved AS (
                SELECT
                    COUNT(*) FILTER (WHERE edge->>'status' = 'unresolved')
                        AS unresolved_ref_count
                FROM apiome.primitives p
                LEFT JOIN LATERAL jsonb_array_elements(p.refs) AS edge ON true
                WHERE p.tenant_id = %s
            )
            SELECT
                tc.core_type_count,
                tc.tenant_type_count,
                tc.imported_count,
                tc.namespace_count,
                bc.properties_bound_count,
                bc.bound_class_count,
                u.unresolved_ref_count
            FROM type_counts tc
            CROSS JOIN binding_counts bc
            CROSS JOIN unresolved u
        """
        results = self.execute_query(query, (tenant_id, tenant_id, tenant_id))
        row = results[0] if results else {}
        return {
            "core_type_count": int(row.get("core_type_count") or 0),
            "tenant_type_count": int(row.get("tenant_type_count") or 0),
            "imported_count": int(row.get("imported_count") or 0),
            "namespace_count": int(row.get("namespace_count") or 0),
            "properties_bound_count": int(row.get("properties_bound_count") or 0),
            "bound_class_count": int(row.get("bound_class_count") or 0),
            "unresolved_ref_count": int(row.get("unresolved_ref_count") or 0),
        }

    def get_primitives_with_unresolved_refs(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List the tenant's primitives that have at least one unresolved ``$ref`` edge (#3457).

        Backs the resolver UI's dangling-reference table (#3470): each returned row
        carries the primitive's identity plus its full ``refs`` edge list (the route
        narrows it to the unresolved edges).

        Args:
            tenant_id: The caller's tenant id (scopes the listing — see section note).

        Returns:
            The matching primitive rows (id, name, schema_id, namespace, base_uri, refs),
            ordered by namespace then name. Empty when nothing is unresolved.
        """
        query = """
            SELECT id, tenant_id, name, schema_id, namespace, base_uri, refs
            FROM apiome.primitives
            WHERE tenant_id = %s
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(refs) AS e
                  WHERE e->>'status' = 'unresolved'
              )
            ORDER BY namespace NULLS FIRST, name
        """
        return self.execute_query(query, (tenant_id,))

    def mark_refs_resolved_to_target(self, tenant_id: str, target_schema_id: str) -> int:
        """Clear the unresolved flag on edges that point at a now-existing target (#3457).

        When a primitive is created/imported (or repinned), any of the tenant's other
        primitives that carried an *unresolved* edge whose ``resolved_target`` equals the
        new primitive's ``$id`` are re-resolved: just that edge flips to ``resolved`` in
        place, preserving edge order and leaving every other edge untouched. This is the
        "fixing target clears on re-resolve" half of the acceptance criteria — it runs
        without requiring the dependent primitive to be re-saved by hand.

        Only the tenant's own rows are rewritten (system-core rows are seeded/immutable),
        and only edges that are both unresolved *and* aimed at ``target_schema_id`` change.

        Args:
            tenant_id: The tenant whose primitives may reference the new target.
            target_schema_id: The absolute ``$id`` of the just-created/updated primitive.

        Returns:
            The number of dependent primitives whose ``refs`` were updated (0 when none
            referenced the target as unresolved).
        """
        query = """
            UPDATE apiome.primitives p
            SET refs = (
                SELECT jsonb_agg(
                    CASE
                        WHEN e->>'resolved_target' = %s AND e->>'status' = 'unresolved'
                        THEN jsonb_set(e, '{status}', '"resolved"'::jsonb)
                        ELSE e
                    END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(p.refs) WITH ORDINALITY AS t(e, ord)
            )
            WHERE p.tenant_id = %s
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(p.refs) AS e2
                  WHERE e2->>'resolved_target' = %s AND e2->>'status' = 'unresolved'
              )
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (target_schema_id, tenant_id, target_schema_id))
                affected = cursor.rowcount
                conn.commit()
                return affected
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Primitive Import Provenance (#3448) ====================

    def create_primitive_import(
        self,
        tenant_id: str,
        report: Dict[str, Any],
        source_kind: str = 'json-schema',
        source_label: Optional[str] = None,
        target_namespace: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        imported_count: int = 0,
        skipped_count: int = 0,
        error_count: int = 0,
        imported_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record an auditable provenance row for a primitive import.

        Args:
            tenant_id: The tenant the import ran for.
            report: The import outcome report (imported/skipped/errors lists + counts).
            source_kind: Shape of the source document — one of 'json-schema',
                'type-def-bundle', 'openapi'.
            source_label: Optional human label (filename / URL) of the source.
            target_namespace: Optional registry namespace imported into.
            options: Import options echoed back for reproducibility.
            imported_count/skipped_count/error_count: Outcome tallies.
            imported_by: The authenticated user id (None for API-key auth).

        Returns:
            The persisted provenance row.
        """
        import json

        query = """
            INSERT INTO apiome.primitive_imports
            (tenant_id, source_kind, source_label, target_namespace, options, report,
             imported_count, skipped_count, error_count, imported_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, source_kind, source_label, target_namespace,
                      options, report, imported_count, skipped_count, error_count,
                      imported_by, created_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        tenant_id, source_kind, source_label, target_namespace,
                        json.dumps(options or {}), json.dumps(report),
                        imported_count, skipped_count, error_count, imported_by
                    )
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def get_primitive_imports(
        self, tenant_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List primitive import provenance records for a tenant, newest first."""
        query = """
            SELECT id, tenant_id, source_kind, source_label, target_namespace,
                   options, report, imported_count, skipped_count, error_count,
                   imported_by, created_at
            FROM apiome.primitive_imports
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        return self.execute_query(query, (tenant_id, limit))

    def get_primitive_import_by_id(
        self, import_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a single primitive import provenance record scoped to the tenant."""
        query = """
            SELECT id, tenant_id, source_kind, source_label, target_namespace,
                   options, report, imported_count, skipped_count, error_count,
                   imported_by, created_at
            FROM apiome.primitive_imports
            WHERE id = %s AND tenant_id = %s
        """
        results = self.execute_query(query, (import_id, tenant_id))
        return results[0] if results else None

    # ==================== Type-registry Namespaces (#3451) ====================
    #
    # Namespaces are the durable scope/base-uri/version-root/visibility/default records of the
    # type registry, stored in apiome.type_namespaces. Their `namespace` column mirrors
    # apiome.primitives.namespace, which is the join key for a namespace's type count.

    def list_type_namespaces(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List the namespaces visible to a tenant: system-core ∪ this tenant's own.

        Each row carries a ``type_count``: the number of ``apiome.primitives`` rows the caller's
        tenant has in that namespace (system-core primitives are seeded per tenant, so the count
        is correct from the caller's perspective for both scopes).

        Args:
            tenant_id: The caller's tenant id.

        Returns:
            Namespace rows (system-core first, then alphabetical), each with ``type_count``.
        """
        query = """
            SELECT n.id, n.tenant_id, n.namespace, n.base_uri, n.version_root,
                   n.description, n.is_system, n.is_public, n.is_default,
                   n.created_by, n.created_at, n.updated_at,
                   (SELECT COUNT(*) FROM apiome.primitives p
                     WHERE p.namespace = n.namespace AND p.tenant_id = %s::uuid) AS type_count
            FROM apiome.type_namespaces n
            WHERE n.is_system = true OR n.tenant_id = %s::uuid
            ORDER BY n.is_system DESC, n.namespace ASC
        """
        return self.execute_query(query, (tenant_id, tenant_id))

    def get_type_namespace_by_id(
        self, namespace_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a single namespace visible to a tenant (system-core or its own), with type count.

        Args:
            namespace_id: The namespace row id.
            tenant_id: The caller's tenant id (scopes visibility).

        Returns:
            The namespace row with ``type_count``, or None when missing/not visible.
        """
        query = """
            SELECT n.id, n.tenant_id, n.namespace, n.base_uri, n.version_root,
                   n.description, n.is_system, n.is_public, n.is_default,
                   n.created_by, n.created_at, n.updated_at,
                   (SELECT COUNT(*) FROM apiome.primitives p
                     WHERE p.namespace = n.namespace AND p.tenant_id = %s::uuid) AS type_count
            FROM apiome.type_namespaces n
            WHERE n.id = %s::uuid AND (n.is_system = true OR n.tenant_id = %s::uuid)
        """
        results = self.execute_query(query, (tenant_id, namespace_id, tenant_id))
        return results[0] if results else None

    def get_type_namespace_by_path(
        self, namespace: str, tenant_id: str, is_system: bool
    ) -> Optional[Dict[str, Any]]:
        """Look up a namespace by its path within a scope (for conflict detection).

        Args:
            namespace: The registry path (e.g. tenant/acme/v1/types).
            tenant_id: The owning tenant id (ignored when is_system is True).
            is_system: True to match a system-core path, False to match this tenant's path.

        Returns:
            The matching namespace row, or None.
        """
        if is_system:
            query = """
                SELECT id, tenant_id, namespace, base_uri, version_root, description,
                       is_system, is_public, is_default, created_by, created_at, updated_at
                FROM apiome.type_namespaces
                WHERE is_system = true AND namespace = %s
            """
            results = self.execute_query(query, (namespace,))
        else:
            query = """
                SELECT id, tenant_id, namespace, base_uri, version_root, description,
                       is_system, is_public, is_default, created_by, created_at, updated_at
                FROM apiome.type_namespaces
                WHERE is_system = false AND tenant_id = %s::uuid AND namespace = %s
            """
            results = self.execute_query(query, (tenant_id, namespace))
        return results[0] if results else None

    def create_type_namespace(
        self,
        namespace: str,
        base_uri: str,
        *,
        tenant_id: Optional[str],
        version_root: Optional[str] = None,
        description: Optional[str] = None,
        is_system: bool = False,
        is_public: bool = False,
        is_default: bool = False,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a namespace.

        When ``is_default`` is True, any existing default in the same scope (system-core, or this
        tenant) is cleared first so at most one default exists per scope — done in one transaction.

        Args:
            namespace: The registry path (unique within its scope).
            base_uri: Base URL the namespace's relative $ref values resolve against.
            tenant_id: Owning tenant id; None for a system-core namespace.
            version_root: Version segment (e.g. v1); derived by the caller when omitted.
            description: Optional human description.
            is_system: True for a platform-curated system-core namespace.
            is_public: True when visible to all tenants (always True for system-core).
            is_default: True to make this the default namespace for its scope.
            created_by: The authenticated user id (None for API-key auth).

        Returns:
            The persisted namespace row (with ``type_count`` of 0).
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                if is_default:
                    self._clear_default_type_namespace(cursor, tenant_id, is_system)
                cursor.execute(
                    """
                    INSERT INTO apiome.type_namespaces
                    (tenant_id, namespace, base_uri, version_root, description,
                     is_system, is_public, is_default, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, tenant_id, namespace, base_uri, version_root, description,
                              is_system, is_public, is_default, created_by, created_at, updated_at
                    """,
                    (
                        tenant_id, namespace, base_uri, version_root, description,
                        is_system, is_public, is_default, created_by,
                    ),
                )
                result = cursor.fetchone()
                conn.commit()
                result["type_count"] = 0
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_type_namespace(
        self, namespace_id: str, tenant_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a namespace's mutable fields (base_uri, version_root, description, visibility,
        default), ensuring it belongs to the tenant. The namespace path itself is immutable — it
        links the namespace to its ``apiome.primitives`` rows.

        When ``is_default`` is set True, any existing default in the same scope is cleared first.

        Args:
            namespace_id: The namespace row id.
            tenant_id: The owning tenant id (scopes the write).
            updates: Subset of base_uri / version_root / description / is_public / is_default.

        Returns:
            The updated namespace row with ``type_count``, or None when not found for the tenant.
        """
        allowed = ("base_uri", "version_root", "description", "is_public", "is_default")
        update_fields = []
        params: List[Any] = []
        for field in allowed:
            if field in updates and updates[field] is not None:
                update_fields.append(f"{field} = %s")
                params.append(updates[field])

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                if updates.get("is_default") is True:
                    self._clear_default_type_namespace(cursor, tenant_id, is_system=False)

                if not update_fields:
                    conn.commit()
                    return self.get_type_namespace_by_id(namespace_id, tenant_id)

                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                params.extend([namespace_id, tenant_id])
                cursor.execute(
                    f"""
                    UPDATE apiome.type_namespaces
                    SET {', '.join(update_fields)}
                    WHERE id = %s::uuid AND tenant_id = %s::uuid AND is_system = false
                    RETURNING id
                    """,
                    tuple(params),
                )
                updated = cursor.fetchone()
                conn.commit()
                if not updated:
                    return None
                return self.get_type_namespace_by_id(namespace_id, tenant_id)
        except Exception as e:
            conn.rollback()
            raise e

    @staticmethod
    def _clear_default_type_namespace(cursor, tenant_id: Optional[str], is_system: bool) -> None:
        """Clear the current default namespace in a scope so a new default can be set.

        Runs on the caller's open cursor/transaction. System-core and tenant scopes are disjoint:
        system-core clears where is_system is true; a tenant clears its own rows.
        """
        if is_system:
            cursor.execute(
                "UPDATE apiome.type_namespaces SET is_default = false "
                "WHERE is_system = true AND is_default = true"
            )
        else:
            cursor.execute(
                "UPDATE apiome.type_namespaces SET is_default = false "
                "WHERE tenant_id = %s::uuid AND is_system = false AND is_default = true",
                (tenant_id,),
            )

    # ==================== Type-registry settings (#3472) ====================

    # The mutable settings columns, in one place so the read projection and the upsert write
    # list stay in lock-step (a column added to one but not the other would silently drop).
    TYPE_REGISTRY_SETTINGS_COLUMNS = (
        "default_draft",
        "strict_validation",
        "allow_annotation_keywords",
        "coerce_imported_drafts",
        "resolution_base_url",
        "ref_style",
        "allow_remote_refs",
        "remote_host_allowlist",
        "max_resolution_depth",
        "circular_ref_policy",
        "default_import_scope",
        "default_target_namespace",
        "rewrite_refs_on_import",
        "accepted_formats",
        "dedupe_identical_types",
        "validate_on_save",
        "block_publish_on_errors",
        "core_publish_role",
    )

    def get_type_registry_settings(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a tenant's persisted type-registry settings (#3472).

        Returns the saved row when one exists. A tenant that has never saved settings has no
        row; this returns ``None`` and the route layer serves the model defaults (the GET is a
        pure read and never materializes a row).

        Args:
            tenant_id: The caller's tenant id.

        Returns:
            The settings row, or None when the tenant has not saved settings yet.
        """
        columns = ", ".join(self.TYPE_REGISTRY_SETTINGS_COLUMNS)
        query = f"""
            SELECT {columns}, updated_by, created_at, updated_at
            FROM apiome.type_registry_settings
            WHERE tenant_id = %s::uuid
        """
        results = self.execute_query(query, (tenant_id,))
        return results[0] if results else None

    def upsert_type_registry_settings(
        self, tenant_id: str, updates: Dict[str, Any], updated_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Insert or update a tenant's type-registry settings (#3472).

        The first save for a tenant inserts a row; subsequent saves update only the supplied
        fields and leave the rest untouched (``COALESCE`` keeps the stored value when a column
        is omitted, falling back to the table default on the initial insert). Runs as a single
        upsert keyed on ``tenant_id``.

        Args:
            tenant_id: The owning tenant id.
            updates: Subset of {@link TYPE_REGISTRY_SETTINGS_COLUMNS} to persist; omitted
                columns keep their current value (or the table default on first save).
            updated_by: The authenticated user id making the change (None for API-key auth).

        Returns:
            The full persisted settings row after the write.
        """
        columns = list(self.TYPE_REGISTRY_SETTINGS_COLUMNS)
        # Only the supplied columns get an explicit value; omitted ones fall to their table default
        # on first insert. On conflict we update *only* the supplied columns — an omitted column is
        # left exactly as stored. (We cannot COALESCE over EXCLUDED here: for a column absent from
        # the INSERT list, EXCLUDED.<col> is that column's DEFAULT, not NULL, so a partial update
        # would otherwise reset every untouched column back to its default.)
        supplied = [col for col in columns if col in updates]
        insert_cols = ["tenant_id", "updated_by", *supplied]
        insert_vals: List[Any] = [tenant_id, updated_by, *(updates[col] for col in supplied)]

        set_clauses = [f"{col} = EXCLUDED.{col}" for col in supplied]
        set_clauses.append("updated_by = EXCLUDED.updated_by")
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

        placeholders = ", ".join(["%s"] * len(insert_vals))
        select_cols = ", ".join(columns)
        query = f"""
            INSERT INTO apiome.type_registry_settings ({", ".join(insert_cols)})
            VALUES ({placeholders})
            ON CONFLICT (tenant_id) DO UPDATE SET {", ".join(set_clauses)}
            RETURNING {select_cols}, updated_by, created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(insert_vals))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Project CRUD Operations ====================
    # NOTE: queries below select `change_report_template_version_id`, which requires
    # migration 20260414-150000.sql. Ensure that migration is applied before deploying.

    def get_projects_for_tenant(
        self, tenant_id: str, *, include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all projects for a tenant.

        By default only non-deleted rows are returned. When include_deleted is True,
        soft-deleted projects are included too (active rows first, then deleted).
        """
        deleted_filter = "" if include_deleted else "AND p.deleted_at IS NULL"
        order_clause = (
            "ORDER BY (p.deleted_at IS NULL) DESC, p.created_at DESC"
            if include_deleted
            else "ORDER BY p.created_at DESC"
        )
        query = f"""
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.publishable,
                   p.created_at, p.updated_at,
                   p.deleted_at,
                   u.name as creator_name, u.email as creator_email,
                   qs.quality_score, qs.quality_grade
            FROM apiome.projects p
            LEFT JOIN apiome.users u ON p.creator_id = u.id
            LEFT JOIN LATERAL (
                SELECT v.quality_score, v.quality_grade
                FROM apiome.versions v
                WHERE v.project_id = p.id AND v.deleted_at IS NULL
                ORDER BY v.created_at DESC NULLS LAST, v.id DESC
                LIMIT 1
            ) qs ON TRUE
            WHERE p.tenant_id = %s {deleted_filter}
            {order_clause}
        """
        return self.execute_query(query, (tenant_id,))

    # The columns a catalog item projects off its latest live revision (MFI-7.1/7.2): the captured
    # lint score/grade plus what *kind* of API it is and the format provenance. Shared by the list
    # and single-item catalog reads so both surfaces project an identical shape.
    _CATALOG_VERSION_LATERAL = """
            LEFT JOIN LATERAL (
                SELECT v.quality_score, v.quality_grade,
                       v.source_format, v.protocol, v.format_metadata,
                       v.source_tool_versions AS tool_versions
                FROM apiome.versions v
                WHERE v.project_id = p.id AND v.deleted_at IS NULL
                ORDER BY v.created_at DESC NULLS LAST, v.id DESC
                LIMIT 1
            ) cv ON TRUE
    """

    #: Latest convert-to-OpenAPI provenance for a catalog item (MFI-23.11), joined to the target
    #: publishable Project for its display name/slug/deleted state. A catalog item that has been
    #: converted (apiome.conversion_provenance, MFI-22.5) carries a back-link to the Project it produced,
    #: so the Catalog card/detail can show "Converted -> {project}". LEFT JOINs so an unconverted item
    #: simply yields NULLs (no conversion). ``conv_*`` columns are consumed by the catalog routes.
    _CATALOG_CONVERSION_LATERAL = """
            LEFT JOIN LATERAL (
                SELECT cp.target_project_id, cp.target_version_id, cp.target_version_label,
                       cp.reconverted, cp.fidelity_grade, cp.fidelity_tier, cp.created_at
                FROM apiome.conversion_provenance cp
                WHERE cp.tenant_id = p.tenant_id AND cp.source_project_id = p.id
                ORDER BY cp.created_at DESC
                LIMIT 1
            ) conv ON TRUE
            LEFT JOIN apiome.projects tp ON tp.id = conv.target_project_id
    """

    #: The ``conv_*`` / ``conv_target_*`` SELECT list projecting the conversion lateral above onto
    #: stable, prefixed column names the routes build a :class:`CatalogConversionRef` from.
    _CATALOG_CONVERSION_COLUMNS = """
                   conv.target_project_id AS conv_target_project_id,
                   conv.target_version_id AS conv_target_version_id,
                   conv.target_version_label AS conv_target_version_label,
                   conv.reconverted AS conv_reconverted,
                   conv.fidelity_grade AS conv_fidelity_grade,
                   conv.fidelity_tier AS conv_fidelity_tier,
                   conv.created_at AS conv_converted_at,
                   tp.name AS conv_target_project_name,
                   tp.slug AS conv_target_project_slug,
                   tp.deleted_at AS conv_target_project_deleted_at
    """

    def get_catalog_items_for_tenant(
        self, tenant_id: str, *, include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """List a tenant's catalog items (MFI-23.1): the ``publishable = false`` slice of projects.

        A catalog item is a projection over the same ``projects`` + ``versions`` tables a Project
        uses, so this mirrors :meth:`get_projects_for_tenant` (creator join, latest-revision quality
        score, soft-delete handling) but (a) filters to non-publishable rows and (b) also projects
        the latest revision's ``source_format`` / ``protocol`` / ``format_metadata`` /
        ``tool_versions`` so the Catalog screen can show each item's format/protocol/source. Live
        rows only by default; ``include_deleted`` appends soft-deleted items (active first).
        """
        deleted_filter = "" if include_deleted else "AND p.deleted_at IS NULL"
        order_clause = (
            "ORDER BY (p.deleted_at IS NULL) DESC, p.created_at DESC"
            if include_deleted
            else "ORDER BY p.created_at DESC"
        )
        query = f"""
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.publishable,
                   p.created_at, p.updated_at, p.deleted_at,
                   u.name as creator_name, u.email as creator_email,
                   cv.quality_score, cv.quality_grade,
                   cv.source_format, cv.protocol, cv.format_metadata, cv.tool_versions,
                   {self._CATALOG_CONVERSION_COLUMNS}
            FROM apiome.projects p
            LEFT JOIN apiome.users u ON p.creator_id = u.id
            {self._CATALOG_VERSION_LATERAL}
            {self._CATALOG_CONVERSION_LATERAL}
            WHERE p.tenant_id = %s AND p.publishable = false {deleted_filter}
            {order_clause}
        """
        return self.execute_query(query, (tenant_id,))

    def get_catalog_item_by_id(
        self, item_id: str, tenant_id: str, *, include_deleted: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get a single catalog item by id, scoped to the tenant (MFI-23.1).

        Like :meth:`get_project_by_id` but restricted to non-publishable rows and carrying the
        latest revision's format/protocol/source projection. Returns ``None`` when no non-publishable
        project with that id exists for the tenant (a publishable Project is *not* a catalog item and
        is intentionally not returned here).
        """
        deleted_clause = "" if include_deleted else "AND p.deleted_at IS NULL"
        query = f"""
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.publishable,
                   p.created_at, p.updated_at, p.deleted_at,
                   u.name as creator_name, u.email as creator_email,
                   cv.quality_score, cv.quality_grade,
                   cv.source_format, cv.protocol, cv.format_metadata, cv.tool_versions,
                   {self._CATALOG_CONVERSION_COLUMNS}
            FROM apiome.projects p
            LEFT JOIN apiome.users u ON p.creator_id = u.id
            {self._CATALOG_VERSION_LATERAL}
            {self._CATALOG_CONVERSION_LATERAL}
            WHERE p.id = %s AND p.tenant_id = %s AND p.publishable = false {deleted_clause}
        """
        results = self.execute_query(query, (item_id, tenant_id))
        return results[0] if results else None

    def set_version_quality_score(
        self,
        version_record_id: str,
        tenant_id: str,
        score: int,
        grade: str,
        report_fingerprint: Optional[str] = None,
    ) -> bool:
        """Persist the captured quality/lint score onto a revision (#3609 follow-up).

        Scoped to ``tenant_id`` via the owning project so a caller cannot write a score onto another
        tenant's revision. Returns True when a row was updated.
        """
        query = """
            UPDATE apiome.versions v
            SET quality_score = %s,
                quality_grade = %s,
                quality_report_fingerprint = %s,
                updated_at = CURRENT_TIMESTAMP
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
            RETURNING v.id
        """
        rows = self.execute_query(
            query, (score, grade, report_fingerprint, version_record_id, tenant_id)
        )
        return bool(rows)

    def set_version_source_format(
        self,
        version_record_id: str,
        tenant_id: str,
        source_format: Optional[str] = None,
        protocol: Optional[str] = None,
        format_metadata: Optional[Dict[str, Any]] = None,
        source_tool_versions: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist a revision's source format / protocol / format provenance (MFI-7.1/7.2, MFI-23.1).

        The import path captures what *kind* of API a revision came from (``source_format`` /
        ``protocol``) plus the format-specific metadata bag and tool-version provenance. Catalog
        items (MFI-23.1) project these off their latest revision, so a non-OpenAPI import is
        retrievable with its format/protocol/source. Scoped to ``tenant_id`` via the owning project
        so a caller cannot write onto another tenant's revision.

        ``format_metadata`` / ``source_tool_versions`` are JSONB columns that never accept NULL
        (they default to ``{}``); passing ``None`` leaves the existing value untouched via COALESCE.

        Returns:
            True when a matching live revision was updated, False otherwise.
        """
        import json
        format_metadata_json = json.dumps(format_metadata) if format_metadata is not None else None
        tool_versions_json = (
            json.dumps(source_tool_versions) if source_tool_versions is not None else None
        )
        query = """
            UPDATE apiome.versions v
            SET source_format = COALESCE(%s, v.source_format),
                protocol = COALESCE(%s, v.protocol),
                format_metadata = COALESCE(%s::jsonb, v.format_metadata),
                source_tool_versions = COALESCE(%s::jsonb, v.source_tool_versions),
                updated_at = CURRENT_TIMESTAMP
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
            RETURNING v.id
        """
        rows = self.execute_query(
            query,
            (
                source_format,
                protocol,
                format_metadata_json,
                tool_versions_json,
                version_record_id,
                tenant_id,
            ),
        )
        return bool(rows)

    def get_version_quality_score(
        self, version_record_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Read the captured quality/lint score persisted on a revision (MFI-4.4 surfacing).

        Returns the ``quality_score`` / ``quality_grade`` / ``quality_report_fingerprint`` that
        was rolled up and stored at import time (#3609 for specs, MFI-4.2 for canonical models)
        so all three surfaces (REST, ADE, CLI) can show the *authoritative persisted* score for a
        version rather than only a live recompute. Scoped to ``tenant_id`` via the owning project
        so a caller cannot read another tenant's revision.

        Args:
            version_record_id: The ``versions.id`` (revision UUID) to read.
            tenant_id: The tenant that must own the revision's project.

        Returns:
            A dict with keys ``quality_score`` (int or None), ``quality_grade`` (str or None), and
            ``quality_report_fingerprint`` (str or None) when the revision exists; ``None`` when
            no matching revision is found for the tenant. A revision that has never been scored
            yields a dict whose three values are all ``None``.
        """
        if not version_record_id or not is_uuid_string(str(version_record_id)):
            return None
        query = """
            SELECT v.quality_score, v.quality_grade, v.quality_report_fingerprint
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        """
        rows = self.execute_query(query, (version_record_id, tenant_id))
        return rows[0] if rows else None

    def get_project_by_id(
        self, project_id: str, tenant_id: str, *, include_deleted: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get a specific project by ID, ensuring it belongs to the tenant."""
        deleted_clause = "" if include_deleted else "AND p.deleted_at IS NULL"
        query = f"""
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.publishable,
                   p.created_at, p.updated_at,
                   p.deleted_at,
                   u.name as creator_name, u.email as creator_email
            FROM apiome.projects p
            LEFT JOIN apiome.users u ON p.creator_id = u.id
            WHERE p.id = %s AND p.tenant_id = %s {deleted_clause}
        """
        results = self.execute_query(query, (project_id, tenant_id))
        return results[0] if results else None

    def get_project_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific project by slug, ensuring it belongs to the tenant."""
        query = """
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.publishable,
                   p.created_at, p.updated_at,
                   u.name as creator_name, u.email as creator_email
            FROM apiome.projects p
            LEFT JOIN apiome.users u ON p.creator_id = u.id
            WHERE p.slug = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
        """
        results = self.execute_query(query, (slug, tenant_id))
        return results[0] if results else None

    def create_project(
        self,
        tenant_id: str,
        creator_id: Optional[str],
        name: str,
        slug: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        publishable: bool = True,
    ) -> Dict[str, Any]:
        """Create a new project.

        ``publishable`` is the Project-vs-Catalog boundary (MFI-23.1): pass ``True`` (the default,
        preserving today's behaviour) for an OpenAPI/Swagger Project, ``False`` to create a
        non-publishable catalog item (an OpenAPI-worthy non-OpenAPI import, routed here by MFI-23.7).
        The flag is write-once — a database trigger rejects any later change — so a catalog item can
        never be promoted to a publishable Project except via the MFI-EPIC-22 convert flow.
        """
        import json
        query = """
            INSERT INTO apiome.projects
            (tenant_id, creator_id, name, description, slug, metadata, publishable)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, creator_id, name, description, slug,
                      enabled, metadata, change_report_template_version_id, publishable,
                      created_at, updated_at
        """
        metadata_json = json.dumps(metadata) if metadata else '{}'

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (tenant_id, creator_id, name, description, slug.lower(), metadata_json, publishable)
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_project(
        self,
        project_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an existing project, ensuring it belongs to the tenant."""
        import json

        # First verify the project belongs to the tenant
        existing = self.get_project_by_id(project_id, tenant_id)
        if not existing:
            return None

        # Build dynamic update query
        update_fields = []
        params = []

        if 'name' in updates and updates['name'] is not None:
            update_fields.append("name = %s")
            params.append(updates['name'])
        if 'description' in updates:
            update_fields.append("description = %s")
            params.append(updates['description'])
        if 'slug' in updates and updates['slug'] is not None:
            update_fields.append("slug = %s")
            params.append(updates['slug'].lower())
        if 'enabled' in updates and updates['enabled'] is not None:
            update_fields.append("enabled = %s")
            params.append(updates['enabled'])
        if 'metadata' in updates:
            update_fields.append("metadata = %s")
            params.append(json.dumps(updates['metadata']) if updates['metadata'] else '{}')
        if 'change_report_template_version_id' in updates:
            update_fields.append("change_report_template_version_id = %s")
            params.append(updates['change_report_template_version_id'])

        if not update_fields:
            # Nothing to update, return current project
            return existing

        # Always update updated_at
        update_fields.append("updated_at = CURRENT_TIMESTAMP")

        params.extend([project_id, tenant_id])
        query = f"""
            UPDATE apiome.projects
            SET {', '.join(update_fields)}
            WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
            RETURNING id, tenant_id, creator_id, name, description, slug,
                      enabled, metadata, change_report_template_version_id, publishable,
                      created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_project(self, project_id: str, tenant_id: str) -> bool:
        """Soft delete a project, ensuring it belongs to the tenant."""
        query = """
            UPDATE apiome.projects
            SET pre_delete_enabled = enabled, enabled = false,
                deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (project_id, tenant_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def restore_project(self, project_id: str, tenant_id: str) -> bool:
        """Clear soft-delete on a project, restoring its pre-delete enabled state."""
        query = """
            UPDATE apiome.projects
            SET deleted_at = NULL,
                enabled = COALESCE(pre_delete_enabled, TRUE),
                pre_delete_enabled = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND tenant_id = %s AND deleted_at IS NOT NULL
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (project_id, tenant_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Version CRUD Operations ====================

    def get_versions_for_project(
        self,
        project_id: str,
        tenant_id: str,
        lifecycle: Optional[str] = None,
        *,
        message_q: Optional[str] = None,
        creator_id: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get all versions for a project, ensuring project belongs to tenant.

        Optional lifecycle filter (#739). Optional history filters (#2579): substring match on
        revision note / changelog / commit message body, creator id, and created_at range.
        """
        lifecycle_clause = ""
        params: List[Any] = [project_id, tenant_id]
        if lifecycle:
            lifecycle_clause = f" AND {sql_effective_lifecycle_expr('v')} = %s"
            params.append(lifecycle.strip().lower())

        message_clause = ""
        mq = (message_q or "").strip()
        if mq:
            message_clause = """
              AND (
                strpos(lower(COALESCE(v.description, '')), lower(%s)) > 0
                OR strpos(lower(COALESCE(v.change_log, '')), lower(%s)) > 0
                OR strpos(lower(COALESCE(v.commit_message, '')), lower(%s)) > 0
                OR strpos(lower(COALESCE(v.commit_author, '')), lower(%s)) > 0
              )
            """
            params.extend([mq, mq, mq, mq])

        creator_clause = ""
        cid = (creator_id or "").strip()
        if cid:
            creator_clause = " AND v.creator_id = %s"
            params.append(cid)

        created_after_clause = ""
        if created_after is not None:
            created_after_clause = " AND v.created_at >= %s"
            params.append(created_after)

        created_before_clause = ""
        if created_before is not None:
            created_before_clause = " AND v.created_at <= %s"
            params.append(created_before)

        query = f"""
            SELECT v.id, v.project_id, v.creator_id, v.version_id, v.description,
                   v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                   v.enabled, v.parent_version_id, v.merge_parent_version_id,
                   v.forked_from_revision_id, v.upstream_project_id,
                   v.revision_locked, v.metadata,
                   v.commit_author, v.commit_message, v.external_ref,
                   v.source_commit_sha, v.source_committed_at,
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN apiome.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN apiome.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN apiome.users u ON v.creator_id = u.id
            WHERE v.project_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              {lifecycle_clause}
              {message_clause}
              {creator_clause}
              {created_after_clause}
              {created_before_clause}
            ORDER BY v.created_at DESC
        """
        return self.execute_query(query, tuple(params))

    def list_sunset_timeline_entries(
        self, tenant_id: str, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Schema revisions with deprecation and/or a sunset date (#508).
        """
        project_filter = ""
        params: List[Any] = [tenant_id]
        if project_id:
            project_filter = " AND v.project_id = %s"
            params.append(project_id)

        query = f"""
            SELECT v.id, v.project_id, v.version_id, v.metadata, v.published,
                   p.name AS project_name, p.slug AS project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              {project_filter}
              AND (
                COALESCE(v.metadata->>'deprecated', '') IN ('true', '1', 'True', 'yes')
                OR (v.metadata @> '{{"deprecated": true}}'::jsonb)
                OR NULLIF(trim(COALESCE(v.metadata->>'sunsetDate', v.metadata->>'sunset_date', '')), '') IS NOT NULL
              )
            ORDER BY p.name ASC, v.version_id ASC
        """
        return self.execute_query(query, tuple(params))

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific version by ID, ensuring it belongs to the tenant."""
        # A non-UUID identifier (e.g. a version string like '0.0.1' sent to a route that
        # expects the version record UUID) can never match v.id and would otherwise raise
        # psycopg2 InvalidTextRepresentation -> a 500. Treat it as "not found" instead.
        if not version_id or not is_uuid_string(str(version_id)):
            return None
        query = """
            SELECT v.id, v.project_id, v.creator_id, v.version_id, v.description,
                   v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                   v.enabled, v.parent_version_id, v.merge_parent_version_id,
                   v.forked_from_revision_id, v.upstream_project_id,
                   v.revision_locked, v.metadata,
                   v.commit_author, v.commit_message, v.external_ref,
                   v.source_commit_sha, v.source_committed_at,
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN apiome.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN apiome.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN apiome.users u ON v.creator_id = u.id
            WHERE v.id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        """
        results = self.execute_query(query, (version_id, tenant_id))
        return results[0] if results else None

    def get_version_by_version_id(self, project_id: str, version_id_str: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific version by version_id string (e.g., '1.0.0'), ensuring it belongs to tenant."""
        query = """
            SELECT v.id, v.project_id, v.creator_id, v.version_id, v.description,
                   v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                   v.enabled, v.parent_version_id, v.merge_parent_version_id,
                   v.forked_from_revision_id, v.upstream_project_id,
                   v.revision_locked, v.metadata,
                   v.commit_author, v.commit_message, v.external_ref,
                   v.source_commit_sha, v.source_committed_at,
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN apiome.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN apiome.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN apiome.users u ON v.creator_id = u.id
            WHERE v.project_id = %s
              AND v.version_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        """
        results = self.execute_query(query, (project_id, version_id_str, tenant_id))
        return results[0] if results else None

    def revision_has_protected_named_ref(
        self, version_row_id: str, project_id: str, tenant_id: str
    ) -> bool:
        """
        True if this revision is the tip of a protected branch or the target of a protected tag (#504).
        Used to block successor redirection off an immutable anchor (#749).
        """
        q_branch = """
            SELECT 1 FROM apiome.version_branches b
            INNER JOIN apiome.projects p ON p.id = b.project_id AND p.deleted_at IS NULL
            WHERE b.project_id = %s AND b.tip_version_id = %s AND b.protected = TRUE
              AND p.tenant_id = %s
            LIMIT 1
        """
        q_tag = """
            SELECT 1 FROM apiome.version_tags t
            INNER JOIN apiome.projects p ON p.id = t.project_id AND p.deleted_at IS NULL
            WHERE t.project_id = %s AND t.version_id = %s AND t.protected = TRUE
              AND p.tenant_id = %s
            LIMIT 1
        """
        if self.execute_query(q_branch, (project_id, version_row_id, tenant_id)):
            return True
        if self.execute_query(q_tag, (project_id, version_row_id, tenant_id)):
            return True
        return False

    def resolve_successor_revision_chain(
        self,
        start_version_id: str,
        tenant_id: str,
        project_id: str,
        *,
        max_hops: int = 32,
    ) -> Tuple[str, List[str], str, Optional[str]]:
        """
        Walk ``metadata.successorRevisionId`` from ``start_version_id`` (#749).

        Returns ``(final_id, hop_targets, status, missing_successor_id)`` where ``hop_targets`` lists
        each successor revision id visited in order. ``missing_successor_id`` is set when ``status``
        is ``missing_target`` (pointer to a deleted or unknown revision).
        """
        current = start_version_id
        visited: Set[str] = {start_version_id}
        hops: List[str] = []

        for _ in range(max_hops + 1):
            row = self.get_version_by_id(current, tenant_id)
            if not row:
                return current, hops, "missing_target", None
            if str(row.get("project_id")) != project_id:
                return current, hops, "project_mismatch", None

            succ = successor_revision_id_from_metadata(row.get("metadata"))
            if not succ:
                st = "none" if not hops else "resolved"
                return current, hops, st, None

            if self.revision_has_protected_named_ref(current, project_id, tenant_id):
                return current, hops, "blocked_protected_ref", None

            if succ in visited:
                return current, hops, "cycle", None

            nxt = self.get_version_by_id(succ, tenant_id)
            if not nxt:
                return current, hops, "missing_target", succ
            if str(nxt.get("project_id")) != project_id:
                return current, hops, "project_mismatch", None

            hops.append(succ)
            visited.add(succ)
            current = succ

        return current, hops, "max_hops_exceeded", None

    def get_latest_version_for_project(self, project_id: str, tenant_id: str) -> Optional[str]:
        """Get the latest version_id string for a project."""
        query = """
            SELECT v.version_id
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.project_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
            ORDER BY v.created_at DESC
            LIMIT 1
        """
        results = self.execute_query(query, (project_id, tenant_id))
        return results[0]['version_id'] if results else None

    def create_version(
        self,
        project_id: str,
        creator_id: Optional[str],
        version_id: str,
        description: Optional[str] = None,
        change_log: Optional[str] = None,
        commit_author: Optional[str] = None,
        commit_message: Optional[str] = None,
        external_ref: Optional[str] = None,
        source_commit_sha: Optional[str] = None,
        source_committed_at: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Create a new version.

        ``source_commit_sha`` / ``source_committed_at`` record RAR-4.2 refresh
        provenance: the repository source commit that produced this revision. Both
        default to ``None`` for hand-authored / non-repository revisions.
        """
        query = """
            INSERT INTO apiome.versions
            (project_id, creator_id, version_id, description, change_log,
             commit_author, commit_message, external_ref,
             source_commit_sha, source_committed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, creator_id, version_id, description,
                      change_log, visibility, published, published_at,
                      enabled, parent_version_id, merge_parent_version_id,
                      commit_author, commit_message, external_ref,
                      source_commit_sha, source_committed_at,
                      created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        project_id,
                        creator_id,
                        version_id,
                        description,
                        change_log,
                        commit_author,
                        commit_message,
                        external_ref,
                        source_commit_sha,
                        source_committed_at,
                    ),
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def apply_version_refresh_provenance(
        self,
        version_record_id: str,
        tenant_id: str,
        *,
        parent_version_id: Optional[str] = None,
        source_commit_sha: Optional[str] = None,
        source_committed_at: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Stamp RAR-4.2 refresh provenance onto an existing version row.

        A repository auto-refresh creates the new version through the import worker;
        this records the refresh lineage on that row afterwards: the prior version it
        supersedes (``parent_version_id``) and the source commit that triggered it
        (``source_commit_sha`` + ``source_committed_at``). The update is tenant-scoped
        via the owning project so a refresh cannot stamp another tenant's version.

        Only non-``None`` arguments are written; passing ``None`` leaves the existing
        column untouched (so a parent already set by the importer is preserved when a
        caller stamps only the commit signals).

        Args:
            version_record_id: The version row id (``versions.id``) to stamp.
            tenant_id: The tenant that must own the version's project.
            parent_version_id: Prior version this refresh supersedes; the new
                version's linear parent.
            source_commit_sha: Repository source commit SHA that triggered the refresh.
            source_committed_at: Commit timestamp of ``source_commit_sha``.

        Returns:
            The updated version row (via :meth:`get_version_by_id`), or ``None`` when
            no version matches the id within the tenant.
        """
        sets: List[str] = []
        params: List[Any] = []
        if parent_version_id is not None:
            sets.append("parent_version_id = %s")
            params.append(parent_version_id)
        if source_commit_sha is not None:
            sets.append("source_commit_sha = %s")
            params.append(source_commit_sha)
        if source_committed_at is not None:
            sets.append("source_committed_at = %s")
            params.append(source_committed_at)

        if not sets:
            # Nothing to record — return the current row unchanged.
            return self.get_version_by_id(version_record_id, tenant_id)

        sets.append("updated_at = CURRENT_TIMESTAMP")
        query = f"""
            UPDATE apiome.versions v
            SET {", ".join(sets)}
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
            RETURNING v.id
        """
        params.extend([version_record_id, tenant_id])

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
                conn.commit()
                if not row:
                    return None
                return self.get_version_by_id(version_record_id, tenant_id)
        except Exception as e:
            conn.rollback()
            raise e

    def create_forked_version(
        self,
        target_project_id: str,
        tenant_id: str,
        creator_id: Optional[str],
        version_id: str,
        description: Optional[str],
        change_log: Optional[str],
        source_revision_id: str,
        upstream_project_id: Optional[str],
        commit_author: Optional[str] = None,
        commit_message: Optional[str] = None,
        external_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new version in target_project_id as a fork of source_revision_id (cross-project).
        Copies classes from the source revision. Sets fork lineage columns; parent_version_id stays NULL (new root in target project).
        """
        source = self.get_version_by_id(source_revision_id, tenant_id)
        if not source:
            return {"success": False, "error": "Source revision not found or not accessible"}

        src_project_id = source["project_id"]
        if src_project_id == target_project_id:
            return {
                "success": False,
                "error": "Fork requires a different target project than the source. Use “Branch from here” for named branches within the same project.",
            }

        target = self.get_project_by_id(target_project_id, tenant_id)
        if not target:
            return {"success": False, "error": "Target project not found"}

        upstream = upstream_project_id if upstream_project_id else src_project_id
        up_proj = self.get_project_by_id(upstream, tenant_id)
        if not up_proj:
            return {"success": False, "error": "Upstream project not found or not accessible"}

        effective_upstream = upstream

        insert_query = """
            INSERT INTO apiome.versions
            (project_id, creator_id, version_id, description, change_log,
             parent_version_id, forked_from_revision_id, upstream_project_id,
             commit_author, commit_message, external_ref)
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s)
            RETURNING id
        """
        conn = self.connect()
        new_id = None
        copied_count = 0
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    insert_query,
                    (
                        target_project_id,
                        creator_id,
                        version_id,
                        description,
                        change_log,
                        source_revision_id,
                        effective_upstream,
                        commit_author,
                        commit_message,
                        external_ref,
                    ),
                )
                row = cursor.fetchone()
                new_id = row["id"] if row else None
                if not new_id:
                    conn.rollback()
                    return {"success": False, "error": "Failed to create forked version"}

                # Copy classes within the same transaction so insert + copy are atomic
                cursor.execute("""
                    INSERT INTO apiome.classes (version_id, name, description, schema, enabled, canvas_metadata)
                    SELECT %s, name, description, schema, enabled, canvas_metadata
                    FROM apiome.classes
                    WHERE version_id = %s AND deleted_at IS NULL
                    RETURNING id, name
                """, (new_id, source_revision_id))

                copied_classes = cursor.fetchall()
                copied_count = len(copied_classes)

                for copied_class in copied_classes:
                    new_class_id = copied_class["id"]
                    class_name = copied_class["name"]

                    cursor.execute("""
                        SELECT id FROM apiome.classes
                        WHERE version_id = %s AND name = %s AND deleted_at IS NULL
                    """, (source_revision_id, class_name))

                    original = cursor.fetchone()
                    if original:
                        original_class_id = original["id"]
                        cursor.execute("""
                            INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, primitive_id, primitive_ref)
                            SELECT %s, property_id, name, description, data, primitive_id, primitive_ref
                            FROM apiome.class_properties
                            WHERE class_id = %s AND parent_id IS NULL
                        """, (new_class_id, original_class_id))

                conn.commit()
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}

        full = self.get_version_by_id(new_id, tenant_id)
        if not full:
            return {"success": False, "error": "Fork created but could not load version"}
        return {"success": True, "version": full, "copied_count": copied_count}

    def _validate_successor_revision_pointer(
        self,
        *,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
        metadata: Dict[str, Any],
    ) -> None:
        """When a sunset is set, successor must point at another revision in the same project (#748)."""
        if not effective_sunset_string(metadata):
            return
        m = coerce_metadata(metadata)
        succ = m.get("successorRevisionId") or m.get("successor_revision_id")
        if not isinstance(succ, str) or not succ.strip():
            return
        succ_id = succ.strip()
        if succ_id == version_record_id:
            raise ValueError("successorRevisionId cannot reference the same revision")
        other = self.get_version_by_id(succ_id, tenant_id)
        if not other or str(other.get("project_id")) != project_id:
            raise ValueError("successorRevisionId must reference another revision in the same project")

    def update_version(
        self,
        version_record_id: str,
        tenant_id: str,
        updates: Dict[str, Any],
        lifecycle_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing version, ensuring it belongs to the tenant."""
        existing = self.get_version_by_id(version_record_id, tenant_id)
        if not existing:
            return None

        if existing.get("published"):
            allowed_only = set(updates.keys()) <= {"revision_locked", "metadata"}
            if not allowed_only:
                raise Exception("Cannot edit a published version. Published versions are frozen.")

        update_fields = []
        params = []

        if "description" in updates:
            update_fields.append("description = %s")
            params.append(updates["description"])
        if "change_log" in updates:
            update_fields.append("change_log = %s")
            params.append(updates["change_log"])
        if "enabled" in updates and updates["enabled"] is not None:
            update_fields.append("enabled = %s")
            params.append(updates["enabled"])
        if "revision_locked" in updates:
            update_fields.append("revision_locked = %s")
            params.append(bool(updates["revision_locked"]))
        if "metadata" in updates and updates["metadata"] is not None:
            merged_meta = prepare_version_metadata_update(
                existing.get("metadata"),
                updates["metadata"],
                allow_exit_archived=lifecycle_admin,
            )
            self._validate_successor_revision_pointer(
                tenant_id=tenant_id,
                project_id=str(existing.get("project_id")),
                version_record_id=version_record_id,
                metadata=merged_meta,
            )
            update_fields.append("metadata = %s::jsonb")
            params.append(json.dumps(merged_meta))

        if not update_fields:
            return existing

        update_fields.append("updated_at = CURRENT_TIMESTAMP")

        params.append(version_record_id)
        query = f"""
            UPDATE apiome.versions
            SET {', '.join(update_fields)}
            WHERE id = %s AND deleted_at IS NULL
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                conn.commit()
                return self.get_version_by_id(version_record_id, tenant_id)
        except Exception as e:
            conn.rollback()
            raise e

    def publish_version(
        self,
        version_record_id: str,
        tenant_id: str,
        user_id: str,
        visibility: str = "private",
        description: Optional[str] = None,
        change_log: Optional[str] = None,
        published_immutable: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Publish a version (only owner or tenant admin can publish). Captures class schemas to apiome.class_schema.

        description and change_log are written in the same update as publish (validated in routes).
        """
        query = """
            UPDATE apiome.versions v
            SET published = true,
                published_at = CURRENT_TIMESTAMP,
                visibility = %s,
                description = %s,
                change_log = %s,
                published_immutable = %s,
                updated_at = CURRENT_TIMESTAMP
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND (
                v.creator_id = %s
                OR EXISTS (
                  SELECT 1 FROM apiome.tenant_administrators ta
                  WHERE ta.tenant_id = p.tenant_id AND ta.user_id = %s
                )
              )
            RETURNING v.id, v.project_id, v.creator_id, v.version_id, v.description,
                      v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                      v.enabled, v.commit_author, v.commit_message, v.external_ref,
                      v.source_commit_sha, v.source_committed_at,
                      v.created_at, v.updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        visibility,
                        description,
                        change_log,
                        published_immutable,
                        version_record_id,
                        tenant_id,
                        user_id,
                        user_id,
                    ),
                )
                result = cursor.fetchone()
                if result:
                    # Capture frozen JSON Schema 2020-12 per class into class_schema
                    cursor.execute("""
                        SELECT v.version_id, p.slug AS project_slug, t.slug AS tenant_slug
                        FROM apiome.versions v
                        JOIN apiome.projects p ON v.project_id = p.id
                        JOIN apiome.tenants t ON p.tenant_id = t.id
                        WHERE v.id = %s
                    """, (version_record_id,))
                    slug_row = cursor.fetchone()
                    if slug_row:
                        classes = self.get_classes_with_properties_and_tags_for_version(version_record_id)
                        for class_data in classes:
                            schema_dict = generate_class_jsonschema_spec(
                                slug_row['tenant_slug'],
                                slug_row['project_slug'],
                                slug_row['version_id'],
                                class_data,
                                class_data.get('properties', []),
                            )
                            schema_json = json.dumps(schema_dict)
                            cursor.execute("""
                                INSERT INTO apiome.class_schema (version_id, class_id, schema, updated_at)
                                VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                                ON CONFLICT (version_id, class_id)
                                DO UPDATE SET schema = EXCLUDED.schema, updated_at = CURRENT_TIMESTAMP
                            """, (version_record_id, class_data['id'], schema_json))
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def version_has_data_records(self, version_record_id: str) -> bool:
        """Return True if any data_record exists for class_schema rows belonging to this version."""
        query = """
            SELECT 1
            FROM apiome.data_record dr
            JOIN apiome.class_schema cs ON dr.class_schema_id = cs.id
            WHERE cs.version_id = %s
            LIMIT 1
        """
        results = self.execute_query(query, (version_record_id,))
        return len(results) > 0

    def version_has_class_schema(self, version_record_id: str) -> bool:
        """Return True if any class_schema row exists for this version (schema already frozen)."""
        query = """
            SELECT 1 FROM apiome.class_schema WHERE version_id = %s LIMIT 1
        """
        results = self.execute_query(query, (version_record_id,))
        return len(results) > 0

    # ------------------------- Data records & data_snapshot (embedding in REST) -------------------------

    def assert_class_schema_tenant_access(self, class_schema_id: str, tenant_id: str) -> bool:
        """Return True if class_schema_id belongs to a version in a project under the tenant."""
        query = """
            SELECT 1 FROM apiome.class_schema cs
            JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
            WHERE cs.id = %s
        """
        results = self.execute_query(query, (tenant_id, class_schema_id))
        return len(results) > 0

    def get_class_schema_tenant_info(self, class_schema_id: str) -> Optional[Dict[str, Any]]:
        """Return class_schema row and its version's project tenant_id if it exists; None otherwise."""
        query = """
            SELECT cs.id, cs.version_id, p.tenant_id AS project_tenant_id
            FROM apiome.class_schema cs
            JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
            WHERE cs.id = %s
        """
        results = self.execute_query(query, (class_schema_id,))
        return results[0] if results else None

    def get_class_schema_by_id(self, class_schema_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a single class_schema row by id. Returns None if not found or tenant has no access."""
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            return None
        query = """
            SELECT cs.id AS class_schema_id, cs.class_id, c.name AS class_name, cs.schema
            FROM apiome.class_schema cs
            JOIN apiome.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
            JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
            WHERE cs.id = %s
        """
        results = self.execute_query(query, (tenant_id, class_schema_id))
        if not results:
            return None
        row = results[0]
        return {
            "class_schema_id": row["class_schema_id"],
            "class_id": row["class_id"],
            "class_name": row["class_name"],
            "schema": row["schema"] if isinstance(row["schema"], dict) else {},
        }

    def insert_data_record(
        self,
        class_schema_id: str,
        tenant_id: str,
        data: Dict[str, Any],
        created_by: Optional[str] = None,
    ) -> str:
        """
        Insert a new record: one data_record (action 'created', record_sequence 1) and one data_snapshot row.
        Returns record_id. Raises if tenant has no access to the class_schema.
        """
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            raise ValueError("Access denied to class schema")
        import uuid
        record_id = str(uuid.uuid4())
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'created', 1, %s::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, json.dumps(data), tenant_id, created_by),
                )
                cursor.execute(
                    """
                    INSERT INTO apiome.data_snapshot (record_id, class_schema_id, data, tenant_id)
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    (record_id, class_schema_id, json.dumps(data), tenant_id),
                )
                conn.commit()
            return record_id
        except Exception as e:
            conn.rollback()
            raise e

    def get_data_snapshot(
        self,
        record_id: str,
        class_schema_id: str,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the current data_snapshot row for a record (data only).
        Returns None if tenant has no access or record not found (e.g. deleted).
        """
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            return None
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT data FROM apiome.data_snapshot
                    WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = row["data"]
                return {"data": data} if data is not None else {"data": {}}
        finally:
            conn.close()

    def update_data_record(
        self,
        record_id: str,
        class_schema_id: str,
        tenant_id: str,
        data: Dict[str, Any],
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Update an existing record: compute delta vs current snapshot; if no changes, return False.
        Otherwise append data_record (action 'updated', data = delta only), update data_snapshot with full data,
        and return True. Raises if tenant has no access or record not found.
        """
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            raise ValueError("Access denied to class schema")
        snapshot = self.get_data_snapshot(record_id, class_schema_id, tenant_id)
        if not snapshot:
            raise ValueError("Record not found")
        old_data = snapshot.get("data") or {}
        if not isinstance(old_data, dict):
            old_data = {}
        delta = _compute_delta(old_data, data)
        if not delta:
            return False
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(record_sequence), 0) + 1 AS next_seq
                    FROM apiome.data_record WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                row = cursor.fetchone()
                next_seq = row["next_seq"] if row else 1
                cursor.execute(
                    """
                    UPDATE apiome.data_snapshot
                    SET data = %s::jsonb, updated_at = CURRENT_TIMESTAMP
                    WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (json.dumps(data), record_id, class_schema_id, tenant_id),
                )
                if cursor.rowcount == 0:
                    conn.rollback()
                    raise ValueError("Record not found")
                cursor.execute(
                    """
                    INSERT INTO apiome.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'updated', %s, %s::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, next_seq, json.dumps(delta), tenant_id, updated_by),
                )
                conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e

    def delete_data_record(
        self,
        record_id: str,
        class_schema_id: str,
        tenant_id: str,
        deleted_by: Optional[str] = None,
    ) -> None:
        """
        Delete a record: append data_record (action 'deleted') then remove data_snapshot row.
        Raises if tenant has no access or record not found.
        """
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            raise ValueError("Access denied to class schema")
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT data FROM apiome.data_snapshot
                    WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                snapshot_row = cursor.fetchone()
                if not snapshot_row:
                    conn.rollback()
                    raise ValueError("Record not found")
                current_data = snapshot_row["data"]
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(record_sequence), 0) + 1 AS next_seq
                    FROM apiome.data_record WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                seq_row = cursor.fetchone()
                next_seq = seq_row["next_seq"] if seq_row else 1
                cursor.execute(
                    """
                    INSERT INTO apiome.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'deleted', %s, %s::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, next_seq, json.dumps(current_data or {}), tenant_id, deleted_by),
                )
                cursor.execute(
                    """
                    DELETE FROM apiome.data_snapshot
                    WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def restore_data_record(
        self,
        record_id: str,
        class_schema_id: str,
        tenant_id: str,
        restored_by: Optional[str] = None,
    ) -> None:
        """
        Restore a deleted record: data must have action 'deleted'. Pull data from the
        deleted data_record, insert a new data_snapshot row with that data, and append
        a data_record with action 'restored', data '{}', record_sequence incremented by 1.
        Raises if tenant has no access, record not found, or latest action is not 'deleted'.
        """
        if not self.assert_class_schema_tenant_access(class_schema_id, tenant_id):
            raise ValueError("Access denied to class schema")
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT data, record_sequence, action
                    FROM apiome.data_record
                    WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    ORDER BY record_sequence DESC
                    LIMIT 1
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    raise ValueError("Record not found")
                if row["action"] != "deleted":
                    conn.rollback()
                    raise ValueError("Record is not deleted; only deleted records can be restored")
                data_to_restore = row["data"] or {}
                next_seq = (row["record_sequence"] or 0) + 1

                cursor.execute(
                    """
                    INSERT INTO apiome.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'restored', %s, '{}'::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, next_seq, tenant_id, restored_by),
                )
                cursor.execute(
                    """
                    INSERT INTO apiome.data_snapshot (record_id, class_schema_id, data, tenant_id)
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    (record_id, class_schema_id, json.dumps(data_to_restore), tenant_id),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def update_data_snapshot_embedding(
        self, record_id: str, embedding: List[float], model: str
    ) -> None:
        """
        Update the embedding (and metadata) for a data_snapshot row.
        No-op if embedding is empty. Logs and no-ops if pgvector type is not available.
        """
        if not embedding or len(embedding) == 0:
            return

        if not isinstance(embedding, np.ndarray):
            embedding = np.array(embedding, dtype=np.float32)

        conn = self.connect()

        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception as e:
            print("pgvector not available; embedding update skipped for record_id=", record_id)
            print(f"register_vector failed: {type(e).__name__}: {e}")
            return

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE apiome.data_snapshot
                    SET embedding = %s,
                        embedding_model = %s,
                        embedding_updated_at = CURRENT_TIMESTAMP
                    WHERE record_id = %s
                    """,
                    (embedding, model, record_id),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            code = getattr(e, "pgcode", None) or getattr(e, "code", None)
            msg = str(getattr(e, "message", e) or e)
            if code == "42704" or ("vector" in msg.lower() and "does not exist" in msg.lower()):
                print(
                    "pgvector not available: ", msg, "code=", code, " embedding update skipped for record_id=", record_id
                )
                return
            raise

    def freeze_version_schema(
        self, version_record_id: str, tenant_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Capture class schemas into apiome.class_schema for this version (same as publish capture).
        Only allowed when the version has no class_schema rows yet.
        Returns version dict if successful; None if permission denied or schema already frozen.
        """
        if self.version_has_class_schema(version_record_id):
            return None
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT v.id, v.version_id, p.id AS project_id
                    FROM apiome.versions v
                    JOIN apiome.projects p ON v.project_id = p.id
                    JOIN apiome.tenants t ON p.tenant_id = t.id
                    WHERE v.id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND (v.creator_id = %s OR EXISTS (
                        SELECT 1 FROM apiome.tenant_administrators ta
                        WHERE ta.tenant_id = p.tenant_id AND ta.user_id = %s
                      ))
                    """,
                    (version_record_id, tenant_id, user_id, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute(
                    """
                    SELECT v.version_id, p.slug AS project_slug, t.slug AS tenant_slug
                    FROM apiome.versions v
                    JOIN apiome.projects p ON v.project_id = p.id
                    JOIN apiome.tenants t ON p.tenant_id = t.id
                    WHERE v.id = %s
                    """,
                    (version_record_id,),
                )
                slug_row = cursor.fetchone()
                if not slug_row:
                    return None
                classes = self.get_classes_with_properties_and_tags_for_version(version_record_id)
                for class_data in classes:
                    schema_dict = generate_class_jsonschema_spec(
                        slug_row["tenant_slug"],
                        slug_row["project_slug"],
                        slug_row["version_id"],
                        class_data,
                        class_data.get("properties", []),
                    )
                    schema_json = json.dumps(schema_dict)
                    cursor.execute(
                        """
                        INSERT INTO apiome.class_schema (version_id, class_id, schema, updated_at)
                        VALUES (%s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                        ON CONFLICT (version_id, class_id)
                        DO UPDATE SET schema = EXCLUDED.schema, updated_at = CURRENT_TIMESTAMP
                        """,
                        (version_record_id, class_data["id"], schema_json),
                    )
                conn.commit()
                return self.get_version_by_id(version_record_id, tenant_id)
        except Exception as e:
            conn.rollback()
            raise e

    def unpublish_version(self, version_record_id: str, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Unpublish a version (only owner or tenant admin can unpublish). Call version_has_data_records before this to block when data exists."""
        query = """
            UPDATE apiome.versions v
            SET published = false,
                published_at = NULL,
                published_immutable = false,
                updated_at = CURRENT_TIMESTAMP
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND (
                v.creator_id = %s
                OR EXISTS (
                  SELECT 1 FROM apiome.tenant_administrators ta
                  WHERE ta.tenant_id = p.tenant_id AND ta.user_id = %s
                )
              )
            RETURNING v.id, v.project_id, v.creator_id, v.version_id, v.description,
                      v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                      v.enabled, v.commit_author, v.commit_message, v.external_ref,
                      v.source_commit_sha, v.source_committed_at,
                      v.created_at, v.updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_record_id, tenant_id, user_id, user_id))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def is_user_tenant_admin(self, tenant_id: str, user_id: str) -> bool:
        """True if user is a tenant administrator."""
        q = """
            SELECT 1 FROM apiome.tenant_administrators
            WHERE tenant_id = %s::uuid AND user_id = %s::uuid LIMIT 1
        """
        return bool(self.execute_query(q, (tenant_id, user_id)))

    # ------------------------------------------------------------------
    # Granular RBAC (#3611): roles, permissions, members, access audit
    # ------------------------------------------------------------------

    def user_has_permission(
        self, tenant_id: str, user_id: str, resource: str, action: str
    ) -> bool:
        """
        Central authorization predicate used by the permission guard.

        A tenant administrator (Owner-equivalent / legacy ``tenant_administrators``) is allowed
        everything; otherwise the user's assigned role — or the built-in Editor default for a member
        with no explicit role — must grant ``resource:action``.
        """
        if self.is_user_tenant_admin(tenant_id, user_id):
            return True
        return f"{resource}:{action}" in self.get_effective_permissions(
            tenant_id, user_id
        )

    def _modify(self, query: str, params: tuple = None) -> int:
        """Execute a write that returns no rows (UPDATE/DELETE/INSERT-without-RETURNING).

        Commits on success and returns the affected row count, mirroring ``execute_query``'s
        connection hygiene (a committed write leaves the shared connection IDLE).
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception:
            conn.rollback()
            raise

    def is_platform_admin(self, user_id: Optional[str]) -> bool:
        """True when the user is a platform administrator (the plane separate from tenant admin)."""
        if not user_id:
            return False
        return bool(
            self.execute_query(
                "SELECT 1 FROM apiome.platform_administrators WHERE user_id = %s::uuid LIMIT 1",
                (user_id,),
            )
        )

    def ensure_builtin_roles(self, tenant_id: str) -> None:
        """Idempotently seed the four built-in roles + grids for a tenant (safe to call on every read)."""
        self.execute_query("SELECT apiome.seed_builtin_roles(%s::uuid)", (tenant_id,))

    def get_effective_permissions(self, tenant_id: str, user_id: str) -> Set[str]:
        """
        Resolve a member's granted ``resource:action`` permissions from their assigned role.

        A member with no explicit role assignment inherits the built-in **Editor** grid (any member
        could create/edit content before RBAC). A suspended member has no permissions. Tenant
        administrators are handled upstream by the guard's full-access plane and never reach here.
        """
        rows = self.execute_query(
            """
            SELECT rp.resource, rp.action
            FROM apiome.tenant_user_roles tur
            JOIN apiome.role_permissions rp ON rp.role_id = tur.role_id
            WHERE tur.tenant_id = %s::uuid AND tur.user_id = %s::uuid
            """,
            (tenant_id, user_id),
        )
        if rows:
            return {f"{r['resource']}:{r['action']}" for r in rows}

        member = self.execute_query(
            """
            SELECT 1 FROM apiome.tenant_users
            WHERE tenant_id = %s::uuid AND user_id = %s::uuid AND status <> 'suspended'
            LIMIT 1
            """,
            (tenant_id, user_id),
        )
        if not member:
            return set()

        editor_rows = self.execute_query(
            """
            SELECT rp.resource, rp.action
            FROM apiome.roles r
            JOIN apiome.role_permissions rp ON rp.role_id = r.id
            WHERE r.tenant_id = %s::uuid AND r.slug = 'editor'
            """,
            (tenant_id,),
        )
        return {f"{r['resource']}:{r['action']}" for r in editor_rows}

    def write_access_audit(
        self,
        *,
        tenant_id: Optional[str],
        action: str,
        actor_id: Optional[str] = None,
        actor_label: Optional[str] = None,
        target: Optional[str] = None,
        source: str = "web",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a hash-chained row to ``apiome.access_audit`` (best-effort; callers swallow failures)."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT entry_hash FROM apiome.access_audit
                    WHERE tenant_id IS NOT DISTINCT FROM %s::uuid
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (tenant_id,),
                )
                prev_row = cursor.fetchone()
                prev_hash = prev_row["entry_hash"] if prev_row else None
                detail_json = (
                    json.dumps(detail, sort_keys=True, default=str)
                    if detail is not None
                    else None
                )
                payload = "|".join(
                    [
                        prev_hash or "",
                        str(tenant_id or ""),
                        str(actor_id or actor_label or ""),
                        action,
                        str(target or ""),
                        detail_json or "",
                    ]
                )
                entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO apiome.access_audit
                        (tenant_id, actor_id, actor_label, action, target, source, detail, prev_hash, entry_hash)
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        tenant_id,
                        actor_id,
                        actor_label,
                        action,
                        target,
                        source,
                        detail_json,
                        prev_hash,
                        entry_hash,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def list_access_audit(
        self, tenant_id: str, *, action_prefix: Optional[str] = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Return access-audit rows for a tenant, newest first, optionally filtered by action prefix."""
        params: list = [tenant_id]
        where = "tenant_id = %s::uuid"
        if action_prefix:
            where += " AND action LIKE %s"
            params.append(f"{action_prefix}%")
        params.append(max(1, min(int(limit), 1000)))
        return self.execute_query(
            f"""
            SELECT id::text, actor_id::text, actor_label, action, target, source,
                   detail, created_at
            FROM apiome.access_audit
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            tuple(params),
        )

    # ---- Roles -------------------------------------------------------

    def list_roles(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List a tenant's roles with their assigned-member counts (built-in first, then by name)."""
        return self.execute_query(
            """
            SELECT r.id::text, r.slug, r.name, r.description, r.is_builtin,
                   r.created_at, r.updated_at,
                   (SELECT COUNT(*) FROM apiome.tenant_user_roles tur WHERE tur.role_id = r.id) AS member_count
            FROM apiome.roles r
            WHERE r.tenant_id = %s::uuid
            ORDER BY r.is_builtin DESC,
                     CASE r.slug WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
                                 WHEN 'editor' THEN 2 WHEN 'viewer' THEN 3 ELSE 4 END,
                     r.name ASC
            """,
            (tenant_id,),
        )

    def get_role(self, tenant_id: str, role_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one role scoped to a tenant, or None."""
        rows = self.execute_query(
            """
            SELECT id::text, slug, name, description, is_builtin, created_at, updated_at
            FROM apiome.roles WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            (role_id, tenant_id),
        )
        return rows[0] if rows else None

    def get_role_permissions(self, role_id: str) -> List[Dict[str, str]]:
        """Return the allowed ``resource``/``action`` pairs for a role."""
        return self.execute_query(
            "SELECT resource, action FROM apiome.role_permissions WHERE role_id = %s::uuid",
            (role_id,),
        )

    def create_role(
        self, tenant_id: str, slug: str, name: str, description: Optional[str]
    ) -> Dict[str, Any]:
        """Create a custom (non-built-in) role and return it."""
        rows = self.execute_query(
            """
            INSERT INTO apiome.roles (tenant_id, slug, name, description, is_builtin)
            VALUES (%s::uuid, %s, %s, %s, false)
            RETURNING id::text, slug, name, description, is_builtin, created_at, updated_at
            """,
            (tenant_id, slug, name, description),
        )
        return rows[0]

    def update_role(
        self, tenant_id: str, role_id: str, name: str, description: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Update a role's name/description (built-in or custom). Returns the updated row or None."""
        rows = self.execute_query(
            """
            UPDATE apiome.roles SET name = %s, description = %s
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            RETURNING id::text, slug, name, description, is_builtin, created_at, updated_at
            """,
            (name, description, role_id, tenant_id),
        )
        return rows[0] if rows else None

    def set_role_permissions(self, role_id: str, pairs: List[Tuple[str, str]]) -> None:
        """Replace a role's permission grid with the given ``(resource, action)`` pairs."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM apiome.role_permissions WHERE role_id = %s::uuid", (role_id,)
                )
                for resource, action in pairs:
                    cursor.execute(
                        """
                        INSERT INTO apiome.role_permissions (role_id, resource, action)
                        VALUES (%s::uuid, %s, %s)
                        ON CONFLICT (role_id, resource, action) DO NOTHING
                        """,
                        (role_id, resource, action),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def delete_role(self, tenant_id: str, role_id: str) -> int:
        """Delete a custom role (assignments cascade). Returns rows deleted."""
        return self._modify(
            "DELETE FROM apiome.roles WHERE id = %s::uuid AND tenant_id = %s::uuid AND is_builtin = false",
            (role_id, tenant_id),
        )

    # ---- Members -----------------------------------------------------

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Resolve an active user by email (for member invites)."""
        rows = self.execute_query(
            """
            SELECT id::text, name, email FROM apiome.users
            WHERE lower(email) = lower(%s) AND deleted_at IS NULL
            LIMIT 1
            """,
            (email,),
        )
        return rows[0] if rows else None

    def list_members(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List tenant members with their role, lifecycle status, and admin flag."""
        return self.execute_query(
            """
            SELECT u.id::text AS user_id, u.name, u.email,
                   tu.status,
                   tu.updated_at AS member_since,
                   r.id::text AS role_id, r.name AS role_name, r.slug AS role_slug,
                   EXISTS (
                       SELECT 1 FROM apiome.tenant_administrators ta
                       WHERE ta.tenant_id = tu.tenant_id AND ta.user_id = u.id
                   ) AS is_admin
            FROM apiome.tenant_users tu
            JOIN apiome.users u ON u.id = tu.user_id
            LEFT JOIN apiome.tenant_user_roles tur
                   ON tur.tenant_id = tu.tenant_id AND tur.user_id = tu.user_id
            LEFT JOIN apiome.roles r ON r.id = tur.role_id
            WHERE tu.tenant_id = %s::uuid AND u.deleted_at IS NULL
            ORDER BY u.name ASC
            """,
            (tenant_id,),
        )

    def add_member(self, tenant_id: str, user_id: str, status: str = "active") -> None:
        """Add (or reactivate) a tenant membership with the given lifecycle status."""
        self._modify(
            """
            INSERT INTO apiome.tenant_users (tenant_id, user_id, status)
            VALUES (%s::uuid, %s::uuid, %s)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET status = EXCLUDED.status
            """,
            (tenant_id, user_id, status),
        )

    def set_member_status(self, tenant_id: str, user_id: str, status: str) -> int:
        """Set a member's lifecycle status (active/pending/suspended). Returns rows updated."""
        return self._modify(
            "UPDATE apiome.tenant_users SET status = %s WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
            (status, tenant_id, user_id),
        )

    def assign_member_role(self, tenant_id: str, user_id: str, role_id: str) -> None:
        """Assign (replacing any existing) a role to a tenant member."""
        self._modify(
            """
            INSERT INTO apiome.tenant_user_roles (tenant_id, user_id, role_id)
            VALUES (%s::uuid, %s::uuid, %s::uuid)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET role_id = EXCLUDED.role_id
            """,
            (tenant_id, user_id, role_id),
        )

    def remove_member(self, tenant_id: str, user_id: str) -> int:
        """Offboard a member: drop membership, role assignment, and any tenant-admin row."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM apiome.tenant_user_roles WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
                    (tenant_id, user_id),
                )
                cursor.execute(
                    "DELETE FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
                    (tenant_id, user_id),
                )
                cursor.execute(
                    "DELETE FROM apiome.tenant_users WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
                    (tenant_id, user_id),
                )
                affected = cursor.rowcount
            conn.commit()
            return affected
        except Exception:
            conn.rollback()
            raise

    def tenant_has_feature_flag(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        flag_name: str,
    ) -> bool:
        """Resolve whether a tenant/user is entitled to a named feature flag (#3478).

        Effective entitlement layers, highest precedence first:

        1. Per-user override (``apiome.user_feature_flags.enabled``) — an admin explicitly
           granting or revoking the flag for this user.
        2. Per-tenant override (``apiome.tenant_feature_flags.enabled``) — all members of the
           tenant inherit this unless a user override exists.
        3. License default (``apiome.license_feature_flags`` via ``user_entitlements.license_id``)
           — the flag is bundled into the user's assigned plan.

        The flag's global master switch (``apiome.feature_flags.enabled``) is honored: a missing
        or globally-disabled flag is never entitled, regardless of overrides. ``user_id`` may be
        ``None`` (e.g. a legacy API key without an attributed user), in which case only the
        tenant-level override is consulted.

        Args:
            tenant_id: The acting tenant's id (``None`` skips the tenant-override lookup).
            user_id: The acting user's id (``None`` skips user-override and license lookups).
            flag_name: The feature flag slug, e.g. ``"primitives-registry"``.

        Returns:
            True when the flag is globally enabled and the resolved entitlement grants it.
        """
        row = self.execute_query(
            """
            WITH ff AS (
                SELECT id, enabled FROM apiome.feature_flags WHERE name = %s
            )
            SELECT
                ff.enabled                          AS flag_enabled,
                uff.enabled                         AS user_override,
                tff.enabled                         AS tenant_override,
                (lff.feature_flag_id IS NOT NULL)   AS license_grant
            FROM ff
            LEFT JOIN apiome.user_feature_flags uff
                   ON uff.feature_flag_id = ff.id AND uff.user_id = %s::uuid
            LEFT JOIN apiome.tenant_feature_flags tff
                   ON tff.feature_flag_id = ff.id AND tff.tenant_id = %s::uuid
            LEFT JOIN apiome.user_entitlements ue
                   ON ue.user_id = %s::uuid
            LEFT JOIN apiome.license_feature_flags lff
                   ON lff.feature_flag_id = ff.id AND lff.license_id = ue.license_id
            LIMIT 1
            """,
            (flag_name, user_id, tenant_id, user_id),
        )
        if not row:
            # Flag is not defined in the registry — treat as not entitled.
            return False

        record = row[0]
        if not record["flag_enabled"]:
            # Globally disabled master switch — off for everyone.
            return False

        if record["user_override"] is not None:
            return bool(record["user_override"])
        if record["tenant_override"] is not None:
            return bool(record["tenant_override"])
        return bool(record["license_grant"])

    def get_active_tenant_auth_row(self, tenant_slug: str) -> Optional[Dict[str, Any]]:
        """Resolve a non-deleted tenant slug to id/slug/name for auth checks."""
        query = """
            SELECT id::text AS tenant_id, slug AS tenant_slug, name AS tenant_name
            FROM apiome.tenants
            WHERE slug = %s AND deleted_at IS NULL
            LIMIT 1
        """
        rows = self.execute_query(query, (tenant_slug,))
        return rows[0] if rows else None

    def user_has_tenant_access(self, user_id: str, tenant_id: str) -> bool:
        """
        True when the user is a tenant member or tenant administrator.

        Administrators must be able to call tenant-scoped REST routes even if a legacy
        row is missing from ``tenant_users`` (UI treats ``tenant_administrators`` as authoritative).
        """
        member_q = """
            SELECT 1
            FROM apiome.tenant_users
            WHERE user_id = %s::uuid AND tenant_id = %s::uuid
              AND status <> 'suspended'
            LIMIT 1
        """
        if self.execute_query(member_q, (user_id, tenant_id)):
            return True
        admin_q = """
            SELECT 1
            FROM apiome.tenant_administrators
            WHERE user_id = %s::uuid AND tenant_id = %s::uuid
            LIMIT 1
        """
        return bool(self.execute_query(admin_q, (user_id, tenant_id)))

    def insert_version_protection_audit(
        self,
        tenant_id: str,
        project_id: Optional[str],
        actor_id: Optional[str],
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Best-effort audit row for protection policy and overrides (#504)."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.version_protection_audit
                      (tenant_id, project_id, actor_id, action, resource_type, resource_id, outcome, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        tenant_id,
                        project_id,
                        actor_id,
                        action,
                        resource_type,
                        resource_id,
                        outcome,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.warning("insert_version_protection_audit failed: %s", e)

    def insert_workflow_audit(
        self,
        tenant_id: str,
        project_id: Optional[str],
        version_id: Optional[str],
        action: str,
        outcome: str,
        actor_id: Optional[str],
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append-only workflow audit row (#2577). Best-effort: logs and swallows DB errors."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.workflow_audit
                      (tenant_id, project_id, version_id, action, outcome, actor_id, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        tenant_id,
                        project_id,
                        version_id,
                        action,
                        outcome,
                        actor_id,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.warning("insert_workflow_audit failed: %s", e)

    def list_workflow_audit_for_version(
        self,
        version_id: str,
        tenant_id: str,
        since=None,
        until=None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Rows for one revision, tenant-scoped, optional created_at range (for queries / tests)."""
        clauses = [
            "wa.version_id = %s",
            "wa.tenant_id = %s",
        ]
        params: List[Any] = [version_id, tenant_id]
        if since is not None:
            clauses.append("wa.created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("wa.created_at <= %s")
            params.append(until)
        q = f"""
            SELECT wa.id, wa.tenant_id, wa.project_id, wa.version_id, wa.action, wa.outcome,
                   wa.actor_id, wa.detail, wa.created_at
            FROM apiome.workflow_audit wa
            WHERE {' AND '.join(clauses)}
            ORDER BY wa.created_at ASC, wa.id ASC
            LIMIT %s
        """
        params.append(limit)
        return self.execute_query(q, tuple(params))

    def _workflow_audit_filter_clauses(
        self,
        tenant_id: str,
        *,
        project_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        version_id: Optional[str] = None,
        since=None,
        until=None,
        cursor_created_at=None,
        cursor_id: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        """Build WHERE fragment and params for tenant-scoped workflow_audit queries (#2578)."""
        clauses = ["wa.tenant_id = %s"]
        params: List[Any] = [tenant_id]
        if project_id is not None:
            clauses.append("wa.project_id = %s")
            params.append(project_id)
        if actions:
            placeholders = ",".join(["%s"] * len(actions))
            clauses.append(f"wa.action IN ({placeholders})")
            params.extend(actions)
        if actor_id is not None:
            clauses.append("wa.actor_id = %s")
            params.append(actor_id)
        if outcome is not None:
            clauses.append("wa.outcome = %s")
            params.append(outcome)
        if version_id is not None:
            clauses.append("wa.version_id = %s")
            params.append(version_id)
        if since is not None:
            clauses.append("wa.created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("wa.created_at <= %s")
            params.append(until)
        if cursor_created_at is not None and cursor_id is not None:
            clauses.append("(wa.created_at, wa.id) < (%s, %s::uuid)")
            params.extend([cursor_created_at, cursor_id])
        where_sql = " AND ".join(clauses)
        return where_sql, params

    def count_workflow_audit_filtered(
        self,
        tenant_id: str,
        *,
        project_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        version_id: Optional[str] = None,
        since=None,
        until=None,
    ) -> int:
        """Count rows matching filters (no cursor)."""
        where_sql, params = self._workflow_audit_filter_clauses(
            tenant_id,
            project_id=project_id,
            actions=actions,
            actor_id=actor_id,
            outcome=outcome,
            version_id=version_id,
            since=since,
            until=until,
            cursor_created_at=None,
            cursor_id=None,
        )
        q = f"SELECT COUNT(*)::bigint AS cnt FROM apiome.workflow_audit wa WHERE {where_sql}"
        rows = self.execute_query(q, tuple(params))
        if not rows:
            return 0
        return int(rows[0].get("cnt") or 0)

    def search_workflow_audit(
        self,
        tenant_id: str,
        *,
        project_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        version_id: Optional[str] = None,
        since=None,
        until=None,
        limit: int = 50,
        offset: int = 0,
        cursor_created_at=None,
        cursor_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Paginated workflow_audit rows, newest first (created_at DESC, id DESC).
        Use either (offset) or (cursor_created_at + cursor_id), not both.
        """
        where_sql, params = self._workflow_audit_filter_clauses(
            tenant_id,
            project_id=project_id,
            actions=actions,
            actor_id=actor_id,
            outcome=outcome,
            version_id=version_id,
            since=since,
            until=until,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )
        use_cursor = cursor_created_at is not None and cursor_id is not None
        q = f"""
            SELECT wa.id, wa.tenant_id, wa.project_id, wa.version_id, wa.action, wa.outcome,
                   wa.actor_id, wa.detail, wa.created_at
            FROM apiome.workflow_audit wa
            WHERE {where_sql}
            ORDER BY wa.created_at DESC, wa.id DESC
            LIMIT %s
        """
        params.append(limit)
        if not use_cursor:
            q += " OFFSET %s"
            params.append(offset)
        return self.execute_query(q, tuple(params))

    def insert_registry_audit(
        self,
        tenant_id: str,
        action: str,
        outcome: str,
        *,
        primitive_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        namespace: Optional[str] = None,
        actor_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append-only type-registry audit row (#3481).

        Best-effort: logs and swallows DB errors so a failed audit write can never fail the
        governed registry action (create/update/delete/import) it records.

        Args:
            tenant_id: Owning tenant (required).
            action: Registry verb, e.g. ``primitive.create``.
            outcome: ``success`` or ``failure``.
            primitive_id: Affected primitive id, when one exists.
            schema_id: Derived ``$id`` of the affected type, for traceability.
            namespace: Registry namespace path of the affected type, when applicable.
            actor_id: User who performed the action (None for unattributable API-key calls).
            detail: Structured JSON context (changed fields, import counts, error info).
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.registry_audit
                      (tenant_id, primitive_id, schema_id, namespace, action, outcome,
                       actor_id, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        tenant_id,
                        primitive_id,
                        schema_id,
                        namespace,
                        action,
                        outcome,
                        actor_id,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            _logger.warning("insert_registry_audit failed: %s", e)

    def _registry_audit_filter_clauses(
        self,
        tenant_id: str,
        *,
        primitive_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        schema_id: Optional[str] = None,
        since=None,
        until=None,
        cursor_created_at=None,
        cursor_id: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        """Build WHERE fragment and params for tenant-scoped registry_audit queries (#3481)."""
        clauses = ["ra.tenant_id = %s"]
        params: List[Any] = [tenant_id]
        if primitive_id is not None:
            clauses.append("ra.primitive_id = %s")
            params.append(primitive_id)
        if actions:
            placeholders = ",".join(["%s"] * len(actions))
            clauses.append(f"ra.action IN ({placeholders})")
            params.extend(actions)
        if actor_id is not None:
            clauses.append("ra.actor_id = %s")
            params.append(actor_id)
        if outcome is not None:
            clauses.append("ra.outcome = %s")
            params.append(outcome)
        if schema_id is not None:
            clauses.append("ra.schema_id = %s")
            params.append(schema_id)
        if since is not None:
            clauses.append("ra.created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("ra.created_at <= %s")
            params.append(until)
        if cursor_created_at is not None and cursor_id is not None:
            clauses.append("(ra.created_at, ra.id) < (%s, %s::uuid)")
            params.extend([cursor_created_at, cursor_id])
        where_sql = " AND ".join(clauses)
        return where_sql, params

    def count_registry_audit_filtered(
        self,
        tenant_id: str,
        *,
        primitive_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        schema_id: Optional[str] = None,
        since=None,
        until=None,
    ) -> int:
        """Count registry_audit rows matching filters (no cursor)."""
        where_sql, params = self._registry_audit_filter_clauses(
            tenant_id,
            primitive_id=primitive_id,
            actions=actions,
            actor_id=actor_id,
            outcome=outcome,
            schema_id=schema_id,
            since=since,
            until=until,
            cursor_created_at=None,
            cursor_id=None,
        )
        q = f"SELECT COUNT(*)::bigint AS cnt FROM apiome.registry_audit ra WHERE {where_sql}"
        rows = self.execute_query(q, tuple(params))
        if not rows:
            return 0
        return int(rows[0].get("cnt") or 0)

    def search_registry_audit(
        self,
        tenant_id: str,
        *,
        primitive_id: Optional[str] = None,
        actions: Optional[List[str]] = None,
        actor_id: Optional[str] = None,
        outcome: Optional[str] = None,
        schema_id: Optional[str] = None,
        since=None,
        until=None,
        limit: int = 50,
        offset: int = 0,
        cursor_created_at=None,
        cursor_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Paginated registry_audit rows, newest first (created_at DESC, id DESC).
        Use either (offset) or (cursor_created_at + cursor_id), not both.
        """
        where_sql, params = self._registry_audit_filter_clauses(
            tenant_id,
            primitive_id=primitive_id,
            actions=actions,
            actor_id=actor_id,
            outcome=outcome,
            schema_id=schema_id,
            since=since,
            until=until,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
        )
        use_cursor = cursor_created_at is not None and cursor_id is not None
        q = f"""
            SELECT ra.id, ra.tenant_id, ra.primitive_id, ra.schema_id, ra.namespace,
                   ra.action, ra.outcome, ra.actor_id, ra.detail, ra.created_at
            FROM apiome.registry_audit ra
            WHERE {where_sql}
            ORDER BY ra.created_at DESC, ra.id DESC
            LIMIT %s
        """
        params.append(limit)
        if not use_cursor:
            q += " OFFSET %s"
            params.append(offset)
        return self.execute_query(q, tuple(params))

    def _refresh_audit_filter_clauses(
        self,
        tenant_id: str,
        *,
        repository_id: Optional[str] = None,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        trigger: Optional[str] = None,
        outcome: Optional[str] = None,
        since=None,
        until=None,
    ) -> Tuple[str, List[Any]]:
        """Build WHERE fragment + params for refresh-cycle history queries (RAR-5.3).

        Filters the shared ``apiome.workflow_audit`` ledger down to the dedicated
        refresh-cycle action and, when supplied, the per-repo / per-file lineage and
        the refresh facets carried in the ``detail`` JSONB (see
        :mod:`repository_refresh_audit`). ``repository_id`` + ``path`` make the
        history queryable per repo and per file.
        """
        from .repository_refresh_audit import REFRESH_CYCLE_ACTION

        clauses = ["wa.tenant_id = %s", "wa.action = %s"]
        params: List[Any] = [tenant_id, REFRESH_CYCLE_ACTION]
        if repository_id is not None:
            clauses.append("wa.detail->>'repositoryId' = %s")
            params.append(str(repository_id))
        if branch is not None:
            clauses.append("wa.detail->>'branch' = %s")
            params.append(str(branch))
        if path is not None:
            clauses.append("wa.detail->>'path' = %s")
            params.append(str(path))
        if trigger is not None:
            clauses.append("wa.detail->>'trigger' = %s")
            params.append(str(trigger))
        if outcome is not None:
            clauses.append("wa.detail->>'outcome' = %s")
            params.append(str(outcome))
        if since is not None:
            clauses.append("wa.created_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("wa.created_at <= %s")
            params.append(until)
        return " AND ".join(clauses), params

    def count_repository_refresh_audit(
        self,
        tenant_id: str,
        *,
        repository_id: Optional[str] = None,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        trigger: Optional[str] = None,
        outcome: Optional[str] = None,
        since=None,
        until=None,
    ) -> int:
        """Count refresh-cycle audit rows matching the filters (RAR-5.3)."""
        where_sql, params = self._refresh_audit_filter_clauses(
            tenant_id,
            repository_id=repository_id,
            branch=branch,
            path=path,
            trigger=trigger,
            outcome=outcome,
            since=since,
            until=until,
        )
        q = f"SELECT COUNT(*)::bigint AS cnt FROM apiome.workflow_audit wa WHERE {where_sql}"
        rows = self.execute_query(q, tuple(params))
        if not rows:
            return 0
        return int(rows[0].get("cnt") or 0)

    def search_repository_refresh_audit(
        self,
        tenant_id: str,
        *,
        repository_id: Optional[str] = None,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        trigger: Optional[str] = None,
        outcome: Optional[str] = None,
        since=None,
        until=None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Paginated refresh-cycle history, newest first (RAR-5.3).

        Returns ``apiome.workflow_audit`` rows stamped with the refresh-cycle action,
        scoped to the tenant and optionally to a repository / branch / file path and
        the refresh facets. ``repository_id`` makes the history queryable per repo;
        adding ``path`` makes it queryable per file.
        """
        where_sql, params = self._refresh_audit_filter_clauses(
            tenant_id,
            repository_id=repository_id,
            branch=branch,
            path=path,
            trigger=trigger,
            outcome=outcome,
            since=since,
            until=until,
        )
        q = f"""
            SELECT wa.id, wa.tenant_id, wa.project_id, wa.version_id, wa.action,
                   wa.outcome, wa.actor_id, wa.detail, wa.created_at
            FROM apiome.workflow_audit wa
            WHERE {where_sql}
            ORDER BY wa.created_at DESC, wa.id DESC
            LIMIT %s OFFSET %s
        """
        params.append(limit)
        params.append(offset)
        return self.execute_query(q, tuple(params))

    def delete_version(
        self, version_record_id: str, tenant_id: str, user_id: Optional[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Soft delete a version. Returns (True, None) on success, or (False, error_code).
        error_code: not_found | forbidden | revision_locked
        """
        existing = self.get_version_by_id(version_record_id, tenant_id)
        if not existing:
            return False, "not_found"

        rev_locked = bool(existing.get("revision_locked"))
        creator_id = existing.get("creator_id")
        project_id = existing.get("project_id")

        if user_id is None:
            if rev_locked:
                self.insert_version_protection_audit(
                    tenant_id,
                    project_id,
                    None,
                    "version.delete",
                    "version",
                    version_record_id,
                    "denied",
                    {"reason": "revision_locked_no_user_context"},
                )
                return False, "revision_locked"
        else:
            is_admin = self.is_user_tenant_admin(tenant_id, user_id)
            if creator_id != user_id and not is_admin:
                self.insert_version_protection_audit(
                    tenant_id,
                    project_id,
                    user_id,
                    "version.delete",
                    "version",
                    version_record_id,
                    "denied",
                    {"reason": "not_owner_or_admin"},
                )
                return False, "forbidden"
            if rev_locked and not is_admin:
                self.insert_version_protection_audit(
                    tenant_id,
                    project_id,
                    user_id,
                    "version.delete",
                    "version",
                    version_record_id,
                    "denied",
                    {"reason": "revision_locked"},
                )
                return False, "revision_locked"

        query = """
            UPDATE apiome.versions v
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            FROM apiome.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_record_id, tenant_id))
                ok = cursor.rowcount > 0
                conn.commit()
                if ok and rev_locked and user_id and self.is_user_tenant_admin(tenant_id, user_id):
                    self.insert_version_protection_audit(
                        tenant_id,
                        project_id,
                        user_id,
                        "version.delete",
                        "version",
                        version_record_id,
                        "allowed",
                        {"reason": "admin_override_locked_revision"},
                    )
                return (True, None) if ok else (False, "not_found")
        except Exception as e:
            conn.rollback()
            raise e

    def copy_classes_from_version(self, source_version_id: str, target_version_id: str) -> Dict[str, Any]:
        """Copy all classes from source version to target version."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                # Copy classes
                cursor.execute("""
                    INSERT INTO apiome.classes (version_id, name, description, schema, enabled, canvas_metadata)
                    SELECT %s, name, description, schema, enabled, canvas_metadata
                    FROM apiome.classes
                    WHERE version_id = %s AND deleted_at IS NULL
                    RETURNING id, name
                """, (target_version_id, source_version_id))

                copied_classes = cursor.fetchall()
                copied_count = len(copied_classes)

                # For each copied class, copy its properties
                for copied_class in copied_classes:
                    new_class_id = copied_class['id']
                    class_name = copied_class['name']

                    # Find original class ID
                    cursor.execute("""
                        SELECT id FROM apiome.classes
                        WHERE version_id = %s AND name = %s AND deleted_at IS NULL
                    """, (source_version_id, class_name))

                    original = cursor.fetchone()
                    if original:
                        original_class_id = original['id']

                        # Copy class properties (simple copy without nested property mapping for now)
                        cursor.execute("""
                            INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, primitive_id, primitive_ref)
                            SELECT %s, property_id, name, description, data, primitive_id, primitive_ref
                            FROM apiome.class_properties
                            WHERE class_id = %s AND parent_id IS NULL
                        """, (new_class_id, original_class_id))

                conn.commit()
                return {"success": True, "copied_count": copied_count}
        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}

    # ==================== Project Properties Methods ====================

    def get_properties_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all properties for a project."""
        query = """
            SELECT id, project_id, name, description, data, enabled, created_at, updated_at
            FROM apiome.properties
            WHERE project_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """
        return self.execute_query(query, (project_id,))

    def get_property_by_id(self, property_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific property by ID, ensuring it belongs to the project."""
        query = """
            SELECT id, project_id, name, description, data, enabled, created_at, updated_at
            FROM apiome.properties
            WHERE id = %s AND project_id = %s AND deleted_at IS NULL
        """
        results = self.execute_query(query, (property_id, project_id))
        return results[0] if results else None

    def create_property(self, project_id: str, name: str, description: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new property for a project."""
        query = """
            INSERT INTO apiome.properties (project_id, name, description, data)
            VALUES (%s, %s, %s, %s)
            RETURNING id, project_id, name, description, data, enabled, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (project_id, name.strip(), description, json.dumps(data) if isinstance(data, dict) else data))
                result = cursor.fetchone()
                conn.commit()
                # Parse JSON data if it's a string
                if result and isinstance(result.get('data'), str):
                    result['data'] = json.loads(result['data'])
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_property(self, property_id: str, project_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a property, ensuring it belongs to the project."""
        # Build dynamic update query
        set_clauses = []
        params = []

        if 'name' in updates:
            set_clauses.append("name = %s")
            params.append(updates['name'].strip() if updates['name'] else None)
        if 'description' in updates:
            set_clauses.append("description = %s")
            params.append(updates['description'])
        if 'data' in updates:
            set_clauses.append("data = %s")
            data_value = updates['data']
            params.append(json.dumps(data_value) if isinstance(data_value, dict) else data_value)
        if 'enabled' in updates:
            set_clauses.append("enabled = %s")
            params.append(updates['enabled'])

        if not set_clauses:
            # No updates provided
            return self.get_property_by_id(property_id, project_id)

        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

        query = f"""
            UPDATE apiome.properties
            SET {', '.join(set_clauses)}
            WHERE id = %s AND project_id = %s AND deleted_at IS NULL
            RETURNING id, project_id, name, description, data, enabled, created_at, updated_at
        """
        params.extend([property_id, project_id])

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                if result and isinstance(result.get('data'), str):
                    result['data'] = json.loads(result['data'])
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_property(self, property_id: str, project_id: str) -> bool:
        """Soft delete a property, ensuring it belongs to the project."""
        query = """
            UPDATE apiome.properties
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND project_id = %s AND deleted_at IS NULL
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (property_id, project_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Path CRUD Operations ====================

    def get_path_by_id(self, path_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific path by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT vp.id, vp.version_id, vp.pathname, vp.metadata,
                   vp.created_at, vp.updated_at
            FROM apiome.version_path vp
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE vp.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(query, (path_id, tenant_id))
        return results[0] if results else None

    def get_paths_for_version_with_tenant(self, version_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all paths for a version, ensuring it belongs to the tenant."""
        query = """
            SELECT vp.id, vp.version_id, vp.pathname, vp.metadata,
                   vp.metadata->>'summary' as summary,
                   vp.metadata->>'description' as description,
                   vp.created_at, vp.updated_at
            FROM apiome.version_path vp
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE vp.version_id = %s AND p.tenant_id = %s
            ORDER BY vp.pathname
        """
        return self.execute_query(query, (version_id, tenant_id))

    def create_path(
        self,
        version_id: str,
        pathname: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new path for a version."""
        query = """
            INSERT INTO apiome.version_path (version_id, pathname, metadata)
            VALUES (%s, %s, %s)
            RETURNING id, version_id, pathname, metadata, created_at, updated_at
        """
        metadata_json = json.dumps(metadata) if metadata else '{}'

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_id, pathname, metadata_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_path(
        self,
        path_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a path, ensuring it belongs to the tenant."""
        # Verify path belongs to tenant
        existing = self.get_path_by_id(path_id, tenant_id)
        if not existing:
            return None

        update_fields = []
        params = []

        if 'pathname' in updates and updates['pathname'] is not None:
            update_fields.append("pathname = %s")
            params.append(updates['pathname'])
        if 'metadata' in updates:
            update_fields.append("metadata = %s")
            params.append(json.dumps(updates['metadata']) if updates['metadata'] else '{}')

        if not update_fields:
            return existing

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(path_id)

        query = f"""
            UPDATE apiome.version_path
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, version_id, pathname, metadata, created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_path(self, path_id: str, tenant_id: str) -> bool:
        """Delete a path, ensuring it belongs to the tenant."""
        # Verify path belongs to tenant
        existing = self.get_path_by_id(path_id, tenant_id)
        if not existing:
            return False

        query = "DELETE FROM apiome.version_path WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def get_path_canvas(self, version_id: str, path_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Load Paths React Flow canvas JSON for a version_path row (tenant-scoped).
        Returns None if the path is missing or not under the given version.
        """
        path = self.get_path_by_id(path_id, tenant_id)
        if not path or str(path["version_id"]) != str(version_id):
            return None

        query = """
            SELECT canvas, updated_at
            FROM apiome.version_path_canvas
            WHERE version_path_id = %s
        """
        rows = self.execute_query(query, (path_id,))
        default_canvas = {
            "nodes": [],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
        if not rows:
            return {
                **default_canvas,
                "updated_at": None,
            }

        row = rows[0]
        canvas = row["canvas"]
        if isinstance(canvas, str):
            canvas = json.loads(canvas)
        if not isinstance(canvas, dict):
            canvas = default_canvas
        nodes = canvas.get("nodes")
        edges = canvas.get("edges")
        viewport = canvas.get("viewport")
        if not isinstance(nodes, list):
            nodes = []
        if not isinstance(edges, list):
            edges = []
        if not isinstance(viewport, dict):
            viewport = {"x": 0, "y": 0, "zoom": 1}

        return {
            "nodes": nodes,
            "edges": edges,
            "viewport": {
                "x": float(viewport.get("x", 0)),
                "y": float(viewport.get("y", 0)),
                "zoom": float(viewport.get("zoom", 1)),
            },
            "updated_at": row.get("updated_at"),
        }

    def upsert_path_canvas(
        self,
        version_id: str,
        path_id: str,
        tenant_id: str,
        canvas: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Insert or update Paths canvas JSON (last-write-wins). Returns None if path/version/tenant mismatch.
        """
        path = self.get_path_by_id(path_id, tenant_id)
        if not path or str(path["version_id"]) != str(version_id):
            return None

        payload = {
            "nodes": canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else [],
            "edges": canvas.get("edges") if isinstance(canvas.get("edges"), list) else [],
            "viewport": canvas.get("viewport")
            if isinstance(canvas.get("viewport"), dict)
            else {"x": 0, "y": 0, "zoom": 1},
        }
        vp = payload["viewport"]
        try:
            payload["viewport"] = {
                "x": float(vp.get("x", 0)),
                "y": float(vp.get("y", 0)),
                "zoom": float(vp.get("zoom", 1)),
            }
        except (TypeError, ValueError):
            payload["viewport"] = {"x": 0, "y": 0, "zoom": 1}

        query = """
            INSERT INTO apiome.version_path_canvas (version_path_id, canvas, updated_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (version_path_id) DO UPDATE SET
                canvas = EXCLUDED.canvas,
                updated_at = CURRENT_TIMESTAMP
            RETURNING canvas, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_id, Json(payload)))
                result = cursor.fetchone()
                conn.commit()
                if not result:
                    return None
                out_canvas = result["canvas"]
                if isinstance(out_canvas, str):
                    out_canvas = json.loads(out_canvas)
                return {
                    "nodes": out_canvas.get("nodes", []),
                    "edges": out_canvas.get("edges", []),
                    "viewport": out_canvas.get("viewport", {"x": 0, "y": 0, "zoom": 1}),
                    "updated_at": result.get("updated_at"),
                }
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Path Operation CRUD ====================

    def get_operation_by_id(self, operation_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific operation by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT po.id, po.version_path_id, po.operation, po.metadata,
                   po.created_at, po.updated_at
            FROM apiome.path_operation po
            JOIN apiome.version_path vp ON po.version_path_id = vp.id
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE po.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(query, (operation_id, tenant_id))
        return results[0] if results else None

    def create_operation(
        self,
        version_path_id: str,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new operation for a path."""
        query = """
            INSERT INTO apiome.path_operation (version_path_id, operation, metadata)
            VALUES (%s, %s, %s)
            RETURNING id, version_path_id, operation, metadata, created_at, updated_at
        """
        metadata_json = json.dumps(metadata) if metadata else '{}'

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_path_id, operation.upper(), metadata_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_operation(
        self,
        operation_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update an operation, ensuring it belongs to the tenant."""
        existing = self.get_operation_by_id(operation_id, tenant_id)
        if not existing:
            return None

        update_fields = []
        params = []

        if 'operation' in updates and updates['operation'] is not None:
            update_fields.append("operation = %s")
            params.append(updates['operation'].upper())
        if 'metadata' in updates:
            update_fields.append("metadata = %s")
            params.append(json.dumps(updates['metadata']) if updates['metadata'] else '{}')

        if not update_fields:
            return existing

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(operation_id)

        query = f"""
            UPDATE apiome.path_operation
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, version_path_id, operation, metadata, created_at, updated_at
        """

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, tuple(params))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_operation(self, operation_id: str, tenant_id: str) -> bool:
        """Delete an operation, ensuring it belongs to the tenant."""
        existing = self.get_operation_by_id(operation_id, tenant_id)
        if not existing:
            return False

        query = "DELETE FROM apiome.path_operation WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (operation_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Operation Description CRUD ====================

    def create_operation_description(
        self,
        path_operation_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        operation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create or update operation description."""
        # Check if description already exists
        existing_query = "SELECT id FROM apiome.path_operation_description WHERE path_operation_id = %s"
        results = self.execute_query(existing_query, (path_operation_id,))

        metadata_json = json.dumps(metadata) if metadata else '{}'

        if results:
            # Update existing
            query = """
                UPDATE apiome.path_operation_description
                SET summary = %s, description = %s, operation_id = %s, metadata = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE path_operation_id = %s
                RETURNING id, path_operation_id, summary, description, operation_id, metadata,
                          created_at, updated_at
            """
            conn = self.connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (summary, description, operation_id, metadata_json, path_operation_id))
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                raise e
        else:
            # Create new
            query = """
                INSERT INTO apiome.path_operation_description
                (path_operation_id, summary, description, operation_id, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, path_operation_id, summary, description, operation_id, metadata,
                          created_at, updated_at
            """
            conn = self.connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (path_operation_id, summary, description, operation_id, metadata_json))
                    result = cursor.fetchone()
                    conn.commit()
                    return result
            except Exception as e:
                conn.rollback()
                raise e

    # ==================== Shared Path Parameter CRUD ====================

    def get_shared_parameters_for_path(self, version_path_id: str) -> List[Dict[str, Any]]:
        """Get all shared parameters for a path."""
        query = """
            SELECT id, version_path_id, name, in_location, summary, description, data,
                   created_at, updated_at
            FROM apiome.shared_path_parameter
            WHERE version_path_id = %s
            ORDER BY in_location, name
        """
        return self.execute_query(query, (version_path_id,))

    def create_shared_parameter(
        self,
        version_path_id: str,
        name: str,
        in_location: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a shared parameter for a path."""
        query = """
            INSERT INTO apiome.shared_path_parameter
            (version_path_id, name, in_location, summary, description, data)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, version_path_id, name, in_location, summary, description, data,
                      created_at, updated_at
        """
        data_json = json.dumps(data) if data else '{}'

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_path_id, name, in_location, summary, description, data_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def link_parameter_to_operation(self, path_operation_id: str, shared_path_parameter_id: str) -> Dict[str, Any]:
        """Link a shared parameter to an operation."""
        query = """
            INSERT INTO apiome.path_operation_parameter_link (path_operation_id, shared_path_parameter_id)
            VALUES (%s, %s)
            ON CONFLICT (path_operation_id, shared_path_parameter_id) DO NOTHING
            RETURNING id, path_operation_id, shared_path_parameter_id, created_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id, shared_path_parameter_id))
                result = cursor.fetchone()
                conn.commit()
                if result is None:
                    # Already existed, fetch it
                    cursor.execute(
                        """SELECT id, path_operation_id, shared_path_parameter_id, created_at
                           FROM apiome.path_operation_parameter_link
                           WHERE path_operation_id = %s AND shared_path_parameter_id = %s""",
                        (path_operation_id, shared_path_parameter_id)
                    )
                    result = cursor.fetchone()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def unlink_parameter_from_operation(self, path_operation_id: str, shared_path_parameter_id: str) -> bool:
        """Unlink a shared parameter from an operation."""
        query = """
            DELETE FROM apiome.path_operation_parameter_link
            WHERE path_operation_id = %s AND shared_path_parameter_id = %s
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id, shared_path_parameter_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def delete_shared_parameter(self, parameter_id: str, tenant_id: str) -> bool:
        """Delete a shared parameter, ensuring it belongs to the tenant."""
        verify_query = """
            SELECT spp.id FROM apiome.shared_path_parameter spp
            JOIN apiome.version_path vp ON spp.version_path_id = vp.id
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE spp.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (parameter_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM apiome.shared_path_parameter WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (parameter_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Shared Request Body CRUD ====================

    def get_shared_request_bodies_for_path(self, version_path_id: str) -> List[Dict[str, Any]]:
        """Get all shared request bodies for a path."""
        query = """
            SELECT id, version_path_id, name, description, required,
                   created_at, updated_at
            FROM apiome.shared_path_request_body
            WHERE version_path_id = %s
            ORDER BY name
        """
        return self.execute_query(query, (version_path_id,))

    def create_shared_request_body(
        self,
        version_path_id: str,
        name: str,
        description: Optional[str] = None,
        required: bool = True
    ) -> Dict[str, Any]:
        """Create a shared request body for a path."""
        query = """
            INSERT INTO apiome.shared_path_request_body
            (version_path_id, name, description, required)
            VALUES (%s, %s, %s, %s)
            RETURNING id, version_path_id, name, description, required, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_path_id, name, description, required))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def link_request_body_to_operation(self, path_operation_id: str, shared_request_body_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Link a shared request body to an operation."""
        metadata_json = json.dumps(metadata) if metadata else None
        query = """
            INSERT INTO apiome.path_operation_request_body_link (path_operation_id, shared_path_request_body_id, metadata)
            VALUES (%s, %s, %s)
            ON CONFLICT (path_operation_id) DO UPDATE SET
                shared_path_request_body_id = EXCLUDED.shared_path_request_body_id,
                metadata = EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, path_operation_id, shared_path_request_body_id, metadata, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id, shared_request_body_id, metadata_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def unlink_request_body_from_operation(self, path_operation_id: str) -> bool:
        """Unlink request body from an operation."""
        query = "DELETE FROM apiome.path_operation_request_body_link WHERE path_operation_id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def add_request_body_content_type(
        self,
        shared_request_body_id: str,
        media_type: str,
        class_id: Optional[str] = None,
        inline_schema: Optional[Dict[str, Any]] = None,
        encoding: Optional[Dict[str, Any]] = None,
        examples: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Add a content type to a request body."""
        query = """
            INSERT INTO apiome.shared_path_request_body_content
            (shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (shared_path_request_body_id, media_type) DO UPDATE SET
                class_id = EXCLUDED.class_id,
                inline_schema = EXCLUDED.inline_schema,
                encoding = EXCLUDED.encoding,
                examples = EXCLUDED.examples,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema,
                      encoding, examples, created_at, updated_at
        """
        inline_schema_json = json.dumps(inline_schema) if inline_schema else None
        encoding_json = json.dumps(encoding) if encoding else None
        examples_json = json.dumps(examples) if examples else None

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (shared_request_body_id, media_type, class_id,
                                       inline_schema_json, encoding_json, examples_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_shared_request_body(self, request_body_id: str, tenant_id: str) -> bool:
        """Delete a shared request body, ensuring it belongs to the tenant."""
        verify_query = """
            SELECT rb.id FROM apiome.shared_path_request_body rb
            JOIN apiome.version_path vp ON rb.version_path_id = vp.id
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE rb.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (request_body_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM apiome.shared_path_request_body WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (request_body_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Shared Response CRUD ====================

    def get_shared_responses_for_path(self, version_path_id: str) -> List[Dict[str, Any]]:
        """Get all shared responses for a path."""
        query = """
            SELECT id, version_path_id, status_code, description, data, class_id, inline_schema,
                   schema_mode, created_at, updated_at
            FROM apiome.shared_path_response
            WHERE version_path_id = %s
            ORDER BY status_code
        """
        return self.execute_query(query, (version_path_id,))

    def create_shared_response(
        self,
        version_path_id: str,
        status_code: str,
        description: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        class_id: Optional[str] = None,
        inline_schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a shared response for a path."""
        query = """
            INSERT INTO apiome.shared_path_response
            (version_path_id, status_code, description, data, class_id, inline_schema)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, version_path_id, status_code, description, data, class_id, inline_schema,
                      created_at, updated_at
        """
        data_json = json.dumps(data) if data else None
        inline_schema_json = json.dumps(inline_schema) if inline_schema else None

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (version_path_id, status_code, description,
                                       data_json, class_id, inline_schema_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def link_response_to_operation(self, path_operation_id: str, shared_response_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Link a shared response to an operation."""
        metadata_json = json.dumps(metadata) if metadata else None
        query = """
            INSERT INTO apiome.path_operation_response_link (path_operation_id, shared_path_response_id, metadata)
            VALUES (%s, %s, %s)
            ON CONFLICT (path_operation_id, shared_path_response_id) DO UPDATE SET
                metadata = EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, path_operation_id, shared_path_response_id, metadata, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id, shared_response_id, metadata_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def unlink_response_from_operation(self, path_operation_id: str, shared_response_id: str) -> bool:
        """Unlink a shared response from an operation."""
        query = """
            DELETE FROM apiome.path_operation_response_link
            WHERE path_operation_id = %s AND shared_path_response_id = %s
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (path_operation_id, shared_response_id))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def add_response_content_type(
        self,
        shared_response_id: str,
        media_type: str,
        class_id: Optional[str] = None,
        inline_schema: Optional[Dict[str, Any]] = None,
        examples: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Add a content type to a response."""
        query = """
            INSERT INTO apiome.shared_path_response_content
            (shared_path_response_id, media_type, class_id, inline_schema, examples)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (shared_path_response_id, media_type) DO UPDATE SET
                class_id = EXCLUDED.class_id,
                inline_schema = EXCLUDED.inline_schema,
                examples = EXCLUDED.examples,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, shared_path_response_id, media_type, class_id, inline_schema,
                      examples, created_at, updated_at
        """
        inline_schema_json = json.dumps(inline_schema) if inline_schema else None
        examples_json = json.dumps(examples) if examples else None

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (shared_response_id, media_type, class_id,
                                       inline_schema_json, examples_json))
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def delete_shared_response(self, response_id: str, tenant_id: str) -> bool:
        """Delete a shared response, ensuring it belongs to the tenant."""
        verify_query = """
            SELECT sr.id FROM apiome.shared_path_response sr
            JOIN apiome.version_path vp ON sr.version_path_id = vp.id
            JOIN apiome.versions v ON vp.version_id = v.id
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE sr.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (response_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM apiome.shared_path_response WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (response_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def copy_class_properties_to_inline_schema(self, class_id: str) -> Dict[str, Any]:
        """Copy class properties to create an inline schema structure."""
        # Get class properties
        properties = self.get_properties_for_class(class_id)

        # Build inline schema structure
        inline_properties = []
        for prop in properties:
            prop_data = prop.get('data', {})
            if isinstance(prop_data, str):
                prop_data = json.loads(prop_data)

            inline_prop = {
                'id': str(prop['id']),
                'name': prop['name'],
                'description': prop.get('description'),
                'data': prop_data,
                'parent_id': str(prop['parent_id']) if prop.get('parent_id') else None
            }
            inline_properties.append(inline_prop)

        return {
            'type': 'object',
            'properties': inline_properties
        }

    def get_migration_plan_rules(
        self,
        project_id: str,
        from_version_id: str,
        to_version_id: str,
        class_name: str,
        tenant_id: str
    ) -> Dict[str, Any]:
        """
        Get migration plan rules for a (project, from_version, to_version, class_name).
        Only returns rules for plans whose project belongs to the tenant.
        Returns dict keyed by 'migration-edge-prop-{source_property}' with rule payloads.
        """
        query = """
            SELECT mpr.source_property, mpr.rule
            FROM apiome.migration_plan_rules mpr
            JOIN apiome.migration_plans mp ON mp.id = mpr.migration_plan_id
            JOIN apiome.projects p ON p.id = mp.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
            WHERE mp.project_id = %s AND mp.from_version_id = %s AND mp.to_version_id = %s AND mpr.class_name = %s
        """
        rows = self.execute_query(
            query,
            (tenant_id, project_id, from_version_id, to_version_id, class_name)
        )
        rules = {}
        prefix = "migration-edge-prop-"
        for row in rows:
            source_property = row.get("source_property")
            rule = row.get("rule")
            if not source_property or not isinstance(rule, dict):
                continue
            if not (isinstance(rule.get("inputProperties"), list) and isinstance(rule.get("outputProperties"), list)):
                continue
            key = prefix + source_property
            rules[key] = {
                "name": rule.get("name"),
                "inputProperties": rule["inputProperties"],
                "ruleType": rule.get("ruleType", "simple"),
                "ruleContent": rule.get("ruleContent", ""),
                "outputProperties": rule["outputProperties"],
            }
        return rules

    def get_migration_plan_rule_counts(
        self,
        project_id: str,
        from_version_id: str,
        to_version_id: str,
        tenant_id: str
    ) -> Dict[str, int]:
        """
        Get rule counts per class_name for a migration plan.
        Only includes plans whose project belongs to the tenant.
        Returns dict class_name -> count (classes with no rules are not in the dict; treat as 0).
        """
        query = """
            SELECT mpr.class_name, COUNT(*) AS cnt
            FROM apiome.migration_plan_rules mpr
            JOIN apiome.migration_plans mp ON mp.id = mpr.migration_plan_id
            JOIN apiome.projects p ON p.id = mp.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
            WHERE mp.project_id = %s AND mp.from_version_id = %s AND mp.to_version_id = %s
            GROUP BY mpr.class_name
        """
        rows = self.execute_query(
            query,
            (tenant_id, project_id, from_version_id, to_version_id)
        )
        return {row["class_name"]: int(row["cnt"]) for row in rows}

    def save_migration_plan_rules(
        self,
        project_id: str,
        from_version_id: str,
        to_version_id: str,
        class_name: str,
        rules: Dict[str, Any],
        tenant_id: str
    ) -> Optional[str]:
        """
        Save migration plan rules for a (project, from_version, to_version, class_name).
        Replaces all rules for that class in the plan. Ensures project belongs to tenant.
        Returns None on success, or error message string on failure.
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM apiome.projects WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL",
                    (project_id, tenant_id)
                )
                if cursor.fetchone() is None:
                    return "Project not found or access denied"

                cursor.execute(
                    """SELECT id FROM apiome.migration_plans
                       WHERE project_id = %s AND from_version_id = %s AND to_version_id = %s""",
                    (project_id, from_version_id, to_version_id)
                )
                row = cursor.fetchone()
                if row:
                    plan_id = row["id"]
                    cursor.execute(
                        "UPDATE apiome.migration_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (plan_id,)
                    )
                else:
                    cursor.execute(
                        """INSERT INTO apiome.migration_plans (project_id, from_version_id, to_version_id)
                           VALUES (%s, %s, %s) RETURNING id""",
                        (project_id, from_version_id, to_version_id)
                    )
                    plan_id = cursor.fetchone()["id"]

                cursor.execute(
                    "DELETE FROM apiome.migration_plan_rules WHERE migration_plan_id = %s AND class_name = %s",
                    (plan_id, class_name)
                )

                prefix = "migration-edge-prop-"
                for edge_key, rule in (rules or {}).items():
                    if not edge_key.startswith(prefix):
                        continue
                    source_property = edge_key[len(prefix):]
                    if not source_property:
                        continue
                    rule_json = json.dumps({
                        "name": rule.get("name"),
                        "inputProperties": rule.get("inputProperties", []),
                        "ruleType": rule.get("ruleType", "simple"),
                        "ruleContent": rule.get("ruleContent", ""),
                        "outputProperties": rule.get("outputProperties", []),
                    })
                    cursor.execute(
                        """INSERT INTO apiome.migration_plan_rules (migration_plan_id, class_name, source_property, rule)
                           VALUES (%s, %s, %s, %s::jsonb)""",
                        (plan_id, class_name, source_property, rule_json)
                    )
                conn.commit()
                return None
        except Exception as e:
            conn.rollback()
            return str(e)

    # ==================== Version tags (git-like pointers to revisions) ====================

    def list_version_tags_for_project(self, project_id: str, tenant_id: str) -> List[Dict[str, Any]]:
        """List tags for a project; tenant-scoped."""
        query = """
            SELECT t.id, t.project_id, t.version_id, t.name, t.message, t.channel, t.immutable, t.protected,
                   t.created_by, t.created_at, t.updated_at,
                   v.version_id AS target_version_string
            FROM apiome.version_tags t
            JOIN apiome.versions v ON v.id = t.version_id AND v.project_id = t.project_id
            JOIN apiome.projects p ON t.project_id = p.id
            WHERE t.project_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
            ORDER BY t.name ASC
        """
        return self.execute_query(query, (project_id, tenant_id))

    def get_version_tag_by_id(self, tag_id: str, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT t.id, t.project_id, t.version_id, t.name, t.message, t.channel, t.immutable, t.protected,
                   t.created_by, t.created_at, t.updated_at
            FROM apiome.version_tags t
            JOIN apiome.projects p ON t.project_id = p.id
            WHERE t.id = %s AND t.project_id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
        """
        rows = self.execute_query(query, (tag_id, project_id, tenant_id))
        return rows[0] if rows else None

    def assert_version_in_project_tenant(
        self, version_row_id: str, project_id: str, tenant_id: str
    ) -> bool:
        q = """
            SELECT 1 FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s AND v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL
        """
        rows = self.execute_query(q, (version_row_id, project_id, tenant_id))
        return bool(rows)

    def create_version_tag(
        self,
        project_id: str,
        tenant_id: str,
        version_row_id: str,
        name: str,
        message: Optional[str],
        channel: Optional[str],
        immutable: bool,
        tag_protected: bool,
        created_by: Optional[str],
    ) -> Dict[str, Any]:
        if not self.assert_version_in_project_tenant(version_row_id, project_id, tenant_id):
            raise ValueError("Target version not found in this project")
        query = """
            INSERT INTO apiome.version_tags
            (project_id, version_id, name, message, channel, immutable, protected, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, version_id, name, message, channel, immutable, protected, created_by, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        project_id,
                        version_row_id,
                        name.strip(),
                        message,
                        channel,
                        immutable,
                        tag_protected,
                        created_by,
                    ),
                )
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def update_version_tag(
        self,
        tag_id: str,
        project_id: str,
        tenant_id: str,
        user_id: Optional[str],
        is_admin: bool,
        new_version_row_id: Optional[str],
        set_immutable: bool,
        set_protected: Optional[bool],
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_version_tag_by_id(tag_id, project_id, tenant_id)
        if not existing:
            return None
        if existing.get("immutable"):
            raise PermissionError("TAG_IMMUTABLE")
        if set_protected is not None and not is_admin:
            raise PermissionError("TAG_PROTECT_POLICY_ADMIN_ONLY")
        if existing.get("protected") and not is_admin:
            self.insert_version_protection_audit(
                tenant_id,
                project_id,
                user_id,
                "tag.update",
                "version_tag",
                tag_id,
                "denied",
                {"reason": "tag_protected"},
            )
            raise PermissionError("TAG_PROTECTED")
        if not self.user_may_manage_version_tag(
            tenant_id, user_id or "", existing.get("created_by")
        ):
            raise PermissionError("TAG_FORBIDDEN")

        if new_version_row_id and not self.assert_version_in_project_tenant(
            new_version_row_id, project_id, tenant_id
        ):
            raise ValueError("Target version not found in this project")
        if (
            not new_version_row_id
            and not set_immutable
            and set_protected is None
        ):
            raise ValueError("Provide new revision id, immutable lock, and/or protected policy")

        sets = ["updated_at = CURRENT_TIMESTAMP"]
        params: List[Any] = []
        if new_version_row_id:
            sets.append("version_id = %s")
            params.append(new_version_row_id)
        if set_immutable:
            sets.append("immutable = true")
        if set_protected is not None:
            sets.append("protected = %s")
            params.append(set_protected)
        params.extend([tag_id, project_id])
        q = f"""
            UPDATE apiome.version_tags SET {", ".join(sets)}
            WHERE id = %s AND project_id = %s
            RETURNING id, project_id, version_id, name, message, channel, immutable, protected, created_by, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, tuple(params))
                row = cursor.fetchone()
                conn.commit()
                if existing.get("protected") and is_admin and (new_version_row_id or set_immutable):
                    self.insert_version_protection_audit(
                        tenant_id,
                        project_id,
                        user_id,
                        "tag.update",
                        "version_tag",
                        tag_id,
                        "allowed",
                        {"reason": "admin_override_tag_protection"},
                    )
                if set_protected is not None:
                    self.insert_version_protection_audit(
                        tenant_id,
                        project_id,
                        user_id,
                        "tag.protection_policy",
                        "version_tag",
                        tag_id,
                        "policy_change",
                        {"protected": set_protected},
                    )
                return row
        except Exception as e:
            conn.rollback()
            raise e

    def delete_version_tag(
        self, tag_id: str, project_id: str, tenant_id: str, user_id: Optional[str], is_admin: bool
    ) -> bool:
        existing = self.get_version_tag_by_id(tag_id, project_id, tenant_id)
        if not existing:
            return False
        if existing.get("immutable"):
            raise PermissionError("TAG_IMMUTABLE")
        if existing.get("protected") and not is_admin:
            self.insert_version_protection_audit(
                tenant_id,
                project_id,
                user_id,
                "tag.delete",
                "version_tag",
                tag_id,
                "denied",
                {"reason": "tag_protected"},
            )
            raise PermissionError("TAG_PROTECTED")
        if not is_admin and not self.user_may_manage_version_tag(
            tenant_id, user_id or "", existing.get("created_by")
        ):
            raise PermissionError("TAG_FORBIDDEN")
        query = "DELETE FROM apiome.version_tags WHERE id = %s AND project_id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (tag_id, project_id))
                ok = cursor.rowcount > 0
                conn.commit()
                if ok and existing.get("protected") and is_admin:
                    self.insert_version_protection_audit(
                        tenant_id,
                        project_id,
                        user_id,
                        "tag.delete",
                        "version_tag",
                        tag_id,
                        "allowed",
                        {"reason": "admin_override_tag_protection"},
                    )
                return ok
        except Exception as e:
            conn.rollback()
            raise e

    def user_may_manage_version_tag(
        self, tenant_id: str, user_id: str, tag_created_by: Optional[str]
    ) -> bool:
        """Creator match or tenant administrator."""
        if tag_created_by and tag_created_by == user_id:
            return True
        q = """
            SELECT 1 FROM apiome.tenant_administrators
            WHERE tenant_id = %s AND user_id = %s
            LIMIT 1
        """
        return bool(self.execute_query(q, (tenant_id, user_id)))

    # ==================== Version merge (Git-like three-way) ====================

    def collect_revision_ancestors(self, version_id: str, tenant_id: str) -> Set[str]:
        """All revision ids reachable from ``version_id`` following parent links (including self)."""
        result: Set[str] = set()
        stack = [version_id]
        steps = 0
        while stack:
            if steps > 100000:
                raise RuntimeError("Revision ancestor walk exceeded safety limit")
            steps += 1
            vid = stack.pop()
            if vid in result:
                continue
            result.add(vid)
            row = self.get_version_by_id(vid, tenant_id)
            if not row:
                continue
            for p in (row.get("parent_version_id"), row.get("merge_parent_version_id")):
                if p and str(p) not in result:
                    stack.append(str(p))
        return result

    def compute_merge_base_revision_id(
        self, rev_a: str, rev_b: str, tenant_id: str
    ) -> Optional[str]:
        """Best common ancestor (nearest to tips by creation time) for two revision ids in the same project."""
        a = self.collect_revision_ancestors(rev_a, tenant_id)
        b = self.collect_revision_ancestors(rev_b, tenant_id)
        common = a & b
        if not common:
            return None

        # Cache ancestor sets to avoid O(n²) repeated full graph walks.
        ancestor_cache: Dict[str, Set[str]] = {rev_a: a, rev_b: b}

        def get_cached_ancestors(vid: str) -> Set[str]:
            if vid not in ancestor_cache:
                ancestor_cache[vid] = self.collect_revision_ancestors(vid, tenant_id)
            return ancestor_cache[vid]

        def is_strict_ancestor(anc: str, desc: str) -> bool:
            if anc == desc:
                return False
            return anc in get_cached_ancestors(desc)

        bases = [
            c
            for c in common
            if not any(c != d and is_strict_ancestor(c, d) for d in common)
        ]
        if not bases:
            return None
        if len(bases) == 1:
            return bases[0]

        # Multiple maximal common ancestors (criss-cross history): pick the one
        # nearest to the branch tips by choosing the most recently created revision.
        from datetime import datetime, timezone

        _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

        def created_at_key(vid: str):
            row = self.get_version_by_id(vid, tenant_id)
            ts = row["created_at"] if row and row.get("created_at") else None
            return ts if ts is not None else _epoch

        return max(bases, key=created_at_key)

    def get_prior_published_baseline_revision_id(
        self, project_id: str, tenant_id: str, published_revision_id: str
    ) -> Optional[str]:
        """
        Latest **published** ancestor of ``published_revision_id`` (excluding the revision itself),
        ordered by ``published_at`` then ``created_at``.

        Used as the default baseline for publication change reports (#2702). Revisions outside the
        ancestor closure of ``parent_version_id`` / ``merge_parent_version_id`` are not considered
        (named-branch isolation is a possible follow-up).
        """
        ancestors = self.collect_revision_ancestors(published_revision_id, tenant_id)
        cand_ids = [str(a) for a in ancestors if str(a) != str(published_revision_id)]
        if not cand_ids:
            return None
        placeholders = ",".join(["%s"] * len(cand_ids))
        query = f"""
            SELECT v.id
            FROM apiome.versions v
            INNER JOIN apiome.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
            WHERE v.project_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND v.published = true
              AND v.id IN ({placeholders})
            ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
            LIMIT 1
        """
        params = tuple([project_id, tenant_id, *cand_ids])
        rows = self.execute_query(query, params)
        if not rows:
            return None
        rid = rows[0].get("id")
        return str(rid) if rid is not None else None

    def get_version_branch_by_id(
        self, branch_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the branch row for *branch_id* scoped to *tenant_id* (no project filter)."""
        q = """
            SELECT b.id, b.project_id, b.name, b.tip_version_id, b.branched_from_revision_id,
                   b.protected, b.is_default, b.require_merge_path, b.created_by, b.created_at, b.updated_at
            FROM apiome.version_branches b
            JOIN apiome.projects p ON b.project_id = p.id
            WHERE b.id = %s AND p.tenant_id = %s
        """
        rows = self.execute_query(q, (branch_id, tenant_id))
        return rows[0] if rows else None

    def get_version_branch_by_name(
        self, project_id: str, tenant_id: str, name: str
    ) -> Optional[Dict[str, Any]]:
        q = """
            SELECT b.id, b.project_id, b.name, b.tip_version_id, b.branched_from_revision_id,
                   b.protected, b.is_default, b.require_merge_path, b.created_by, b.created_at, b.updated_at
            FROM apiome.version_branches b
            JOIN apiome.projects p ON b.project_id = p.id
            WHERE b.project_id = %s AND p.tenant_id = %s AND b.name = %s
        """
        rows = self.execute_query(q, (project_id, tenant_id, name.strip()))
        return rows[0] if rows else None

    def update_version_branch_protection_policy(
        self,
        project_id: str,
        tenant_id: str,
        branch_id: str,
        *,
        protected: Optional[bool] = None,
        is_default: Optional[bool] = None,
        require_merge_path: Optional[bool] = None,
        actor_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Tenant-admin policy fields on a branch (#504, #2583, #2727). At least one of protected or
        require_merge_path or is_default must be set.

        When the default branch changes (promotion), ``require_merge_path`` is set to true in the
        same transaction unless the request explicitly sets ``require_merge_path`` false. If the
        target branch is already default, merge-path is only updated when ``require_merge_path`` is
        present in the request. Optionally records ``version.default_branch_promoted`` in
        ``workflow_audit`` when ``actor_id`` is set.
        """
        if protected is None and require_merge_path is None and is_default is None:
            return None
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT b.id
                    FROM apiome.version_branches b
                    JOIN apiome.projects p ON b.project_id = p.id
                    WHERE b.id = %s AND b.project_id = %s AND p.tenant_id = %s
                    FOR UPDATE
                    """,
                    (branch_id, project_id, tenant_id),
                )
                locked = cursor.fetchone()
                if not locked:
                    conn.rollback()
                    return None

                prior_default_id: Optional[str] = None
                is_promotion = False
                merge_path_auto_enabled = False
                rmp_for_set: Optional[bool] = None

                if is_default is True:
                    cursor.execute(
                        """
                        SELECT id FROM apiome.version_branches
                        WHERE project_id = %s AND is_default = true
                        FOR UPDATE
                        """,
                        (project_id,),
                    )
                    prow = cursor.fetchone()
                    pid = prow.get("id") if prow else None
                    prior_default_id = str(pid) if pid is not None else None
                    is_promotion = prior_default_id is None or prior_default_id != str(branch_id)
                    if is_promotion:
                        if require_merge_path is None:
                            rmp_for_set = True
                            merge_path_auto_enabled = True
                        else:
                            rmp_for_set = require_merge_path
                    elif require_merge_path is not None:
                        rmp_for_set = require_merge_path
                elif require_merge_path is not None:
                    rmp_for_set = require_merge_path

                if is_default is True:
                    cursor.execute(
                        """
                        UPDATE apiome.version_branches
                        SET is_default = false, updated_at = CURRENT_TIMESTAMP
                        WHERE project_id = %s AND id <> %s AND is_default = true
                        """,
                        (project_id, branch_id),
                    )

                sets: List[str] = []
                params: List[Any] = []
                if protected is not None:
                    sets.append("protected = %s")
                    params.append(protected)
                if is_default is not None:
                    sets.append("is_default = %s")
                    params.append(is_default)
                if rmp_for_set is not None:
                    sets.append("require_merge_path = %s")
                    params.append(rmp_for_set)
                sets.append("updated_at = CURRENT_TIMESTAMP")
                params.extend([branch_id, project_id, tenant_id])

                cursor.execute(
                    f"""
                    UPDATE apiome.version_branches b
                    SET {", ".join(sets)}
                    FROM apiome.projects p
                    WHERE b.id = %s AND b.project_id = %s AND b.project_id = p.id AND p.tenant_id = %s
                    RETURNING b.id, b.project_id, b.name, b.tip_version_id, b.branched_from_revision_id,
                              b.protected, b.is_default, b.require_merge_path, b.created_by, b.created_at, b.updated_at
                    """,
                    tuple(params),
                )
                row = cursor.fetchone()

                if row and is_default is True and is_promotion and actor_id:
                    detail = {
                        "priorDefaultBranchId": prior_default_id,
                        "newDefaultBranchId": str(branch_id),
                        "mergePathAutoEnabled": merge_path_auto_enabled,
                    }
                    cursor.execute(
                        """
                        INSERT INTO apiome.workflow_audit
                          (tenant_id, project_id, version_id, action, outcome, actor_id, detail)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            tenant_id,
                            project_id,
                            None,
                            "version.default_branch_promoted",
                            "success",
                            actor_id,
                            json.dumps(detail),
                        ),
                    )

            conn.commit()
            return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            msg = str(e).lower()
            if "23505" in msg or "uq_version_branches_default_per_project" in msg:
                raise BranchDefaultConflictError() from e
            raise
        finally:
            conn.autocommit = prev_autocommit

    def _branch_from_revision_idempotent_result(
        self,
        existing: Dict[str, Any],
        source_revision_id: str,
        tenant_id: str,
    ) -> Dict[str, Any]:
        """If existing branch matches source revision as tip (and lineage), return success replay."""
        tip = str(existing["tip_version_id"])
        bf = existing.get("branched_from_revision_id")
        bf_s = str(bf) if bf is not None else None
        src = str(source_revision_id).strip()
        if tip == src and (bf_s is None or bf_s == src):
            full_tip = self.get_version_by_id(tip, tenant_id)
            if not full_tip:
                return {
                    "success": False,
                    "error": "Branch tip revision not found",
                    "code": "NOT_FOUND",
                }
            return {
                "success": True,
                "branch": existing,
                "tip_version": full_tip,
                "idempotent_replay": True,
            }
        return {
            "success": False,
            "error": (
                f"A branch named '{existing.get('name')}' already exists in this project "
                "with a different tip or lineage."
            ),
            "code": "BRANCH_NAME_CONFLICT",
        }

    def create_version_branch_from_revision(
        self,
        project_id: str,
        tenant_id: str,
        branch_name: str,
        source_revision_id: str,
        creator_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Insert a named branch whose tip is ``source_revision_id``; persist ``branched_from_revision_id`` (#2570).
        Idempotent when the same name already points at the same source revision (and compatible lineage).
        """
        bn = (branch_name or "").strip()
        src = (source_revision_id or "").strip()
        if not bn:
            return {"success": False, "error": "branchName is required", "code": "INVALID_INPUT"}
        if not src:
            return {"success": False, "error": "sourceRevisionId is required", "code": "INVALID_INPUT"}

        ver = self.get_version_by_id(src, tenant_id)
        if not ver or str(ver["project_id"]) != str(project_id):
            return {
                "success": False,
                "error": "Source revision not found in this project",
                "code": "NOT_FOUND",
            }

        existing = self.get_version_branch_by_name(project_id, tenant_id, bn)
        if existing:
            return self._branch_from_revision_idempotent_result(existing, src, tenant_id)

        conn = self.connect()
        row: Optional[Dict[str, Any]] = None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.version_branches
                        (project_id, name, tip_version_id, created_by, branched_from_revision_id)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, project_id, name, tip_version_id, branched_from_revision_id,
                              protected, is_default, require_merge_path, created_by, created_at, updated_at
                    """,
                    (project_id, bn, src, creator_id, src),
                )
                row = cursor.fetchone()
            conn.commit()
        except Exception as e:
            conn.rollback()
            err = str(e).lower()
            if "23505" in err or "unique" in err:
                existing2 = self.get_version_branch_by_name(project_id, tenant_id, bn)
                if existing2:
                    return self._branch_from_revision_idempotent_result(
                        existing2, src, tenant_id
                    )
            _logger.exception(
                "Database error creating version branch from revision "
                "(project_id=%s, tenant_id=%s, branch_name=%s, source_revision_id=%s)",
                project_id,
                tenant_id,
                bn,
                src,
            )
            return {
                "success": False,
                "error": "Failed to create branch due to a database error",
                "code": "DATABASE_ERROR",
            }

        if not row:
            return {"success": False, "error": "Failed to create branch", "code": "DATABASE_ERROR"}

        branch_row = dict(row)
        full_tip = self.get_version_by_id(src, tenant_id)
        if not full_tip:
            return {"success": False, "error": "Tip revision not found after insert", "code": "NOT_FOUND"}
        return {
            "success": True,
            "branch": branch_row,
            "tip_version": full_tip,
            "idempotent_replay": False,
        }

    def delete_class_by_name_for_version(
        self,
        version_id: str,
        class_name: str,
        tenant_id: str,
        cursor: Optional[Any] = None,
    ) -> bool:
        """Soft-delete a class by name within a version (tenant-scoped)."""
        query = """
            UPDATE apiome.classes c
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE c.version_id = v.id
              AND c.version_id = %s
              AND c.name = %s
              AND p.tenant_id = %s
              AND c.deleted_at IS NULL
        """
        if cursor is not None:
            cursor.execute(query, (version_id, class_name, tenant_id))
            return cursor.rowcount > 0
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, (version_id, class_name, tenant_id))
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e

    def _copy_class_properties_recursive(
        self, cursor: Any, source_class_id: str, target_class_id: str
    ) -> None:
        cursor.execute(
            """
            SELECT id, property_id, name, description, data, parent_id, primitive_id, primitive_ref
            FROM apiome.class_properties
            WHERE class_id = %s
            """,
            (source_class_id,),
        )
        rows = cursor.fetchall()
        old_to_new: Dict[str, str] = {}
        processed: Set[str] = set()

        def copy_level(parent_id: Optional[str]) -> None:
            props: List[Dict[str, Any]] = []
            for r in rows:
                if str(r["id"]) in processed:
                    continue
                pid = r.get("parent_id")
                if parent_id is None:
                    if pid is not None:
                        continue
                else:
                    if pid is None or str(pid) != str(parent_id):
                        continue
                props.append(r)
            for prop in props:
                new_parent = None
                if prop["parent_id"]:
                    new_parent = old_to_new.get(str(prop["parent_id"]))
                cursor.execute(
                    """
                    INSERT INTO apiome.class_properties
                        (class_id, property_id, name, description, data, parent_id, primitive_id, primitive_ref)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        target_class_id,
                        prop["property_id"],
                        prop["name"],
                        prop["description"],
                        # ``data`` is a JSONB column read back as a Python dict; it must be
                        # re-wrapped with Json() before re-insertion or psycopg2 raises
                        # "can't adapt type 'dict'". Preserve SQL NULL (vs JSON null) for
                        # properties that have no data payload.
                        Json(prop["data"]) if prop["data"] is not None else None,
                        new_parent,
                        prop.get("primitive_id"),
                        prop.get("primitive_ref"),
                    ),
                )
                new_id = cursor.fetchone()["id"]
                old_to_new[str(prop["id"])] = str(new_id)
                processed.add(str(prop["id"]))
                copy_level(str(prop["id"]))

        copy_level(None)

    def copy_classes_from_version_for_merge(
        self, cursor: Any, source_version_id: str, target_version_id: str
    ) -> int:
        """Copy all classes and nested properties (used inside an open transaction)."""
        cursor.execute(
            """
            INSERT INTO apiome.classes (version_id, name, description, schema, enabled, canvas_metadata)
            SELECT %s, name, description, schema, enabled, canvas_metadata
            FROM apiome.classes
            WHERE version_id = %s AND deleted_at IS NULL
            RETURNING id, name
            """,
            (target_version_id, source_version_id),
        )
        copied = cursor.fetchall()
        for row in copied:
            cursor.execute(
                """
                SELECT id FROM apiome.classes
                WHERE version_id = %s AND name = %s AND deleted_at IS NULL
                """,
                (source_version_id, row["name"]),
            )
            orig = cursor.fetchone()
            if not orig:
                continue
            self._copy_class_properties_recursive(cursor, str(orig["id"]), str(row["id"]))
        return len(copied)

    def copy_single_class_between_versions_for_merge(
        self, cursor: Any, source_version_id: str, target_version_id: str, class_name: str
    ) -> Dict[str, Any]:
        """Copy one class by name from source version to target (open transaction)."""
        cursor.execute(
            """
            INSERT INTO apiome.classes (version_id, name, description, schema, enabled, canvas_metadata)
            SELECT %s, name, description, schema, enabled, canvas_metadata
            FROM apiome.classes
            WHERE version_id = %s AND name = %s AND deleted_at IS NULL
            RETURNING id, name
            """,
            (target_version_id, source_version_id, class_name),
        )
        ins = cursor.fetchone()
        if not ins:
            return {"success": False, "error": f"Class {class_name} not found on source version"}
        cursor.execute(
            """
            SELECT id FROM apiome.classes
            WHERE version_id = %s AND name = %s AND deleted_at IS NULL
            """,
            (source_version_id, class_name),
        )
        orig = cursor.fetchone()
        if not orig:
            return {"success": False, "error": "Original class missing"}
        self._copy_class_properties_recursive(cursor, str(orig["id"]), str(ins["id"]))
        return {"success": True}

    def list_version_branches_for_project(
        self, project_id: str, tenant_id: str
    ) -> List[Dict[str, Any]]:
        """Named branches for a project (tenant-scoped)."""
        q = """
            SELECT b.id, b.project_id, b.name, b.tip_version_id, b.branched_from_revision_id,
                   b.protected, b.is_default, b.require_merge_path, b.created_by
            FROM apiome.version_branches b
            JOIN apiome.projects p ON b.project_id = p.id
            WHERE b.project_id = %s AND p.tenant_id = %s
            ORDER BY b.is_default DESC, b.name ASC
        """
        return self.execute_query(q, (project_id, tenant_id))

    def compute_branch_divergence(
        self,
        *,
        project_id: str,
        tenant_id: str,
        branch_tip_revision_id: str,
        against_tip_revision_id: str,
        sample_limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Compute git-like branch divergence from branch tips using recursive CTEs.

        Returns merge base revision metadata, ahead/behind counts, and sampled revisions on each side.
        """
        limit = max(1, min(int(sample_limit), 25))
        q = """
            WITH RECURSIVE
            branch_ancestors AS (
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN apiome.projects p ON v.project_id = p.id
                WHERE v.id = %s
                  AND v.project_id = %s
                  AND p.tenant_id = %s
                  AND v.deleted_at IS NULL
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN branch_ancestors a
                  ON v.id::text = a.parent_revision_id
                  OR v.id::text = a.merge_parent_revision_id
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
            ),
            against_ancestors AS (
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN apiome.projects p ON v.project_id = p.id
                WHERE v.id = %s
                  AND v.project_id = %s
                  AND p.tenant_id = %s
                  AND v.deleted_at IS NULL
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN against_ancestors a
                  ON v.id::text = a.parent_revision_id
                  OR v.id::text = a.merge_parent_revision_id
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
            ),
            merge_base AS (
                SELECT v.id::text AS revision_id, v.created_at
                FROM apiome.versions v
                JOIN branch_ancestors ba ON ba.revision_id = v.id::text
                JOIN against_ancestors aa ON aa.revision_id = v.id::text
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
                ORDER BY v.created_at DESC, v.id DESC
                LIMIT 1
            ),
            merge_base_ancestors AS (
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN merge_base mb ON v.id::text = mb.revision_id
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM apiome.versions v
                JOIN merge_base_ancestors mba
                  ON v.id::text = mba.parent_revision_id
                  OR v.id::text = mba.merge_parent_revision_id
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
            ),
            ahead_set AS (
                SELECT ba.revision_id
                FROM branch_ancestors ba
                LEFT JOIN merge_base_ancestors mba ON mba.revision_id = ba.revision_id
                WHERE mba.revision_id IS NULL
            ),
            behind_set AS (
                SELECT aa.revision_id
                FROM against_ancestors aa
                LEFT JOIN merge_base_ancestors mba ON mba.revision_id = aa.revision_id
                WHERE mba.revision_id IS NULL
            ),
            ahead_sample AS (
                SELECT
                    v.id::text AS revision_id,
                    COALESCE(v.description, '') AS short_message,
                    v.created_at
                FROM apiome.versions v
                JOIN ahead_set a ON a.revision_id = v.id::text
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
                ORDER BY v.created_at DESC, v.id DESC
                LIMIT %s
            ),
            behind_sample AS (
                SELECT
                    v.id::text AS revision_id,
                    COALESCE(v.description, '') AS short_message,
                    v.created_at
                FROM apiome.versions v
                JOIN behind_set b ON b.revision_id = v.id::text
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
                ORDER BY v.created_at DESC, v.id DESC
                LIMIT %s
            )
            SELECT
                (SELECT mb.revision_id FROM merge_base mb) AS merge_base_revision_id,
                (SELECT mb.created_at FROM merge_base mb) AS merge_base_created_at,
                (SELECT COUNT(*)::int FROM ahead_set) AS ahead_count,
                (SELECT COUNT(*)::int FROM behind_set) AS behind_count,
                COALESCE(
                    (
                        SELECT json_agg(
                            json_build_object(
                                'revisionId', a.revision_id,
                                'shortMessage', a.short_message
                            )
                            ORDER BY a.created_at DESC, a.revision_id DESC
                        )
                        FROM ahead_sample a
                    ),
                    '[]'::json
                ) AS ahead_sample,
                COALESCE(
                    (
                        SELECT json_agg(
                            json_build_object(
                                'revisionId', b.revision_id,
                                'shortMessage', b.short_message
                            )
                            ORDER BY b.created_at DESC, b.revision_id DESC
                        )
                        FROM behind_sample b
                    ),
                    '[]'::json
                ) AS behind_sample
        """
        rows = self.execute_query(
            q,
            (
                branch_tip_revision_id,
                project_id,
                tenant_id,
                project_id,
                against_tip_revision_id,
                project_id,
                tenant_id,
                project_id,
                project_id,
                project_id,
                project_id,
                limit,
                project_id,
                limit,
            ),
        )
        if not rows:
            return {
                "merge_base_revision_id": None,
                "merge_base_created_at": None,
                "ahead_count": 0,
                "behind_count": 0,
                "ahead_sample": [],
                "behind_sample": [],
            }
        row = rows[0]
        ahead_sample = row.get("ahead_sample") or []
        behind_sample = row.get("behind_sample") or []
        if isinstance(ahead_sample, str):
            ahead_sample = json.loads(ahead_sample)
        if isinstance(behind_sample, str):
            behind_sample = json.loads(behind_sample)
        return {
            "merge_base_revision_id": row.get("merge_base_revision_id"),
            "merge_base_created_at": row.get("merge_base_created_at"),
            "ahead_count": int(row.get("ahead_count") or 0),
            "behind_count": int(row.get("behind_count") or 0),
            "ahead_sample": ahead_sample if isinstance(ahead_sample, list) else [],
            "behind_sample": behind_sample if isinstance(behind_sample, list) else [],
        }

    def get_latest_revision_id_for_project(
        self, project_id: str, tenant_id: str
    ) -> Optional[str]:
        """Most recently created revision row id for the project (no branch), or None if empty."""
        q = """
            SELECT v.id::text AS id
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL
            ORDER BY v.created_at DESC
            LIMIT 1
        """
        rows = self.execute_query(q, (project_id, tenant_id))
        return str(rows[0]["id"]) if rows else None

    # -----------------------------------------------------------------------
    # Convert-to-project provenance (apiome.conversion_provenance, V139, MFI-22.5)
    # -----------------------------------------------------------------------

    #: Columns returned by conversion-provenance reads, in a fixed order.
    _CONVERSION_PROVENANCE_COLUMNS = (
        "id, tenant_id, source_project_id, source_version_id, source_format, "
        "source_protocol, source_version_label, source_tool_versions, target_project_id, "
        "target_version_id, target_version_label, fidelity_report, fidelity_score, "
        "fidelity_grade, fidelity_tier, lint_score, lint_grade, converter_tool_versions, "
        "reconverted, created_by, created_at"
    )

    def create_conversion_provenance(
        self,
        *,
        tenant_id: str,
        created_by: Optional[str],
        source_project_id: str,
        source_version_id: Optional[str],
        source_format: Optional[str],
        source_protocol: Optional[str],
        source_version_label: Optional[str],
        source_tool_versions: Optional[Dict[str, Any]],
        target_project_id: str,
        target_version_id: Optional[str],
        target_version_label: Optional[str],
        fidelity_report: Optional[Dict[str, Any]],
        fidelity_score: Optional[int],
        fidelity_grade: Optional[str],
        fidelity_tier: Optional[str],
        lint_score: Optional[int],
        lint_grade: Optional[str],
        converter_tool_versions: Optional[Dict[str, Any]],
        reconverted: bool,
    ) -> Dict[str, Any]:
        """Append one convert-to-project provenance row (MFI-22.5) and return it.

        Records the lineage of a catalog → OpenAPI conversion: the source catalog item + revision it
        was converted from (with its format/protocol/tool provenance), the publishable Project +
        revision it produced, the fidelity report the user reviewed, the captured OpenAPI lint score,
        and the converter tool versions that produced it. The ``conversion_provenance`` table is
        append-only (a DB trigger rejects UPDATE/DELETE), so a re-convert calls this again with a new
        target revision rather than mutating the prior row.

        JSONB bags (``*_tool_versions``, ``fidelity_report``) are wrapped in :class:`psycopg2.extras.Json`;
        ``None`` becomes the column default (``{}``).

        Returns:
            The inserted row as a dict.
        """
        query = f"""
            INSERT INTO apiome.conversion_provenance
                (tenant_id, created_by, source_project_id, source_version_id, source_format,
                 source_protocol, source_version_label, source_tool_versions, target_project_id,
                 target_version_id, target_version_label, fidelity_report, fidelity_score,
                 fidelity_grade, fidelity_tier, lint_score, lint_grade, converter_tool_versions,
                 reconverted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, '{{}}'::jsonb), %s, %s, %s,
                    COALESCE(%s, '{{}}'::jsonb), %s, %s, %s, %s, %s,
                    COALESCE(%s, '{{}}'::jsonb), %s)
            RETURNING {self._CONVERSION_PROVENANCE_COLUMNS}
        """
        params = (
            tenant_id,
            created_by,
            source_project_id,
            source_version_id,
            source_format,
            source_protocol,
            source_version_label,
            Json(source_tool_versions) if source_tool_versions is not None else None,
            target_project_id,
            target_version_id,
            target_version_label,
            Json(fidelity_report) if fidelity_report is not None else None,
            fidelity_score,
            fidelity_grade,
            fidelity_tier,
            lint_score,
            lint_grade,
            Json(converter_tool_versions) if converter_tool_versions is not None else None,
            reconverted,
        )
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                result = cursor.fetchone()
                conn.commit()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def get_latest_conversion_for_source(
        self, tenant_id: str, source_project_id: str
    ) -> Optional[Dict[str, Any]]:
        """Most recent conversion of a source catalog item, or ``None`` if never converted.

        The convert job reads this to decide first-convert vs re-convert: a non-``None`` row names the
        ``target_project_id`` a re-convert must append a new version to (rather than minting a
        duplicate Project). Tenant-scoped so one tenant never sees another's conversions.
        """
        query = f"""
            SELECT {self._CONVERSION_PROVENANCE_COLUMNS}
            FROM apiome.conversion_provenance
            WHERE tenant_id = %s AND source_project_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        rows = self.execute_query(query, (tenant_id, source_project_id))
        return rows[0] if rows else None

    def get_conversions_for_project(
        self, tenant_id: str, target_project_id: str
    ) -> List[Dict[str, Any]]:
        """All conversion-provenance rows that produced ``target_project_id`` (newest first).

        The reverse of :meth:`get_latest_conversion_for_source`: "where did this converted Project come
        from?" — one Project accumulates one row per (re-)convert. Tenant-scoped.
        """
        query = f"""
            SELECT {self._CONVERSION_PROVENANCE_COLUMNS}
            FROM apiome.conversion_provenance
            WHERE tenant_id = %s AND target_project_id = %s
            ORDER BY created_at DESC
        """
        return self.execute_query(query, (tenant_id, target_project_id))

    def create_version_push_transaction(
        self,
        project_id: str,
        tenant_id: str,
        creator_id: Optional[str],
        version_id: str,
        description: Optional[str],
        change_log: Optional[str],
        commit_author: Optional[str],
        commit_message: Optional[str],
        external_ref: Optional[str],
        parent_version_id: Optional[str],
        source_version_id: Optional[str],
        branch_row: Optional[Dict[str, Any]],
        client_base_revision_id: str,
        source_commit_sha: Optional[str] = None,
        source_committed_at: Optional[Any] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Insert version (optional parent), copy classes from source, advance branch tip under lock.

        ``source_commit_sha`` / ``source_committed_at`` record RAR-4.2 refresh
        provenance on the new revision (the repository source commit that produced it).
        Returns (full version row from get_version_by_id, copied_class_count).
        """
        base = (client_base_revision_id or "").strip()
        src = (source_version_id or "").strip() or None
        conn = self.connect()
        copied_count = 0
        new_id: Optional[str] = None
        prev_autocommit = self._begin_tx(conn)
        no_prior_revision = False
        try:
            with conn.cursor() as cursor:
                if branch_row is not None:
                    bid = str(branch_row["id"])
                    cursor.execute(
                        """
                        SELECT b.id, b.tip_version_id, b.require_merge_path
                        FROM apiome.version_branches b
                        JOIN apiome.projects p ON b.project_id = p.id
                        WHERE b.id = %s AND b.project_id = %s AND p.tenant_id = %s
                        FOR UPDATE
                        """,
                        (bid, project_id, tenant_id),
                    )
                    locked = cursor.fetchone()
                    if not locked:
                        raise BranchNotFoundError(bid)
                    if str(locked["tip_version_id"]) != base:
                        raise StaleHeadPushError(str(locked["tip_version_id"]))
                else:
                    # No named branches: lock the project row to serialize concurrent no-branch
                    # pushes and re-verify the head under the lock (TOCTOU fix, #2566).
                    cursor.execute(
                        """
                        SELECT p.id FROM apiome.projects p
                        WHERE p.id = %s AND p.tenant_id = %s
                        FOR UPDATE
                        """,
                        (project_id, tenant_id),
                    )
                    if not cursor.fetchone():
                        raise ValueError("Project not found or not accessible")
                    cursor.execute(
                        """
                        SELECT v.id::text AS id
                        FROM apiome.versions v
                        WHERE v.project_id = %s AND v.deleted_at IS NULL
                        ORDER BY v.created_at DESC
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    head_row = cursor.fetchone()
                    current_tip: Optional[str] = str(head_row["id"]) if head_row else None
                    no_prior_revision = current_tip is None
                    if current_tip is None and base:
                        raise ValueError("baseRevisionId must be empty for projects with no existing revisions")
                    if current_tip is not None and base != current_tip:
                        raise StaleHeadPushError(current_tip)

                cursor.execute(
                    """
                    INSERT INTO apiome.versions
                    (project_id, creator_id, version_id, description, change_log,
                     commit_author, commit_message, external_ref, parent_version_id,
                     source_commit_sha, source_committed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        project_id,
                        creator_id,
                        version_id,
                        description,
                        change_log,
                        commit_author,
                        commit_message,
                        external_ref,
                        parent_version_id,
                        source_commit_sha,
                        source_committed_at,
                    ),
                )
                row = cursor.fetchone()
                if not row or row.get("id") is None:
                    raise ValueError("Failed to insert version")
                new_id = str(row["id"])

                if src:
                    copied_count = self.copy_classes_from_version_for_merge(cursor, src, new_id)

                if branch_row is not None:
                    cursor.execute(
                        """
                        UPDATE apiome.version_branches
                        SET tip_version_id = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (new_id, str(branch_row["id"])),
                    )
                elif no_prior_revision:
                    # First commit in a brand-new project: bootstrap a default main branch (#2727).
                    cursor.execute(
                        """
                        INSERT INTO apiome.version_branches
                            (project_id, name, tip_version_id, created_by, branched_from_revision_id,
                             is_default, require_merge_path)
                        VALUES (%s, 'main', %s, %s, %s, true, true)
                        ON CONFLICT (project_id, name)
                        DO UPDATE SET
                            tip_version_id = EXCLUDED.tip_version_id,
                            is_default = true,
                            require_merge_path = true,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (project_id, new_id, creator_id, new_id),
                    )

            conn.commit()
        except (StaleHeadPushError, BranchNotFoundError):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = prev_autocommit

        if not new_id:
            raise ValueError("create_version_push_transaction: missing new id")

        full = self.get_version_by_id(new_id, tenant_id)
        if not full:
            raise ValueError("Version created but could not be loaded")
        return full, copied_count

    _MERGE_SESSION_TRANSITIONS: Dict[str, Set[str]] = {
        "preview": {"resolving", "aborted"},
        "resolving": {"applied", "aborted"},
        "applied": set(),
        "aborted": set(),
    }

    def _merge_session_project_scope(
        self, merge_session_id: str, project_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        q = """
            SELECT ms.id, ms.project_id, ms.source_branch_id, ms.source_branch_name, ms.target_branch_name,
                   ms.merge_base_version_id, ms.source_tip_version_id, ms.target_tip_version_id,
                   ms.status, ms.created_by, ms.created_at, ms.updated_at
            FROM apiome.merge_sessions ms
            JOIN apiome.projects p ON ms.project_id = p.id
            WHERE ms.id = %s AND ms.project_id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
        """
        rows = self.execute_query(q, (merge_session_id, project_id, tenant_id))
        return dict(rows[0]) if rows else None

    def create_merge_session_for_preview(
        self,
        project_id: str,
        tenant_id: str,
        source_branch_name: str,
        target_branch_name: str,
        source_branch_id: Optional[str],
        merge_base_version_id: str,
        source_tip_version_id: str,
        target_tip_version_id: str,
        conflict_records: List[Dict[str, Any]],
        created_by: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Insert merge session in ``preview``, conflict rows, and initial status event (#2573).
        """
        proj = self.get_project_by_id(project_id, tenant_id)
        if not proj:
            return None

        conn = self.connect()
        session_row: Optional[Dict[str, Any]] = None
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.merge_sessions (
                        project_id, source_branch_id, source_branch_name, target_branch_name,
                        merge_base_version_id, source_tip_version_id, target_tip_version_id,
                        status, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'preview', %s)
                    RETURNING id, project_id, source_branch_id, source_branch_name, target_branch_name,
                              merge_base_version_id, source_tip_version_id, target_tip_version_id,
                              status, created_by, created_at, updated_at
                    """,
                    (
                        project_id,
                        source_branch_id,
                        source_branch_name.strip(),
                        target_branch_name.strip(),
                        merge_base_version_id,
                        source_tip_version_id,
                        target_tip_version_id,
                        created_by,
                    ),
                )
                session_row = dict(cursor.fetchone() or {})
                sid = str(session_row["id"])

                for i, rec in enumerate(conflict_records):
                    path = (rec.get("path") or "").strip()
                    kinds = rec.get("kinds") or []
                    if not path:
                        continue
                    cursor.execute(
                        """
                        INSERT INTO apiome.merge_session_conflicts (merge_session_id, path, kinds, sort_order)
                        VALUES (%s, %s, %s::jsonb, %s)
                        """,
                        (sid, path, Json(kinds), i),
                    )

                cursor.execute(
                    """
                    INSERT INTO apiome.merge_session_status_events (merge_session_id, from_status, to_status, changed_by)
                    VALUES (%s, NULL, 'preview', %s)
                    """,
                    (sid, created_by),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            _logger.exception(
                "create_merge_session_for_preview failed project_id=%s tenant_id=%s",
                project_id,
                tenant_id,
            )
            return None

        return session_row

    def get_merge_session_detail(
        self, merge_session_id: str, project_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Session row plus ordered status events for the same project/tenant (#2573)."""
        base = self._merge_session_project_scope(merge_session_id, project_id, tenant_id)
        if not base:
            return None
        ev = self.execute_query(
            """
            SELECT id, from_status, to_status, changed_by, changed_at
            FROM apiome.merge_session_status_events
            WHERE merge_session_id = %s
            ORDER BY changed_at ASC, id ASC
            """,
            (merge_session_id,),
        )
        return {"session": base, "status_events": [dict(r) for r in ev]}

    def list_merge_session_conflicts(
        self, merge_session_id: str, project_id: str, tenant_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        if not self._merge_session_project_scope(merge_session_id, project_id, tenant_id):
            return None
        rows = self.execute_query(
            """
            SELECT id, path, kinds, sort_order, created_at
            FROM apiome.merge_session_conflicts
            WHERE merge_session_id = %s
            ORDER BY sort_order ASC, path ASC
            """,
            (merge_session_id,),
        )
        return [dict(r) for r in rows]

    def update_merge_session_status(
        self,
        merge_session_id: str,
        project_id: str,
        tenant_id: str,
        new_status: str,
        changed_by: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        """
        Validated transition; returns (ok, error_message).
        """
        ns = (new_status or "").strip()
        if ns not in self._MERGE_SESSION_TRANSITIONS:
            return False, f"Invalid status: {new_status}"

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                # Lock the row for this transaction to prevent concurrent status changes.
                cursor.execute(
                    """
                    SELECT ms.status
                    FROM apiome.merge_sessions ms
                    JOIN apiome.projects p ON ms.project_id = p.id
                    WHERE ms.id = %s AND ms.project_id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
                    FOR UPDATE
                    """,
                    (merge_session_id, project_id, tenant_id),
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return False, "Merge session not found"

                cur_status = str(row["status"])
                allowed = self._MERGE_SESSION_TRANSITIONS.get(cur_status, set())
                if ns not in allowed:
                    conn.rollback()
                    return False, f"Cannot transition from {cur_status} to {ns}"

                cursor.execute(
                    """
                    UPDATE apiome.merge_sessions
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND project_id = %s AND status = %s
                    """,
                    (ns, merge_session_id, project_id, cur_status),
                )
                if cursor.rowcount == 0:
                    conn.rollback()
                    return False, f"Cannot transition from {cur_status} to {ns}"

                cursor.execute(
                    """
                    INSERT INTO apiome.merge_session_status_events (merge_session_id, from_status, to_status, changed_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (merge_session_id, cur_status, ns, changed_by),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            _logger.exception("update_merge_session_status failed merge_session_id=%s", merge_session_id)
            return False, "Database error updating merge session"

        return True, None

    def _draft_lock_version_row_for_update(
        self, cursor, tenant_id: str, project_id: str, version_record_id: str
    ) -> Optional[Dict[str, Any]]:
        """Lock the version row; return id and published, or None if not found."""
        cursor.execute(
            """
            SELECT v.id::text AS id, v.published
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s::uuid AND v.project_id = %s AND p.tenant_id = %s
              AND v.deleted_at IS NULL
            FOR UPDATE OF v
            """,
            (version_record_id, project_id, tenant_id),
        )
        return cursor.fetchone()

    def _draft_lock_expires_active(self, exp: Any) -> bool:
        from datetime import timezone

        if exp is None:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        rows = self.execute_query(
            """
            SELECT CURRENT_TIMESTAMP AS current_timestamp
            """
        )
        db_now = rows[0]["current_timestamp"] if rows else None
        if db_now is None:
            return False
        if db_now.tzinfo is None:
            db_now = db_now.replace(tzinfo=timezone.utc)
        return exp > db_now

    def get_version_draft_lock_status(
        self,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
    ) -> Dict[str, Any]:
        """
        Read-only draft lock state for polling (#2585).

        Returns:
            ``{active: False}`` when no row, version missing, published, no lock, or lock expired.
            ``{active: True, version_id, owner_user_id, expires_at}`` when a lock is active.
        """
        rows = self.execute_query(
            """
            SELECT v.id::text AS version_id, v.published,
                   l.owner_user_id::text AS owner_user_id, l.expires_at
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.version_draft_lock l ON l.version_id = v.id
            WHERE v.id = %s::uuid AND v.project_id = %s AND p.tenant_id = %s
              AND v.deleted_at IS NULL
            """,
            (version_record_id, project_id, tenant_id),
        )
        if not rows:
            return {"active": False}
        row = rows[0]
        if row.get("published"):
            return {"active": False}
        ouid = row.get("owner_user_id")
        exp = row.get("expires_at")
        if not ouid or exp is None:
            return {"active": False}
        if not self._draft_lock_expires_active(exp):
            return {"active": False}
        return {
            "active": True,
            "version_id": str(row["version_id"]),
            "owner_user_id": ouid,
            "expires_at": exp,
        }

    def acquire_version_draft_lock(
        self,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
        user_id: str,
        lease_seconds: int,
    ) -> Dict[str, Any]:
        """
        Acquire or refresh a draft edit lock on an unpublished revision.

        Returns:
            ``{kind: 'ok', version_id, owner_user_id, expires_at}`` on success.
            ``{kind: 'conflict', owner_user_id, expires_at}`` when another user holds an active lock.

        Raises:
            ValueError: ``version_not_found`` or ``published_version``.
        """
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                vrow = self._draft_lock_version_row_for_update(
                    cursor, tenant_id, project_id, version_record_id
                )
                if not vrow:
                    conn.rollback()
                    raise ValueError("version_not_found")
                if vrow.get("published"):
                    conn.rollback()
                    raise ValueError("published_version")

                vid = str(vrow["id"])
                cursor.execute(
                    """
                    SELECT owner_user_id::text AS owner_user_id, expires_at
                    FROM apiome.version_draft_lock
                    WHERE version_id = %s::uuid
                    FOR UPDATE
                    """,
                    (vid,),
                )
                lock_row = cursor.fetchone()

                if not lock_row:
                    cursor.execute(
                        """
                        INSERT INTO apiome.version_draft_lock
                          (version_id, owner_user_id, expires_at, updated_at)
                        VALUES (
                          %s::uuid, %s::uuid,
                          NOW() + (%s * INTERVAL '1 second'),
                          CURRENT_TIMESTAMP
                        )
                        RETURNING owner_user_id::text AS owner_user_id, expires_at
                        """,
                        (vid, user_id, lease_seconds),
                    )
                    out = cursor.fetchone()
                    conn.commit()
                    return {
                        "kind": "ok",
                        "version_id": vid,
                        "owner_user_id": str(out["owner_user_id"]),
                        "expires_at": out["expires_at"],
                    }

                owner = str(lock_row["owner_user_id"])
                exp = lock_row["expires_at"]
                active = self._draft_lock_expires_active(exp)

                if not active:
                    cursor.execute(
                        """
                        UPDATE apiome.version_draft_lock
                        SET owner_user_id = %s::uuid,
                            expires_at = NOW() + (%s * INTERVAL '1 second'),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE version_id = %s::uuid
                        RETURNING owner_user_id::text AS owner_user_id, expires_at
                        """,
                        (user_id, lease_seconds, vid),
                    )
                    out = cursor.fetchone()
                    conn.commit()
                    return {
                        "kind": "ok",
                        "version_id": vid,
                        "owner_user_id": str(out["owner_user_id"]),
                        "expires_at": out["expires_at"],
                    }

                if owner == user_id:
                    cursor.execute(
                        """
                        UPDATE apiome.version_draft_lock
                        SET expires_at = NOW() + (%s * INTERVAL '1 second'),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE version_id = %s::uuid
                        RETURNING owner_user_id::text AS owner_user_id, expires_at
                        """,
                        (lease_seconds, vid),
                    )
                    out = cursor.fetchone()
                    conn.commit()
                    return {
                        "kind": "ok",
                        "version_id": vid,
                        "owner_user_id": str(out["owner_user_id"]),
                        "expires_at": out["expires_at"],
                    }

                conn.rollback()
                return {
                    "kind": "conflict",
                    "owner_user_id": owner,
                    "expires_at": exp,
                }
        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    def renew_version_draft_lock(
        self,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
        user_id: str,
        lease_seconds: int,
    ) -> Dict[str, Any]:
        """
        Extend an active draft lock held by the same user.

        Returns:
            ``{kind: 'ok', ...}``, ``{kind: 'not_held'}``, or
            ``{kind: 'conflict', owner_user_id, expires_at}``.

        Raises:
            ValueError: ``version_not_found`` or ``published_version``.
        """
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                vrow = self._draft_lock_version_row_for_update(
                    cursor, tenant_id, project_id, version_record_id
                )
                if not vrow:
                    conn.rollback()
                    raise ValueError("version_not_found")
                if vrow.get("published"):
                    conn.rollback()
                    raise ValueError("published_version")

                vid = str(vrow["id"])
                cursor.execute(
                    """
                    SELECT owner_user_id::text AS owner_user_id, expires_at
                    FROM apiome.version_draft_lock
                    WHERE version_id = %s::uuid
                    FOR UPDATE
                    """,
                    (vid,),
                )
                lock_row = cursor.fetchone()
                if not lock_row:
                    conn.rollback()
                    return {"kind": "not_held"}

                if not self._draft_lock_expires_active(lock_row["expires_at"]):
                    conn.rollback()
                    return {"kind": "not_held"}

                owner = str(lock_row["owner_user_id"])
                if owner != user_id:
                    conn.rollback()
                    return {
                        "kind": "conflict",
                        "owner_user_id": owner,
                        "expires_at": lock_row["expires_at"],
                    }

                cursor.execute(
                    """
                    UPDATE apiome.version_draft_lock
                    SET expires_at = NOW() + (%s * INTERVAL '1 second'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE version_id = %s::uuid AND owner_user_id = %s::uuid
                    RETURNING owner_user_id::text AS owner_user_id, expires_at
                    """,
                    (lease_seconds, vid, user_id),
                )
                out = cursor.fetchone()
                conn.commit()
                return {
                    "kind": "ok",
                    "version_id": vid,
                    "owner_user_id": str(out["owner_user_id"]),
                    "expires_at": out["expires_at"],
                }
        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    def release_version_draft_lock(
        self,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
        user_id: str,
    ) -> str:
        """
        Release a draft lock held by ``user_id``.

        Returns:
            ``released``, ``not_found`` (no lock row), or ``forbidden`` (another user holds the lock).
        """
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                vrow = self._draft_lock_version_row_for_update(
                    cursor, tenant_id, project_id, version_record_id
                )
                if not vrow:
                    conn.rollback()
                    raise ValueError("version_not_found")

                vid = str(vrow["id"])
                cursor.execute(
                    """
                    DELETE FROM apiome.version_draft_lock
                    WHERE version_id = %s::uuid AND owner_user_id = %s::uuid
                    RETURNING version_id
                    """,
                    (vid, user_id),
                )
                if cursor.fetchone():
                    conn.commit()
                    return "released"

                cursor.execute(
                    """
                    SELECT 1 FROM apiome.version_draft_lock
                    WHERE version_id = %s::uuid
                    LIMIT 1
                    """,
                    (vid,),
                )
                if not cursor.fetchone():
                    conn.commit()
                    return "not_found"

                conn.rollback()
                return "forbidden"
        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    def force_release_version_draft_lock(
        self,
        tenant_id: str,
        project_id: str,
        version_record_id: str,
    ) -> bool:
        """
        Remove any draft lock on the revision (tenant-admin force release).

        Returns:
            True if a lock row was deleted.

        Raises:
            ValueError: ``version_not_found``.
        """
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                vrow = self._draft_lock_version_row_for_update(
                    cursor, tenant_id, project_id, version_record_id
                )
                if not vrow:
                    conn.rollback()
                    raise ValueError("version_not_found")

                vid = str(vrow["id"])
                cursor.execute(
                    """
                    DELETE FROM apiome.version_draft_lock
                    WHERE version_id = %s::uuid
                    RETURNING version_id
                    """,
                    (vid,),
                )
                deleted = cursor.fetchone() is not None
                conn.commit()
                return deleted
        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    @staticmethod
    def hash_webhook_signing_secret(plain: str) -> str:
        """Store bcrypt(SHA256(utf8(plain))) so long secrets are safe for bcrypt's 72-byte input limit."""
        digest = hashlib.sha256(plain.encode("utf-8")).digest()
        hashed = bcrypt.hashpw(digest, bcrypt.gensalt())
        return hashed.decode("ascii")

    def create_push_webhook_subscription(
        self,
        tenant_id: str,
        url: str,
        url_normalized: str,
        signing_secret_plain: str,
        active: bool = True,
    ) -> Dict[str, Any]:
        """Insert a push webhook row; returns public fields only (no hash)."""
        secret_hash = self.hash_webhook_signing_secret(signing_secret_plain)
        secret_enc = encrypt_signing_secret(signing_secret_plain)
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.push_webhook_subscriptions
                      (tenant_id, url, url_normalized, active, signing_secret_hash, signing_secret_encrypted)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s)
                    RETURNING id, url, active, signing_secret_ref, created_at, updated_at
                    """,
                    (tenant_id, url, url_normalized, active, secret_hash, secret_enc),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except Exception as e:
            conn.rollback()
            raise e

    def list_push_webhook_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT id, url, active, signing_secret_ref, created_at, updated_at
            FROM apiome.push_webhook_subscriptions
            WHERE tenant_id = %s::uuid AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        return self.execute_query(q, (tenant_id,))

    def list_active_push_webhook_subscription_ids(self, tenant_id: str) -> List[str]:
        """Return the ids of every active (non-deleted) push-webhook subscription for a tenant.

        Used by the refresh-notification fan-out (RAR-5.4) to enqueue one delivery
        per subscribed channel. Inactive and soft-deleted subscriptions are excluded
        so a notification is never queued for a channel that cannot receive it.

        Args:
            tenant_id: Owning tenant id.

        Returns:
            A list of subscription id strings (possibly empty), newest first.
        """
        q = """
            SELECT id
            FROM apiome.push_webhook_subscriptions
            WHERE tenant_id = %s::uuid AND active = true AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        return [str(row["id"]) for row in self.execute_query(q, (tenant_id,))]

    def get_push_webhook_subscription(
        self, tenant_id: str, subscription_id: str
    ) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, url, active, signing_secret_ref, created_at, updated_at
            FROM apiome.push_webhook_subscriptions
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND deleted_at IS NULL
        """
        rows = self.execute_query(q, (tenant_id, subscription_id))
        return rows[0] if rows else None

    def update_push_webhook_subscription(
        self,
        tenant_id: str,
        subscription_id: str,
        url: Optional[str] = None,
        url_normalized: Optional[str] = None,
        active: Optional[bool] = None,
        signing_secret_plain: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update subscription fields. Returns public row or None if not found.
        Raises ValueError if no updatable fields were provided.
        """
        sets: List[str] = []
        params: List[Any] = []

        if url is not None and url_normalized is not None:
            sets.append("url = %s")
            sets.append("url_normalized = %s")
            params.extend([url, url_normalized])
        elif url is not None or url_normalized is not None:
            raise ValueError("url_and_normalized_together")

        if active is not None:
            sets.append("active = %s")
            params.append(active)

        if signing_secret_plain is not None:
            sets.append("signing_secret_hash = %s")
            params.append(self.hash_webhook_signing_secret(signing_secret_plain))
            sets.append("signing_secret_encrypted = %s")
            params.append(encrypt_signing_secret(signing_secret_plain))

        if not sets:
            raise ValueError("no_updates")

        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([tenant_id, subscription_id])

        q = f"""
            UPDATE apiome.push_webhook_subscriptions
            SET {", ".join(sets)}
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND deleted_at IS NULL
            RETURNING id, url, active, signing_secret_ref, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, tuple(params))
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def enqueue_push_webhook_delivery(
        self,
        tenant_id: str,
        subscription_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Queue one outbound delivery. Raises ValueError if subscription is missing or inactive."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, active FROM apiome.push_webhook_subscriptions
                    WHERE tenant_id = %s::uuid AND id = %s::uuid AND deleted_at IS NULL
                    """,
                    (tenant_id, subscription_id),
                )
                sub = cursor.fetchone()
                if not sub:
                    raise ValueError("subscription_not_found")
                if not sub["active"]:
                    raise ValueError("subscription_inactive")
                cursor.execute(
                    """
                    INSERT INTO apiome.push_webhook_delivery_events
                      (tenant_id, subscription_id, event_type, payload, status, attempt_count, next_retry_at)
                    VALUES (%s::uuid, %s::uuid, %s, %s::jsonb, 'pending', 0, CURRENT_TIMESTAMP)
                    RETURNING id, tenant_id, subscription_id, event_type, status, attempt_count, next_retry_at, created_at
                    """,
                    (tenant_id, subscription_id, event_type, Json(payload)),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except ValueError:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            raise e

    def get_next_due_push_webhook_delivery(self) -> Optional[Dict[str, Any]]:
        """Atomically claim and return one due event joined with subscription URL and ciphertext, or None."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    WITH next_event AS (
                        SELECT e.id
                        FROM apiome.push_webhook_delivery_events e
                        INNER JOIN apiome.push_webhook_subscriptions s
                          ON s.id = e.subscription_id
                         AND s.deleted_at IS NULL
                        WHERE e.status IN ('pending', 'retrying')
                          AND e.next_retry_at IS NOT NULL
                          AND e.next_retry_at <= CURRENT_TIMESTAMP
                          AND e.attempt_count < %s
                        ORDER BY e.next_retry_at ASC
                        FOR UPDATE OF e SKIP LOCKED
                        LIMIT 1
                    ),
                    claimed_event AS (
                        UPDATE apiome.push_webhook_delivery_events e
                        SET status = 'processing',
                            updated_at = CURRENT_TIMESTAMP
                        FROM next_event ne
                        WHERE e.id = ne.id
                        RETURNING
                          e.id AS event_id,
                          e.tenant_id,
                          e.subscription_id,
                          e.event_type,
                          e.payload,
                          e.status AS event_status,
                          e.attempt_count,
                          e.next_retry_at
                    )
                    SELECT
                      ce.event_id,
                      ce.tenant_id,
                      ce.subscription_id,
                      ce.event_type,
                      ce.payload,
                      ce.event_status,
                      ce.attempt_count,
                      ce.next_retry_at,
                      s.url AS subscription_url,
                      s.active AS subscription_active,
                      s.signing_secret_encrypted
                    FROM claimed_event ce
                    INNER JOIN apiome.push_webhook_subscriptions s
                      ON s.id = ce.subscription_id
                     AND s.deleted_at IS NULL
                    """,
                    (WEBHOOK_MAX_DELIVERY_ATTEMPTS,),
                )
                row = cursor.fetchone()
                if row:
                    conn.commit()
                    return dict(row)
                conn.rollback()
                return None
        except Exception:
            conn.rollback()
            raise

    def finalize_push_webhook_delivery_attempt(
        self,
        event_id: str,
        *,
        attempt_number: int,
        http_status: Optional[int],
        response_body_preview: Optional[str],
        error_message: Optional[str],
        latency_ms: int,
        new_status: str,
        new_attempt_count: int,
        next_retry_at: Optional[datetime],
        last_error: Optional[str],
    ) -> None:
        """Insert one attempt row and update the parent event (single transaction)."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.push_webhook_delivery_attempts
                      (delivery_event_id, attempt_number, http_status, response_body_preview, error_message, latency_ms)
                    VALUES (%s::uuid, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_id,
                        attempt_number,
                        http_status,
                        response_body_preview,
                        error_message,
                        latency_ms,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE apiome.push_webhook_delivery_events
                    SET status = %s,
                        attempt_count = %s,
                        next_retry_at = %s,
                        last_error = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s::uuid
                    """,
                    (new_status, new_attempt_count, next_retry_at, last_error, event_id),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def list_push_webhook_dead_letter_events(self, tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        q = """
            SELECT id, subscription_id, event_type, payload, attempt_count, last_error, created_at, updated_at
            FROM apiome.push_webhook_delivery_events
            WHERE tenant_id = %s::uuid AND status = 'dead_letter'
            ORDER BY updated_at DESC
            LIMIT %s
        """
        return self.execute_query(q, (tenant_id, limit))

    def get_push_webhook_delivery_event(self, tenant_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, subscription_id, event_type, payload, status, attempt_count, next_retry_at, last_error,
                   created_at, updated_at
            FROM apiome.push_webhook_delivery_events
            WHERE tenant_id = %s::uuid AND id = %s::uuid
        """
        rows = self.execute_query(q, (tenant_id, event_id))
        return dict(rows[0]) if rows else None

    def list_push_webhook_delivery_attempts(self, delivery_event_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT attempt_number, http_status, response_body_preview, error_message, latency_ms, attempted_at
            FROM apiome.push_webhook_delivery_attempts
            WHERE delivery_event_id = %s::uuid
            ORDER BY attempt_number ASC
        """
        return self.execute_query(q, (delivery_event_id,))

    def get_change_report_by_published_revision(
        self,
        published_revision_id: str,
        tenant_id: str,
        project_id: str,
    ) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                   change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                   edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                   edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                   created_at, updated_at
            FROM apiome.change_reports
            WHERE published_revision_id = %s::uuid
              AND tenant_id = %s::uuid
              AND project_id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (published_revision_id, tenant_id, project_id))
        return dict(rows[0]) if rows else None

    def insert_change_report_if_absent(
        self,
        tenant_id: str,
        project_id: str,
        published_revision_id: str,
        baseline_revision_id: Optional[str],
        change_model_json: Dict[str, Any],
        rendered_body: Optional[str] = None,
        header_snapshot: Optional[str] = None,
        footnote_snapshot: Optional[str] = None,
        template_version_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Insert one row per published_revision_id or return the existing row unchanged
        (change_model_json is immutable after the first insert).
        """
        has_render = bool(
            rendered_body is not None or header_snapshot is not None or footnote_snapshot is not None
        )
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.change_reports (
                        tenant_id, project_id, published_revision_id, baseline_revision_id,
                        change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                        template_version_id, rendered_at
                    ) VALUES (
                        %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                        %s, %s, %s, %s, %s::uuid,
                        CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
                    )
                    ON CONFLICT (published_revision_id) DO NOTHING
                    RETURNING id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                              change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                              edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                              edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                              created_at, updated_at
                    """,
                    (
                        tenant_id,
                        project_id,
                        published_revision_id,
                        baseline_revision_id,
                        Json(change_model_json),
                        rendered_body,
                        header_snapshot,
                        footnote_snapshot,
                        template_version_id if template_version_id else None,
                        has_render,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                               change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                               edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                               edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                               created_at, updated_at
                        FROM apiome.change_reports
                        WHERE published_revision_id = %s::uuid
                          AND tenant_id = %s::uuid
                          AND project_id = %s::uuid
                        LIMIT 1
                        """,
                        (published_revision_id, tenant_id, project_id),
                    )
                    row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def patch_change_report_edits(
        self,
        published_revision_id: str,
        tenant_id: str,
        project_id: str,
        user_id: str,
        *,
        clear_edits: bool = False,
        set_edited_rendered_body: bool = False,
        edited_rendered_body: Optional[str] = None,
        set_edited_header: bool = False,
        edited_header_snapshot: Optional[str] = None,
        set_edited_footnote: bool = False,
        edited_footnote_snapshot: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update user edit snapshots; missing *_was_set flags leave columns unchanged."""
        if clear_edits:
            q = """
                UPDATE apiome.change_reports
                SET edited_rendered_body = NULL,
                    edited_header_snapshot = NULL,
                    edited_footnote_snapshot = NULL,
                    edited_at = NULL,
                    edited_by = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE published_revision_id = %s::uuid
                  AND tenant_id = %s::uuid
                  AND project_id = %s::uuid
                RETURNING id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                          change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                          edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                          edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                          created_at, updated_at
            """
            conn = self.connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(q, (published_revision_id, tenant_id, project_id))
                    row = cursor.fetchone()
                    conn.commit()
                    return dict(row) if row else None
            except Exception as e:
                conn.rollback()
                raise e

        assignments: List[str] = []
        params: List[Any] = []
        if set_edited_rendered_body:
            assignments.append("edited_rendered_body = %s")
            params.append(edited_rendered_body)
        if set_edited_header:
            assignments.append("edited_header_snapshot = %s")
            params.append(edited_header_snapshot)
        if set_edited_footnote:
            assignments.append("edited_footnote_snapshot = %s")
            params.append(edited_footnote_snapshot)
        if not assignments:
            return self.get_change_report_by_published_revision(
                published_revision_id, tenant_id, project_id
            )

        assignments.append("edited_at = CURRENT_TIMESTAMP")
        assignments.append("edited_by = %s::uuid")
        params.append(user_id)
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([published_revision_id, tenant_id, project_id])

        q = f"""
            UPDATE apiome.change_reports
            SET {", ".join(assignments)}
            WHERE published_revision_id = %s::uuid
              AND tenant_id = %s::uuid
              AND project_id = %s::uuid
            RETURNING id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                      change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                      edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                      edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                      created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, tuple(params))
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def apply_change_report_regeneration(
        self,
        published_revision_id: str,
        tenant_id: str,
        project_id: str,
        header_snapshot: str,
        rendered_body: str,
        footnote_snapshot: str,
        discard_user_edits: bool,
        template_version_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Re-run placeholder/template render: update rendered_* and regeneration timestamps."""
        if discard_user_edits:
            q = """
                UPDATE apiome.change_reports
                SET rendered_body = %s,
                    header_snapshot = %s,
                    footnote_snapshot = %s,
                    rendered_at = CURRENT_TIMESTAMP,
                    regenerated_at = CURRENT_TIMESTAMP,
                    edited_rendered_body = NULL,
                    edited_header_snapshot = NULL,
                    edited_footnote_snapshot = NULL,
                    edited_at = NULL,
                    edited_by = NULL,
                    template_version_id = COALESCE(%s::uuid, template_version_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE published_revision_id = %s::uuid
                  AND tenant_id = %s::uuid
                  AND project_id = %s::uuid
                RETURNING id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                          change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                          edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                          edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                          created_at, updated_at
            """
            params = (
                rendered_body,
                header_snapshot,
                footnote_snapshot,
                template_version_id if template_version_id else None,
                published_revision_id,
                tenant_id,
                project_id,
            )
        else:
            q = """
                UPDATE apiome.change_reports
                SET rendered_body = %s,
                    header_snapshot = %s,
                    footnote_snapshot = %s,
                    rendered_at = CURRENT_TIMESTAMP,
                    regenerated_at = CURRENT_TIMESTAMP,
                    template_version_id = COALESCE(%s::uuid, template_version_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE published_revision_id = %s::uuid
                  AND tenant_id = %s::uuid
                  AND project_id = %s::uuid
                RETURNING id, tenant_id, project_id, published_revision_id, baseline_revision_id,
                          change_model_json, rendered_body, header_snapshot, footnote_snapshot,
                          edited_rendered_body, edited_header_snapshot, edited_footnote_snapshot,
                          edited_at, edited_by, template_version_id, rendered_at, regenerated_at,
                          created_at, updated_at
            """
            params = (
                rendered_body,
                header_snapshot,
                footnote_snapshot,
                template_version_id if template_version_id else None,
                published_revision_id,
                tenant_id,
                project_id,
            )
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, params)
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    # ==================== Change report templates (CR-03, #2701) ====================

    def ensure_system_change_report_template(self) -> None:
        """Insert bundled system template row if missing (well-known id + semver 1.0.0)."""
        from .change_report_default_templates import (
            DEFAULT_BODY_TEMPLATE,
            DEFAULT_FOOTNOTE_TEMPLATE,
            DEFAULT_HEADER_TEMPLATE,
            SYSTEM_TEMPLATE_ID,
            SYSTEM_TEMPLATE_SEMVER,
        )

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apiome.change_report_template_versions (
                        id, owner_tenant_id, semver, header_template, body_template, footnote_template
                    ) VALUES (%s::uuid, NULL, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        SYSTEM_TEMPLATE_ID,
                        SYSTEM_TEMPLATE_SEMVER,
                        DEFAULT_HEADER_TEMPLATE,
                        DEFAULT_BODY_TEMPLATE,
                        DEFAULT_FOOTNOTE_TEMPLATE,
                    ),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def get_change_report_template_version_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, owner_tenant_id, semver, header_template, body_template, footnote_template,
                   created_at, created_by
            FROM apiome.change_report_template_versions
            WHERE id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (template_id,))
        return dict(rows[0]) if rows else None

    def list_change_report_template_version_summaries(self, tenant_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT id, owner_tenant_id, semver, created_at
            FROM apiome.change_report_template_versions
            WHERE owner_tenant_id IS NULL OR owner_tenant_id = %s::uuid
            ORDER BY owner_tenant_id NULLS FIRST, semver ASC
        """
        return self.execute_query(q, (tenant_id,))

    def insert_change_report_template_version(
        self,
        tenant_id: str,
        semver: str,
        header_template: str,
        body_template: str,
        footnote_template: str,
        created_by: Optional[str],
    ) -> Dict[str, Any]:
        q = """
            INSERT INTO apiome.change_report_template_versions (
                owner_tenant_id, semver, header_template, body_template, footnote_template, created_by
            ) VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid)
            RETURNING id, owner_tenant_id, semver, header_template, body_template, footnote_template,
                      created_at, created_by
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    q,
                    (
                        tenant_id,
                        semver,
                        header_template,
                        body_template,
                        footnote_template,
                        created_by if created_by else None,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except Exception as e:
            conn.rollback()
            raise e

    def set_tenant_change_report_template_version(
        self,
        tenant_id: str,
        template_version_id: Optional[str],
    ) -> None:
        q = """
            UPDATE apiome.tenants
            SET change_report_template_version_id = %s::uuid,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    q,
                    (template_version_id if template_version_id else None, tenant_id),
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def get_tenant_change_report_template_version_id(self, tenant_id: str) -> Optional[str]:
        q = """
            SELECT change_report_template_version_id
            FROM apiome.tenants
            WHERE id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (tenant_id,))
        if not rows:
            return None
        v = rows[0].get("change_report_template_version_id")
        return str(v) if v is not None else None

    def get_external_auth_provider_for_user(self, linked_account_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, user_id, provider, access_token
            FROM apiome.external_auth_providers
            WHERE id = %s::uuid AND user_id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (linked_account_id, user_id))
        return dict(rows[0]) if rows else None

    def list_tenant_repositories(self, tenant_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT id, tenant_id, source, provider, clone_url, repository_full_name,
                   description, default_branch, visibility, status, created_at, updated_at,
                   linked_account_id, last_scanned_at, total_files, importable_count, branch_count,
                   refresh_interval_seconds, last_refreshed_at, auto_refresh_enabled
            FROM apiome.tenant_repositories
            WHERE tenant_id = %s::uuid AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        return self.execute_query(q, (tenant_id,))

    def get_tenant_repository(self, tenant_id: str, repository_id: str) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, tenant_id, source, provider, clone_url, repository_full_name,
                   description, default_branch, visibility, status, created_at, updated_at,
                   linked_account_id, last_scanned_at, total_files, importable_count, branch_count, created_by,
                   refresh_interval_seconds, last_refreshed_at, auto_refresh_enabled
            FROM apiome.tenant_repositories
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            LIMIT 1
        """
        rows = self.execute_query(q, (repository_id, tenant_id))
        return dict(rows[0]) if rows else None

    def list_due_repositories(
        self,
        *,
        floor_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return repositories due for an auto-refresh sweep tick (RAR-3.1).

        A repository is due when it has never been refreshed
        (``last_refreshed_at IS NULL``) or when at least its effective interval
        has elapsed since the last tick. The effective interval is the per-repo
        ``refresh_interval_seconds`` clamped up to the global floor, so a
        too-aggressive per-repo cadence cannot defeat the floor. Soft-deleted
        repositories, those not in a scannable ``ready``/``error`` state, and those
        with ``auto_refresh_enabled = FALSE`` (the per-repo RAR-3.3 opt-out) are
        excluded. The recency comparison is done in the database against
        ``now()`` so it does not depend on application clock skew.

        The actual rescan + enqueue is the RAR-3.2 sweep; this is the
        due-selection primitive it iterates.

        Args:
            floor_seconds: The global minimum interval; per-repo values below it
                are treated as the floor. Defaults to
                ``settings.refresh_min_interval_seconds`` when omitted.

        Returns:
            Repository rows due for refresh, oldest ``last_refreshed_at`` first
            (NULLs — never refreshed — first) for fair scheduling.
        """
        from .config import settings
        from .repository_refresh_cadence import DEFAULT_MIN_REFRESH_INTERVAL_SECONDS

        floor = floor_seconds if floor_seconds is not None else settings.refresh_min_interval_seconds
        if floor < 1:
            floor = DEFAULT_MIN_REFRESH_INTERVAL_SECONDS

        q = """
            SELECT id, tenant_id, source, provider, clone_url, repository_full_name,
                   description, default_branch, visibility, status, created_at, updated_at,
                   linked_account_id, last_scanned_at, total_files, importable_count, branch_count,
                   refresh_interval_seconds, last_refreshed_at, auto_refresh_enabled
            FROM apiome.tenant_repositories
            WHERE deleted_at IS NULL
              AND status IN ('ready', 'error')
              AND auto_refresh_enabled = TRUE
              AND (
                last_refreshed_at IS NULL
                OR last_refreshed_at <= now() - make_interval(
                     secs => GREATEST(refresh_interval_seconds, %s)
                   )
              )
            ORDER BY last_refreshed_at ASC NULLS FIRST, created_at ASC
        """
        return self.execute_query(q, (floor,))

    def mark_repository_refreshed(self, repository_id: str) -> bool:
        """Advance a repository's ``last_refreshed_at`` to now (RAR-3.1).

        Called by the sweep at the end of each tick for a repository so the next
        due check is measured from this moment. Returns True when a live row was
        updated (False when the id is unknown or soft-deleted).

        Args:
            repository_id: The repository whose refresh anchor to advance.

        Returns:
            True when a row was updated.
        """
        q = """
            UPDATE apiome.tenant_repositories
            SET last_refreshed_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND deleted_at IS NULL
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (repository_id,))
                row = cursor.fetchone()
                conn.commit()
                return bool(row)
        except Exception as e:
            conn.rollback()
            raise e

    def set_repository_refresh_interval(
        self,
        tenant_id: str,
        repository_id: str,
        interval_seconds: Optional[int],
    ) -> Optional[int]:
        """Set a repository's per-repo refresh cadence, clamped to the floor (RAR-3.1).

        The value is resolved through
        :func:`repository_refresh_cadence.resolve_refresh_interval` first, so a
        ``None``/non-positive value falls back to the configured default and a
        sub-floor value is clamped up (with a warning). The clamped value is what
        is persisted, so a later read needs no re-clamping.

        Args:
            tenant_id: Owning tenant id (scopes the update for isolation).
            repository_id: The repository to update.
            interval_seconds: The requested cadence in seconds, or None to reset
                to the configured default.

        Returns:
            The effective (clamped) interval that was stored, or None when no
            live repository matched the tenant + id.
        """
        from .config import settings
        from .repository_refresh_cadence import resolve_refresh_interval

        effective = resolve_refresh_interval(
            interval_seconds,
            floor_seconds=settings.refresh_min_interval_seconds,
            default_seconds=settings.refresh_default_interval_seconds,
        )
        q = """
            UPDATE apiome.tenant_repositories
            SET refresh_interval_seconds = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (effective, repository_id, tenant_id))
                row = cursor.fetchone()
                conn.commit()
                return effective if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def set_repository_auto_refresh_enabled(
        self,
        tenant_id: str,
        repository_id: str,
        enabled: bool,
    ) -> Optional[bool]:
        """Set a repository's per-repo auto-refresh opt-out flag (RAR-3.3).

        When ``enabled`` is False the refresh sweep's due-selection
        (:meth:`list_due_repositories`) skips this repository, so it is never
        auto-refreshed. The global ``APIOME_REFRESH_ENABLED`` kill switch and
        manual "Refresh Now" (RAR-5.2) are independent of this flag.

        Args:
            tenant_id: Owning tenant id (scopes the update for isolation).
            repository_id: The repository to update.
            enabled: True to allow auto-refresh, False to opt this repo out.

        Returns:
            The stored value (``enabled``) when a live repository matched the
            tenant + id, or None when no row was updated.
        """
        q = """
            UPDATE apiome.tenant_repositories
            SET auto_refresh_enabled = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (bool(enabled), repository_id, tenant_id))
                row = cursor.fetchone()
                conn.commit()
                return bool(enabled) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def try_acquire_repository_refresh_lock(self, repository_id: str) -> bool:
        """Try to take the per-repo auto-refresh advisory lock (RAR-3.2).

        Per-repo single-flight for the refresh sweep is enforced with a Postgres
        **session** advisory lock keyed on the repository id, so two workers (or
        two overlapping sweep ticks) never rescan and enqueue for the same repo at
        once. The lock is held on this :class:`Database`'s connection until
        :meth:`release_repository_refresh_lock` is called (or the connection
        closes); ``pg_try_advisory_lock`` is non-blocking, returning False
        immediately when another session holds it so the sweep can move on.

        Because the lock is session-scoped (not transaction-scoped), the
        ``execute_query`` commit here does not release it — acquire and release
        must run on the same connection, which the single-``Database``-per-tick
        sweep guarantees.

        Args:
            repository_id: The repository to serialize refreshes for.

        Returns:
            True when the lock was acquired, False when another session holds it.
        """
        rows = self.execute_query(
            "SELECT pg_try_advisory_lock(hashtext(%s)) AS locked",
            (f"repo-refresh:{repository_id}",),
        )
        return bool(rows and rows[0].get("locked"))

    def release_repository_refresh_lock(self, repository_id: str) -> None:
        """Release the per-repo auto-refresh advisory lock (RAR-3.2).

        Counterpart to :meth:`try_acquire_repository_refresh_lock`; must run on the
        same connection that acquired the lock. Safe to call even if the lock was
        not held (Postgres returns False and logs a warning, which is harmless).

        Args:
            repository_id: The repository whose lock to release.
        """
        self.execute_query(
            "SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked",
            (f"repo-refresh:{repository_id}",),
        )

    def list_repository_import_spec_branches(self, repository_id: str) -> List[str]:
        """Distinct branches that have a stored import spec for this repository (RAR-3.2).

        The refresh sweep only needs to rescan branches that actually have
        imported files to refresh; a repository with no captured spec yields an
        empty list and the sweep skips the (rate-limited) GitHub walk entirely.

        Args:
            repository_id: The repository to inspect.

        Returns:
            Distinct branch names with at least one stored import spec, sorted.
        """
        q = """
            SELECT DISTINCT branch
            FROM apiome.repository_import_spec
            WHERE repository_id = %s::uuid
            ORDER BY branch ASC
        """
        rows = self.execute_query(q, (repository_id,))
        return [str(r["branch"]) for r in rows if r.get("branch")]

    def list_repository_refresh_candidates(
        self, repository_id: str, branch: str
    ) -> List[Dict[str, Any]]:
        """Stored specs joined to their current indexed file, for one branch (RAR-3.2).

        Returns one row per imported-file lineage that still exists in the latest
        scan index, pairing the stored import spec (project, source descriptor,
        options, and the ``last_imported_*`` recency anchors from RAR-2.1) with the
        file's current remote freshness signals (``remote_committed_at`` /
        ``remote_blob_sha`` / ``remote_commit_sha``) from the just-completed
        rescan. The sweep feeds each row to the RAR-2.2 newer-than comparator to
        decide whether to enqueue a re-import.

        The join is an INNER join on ``tenant_repository_files`` so a spec whose
        file no longer exists upstream (deleted file) is *not* a refresh candidate
        — handling deletions is out of scope here.

        Args:
            repository_id: The repository to scan candidates for.
            branch: The branch whose files were just re-indexed.

        Returns:
            Candidate rows with the spec fields and the current remote signals.
        """
        q = """
            SELECT s.id AS import_spec_id, s.tenant_id, s.repository_id, s.branch, s.path,
                   s.project_id, s.source_kind, s.format_override, s.content_type,
                   s.options_json, s.spec_schema_version, s.created_by,
                   s.last_imported_commit_sha, s.last_imported_committed_at,
                   s.last_imported_blob_sha,
                   trf.commit_sha AS remote_commit_sha,
                   trf.committed_at AS remote_committed_at,
                   trf.blob_sha AS remote_blob_sha
            FROM apiome.repository_import_spec s
            INNER JOIN apiome.tenant_repository_files trf
              ON trf.repository_id = s.repository_id
             AND trf.branch = s.branch
             AND trf.path = s.path
            WHERE s.repository_id = %s::uuid AND s.branch = %s
            ORDER BY s.path ASC
        """
        return self.execute_query(q, (repository_id, branch))

    def enqueue_repository_refresh_job(
        self,
        *,
        tenant_id: str,
        repository_id: str,
        branch: str,
        path: str,
        import_spec_id: Optional[str] = None,
        project_id: Optional[str] = None,
        source_kind: Optional[str] = None,
        format_override: Optional[str] = None,
        content_type: Optional[str] = None,
        options_json: Optional[Any] = None,
        spec_schema_version: int = 1,
        created_by: Optional[str] = None,
        remote_commit_sha: Optional[str] = None,
        remote_committed_at: Optional[Any] = None,
        remote_blob_sha: Optional[str] = None,
        refresh_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Enqueue one spec-faithful re-import job for the EPIC-4 worker (RAR-3.2).

        Inserts a row into ``apiome.tenant_repository_refresh_jobs`` carrying a
        self-contained snapshot of the stored import spec (so the executor replays
        the user's original request even if the spec row later changes) plus the
        remote freshness signals that triggered it. The insert is idempotent at the
        file-lineage level via the partial unique index
        (``uq_tenant_repo_refresh_jobs_active_lineage``): if an active
        (queued/running) job already exists for ``(repository_id, branch, path)``
        the insert is a no-op and ``None`` is returned, so a repeated sweep tick
        never duplicates work.

        Args:
            tenant_id: Owning tenant id.
            repository_id: Source repository id.
            branch: Branch the file lives on.
            path: Repository-relative file path (lineage key).
            import_spec_id: Back-reference to the source spec row, if known.
            project_id: Catalog project the original import targeted.
            source_kind: Importer discriminator (for example ``openapi-3``).
            format_override: Explicit importer ``--format`` override, if any.
            content_type: MIME type used to read the file, if known.
            options_json: Snapshot of the full ``SpecImportOptions`` payload.
            spec_schema_version: Envelope version of the captured spec.
            created_by: User id that initiated the original import, if known.
            remote_commit_sha: Branch-tip commit SHA observed at sweep time.
            remote_committed_at: Committed-at of the observed commit.
            remote_blob_sha: Blob SHA of the file at sweep time.
            refresh_reason: Stable RAR-2.2 ``RefreshReason`` code for the enqueue.

        Returns:
            The inserted job row as a dict, or ``None`` when an active job already
            existed for the lineage (idempotent no-op).
        """
        import json

        if isinstance(options_json, str):
            options_text = options_json if options_json.strip() else "{}"
        else:
            options_text = json.dumps(options_json or {})

        q = """
            INSERT INTO apiome.tenant_repository_refresh_jobs (
                tenant_id, repository_id, import_spec_id, branch, path,
                project_id, source_kind, format_override, content_type,
                options_json, spec_schema_version, created_by,
                remote_commit_sha, remote_committed_at, remote_blob_sha, refresh_reason
            )
            VALUES (
                %s::uuid, %s::uuid, %s::uuid, %s, %s,
                %s::uuid, %s, %s, %s,
                %s::jsonb, %s, %s::uuid,
                %s, %s::timestamptz, %s, %s
            )
            ON CONFLICT (repository_id, branch, path)
                WHERE status IN ('queued', 'running')
            DO NOTHING
            RETURNING id, tenant_id, repository_id, import_spec_id, branch, path,
                      project_id, source_kind, format_override, content_type,
                      options_json, spec_schema_version, created_by,
                      remote_commit_sha, remote_committed_at, remote_blob_sha,
                      refresh_reason, status, created_at
        """
        params = (
            tenant_id, repository_id,
            (str(import_spec_id) if import_spec_id else None),
            branch, path,
            (str(project_id) if project_id else None),
            source_kind, format_override, content_type,
            options_text, spec_schema_version,
            (str(created_by) if created_by else None),
            remote_commit_sha, remote_committed_at, remote_blob_sha, refresh_reason,
        )
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, params)
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def list_tenant_repository_file_branches(self, tenant_id: str, repository_id: str) -> List[str]:
        """Distinct branch names that have indexed file rows for this repository."""
        q = """
            SELECT DISTINCT f.branch
            FROM apiome.tenant_repository_files f
            INNER JOIN apiome.tenant_repositories r ON r.id = f.repository_id
            WHERE r.tenant_id = %s::uuid AND r.id = %s::uuid AND r.deleted_at IS NULL
            ORDER BY f.branch ASC
        """
        rows = self.execute_query(q, (tenant_id, repository_id))
        return [str(r["branch"]) for r in rows if r.get("branch")]

    def get_tenant_repository_file_row(
        self, tenant_id: str, repository_id: str, file_id: str
    ) -> Optional[Dict[str, Any]]:
        """One indexed file joined to its repository row (tenant-scoped)."""
        q = """
            SELECT f.id, f.repository_id, f.branch, f.path, f.name, f.ext, f.size_bytes, f.blob_sha,
                   f.detected_kind,
                   r.provider, r.clone_url, r.repository_full_name, r.linked_account_id, r.created_by,
                   r.visibility
            FROM apiome.tenant_repository_files f
            INNER JOIN apiome.tenant_repositories r ON r.id = f.repository_id
            WHERE f.id = %s::uuid AND r.tenant_id = %s::uuid AND r.id = %s::uuid AND r.deleted_at IS NULL
            LIMIT 1
        """
        rows = self.execute_query(q, (file_id, tenant_id, repository_id))
        return dict(rows[0]) if rows else None

    def tenant_repository_files_stats_and_page(
        self,
        tenant_id: str,
        repository_id: str,
        branch: str,
        *,
        path_regex: Optional[str],
        like_patterns: Optional[List[str]],
        hide_non_importable: bool,
        skip_vendor: bool,
        include_hidden: bool,
        path_prefix: Optional[str],
        limit: int,
        offset: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Return indexed totals for the branch, filtered counts, and one page of file rows.
        ``like_patterns`` entries are passed to ``path ILIKE ... ESCAPE '\\'`` (OR together).
        If ``path_regex`` is set, it replaces all LIKE path matching (POSIX ``~*``).
        """
        if not self.get_tenant_repository(tenant_id, repository_id):
            return None

        importable_sql = """(
          f.detected_kind IS NOT NULL AND (
            f.detected_kind ILIKE 'openapi%%' OR f.detected_kind ILIKE 'arazzo%%' OR
            f.detected_kind ILIKE 'asyncapi%%' OR f.detected_kind ILIKE 'graphql%%' OR
            f.detected_kind ILIKE 'protobuf%%' OR f.detected_kind ILIKE 'postman%%' OR
            f.detected_kind ILIKE 'prisma%%' OR f.detected_kind ILIKE 'sql-ddl%%' OR
            f.detected_kind ILIKE 'avro%%' OR f.detected_kind ILIKE 'dbml%%'
          )
        )"""

        from_sql = """
            FROM apiome.tenant_repository_files f
            INNER JOIN apiome.tenant_repositories r ON r.id = f.repository_id
            WHERE """

        base_parts = [
            "r.tenant_id = %s::uuid",
            "r.id = %s::uuid",
            "r.deleted_at IS NULL",
            "f.repository_id = r.id",
            "f.branch = %s",
        ]
        base_params: List[Any] = [tenant_id, repository_id, branch]

        extra_parts: List[str] = []
        extra_params: List[Any] = []
        if path_prefix:
            pp = path_prefix.strip().strip("/")
            if pp:
                extra_parts.append("(f.path = %s OR f.path LIKE %s)")
                extra_params.extend([pp, pp + "/%"])
        if skip_vendor:
            extra_parts.append(
                """(
          f.path NOT ILIKE '%%/node_modules/%%' AND f.path NOT ILIKE 'node_modules/%%' AND
          f.path NOT ILIKE '%%/vendor/%%' AND f.path NOT ILIKE 'vendor/%%' AND
          f.path NOT ILIKE '%%/.git/%%' AND f.path NOT ILIKE '.git/%%'
        )"""
            )
        if not include_hidden:
            extra_parts.append("f.path !~ '(^|/)\\.[^/]+(/|$)'")

        path_parts: List[str] = []
        path_params: List[Any] = []
        rx = (path_regex or "").strip()
        if rx:
            path_parts.append("f.path ~* %s")
            path_params.append(rx)
        else:
            pats = [p for p in (like_patterns or []) if p and str(p).strip()]
            if pats:
                ors = " OR ".join(["f.path ILIKE %s ESCAPE E'\\\\'"] * len(pats))
                path_parts.append("(" + ors + ")")
                path_params.extend(pats)

        idx_parts = base_parts + extra_parts
        idx_params = base_params + extra_params
        q_indexed = "SELECT COUNT(*) AS c " + from_sql + " AND ".join(idx_parts)
        indexed_rows = self.execute_query(q_indexed, tuple(idx_params))
        indexed_total = int(indexed_rows[0]["c"]) if indexed_rows else 0

        filt_parts = base_parts + extra_parts + path_parts
        filt_params = base_params + extra_params + path_params
        if hide_non_importable:
            filt_parts.append(importable_sql)

        where_f = " AND ".join(filt_parts)
        q_match = (
            "SELECT COUNT(*) AS c, COUNT(*) FILTER (WHERE "
            + importable_sql
            + ") AS ic "
            + from_sql
            + where_f
        )
        match_rows = self.execute_query(q_match, tuple(filt_params))
        match_count = int(match_rows[0]["c"]) if match_rows else 0
        importable_match = int(match_rows[0]["ic"]) if match_rows else 0

        lim = max(1, min(int(limit), 500))
        off = max(0, min(int(offset), 500_000))
        q_page = (
            "SELECT f.id, f.path, f.name, f.ext, f.size_bytes, f.blob_sha, f.detected_kind "
            + from_sql
            + where_f
            + " ORDER BY f.path ASC LIMIT %s OFFSET %s"
        )
        page_params = tuple(filt_params + [lim, off])
        rows = self.execute_query(q_page, page_params)

        return {
            "indexed_total": indexed_total,
            "match_count": match_count,
            "importable_match_count": importable_match,
            "limit": lim,
            "offset": off,
            "rows": rows,
        }

    def insert_tenant_repository(
        self,
        tenant_id: str,
        source: str,
        provider: str,
        clone_url: str,
        clone_url_normalized: str,
        repository_full_name: Optional[str],
        description: Optional[str],
        default_branch: str,
        visibility: Optional[str],
        status: str,
        created_by: Optional[str],
        linked_account_id: Optional[str] = None,
        branch_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        q = """
            INSERT INTO apiome.tenant_repositories (
                tenant_id, source, provider, clone_url, clone_url_normalized,
                repository_full_name, description, default_branch, visibility, status, created_by,
                linked_account_id, branch_count
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s::uuid, %s
            )
            RETURNING id, tenant_id, source, provider, clone_url, repository_full_name,
                      description, default_branch, visibility, status, created_at, updated_at,
                      linked_account_id, last_scanned_at, total_files, importable_count, branch_count
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    q,
                    (
                        tenant_id,
                        source,
                        provider,
                        clone_url,
                        clone_url_normalized,
                        repository_full_name,
                        description,
                        default_branch,
                        visibility,
                        status,
                        created_by if created_by else None,
                        linked_account_id if linked_account_id else None,
                        branch_count,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except Exception as e:
            conn.rollback()
            raise e

    def enqueue_repository_file_scan_job(self, tenant_id: str, repository_id: str, branch: str) -> str:
        q = """
            INSERT INTO apiome.tenant_repository_file_scan_jobs (tenant_id, repository_id, branch, status)
            VALUES (%s::uuid, %s::uuid, %s, 'queued')
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (tenant_id, repository_id, branch))
                row = cursor.fetchone()
                conn.commit()
                return str(row["id"]) if row else ""
        except Exception as e:
            conn.rollback()
            raise e

    def claim_next_repository_file_scan_job(self) -> Optional[Dict[str, Any]]:
        q = """
            UPDATE apiome.tenant_repository_file_scan_jobs j
            SET status = 'running', started_at = CURRENT_TIMESTAMP
            FROM (
                SELECT id FROM apiome.tenant_repository_file_scan_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            ) AS sub
            WHERE j.id = sub.id
            RETURNING j.id, j.tenant_id, j.repository_id, j.branch, j.status
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q)
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def replace_tenant_repository_files(
        self, repository_id: str, branch: str, files: List[Dict[str, Any]]
    ) -> None:
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM apiome.tenant_repository_files
                    WHERE repository_id = %s::uuid AND branch = %s
                    """,
                    (repository_id, branch),
                )
                if files:
                    cursor.executemany(
                        """
                        INSERT INTO apiome.tenant_repository_files (
                            repository_id, branch, path, name, ext, size_bytes, blob_sha,
                            detected_kind, commit_sha, committed_at
                        ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
                        """,
                        [
                            (
                                repository_id,
                                branch,
                                f["path"],
                                f["name"],
                                f.get("ext"),
                                f.get("size_bytes"),
                                f.get("blob_sha"),
                                f.get("detected_kind"),
                                f.get("commit_sha"),
                                f.get("committed_at"),
                            )
                            for f in files
                        ],
                    )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def update_tenant_repository_after_file_scan(
        self,
        tenant_id: str,
        repository_id: str,
        total_files: int,
        importable_count: int,
        status: str,
        touch_last_scanned_at: bool,
    ) -> None:
        if touch_last_scanned_at:
            q = """
                UPDATE apiome.tenant_repositories
                SET total_files = %s,
                    importable_count = %s,
                    status = %s,
                    last_scanned_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            """
            params = (total_files, importable_count, status, repository_id, tenant_id)
        else:
            q = """
                UPDATE apiome.tenant_repositories
                SET total_files = %s,
                    importable_count = %s,
                    status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            """
            params = (total_files, importable_count, status, repository_id, tenant_id)
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, params)
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def mark_repository_file_scan_job_succeeded(self, job_id: str) -> None:
        q = """
            UPDATE apiome.tenant_repository_file_scan_jobs
            SET status = 'succeeded', finished_at = CURRENT_TIMESTAMP, error_message = NULL
            WHERE id = %s::uuid
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (job_id,))
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def mark_repository_file_scan_job_failed(self, job_id: str, error_message: str) -> None:
        q = """
            UPDATE apiome.tenant_repository_file_scan_jobs
            SET status = 'failed', finished_at = CURRENT_TIMESTAMP, error_message = %s
            WHERE id = %s::uuid
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (error_message[:8000], job_id))
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def delete_tenant_repository(self, tenant_id: str, repository_id: str) -> bool:
        """Soft-delete a tenant repository (sets ``deleted_at``). Returns True if a row was updated."""
        q = """
            UPDATE apiome.tenant_repositories
            SET deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (repository_id, tenant_id))
                row = cursor.fetchone()
                conn.commit()
                return bool(row)
        except Exception as e:
            conn.rollback()
            raise e

    # -----------------------------------------------------------------------
    # MCP Catalog — endpoint registration & management (MCAT-3.1, #3663)
    # -----------------------------------------------------------------------

    # The columns returned to the API for every endpoint read/write. Kept as one
    # constant so list/get/insert/update all project the same shape.
    _MCP_ENDPOINT_COLUMNS = (
        "id, tenant_id, name, slug, endpoint_url, transport, description, category, "
        "visibility, published, enabled, discovery_cadence_seconds, last_discovered_at, "
        "last_discovery_status, consecutive_failures, next_discovery_after, quarantined_at, "
        "quarantine_reason, current_version_id, created_at, updated_at"
    )

    def list_mcp_endpoints(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List a tenant's live catalog endpoints, newest first (MCAT-3.1)."""
        q = f"""
            SELECT {self._MCP_ENDPOINT_COLUMNS}
            FROM apiome.mcp_endpoints
            WHERE tenant_id = %s::uuid AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        return self.execute_query(q, (tenant_id,))

    def browse_mcp_endpoints(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List a tenant's live endpoints enriched for the private browse view (MCAT-9.1).

        Each row is a catalog endpoint joined to its *current* version snapshot's quality
        ``score`` / ``grade`` (from ``mcp_version_scores``, NULL until the snapshot is scored)
        and its per-kind capability tallies (tools, resources, resource templates, prompts)
        from ``mcp_capability_items`` — exactly what a browse card renders next to the host.
        An endpoint with no current version (never successfully discovered) still appears,
        with zero counts and a NULL score, so the catalog is shown in full. Ordered by name so
        the per-host grouping the route performs lists endpoints predictably.

        Args:
            tenant_id: The caller's token tenant; the sole scoping predicate, so an endpoint
                never leaks across tenants.

        Returns:
            One dict per live endpoint with its score/grade and capability counts.
        """
        q = """
            SELECT e.id, e.tenant_id, e.name, e.slug, e.endpoint_url, e.transport,
                   e.description, e.category, e.visibility, e.published, e.enabled,
                   e.last_discovered_at, e.last_discovery_status, e.quarantined_at,
                   e.current_version_id,
                   s.score, s.grade, s.scored_at,
                   COUNT(ci.id) FILTER (WHERE ci.item_type = 'tool')              AS tool_count,
                   COUNT(ci.id) FILTER (WHERE ci.item_type = 'resource')          AS resource_count,
                   COUNT(ci.id) FILTER (WHERE ci.item_type = 'resource_template') AS resource_template_count,
                   COUNT(ci.id) FILTER (WHERE ci.item_type = 'prompt')            AS prompt_count
            FROM apiome.mcp_endpoints e
            LEFT JOIN apiome.mcp_version_scores s ON s.version_id = e.current_version_id
            LEFT JOIN apiome.mcp_capability_items ci ON ci.version_id = e.current_version_id
            WHERE e.tenant_id = %s::uuid AND e.deleted_at IS NULL
            GROUP BY e.id, s.score, s.grade, s.scored_at
            ORDER BY e.name ASC
        """
        return self.execute_query(q, (tenant_id,))

    # -----------------------------------------------------------------------
    # MCP Catalog — capability search index & query (MCAT-9.2, #3692)
    # -----------------------------------------------------------------------

    #: tsvector expression that matches the V127 expression GIN index
    #: (``idx_mcp_capability_items_fts``) verbatim, so the capability search is index-usable.
    _MCP_CAPABILITY_FTS_EXPR = (
        "to_tsvector('english', coalesce(ci.name, '') || ' ' || coalesce(ci.description, ''))"
    )

    #: tsvector expression for endpoint-level search (name + description + category). There is no
    #: supporting index — ``mcp_endpoints`` is a small per-tenant table, so a seq scan is cheap and a
    #: dedicated GIN index would only add write/import cost for no real read benefit.
    _MCP_ENDPOINT_FTS_EXPR = (
        "to_tsvector('english', coalesce(e.name, '') || ' ' || coalesce(e.description, '') "
        "|| ' ' || coalesce(e.category, ''))"
    )

    #: Extract the host from a stored endpoint URL in SQL (mirrors ``urlsplit().hostname``): the
    #: authority between ``://`` (after optional ``user:pass@`` userinfo) up to the first ``:`` /
    #: ``/`` / ``?`` / ``#``. NULL for hostless targets (e.g. stdio commands), which a host filter
    #: then excludes — those are the ``(local)`` bucket in browse and have no host to match on.
    _MCP_ENDPOINT_HOST_EXPR = "substring(e.endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)')"

    def _mcp_search_filter_clauses(
        self,
        *,
        host: Optional[str],
        category: Optional[str],
        grade: Optional[str],
        visibility: Optional[str],
    ) -> Tuple[List[str], List[Any]]:
        """Build the composable WHERE clauses shared by both catalog-search queries (MCAT-9.2).

        Each filter is optional and they compose (every supplied filter is ANDed in). Returns a
        ``(clauses, params)`` pair the caller splices into its query; the clauses reference the
        ``e`` (endpoint) and ``s`` (version score) aliases both search queries expose. Host and
        category match case-insensitively; grade matches case-insensitively against the current
        snapshot's letter grade; visibility matches the endpoint's ``visibility`` exactly.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if host:
            clauses.append(f"lower({self._MCP_ENDPOINT_HOST_EXPR}) = lower(%s)")
            params.append(host)
        if category:
            clauses.append("lower(e.category) = lower(%s)")
            params.append(category)
        if grade:
            clauses.append("upper(s.grade) = upper(%s)")
            params.append(grade)
        if visibility:
            clauses.append("e.visibility = %s")
            params.append(visibility)
        return clauses, params

    def search_mcp_capability_items(
        self,
        tenant_id: str,
        query: str,
        *,
        item_type: Optional[str] = None,
        host: Optional[str] = None,
        category: Optional[str] = None,
        grade: Optional[str] = None,
        visibility: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Full-text search a tenant's *current* capability surface, relevance-then-score ranked (MCAT-9.2).

        Matches ``query`` (parsed with ``websearch_to_tsquery`` — quotes, ``OR``, and ``-`` are
        honoured, malformed syntax never errors) against the ``name + description`` tsvector of every
        capability item that belongs to an endpoint's *current* version snapshot
        (``e.current_version_id = ci.version_id``), so only live surfaces are searched — never
        superseded history. Joining through ``mcp_endpoints`` and scoping by ``tenant_id`` is what
        keeps the search inside the caller's own catalog. The ``@@`` predicate uses the same
        expression as the V127 GIN index, so the index does the matching.

        Args:
            tenant_id: The caller's token tenant; the sole cross-tenant scoping predicate.
            query: The free-text query (already stripped non-empty by the caller).
            item_type: Restrict to one capability kind (``tool`` / ``resource`` /
                ``resource_template`` / ``prompt``); ``None`` searches all four.
            host: Restrict to endpoints on this host (case-insensitive).
            category: Restrict to endpoints in this category (case-insensitive).
            grade: Restrict to endpoints whose current snapshot earned this A-F grade.
            visibility: Restrict to ``private`` or ``public`` endpoints within the tenant.
            limit: Maximum rows to return.
            offset: Rows to skip (pagination).

        Returns:
            One row per matching capability item — the item plus its owning endpoint's browse
            context and a ``relevance`` rank — ordered by relevance desc, then score desc, then
            endpoint name and item ordinal for a stable tie-break.
        """
        fts = self._MCP_CAPABILITY_FTS_EXPR
        clauses, fparams = self._mcp_search_filter_clauses(
            host=host, category=category, grade=grade, visibility=visibility
        )
        if item_type:
            clauses.append("ci.item_type = %s")
            fparams.append(item_type)
        where_extra = ("\n              AND " + "\n              AND ".join(clauses)) if clauses else ""
        q = f"""
            SELECT ci.item_type AS kind,
                   ci.id AS item_id, ci.name AS item_name, ci.title AS item_title,
                   ci.description AS description,
                   e.id AS endpoint_id, e.name AS endpoint_name, e.slug AS endpoint_slug,
                   e.endpoint_url, e.category, e.visibility, e.current_version_id,
                   e.last_discovered_at, s.score, s.grade,
                   ts_rank({fts}, websearch_to_tsquery('english', %s)) AS relevance
            FROM apiome.mcp_capability_items ci
            JOIN apiome.mcp_endpoints e ON e.current_version_id = ci.version_id
            LEFT JOIN apiome.mcp_version_scores s ON s.version_id = e.current_version_id
            WHERE e.tenant_id = %s::uuid
              AND e.deleted_at IS NULL
              AND {fts} @@ websearch_to_tsquery('english', %s){where_extra}
            ORDER BY relevance DESC, s.score DESC NULLS LAST, e.name ASC, ci.ordinal ASC
            LIMIT %s OFFSET %s
        """
        params = (query, tenant_id, query, *fparams, int(limit), int(offset))
        return self.execute_query(q, params)

    def search_mcp_endpoints_fts(
        self,
        tenant_id: str,
        query: str,
        *,
        host: Optional[str] = None,
        category: Optional[str] = None,
        grade: Optional[str] = None,
        visibility: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Full-text search a tenant's endpoints by name/description/category (MCAT-9.2, ``scope=endpoint``).

        The endpoint-level half of catalog search: matches ``query`` against each endpoint's
        ``name + description + category`` tsvector rather than its capability items, so "find the MCP
        server" queries surface the server itself. Same tenant scoping, same composable
        host/category/grade/visibility filters, and the same relevance-then-score ordering as the
        capability search; rows are shaped identically (``kind = 'endpoint'`` with the ``item_*``
        columns NULL) so one projection serves both.

        Args:
            tenant_id: The caller's token tenant; the sole cross-tenant scoping predicate.
            query: The free-text query (already stripped non-empty by the caller).
            host: Restrict to endpoints on this host (case-insensitive).
            category: Restrict to endpoints in this category (case-insensitive).
            grade: Restrict to endpoints whose current snapshot earned this A-F grade.
            visibility: Restrict to ``private`` or ``public`` endpoints within the tenant.
            limit: Maximum rows to return.
            offset: Rows to skip (pagination).

        Returns:
            One row per matching endpoint — its browse context and a ``relevance`` rank — ordered by
            relevance desc, then score desc, then name for a stable tie-break.
        """
        fts = self._MCP_ENDPOINT_FTS_EXPR
        clauses, fparams = self._mcp_search_filter_clauses(
            host=host, category=category, grade=grade, visibility=visibility
        )
        where_extra = ("\n              AND " + "\n              AND ".join(clauses)) if clauses else ""
        q = f"""
            SELECT 'endpoint' AS kind,
                   NULL::uuid AS item_id, NULL::text AS item_name, NULL::text AS item_title,
                   e.description AS description,
                   e.id AS endpoint_id, e.name AS endpoint_name, e.slug AS endpoint_slug,
                   e.endpoint_url, e.category, e.visibility, e.current_version_id,
                   e.last_discovered_at, s.score, s.grade,
                   ts_rank({fts}, websearch_to_tsquery('english', %s)) AS relevance
            FROM apiome.mcp_endpoints e
            LEFT JOIN apiome.mcp_version_scores s ON s.version_id = e.current_version_id
            WHERE e.tenant_id = %s::uuid
              AND e.deleted_at IS NULL
              AND {fts} @@ websearch_to_tsquery('english', %s){where_extra}
            ORDER BY relevance DESC, s.score DESC NULLS LAST, e.name ASC
            LIMIT %s OFFSET %s
        """
        params = (query, tenant_id, query, *fparams, int(limit), int(offset))
        return self.execute_query(q, params)

    def get_mcp_endpoint(self, tenant_id: str, endpoint_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one live catalog endpoint scoped to ``tenant_id`` (MCAT-3.1).

        Scoping by ``tenant_id`` is what makes a cross-tenant id read as "not
        found" (the route turns ``None`` into a 404), so an endpoint never leaks
        to another tenant.
        """
        q = f"""
            SELECT {self._MCP_ENDPOINT_COLUMNS}
            FROM apiome.mcp_endpoints
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            LIMIT 1
        """
        rows = self.execute_query(q, (endpoint_id, tenant_id))
        return dict(rows[0]) if rows else None

    def list_due_mcp_endpoints(
        self,
        *,
        default_cadence_seconds: int,
    ) -> List[Dict[str, Any]]:
        """Return endpoints due for a periodic re-discovery sweep tick (MCAT-5.1, #3673).

        An endpoint is *due* when it is live (``deleted_at IS NULL``), turned on
        (``enabled = TRUE``), and either has never been discovered
        (``last_discovered_at IS NULL``) or at least its effective cadence has
        elapsed since the last attempt. The effective cadence is the per-endpoint
        ``discovery_cadence_seconds`` when set, otherwise the global
        ``default_cadence_seconds`` — this is the "global default + per-endpoint
        override" model from the ticket. The recency comparison is evaluated in the
        database against ``now()`` so it never depends on application clock skew.

        Disabled and soft-deleted endpoints are excluded here, so the sweep
        (:func:`mcp_discovery_sweep.process_mcp_discovery_sweep`) never has to
        re-check them. Ordering is oldest-first (NULLs — never discovered — first)
        so attention is spread fairly and a brand-new endpoint is picked up promptly.

        Failure handling (MCAT-5.3, #3675) adds two more carve-outs so a flaky/dead
        endpoint cannot wedge the sweep or spam failures: a **quarantined** endpoint
        (``quarantined_at IS NOT NULL`` — it tripped the consecutive-failure threshold)
        is excluded entirely until it recovers or an operator clears it, and an endpoint
        still inside its **backoff window** (``next_discovery_after`` in the future) is
        skipped even when its cadence has otherwise elapsed. Both are reset on the next
        successful contact, so a recovered endpoint rejoins the sweep automatically.

        Note: unlike the V126 column comment's original "null means no automatic
        discovery", a null ``discovery_cadence_seconds`` now means "use the global
        default cadence". The real on/off switch is the ``enabled`` column, so an
        operator opts an endpoint out of the sweep by disabling it, not by clearing
        its cadence.

        Args:
            default_cadence_seconds: Global fallback cadence (seconds) applied to
                endpoints with no explicit ``discovery_cadence_seconds``.

        Returns:
            Endpoint rows due for re-discovery, oldest ``last_discovered_at`` first
            (never-discovered endpoints first) for fair scheduling.
        """
        cadence = int(default_cadence_seconds)
        if cadence < 1:
            cadence = 1
        q = f"""
            SELECT {self._MCP_ENDPOINT_COLUMNS}
            FROM apiome.mcp_endpoints
            WHERE deleted_at IS NULL
              AND enabled = TRUE
              AND quarantined_at IS NULL
              AND (next_discovery_after IS NULL OR next_discovery_after <= now())
              AND (
                last_discovered_at IS NULL
                OR last_discovered_at <= now() - make_interval(
                     secs => COALESCE(discovery_cadence_seconds, %s)
                   )
              )
            ORDER BY last_discovered_at ASC NULLS FIRST, created_at ASC
        """
        return self.execute_query(q, (cadence,))

    def _next_available_mcp_slug(self, cursor, tenant_id: str, base_slug: str) -> str:
        """Pick a tenant-unique slug derived from ``base_slug``.

        Returns ``base_slug`` when free, otherwise the first free ``base_slug-N``
        (N starting at 2). Collision detection considers *all* rows for the tenant
        — including soft-deleted ones — because the ``(tenant_id, slug)`` unique
        constraint (V126) counts deleted rows too, so reusing a deleted endpoint's
        slug would still violate it. Runs on the caller's cursor inside the insert
        transaction so the check and the insert see a consistent snapshot.
        """
        cursor.execute(
            """
            SELECT slug FROM apiome.mcp_endpoints
            WHERE tenant_id = %s::uuid AND (slug = %s OR slug LIKE %s)
            """,
            (tenant_id, base_slug, f"{base_slug}-%"),
        )
        taken = {str(r["slug"]) for r in cursor.fetchall()}
        if base_slug not in taken:
            return base_slug
        suffix = 2
        while f"{base_slug}-{suffix}" in taken:
            suffix += 1
        return f"{base_slug}-{suffix}"

    def insert_mcp_endpoint(
        self,
        *,
        tenant_id: str,
        creator_id: str,
        name: str,
        base_slug: str,
        endpoint_url: str,
        transport: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        visibility: str = "private",
        discovery_cadence_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert a catalog endpoint, resolving a tenant-unique slug (MCAT-3.1).

        Args:
            tenant_id: Owning tenant.
            creator_id: User registering the endpoint (``creator_id`` is NOT NULL).
            name: Friendly display name.
            base_slug: Already-slugified candidate; uniquified per tenant here.
            endpoint_url: The MCP server URL (or stdio command target).
            transport: One of ``streamable_http`` / ``sse`` / ``stdio``.
            description: Optional free-text description.
            category: Optional catalog category.
            visibility: ``private`` (default) or ``public``.
            discovery_cadence_seconds: Optional positive re-discovery cadence.

        Returns:
            The inserted row projected onto :attr:`_MCP_ENDPOINT_COLUMNS`.
        """
        q = f"""
            INSERT INTO apiome.mcp_endpoints (
                tenant_id, creator_id, name, slug, endpoint_url, transport,
                description, category, visibility, discovery_cadence_seconds
            ) VALUES (
                %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING {self._MCP_ENDPOINT_COLUMNS}
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                slug = self._next_available_mcp_slug(cursor, tenant_id, base_slug)
                cursor.execute(
                    q,
                    (
                        tenant_id,
                        creator_id,
                        name,
                        slug,
                        endpoint_url,
                        transport,
                        description,
                        category,
                        visibility,
                        discovery_cadence_seconds,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except Exception as e:
            conn.rollback()
            raise e

    # Columns a PATCH may update, mapped to whether they need a cast in SQL.
    _MCP_ENDPOINT_UPDATABLE = (
        "name",
        "endpoint_url",
        "transport",
        "description",
        "category",
        "visibility",
        "published",
        "enabled",
        "discovery_cadence_seconds",
    )

    def update_mcp_endpoint(
        self,
        tenant_id: str,
        endpoint_id: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Apply a partial update to a live catalog endpoint (MCAT-3.1).

        Only the keys present in ``fields`` (restricted to
        :attr:`_MCP_ENDPOINT_UPDATABLE`) are written; ``updated_at`` is always
        bumped. The update is scoped to ``tenant_id`` so a cross-tenant id matches
        no row.

        Args:
            tenant_id: Owning tenant (scopes the update for isolation).
            endpoint_id: The endpoint to patch.
            fields: Column → value map of changes to apply.

        Returns:
            The updated row, or ``None`` when no live endpoint matched the tenant
            + id (the route maps this to a 404). When ``fields`` is empty the row
            is returned unchanged.
        """
        updates = {k: v for k, v in fields.items() if k in self._MCP_ENDPOINT_UPDATABLE}
        if not updates:
            return self.get_mcp_endpoint(tenant_id, endpoint_id)

        set_clauses = [f"{col} = %s" for col in updates]
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params: List[Any] = list(updates.values())
        params.extend([endpoint_id, tenant_id])

        q = f"""
            UPDATE apiome.mcp_endpoints
            SET {", ".join(set_clauses)}
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING {self._MCP_ENDPOINT_COLUMNS}
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, tuple(params))
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def soft_delete_mcp_endpoint(
        self,
        tenant_id: str,
        endpoint_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retire a catalog endpoint and purge its child data (MCAT-3.5, #3667).

        The endpoint row is *soft* deleted — stamped with ``deleted_at`` (and
        flipped to ``enabled = false`` with ``current_version_id`` cleared) so it
        drops out of browse/list/get and is skipped by the discovery sweep, while
        its slug stays reserved against the ``(tenant_id, slug)`` unique
        constraint. Its children, by contrast, are *hard* deleted so no stale or
        sensitive data survives the endpoint: the credential vault row (the
        security-critical purge), all discovery jobs, and all version snapshots —
        which cascade-reap their capability items, change logs and scores via the
        ``ON DELETE CASCADE`` chain off ``mcp_endpoint_versions`` (V128/V130).

        Everything runs in one transaction scoped to ``tenant_id``: a cross-tenant
        or already-deleted id matches no live row, so nothing is touched and
        ``None`` is returned (the route maps that to a 404).

        Args:
            tenant_id: Owning tenant (scopes the delete for isolation).
            endpoint_id: The endpoint to retire.

        Returns:
            A teardown summary — ``{"endpoint_id", "credentials_purged",
            "versions_deleted", "jobs_deleted"}`` — or ``None`` when no live
            endpoint matched the tenant + id.
        """
        # Retire the endpoint first; the WHERE clause is the existence/ownership
        # guard, so a no-match short-circuits before any child rows are touched.
        retire = """
            UPDATE apiome.mcp_endpoints
            SET deleted_at = CURRENT_TIMESTAMP,
                enabled = false,
                current_version_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING id
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(retire, (endpoint_id, tenant_id))
                if cursor.fetchone() is None:
                    conn.rollback()
                    return None

                cursor.execute(
                    "DELETE FROM apiome.mcp_endpoint_credentials WHERE endpoint_id = %s::uuid",
                    (endpoint_id,),
                )
                credentials_purged = (cursor.rowcount or 0) > 0

                cursor.execute(
                    "DELETE FROM apiome.mcp_discovery_jobs WHERE endpoint_id = %s::uuid",
                    (endpoint_id,),
                )
                jobs_deleted = cursor.rowcount or 0

                # Versions cascade-reap capability items, version changes and
                # scores (V128/V130), so this single delete clears the snapshot tree.
                cursor.execute(
                    "DELETE FROM apiome.mcp_endpoint_versions WHERE endpoint_id = %s::uuid",
                    (endpoint_id,),
                )
                versions_deleted = cursor.rowcount or 0

                conn.commit()
                return {
                    "endpoint_id": endpoint_id,
                    "credentials_purged": credentials_purged,
                    "versions_deleted": versions_deleted,
                    "jobs_deleted": jobs_deleted,
                }
        except Exception as e:
            conn.rollback()
            raise e

    # -----------------------------------------------------------------------
    # MCP Catalog — discovery jobs & version persistence (MCAT-3.2, #3664)
    # -----------------------------------------------------------------------

    # Columns returned for every discovery-job read/write. Kept as one constant so
    # enqueue/get/list/transition all project the same shape.
    _MCP_DISCOVERY_JOB_COLUMNS = (
        "id, endpoint_id, tenant_id, state, trigger, started_at, finished_at, "
        "error, result, created_at"
    )

    # A discovery job is "active" (and therefore a de-duplication target) while it is
    # still queued or running; completed/failed jobs never coalesce a new request.
    _MCP_DISCOVERY_ACTIVE_STATES = ("queued", "running")

    def enqueue_mcp_discovery_job(
        self,
        endpoint_id: str,
        tenant_id: str,
        trigger: str = "manual",
    ) -> Dict[str, Any]:
        """Create a queued discovery job for an endpoint, de-duplicating concurrent runs.

        A transaction-scoped Postgres advisory lock keyed on the endpoint serializes
        concurrent callers so the "is one already active?" check and the insert see a
        consistent snapshot: if a queued/running job already exists for the endpoint the
        existing row is returned instead of inserting a second one. The lock is released
        automatically when the transaction commits.

        Args:
            endpoint_id: The endpoint to discover (assumed already tenant-validated).
            tenant_id: Owning tenant, stamped on the job for scoped reads.
            trigger: How the run was initiated — one of ``manual`` / ``sweep`` /
                ``registry`` (this REST path always passes ``manual``).

        Returns:
            ``{"job": <row>, "deduplicated": bool}`` — ``deduplicated`` is ``True`` when an
            already-active job was returned rather than a new one being created.
        """
        select_active = f"""
            SELECT {self._MCP_DISCOVERY_JOB_COLUMNS}
            FROM apiome.mcp_discovery_jobs
            WHERE endpoint_id = %s::uuid AND state = ANY(%s)
            ORDER BY created_at ASC
            LIMIT 1
        """
        insert_job = f"""
            INSERT INTO apiome.mcp_discovery_jobs (endpoint_id, tenant_id, trigger)
            VALUES (%s::uuid, %s::uuid, %s)
            RETURNING {self._MCP_DISCOVERY_JOB_COLUMNS}
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                # Serialize per endpoint so the dedupe check below cannot race a
                # concurrent insert. hashtext() maps the id to the int the advisory
                # lock expects; the lock is held until commit.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", (str(endpoint_id),)
                )
                cursor.execute(
                    select_active,
                    (endpoint_id, list(self._MCP_DISCOVERY_ACTIVE_STATES)),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    conn.commit()
                    return {"job": dict(existing), "deduplicated": True}
                cursor.execute(insert_job, (endpoint_id, tenant_id, trigger))
                row = cursor.fetchone()
                conn.commit()
                return {"job": dict(row), "deduplicated": False}
        except Exception as e:
            conn.rollback()
            raise e

    def get_mcp_discovery_job(
        self, tenant_id: str, job_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch one discovery job scoped to ``tenant_id`` (a cross-tenant id reads as None)."""
        q = f"""
            SELECT {self._MCP_DISCOVERY_JOB_COLUMNS}
            FROM apiome.mcp_discovery_jobs
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (job_id, tenant_id))
        return dict(rows[0]) if rows else None

    def list_mcp_discovery_jobs(
        self, tenant_id: str, endpoint_id: str
    ) -> List[Dict[str, Any]]:
        """List discovery jobs for one endpoint (newest first), scoped to the tenant."""
        q = f"""
            SELECT {self._MCP_DISCOVERY_JOB_COLUMNS}
            FROM apiome.mcp_discovery_jobs
            WHERE endpoint_id = %s::uuid AND tenant_id = %s::uuid
            ORDER BY created_at DESC
        """
        return self.execute_query(q, (endpoint_id, tenant_id))

    def mark_mcp_discovery_job_running(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Transition a queued job to ``running`` and stamp ``started_at``.

        Idempotent in spirit: the WHERE clause only advances a job that is still
        ``queued`` so a double-start is a no-op (returns ``None``).
        """
        q = f"""
            UPDATE apiome.mcp_discovery_jobs
            SET state = 'running', started_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND state = 'queued'
            RETURNING {self._MCP_DISCOVERY_JOB_COLUMNS}
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (job_id,))
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def finish_mcp_discovery_job(
        self,
        job_id: str,
        state: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Move a job to a terminal state (``completed`` / ``failed``).

        Stamps ``finished_at`` and writes the JSONB ``result`` payload (which carries the
        ``version_id`` reference on success) and/or the ``error`` text on failure.
        """
        q = f"""
            UPDATE apiome.mcp_discovery_jobs
            SET state = %s,
                finished_at = CURRENT_TIMESTAMP,
                result = COALESCE(%s, result),
                error = %s
            WHERE id = %s::uuid
            RETURNING {self._MCP_DISCOVERY_JOB_COLUMNS}
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    q,
                    (
                        state,
                        Json(result) if result is not None else None,
                        error,
                        job_id,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            raise e

    def get_latest_mcp_endpoint_version(
        self, endpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the highest-``version_seq`` snapshot for an endpoint, or None if never discovered."""
        q = """
            SELECT id, endpoint_id, version_seq, version_tag, protocol_version,
                   server_name, server_title, server_version, instructions,
                   capabilities, surface_fingerprint, discovered_at, created_at
            FROM apiome.mcp_endpoint_versions
            WHERE endpoint_id = %s::uuid
            ORDER BY version_seq DESC
            LIMIT 1
        """
        rows = self.execute_query(q, (endpoint_id,))
        return dict(rows[0]) if rows else None

    def get_mcp_capability_items(self, version_id: str) -> List[Dict[str, Any]]:
        """Fetch the normalized capability rows of a version snapshot (discovery order)."""
        q = """
            SELECT version_id, item_type, name, title, description, input_schema,
                   output_schema, annotations, uri, uri_template, raw, ordinal
            FROM apiome.mcp_capability_items
            WHERE version_id = %s::uuid
            ORDER BY item_type ASC, ordinal ASC
        """
        return self.execute_query(q, (version_id,))

    # The per-change-type tally a version-history row carries, computed by joining the
    # snapshot to its ``mcp_version_changes`` and counting each direction (plus a total).
    # Defined once so the list and single-version reads stay byte-identical.
    _MCP_VERSION_CHANGE_COUNTS = """
        COUNT(c.id) FILTER (WHERE c.change_type = 'added')    AS added_count,
        COUNT(c.id) FILTER (WHERE c.change_type = 'removed')  AS removed_count,
        COUNT(c.id) FILTER (WHERE c.change_type = 'modified') AS modified_count,
        COUNT(c.id)                                           AS total_count
    """

    def list_mcp_endpoint_versions(self, endpoint_id: str) -> List[Dict[str, Any]]:
        """List an endpoint's version snapshots newest-first, with score and change counts.

        Each row carries the snapshot's identity (``version_seq``, the human-readable
        ``version_tag``, server/protocol identity, ``surface_fingerprint``, timings), its
        quality ``score`` / ``grade`` from ``mcp_version_scores`` (NULL when not yet scored),
        and the per-direction tally of ``mcp_version_changes`` it introduced — exactly the
        fields a "version history" timeline renders. Ordered by ``version_seq`` descending so
        the latest snapshot is first.

        Args:
            endpoint_id: Owning endpoint whose history to read (already tenant-validated by
                the caller).

        Returns:
            One dict per snapshot, newest first; empty when the endpoint was never discovered.
        """
        q = f"""
            SELECT v.id, v.endpoint_id, v.version_seq, v.version_tag, v.protocol_version,
                   v.server_name, v.server_title, v.server_version, v.surface_fingerprint,
                   v.discovered_at, v.created_at,
                   s.score, s.grade, s.scored_at,
                   {self._MCP_VERSION_CHANGE_COUNTS}
            FROM apiome.mcp_endpoint_versions v
            LEFT JOIN apiome.mcp_version_scores s ON s.version_id = v.id
            LEFT JOIN apiome.mcp_version_changes c ON c.version_id = v.id
            WHERE v.endpoint_id = %s::uuid
            GROUP BY v.id, s.score, s.grade, s.scored_at
            ORDER BY v.version_seq DESC
        """
        return self.execute_query(q, (endpoint_id,))

    def get_mcp_endpoint_version(
        self, endpoint_id: str, version_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch one version snapshot scoped to its endpoint, with score and change counts.

        Returns the full surface-identity columns (including ``instructions`` and the
        declared ``capabilities`` blob, which the list view omits) plus the same score and
        change-count aggregates as :meth:`list_mcp_endpoint_versions`. The ``endpoint_id``
        predicate is the scoping guard: a version id belonging to another endpoint (and thus,
        once the caller has tenant-validated the endpoint, another tenant) reads as ``None``.

        Args:
            endpoint_id: Owning endpoint the version must belong to.
            version_id: The snapshot to fetch.

        Returns:
            The snapshot row, or ``None`` when no such version exists under this endpoint.
        """
        q = f"""
            SELECT v.id, v.endpoint_id, v.version_seq, v.version_tag, v.protocol_version,
                   v.server_name, v.server_title, v.server_version, v.instructions,
                   v.capabilities, v.surface_fingerprint, v.discovered_at, v.created_at,
                   s.score, s.grade, s.scored_at,
                   {self._MCP_VERSION_CHANGE_COUNTS}
            FROM apiome.mcp_endpoint_versions v
            LEFT JOIN apiome.mcp_version_scores s ON s.version_id = v.id
            LEFT JOIN apiome.mcp_version_changes c ON c.version_id = v.id
            WHERE v.endpoint_id = %s::uuid AND v.id = %s::uuid
            GROUP BY v.id, s.score, s.grade, s.scored_at
        """
        rows = self.execute_query(q, (endpoint_id, version_id))
        return dict(rows[0]) if rows else None

    def get_mcp_version_changes(self, version_id: str) -> List[Dict[str, Any]]:
        """Fetch the stored ``previous → this`` diff rows for a version, in stable order.

        Returns the ``mcp_version_changes`` rows the snapshot introduced relative to the
        version before it (empty for the first version, which introduces no diff). Ordered to
        match the on-demand compare engine's emission order — server metadata first, then
        tools, resources, resource templates, prompts, each by name — so the persisted change
        report and a live compare of the same pair render identically.

        Args:
            version_id: The snapshot whose change records to read.

        Returns:
            One dict per change row, in stable order; empty when the version recorded no diff.
        """
        q = """
            SELECT version_id, change_type, item_type, item_name, detail, created_at
            FROM apiome.mcp_version_changes
            WHERE version_id = %s::uuid
            ORDER BY
                CASE item_type
                    WHEN 'server' THEN 0
                    WHEN 'tool' THEN 1
                    WHEN 'resource' THEN 2
                    WHEN 'resource_template' THEN 3
                    WHEN 'prompt' THEN 4
                    ELSE 5
                END ASC,
                item_name ASC
        """
        return self.execute_query(q, (version_id,))

    def _next_mcp_version_tag(self, cursor: Any, endpoint_id: str, base_tag: str) -> str:
        """Resolve a per-endpoint-unique date/time tag, disambiguating same-minute collisions.

        The base tag is minute-precision (e.g. ``2026-06-26T14:03Z``), so two material surface
        changes to one endpoint inside a single minute would map to the same label. Mirroring how
        ``version_seq`` is allocated, the second and subsequent collisions get a ``-2``, ``-3``, …
        suffix. Lookups run inside the caller's open transaction; two concurrent persists could
        still both pick the same tag, in which case the ``(endpoint_id, version_tag)`` unique
        constraint (V131) is the backstop that fails the loser loudly.

        Args:
            cursor: An open cursor on the in-progress transaction.
            endpoint_id: Owning endpoint the tag must be unique within.
            base_tag: The minute-precision base label from :func:`format_mcp_version_tag`.

        Returns:
            The first free tag — ``base_tag`` itself, or ``base_tag`` with a ``-N`` suffix.
        """
        candidate = base_tag
        suffix = 1
        while True:
            cursor.execute(
                """
                SELECT 1 FROM apiome.mcp_endpoint_versions
                WHERE endpoint_id = %s::uuid AND version_tag = %s
                LIMIT 1
                """,
                (endpoint_id, candidate),
            )
            if cursor.fetchone() is None:
                return candidate
            suffix += 1
            candidate = f"{base_tag}-{suffix}"

    def record_mcp_discovery_version(
        self,
        endpoint_id: str,
        *,
        version_row: Dict[str, Any],
        capability_rows: List[Dict[str, Any]],
        change_rows: List[Dict[str, Any]],
        discovered_at: Any,
    ) -> Dict[str, Any]:
        """Persist a new version snapshot atomically and point the endpoint at it.

        In one transaction this: assigns the next ``version_seq`` for the endpoint, stamps a
        unique human-readable date/time ``version_tag``, inserts the immutable
        ``mcp_endpoint_versions`` row, its ``mcp_capability_items`` children, and any
        ``mcp_version_changes`` diff rows, then updates the endpoint's ``current_version_id`` /
        ``last_discovered_at`` / ``last_discovery_status``.

        Args:
            endpoint_id: Owning endpoint.
            version_row: Surface columns from :meth:`DiscoverySurface.to_version_row`.
            capability_rows: Rows from :meth:`DiscoverySurface.to_capability_rows`
                (``version_id`` is overwritten here with the freshly assigned id).
            change_rows: Diff rows (``change_type`` / ``item_type`` / ``item_name`` /
                ``detail``) relative to the previous version; empty for a first run.
            discovered_at: When the discovery that produced this snapshot ran; also the source
                of the ``version_tag`` date/time label.

        Returns:
            ``{"version_id": str, "version_seq": int, "version_tag": str}`` for the new snapshot.
        """
        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                # Next monotonic per-endpoint sequence (1 on first run). Computed under
                # the transaction so two concurrent persists cannot collide; the
                # (endpoint_id, version_seq) unique constraint is the final backstop.
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(version_seq), 0) + 1 AS next_seq
                    FROM apiome.mcp_endpoint_versions
                    WHERE endpoint_id = %s::uuid
                    """,
                    (endpoint_id,),
                )
                next_seq = int(cursor.fetchone()["next_seq"])

                # Human-readable, per-endpoint-unique date/time tag for this snapshot (#3671).
                # The base label is minute-precision UTC; collisions within a minute are
                # disambiguated with a -N suffix, backstopped by the unique constraint (V131).
                version_tag = self._next_mcp_version_tag(
                    cursor, endpoint_id, format_mcp_version_tag(discovered_at)
                )

                cursor.execute(
                    """
                    INSERT INTO apiome.mcp_endpoint_versions (
                        endpoint_id, version_seq, version_tag, protocol_version, server_name,
                        server_title, server_version, instructions, capabilities,
                        surface_fingerprint, discovered_at
                    ) VALUES (
                        %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        endpoint_id,
                        next_seq,
                        version_tag,
                        version_row.get("protocol_version"),
                        version_row.get("server_name"),
                        version_row.get("server_title"),
                        version_row.get("server_version"),
                        version_row.get("instructions"),
                        Json(version_row.get("capabilities"))
                        if version_row.get("capabilities") is not None
                        else None,
                        version_row.get("surface_fingerprint"),
                        discovered_at,
                    ),
                )
                version_id = str(cursor.fetchone()["id"])

                for item in capability_rows:
                    cursor.execute(
                        """
                        INSERT INTO apiome.mcp_capability_items (
                            version_id, item_type, name, title, description,
                            input_schema, output_schema, annotations, uri,
                            uri_template, raw, ordinal
                        ) VALUES (
                            %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            version_id,
                            item.get("item_type"),
                            item.get("name"),
                            item.get("title"),
                            item.get("description"),
                            Json(item["input_schema"])
                            if item.get("input_schema") is not None
                            else None,
                            Json(item["output_schema"])
                            if item.get("output_schema") is not None
                            else None,
                            Json(item["annotations"])
                            if item.get("annotations") is not None
                            else None,
                            item.get("uri"),
                            item.get("uri_template"),
                            Json(item.get("raw") if item.get("raw") is not None else {}),
                            item.get("ordinal"),
                        ),
                    )

                for change in change_rows:
                    cursor.execute(
                        """
                        INSERT INTO apiome.mcp_version_changes (
                            version_id, change_type, item_type, item_name, detail
                        ) VALUES (
                            %s::uuid, %s, %s, %s, %s
                        )
                        """,
                        (
                            version_id,
                            change.get("change_type"),
                            change.get("item_type"),
                            change.get("item_name"),
                            Json(change.get("detail") if change.get("detail") is not None else {}),
                        ),
                    )

                # A successful discovery clears any failure backoff/quarantine state (MCAT-5.3):
                # the endpoint is healthy again, so it rejoins the sweep at its normal cadence.
                cursor.execute(
                    """
                    UPDATE apiome.mcp_endpoints
                    SET current_version_id = %s::uuid,
                        last_discovered_at = %s,
                        last_discovery_status = 'changed',
                        consecutive_failures = 0,
                        next_discovery_after = NULL,
                        quarantined_at = NULL,
                        quarantine_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s::uuid
                    """,
                    (version_id, discovered_at, endpoint_id),
                )
            conn.commit()
            return {
                "version_id": version_id,
                "version_seq": next_seq,
                "version_tag": version_tag,
            }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    def set_mcp_version_score(
        self,
        version_id: str,
        *,
        score: Optional[int],
        grade: Optional[str],
        report: Optional[Dict[str, Any]] = None,
        report_fingerprint: Optional[str] = None,
    ) -> bool:
        """Upsert the quality/lint score for an MCP version snapshot (V2-MCP-21.4, #3685).

        Persists the rolled-up :class:`app.mcp_score.MCPScoreResult` for a discovery snapshot
        into ``mcp_version_scores``. There is exactly one score row per version
        (``mcp_version_scores_version_unique``), so this is an upsert: a re-score of the same
        version overwrites ``score``/``grade``/``report``/``report_fingerprint`` and moves
        ``scored_at`` to now, mirroring the per-revision behaviour of
        :meth:`set_version_quality_score`. The MCP score lives in its own table rather than on
        the version row because ``mcp_endpoint_versions`` snapshots are immutable.

        Tenant scoping is implicit: ``version_id`` is opaque and the caller has already
        validated the owning endpoint/tenant, and the row cascade-deletes with its version
        (and thus its endpoint), so no tenant column is needed here.

        Args:
            version_id: The ``mcp_endpoint_versions`` snapshot to score.
            score: Deterministic 0-100 score, or ``None`` to record an as-yet-unscored row.
            grade: A-F letter grade, or ``None``.
            report: Full scoring report retained for drill-down/render; stored as JSONB
                (defaults to an empty object when omitted, matching the column default).
            report_fingerprint: Stable fingerprint of the report for staleness detection.

        Returns:
            ``True`` when a score row was inserted or updated.
        """
        query = """
            INSERT INTO apiome.mcp_version_scores (
                version_id, score, grade, report, report_fingerprint, scored_at
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (version_id) DO UPDATE SET
                score = EXCLUDED.score,
                grade = EXCLUDED.grade,
                report = EXCLUDED.report,
                report_fingerprint = EXCLUDED.report_fingerprint,
                scored_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        rows = self.execute_query(
            query,
            (
                version_id,
                score,
                grade,
                Json(report if report is not None else {}),
                report_fingerprint,
            ),
        )
        return bool(rows)

    def insert_mcp_test_invocation(
        self,
        *,
        endpoint_id: str,
        version_id: Optional[str],
        item_type: str,
        item_name: str,
        arguments: Optional[Dict[str, Any]],
        response: Optional[Dict[str, Any]],
        is_error: bool,
        latency_ms: Optional[int],
        invoked_by: Optional[str],
    ) -> Dict[str, Any]:
        """Record one test-harness invocation in ``mcp_test_invocations`` (V2-MCP-22.3, #3689).

        Appends a single audit row for a capability that was actually dispatched to its live MCP
        server, so a tenant can see what was tested, when, by whom, and how it turned out. The row
        is the security-critical test log: callers MUST pass an already-redacted ``arguments`` /
        ``response`` (see :func:`app.models.redact_sensitive_args`) — this method persists them
        verbatim and never sees the raw secret-bearing values or the request's auth headers (which
        are never part of the log at all).

        Tenant scoping is implicit: ``endpoint_id`` is opaque and the caller has already validated
        the owning endpoint against the token tenant, and the row cascade-deletes with its endpoint.

        Args:
            endpoint_id: The endpoint the call was made against.
            version_id: The snapshot the invoked item came from (``current_version_id``); may be
                ``None`` (the column is SET NULL on version prune).
            item_type: The capability kind invoked (``tool``/``resource``/``prompt``).
            item_name: The invoked capability's programmatic name.
            arguments: The **redacted** call arguments to log (defaults to ``{}`` when ``None``).
            response: The **redacted** outcome to log (content/error summary), or ``None``.
            is_error: ``True`` when the call returned a tool-level error or failed in transport.
            latency_ms: Integer round-trip latency, or ``None`` when the call never completed.
            invoked_by: The acting user id, or ``None`` when it cannot be resolved.

        Returns:
            The inserted row (``id`` and ``created_at`` among the persisted columns).
        """
        query = """
            INSERT INTO apiome.mcp_test_invocations (
                endpoint_id, version_id, item_type, item_name,
                arguments, response, is_error, latency_ms, invoked_by
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id, endpoint_id, version_id, item_type, item_name,
                      is_error, latency_ms, invoked_by, created_at
        """
        rows = self.execute_query(
            query,
            (
                endpoint_id,
                version_id,
                item_type,
                item_name,
                Json(arguments if arguments is not None else {}),
                Json(response) if response is not None else None,
                is_error,
                latency_ms,
                invoked_by,
            ),
        )
        return rows[0] if rows else {}

    def get_mcp_version_score(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the persisted quality/lint score row for an MCP version snapshot.

        The read counterpart of :meth:`set_mcp_version_score` (V2-MCP-21.5, #3686): returns the
        full stored scoring report so the lint API can serve the *stored* score/grade/findings
        without recomputing. There is at most one row per version
        (``mcp_version_scores_version_unique``), so this returns that single row or ``None`` when
        the snapshot has not been scored yet.

        Tenant scoping is implicit: ``version_id`` is opaque and the caller has already validated
        the owning endpoint/tenant before reaching here.

        Args:
            version_id: The ``mcp_endpoint_versions`` snapshot whose score to read.

        Returns:
            ``{"score", "grade", "report", "report_fingerprint", "scored_at"}`` for the snapshot,
            or ``None`` when it has not been scored.
        """
        query = """
            SELECT score, grade, report, report_fingerprint, scored_at
            FROM apiome.mcp_version_scores
            WHERE version_id = %s::uuid
        """
        rows = self.execute_query(query, (version_id,))
        return dict(rows[0]) if rows else None

    def touch_mcp_endpoint_discovery(
        self,
        endpoint_id: str,
        *,
        status: str,
        discovered_at: Any,
    ) -> None:
        """Stamp a successful no-change discovery without creating a new version.

        Used when a run reaches the server and finds an unchanged surface
        (``status='unchanged'``): the ``current_version_id`` is left untouched so it keeps
        pointing at the last good snapshot, but the contact still succeeded, so — like a
        new-version success — any failure backoff/quarantine state is cleared (MCAT-5.3) and
        the endpoint rejoins the sweep at its normal cadence.

        Failures take a different path (:meth:`record_mcp_discovery_failure`) because they
        *accumulate* state (increment the counter, set the backoff anchor, maybe quarantine)
        rather than reset it.
        """
        q = """
            UPDATE apiome.mcp_endpoints
            SET last_discovered_at = %s,
                last_discovery_status = %s,
                consecutive_failures = 0,
                next_discovery_after = NULL,
                quarantined_at = NULL,
                quarantine_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (discovered_at, status, endpoint_id))
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    def record_mcp_discovery_failure(
        self,
        endpoint_id: str,
        *,
        discovered_at: Any,
        status: str = "failed",
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        quarantine_threshold: int,
        quarantine_reason: str,
        retry_after_seconds: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a failed discovery: increment the failure counter, back off, maybe quarantine.

        The failure counterpart of :meth:`touch_mcp_endpoint_discovery` (MCAT-5.3, #3675).
        In one transaction this:

        1. increments ``consecutive_failures`` and stamps ``last_discovered_at`` /
           ``last_discovery_status`` so the endpoint is not immediately due again (its cadence
           anchor advances) and the latest outcome is visible via the status API;
        2. computes an exponential backoff from the *new* failure count
           (:func:`app.mcp_discovery_backoff.compute_backoff_seconds`, honouring a 429
           ``Retry-After`` floor) and writes ``next_discovery_after`` so the sweep defers the
           endpoint for that delay; and
        3. when the new count reaches ``quarantine_threshold`` (and ``> 0``), sets
           ``quarantined_at`` / ``quarantine_reason`` so the endpoint is auto-excluded from the
           sweep until it recovers — an already-quarantined endpoint keeps its original
           ``quarantined_at`` (the quarantine does not "renew").

        Args:
            endpoint_id: The endpoint whose run failed.
            discovered_at: When the failed attempt ran (the backoff is measured from here).
            status: ``last_discovery_status`` to stamp (default ``failed``; callers may pass a
                more specific error code).
            backoff_base_seconds: Base unit for the exponential backoff.
            backoff_max_seconds: Ceiling for the exponential backoff (a ``Retry-After`` floor
                may exceed it).
            quarantine_threshold: Consecutive-failure count that trips quarantine; ``<= 0``
                disables quarantine (the endpoint backs off but is never auto-disabled).
            quarantine_reason: Diagnostic text stored when the endpoint is quarantined.
            retry_after_seconds: Optional server-supplied minimum delay from a 429 response.

        Returns:
            ``{"consecutive_failures": int, "backoff_seconds": float, "quarantined": bool,
            "newly_quarantined": bool}`` describing the post-update state, or ``None`` when the
            endpoint row no longer exists. ``newly_quarantined`` is ``True`` only on the
            transition into quarantine, so the caller can emit the quarantine event exactly once.
        """
        from .mcp_discovery_backoff import compute_backoff_seconds

        conn = self.connect()
        prev_autocommit = self._begin_tx(conn)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE apiome.mcp_endpoints
                    SET consecutive_failures = consecutive_failures + 1,
                        last_discovered_at = %s,
                        last_discovery_status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s::uuid
                    RETURNING consecutive_failures,
                              (quarantined_at IS NOT NULL) AS was_quarantined
                    """,
                    (discovered_at, status, endpoint_id),
                )
                row = cursor.fetchone()
                if row is None:
                    conn.commit()
                    return None

                failures = int(row["consecutive_failures"])
                already_quarantined = bool(row["was_quarantined"])
                backoff_seconds = compute_backoff_seconds(
                    failures,
                    base_seconds=backoff_base_seconds,
                    max_seconds=backoff_max_seconds,
                    retry_after_seconds=retry_after_seconds,
                )
                should_quarantine = (
                    quarantine_threshold > 0 and failures >= quarantine_threshold
                )
                newly_quarantined = should_quarantine and not already_quarantined

                # Set the backoff anchor always; set quarantine fields only when tripping it,
                # preserving the original quarantined_at if already quarantined (no renewal).
                cursor.execute(
                    """
                    UPDATE apiome.mcp_endpoints
                    SET next_discovery_after = %s + make_interval(secs => %s),
                        quarantined_at = CASE
                            WHEN %s THEN COALESCE(quarantined_at, %s)
                            ELSE quarantined_at
                        END,
                        quarantine_reason = CASE
                            WHEN %s AND quarantined_at IS NULL THEN %s
                            ELSE quarantine_reason
                        END
                    WHERE id = %s::uuid
                    """,
                    (
                        discovered_at,
                        backoff_seconds,
                        should_quarantine,
                        discovered_at,
                        should_quarantine,
                        quarantine_reason,
                        endpoint_id,
                    ),
                )
                conn.commit()
                return {
                    "consecutive_failures": failures,
                    "backoff_seconds": backoff_seconds,
                    "quarantined": should_quarantine or already_quarantined,
                    "newly_quarantined": newly_quarantined,
                }
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.autocommit = prev_autocommit

    def get_mcp_endpoint_credentials(
        self, endpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch the stored credential row for an endpoint, or None when none is configured.

        Returns the credential metadata (``auth_type``, ``key_version``, ``oauth_metadata``,
        timestamps) and the ciphertext ``encrypted_payload``. Plaintext secrets are never
        stored; the caller is responsible for decryption when a decrypting key is wired in.
        """
        q = """
            SELECT id, endpoint_id, auth_type, encrypted_payload, key_version,
                   oauth_metadata, last_refreshed_at, created_at, updated_at
            FROM apiome.mcp_endpoint_credentials
            WHERE endpoint_id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (endpoint_id,))
        return dict(rows[0]) if rows else None

    def upsert_mcp_endpoint_credentials(
        self,
        *,
        endpoint_id: str,
        auth_type: str,
        encrypted_payload: bytes,
        key_version: int,
        oauth_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Set or replace an endpoint's sealed credential (MCAT-6.5), one row per endpoint.

        The secret arrives already sealed (MCAT-6.2): only the ciphertext ``encrypted_payload`` and
        its ``key_version`` are written — never plaintext. The ``endpoint_id`` UNIQUE constraint
        makes this an upsert: a repeat set replaces the previous secret in place and bumps
        ``last_refreshed_at`` (when the secret was last (re)sealed), while the trigger maintains
        ``updated_at``. The caller is responsible for scoping ``endpoint_id`` to the tenant before
        calling.

        Args:
            endpoint_id: The endpoint the credential belongs to.
            auth_type: The secret-bearing scheme (``bearer``/``header``/``oauth2``/``env``).
            encrypted_payload: The sealed secret bytes (ciphertext only).
            key_version: The master-key version that sealed ``encrypted_payload``.
            oauth_metadata: Non-secret OAuth2 metadata to store as cleartext JSONB (defaults to
                ``{}``).

        Returns:
            The stored credential row (including the ciphertext column the caller must redact
            before it leaves the service).
        """
        q = """
            INSERT INTO apiome.mcp_endpoint_credentials (
                endpoint_id, auth_type, encrypted_payload, key_version,
                oauth_metadata, last_refreshed_at
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (endpoint_id) DO UPDATE SET
                auth_type = EXCLUDED.auth_type,
                encrypted_payload = EXCLUDED.encrypted_payload,
                key_version = EXCLUDED.key_version,
                oauth_metadata = EXCLUDED.oauth_metadata,
                last_refreshed_at = CURRENT_TIMESTAMP
            RETURNING id, endpoint_id, auth_type, encrypted_payload, key_version,
                      oauth_metadata, last_refreshed_at, created_at, updated_at
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    q,
                    (
                        endpoint_id,
                        auth_type,
                        psycopg2.Binary(encrypted_payload),
                        key_version,
                        Json(oauth_metadata or {}),
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)
        except Exception as e:
            conn.rollback()
            raise e

    def delete_mcp_endpoint_credentials(self, endpoint_id: str) -> bool:
        """Clear an endpoint's stored credential, removing the row (MCAT-6.5).

        Idempotent: deleting when no credential is configured is a no-op that reports ``False``.
        The caller is responsible for scoping ``endpoint_id`` to the tenant before calling.

        Args:
            endpoint_id: The endpoint whose credential to remove.

        Returns:
            ``True`` when a credential row was deleted, ``False`` when there was none to delete.
        """
        q = "DELETE FROM apiome.mcp_endpoint_credentials WHERE endpoint_id = %s::uuid"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(q, (endpoint_id,))
                deleted = (cursor.rowcount or 0) > 0
                conn.commit()
                return deleted
        except Exception as e:
            conn.rollback()
            raise e

    def upsert_repository_import_spec(
        self,
        tenant_id: str,
        repository_id: str,
        branch: str,
        path: str,
        project_id: str,
        source_kind: str,
        options: Dict[str, Any],
        format_override: Optional[str] = None,
        content_type: Optional[str] = None,
        spec_schema_version: int = 1,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert or refresh the persisted import spec for one repository file (RAR-1.1).

        Keyed on the imported-file lineage ``(repository_id, branch, path)``: a
        repeat import of the same file updates the existing row in place so the
        table always holds the latest spec. ``options`` is the full
        ``SpecImportOptions`` payload and is stored verbatim in ``options_json``.

        The insert is guarded by a subquery so a row is only written when the
        repository belongs to the given tenant.

        Freshness signals (RAR-2.1) — ``last_imported_commit_sha``,
        ``last_imported_committed_at``, ``last_imported_blob_sha`` — are copied from
        the matching indexed ``tenant_repository_files`` row via a LEFT JOIN, so the
        spec records the repository's observed recency for the file at import time.
        When no scan row matches the lineage the anchors are stored as ``NULL`` and
        the newer-than comparator (RAR-2.2) falls back to checksum-only gating.

        Args:
            tenant_id: Owning tenant id.
            repository_id: Source repository id (must belong to ``tenant_id``).
            branch: Branch the file was imported from.
            path: Repository-relative file path (lineage key).
            project_id: Catalog project the import targeted.
            source_kind: Importer discriminator (for example ``openapi-3``).
            options: Full ``SpecImportOptions`` payload to persist.
            format_override: Explicit importer ``--format`` override, if any.
            content_type: MIME type used to read the file, if known.
            spec_schema_version: Envelope version of the stored spec.
            created_by: User id that initiated the import, if known.

        Returns:
            The persisted row as a dict.

        Raises:
            ValueError: If the repository does not belong to the tenant.
        """
        import json

        query = """
            INSERT INTO apiome.repository_import_spec (
                tenant_id, repository_id, branch, path, project_id,
                source_kind, format_override, content_type,
                options_json, spec_schema_version, created_by,
                last_imported_commit_sha, last_imported_committed_at, last_imported_blob_sha
            )
            SELECT %s::uuid, %s::uuid, %s, %s, %s::uuid,
                   %s, %s, %s,
                   %s::jsonb, %s, %s::uuid,
                   trf.commit_sha, trf.committed_at, trf.blob_sha
            FROM apiome.tenant_repositories tr
            LEFT JOIN apiome.tenant_repository_files trf
                ON trf.repository_id = tr.id AND trf.branch = %s AND trf.path = %s
            WHERE tr.id = %s::uuid AND tr.tenant_id = %s::uuid AND tr.deleted_at IS NULL
            ON CONFLICT ON CONSTRAINT uq_repository_import_spec_repo_branch_path
            DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                project_id = EXCLUDED.project_id,
                source_kind = EXCLUDED.source_kind,
                format_override = EXCLUDED.format_override,
                content_type = EXCLUDED.content_type,
                options_json = EXCLUDED.options_json,
                spec_schema_version = EXCLUDED.spec_schema_version,
                created_by = EXCLUDED.created_by,
                last_imported_commit_sha = EXCLUDED.last_imported_commit_sha,
                last_imported_committed_at = EXCLUDED.last_imported_committed_at,
                last_imported_blob_sha = EXCLUDED.last_imported_blob_sha,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, tenant_id, repository_id, branch, path, project_id,
                      source_kind, format_override, content_type,
                      options_json, spec_schema_version, created_by,
                      last_imported_commit_sha, last_imported_committed_at,
                      last_imported_blob_sha, created_at, updated_at
        """
        params = (
            tenant_id, repository_id, branch, path, project_id,
            source_kind, format_override, content_type,
            json.dumps(options or {}), spec_schema_version, created_by,
            branch, path,
            repository_id, tenant_id,
        )
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                conn.commit()
            if row is None:
                raise ValueError(
                    f"Repository {repository_id} not found for tenant {tenant_id}; "
                    "import spec not persisted."
                )
            return row
        except Exception as e:
            conn.rollback()
            raise e

    def get_repository_import_spec(
        self, tenant_id: str, repository_id: str, branch: str, path: str
    ) -> Optional[Dict[str, Any]]:
        """Return the persisted import spec for one repository file, or None.

        Args:
            tenant_id: Owning tenant id (scopes the lookup).
            repository_id: Source repository id.
            branch: Branch the file was imported from.
            path: Repository-relative file path (lineage key).

        Returns:
            The stored row as a dict, or None when no spec exists.
        """
        query = """
            SELECT id, tenant_id, repository_id, branch, path, project_id,
                   source_kind, format_override, content_type,
                   options_json, spec_schema_version, created_by,
                   last_imported_commit_sha, last_imported_committed_at,
                   last_imported_blob_sha, created_at, updated_at
            FROM apiome.repository_import_spec
            WHERE tenant_id = %s::uuid
              AND repository_id = %s::uuid
              AND branch = %s
              AND path = %s
        """
        results = self.execute_query(query, (tenant_id, repository_id, branch, path))
        return results[0] if results else None

    def get_repository_import_options(
        self, tenant_id: str, repository_id: str, branch: str, path: str
    ) -> Optional[Dict[str, Any]]:
        """Return the stored import options for one file, migrated to the current shape.

        Reads the persisted envelope and applies the versioned upgrade path
        (RAR-1.4): if the row's ``spec_schema_version`` is older than the current
        envelope version, the stored ``options_json`` blob is migrated forward so
        the caller always receives a current-shape options dictionary, regardless
        of when the spec was written. Used by repository auto-refresh to replay
        the user's original request.

        Args:
            tenant_id: Owning tenant id (scopes the lookup).
            repository_id: Source repository id.
            branch: Branch the file was imported from.
            path: Repository-relative file path (lineage key).

        Returns:
            The current-shape options as a dict, or None when no spec exists.
        """
        from .models import load_repository_import_options

        row = self.get_repository_import_spec(tenant_id, repository_id, branch, path)
        if row is None:
            return None
        return load_repository_import_options(row).model_dump()

    def get_repository_import_spec_by_id(
        self, tenant_id: str, spec_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return one persisted import spec by its row id, scoped to a tenant (RAR-1.5).

        Backs the ``GET …/repository-imports/{id}/spec`` read endpoint. The
        ``tenant_id`` predicate enforces tenant isolation: a spec belonging to
        another tenant resolves to ``None`` (a 404 at the route) rather than
        leaking across tenants.

        Args:
            tenant_id: Owning tenant id (scopes the lookup).
            spec_id: ``apiome.repository_import_spec`` row id.

        Returns:
            The stored row as a dict, or None when no spec matches in the tenant.
        """
        query = """
            SELECT s.id, s.tenant_id, s.repository_id, s.branch, s.path, s.project_id,
                   s.source_kind, s.format_override, s.content_type,
                   s.options_json, s.spec_schema_version, s.created_by,
                   s.last_imported_commit_sha, s.last_imported_committed_at,
                   s.last_imported_blob_sha, s.created_at, s.updated_at,
                   trf.committed_at AS remote_committed_at,
                   trf.blob_sha AS remote_blob_sha
            FROM apiome.repository_import_spec s
            LEFT JOIN apiome.tenant_repository_files trf
              ON trf.repository_id = s.repository_id
             AND trf.branch = s.branch
             AND trf.path = s.path
            WHERE s.tenant_id = %s::uuid
              AND s.id = %s::uuid
        """
        results = self.execute_query(query, (tenant_id, spec_id))
        return results[0] if results else None

    def get_repository_import_spec_by_path(
        self,
        tenant_id: str,
        repository_id: str,
        path: str,
        branch: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return the latest persisted import spec for a repository file path (RAR-1.5).

        Backs the ``?path=`` lookup variant of the read endpoint. The table keeps
        exactly one row per ``(repository_id, branch, path)`` lineage; when
        ``branch`` is given the lookup is exact, and when it is omitted the most
        recently updated row across branches for that ``(repository_id, path)`` is
        returned. The ``tenant_id`` predicate scopes the lookup so a path under
        another tenant's repository resolves to ``None``.

        Args:
            tenant_id: Owning tenant id (scopes the lookup).
            repository_id: Source repository id.
            path: Repository-relative file path (lineage key).
            branch: Branch to match exactly; when None, the latest across branches.

        Returns:
            The stored row as a dict, or None when no spec matches.
        """
        select = """
            SELECT s.id, s.tenant_id, s.repository_id, s.branch, s.path, s.project_id,
                   s.source_kind, s.format_override, s.content_type,
                   s.options_json, s.spec_schema_version, s.created_by,
                   s.last_imported_commit_sha, s.last_imported_committed_at,
                   s.last_imported_blob_sha, s.created_at, s.updated_at,
                   trf.committed_at AS remote_committed_at,
                   trf.blob_sha AS remote_blob_sha
            FROM apiome.repository_import_spec s
            LEFT JOIN apiome.tenant_repository_files trf
              ON trf.repository_id = s.repository_id
             AND trf.branch = s.branch
             AND trf.path = s.path
            WHERE s.tenant_id = %s::uuid
              AND s.repository_id = %s::uuid
              AND s.path = %s
        """
        if branch is not None:
            query = select + "  AND s.branch = %s\n            ORDER BY s.updated_at DESC\n            LIMIT 1"
            params: tuple = (tenant_id, repository_id, path, branch)
        else:
            query = select + "            ORDER BY s.updated_at DESC\n            LIMIT 1"
            params = (tenant_id, repository_id, path)
        results = self.execute_query(query, params)
        return results[0] if results else None

    def get_public_browse_directory_stats(self) -> Dict[str, int]:
        """Counts for tenants/projects/versions with published public revisions (browse directory)."""
        query = """
            SELECT
                COUNT(DISTINCT t.id)::int AS tenant_count,
                COUNT(DISTINCT p.id)::int AS project_count,
                COUNT(DISTINCT v.id)::int AS version_count
            FROM apiome.tenants t
            JOIN apiome.projects p ON t.id = p.tenant_id
            JOIN apiome.versions v ON p.id = v.project_id
            WHERE v.published = true
              AND v.visibility = 'public'
              AND t.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND v.deleted_at IS NULL
        """
        rows = self.execute_query(query)
        row = rows[0] if rows else {}
        return {
            "tenant_count": int(row.get("tenant_count") or 0),
            "project_count": int(row.get("project_count") or 0),
            "version_count": int(row.get("version_count") or 0),
        }

    def list_public_browse_tenants(
        self,
        *,
        search: Optional[str] = None,
        sort: str = "name",
    ) -> List[Dict[str, Any]]:
        """
        Tenants that have at least one published public version, with aggregates.
        Optional ``search`` filters by tenant name or slug (substring, case-insensitive).
        ``sort`` is one of: name, projects, latest.
        """
        sort_key = sort if sort in ("name", "projects", "latest") else "name"
        order_clause = {
            "name": "a.name ASC, a.slug ASC",
            "projects": "a.project_count DESC, a.name ASC, a.slug ASC",
            "latest": "a.latest_activity_at DESC NULLS LAST, a.name ASC, a.slug ASC",
        }[sort_key]

        search_clause = ""
        params: Tuple[Any, ...] = ()
        term = search.strip() if search and search.strip() else ""
        if term:
            search_clause = "AND (t.name ILIKE %s OR t.slug ILIKE %s)"
            pat = f"%{term}%"
            params = (pat, pat)

        query = f"""
            WITH eligible AS (
                SELECT
                    t.id AS tenant_id,
                    t.slug,
                    t.name,
                    p.id AS project_id,
                    v.id AS version_id,
                    v.version_id AS version_slug,
                    COALESCE(v.published_at, v.updated_at, v.created_at) AS activity_ts
                FROM apiome.tenants t
                INNER JOIN apiome.projects p ON t.id = p.tenant_id
                INNER JOIN apiome.versions v ON p.id = v.project_id
                WHERE v.published = true
                  AND v.visibility = 'public'
                  AND t.deleted_at IS NULL
                  AND p.deleted_at IS NULL
                  AND v.deleted_at IS NULL
                  {search_clause}
            ),
            agg AS (
                SELECT
                    tenant_id,
                    slug,
                    name,
                    COUNT(DISTINCT project_id)::int AS project_count,
                    COUNT(DISTINCT version_id)::int AS published_versions,
                    MAX(activity_ts) AS latest_activity_at
                FROM eligible
                GROUP BY tenant_id, slug, name
            ),
            latest_ver AS (
                SELECT DISTINCT ON (e.tenant_id)
                    e.tenant_id,
                    e.version_slug AS latest_version
                FROM eligible e
                ORDER BY e.tenant_id, e.activity_ts DESC NULLS LAST, e.version_slug DESC
            )
            SELECT
                a.slug,
                a.name,
                a.project_count,
                a.published_versions,
                lv.latest_version,
                a.latest_activity_at
            FROM agg a
            LEFT JOIN latest_ver lv ON lv.tenant_id = a.tenant_id
            ORDER BY {order_clause}
        """
        return self.execute_query(query, params)

    _BROWSE_PROJECT_DOMAIN_COMPARE_SQL = """
        LOWER(TRIM(COALESCE(
            NULLIF(TRIM(COALESCE(p.metadata->>'domain', '')), ''),
            CASE
                WHEN LOWER(TRIM(COALESCE(p.metadata->>'domainCategory', ''))) IN ('', 'none')
                THEN NULL
                ELSE TRIM(COALESCE(p.metadata->>'domainCategory', ''))
            END,
            ''
        )))
        """

    def list_public_browse_projects_for_tenant(
        self,
        tenant_id: str,
        *,
        search: Optional[str] = None,
        domain: Optional[str] = None,
        require_published: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Projects with at least one published **public** version (browse-app parity).

        Optional ``search`` filters slug/name (substring, case-insensitive).
        Optional ``domain`` filters metadata ``domain`` / ``domainCategory`` (case-insensitive).
        ``require_published`` retained for API symmetry; this listing already implies ≥1 public publish.
        """
        dom_sql = self._BROWSE_PROJECT_DOMAIN_COMPARE_SQL.strip()
        term = search.strip() if search and search.strip() else ""
        search_clause = ""
        params: List[Any] = [tenant_id]
        if term:
            search_clause = " AND (p.slug ILIKE %s OR p.name ILIKE %s)"
            pat = f"%{term}%"
            params.extend([pat, pat])
        domain_clause = ""
        domain_term = domain.strip() if domain and domain.strip() else ""
        if domain_term:
            domain_clause = f" AND ({dom_sql}) = LOWER(TRIM(%s))"
            params.append(domain_term)
        published_outer = ""
        if require_published:
            published_outer = " AND a.published_versions >= 1"

        query = f"""
            WITH eligible AS (
                SELECT
                    p.id AS project_id,
                    p.slug,
                    p.name,
                    p.metadata,
                    v.id AS version_id,
                    v.version_id AS version_slug,
                    COALESCE(v.published_at, v.updated_at, v.created_at) AS activity_ts
                FROM apiome.projects p
                INNER JOIN apiome.tenants t ON p.tenant_id = t.id
                INNER JOIN apiome.versions v ON p.id = v.project_id
                WHERE t.id = %s
                  AND v.published IS TRUE
                  AND v.visibility = 'public'
                  AND t.deleted_at IS NULL
                  AND p.deleted_at IS NULL
                  AND v.deleted_at IS NULL
                  {search_clause}
                  {domain_clause}
            ),
            agg AS (
                SELECT
                    e.project_id,
                    e.slug,
                    e.name,
                    e.metadata,
                    COUNT(DISTINCT e.version_id)::int AS published_versions,
                    MAX(e.activity_ts) AS latest_activity_ts
                FROM eligible e
                GROUP BY e.project_id, e.slug, e.name, e.metadata
            ),
            latest_ver AS (
                SELECT DISTINCT ON (e.project_id)
                    e.project_id,
                    e.version_slug AS latest_version,
                    e.activity_ts AS latest_published_at
                FROM eligible e
                ORDER BY e.project_id, e.activity_ts DESC NULLS LAST, e.version_slug DESC
            )
            SELECT
                a.slug,
                a.name,
                a.metadata,
                a.published_versions,
                lv.latest_version,
                lv.latest_published_at
            FROM agg a
            LEFT JOIN latest_ver lv ON lv.project_id = a.project_id
            WHERE 1 = 1
              {published_outer}
            ORDER BY a.slug ASC
        """
        return self.execute_query(query, tuple(params))

    def list_member_browse_projects_for_tenant(
        self,
        tenant_id: str,
        *,
        search: Optional[str] = None,
        domain: Optional[str] = None,
        require_published: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        All non-deleted projects for a tenant member (JWT/API key scoped to tenant).

        Counts and ``latest_*`` consider any published version (any visibility).
        """
        dom_sql = self._BROWSE_PROJECT_DOMAIN_COMPARE_SQL.strip()
        term = search.strip() if search and search.strip() else ""
        search_clause = ""
        params: List[Any] = [tenant_id]
        if term:
            search_clause = " AND (p.slug ILIKE %s OR p.name ILIKE %s)"
            pat = f"%{term}%"
            params.extend([pat, pat])
        domain_clause = ""
        domain_term = domain.strip() if domain and domain.strip() else ""
        if domain_term:
            domain_clause = f" AND ({dom_sql}) = LOWER(TRIM(%s))"
            params.append(domain_term)
        published_clause = ""
        if require_published:
            published_clause = " AND COALESCE(va.published_versions, 0) >= 1"

        query = f"""
            WITH project_base AS (
                SELECT
                    p.id AS project_id,
                    p.slug,
                    p.name,
                    p.metadata
                FROM apiome.projects p
                WHERE p.tenant_id = %s
                  AND p.deleted_at IS NULL
                  {search_clause}
                  {domain_clause}
            ),
            version_agg AS (
                SELECT
                    v.project_id,
                    COUNT(*)::int AS published_versions,
                    MAX(COALESCE(v.published_at, v.updated_at, v.created_at)) AS latest_activity_ts
                FROM apiome.versions v
                INNER JOIN project_base pb ON pb.project_id = v.project_id
                WHERE v.deleted_at IS NULL
                  AND v.published IS TRUE
                GROUP BY v.project_id
            ),
            latest_ver AS (
                SELECT DISTINCT ON (v.project_id)
                    v.project_id,
                    v.version_id AS latest_version,
                    COALESCE(v.published_at, v.updated_at, v.created_at) AS latest_published_at
                FROM apiome.versions v
                INNER JOIN project_base pb ON pb.project_id = v.project_id
                WHERE v.deleted_at IS NULL
                  AND v.published IS TRUE
                ORDER BY
                    v.project_id,
                    COALESCE(v.published_at, v.updated_at, v.created_at) DESC NULLS LAST,
                    v.version_id DESC
            )
            SELECT
                pb.slug,
                pb.name,
                pb.metadata,
                COALESCE(va.published_versions, 0) AS published_versions,
                lv.latest_version,
                lv.latest_published_at
            FROM project_base pb
            LEFT JOIN version_agg va ON va.project_id = pb.project_id
            LEFT JOIN latest_ver lv ON lv.project_id = pb.project_id
            WHERE 1 = 1
              {published_clause}
            ORDER BY pb.slug ASC
        """
        return self.execute_query(query, tuple(params))

    def project_has_public_published_version(self, tenant_id: str, project_slug: str) -> bool:
        """True when the project has at least one published version visible on the public browse surface."""
        q = """
            SELECT 1
            FROM apiome.projects p
            INNER JOIN apiome.versions v ON v.project_id = p.id
            WHERE p.tenant_id = %s
              AND p.slug = %s
              AND p.deleted_at IS NULL
              AND v.deleted_at IS NULL
              AND v.published IS TRUE
              AND v.visibility = 'public'
            LIMIT 1
        """
        rows = self.execute_query(q, (tenant_id, project_slug))
        return bool(rows)

    def list_public_browse_versions_for_project(
        self,
        tenant_id: str,
        project_slug: str,
        *,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Published **public** versions for anonymous browse (parity with apiome-browse).

        ``since`` filters on ``published_at`` (inclusive); rows with null ``published_at`` are excluded when
        ``since`` is set.
        """
        params: List[Any] = [tenant_id, project_slug]
        since_clause = ""
        if since is not None:
            since_clause = " AND v.published_at IS NOT NULL AND v.published_at >= %s"
            params.append(since)

        query = f"""
            SELECT
                v.id::text AS id,
                v.version_id AS version_id,
                v.published_at,
                v.description,
                v.change_log,
                cr.change_model_json,
                COALESCE(
                    (
                        SELECT array_agg(t.name ORDER BY t.name)
                        FROM apiome.version_tags t
                        WHERE t.project_id = p.id
                          AND t.version_id = v.id
                    ),
                    ARRAY[]::text[]
                ) AS tags
            FROM apiome.versions v
            INNER JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.change_reports cr
              ON cr.published_revision_id = v.id
             AND cr.tenant_id = p.tenant_id
             AND cr.project_id = p.id
            WHERE p.tenant_id = %s
              AND p.slug = %s
              AND p.deleted_at IS NULL
              AND v.deleted_at IS NULL
              AND v.published IS TRUE
              AND v.visibility = 'public'
              {since_clause}
        """
        return self.execute_query(query, tuple(params))

    def list_member_browse_versions_for_project(
        self,
        tenant_id: str,
        project_slug: str,
        *,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Published versions for any visibility (tenant member directory)."""
        params: List[Any] = [tenant_id, project_slug]
        since_clause = ""
        if since is not None:
            since_clause = " AND v.published_at IS NOT NULL AND v.published_at >= %s"
            params.append(since)

        query = f"""
            SELECT
                v.id::text AS id,
                v.version_id AS version_id,
                v.published_at,
                v.description,
                v.change_log,
                cr.change_model_json,
                COALESCE(
                    (
                        SELECT array_agg(t.name ORDER BY t.name)
                        FROM apiome.version_tags t
                        WHERE t.project_id = p.id
                          AND t.version_id = v.id
                    ),
                    ARRAY[]::text[]
                ) AS tags
            FROM apiome.versions v
            INNER JOIN apiome.projects p ON v.project_id = p.id
            LEFT JOIN apiome.change_reports cr
              ON cr.published_revision_id = v.id
             AND cr.tenant_id = p.tenant_id
             AND cr.project_id = p.id
            WHERE p.tenant_id = %s
              AND p.slug = %s
              AND p.deleted_at IS NULL
              AND v.deleted_at IS NULL
              AND v.published IS TRUE
              {since_clause}
        """
        return self.execute_query(query, tuple(params))

    # ------------------------------------------------------------------
    # Mock Server instances (#3615, RC1-2.2)
    # ------------------------------------------------------------------

    # Columns returned for every mock-instance read, kept in one place so the management and data
    # planes always see the same shape.
    _MOCK_INSTANCE_COLUMNS = (
        "id, tenant_id, version_id, tenant_slug, project_slug, version_slug, name, "
        "spec, config, rate_limit_per_minute, status, created_by, request_count, "
        "created_at, expires_at, last_activity_at"
    )

    def create_mock_instance(
        self,
        tenant_id: str,
        version_id: Optional[str],
        tenant_slug: str,
        project_slug: str,
        version_slug: str,
        name: str,
        spec: Dict[str, Any],
        config: Dict[str, Any],
        rate_limit_per_minute: int,
        created_by: Optional[str],
        expires_at: Optional[datetime],
    ) -> Dict[str, Any]:
        """Provision a mock instance from a published version's frozen spec.

        Args:
            tenant_id: Owning tenant (for management/listing scope).
            version_id: ``apiome.versions.id`` the mock was generated from (nullable).
            tenant_slug/project_slug/version_slug: Human coordinates for display.
            name: Display name.
            spec: Frozen OpenAPI document the data plane replays from.
            config: Scenario / generation configuration (stored as JSONB).
            rate_limit_per_minute: Per-instance free-tier request budget.
            created_by: User id for attribution (nullable).
            expires_at: Auto-expiry timestamp, or ``None`` for no expiry.

        Returns:
            The newly created mock-instance row.
        """
        query = f"""
            INSERT INTO apiome.mock_instances
                (tenant_id, version_id, tenant_slug, project_slug, version_slug, name,
                 spec, config, rate_limit_per_minute, created_by, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {self._MOCK_INSTANCE_COLUMNS}
        """
        rows = self.execute_query(
            query,
            (
                tenant_id,
                version_id,
                tenant_slug,
                project_slug,
                version_slug,
                name,
                Json(spec),
                Json(config),
                rate_limit_per_minute,
                created_by,
                expires_at,
            ),
        )
        return rows[0]

    def list_mock_instances(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List a tenant's mock instances, newest first."""
        query = f"""
            SELECT {self._MOCK_INSTANCE_COLUMNS}
            FROM apiome.mock_instances
            WHERE tenant_id = %s
            ORDER BY created_at DESC
        """
        return self.execute_query(query, (tenant_id,))

    def get_mock_instance_for_tenant(
        self, mock_id: str, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single mock instance scoped to its owning tenant (management plane)."""
        query = f"""
            SELECT {self._MOCK_INSTANCE_COLUMNS}
            FROM apiome.mock_instances
            WHERE id = %s AND tenant_id = %s
        """
        rows = self.execute_query(query, (mock_id, tenant_id))
        return rows[0] if rows else None

    def get_mock_instance(self, mock_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a mock instance by id without a tenant filter (public data plane)."""
        query = f"""
            SELECT {self._MOCK_INSTANCE_COLUMNS}
            FROM apiome.mock_instances
            WHERE id = %s
        """
        rows = self.execute_query(query, (mock_id,))
        return rows[0] if rows else None

    def update_mock_instance_config(
        self, mock_id: str, tenant_id: str, config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Replace a mock instance's config JSONB (e.g. switch the active scenario)."""
        query = f"""
            UPDATE apiome.mock_instances
            SET config = %s
            WHERE id = %s AND tenant_id = %s
            RETURNING {self._MOCK_INSTANCE_COLUMNS}
        """
        rows = self.execute_query(query, (Json(config), mock_id, tenant_id))
        return rows[0] if rows else None

    def delete_mock_instance(self, mock_id: str, tenant_id: str) -> bool:
        """Destroy a mock instance; returns ``True`` if a row was removed."""
        query = """
            DELETE FROM apiome.mock_instances
            WHERE id = %s AND tenant_id = %s
            RETURNING id
        """
        rows = self.execute_query(query, (mock_id, tenant_id))
        return bool(rows)

    def touch_mock_instance(self, mock_id: str) -> None:
        """Best-effort: bump request_count and last_activity_at for a served data-plane request.

        Failures are swallowed — usage accounting must never break the mock response itself.
        """
        query = """
            UPDATE apiome.mock_instances
            SET request_count = request_count + 1,
                last_activity_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
        """
        try:
            self.execute_query(query, (mock_id,))
        except Exception as exc:  # pragma: no cover - accounting must never raise
            _logger.warning("Failed to update mock instance activity for %s: %s", mock_id, exc)


# Global database instance
db = Database()
