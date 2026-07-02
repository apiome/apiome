-- Compliance Class Templates
-- Adds compliance class templates for GDPR consent, data retention, audit trails, and privacy settings
-- These templates provide reusable patterns for regulatory compliance and data governance

SET search_path TO apiome, public;

-- =============================================================================
-- GDPRConsent - GDPR consent tracking
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'GDPRConsent',
    'GDPR consent record with purpose, legal basis, and withdrawal tracking.',
    'compliance',
    $JSON${
        "type": "object",
        "description": "GDPR consent record",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the consent record"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null for anonymous consent)"
            },
            "email": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Email address (for anonymous users)"
            },
            "purpose": {
                "type": "string",
                "description": "Purpose of data processing",
                "maxLength": 255,
                "examples": ["marketing", "analytics", "essential", "personalization"]
            },
            "legalBasis": {
                "type": ["string", "null"],
                "description": "Legal basis for processing",
                "enum": ["consent", "contract", "legal_obligation", "vital_interests", "public_task", "legitimate_interests", null],
                "examples": ["consent", "legitimate_interests", null]
            },
            "consentGiven": {
                "type": "boolean",
                "description": "Whether consent was given",
                "examples": [true, false]
            },
            "consentWithdrawn": {
                "type": ["boolean", "null"],
                "description": "Whether consent was withdrawn",
                "default": false,
                "examples": [true, false, null]
            },
            "consentMethod": {
                "type": ["string", "null"],
                "description": "Method of consent",
                "enum": ["explicit", "implicit", "opt_in", "opt_out", null],
                "examples": ["explicit", "opt_in", null]
            },
            "consentVersion": {
                "type": ["string", "null"],
                "description": "Version of consent text/terms",
                "maxLength": 50,
                "examples": ["v1.0", "2026-01", null]
            },
            "consentText": {
                "type": ["string", "null"],
                "description": "Consent text shown to user",
                "maxLength": 5000,
                "examples": ["I agree to receive marketing emails...", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address when consent was given",
                "maxLength": 45,
                "examples": ["192.168.1.1", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent when consent was given",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "givenAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When consent was given"
            },
            "withdrawnAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When consent was withdrawn"
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When consent expires (if applicable)"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional consent metadata",
                "additionalProperties": true,
                "examples": [{"source": "signup_form", "campaign": "welcome"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When consent record was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When consent was last updated"
            }
        },
        "required": ["purpose", "consentGiven", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['gdpr', 'consent', 'compliance', 'privacy', 'data-protection'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- DataRetention - Data retention policies
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'DataRetention',
    'Data retention policy with retention periods, deletion rules, and compliance requirements.',
    'compliance',
    $JSON${
        "type": "object",
        "description": "Data retention policy",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the retention policy"
            },
            "name": {
                "type": "string",
                "description": "Policy name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["User Data Retention", "Transaction Records", "Log Retention"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Policy description",
                "maxLength": 1000,
                "examples": ["Retain user data for 7 years per legal requirements", null]
            },
            "entityType": {
                "type": ["string", "null"],
                "description": "Entity type this policy applies to",
                "maxLength": 100,
                "examples": ["User", "Order", "Log", "Transaction", null]
            },
            "retentionPeriod": {
                "type": ["integer", "null"],
                "description": "Retention period in days",
                "minimum": 0,
                "examples": [2555, 365, 90, null]
            },
            "retentionPeriodUnit": {
                "type": ["string", "null"],
                "description": "Retention period unit",
                "enum": ["days", "months", "years", null],
                "default": "days",
                "examples": ["days", "years", null]
            },
            "retentionPeriodYears": {
                "type": ["number", "null"],
                "description": "Retention period in years (alternative to retentionPeriod)",
                "minimum": 0,
                "examples": [7, 1, 0.25, null]
            },
            "action": {
                "type": ["string", "null"],
                "description": "Action when retention period expires",
                "enum": ["delete", "anonymize", "archive", "review", null],
                "default": "delete",
                "examples": ["delete", "anonymize", "archive", null]
            },
            "legalBasis": {
                "type": ["string", "null"],
                "description": "Legal basis for retention period",
                "maxLength": 500,
                "examples": ["GDPR Article 6", "Tax law requirement (7 years)", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether policy is active",
                "default": true,
                "examples": [true, false]
            },
            "lastRunAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When retention policy was last executed"
            },
            "nextRunAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When retention policy should next run"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional policy metadata",
                "additionalProperties": true,
                "examples": [{"jurisdiction": "EU", "regulation": "GDPR"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When policy was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When policy was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['retention', 'data', 'policy', 'compliance', 'gdpr', 'deletion'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- AuditTrail - Compliance audit logs
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'AuditTrail',
    'Compliance audit trail with immutable records of data access and modifications.',
    'compliance',
    $JSON${
        "type": "object",
        "description": "Compliance audit trail record",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the audit record"
            },
            "entityType": {
                "type": "string",
                "description": "Type of entity being audited",
                "maxLength": 100,
                "examples": ["User", "Order", "Payment", "Consent"]
            },
            "entityId": {
                "type": "string",
                "description": "ID of entity being audited",
                "maxLength": 255,
                "examples": ["user-123", "550e8400-e29b-41d4-a716-446655440000"]
            },
            "action": {
                "type": "string",
                "description": "Action performed",
                "enum": ["create", "read", "update", "delete", "export", "access", "view", "modify", "anonymize", "restore"],
                "examples": ["read", "update", "delete", "export"]
            },
            "actorType": {
                "type": ["string", "null"],
                "description": "Type of actor",
                "enum": ["user", "system", "api", "admin", "automated", null],
                "examples": ["user", "system", "api", null]
            },
            "actorId": {
                "type": ["string", "null"],
                "description": "ID of actor (user, API key, etc.)",
                "maxLength": 255,
                "examples": ["user-123", "api_key-456", null]
            },
            "actorName": {
                "type": ["string", "null"],
                "description": "Actor display name (denormalized)",
                "maxLength": 255,
                "examples": ["John Doe", "System Process", null]
            },
            "changes": {
                "type": ["object", "null"],
                "description": "Changes made (before/after or diff)",
                "additionalProperties": true,
                "examples": [{"before": {"status": "active"}, "after": {"status": "inactive"}}, null]
            },
            "reason": {
                "type": ["string", "null"],
                "description": "Reason for action",
                "maxLength": 500,
                "examples": ["User requested deletion", "GDPR right to erasure", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address of request",
                "maxLength": 45,
                "examples": ["192.168.1.1", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent string",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "requestId": {
                "type": ["string", "null"],
                "description": "Request/correlation ID",
                "maxLength": 100,
                "examples": ["req_abc123", null]
            },
            "complianceType": {
                "type": ["string", "null"],
                "description": "Compliance regulation type",
                "enum": ["gdpr", "ccpa", "hipaa", "sox", "pci", "other", null],
                "examples": ["gdpr", "ccpa", null]
            },
            "isSensitive": {
                "type": ["boolean", "null"],
                "description": "Whether this involves sensitive data",
                "default": false,
                "examples": [true, false, null]
            },
            "dataCategory": {
                "type": ["string", "null"],
                "description": "Category of data accessed",
                "maxLength": 100,
                "examples": ["personal", "financial", "health", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional audit metadata",
                "additionalProperties": true,
                "examples": [{"exportFormat": "csv", "recordCount": 1000}, null]
            },
            "occurredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When action occurred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When audit record was created"
            }
        },
        "required": ["entityType", "entityId", "action", "occurredAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['audit', 'trail', 'compliance', 'logging', 'gdpr', 'tracking'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- PrivacySettings - User privacy preferences
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PrivacySettings',
    'User privacy preferences and data control settings.',
    'compliance',
    $JSON${
        "type": "object",
        "description": "User privacy settings and preferences",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the privacy settings"
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "User ID"
            },
            "profileVisibility": {
                "type": ["string", "null"],
                "description": "Profile visibility setting",
                "enum": ["public", "private", "friends", "custom", null],
                "default": "private",
                "examples": ["public", "private", null]
            },
            "dataSharing": {
                "type": ["boolean", "null"],
                "description": "Whether to allow data sharing with partners",
                "default": false,
                "examples": [true, false, null]
            },
            "analyticsTracking": {
                "type": ["boolean", "null"],
                "description": "Whether to allow analytics tracking",
                "default": true,
                "examples": [true, false, null]
            },
            "marketingEmails": {
                "type": ["boolean", "null"],
                "description": "Whether to receive marketing emails",
                "default": false,
                "examples": [true, false, null]
            },
            "personalization": {
                "type": ["boolean", "null"],
                "description": "Whether to allow personalization",
                "default": true,
                "examples": [true, false, null]
            },
            "searchIndexing": {
                "type": ["boolean", "null"],
                "description": "Whether profile is searchable/indexed",
                "default": true,
                "examples": [true, false, null]
            },
            "thirdPartyData": {
                "type": ["boolean", "null"],
                "description": "Whether to allow third-party data collection",
                "default": false,
                "examples": [true, false, null]
            },
            "dataExport": {
                "type": ["boolean", "null"],
                "description": "Whether user has requested data export",
                "default": false,
                "examples": [true, false, null]
            },
            "dataDeletion": {
                "type": ["boolean", "null"],
                "description": "Whether user has requested data deletion",
                "default": false,
                "examples": [true, false, null]
            },
            "dataDeletionRequestedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When data deletion was requested"
            },
            "dataDeletionScheduledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When data deletion is scheduled"
            },
            "rightToAccess": {
                "type": ["boolean", "null"],
                "description": "Whether user has exercised right to access",
                "default": false,
                "examples": [true, false, null]
            },
            "rightToRectification": {
                "type": ["boolean", "null"],
                "description": "Whether user has exercised right to rectification",
                "default": false,
                "examples": [true, false, null]
            },
            "rightToErasure": {
                "type": ["boolean", "null"],
                "description": "Whether user has exercised right to erasure",
                "default": false,
                "examples": [true, false, null]
            },
            "rightToPortability": {
                "type": ["boolean", "null"],
                "description": "Whether user has exercised right to data portability",
                "default": false,
                "examples": [true, false, null]
            },
            "consentHistory": {
                "type": ["array", "null"],
                "description": "History of consent changes",
                "items": {
                    "type": "object",
                    "properties": {
                        "setting": { "type": "string" },
                        "value": { "type": "boolean" },
                        "changedAt": { "type": "string", "format": "date-time" }
                    },
                    "required": ["setting", "value", "changedAt"]
                },
                "examples": [[{"setting": "marketingEmails", "value": true, "changedAt": "2026-01-25T10:00:00Z"}], null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional privacy metadata",
                "additionalProperties": true,
                "examples": [{"jurisdiction": "EU", "version": "v1.0"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When privacy settings were created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When privacy settings were last updated"
            }
        },
        "required": ["userId", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['privacy', 'settings', 'gdpr', 'compliance', 'user', 'data-protection'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Compliance class templates successfully created: GDPRConsent, DataRetention, AuditTrail, PrivacySettings';
END $$;
