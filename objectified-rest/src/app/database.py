import psycopg2
import json
import logging
import hashlib
from datetime import datetime
import bcrypt
import numpy as np
from psycopg2.extras import Json, RealDictCursor, execute_values
from psycopg2.extensions import register_adapter, AsIs, adapt
from typing import Optional, List, Dict, Any, Tuple, Set
from .config import settings, WEBHOOK_MAX_DELIVERY_ATTEMPTS
from .jsonschema_generator import generate_class_jsonschema_spec
from .revision_deprecation import coerce_metadata, effective_sunset_string, successor_revision_id_from_metadata
from .revision_lifecycle import prepare_version_metadata_update, sql_effective_lifecycle_expr
from .push_webhook_crypto import encrypt_signing_secret

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
            self.connection = psycopg2.connect(
                settings.effective_database_url,
                cursor_factory=RealDictCursor
            )
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
                   p.description as project_description, v.metadata
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            JOIN odb.tenants t ON p.tenant_id = t.id
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
            FROM odb.classes
            WHERE version_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """
        return self.execute_query(query, (version_id,))

    def get_class_by_name(self, version_id: str, class_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific class by name for a version."""
        query = """
            SELECT id, version_id, name, description, schema, enabled
            FROM odb.classes
            WHERE version_id = %s AND name = %s AND deleted_at IS NULL
        """
        results = self.execute_query(query, (version_id, class_name))
        return results[0] if results else None

    def get_properties_for_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get all properties for a specific class."""
        query = """
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM odb.class_properties cp
            LEFT JOIN odb.properties p ON cp.property_id = p.id
            WHERE cp.class_id = %s
            ORDER BY cp.parent_id NULLS FIRST, cp.name ASC
        """
        return self.execute_query(query, (class_id,))

    def get_classes_with_properties_and_tags_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all classes for a version with their properties and tags in bulk."""
        # Query 1: Get all classes for the version
        classes_query = """
            SELECT id, version_id, name, description, schema, enabled, canvas_metadata, created_at, updated_at
            FROM odb.classes
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
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM odb.class_properties cp
            LEFT JOIN odb.properties p ON cp.property_id = p.id
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
            FROM odb.class_tags ct
            JOIN odb.tags t ON ct.tag_id = t.id
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
            FROM odb.classes
            WHERE id = %s AND deleted_at IS NULL
        """
        classes = self.execute_query(class_query, (class_id,))

        if not classes:
            return None

        cls = classes[0]

        # Query 2: Get all properties for this class
        properties_query = """
            SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
                   p.id as property_source_id, p.name as property_source_name, p.data as property_source_data
            FROM odb.class_properties cp
            LEFT JOIN odb.properties p ON cp.property_id = p.id
            WHERE cp.class_id = %s
            ORDER BY cp.parent_id NULLS FIRST, cp.name ASC
        """
        properties = self.execute_query(properties_query, (class_id,))

        # Query 3: Get all tags for this class
        tags_query = """
            SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
                   t.name as tag_name, t.color as tag_color, t.description as tag_description,
                   t.project_id
            FROM odb.class_tags ct
            JOIN odb.tags t ON ct.tag_id = t.id
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
            FROM odb.classes c
            JOIN odb.versions v ON c.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
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
            FROM odb.classes c
            JOIN odb.versions v ON c.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
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
            INSERT INTO odb.classes
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
            UPDATE odb.classes
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
            UPDATE odb.classes
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
        parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Add a property to a class."""
        import json
        
        if not name or not name.strip():
            raise ValueError('Property name is required')
        
        # Validate: either property_id must be set, or data must contain $ref
        has_ref = data and (data.get('$ref') or (data.get('type') == 'array' and data.get('items', {}).get('$ref')))
        if not property_id and not has_ref:
            raise ValueError('Property must have either a library reference (property_id) or a schema $ref')
        
        query = """
            INSERT INTO odb.class_properties (class_id, property_id, name, description, data, parent_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, class_id, property_id, name, description, data, parent_id
        """
        
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (class_id, property_id, name.strip(), description, json.dumps(data), parent_id)
                )
                result = cursor.fetchone()
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
        
        # First verify the class property belongs to a class that belongs to the tenant
        verify_query = """
            SELECT cp.id, cp.class_id
            FROM odb.class_properties cp
            JOIN odb.classes c ON cp.class_id = c.id
            JOIN odb.versions v ON c.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
            WHERE cp.id = %s
              AND c.id = %s
              AND p.tenant_id = %s
        """
        verify_result = self.execute_query(verify_query, (class_property_id, class_id, tenant_id))
        if not verify_result:
            return None
        
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
        
        if not update_fields:
            # Nothing to update, return current property
            return self.execute_query(
                "SELECT id, class_id, property_id, name, description, data, parent_id FROM odb.class_properties WHERE id = %s",
                (class_property_id,)
            )[0] if self.execute_query("SELECT id FROM odb.class_properties WHERE id = %s", (class_property_id,)) else None
        
        params.append(class_property_id)
        
        query = f"""
            UPDATE odb.class_properties
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING id, class_id, property_id, name, description, data, parent_id
        """
        
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
            FROM odb.class_properties cp
            JOIN odb.classes c ON cp.class_id = c.id
            JOIN odb.versions v ON c.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
            WHERE cp.id = %s
              AND c.id = %s
              AND p.tenant_id = %s
        """
        verify_result = self.execute_query(verify_query, (class_property_id, class_id, tenant_id))
        if not verify_result:
            return False
        
        query = """
            DELETE FROM odb.class_properties
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

        query = """
            SELECT ak.id, ak.tenant_id, ak.key_hash, ak.expires_at, ak.enabled,
                   t.id as tenant_id, t.slug as tenant_slug, t.name as tenant_name
            FROM odb.api_keys ak
            JOIN odb.tenants t ON ak.tenant_id = t.id
            WHERE ak.key_prefix = %s
              AND ak.deleted_at IS NULL
              AND ak.enabled = true
              AND t.deleted_at IS NULL
              AND t.enabled = true
              AND (ak.expires_at IS NULL OR ak.expires_at > CURRENT_TIMESTAMP)
        """
        results = self.execute_query(query, (key_prefix,))

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
                        update_query = "UPDATE odb.api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s"
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

    def get_tags_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all tags for a specific project."""
        query = """
            SELECT id, project_id, name, color, description, created_at, updated_at
            FROM odb.tags
            WHERE project_id = %s
            ORDER BY name ASC
        """
        return self.execute_query(query, (project_id,))

    def get_tags_for_class(self, class_id: str) -> List[Dict[str, Any]]:
        """Get all tags assigned to a specific class."""
        query = """
            SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
                   t.name as tag_name, t.color as tag_color, t.description as tag_description
            FROM odb.class_tags ct
            JOIN odb.tags t ON ct.tag_id = t.id
            WHERE ct.class_id = %s
            ORDER BY t.name ASC
        """
        return self.execute_query(query, (class_id,))

    def create_tag(self, project_id: str, name: str, color: str = "default", description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new tag."""
        query = """
            INSERT INTO odb.tags (project_id, name, color, description)
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
            UPDATE odb.tags
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
        query = "DELETE FROM odb.tags WHERE id = %s"
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
            INSERT INTO odb.class_tags (class_id, tag_id)
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
                        "SELECT id, class_id, tag_id, created_at FROM odb.class_tags WHERE class_id = %s AND tag_id = %s",
                        (class_id, tag_id)
                    )
                    result = cursor.fetchone()
                return result
        except Exception as e:
            conn.rollback()
            raise e

    def remove_tag_from_class(self, class_id: str, tag_id: str) -> bool:
        """Remove a tag from a class."""
        query = "DELETE FROM odb.class_tags WHERE class_id = %s AND tag_id = %s"
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
            FROM odb.version_security_scheme
            WHERE version_id = %s
            ORDER BY scheme_name
        """
        return self.execute_query(query, (version_id,))

    def get_servers_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        """Get all server definitions for a version (OpenAPI servers array)."""
        query = """
            SELECT id, version_id, name, url, description, sort_order, variables, environment, created_at, updated_at
            FROM odb.version_server
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
            FROM odb.version_path
            WHERE version_id = %s
            ORDER BY pathname
        """
        return self.execute_query(query, (version_id,))

    def get_operations_for_path(self, version_path_id: str) -> List[Dict[str, Any]]:
        """Get all operations for a specific path."""
        query = """
            SELECT id, version_path_id, operation, metadata, created_at, updated_at
            FROM odb.path_operation
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
            FROM odb.path_operation_description
            WHERE path_operation_id = %s
            LIMIT 1
        """
        results = self.execute_query(query, (path_operation_id,))
        return results[0] if results else None

    def get_parameters_for_operation(self, path_operation_id: str) -> List[Dict[str, Any]]:
        """Get all parameters linked to an operation."""
        query = """
            SELECT spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
            FROM odb.shared_path_parameter spp
            INNER JOIN odb.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
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
            FROM odb.shared_path_request_body rb
            INNER JOIN odb.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
            LEFT JOIN odb.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
            LEFT JOIN odb.classes c ON rbc.class_id = c.id
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
            FROM odb.shared_path_response spr
            INNER JOIN odb.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
            LEFT JOIN odb.classes c ON spr.class_id = c.id
            LEFT JOIN odb.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
            LEFT JOIN odb.classes rc_class ON rc.class_id = rc_class.id
            WHERE porl.path_operation_id = %s
            GROUP BY spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name, spr.inline_schema
            ORDER BY spr.status_code
        """
        return self.execute_query(query, (path_operation_id,))

    def get_primitives_for_tenant(self, tenant_id: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all primitives for a specific tenant."""
        query = """
            SELECT id, tenant_id, name, description, category, schema, tags,
                   created_by, is_system, is_public, usage_count,
                   created_at, updated_at
            FROM odb.primitives
            WHERE tenant_id = %s
        """
        params = [tenant_id]

        if category:
            query += " AND category = %s"
            params.append(category)

        query += " ORDER BY category, name"
        return self.execute_query(query, tuple(params))

    def get_primitive_by_id(self, primitive_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific primitive by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT id, tenant_id, name, description, category, schema, tags,
                   created_by, is_system, is_public, usage_count,
                   created_at, updated_at
            FROM odb.primitives
            WHERE id = %s AND tenant_id = %s
        """
        results = self.execute_query(query, (primitive_id, tenant_id))
        return results[0] if results else None

    def create_primitive(
        self,
        tenant_id: str,
        name: str,
        category: str,
        schema: Dict[str, Any],
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new primitive."""
        query = """
            INSERT INTO odb.primitives
            (tenant_id, name, description, category, schema, tags, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, name, description, category, schema, tags,
                      created_by, is_system, is_public, usage_count,
                      created_at, updated_at
        """

        import json
        schema_json = json.dumps(schema)

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (tenant_id, name, description, category, schema_json, tags or [], created_by)
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

        if not update_fields:
            # Nothing to update, return current primitive
            return self.get_primitive_by_id(primitive_id, tenant_id)

        params.extend([primitive_id, tenant_id])
        query = f"""
            UPDATE odb.primitives
            SET {', '.join(update_fields)}
            WHERE id = %s AND tenant_id = %s
            RETURNING id, tenant_id, name, description, category, schema, tags,
                      created_by, is_system, is_public, usage_count,
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
            DELETE FROM odb.primitives
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
        query = "UPDATE odb.primitives SET usage_count = usage_count + 1 WHERE id = %s"
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, (primitive_id,))
                conn.commit()
        except Exception:
            pass  # Don't fail if we can't increment usage

    # ==================== Project CRUD Operations ====================
    # NOTE: queries below select `change_report_template_version_id`, which requires
    # migration 20260414-150000.sql. Ensure that migration is applied before deploying.

    def get_projects_for_tenant(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Get all projects for a tenant."""
        query = """
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.created_at, p.updated_at,
                   u.name as creator_name, u.email as creator_email
            FROM odb.projects p
            LEFT JOIN odb.users u ON p.creator_id = u.id
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL
            ORDER BY p.created_at DESC
        """
        return self.execute_query(query, (tenant_id,))

    def get_project_by_id(self, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific project by ID, ensuring it belongs to the tenant."""
        query = """
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.created_at, p.updated_at,
                   u.name as creator_name, u.email as creator_email
            FROM odb.projects p
            LEFT JOIN odb.users u ON p.creator_id = u.id
            WHERE p.id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
        """
        results = self.execute_query(query, (project_id, tenant_id))
        return results[0] if results else None

    def get_project_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific project by slug, ensuring it belongs to the tenant."""
        query = """
            SELECT p.id, p.tenant_id, p.creator_id, p.name, p.description, p.slug,
                   p.enabled, p.metadata, p.change_report_template_version_id, p.created_at, p.updated_at,
                   u.name as creator_name, u.email as creator_email
            FROM odb.projects p
            LEFT JOIN odb.users u ON p.creator_id = u.id
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new project."""
        import json
        query = """
            INSERT INTO odb.projects
            (tenant_id, creator_id, name, description, slug, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, creator_id, name, description, slug,
                      enabled, metadata, change_report_template_version_id, created_at, updated_at
        """
        metadata_json = json.dumps(metadata) if metadata else '{}'

        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (tenant_id, creator_id, name, description, slug.lower(), metadata_json)
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
            UPDATE odb.projects
            SET {', '.join(update_fields)}
            WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
            RETURNING id, tenant_id, creator_id, name, description, slug,
                      enabled, metadata, change_report_template_version_id, created_at, updated_at
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
            UPDATE odb.projects
            SET enabled = false, deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
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
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            LEFT JOIN odb.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN odb.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN odb.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN odb.users u ON v.creator_id = u.id
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
        query = """
            SELECT v.id, v.project_id, v.creator_id, v.version_id, v.description,
                   v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                   v.enabled, v.parent_version_id, v.merge_parent_version_id,
                   v.forked_from_revision_id, v.upstream_project_id,
                   v.revision_locked, v.metadata,
                   v.commit_author, v.commit_message, v.external_ref,
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            LEFT JOIN odb.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN odb.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN odb.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN odb.users u ON v.creator_id = u.id
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
                   vf.version_id AS fork_source_version_string,
                   pf.name AS fork_source_project_name,
                   up.name AS upstream_project_name,
                   v.created_at, v.updated_at,
                   u.name as creator_name, u.email as creator_email,
                   p.name as project_name, p.slug as project_slug
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            LEFT JOIN odb.versions vf ON vf.id = v.forked_from_revision_id AND vf.deleted_at IS NULL
            LEFT JOIN odb.projects pf ON pf.id = vf.project_id AND pf.deleted_at IS NULL
            LEFT JOIN odb.projects up ON up.id = v.upstream_project_id AND up.deleted_at IS NULL
            LEFT JOIN odb.users u ON v.creator_id = u.id
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
            SELECT 1 FROM odb.version_branches b
            INNER JOIN odb.projects p ON p.id = b.project_id AND p.deleted_at IS NULL
            WHERE b.project_id = %s AND b.tip_version_id = %s AND b.protected = TRUE
              AND p.tenant_id = %s
            LIMIT 1
        """
        q_tag = """
            SELECT 1 FROM odb.version_tags t
            INNER JOIN odb.projects p ON p.id = t.project_id AND p.deleted_at IS NULL
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
    ) -> Dict[str, Any]:
        """Create a new version."""
        query = """
            INSERT INTO odb.versions
            (project_id, creator_id, version_id, description, change_log,
             commit_author, commit_message, external_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, creator_id, version_id, description,
                      change_log, visibility, published, published_at,
                      enabled, parent_version_id, merge_parent_version_id,
                      commit_author, commit_message, external_ref,
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
                    ),
                )
                result = cursor.fetchone()
                conn.commit()
                return result
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
            INSERT INTO odb.versions
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
                    INSERT INTO odb.classes (version_id, name, description, schema, enabled, canvas_metadata)
                    SELECT %s, name, description, schema, enabled, canvas_metadata
                    FROM odb.classes
                    WHERE version_id = %s AND deleted_at IS NULL
                    RETURNING id, name
                """, (new_id, source_revision_id))

                copied_classes = cursor.fetchall()
                copied_count = len(copied_classes)

                for copied_class in copied_classes:
                    new_class_id = copied_class["id"]
                    class_name = copied_class["name"]

                    cursor.execute("""
                        SELECT id FROM odb.classes
                        WHERE version_id = %s AND name = %s AND deleted_at IS NULL
                    """, (source_revision_id, class_name))

                    original = cursor.fetchone()
                    if original:
                        original_class_id = original["id"]
                        cursor.execute("""
                            INSERT INTO odb.class_properties (class_id, property_id, name, description, data)
                            SELECT %s, property_id, name, description, data
                            FROM odb.class_properties
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
            UPDATE odb.versions
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
        """Publish a version (only owner or tenant admin can publish). Captures class schemas to odb.class_schema.

        description and change_log are written in the same update as publish (validated in routes).
        """
        query = """
            UPDATE odb.versions v
            SET published = true,
                published_at = CURRENT_TIMESTAMP,
                visibility = %s,
                description = %s,
                change_log = %s,
                published_immutable = %s,
                updated_at = CURRENT_TIMESTAMP
            FROM odb.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND (
                v.creator_id = %s
                OR EXISTS (
                  SELECT 1 FROM odb.tenant_administrators ta
                  WHERE ta.tenant_id = p.tenant_id AND ta.user_id = %s
                )
              )
            RETURNING v.id, v.project_id, v.creator_id, v.version_id, v.description,
                      v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                      v.enabled, v.commit_author, v.commit_message, v.external_ref,
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
                        FROM odb.versions v
                        JOIN odb.projects p ON v.project_id = p.id
                        JOIN odb.tenants t ON p.tenant_id = t.id
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
                                INSERT INTO odb.class_schema (version_id, class_id, schema, updated_at)
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
            FROM odb.data_record dr
            JOIN odb.class_schema cs ON dr.class_schema_id = cs.id
            WHERE cs.version_id = %s
            LIMIT 1
        """
        results = self.execute_query(query, (version_record_id,))
        return len(results) > 0

    def version_has_class_schema(self, version_record_id: str) -> bool:
        """Return True if any class_schema row exists for this version (schema already frozen)."""
        query = """
            SELECT 1 FROM odb.class_schema WHERE version_id = %s LIMIT 1
        """
        results = self.execute_query(query, (version_record_id,))
        return len(results) > 0

    # ------------------------- Data records & data_snapshot (embedding in REST) -------------------------

    def assert_class_schema_tenant_access(self, class_schema_id: str, tenant_id: str) -> bool:
        """Return True if class_schema_id belongs to a version in a project under the tenant."""
        query = """
            SELECT 1 FROM odb.class_schema cs
            JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
            WHERE cs.id = %s
        """
        results = self.execute_query(query, (tenant_id, class_schema_id))
        return len(results) > 0

    def get_class_schema_tenant_info(self, class_schema_id: str) -> Optional[Dict[str, Any]]:
        """Return class_schema row and its version's project tenant_id if it exists; None otherwise."""
        query = """
            SELECT cs.id, cs.version_id, p.tenant_id AS project_tenant_id
            FROM odb.class_schema cs
            JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN odb.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
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
            FROM odb.class_schema cs
            JOIN odb.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
            JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
            JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
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
                    INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'created', 1, %s::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, json.dumps(data), tenant_id, created_by),
                )
                cursor.execute(
                    """
                    INSERT INTO odb.data_snapshot (record_id, class_schema_id, data, tenant_id)
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
                    SELECT data FROM odb.data_snapshot
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
                    FROM odb.data_record WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                row = cursor.fetchone()
                next_seq = row["next_seq"] if row else 1
                cursor.execute(
                    """
                    UPDATE odb.data_snapshot
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
                    INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
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
                    SELECT data FROM odb.data_snapshot
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
                    FROM odb.data_record WHERE record_id = %s AND class_schema_id = %s AND tenant_id = %s
                    """,
                    (record_id, class_schema_id, tenant_id),
                )
                seq_row = cursor.fetchone()
                next_seq = seq_row["next_seq"] if seq_row else 1
                cursor.execute(
                    """
                    INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'deleted', %s, %s::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, next_seq, json.dumps(current_data or {}), tenant_id, deleted_by),
                )
                cursor.execute(
                    """
                    DELETE FROM odb.data_snapshot
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
                    FROM odb.data_record
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
                    INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
                    VALUES (%s, %s, 'restored', %s, '{}'::jsonb, %s, %s)
                    """,
                    (record_id, class_schema_id, next_seq, tenant_id, restored_by),
                )
                cursor.execute(
                    """
                    INSERT INTO odb.data_snapshot (record_id, class_schema_id, data, tenant_id)
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
                    UPDATE odb.data_snapshot
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
        Capture class schemas into odb.class_schema for this version (same as publish capture).
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
                    FROM odb.versions v
                    JOIN odb.projects p ON v.project_id = p.id
                    JOIN odb.tenants t ON p.tenant_id = t.id
                    WHERE v.id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL AND p.deleted_at IS NULL
                      AND (v.creator_id = %s OR EXISTS (
                        SELECT 1 FROM odb.tenant_administrators ta
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
                    FROM odb.versions v
                    JOIN odb.projects p ON v.project_id = p.id
                    JOIN odb.tenants t ON p.tenant_id = t.id
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
                        INSERT INTO odb.class_schema (version_id, class_id, schema, updated_at)
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
            UPDATE odb.versions v
            SET published = false,
                published_at = NULL,
                published_immutable = false,
                updated_at = CURRENT_TIMESTAMP
            FROM odb.projects p
            WHERE v.id = %s
              AND v.project_id = p.id
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
              AND (
                v.creator_id = %s
                OR EXISTS (
                  SELECT 1 FROM odb.tenant_administrators ta
                  WHERE ta.tenant_id = p.tenant_id AND ta.user_id = %s
                )
              )
            RETURNING v.id, v.project_id, v.creator_id, v.version_id, v.description,
                      v.change_log, v.visibility, v.published, v.published_at, v.published_immutable,
                      v.enabled, v.commit_author, v.commit_message, v.external_ref,
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
            SELECT 1 FROM odb.tenant_administrators
            WHERE tenant_id = %s AND user_id = %s LIMIT 1
        """
        return bool(self.execute_query(q, (tenant_id, user_id)))

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
                    INSERT INTO odb.version_protection_audit
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
                    INSERT INTO odb.workflow_audit
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
            FROM odb.workflow_audit wa
            WHERE {' AND '.join(clauses)}
            ORDER BY wa.created_at ASC, wa.id ASC
            LIMIT %s
        """
        params.append(limit)
        return self.execute_query(q, tuple(params))

    # ---------- Version quality snapshots ----------

    def insert_version_quality_score(
        self,
        tenant_id: str,
        project_id: str,
        version_id: str,
        overall: int,
        completeness: int,
        consistency: int,
        descriptions: int,
        examples: int,
        class_count: int,
        property_count: int,
        computed_by: Optional[str],
        detail: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one quality snapshot. Returns the inserted row, or None if the
        insert was rolled back (logged at warning)."""
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO odb.version_quality_scores
                      (tenant_id, project_id, version_id,
                       overall, completeness, consistency, descriptions, examples,
                       class_count, property_count, computed_by, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id, tenant_id, project_id, version_id,
                              overall, completeness, consistency, descriptions, examples,
                              class_count, property_count, computed_by, computed_at, detail
                    """,
                    (
                        tenant_id,
                        project_id,
                        version_id,
                        int(overall),
                        int(completeness),
                        int(consistency),
                        int(descriptions),
                        int(examples),
                        int(class_count),
                        int(property_count),
                        computed_by,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None
        except Exception as e:
            conn.rollback()
            _logger.warning("insert_version_quality_score failed: %s", e)
            return None

    def get_latest_version_quality_score(
        self,
        version_id: str,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Most recent snapshot for a version, or None if it's never been measured."""
        rows = self.execute_query(
            """
            SELECT id, tenant_id, project_id, version_id,
                   overall, completeness, consistency, descriptions, examples,
                   class_count, property_count, computed_by, computed_at, detail
            FROM odb.version_quality_scores
            WHERE version_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT 1
            """,
            (version_id, tenant_id),
        )
        return rows[0] if rows else None

    def list_version_quality_history(
        self,
        version_id: str,
        tenant_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """All snapshots for a version, newest first. Caller-bounded by `limit`."""
        return self.execute_query(
            """
            SELECT id, tenant_id, project_id, version_id,
                   overall, completeness, consistency, descriptions, examples,
                   class_count, property_count, computed_by, computed_at, detail
            FROM odb.version_quality_scores
            WHERE version_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT %s
            """,
            (version_id, tenant_id, int(limit)),
        )

    def list_project_quality_history(
        self,
        project_id: str,
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """All snapshots across every version of a project, newest first.

        Used by the project Versions tab's trajectory chart, which plots one
        point per (version, snapshot) pair."""
        return self.execute_query(
            """
            SELECT id, tenant_id, project_id, version_id,
                   overall, completeness, consistency, descriptions, examples,
                   class_count, property_count, computed_by, computed_at, detail
            FROM odb.version_quality_scores
            WHERE project_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT %s
            """,
            (project_id, tenant_id, int(limit)),
        )

    # ---------- Version lint runs ----------

    # Result rows are append-only; the same is true for findings (each `:run`
    # writes a fresh batch). We never mutate a prior result, so the runner can
    # be replayed without coordination beyond a single transaction per run.

    _LINT_RESULT_COLUMNS = (
        "id, tenant_id, project_id, version_id, grade, "
        "error_count, warning_count, info_count, rules_applied, duration_ms, "
        "computed_by, computed_at, detail"
    )

    _LINT_FINDING_COLUMNS = (
        "id, result_id, version_id, rule_id, severity, "
        "target_kind, target_id, target_path, message, suggestion, detail, created_at"
    )

    def insert_version_lint_run(
        self,
        tenant_id: str,
        project_id: str,
        version_id: str,
        grade: str,
        error_count: int,
        warning_count: int,
        info_count: int,
        rules_applied: int,
        duration_ms: Optional[int],
        computed_by: Optional[str],
        findings: List[Dict[str, Any]],
        detail: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Persist one lint run: parent `version_lint_results` row plus all
        findings, in a single transaction. Returns the result row enriched with
        a `findings` list of fully-hydrated finding rows; returns None on
        failure (rolled back, logged at warning).

        `findings` items must carry: rule_id, severity, target_kind,
        target_path, message; `target_id`, `suggestion`, `detail` are optional.
        """
        conn = self.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO odb.version_lint_results
                      (tenant_id, project_id, version_id, grade,
                       error_count, warning_count, info_count, rules_applied,
                       duration_ms, computed_by, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING {self._LINT_RESULT_COLUMNS}
                    """,
                    (
                        tenant_id,
                        project_id,
                        version_id,
                        grade,
                        int(error_count),
                        int(warning_count),
                        int(info_count),
                        int(rules_applied),
                        int(duration_ms) if duration_ms is not None else None,
                        computed_by,
                        json.dumps(detail) if detail is not None else None,
                    ),
                )
                result_row = cursor.fetchone()
                if not result_row:
                    conn.rollback()
                    _logger.warning("insert_version_lint_run: result insert returned no row")
                    return None
                result_id = result_row["id"]

                inserted_findings: List[Dict[str, Any]] = []
                if findings:
                    rows = [
                        (
                            result_id,
                            version_id,
                            f["rule_id"],
                            f["severity"],
                            f["target_kind"],
                            f.get("target_id"),
                            f["target_path"],
                            f["message"],
                            f.get("suggestion"),
                            json.dumps(f["detail"]) if f.get("detail") is not None else None,
                        )
                        for f in findings
                    ]
                    execute_values(
                        cursor,
                        f"""
                        INSERT INTO odb.version_lint_findings
                          (result_id, version_id, rule_id, severity,
                           target_kind, target_id, target_path, message,
                           suggestion, detail)
                        VALUES %s
                        RETURNING {self._LINT_FINDING_COLUMNS}
                        """,
                        rows,
                        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                    )
                    inserted_findings = [dict(r) for r in cursor.fetchall()]

                conn.commit()
                out = dict(result_row)
                out["findings"] = inserted_findings
                return out
        except Exception as e:
            conn.rollback()
            _logger.warning("insert_version_lint_run failed: %s", e)
            return None

    def get_version_lint_result(
        self,
        result_id: str,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch one result row by id, tenant-scoped. Used by the
        `/results/{resultId}` route to render historical scorecards."""
        rows = self.execute_query(
            f"""
            SELECT {self._LINT_RESULT_COLUMNS}
            FROM odb.version_lint_results
            WHERE id = %s AND tenant_id = %s
            """,
            (result_id, tenant_id),
        )
        return rows[0] if rows else None

    def get_latest_version_lint_result(
        self,
        version_id: str,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Most recent result row for a version, or None if it's never been
        linted (the UI shows a `Run lint` CTA in that case)."""
        rows = self.execute_query(
            f"""
            SELECT {self._LINT_RESULT_COLUMNS}
            FROM odb.version_lint_results
            WHERE version_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT 1
            """,
            (version_id, tenant_id),
        )
        return rows[0] if rows else None

    def list_version_lint_findings(
        self,
        result_id: str,
        tenant_id: str,
    ) -> List[Dict[str, Any]]:
        """All findings for one result, ordered for stable UI rendering
        (severity then target path). Tenant scoping happens via the parent
        result; we join to enforce it without trusting the caller."""
        return self.execute_query(
            f"""
            SELECT {self._LINT_FINDING_COLUMNS}
            FROM odb.version_lint_findings f
            JOIN odb.version_lint_results r ON r.id = f.result_id
            WHERE f.result_id = %s AND r.tenant_id = %s
            ORDER BY
                CASE f.severity
                    WHEN 'error' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2
                END,
                f.target_path,
                f.id
            """,
            (result_id, tenant_id),
        )

    def list_version_lint_history(
        self,
        version_id: str,
        tenant_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Result-row history for a single version, newest first. Findings are
        omitted; callers fetch them per-result on demand."""
        return self.execute_query(
            f"""
            SELECT {self._LINT_RESULT_COLUMNS}
            FROM odb.version_lint_results
            WHERE version_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT %s
            """,
            (version_id, tenant_id, int(limit)),
        )

    def list_project_lint_history(
        self,
        project_id: str,
        tenant_id: str,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Result-row history across every version of a project, newest first.
        Used by the project Versions tab to badge versions with their latest
        grade without N round-trips."""
        return self.execute_query(
            f"""
            SELECT {self._LINT_RESULT_COLUMNS}
            FROM odb.version_lint_results
            WHERE project_id = %s AND tenant_id = %s
            ORDER BY computed_at DESC, id DESC
            LIMIT %s
            """,
            (project_id, tenant_id, int(limit)),
        )

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
        q = f"SELECT COUNT(*)::bigint AS cnt FROM odb.workflow_audit wa WHERE {where_sql}"
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
            FROM odb.workflow_audit wa
            WHERE {where_sql}
            ORDER BY wa.created_at DESC, wa.id DESC
            LIMIT %s
        """
        params.append(limit)
        if not use_cursor:
            q += " OFFSET %s"
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
            UPDATE odb.versions v
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            FROM odb.projects p
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
                    INSERT INTO odb.classes (version_id, name, description, schema, enabled, canvas_metadata)
                    SELECT %s, name, description, schema, enabled, canvas_metadata
                    FROM odb.classes
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
                        SELECT id FROM odb.classes
                        WHERE version_id = %s AND name = %s AND deleted_at IS NULL
                    """, (source_version_id, class_name))

                    original = cursor.fetchone()
                    if original:
                        original_class_id = original['id']

                        # Copy class properties (simple copy without nested property mapping for now)
                        cursor.execute("""
                            INSERT INTO odb.class_properties (class_id, property_id, name, description, data)
                            SELECT %s, property_id, name, description, data
                            FROM odb.class_properties
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
            FROM odb.properties
            WHERE project_id = %s AND deleted_at IS NULL
            ORDER BY name ASC
        """
        return self.execute_query(query, (project_id,))

    def get_property_by_id(self, property_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific property by ID, ensuring it belongs to the project."""
        query = """
            SELECT id, project_id, name, description, data, enabled, created_at, updated_at
            FROM odb.properties
            WHERE id = %s AND project_id = %s AND deleted_at IS NULL
        """
        results = self.execute_query(query, (property_id, project_id))
        return results[0] if results else None

    def create_property(self, project_id: str, name: str, description: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new property for a project."""
        query = """
            INSERT INTO odb.properties (project_id, name, description, data)
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
            UPDATE odb.properties
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
            UPDATE odb.properties
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
            FROM odb.version_path vp
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
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
            FROM odb.version_path vp
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
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
            INSERT INTO odb.version_path (version_id, pathname, metadata)
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
            UPDATE odb.version_path
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

        query = "DELETE FROM odb.version_path WHERE id = %s"
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
            FROM odb.version_path_canvas
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
            INSERT INTO odb.version_path_canvas (version_path_id, canvas, updated_at)
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
            FROM odb.path_operation po
            JOIN odb.version_path vp ON po.version_path_id = vp.id
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
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
            INSERT INTO odb.path_operation (version_path_id, operation, metadata)
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
            UPDATE odb.path_operation
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

        query = "DELETE FROM odb.path_operation WHERE id = %s"
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
        existing_query = "SELECT id FROM odb.path_operation_description WHERE path_operation_id = %s"
        results = self.execute_query(existing_query, (path_operation_id,))

        metadata_json = json.dumps(metadata) if metadata else '{}'

        if results:
            # Update existing
            query = """
                UPDATE odb.path_operation_description
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
                INSERT INTO odb.path_operation_description
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
            FROM odb.shared_path_parameter
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
            INSERT INTO odb.shared_path_parameter
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
            INSERT INTO odb.path_operation_parameter_link (path_operation_id, shared_path_parameter_id)
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
                           FROM odb.path_operation_parameter_link
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
            DELETE FROM odb.path_operation_parameter_link
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
            SELECT spp.id FROM odb.shared_path_parameter spp
            JOIN odb.version_path vp ON spp.version_path_id = vp.id
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
            WHERE spp.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (parameter_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM odb.shared_path_parameter WHERE id = %s"
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
            FROM odb.shared_path_request_body
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
            INSERT INTO odb.shared_path_request_body
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
            INSERT INTO odb.path_operation_request_body_link (path_operation_id, shared_path_request_body_id, metadata)
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
        query = "DELETE FROM odb.path_operation_request_body_link WHERE path_operation_id = %s"
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
            INSERT INTO odb.shared_path_request_body_content
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
            SELECT rb.id FROM odb.shared_path_request_body rb
            JOIN odb.version_path vp ON rb.version_path_id = vp.id
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
            WHERE rb.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (request_body_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM odb.shared_path_request_body WHERE id = %s"
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
            FROM odb.shared_path_response
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
            INSERT INTO odb.shared_path_response
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
            INSERT INTO odb.path_operation_response_link (path_operation_id, shared_path_response_id, metadata)
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
            DELETE FROM odb.path_operation_response_link
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
            INSERT INTO odb.shared_path_response_content
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
            SELECT sr.id FROM odb.shared_path_response sr
            JOIN odb.version_path vp ON sr.version_path_id = vp.id
            JOIN odb.versions v ON vp.version_id = v.id
            JOIN odb.projects p ON v.project_id = p.id
            WHERE sr.id = %s AND p.tenant_id = %s
        """
        results = self.execute_query(verify_query, (response_id, tenant_id))
        if not results:
            return False

        query = "DELETE FROM odb.shared_path_response WHERE id = %s"
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
            FROM odb.migration_plan_rules mpr
            JOIN odb.migration_plans mp ON mp.id = mpr.migration_plan_id
            JOIN odb.projects p ON p.id = mp.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
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
            FROM odb.migration_plan_rules mpr
            JOIN odb.migration_plans mp ON mp.id = mpr.migration_plan_id
            JOIN odb.projects p ON p.id = mp.project_id AND p.tenant_id = %s AND p.deleted_at IS NULL
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
                    "SELECT 1 FROM odb.projects WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL",
                    (project_id, tenant_id)
                )
                if cursor.fetchone() is None:
                    return "Project not found or access denied"

                cursor.execute(
                    """SELECT id FROM odb.migration_plans
                       WHERE project_id = %s AND from_version_id = %s AND to_version_id = %s""",
                    (project_id, from_version_id, to_version_id)
                )
                row = cursor.fetchone()
                if row:
                    plan_id = row["id"]
                    cursor.execute(
                        "UPDATE odb.migration_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (plan_id,)
                    )
                else:
                    cursor.execute(
                        """INSERT INTO odb.migration_plans (project_id, from_version_id, to_version_id)
                           VALUES (%s, %s, %s) RETURNING id""",
                        (project_id, from_version_id, to_version_id)
                    )
                    plan_id = cursor.fetchone()["id"]

                cursor.execute(
                    "DELETE FROM odb.migration_plan_rules WHERE migration_plan_id = %s AND class_name = %s",
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
                        """INSERT INTO odb.migration_plan_rules (migration_plan_id, class_name, source_property, rule)
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
            FROM odb.version_tags t
            JOIN odb.versions v ON v.id = t.version_id AND v.project_id = t.project_id
            JOIN odb.projects p ON t.project_id = p.id
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
            FROM odb.version_tags t
            JOIN odb.projects p ON t.project_id = p.id
            WHERE t.id = %s AND t.project_id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL
        """
        rows = self.execute_query(query, (tag_id, project_id, tenant_id))
        return rows[0] if rows else None

    def assert_version_in_project_tenant(
        self, version_row_id: str, project_id: str, tenant_id: str
    ) -> bool:
        q = """
            SELECT 1 FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
            INSERT INTO odb.version_tags
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
            UPDATE odb.version_tags SET {", ".join(sets)}
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
        query = "DELETE FROM odb.version_tags WHERE id = %s AND project_id = %s"
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
            SELECT 1 FROM odb.tenant_administrators
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
            FROM odb.versions v
            INNER JOIN odb.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
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
            FROM odb.version_branches b
            JOIN odb.projects p ON b.project_id = p.id
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
            FROM odb.version_branches b
            JOIN odb.projects p ON b.project_id = p.id
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
                    FROM odb.version_branches b
                    JOIN odb.projects p ON b.project_id = p.id
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
                        SELECT id FROM odb.version_branches
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
                        UPDATE odb.version_branches
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
                    UPDATE odb.version_branches b
                    SET {", ".join(sets)}
                    FROM odb.projects p
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
                        INSERT INTO odb.workflow_audit
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
                    INSERT INTO odb.version_branches
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
            UPDATE odb.classes c
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
            SELECT id, property_id, name, description, data, parent_id
            FROM odb.class_properties
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
                    INSERT INTO odb.class_properties (class_id, property_id, name, description, data, parent_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        target_class_id,
                        prop["property_id"],
                        prop["name"],
                        prop["description"],
                        prop["data"],
                        new_parent,
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
            INSERT INTO odb.classes (version_id, name, description, schema, enabled, canvas_metadata)
            SELECT %s, name, description, schema, enabled, canvas_metadata
            FROM odb.classes
            WHERE version_id = %s AND deleted_at IS NULL
            RETURNING id, name
            """,
            (target_version_id, source_version_id),
        )
        copied = cursor.fetchall()
        for row in copied:
            cursor.execute(
                """
                SELECT id FROM odb.classes
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
            INSERT INTO odb.classes (version_id, name, description, schema, enabled, canvas_metadata)
            SELECT %s, name, description, schema, enabled, canvas_metadata
            FROM odb.classes
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
            SELECT id FROM odb.classes
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
            FROM odb.version_branches b
            JOIN odb.projects p ON b.project_id = p.id
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
                FROM odb.versions v
                JOIN odb.projects p ON v.project_id = p.id
                WHERE v.id = %s
                  AND v.project_id = %s
                  AND p.tenant_id = %s
                  AND v.deleted_at IS NULL
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM odb.versions v
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
                FROM odb.versions v
                JOIN odb.projects p ON v.project_id = p.id
                WHERE v.id = %s
                  AND v.project_id = %s
                  AND p.tenant_id = %s
                  AND v.deleted_at IS NULL
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM odb.versions v
                JOIN against_ancestors a
                  ON v.id::text = a.parent_revision_id
                  OR v.id::text = a.merge_parent_revision_id
                WHERE v.project_id = %s
                  AND v.deleted_at IS NULL
            ),
            merge_base AS (
                SELECT v.id::text AS revision_id, v.created_at
                FROM odb.versions v
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
                FROM odb.versions v
                JOIN merge_base mb ON v.id::text = mb.revision_id
                UNION
                SELECT
                    v.id::text AS revision_id,
                    v.parent_version_id::text AS parent_revision_id,
                    v.merge_parent_version_id::text AS merge_parent_revision_id
                FROM odb.versions v
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
                FROM odb.versions v
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
                FROM odb.versions v
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            WHERE v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL
            ORDER BY v.created_at DESC
            LIMIT 1
        """
        rows = self.execute_query(q, (project_id, tenant_id))
        return str(rows[0]["id"]) if rows else None

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
    ) -> Tuple[Dict[str, Any], int]:
        """
        Insert version (optional parent), copy classes from source, advance branch tip under lock.
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
                        FROM odb.version_branches b
                        JOIN odb.projects p ON b.project_id = p.id
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
                        SELECT p.id FROM odb.projects p
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
                        FROM odb.versions v
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
                    INSERT INTO odb.versions
                    (project_id, creator_id, version_id, description, change_log,
                     commit_author, commit_message, external_ref, parent_version_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        UPDATE odb.version_branches
                        SET tip_version_id = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (new_id, str(branch_row["id"])),
                    )
                elif no_prior_revision:
                    # First commit in a brand-new project: bootstrap a default main branch (#2727).
                    cursor.execute(
                        """
                        INSERT INTO odb.version_branches
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
            FROM odb.merge_sessions ms
            JOIN odb.projects p ON ms.project_id = p.id
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
                    INSERT INTO odb.merge_sessions (
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
                        INSERT INTO odb.merge_session_conflicts (merge_session_id, path, kinds, sort_order)
                        VALUES (%s, %s, %s::jsonb, %s)
                        """,
                        (sid, path, Json(kinds), i),
                    )

                cursor.execute(
                    """
                    INSERT INTO odb.merge_session_status_events (merge_session_id, from_status, to_status, changed_by)
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
            FROM odb.merge_session_status_events
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
            FROM odb.merge_session_conflicts
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
                    FROM odb.merge_sessions ms
                    JOIN odb.projects p ON ms.project_id = p.id
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
                    UPDATE odb.merge_sessions
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
                    INSERT INTO odb.merge_session_status_events (merge_session_id, from_status, to_status, changed_by)
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
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
            FROM odb.versions v
            JOIN odb.projects p ON v.project_id = p.id
            LEFT JOIN odb.version_draft_lock l ON l.version_id = v.id
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
                    FROM odb.version_draft_lock
                    WHERE version_id = %s::uuid
                    FOR UPDATE
                    """,
                    (vid,),
                )
                lock_row = cursor.fetchone()

                if not lock_row:
                    cursor.execute(
                        """
                        INSERT INTO odb.version_draft_lock
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
                        UPDATE odb.version_draft_lock
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
                        UPDATE odb.version_draft_lock
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
                    FROM odb.version_draft_lock
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
                    UPDATE odb.version_draft_lock
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
                    DELETE FROM odb.version_draft_lock
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
                    SELECT 1 FROM odb.version_draft_lock
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
                    DELETE FROM odb.version_draft_lock
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
                    INSERT INTO odb.push_webhook_subscriptions
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
            FROM odb.push_webhook_subscriptions
            WHERE tenant_id = %s::uuid AND deleted_at IS NULL
            ORDER BY created_at DESC
        """
        return self.execute_query(q, (tenant_id,))

    def get_push_webhook_subscription(
        self, tenant_id: str, subscription_id: str
    ) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, url, active, signing_secret_ref, created_at, updated_at
            FROM odb.push_webhook_subscriptions
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
            UPDATE odb.push_webhook_subscriptions
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
                    SELECT id, active FROM odb.push_webhook_subscriptions
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
                    INSERT INTO odb.push_webhook_delivery_events
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
                        FROM odb.push_webhook_delivery_events e
                        INNER JOIN odb.push_webhook_subscriptions s
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
                        UPDATE odb.push_webhook_delivery_events e
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
                    INNER JOIN odb.push_webhook_subscriptions s
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
                    INSERT INTO odb.push_webhook_delivery_attempts
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
                    UPDATE odb.push_webhook_delivery_events
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
            FROM odb.push_webhook_delivery_events
            WHERE tenant_id = %s::uuid AND status = 'dead_letter'
            ORDER BY updated_at DESC
            LIMIT %s
        """
        return self.execute_query(q, (tenant_id, limit))

    def get_push_webhook_delivery_event(self, tenant_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        q = """
            SELECT id, subscription_id, event_type, payload, status, attempt_count, next_retry_at, last_error,
                   created_at, updated_at
            FROM odb.push_webhook_delivery_events
            WHERE tenant_id = %s::uuid AND id = %s::uuid
        """
        rows = self.execute_query(q, (tenant_id, event_id))
        return dict(rows[0]) if rows else None

    def list_push_webhook_delivery_attempts(self, delivery_event_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT attempt_number, http_status, response_body_preview, error_message, latency_ms, attempted_at
            FROM odb.push_webhook_delivery_attempts
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
            FROM odb.change_reports
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
                    INSERT INTO odb.change_reports (
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
                        FROM odb.change_reports
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
                UPDATE odb.change_reports
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
            UPDATE odb.change_reports
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
                UPDATE odb.change_reports
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
                UPDATE odb.change_reports
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
                    INSERT INTO odb.change_report_template_versions (
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
            FROM odb.change_report_template_versions
            WHERE id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (template_id,))
        return dict(rows[0]) if rows else None

    def list_change_report_template_version_summaries(self, tenant_id: str) -> List[Dict[str, Any]]:
        q = """
            SELECT id, owner_tenant_id, semver, created_at
            FROM odb.change_report_template_versions
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
            INSERT INTO odb.change_report_template_versions (
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
            UPDATE odb.tenants
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
            FROM odb.tenants
            WHERE id = %s::uuid
            LIMIT 1
        """
        rows = self.execute_query(q, (tenant_id,))
        if not rows:
            return None
        v = rows[0].get("change_report_template_version_id")
        return str(v) if v is not None else None


# Global database instance
db = Database()

