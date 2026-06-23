-- Integrations Class Templates
-- Adds integration class templates for webhook events, API credentials, OAuth tokens, and email templates
-- These templates provide reusable patterns for third-party integrations and outbound communications

SET search_path TO odb, public;

-- =============================================================================
-- WebhookEvent - Outgoing webhook payloads
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'WebhookEvent',
    'Outgoing webhook event payload structure for delivering events to subscriber endpoints.',
    'integration',
    $JSON${
        "type": "object",
        "description": "Outgoing webhook event payload",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique event identifier (idempotency key)"
            },
            "eventType": {
                "type": "string",
                "description": "Event type identifier",
                "maxLength": 100,
                "examples": ["order.created", "user.updated", "subscription.cancelled"]
            },
            "eventVersion": {
                "type": ["string", "null"],
                "description": "Event schema version (e.g., v1, 2026-01)",
                "maxLength": 20,
                "examples": ["v1", "2026-01", null]
            },
            "timestamp": {
                "type": "string",
                "format": "date-time",
                "description": "When the event occurred (ISO 8601)",
                "examples": ["2026-01-25T10:30:00Z"]
            },
            "source": {
                "type": ["string", "null"],
                "description": "Event source (e.g., API, system, integration)",
                "maxLength": 100,
                "examples": ["api", "cron", "stripe", null]
            },
            "payload": {
                "type": "object",
                "description": "Event payload data",
                "additionalProperties": true,
                "examples": [{"orderId": "ord_123", "status": "created", "total": 99.99}]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata (request ID, tenant, etc.)",
                "additionalProperties": true,
                "examples": [{"requestId": "req_abc123", "tenantId": "t_xyz"}, null]
            },
            "webhookId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "ID of webhook subscription this event targets"
            },
            "deliveryId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Delivery attempt identifier for retries"
            },
            "attempt": {
                "type": ["integer", "null"],
                "description": "Delivery attempt number (1-based)",
                "minimum": 1,
                "default": 1,
                "examples": [1, 2, 3, null]
            }
        },
        "required": ["id", "eventType", "timestamp", "payload"]
    }$JSON$::jsonb,
    ARRAY['webhook', 'event', 'integration', 'outgoing', 'payload', 'notification'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- APICredential - Third-party service credentials
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'APICredential',
    'Third-party API or service credentials with secure storage references and metadata.',
    'integration',
    $JSON${
        "type": "object",
        "description": "Third-party API/service credentials",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the credential"
            },
            "name": {
                "type": "string",
                "description": "Credential name or label",
                "maxLength": 255,
                "examples": ["Stripe Production", "SendGrid API", "Slack Bot"]
            },
            "service": {
                "type": "string",
                "description": "Service or provider name",
                "maxLength": 100,
                "examples": ["stripe", "sendgrid", "slack", "twilio"]
            },
            "environment": {
                "type": ["string", "null"],
                "description": "Environment (e.g., production, sandbox)",
                "enum": ["production", "staging", "sandbox", "development", "test", null],
                "examples": ["production", "sandbox", null]
            },
            "credentialType": {
                "type": ["string", "null"],
                "description": "Type of credential",
                "enum": ["api_key", "bearer", "basic", "oauth2", "custom", null],
                "examples": ["api_key", "oauth2", null]
            },
            "keyId": {
                "type": ["string", "null"],
                "description": "Public key ID or identifier (e.g., API key prefix)",
                "maxLength": 100,
                "examples": ["sk_live_abc...", "pk_xxx", null]
            },
            "secretRef": {
                "type": ["string", "null"],
                "description": "Reference to secret in secure store (never store raw secret)",
                "maxLength": 500,
                "examples": ["vault:secret/data/stripe#api_key", "aws:secretsmanager:key", null]
            },
            "endpoint": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Base API endpoint URL",
                "maxLength": 500,
                "examples": ["https://api.stripe.com", "https://api.sendgrid.com/v3", null]
            },
            "scopes": {
                "type": ["array", "null"],
                "description": "OAuth scopes or permission set",
                "items": {
                    "type": "string"
                },
                "examples": [["read", "write"], ["email.send"], null]
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When credential expires (if applicable)"
            },
            "lastUsedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Last time credential was used"
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether credential is active",
                "default": true,
                "examples": [true, false]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata (region, account ID, etc.)",
                "additionalProperties": true,
                "examples": [{"region": "us-east-1", "accountId": "123"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When credential was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When credential was last updated"
            }
        },
        "required": ["name", "service", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['api', 'credential', 'integration', 'third-party', 'secret', 'security'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- OAuthToken - OAuth 2.0 token management
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'OAuthToken',
    'OAuth 2.0 access and refresh token management with expiry and refresh logic.',
    'integration',
    $JSON${
        "type": "object",
        "description": "OAuth 2.0 token management",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the token record"
            },
            "provider": {
                "type": "string",
                "description": "OAuth provider name",
                "maxLength": 50,
                "examples": ["google", "github", "stripe", "salesforce"]
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID this token is associated with"
            },
            "subject": {
                "type": ["string", "null"],
                "description": "OAuth subject (provider user ID)",
                "maxLength": 255,
                "examples": ["oauth2|google|123456", "github|12345", null]
            },
            "accessTokenRef": {
                "type": ["string", "null"],
                "description": "Reference to encrypted access token in secure store",
                "maxLength": 500,
                "examples": ["vault:secret/data/oauth#access_token", null]
            },
            "refreshTokenRef": {
                "type": ["string", "null"],
                "description": "Reference to encrypted refresh token in secure store",
                "maxLength": 500,
                "examples": ["vault:secret/data/oauth#refresh_token", null]
            },
            "tokenType": {
                "type": ["string", "null"],
                "description": "Token type (usually Bearer)",
                "default": "Bearer",
                "maxLength": 20,
                "examples": ["Bearer", "bearer", null]
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When access token expires"
            },
            "refreshExpiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When refresh token expires (if applicable)"
            },
            "scopes": {
                "type": ["array", "null"],
                "description": "Granted OAuth scopes",
                "items": {
                    "type": "string"
                },
                "examples": [["openid", "email", "profile"], ["repo", "user"], null]
            },
            "scope": {
                "type": ["string", "null"],
                "description": "Space-separated scopes (alternative to scopes array)",
                "maxLength": 1000,
                "examples": ["openid email profile", "repo user", null]
            },
            "lastRefreshedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When token was last refreshed"
            },
            "refreshCount": {
                "type": ["integer", "null"],
                "description": "Number of times token has been refreshed",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 10, null]
            },
            "isRevoked": {
                "type": "boolean",
                "description": "Whether token has been revoked",
                "default": false,
                "examples": [true, false]
            },
            "revokedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When token was revoked"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional provider-specific metadata",
                "additionalProperties": true,
                "examples": [{"provider_user_id": "123", "email": "user@example.com"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When token was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When token was last updated"
            }
        },
        "required": ["provider", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['oauth', 'oauth2', 'token', 'integration', 'auth', 'sso'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- EmailTemplate - Transactional email structures
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'EmailTemplate',
    'Transactional email template structure with subject, body, variables, and delivery metadata.',
    'integration',
    $JSON${
        "type": "object",
        "description": "Transactional email template",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the template"
            },
            "name": {
                "type": "string",
                "description": "Template name or identifier",
                "maxLength": 100,
                "examples": ["welcome", "password-reset", "order-confirmation"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Template description",
                "maxLength": 500,
                "examples": ["Sent when user signs up", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Email type or category",
                "enum": ["transactional", "marketing", "notification", "system", "other", null],
                "default": "transactional",
                "examples": ["transactional", "notification", null]
            },
            "subject": {
                "type": "string",
                "description": "Email subject line (supports variables)",
                "maxLength": 500,
                "examples": ["Welcome, {{name}}!", "Reset your password"]
            },
            "subjectTemplate": {
                "type": ["string", "null"],
                "description": "Subject template with placeholder syntax",
                "maxLength": 500,
                "examples": ["Welcome, {{user.name}}!", "Order {{order.id}} confirmed", null]
            },
            "bodyHtml": {
                "type": ["string", "null"],
                "description": "HTML body content",
                "examples": ["<h1>Welcome!</h1><p>Hi {{name}},</p>...", null]
            },
            "bodyText": {
                "type": ["string", "null"],
                "description": "Plain text body content (fallback)",
                "examples": ["Welcome!\n\nHi {{name}},\n\n...", null]
            },
            "variables": {
                "type": ["array", "null"],
                "description": "Expected template variables",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": { "type": "string" },
                        "description": { "type": "string" },
                        "required": { "type": "boolean", "default": false },
                        "default": {}
                    },
                    "required": ["name"]
                },
                "examples": [[{"name": "user.name", "required": true}, {"name": "resetUrl", "required": true}], null]
            },
            "fromEmail": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Default from email address",
                "examples": ["noreply@example.com", "support@example.com", null]
            },
            "fromName": {
                "type": ["string", "null"],
                "description": "Default from display name",
                "maxLength": 100,
                "examples": ["Acme Inc", "Support Team", null]
            },
            "replyTo": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Reply-to email address",
                "examples": ["support@example.com", null]
            },
            "locale": {
                "type": ["string", "null"],
                "description": "Template locale (e.g., en-US, es)",
                "maxLength": 10,
                "examples": ["en-US", "es", "en", null]
            },
            "version": {
                "type": ["string", "null"],
                "description": "Template version for tracking",
                "maxLength": 20,
                "examples": ["v1", "2026-01", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether template is active",
                "default": true,
                "examples": [true, false]
            },
            "providerId": {
                "type": ["string", "null"],
                "description": "Template ID in email provider (SendGrid, etc.)",
                "maxLength": 100,
                "examples": ["d-abc123", "tpl_xyz", null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When template was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When template was last updated"
            }
        },
        "required": ["name", "subject", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['email', 'template', 'transactional', 'integration', 'notification', 'mail'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Integrations class templates successfully created: WebhookEvent, APICredential, OAuthToken, EmailTemplate';
END $$;
