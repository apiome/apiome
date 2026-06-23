-- Property Templates: Status Category
-- These templates define common status patterns for tracking record state and lifecycle
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- Drop the existing constraint
ALTER TABLE property_templates
    DROP CONSTRAINT IF EXISTS property_templates_name_category_unique;

-- Add the new constraint with is_system and is_public included
ALTER TABLE property_templates
    ADD CONSTRAINT property_templates_name_category_unique
    UNIQUE NULLS NOT DISTINCT (tenant_id, category, name, is_system, is_public);

-- Update the comment to reflect the new uniqueness rule
COMMENT ON CONSTRAINT property_templates_name_category_unique ON property_templates IS 
    'Ensures template names are unique within the combination of tenant, category, system flag, and public visibility';

-- =============================================================================
-- BOOLEAN STATUS FLAGS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isActive',
    'Boolean flag indicating if the record is currently active and in use.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is active",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['active', 'boolean', 'flag', 'basic'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isEnabled',
    'Boolean flag indicating if the record or feature is enabled.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is enabled",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['enabled', 'boolean', 'flag', 'feature'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isVisible',
    'Boolean flag indicating if the record is visible to users.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is visible",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['visible', 'boolean', 'flag', 'visibility'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isHidden',
    'Boolean flag indicating if the record is hidden from normal views.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is hidden",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['hidden', 'boolean', 'flag', 'visibility'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isFeatured',
    'Boolean flag indicating if the record is featured or highlighted.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is featured",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['featured', 'boolean', 'flag', 'highlight'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isPinned',
    'Boolean flag indicating if the record is pinned to the top of lists.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is pinned",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['pinned', 'boolean', 'flag', 'ordering'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isVerified',
    'Boolean flag indicating if the record has been verified.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record has been verified",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['verified', 'boolean', 'flag', 'trust'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isConfirmed',
    'Boolean flag indicating if the record has been confirmed.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record has been confirmed",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['confirmed', 'boolean', 'flag', 'verification'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isPending',
    'Boolean flag indicating if the record is pending action or approval.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is pending",
        "examples": [true, false],
        "default": true
    }',
    ARRAY['pending', 'boolean', 'flag', 'workflow'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isCompleted',
    'Boolean flag indicating if the record or task has been completed.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is completed",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['completed', 'boolean', 'flag', 'task'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isCancelled',
    'Boolean flag indicating if the record has been cancelled.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record has been cancelled",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['cancelled', 'boolean', 'flag', 'termination'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isExpired',
    'Boolean flag indicating if the record has expired.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record has expired",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['expired', 'boolean', 'flag', 'validity'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isDefault',
    'Boolean flag indicating if the record is the default selection.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is the default",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['default', 'boolean', 'flag', 'selection'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isPrimary',
    'Boolean flag indicating if the record is the primary selection.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is primary",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['primary', 'boolean', 'flag', 'selection'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isReadOnly',
    'Boolean flag indicating if the record is read-only and cannot be modified.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is read-only",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['readonly', 'boolean', 'flag', 'permissions'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'isTemplate',
    'Boolean flag indicating if the record is a template for creating other records.',
    'status',
    '{
        "type": "boolean",
        "description": "Whether the record is a template",
        "examples": [true, false],
        "default": false
    }',
    ARRAY['template', 'boolean', 'flag', 'reusable'],
    true,
    true
);

