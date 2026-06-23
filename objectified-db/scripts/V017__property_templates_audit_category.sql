-- Property Templates: Audit Category
-- These templates define common audit patterns for tracking record changes and ownership
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- =============================================================================
-- USER TRACKING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'createdBy',
    'UUID reference to the user who created the record. Set once on insert and never modified.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who created the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
        "readOnly": true
    }',
    ARRAY['created', 'user', 'ownership', 'immutable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'updatedBy',
    'UUID reference to the user who last modified the record. Updated on every change.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who last updated the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
        "readOnly": true
    }',
    ARRAY['updated', 'modified', 'user', 'tracking'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'deletedBy',
    'UUID reference to the user who soft-deleted the record. Null if record is active.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who deleted the record (null if active)",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
        "readOnly": true
    }',
    ARRAY['deleted', 'soft-delete', 'user', 'tracking', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'archivedBy',
    'UUID reference to the user who archived the record. Null if record is active.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who archived the record (null if active)",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null],
        "readOnly": true
    }',
    ARRAY['archived', 'user', 'tracking', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ownerId',
    'UUID reference to the user who owns the record. May differ from creator and can be transferred.',
    'audit',
    '{
        "type": "string",
        "format": "uuid",
        "description": "User who owns the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
    }',
    ARRAY['owner', 'user', 'ownership', 'transferable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'assignedTo',
    'UUID reference to the user currently assigned to the record. Used for task and workflow assignment.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User currently assigned to the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['assigned', 'user', 'workflow', 'task', 'nullable'],
    true,
    true
);

-- =============================================================================
-- VERSION CONTROL FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'version',
    'Integer version number incremented on each update. Used for optimistic locking.',
    'audit',
    '{
        "type": "integer",
        "description": "Record version for optimistic locking",
        "examples": [1, 5, 42],
        "minimum": 1,
        "default": 1
    }',
    ARRAY['version', 'optimistic-locking', 'concurrency'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'revisionNumber',
    'Sequential revision number for document versioning. Tracks the number of published revisions.',
    'audit',
    '{
        "type": "integer",
        "description": "Published revision number",
        "examples": [1, 2, 10],
        "minimum": 1
    }',
    ARRAY['revision', 'version', 'document', 'publishing'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'changeCount',
    'Total number of modifications made to the record since creation.',
    'audit',
    '{
        "type": "integer",
        "description": "Total number of changes to the record",
        "examples": [0, 15, 100],
        "minimum": 0,
        "default": 0,
        "readOnly": true
    }',
    ARRAY['changes', 'count', 'tracking', 'history'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'checksum',
    'Hash of record content for integrity verification and change detection.',
    'audit',
    '{
        "type": "string",
        "description": "Content hash for integrity verification",
        "examples": ["sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
        "pattern": "^(sha256|sha512|md5):[a-f0-9]+$",
        "readOnly": true
    }',
    ARRAY['checksum', 'hash', 'integrity', 'verification'],
    true,
    true
);

-- =============================================================================
-- RECORD STATE FLAGS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isActive',
    'Boolean flag indicating if the record is currently active.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record is active",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['active', 'status', 'flag', 'boolean'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isDeleted',
    'Boolean flag for soft delete status. True indicates the record has been soft-deleted.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record has been soft-deleted",
        "examples": [true, false],
        "default": false,
        "readOnly": true
    }',
    ARRAY['deleted', 'soft-delete', 'flag', 'boolean'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isArchived',
    'Boolean flag indicating if the record has been archived.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record has been archived",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['archived', 'flag', 'boolean', 'inactive'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isLocked',
    'Boolean flag indicating if the record is locked from editing.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record is locked from modifications",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['locked', 'flag', 'boolean', 'editing'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isDraft',
    'Boolean flag indicating if the record is in draft state.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record is a draft",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['draft', 'flag', 'boolean', 'publishing'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isPublished',
    'Boolean flag indicating if the record has been published.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether the record has been published",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['published', 'flag', 'boolean', 'visibility'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isSystem',
    'Boolean flag indicating if the record is a system-generated or protected record.',
    'audit',
    '{
        "type": "boolean",
        "description": "Whether this is a system-managed record",
        "examples": [true, false],
        "default": false,
        "readOnly": true
    }',
    ARRAY['system', 'flag', 'boolean', 'protected'],
    true,
    true
);

-- =============================================================================
-- MULTI-TENANT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'tenantId',
    'UUID reference to the tenant that owns this record. Used for multi-tenant data isolation.',
    'audit',
    '{
        "type": "string",
        "format": "uuid",
        "description": "Tenant identifier for data isolation",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
        "readOnly": true
    }',
    ARRAY['tenant', 'multi-tenant', 'isolation', 'ownership'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'organizationId',
    'UUID reference to the organization that owns this record. Used for organizational data partitioning.',
    'audit',
    '{
        "type": "string",
        "format": "uuid",
        "description": "Organization identifier for data partitioning",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]
    }',
    ARRAY['organization', 'partitioning', 'ownership'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'workspaceId',
    'UUID reference to the workspace containing this record. Used for workspace-level data organization.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "Workspace identifier for data organization",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['workspace', 'organization', 'partitioning', 'nullable'],
    true,
    true
);

