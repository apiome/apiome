-- Property Templates: Identifiers Category
-- These templates define common identifier patterns used for database joins and record identification
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- =============================================================================
-- PRIMARY KEY IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'uuid',
           'Universal unique identifier suitable for distributed systems. Provides globally unique identification without coordination between nodes.',
           'identifiers',
           '{
               "type": "string",
               "format": "uuid",
               "description": "Unique identifier in UUID v4 format",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
               "readOnly": true
           }',
           ARRAY['uuid', 'primary-key', 'unique', 'distributed'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'id',
           'Sequential integer identifier. Simple and efficient for single-database systems with predictable ordering.',
           'identifiers',
           '{
               "type": "integer",
               "format": "int64",
               "description": "Auto-incrementing unique identifier",
               "examples": [1, 12345, 9876543],
               "minimum": 1,
               "readOnly": true
           }',
           ARRAY['integer', 'primary-key', 'sequential', 'auto-increment'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'ulid',
           'Universally Unique Lexicographically Sortable Identifier. Combines timestamp-based ordering with randomness for distributed systems.',
           'identifiers',
           '{
               "type": "string",
               "description": "ULID - sortable unique identifier",
               "examples": ["01ARZ3NDEKTSV4RRFFQ69G5FAV", "01H9YP8S9KQZ6M7N5X3VWCJTB2"],
               "pattern": "^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
               "minLength": 26,
               "maxLength": 26,
               "readOnly": true
           }',
           ARRAY['ulid', 'primary-key', 'sortable', 'distributed', 'time-based'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cuid2',
           'Collision-resistant unique identifier optimized for horizontal scaling and security. URL-safe and unpredictable.',
           'identifiers',
           '{
               "type": "string",
               "description": "CUID2 - secure, collision-resistant identifier",
               "examples": ["tz4a98xxat96iws9zmbrgj3a", "kj8h7g6f5d4s3a2p1o0i9u8y"],
               "pattern": "^[a-z][a-z0-9]{23}$",
               "minLength": 24,
               "maxLength": 24,
               "readOnly": true
           }',
           ARRAY['cuid', 'primary-key', 'secure', 'distributed', 'url-safe'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'nanoId',
           'Compact, URL-friendly unique identifier. Smaller than UUID while maintaining collision resistance.',
           'identifiers',
           '{
               "type": "string",
               "description": "NanoID - compact unique identifier",
               "examples": ["V1StGXR8_Z5jdHi6B-myT", "FwKp3N9xQ2rLmYc7bJvHs"],
               "pattern": "^[A-Za-z0-9_-]{21}$",
               "minLength": 21,
               "maxLength": 21,
               "readOnly": true
           }',
           ARRAY['nanoid', 'primary-key', 'compact', 'url-safe'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'snowflakeId',
           '64-bit identifier combining timestamp, machine ID, and sequence. Used by Twitter/X and Discord for distributed ID generation.',
           'identifiers',
           '{
               "type": "string",
               "description": "Snowflake ID - distributed 64-bit identifier",
               "examples": ["1541815603606036480", "1234567890123456789"],
               "pattern": "^[0-9]{18,19}$",
               "readOnly": true
           }',
           ARRAY['snowflake', 'primary-key', 'distributed', 'time-based', 'sortable'],
           true,
           true
       );