-- =============================================================================
-- GENERIC STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'status',
    'Generic status field with common lifecycle states.',
    'status',
    '{
        "type": "string",
        "description": "Current status of the record",
        "enum": ["active", "inactive", "pending", "suspended", "deleted"],
        "examples": ["active", "pending", "inactive"],
        "default": "active"
    }',
    ARRAY['status', 'enum', 'generic', 'lifecycle'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'lifecycleStatus',
    'Extended lifecycle status with complete state coverage.',
    'status',
    '{
        "type": "string",
        "description": "Lifecycle status of the record",
        "enum": ["draft", "pending", "active", "suspended", "archived", "deleted"],
        "examples": ["draft", "active", "archived"],
        "default": "draft"
    }',
    ARRAY['status', 'enum', 'lifecycle', 'extended'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'visibilityStatus',
    'Status controlling record visibility.',
    'status',
    '{
        "type": "string",
        "description": "Visibility status of the record",
        "enum": ["public", "private", "unlisted", "restricted", "internal"],
        "examples": ["public", "private", "internal"],
        "default": "private"
    }',
    ARRAY['status', 'enum', 'visibility', 'access'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'moderationStatus',
    'Status for content moderation workflows.',
    'status',
    '{
        "type": "string",
        "description": "Moderation status of the content",
        "enum": ["pending", "approved", "rejected", "flagged", "underReview"],
        "examples": ["pending", "approved", "rejected"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'moderation', 'content'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'verificationStatus',
    'Status for verification workflows.',
    'status',
    '{
        "type": "string",
        "description": "Verification status",
        "enum": ["unverified", "pending", "verified", "failed", "expired"],
        "examples": ["unverified", "verified", "pending"],
        "default": "unverified"
    }',
    ARRAY['status', 'enum', 'verification', 'trust'],
    true,
    true
);

-- =============================================================================
-- PUBLISHING STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'publishStatus',
    'Status for content publishing workflows.',
    'status',
    '{
        "type": "string",
        "description": "Publishing status of the content",
        "enum": ["draft", "pendingReview", "scheduled", "published", "unpublished", "archived"],
        "examples": ["draft", "published", "archived"],
        "default": "draft"
    }',
    ARRAY['status', 'enum', 'publishing', 'content', 'cms'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'editorialStatus',
    'Status for editorial review workflows.',
    'status',
    '{
        "type": "string",
        "description": "Editorial status of the content",
        "enum": ["idea", "assigned", "inProgress", "review", "revision", "approved", "published", "killed"],
        "examples": ["idea", "inProgress", "published"],
        "default": "idea"
    }',
    ARRAY['status', 'enum', 'editorial', 'content', 'workflow'],
    true,
    true
);

-- =============================================================================
-- APPROVAL WORKFLOW STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'approvalStatus',
    'Status for approval workflows.',
    'status',
    '{
        "type": "string",
        "description": "Approval status of the record",
        "enum": ["draft", "submitted", "underReview", "approved", "rejected", "cancelled"],
        "examples": ["draft", "submitted", "approved"],
        "default": "draft"
    }',
    ARRAY['status', 'enum', 'approval', 'workflow'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'reviewStatus',
    'Status for review processes.',
    'status',
    '{
        "type": "string",
        "description": "Review status of the record",
        "enum": ["notReviewed", "inReview", "changesRequested", "approved", "rejected"],
        "examples": ["notReviewed", "inReview", "approved"],
        "default": "notReviewed"
    }',
    ARRAY['status', 'enum', 'review', 'workflow'],
    true,
    true
);

-- =============================================================================
-- TASK AND PROJECT STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'taskStatus',
    'Status for task management.',
    'status',
    '{
        "type": "string",
        "description": "Status of the task",
        "enum": ["backlog", "todo", "inProgress", "inReview", "blocked", "completed", "cancelled"],
        "examples": ["todo", "inProgress", "completed"],
        "default": "backlog"
    }',
    ARRAY['status', 'enum', 'task', 'project'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'projectStatus',
    'Status for project management.',
    'status',
    '{
        "type": "string",
        "description": "Status of the project",
        "enum": ["planning", "notStarted", "inProgress", "onHold", "completed", "cancelled", "archived"],
        "examples": ["planning", "inProgress", "completed"],
        "default": "planning"
    }',
    ARRAY['status', 'enum', 'project', 'management'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'issueStatus',
    'Status for issue and bug tracking.',
    'status',
    '{
        "type": "string",
        "description": "Status of the issue",
        "enum": ["open", "confirmed", "inProgress", "resolved", "closed", "wontFix", "duplicate"],
        "examples": ["open", "inProgress", "resolved"],
        "default": "open"
    }',
    ARRAY['status', 'enum', 'issue', 'bug', 'tracking'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ticketStatus',
    'Status for support ticket tracking.',
    'status',
    '{
        "type": "string",
        "description": "Status of the support ticket",
        "enum": ["new", "open", "pending", "onHold", "solved", "closed"],
        "examples": ["new", "open", "solved"],
        "default": "new"
    }',
    ARRAY['status', 'enum', 'ticket', 'support'],
    true,
    true
);