-- =============================================================================
-- SOURCE AND ORIGIN TRACKING
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'source',
    'Identifier for the system or process that created the record.',
    'audit',
    '{
        "type": "string",
        "description": "Source system or process that created the record",
        "examples": ["web-app", "api", "import", "migration", "system"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['source', 'origin', 'tracking', 'integration'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'sourceDetails',
    'Detailed information about the source of the record including system, version, and context.',
    'audit',
    '{
        "type": "object",
        "description": "Detailed source tracking information",
        "properties": {
            "system": {
                "type": "string",
                "description": "Source system identifier"
            },
            "version": {
                "type": ["string", "null"],
                "description": "Version of the source system"
            },
            "requestId": {
                "type": ["string", "null"],
                "description": "Original request ID if applicable"
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address of the originating request"
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent of the originating request"
            }
        },
        "required": ["system"],
        "examples": [
            {
                "system": "web-app",
                "version": "2.1.0",
                "requestId": "req_abc123",
                "ipAddress": "192.168.1.100",
                "userAgent": "Mozilla/5.0"
            },
            {
                "system": "api",
                "version": "1.0.0",
                "requestId": null,
                "ipAddress": null,
                "userAgent": null
            }
        ]
    }',
    ARRAY['source', 'origin', 'tracking', 'request', 'detailed'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'importedFrom',
    'Reference to the original source when record was imported from an external system.',
    'audit',
    '{
        "type": ["object", "null"],
        "description": "Import source information",
        "properties": {
            "system": {
                "type": "string",
                "description": "External system name"
            },
            "externalId": {
                "type": "string",
                "description": "ID in the external system"
            },
            "importedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the import occurred"
            },
            "importBatchId": {
                "type": ["string", "null"],
                "description": "Batch identifier for bulk imports"
            }
        },
        "required": ["system", "externalId", "importedAt"],
        "examples": [
            {
                "system": "salesforce",
                "externalId": "003xx000004TmiQAAS",
                "importedAt": "2024-01-15T09:30:00Z",
                "importBatchId": "batch_2024011501"
            },
            null
        ]
    }',
    ARRAY['import', 'external', 'migration', 'origin', 'nullable'],
    true,
    true
);

-- =============================================================================
-- CHANGE TRACKING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lastChangeType',
    'Type of the most recent change made to the record.',
    'audit',
    '{
        "type": "string",
        "description": "Type of the last change",
        "enum": ["create", "update", "delete", "restore", "archive", "publish", "unpublish"],
        "examples": ["create", "update", "delete"]
    }',
    ARRAY['change', 'tracking', 'history', 'type'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'changeReason',
    'Human-readable reason or description for the most recent change.',
    'audit',
    '{
        "type": ["string", "null"],
        "description": "Reason for the last change",
        "examples": ["Updated pricing information", "Fixed typo in description", null],
        "maxLength": 500
    }',
    ARRAY['change', 'reason', 'description', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'changeLog',
    'Array of recent changes with timestamps and descriptions.',
    'audit',
    '{
        "type": "array",
        "description": "Log of recent changes to the record",
        "items": {
            "type": "object",
            "properties": {
                "changedAt": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the change occurred"
                },
                "changedBy": {
                    "type": ["string", "null"],
                    "format": "uuid",
                    "description": "User who made the change"
                },
                "changeType": {
                    "type": "string",
                    "description": "Type of change"
                },
                "reason": {
                    "type": ["string", "null"],
                    "description": "Reason for the change"
                },
                "fieldsChanged": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of fields that were modified"
                }
            },
            "required": ["changedAt", "changeType"]
        },
        "examples": [
            [
                {
                    "changedAt": "2024-01-15T14:30:00Z",
                    "changedBy": "550e8400-e29b-41d4-a716-446655440000",
                    "changeType": "update",
                    "reason": "Updated pricing",
                    "fieldsChanged": ["price", "updatedAt"]
                },
                {
                    "changedAt": "2024-01-15T09:30:00Z",
                    "changedBy": "550e8400-e29b-41d4-a716-446655440000",
                    "changeType": "create",
                    "reason": null,
                    "fieldsChanged": []
                }
            ]
        ]
    }',
    ARRAY['change', 'log', 'history', 'array', 'tracking'],
    true,
    true
);

-- =============================================================================
-- APPROVAL WORKFLOW FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'approvedBy',
    'UUID reference to the user who approved the record.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who approved the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['approved', 'workflow', 'user', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'rejectedBy',
    'UUID reference to the user who rejected the record.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who rejected the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['rejected', 'workflow', 'user', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'reviewedBy',
    'UUID reference to the user who reviewed the record.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who reviewed the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['reviewed', 'workflow', 'user', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'submittedBy',
    'UUID reference to the user who submitted the record for review.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who submitted the record for review",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['submitted', 'workflow', 'user', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'publishedBy',
    'UUID reference to the user who published the record.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who published the record",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['published', 'workflow', 'user', 'nullable'],
    true,
    true
);