-- =============================================================================
-- FOREIGN KEY REFERENCES
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'foreignUuid',
           'Reference to another record using UUID. Standard foreign key pattern for UUID-based systems.',
           'identifiers',
           '{
               "type": "string",
               "format": "uuid",
               "description": "Reference to a related record",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
           }',
           ARRAY['uuid', 'foreign-key', 'reference', 'relationship'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'foreignId',
           'Reference to another record using integer ID. Standard foreign key pattern for auto-increment systems.',
           'identifiers',
           '{
               "type": "integer",
               "format": "int64",
               "description": "Reference to a related record",
               "examples": [1, 12345, 9876543],
               "minimum": 1
           }',
           ARRAY['integer', 'foreign-key', 'reference', 'relationship'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'nullableForeignUuid',
           'Optional reference to another record using UUID. Used for optional relationships.',
           'identifiers',
           '{
               "type": ["string", "null"],
               "format": "uuid",
               "description": "Optional reference to a related record",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
           }',
           ARRAY['uuid', 'foreign-key', 'reference', 'relationship', 'nullable', 'optional'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'nullableForeignId',
           'Optional reference to another record using integer ID. Used for optional relationships.',
           'identifiers',
           '{
               "type": ["integer", "null"],
               "format": "int64",
               "description": "Optional reference to a related record",
               "examples": [12345, null],
               "minimum": 1
           }',
           ARRAY['integer', 'foreign-key', 'reference', 'relationship', 'nullable', 'optional'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE AND COMPOUND KEYS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'compositeUuidKey',
           'Two-part composite key using UUIDs. Common for many-to-many junction tables.',
           'identifiers',
           '{
               "type": "object",
               "description": "Composite key consisting of two UUID references",
               "properties": {
                   "firstId": {
                       "type": "string",
                       "format": "uuid",
                       "description": "First part of composite key"
                   },
                   "secondId": {
                       "type": "string",
                       "format": "uuid",
                       "description": "Second part of composite key"
                   }
               },
               "required": ["firstId", "secondId"],
               "additionalProperties": false,
               "examples": [
                   {"firstId": "550e8400-e29b-41d4-a716-446655440000", "secondId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}
               ]
           }',
           ARRAY['composite-key', 'uuid', 'junction-table', 'many-to-many'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'tenantScopedId',
           'Composite identifier combining tenant ID with record ID. Essential for multi-tenant data isolation.',
           'identifiers',
           '{
               "type": "object",
               "description": "Tenant-scoped composite identifier",
               "properties": {
                   "tenantId": {
                       "type": "string",
                       "format": "uuid",
                       "description": "Tenant identifier for data isolation"
                   },
                   "recordId": {
                       "type": "string",
                       "format": "uuid",
                       "description": "Record identifier within tenant scope"
                   }
               },
               "required": ["tenantId", "recordId"],
               "additionalProperties": false,
               "examples": [
                   {"tenantId": "550e8400-e29b-41d4-a716-446655440000", "recordId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"}
               ]
           }',
           ARRAY['composite-key', 'multi-tenant', 'tenant-id', 'isolation'],
           true,
           true
       );

-- =============================================================================
-- BUSINESS/NATURAL IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'slug',
           'URL-friendly identifier derived from human-readable text. Useful for SEO and readable URLs.',
           'identifiers',
           '{
               "type": "string",
               "description": "URL-friendly identifier",
               "examples": ["my-awesome-product", "getting-started-guide", "user-profile-settings"],
               "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
               "minLength": 1,
               "maxLength": 255
           }',
           ARRAY['slug', 'url-friendly', 'seo', 'human-readable', 'natural-key'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'code',
           'Short alphanumeric business code. Used for human-memorable references like product codes or department codes.',
           'identifiers',
           '{
               "type": "string",
               "description": "Short business identifier code",
               "examples": ["PROD001", "DEPT_HR", "SKU-12345"],
               "pattern": "^[A-Z0-9][A-Z0-9_-]{0,49}$",
               "minLength": 1,
               "maxLength": 50
           }',
           ARRAY['code', 'business-key', 'human-readable', 'natural-key'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sku',
           'Stock Keeping Unit identifier. Standard format for inventory and product management.',
           'identifiers',
           '{
               "type": "string",
               "description": "Stock Keeping Unit identifier",
               "examples": ["WH-BLK-XL-001", "ELEC-TV-55-SAM", "FURN-CHR-OAK-42"],
               "pattern": "^[A-Z0-9][A-Z0-9-]{0,63}$",
               "minLength": 1,
               "maxLength": 64
           }',
           ARRAY['sku', 'inventory', 'product', 'business-key', 'natural-key'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'referenceNumber',
           'Human-readable sequential reference number with optional prefix. Common for orders, invoices, tickets.',
           'identifiers',
           '{
               "type": "string",
               "description": "Sequential reference number",
               "examples": ["INV-2024-00001", "ORD-2024-12345", "TKT-2024-00042"],
               "pattern": "^[A-Z]{2,5}-[0-9]{4}-[0-9]{5,10}$",
               "minLength": 12,
               "maxLength": 25
           }',
           ARRAY['reference-number', 'sequential', 'business-key', 'human-readable'],
           true,
           true
       );

-- =============================================================================
-- EXTERNAL SYSTEM IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'externalId',
           'Generic external system identifier. Used for storing IDs from integrated third-party systems.',
           'identifiers',
           '{
               "type": "string",
               "description": "Identifier from an external system",
               "examples": ["ext_abc123xyz", "sf_003xx000004TmiQ", "stripe_cus_123456"],
               "minLength": 1,
               "maxLength": 255
           }',
           ARRAY['external-id', 'integration', 'third-party'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'externalIdWithSource',
           'External identifier paired with its source system. Enables multiple integrations per record.',
           'identifiers',
           '{
               "type": "object",
               "description": "External identifier with source tracking",
               "properties": {
                   "source": {
                       "type": "string",
                       "description": "Name or code of the external system",
                       "minLength": 1,
                       "maxLength": 50
                   },
                   "externalId": {
                       "type": "string",
                       "description": "The identifier in the external system",
                       "minLength": 1,
                       "maxLength": 255
                   }
               },
               "required": ["source", "externalId"],
               "additionalProperties": false,
               "examples": [
                   {"source": "salesforce", "externalId": "003xx000004TmiQAAS"},
                   {"source": "stripe", "externalId": "cus_NffrFeUfNV2Hib"}
               ]
           }',
           ARRAY['external-id', 'integration', 'third-party', 'multi-source'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'correlationId',
           'Identifier for tracing requests across distributed systems. Essential for debugging and observability.',
           'identifiers',
           '{
               "type": "string",
               "format": "uuid",
               "description": "Request correlation identifier for distributed tracing",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
           }',
           ARRAY['correlation-id', 'tracing', 'distributed', 'observability', 'debugging'],
           true,
           true
       );