-- =============================================================================
-- ORDER AND TRANSACTION STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'orderStatus',
    'Status for order processing.',
    'status',
    '{
        "type": "string",
        "description": "Status of the order",
        "enum": ["pending", "confirmed", "processing", "shipped", "delivered", "completed", "cancelled", "refunded"],
        "examples": ["pending", "processing", "delivered"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'order', 'ecommerce'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'paymentStatus',
    'Status for payment processing.',
    'status',
    '{
        "type": "string",
        "description": "Status of the payment",
        "enum": ["pending", "processing", "authorized", "captured", "completed", "failed", "cancelled", "refunded", "disputed"],
        "examples": ["pending", "completed", "refunded"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'payment', 'transaction'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'invoiceStatus',
    'Status for invoice management.',
    'status',
    '{
        "type": "string",
        "description": "Status of the invoice",
        "enum": ["draft", "sent", "viewed", "paid", "partiallyPaid", "overdue", "void", "uncollectible"],
        "examples": ["draft", "sent", "paid"],
        "default": "draft"
    }',
    ARRAY['status', 'enum', 'invoice', 'billing'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'subscriptionStatus',
    'Status for subscription management.',
    'status',
    '{
        "type": "string",
        "description": "Status of the subscription",
        "enum": ["trial", "active", "pastDue", "paused", "cancelled", "expired", "incomplete"],
        "examples": ["trial", "active", "cancelled"],
        "default": "incomplete"
    }',
    ARRAY['status', 'enum', 'subscription', 'billing'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'shippingStatus',
    'Status for shipment tracking.',
    'status',
    '{
        "type": "string",
        "description": "Status of the shipment",
        "enum": ["pending", "labelCreated", "pickedUp", "inTransit", "outForDelivery", "delivered", "failed", "returned"],
        "examples": ["pending", "inTransit", "delivered"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'shipping', 'logistics'],
    true,
    true
);

-- =============================================================================
-- USER AND ACCOUNT STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'userStatus',
    'Status for user accounts.',
    'status',
    '{
        "type": "string",
        "description": "Status of the user account",
        "enum": ["pending", "active", "inactive", "suspended", "banned", "deleted"],
        "examples": ["pending", "active", "suspended"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'user', 'account'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'accountStatus',
    'Status for organization or tenant accounts.',
    'status',
    '{
        "type": "string",
        "description": "Status of the account",
        "enum": ["trial", "active", "suspended", "delinquent", "cancelled", "closed"],
        "examples": ["trial", "active", "suspended"],
        "default": "trial"
    }',
    ARRAY['status', 'enum', 'account', 'organization'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'invitationStatus',
    'Status for user invitations.',
    'status',
    '{
        "type": "string",
        "description": "Status of the invitation",
        "enum": ["pending", "sent", "accepted", "declined", "expired", "revoked"],
        "examples": ["pending", "sent", "accepted"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'invitation', 'user'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'membershipStatus',
    'Status for membership in groups or organizations.',
    'status',
    '{
        "type": "string",
        "description": "Status of the membership",
        "enum": ["pending", "active", "inactive", "suspended", "removed"],
        "examples": ["pending", "active", "removed"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'membership', 'organization'],
    true,
    true
);

-- =============================================================================
-- PROCESS AND JOB STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'jobStatus',
    'Status for background job processing.',
    'status',
    '{
        "type": "string",
        "description": "Status of the background job",
        "enum": ["pending", "queued", "running", "completed", "failed", "cancelled", "retrying"],
        "examples": ["pending", "running", "completed"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'job', 'background', 'async'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'processStatus',
    'Status for long-running processes.',
    'status',
    '{
        "type": "string",
        "description": "Status of the process",
        "enum": ["notStarted", "initializing", "running", "paused", "stopping", "completed", "failed", "terminated"],
        "examples": ["notStarted", "running", "completed"],
        "default": "notStarted"
    }',
    ARRAY['status', 'enum', 'process', 'execution'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'importStatus',
    'Status for data import operations.',
    'status',
    '{
        "type": "string",
        "description": "Status of the import operation",
        "enum": ["pending", "validating", "processing", "completed", "partiallyCompleted", "failed", "cancelled"],
        "examples": ["pending", "processing", "completed"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'import', 'data'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'exportStatus',
    'Status for data export operations.',
    'status',
    '{
        "type": "string",
        "description": "Status of the export operation",
        "enum": ["pending", "generating", "completed", "failed", "expired"],
        "examples": ["pending", "generating", "completed"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'export', 'data'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'syncStatus',
    'Status for data synchronization operations.',
    'status',
    '{
        "type": "string",
        "description": "Status of the sync operation",
        "enum": ["pending", "syncing", "synced", "failed", "conflicted", "stale"],
        "examples": ["pending", "syncing", "synced"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'sync', 'integration'],
    true,
    true
);

-- =============================================================================
-- COMMUNICATION STATUS ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'emailStatus',
    'Status for email delivery.',
    'status',
    '{
        "type": "string",
        "description": "Status of the email",
        "enum": ["draft", "queued", "sending", "sent", "delivered", "opened", "clicked", "bounced", "failed", "unsubscribed"],
        "examples": ["queued", "sent", "delivered"],
        "default": "draft"
    }',
    ARRAY['status', 'enum', 'email', 'communication'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'notificationStatus',
    'Status for notification delivery.',
    'status',
    '{
        "type": "string",
        "description": "Status of the notification",
        "enum": ["pending", "sent", "delivered", "read", "dismissed", "failed"],
        "examples": ["pending", "sent", "read"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'notification', 'communication'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'messageStatus',
    'Status for message delivery in chat or messaging systems.',
    'status',
    '{
        "type": "string",
        "description": "Status of the message",
        "enum": ["pending", "sent", "delivered", "read", "failed"],
        "examples": ["pending", "sent", "read"],
        "default": "pending"
    }',
    ARRAY['status', 'enum', 'message', 'chat'],
    true,
    true
);

-- =============================================================================
-- PRIORITY AND SEVERITY ENUMS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'priority',
    'Priority level for tasks, issues, or requests.',
    'status',
    '{
        "type": "string",
        "description": "Priority level",
        "enum": ["lowest", "low", "medium", "high", "highest", "critical"],
        "examples": ["low", "medium", "high"],
        "default": "medium"
    }',
    ARRAY['priority', 'enum', 'ordering', 'importance'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'priorityNumeric',
    'Numeric priority for flexible ordering. Lower numbers indicate higher priority.',
    'status',
    '{
        "type": "integer",
        "description": "Numeric priority (lower = higher priority)",
        "examples": [1, 5, 10, 100],
        "minimum": 0,
        "default": 50
    }',
    ARRAY['priority', 'numeric', 'ordering', 'importance'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'severity',
    'Severity level for issues, incidents, or alerts.',
    'status',
    '{
        "type": "string",
        "description": "Severity level",
        "enum": ["info", "low", "medium", "high", "critical"],
        "examples": ["info", "medium", "critical"],
        "default": "medium"
    }',
    ARRAY['severity', 'enum', 'incident', 'alert'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'urgency',
    'Urgency level indicating time sensitivity.',
    'status',
    '{
        "type": "string",
        "description": "Urgency level",
        "enum": ["low", "medium", "high", "immediate"],
        "examples": ["low", "medium", "immediate"],
        "default": "medium"
    }',
    ARRAY['urgency', 'enum', 'time', 'sensitivity'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'impact',
    'Impact level indicating scope of effect.',
    'status',
    '{
        "type": "string",
        "description": "Impact level",
        "enum": ["none", "minimal", "moderate", "significant", "severe"],
        "examples": ["minimal", "moderate", "severe"],
        "default": "moderate"
    }',
    ARRAY['impact', 'enum', 'scope', 'assessment'],
    true,
    true
);

-- =============================================================================
-- STATE MACHINE PATTERNS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'state',
    'Generic state field for state machine implementations.',
    'status',
    '{
        "type": "string",
        "description": "Current state in the state machine",
        "examples": ["initial", "processing", "final"],
        "minLength": 1,
        "maxLength": 50
    }',
    ARRAY['state', 'machine', 'generic', 'workflow'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'previousState',
    'Previous state before the last transition.',
    'status',
    '{
        "type": ["string", "null"],
        "description": "Previous state before the last transition",
        "examples": ["draft", "submitted", null],
        "maxLength": 50
    }',
    ARRAY['state', 'machine', 'history', 'transition'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'stateHistory',
    'Array of state transitions with timestamps.',
    'status',
    '{
        "type": "array",
        "description": "History of state transitions",
        "items": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "The state that was entered"
                },
                "enteredAt": {
                    "type": "string",
                    "format": "date-time",
                    "description": "When the state was entered"
                },
                "exitedAt": {
                    "type": ["string", "null"],
                    "format": "date-time",
                    "description": "When the state was exited"
                },
                "triggeredBy": {
                    "type": ["string", "null"],
                    "description": "Event or action that triggered the transition"
                },
                "actorId": {
                    "type": ["string", "null"],
                    "format": "uuid",
                    "description": "User who triggered the transition"
                }
            },
            "required": ["state", "enteredAt"]
        },
        "examples": [
            [
                {
                    "state": "submitted",
                    "enteredAt": "2024-01-15T14:30:00Z",
                    "exitedAt": null,
                    "triggeredBy": "submit",
                    "actorId": "550e8400-e29b-41d4-a716-446655440000"
                },
                {
                    "state": "draft",
                    "enteredAt": "2024-01-15T09:30:00Z",
                    "exitedAt": "2024-01-15T14:30:00Z",
                    "triggeredBy": "create",
                    "actorId": "550e8400-e29b-41d4-a716-446655440000"
                }
            ]
        ]
    }',
    ARRAY['state', 'machine', 'history', 'array', 'audit'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'stateInfo',
    'Complete state machine information including current state, previous state, and metadata.',
    'status',
    '{
        "type": "object",
        "description": "Complete state machine information",
        "properties": {
            "current": {
                "type": "string",
                "description": "Current state"
            },
            "previous": {
                "type": ["string", "null"],
                "description": "Previous state"
            },
            "enteredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the current state was entered"
            },
            "transitionCount": {
                "type": "integer",
                "description": "Number of state transitions",
                "minimum": 0
            },
            "lastTransition": {
                "type": ["string", "null"],
                "description": "Event or action that caused the last transition"
            }
        },
        "required": ["current", "enteredAt", "transitionCount"],
        "examples": [
            {
                "current": "approved",
                "previous": "underReview",
                "enteredAt": "2024-01-15T16:00:00Z",
                "transitionCount": 3,
                "lastTransition": "approve"
            }
        ]
    }',
    ARRAY['state', 'machine', 'composite', 'metadata'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'workflowState',
    'Workflow state with stage tracking and progress information.',
    'status',
    '{
        "type": "object",
        "description": "Workflow state with progress tracking",
        "properties": {
            "currentStage": {
                "type": "string",
                "description": "Current workflow stage"
            },
            "stageIndex": {
                "type": "integer",
                "description": "Index of current stage in workflow",
                "minimum": 0
            },
            "totalStages": {
                "type": "integer",
                "description": "Total number of stages in workflow",
                "minimum": 1
            },
            "completedStages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of completed stage names"
            },
            "pendingStages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of pending stage names"
            },
            "percentComplete": {
                "type": "number",
                "description": "Percentage of workflow completed",
                "minimum": 0,
                "maximum": 100
            }
        },
        "required": ["currentStage", "stageIndex", "totalStages"],
        "examples": [
            {
                "currentStage": "review",
                "stageIndex": 2,
                "totalStages": 4,
                "completedStages": ["draft", "submit"],
                "pendingStages": ["approval"],
                "percentComplete": 50
            }
        ]
    }',
    ARRAY['workflow', 'state', 'progress', 'stages'],
    true,
    true
);