-- =============================================================================
-- COMPOSITE AUDIT OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'simpleAudit',
    'Basic audit fields with created/updated timestamps and user references.',
    'audit',
    '{
        "type": "object",
        "description": "Basic audit tracking fields",
        "properties": {
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was created",
                "readOnly": true
            },
            "createdBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who created the record"
            },
            "updatedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was last updated",
                "readOnly": true
            },
            "updatedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who last updated the record"
            }
        },
        "required": ["createdAt", "updatedAt"],
        "examples": [
            {
                "createdAt": "2024-01-15T09:30:00Z",
                "createdBy": "550e8400-e29b-41d4-a716-446655440000",
                "updatedAt": "2024-01-15T14:45:00Z",
                "updatedBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
            }
        ]
    }',
    ARRAY['audit', 'composite', 'basic', 'timestamps', 'users'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'fullAudit',
    'Complete audit fields including soft delete, version, and ownership.',
    'audit',
    '{
        "type": "object",
        "description": "Complete audit tracking fields",
        "properties": {
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was created",
                "readOnly": true
            },
            "createdBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who created the record"
            },
            "updatedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was last updated",
                "readOnly": true
            },
            "updatedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who last updated the record"
            },
            "deletedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When the record was soft-deleted",
                "readOnly": true
            },
            "deletedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who deleted the record"
            },
            "version": {
                "type": "integer",
                "description": "Record version for optimistic locking",
                "minimum": 1,
                "default": 1
            },
            "isDeleted": {
                "type": "boolean",
                "description": "Whether the record has been soft-deleted",
                "default": false
            }
        },
        "required": ["createdAt", "updatedAt", "version", "isDeleted"],
        "examples": [
            {
                "createdAt": "2024-01-15T09:30:00Z",
                "createdBy": "550e8400-e29b-41d4-a716-446655440000",
                "updatedAt": "2024-01-15T14:45:00Z",
                "updatedBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "deletedAt": null,
                "deletedBy": null,
                "version": 3,
                "isDeleted": false
            }
        ]
    }',
    ARRAY['audit', 'composite', 'full', 'soft-delete', 'version'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'tenantAudit',
    'Multi-tenant audit fields including tenant isolation and ownership.',
    'audit',
    '{
        "type": "object",
        "description": "Multi-tenant audit tracking fields",
        "properties": {
            "tenantId": {
                "type": "string",
                "format": "uuid",
                "description": "Tenant identifier for data isolation",
                "readOnly": true
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was created",
                "readOnly": true
            },
            "createdBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who created the record"
            },
            "updatedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the record was last updated",
                "readOnly": true
            },
            "updatedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who last updated the record"
            },
            "ownerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User who owns the record"
            },
            "version": {
                "type": "integer",
                "description": "Record version for optimistic locking",
                "minimum": 1,
                "default": 1
            }
        },
        "required": ["tenantId", "createdAt", "updatedAt", "version"],
        "examples": [
            {
                "tenantId": "550e8400-e29b-41d4-a716-446655440000",
                "createdAt": "2024-01-15T09:30:00Z",
                "createdBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "updatedAt": "2024-01-15T14:45:00Z",
                "updatedBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "ownerId": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "version": 2
            }
        ]
    }',
    ARRAY['audit', 'composite', 'multi-tenant', 'tenant', 'ownership'],
    true,
    true
);

-- =============================================================================
-- LOCK AND CONCURRENCY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lockedBy',
    'UUID reference to the user who currently holds a lock on the record.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "uuid",
        "description": "User who currently holds the lock (null if unlocked)",
        "examples": ["550e8400-e29b-41d4-a716-446655440000", null]
    }',
    ARRAY['locked', 'user', 'concurrency', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lockedAt',
    'Timestamp when the record was locked.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "date-time",
        "description": "When the record was locked (null if unlocked)",
        "examples": ["2024-01-15T09:30:00Z", null]
    }',
    ARRAY['locked', 'timestamp', 'concurrency', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lockExpiresAt',
    'Timestamp when the current lock expires.',
    'audit',
    '{
        "type": ["string", "null"],
        "format": "date-time",
        "description": "When the lock expires (null if unlocked)",
        "examples": ["2024-01-15T10:30:00Z", null]
    }',
    ARRAY['locked', 'expiration', 'concurrency', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lockInfo',
    'Complete lock information including user, timestamps, and reason.',
    'audit',
    '{
        "type": ["object", "null"],
        "description": "Complete lock information (null if unlocked)",
        "properties": {
            "lockedBy": {
                "type": "string",
                "format": "uuid",
                "description": "User holding the lock"
            },
            "lockedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the lock was acquired"
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When the lock expires"
            },
            "reason": {
                "type": ["string", "null"],
                "description": "Reason for the lock"
            }
        },
        "required": ["lockedBy", "lockedAt"],
        "examples": [
            {
                "lockedBy": "550e8400-e29b-41d4-a716-446655440000",
                "lockedAt": "2024-01-15T09:30:00Z",
                "expiresAt": "2024-01-15T10:30:00Z",
                "reason": "Editing document"
            },
            null
        ]
    }',
    ARRAY['locked', 'composite', 'concurrency', 'nullable'],
    true,
    true
);