-- =============================================================================
-- ARRAY/COLLECTION IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'uuidArray',
           'Array of UUID references. Used for one-to-many relationships stored as arrays.',
           'identifiers',
           '{
               "type": "array",
               "description": "Array of UUID references",
               "items": {
                   "type": "string",
                   "format": "uuid",
                   "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
               },
               "uniqueItems": true,
               "examples": [
                   ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
               ]
           }',
           ARRAY['uuid', 'array', 'collection', 'one-to-many'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'idArray',
           'Array of integer ID references. Used for one-to-many relationships stored as arrays.',
           'identifiers',
           '{
               "type": "array",
               "description": "Array of integer ID references",
               "items": {
                   "type": "integer",
                   "format": "int64",
                   "minimum": 1
               },
               "uniqueItems": true,
               "examples": [
                   [1, 2, 3, 45, 67]
               ]
           }',
           ARRAY['integer', 'array', 'collection', 'one-to-many'],
           true,
           true
       );

-- =============================================================================
-- HIERARCHICAL IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'parentId',
           'Self-referential foreign key for tree structures. Points to parent record in same table.',
           'identifiers',
           '{
               "type": ["string", "null"],
               "format": "uuid",
               "description": "Reference to parent record (null for root nodes)",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
           }',
           ARRAY['parent-id', 'hierarchy', 'tree', 'self-reference', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'materializedPath',
           'Path-based hierarchy representation. Stores ancestor chain for efficient subtree queries.',
           'identifiers',
           '{
               "type": "string",
               "description": "Materialized path showing ancestor hierarchy",
               "examples": ["/root/parent/child/grandchild", "/org/dept/team/member"],
               "pattern": "^(/[a-z0-9_-]+)+$",
               "maxLength": 1000
           }',
           ARRAY['path', 'hierarchy', 'tree', 'materialized-path', 'ancestors'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'ltreePath',
           'PostgreSQL ltree-compatible hierarchical path. Optimized for PostgreSQL ltree extension.',
           'identifiers',
           '{
               "type": "string",
               "description": "Ltree-format hierarchical path",
               "examples": ["root.parent.child.grandchild", "org.engineering.backend.api"],
               "pattern": "^[a-zA-Z0-9_]+(\\.[a-zA-Z0-9_]+)*$",
               "maxLength": 1000
           }',
           ARRAY['ltree', 'hierarchy', 'tree', 'postgresql', 'ancestors'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'ancestryArray',
           'Array of ancestor IDs from root to parent. Enables efficient ancestor/descendant queries.',
           'identifiers',
           '{
               "type": "array",
               "description": "Ordered array of ancestor IDs from root to immediate parent",
               "items": {
                   "type": "string",
                   "format": "uuid"
               },
               "examples": [
                   ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
               ]
           }',
           ARRAY['ancestry', 'hierarchy', 'tree', 'array', 'ancestors'],
           true,
           true
       );

-- =============================================================================
-- VERSIONING IDENTIFIERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'version',
           'Integer version number for optimistic locking and change tracking.',
           'identifiers',
           '{
               "type": "integer",
               "description": "Record version number for optimistic locking",
               "examples": [0, 1, 42],
               "minimum": 0,
               "default": 0
           }',
           ARRAY['version', 'optimistic-locking', 'concurrency', 'change-tracking'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'etag',
           'Entity tag for HTTP caching and conditional requests. Typically a hash of record content.',
           'identifiers',
           '{
               "type": "string",
               "description": "Entity tag for caching and conditional updates",
               "examples": ["\"33a64df551425fcc55e4d42a148795d9f25f89d4\"", "\"a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6\""],
               "pattern": "^\"[a-f0-9]{32,40}\"$"
           }',
           ARRAY['etag', 'caching', 'http', 'conditional-request', 'hash'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'revisionId',
           'UUID identifier for a specific revision of a record. Used in document versioning systems.',
           'identifiers',
           '{
               "type": "string",
               "format": "uuid",
               "description": "Unique identifier for this specific revision",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
               "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
               "readOnly": true
           }',
           ARRAY['revision', 'version', 'document', 'history', 'uuid'],
           true,
           true
       );