-- =============================================================================
-- PROGRESS AND COMPLETION
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'progressPercent',
    'Completion progress as a percentage.',
    'status',
    '{
        "type": "number",
        "description": "Progress percentage (0-100)",
        "examples": [0, 25, 50, 75, 100],
        "minimum": 0,
        "maximum": 100,
        "default": 0
    }',
    ARRAY['progress', 'percent', 'completion', 'numeric'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'progressFraction',
    'Completion progress as a fraction (0 to 1).',
    'status',
    '{
        "type": "number",
        "description": "Progress fraction (0-1)",
        "examples": [0, 0.25, 0.5, 0.75, 1],
        "minimum": 0,
        "maximum": 1,
        "default": 0
    }',
    ARRAY['progress', 'fraction', 'completion', 'numeric'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'progressInfo',
    'Detailed progress information with current, total, and percentage.',
    'status',
    '{
        "type": "object",
        "description": "Detailed progress information",
        "properties": {
            "current": {
                "type": "integer",
                "description": "Current count or step",
                "minimum": 0
            },
            "total": {
                "type": "integer",
                "description": "Total count or steps",
                "minimum": 0
            },
            "percent": {
                "type": "number",
                "description": "Progress percentage",
                "minimum": 0,
                "maximum": 100
            },
            "message": {
                "type": ["string", "null"],
                "description": "Current progress message"
            }
        },
        "required": ["current", "total", "percent"],
        "examples": [
            {
                "current": 45,
                "total": 100,
                "percent": 45,
                "message": "Processing records..."
            }
        ]
    }',
    ARRAY['progress', 'composite', 'completion', 'detailed'],
    true,
    true
);

-- =============================================================================
-- HEALTH AND OPERATIONAL STATUS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'healthStatus',
    'Health status for services or resources.',
    'status',
    '{
        "type": "string",
        "description": "Health status",
        "enum": ["healthy", "degraded", "unhealthy", "unknown"],
        "examples": ["healthy", "degraded", "unhealthy"],
        "default": "unknown"
    }',
    ARRAY['health', 'enum', 'monitoring', 'operations'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'operationalStatus',
    'Operational status for systems or services.',
    'status',
    '{
        "type": "string",
        "description": "Operational status",
        "enum": ["operational", "maintenance", "degraded", "partialOutage", "majorOutage"],
        "examples": ["operational", "maintenance", "degraded"],
        "default": "operational"
    }',
    ARRAY['operational', 'enum', 'monitoring', 'uptime'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'connectionStatus',
    'Connection status for integrations or external services.',
    'status',
    '{
        "type": "string",
        "description": "Connection status",
        "enum": ["connected", "disconnected", "connecting", "error", "unknown"],
        "examples": ["connected", "disconnected", "error"],
        "default": "unknown"
    }',
    ARRAY['connection', 'enum', 'integration', 'external'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'availabilityStatus',
    'Availability status for resources or services.',
    'status',
    '{
        "type": "string",
        "description": "Availability status",
        "enum": ["available", "busy", "away", "offline", "doNotDisturb"],
        "examples": ["available", "busy", "offline"],
        "default": "offline"
    }',
    ARRAY['availability', 'enum', 'presence', 'user'],
    true,
    true
);
