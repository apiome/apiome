-- Security Class Templates
-- Adds security class templates for sessions, API keys, security events, IP whitelisting, and rate limiting
-- These templates provide reusable patterns for authentication, authorization, and security monitoring

SET search_path TO apiome, public;

-- =============================================================================
-- Session - User session management
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Session',
    'User session management with tokens, expiration, and device tracking.',
    'security',
    $JSON${
        "type": "object",
        "description": "User session",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the session"
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "User ID"
            },
            "sessionToken": {
                "type": ["string", "null"],
                "description": "Session token (hashed in storage)",
                "maxLength": 500,
                "examples": ["sess_abc123...", null]
            },
            "sessionTokenHash": {
                "type": ["string", "null"],
                "description": "Hashed session token for verification",
                "maxLength": 255,
                "examples": ["sha256:...", null]
            },
            "refreshToken": {
                "type": ["string", "null"],
                "description": "Refresh token (hashed in storage)",
                "maxLength": 500,
                "examples": ["refresh_xyz...", null]
            },
            "refreshTokenHash": {
                "type": ["string", "null"],
                "description": "Hashed refresh token",
                "maxLength": 255,
                "examples": ["sha256:...", null]
            },
            "expiresAt": {
                "type": "string",
                "format": "date-time",
                "description": "When session expires"
            },
            "refreshExpiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When refresh token expires"
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address when session was created",
                "maxLength": 45,
                "examples": ["192.168.1.1", "2001:db8::1", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent string",
                "maxLength": 500,
                "examples": ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...", null]
            },
            "deviceType": {
                "type": ["string", "null"],
                "description": "Device type",
                "enum": ["desktop", "mobile", "tablet", "unknown", null],
                "examples": ["desktop", "mobile", null]
            },
            "browser": {
                "type": ["string", "null"],
                "description": "Browser name",
                "maxLength": 100,
                "examples": ["Chrome", "Safari", "Firefox", null]
            },
            "os": {
                "type": ["string", "null"],
                "description": "Operating system",
                "maxLength": 100,
                "examples": ["Mac OS", "Windows", "iOS", null]
            },
            "location": {
                "type": ["string", "null"],
                "description": "Geographic location",
                "maxLength": 255,
                "examples": ["San Francisco, CA", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether session is active",
                "default": true,
                "examples": [true, false]
            },
            "revokedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When session was revoked"
            },
            "lastActiveAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Last activity timestamp"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When session was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When session was last updated"
            }
        },
        "required": ["userId", "expiresAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['session', 'auth', 'user', 'token', 'security', 'login'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- APIKeyAuth - API authentication tokens (enhanced)
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'APIKeyAuth',
    'API authentication key/token with scopes, rate limits, and usage tracking.',
    'security',
    $JSON${
        "type": "object",
        "description": "API key for authentication",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the API key"
            },
            "name": {
                "type": "string",
                "description": "Key name or description",
                "maxLength": 255,
                "examples": ["Production API", "Mobile App", "Partner Integration"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Key purpose or usage",
                "maxLength": 500,
                "examples": ["API key for production mobile app", null]
            },
            "keyPrefix": {
                "type": ["string", "null"],
                "description": "Visible key prefix for identification (e.g., first 8 chars)",
                "maxLength": 20,
                "examples": ["sk_live_ab", "pk_test_xy", null]
            },
            "keyHash": {
                "type": ["string", "null"],
                "description": "Hashed key value (never store raw key)",
                "maxLength": 255,
                "examples": ["sha256:...", null]
            },
            "scopes": {
                "type": ["array", "null"],
                "description": "Granted permission scopes",
                "items": {
                    "type": "string",
                    "maxLength": 100
                },
                "examples": [["read", "write"], ["orders:read", "products:write"], null]
            },
            "permissions": {
                "type": ["array", "null"],
                "description": "Granted permissions (alternative to scopes)",
                "items": {
                    "type": "string"
                },
                "examples": [["read", "write"], null]
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When key expires"
            },
            "lastUsedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When key was last used"
            },
            "usageCount": {
                "type": ["integer", "null"],
                "description": "Total number of requests with this key",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1000, 10000, null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether key is active",
                "default": true,
                "examples": [true, false]
            },
            "ipWhitelist": {
                "type": ["array", "null"],
                "description": "Allowed IP addresses or CIDR ranges",
                "items": {
                    "type": "string",
                    "maxLength": 45
                },
                "examples": [["192.168.1.0/24", "10.0.0.1"], null]
            },
            "rateLimit": {
                "type": ["integer", "null"],
                "description": "Requests per minute limit",
                "minimum": 1,
                "examples": [60, 1000, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"environment": "production", "app": "mobile"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When key was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When key was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['api', 'key', 'auth', 'security', 'token', 'authentication'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- SecurityEvent - Login attempts, suspicious activity
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'SecurityEvent',
    'Security event log for login attempts, failures, and suspicious activity.',
    'security',
    $JSON${
        "type": "object",
        "description": "Security event (login, failure, suspicious activity)",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the event"
            },
            "eventType": {
                "type": "string",
                "description": "Type of security event",
                "enum": ["login", "login_failed", "logout", "password_change", "password_reset", "mfa_success", "mfa_failed", "account_lockout", "suspicious_activity", "brute_force", "unauthorized_access", "session_revoked", "api_key_compromised", "other"],
                "examples": ["login", "login_failed", "suspicious_activity"]
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null for failed login with unknown user)"
            },
            "username": {
                "type": ["string", "null"],
                "description": "Username or identifier attempted",
                "maxLength": 255,
                "examples": ["user@example.com", "john_doe", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address of request",
                "maxLength": 45,
                "examples": ["192.168.1.1", "2001:db8::1", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent string",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "success": {
                "type": "boolean",
                "description": "Whether the action succeeded",
                "examples": [true, false]
            },
            "failureReason": {
                "type": ["string", "null"],
                "description": "Reason for failure",
                "maxLength": 500,
                "examples": ["Invalid password", "Account locked", "Invalid MFA code", null]
            },
            "failureCode": {
                "type": ["string", "null"],
                "description": "Failure code",
                "maxLength": 50,
                "examples": ["invalid_credentials", "account_locked", null]
            },
            "severity": {
                "type": ["string", "null"],
                "description": "Event severity",
                "enum": ["low", "medium", "high", "critical", null],
                "examples": ["low", "high", "critical", null]
            },
            "isSuspicious": {
                "type": ["boolean", "null"],
                "description": "Whether event was flagged as suspicious",
                "default": false,
                "examples": [true, false, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional event metadata",
                "additionalProperties": true,
                "examples": [{"attemptCount": 5, "location": "Unknown"}, null]
            },
            "resource": {
                "type": ["string", "null"],
                "description": "Resource accessed (e.g., endpoint, API path)",
                "maxLength": 500,
                "examples": ["/api/users", "/login", null]
            },
            "requestId": {
                "type": ["string", "null"],
                "description": "Request/correlation ID",
                "maxLength": 100,
                "examples": ["req_abc123", null]
            },
            "occurredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When event occurred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When event was recorded"
            }
        },
        "required": ["eventType", "success", "occurredAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['security', 'event', 'audit', 'login', 'auth', 'monitoring'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- IPWhitelist - Allowed IP addresses
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'IPWhitelist',
    'IP whitelist entry for allowed addresses or CIDR ranges.',
    'security',
    $JSON${
        "type": "object",
        "description": "IP whitelist entry",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the whitelist entry"
            },
            "name": {
                "type": ["string", "null"],
                "description": "Entry name or description",
                "maxLength": 255,
                "examples": ["Office Network", "API Gateway", "Partner A", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "Single IP address (IPv4 or IPv6)",
                "maxLength": 45,
                "examples": ["192.168.1.1", "2001:db8::1", null]
            },
            "cidr": {
                "type": ["string", "null"],
                "description": "CIDR range (e.g., 192.168.1.0/24)",
                "maxLength": 50,
                "pattern": "^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}/[0-9]{1,2}$|^[0-9a-f:]+/[0-9]{1,3}$",
                "examples": ["192.168.1.0/24", "10.0.0.0/8", "2001:db8::/32", null]
            },
            "rangeStart": {
                "type": ["string", "null"],
                "description": "Start of IP range (when not using CIDR)",
                "maxLength": 45,
                "examples": ["192.168.1.1", null]
            },
            "rangeEnd": {
                "type": ["string", "null"],
                "description": "End of IP range (when not using CIDR)",
                "maxLength": 45,
                "examples": ["192.168.1.254", null]
            },
            "scope": {
                "type": ["string", "null"],
                "description": "Scope of whitelist (global, API, admin, etc.)",
                "maxLength": 100,
                "examples": ["global", "api", "admin", "webhook", null]
            },
            "resourceType": {
                "type": ["string", "null"],
                "description": "Resource this whitelist applies to",
                "maxLength": 100,
                "examples": ["api_key", "user", "webhook", null]
            },
            "resourceId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Specific resource ID (e.g., API key ID)"
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether entry is active",
                "default": true,
                "examples": [true, false]
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When whitelist entry expires"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"partner": "Partner A", "notes": "Temporary access"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When entry was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When entry was last updated"
            }
        },
        "required": ["createdAt"]
    }$JSON$::jsonb,
    ARRAY['ip', 'whitelist', 'security', 'access', 'firewall', 'network'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- RateLimit - API throttling configuration
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'RateLimit',
    'Rate limit configuration for API throttling and request quotas.',
    'security',
    $JSON${
        "type": "object",
        "description": "Rate limit configuration",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the rate limit config"
            },
            "name": {
                "type": ["string", "null"],
                "description": "Rate limit name or description",
                "maxLength": 255,
                "examples": ["Default API", "Strict Tier", "Partner API", null]
            },
            "scope": {
                "type": ["string", "null"],
                "description": "Scope (global, per-user, per-key, per-IP, endpoint)",
                "enum": ["global", "user", "api_key", "ip", "endpoint", "tenant", null],
                "examples": ["api_key", "ip", "user", null]
            },
            "resourceType": {
                "type": ["string", "null"],
                "description": "Resource type this limit applies to",
                "maxLength": 100,
                "examples": ["api", "login", "webhook", null]
            },
            "resourceId": {
                "type": ["string", "null"],
                "description": "Specific resource (endpoint path, etc.)",
                "maxLength": 500,
                "examples": ["/api/*", "/api/orders", "/login", null]
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of requests allowed",
                "minimum": 1,
                "examples": [60, 1000, 10000]
            },
            "window": {
                "type": "integer",
                "description": "Time window in seconds",
                "minimum": 1,
                "examples": [60, 3600, 86400]
            },
            "windowUnit": {
                "type": ["string", "null"],
                "description": "Window unit (alternative to window in seconds)",
                "enum": ["second", "minute", "hour", "day", null],
                "examples": ["minute", "hour", "day", null]
            },
            "burst": {
                "type": ["integer", "null"],
                "description": "Burst limit (additional requests allowed in short burst)",
                "minimum": 0,
                "examples": [10, 100, null]
            },
            "strategy": {
                "type": ["string", "null"],
                "description": "Rate limiting strategy",
                "enum": ["fixed_window", "sliding_window", "token_bucket", "leaky_bucket", null],
                "default": "fixed_window",
                "examples": ["fixed_window", "sliding_window", null]
            },
            "exceedAction": {
                "type": ["string", "null"],
                "description": "Action when limit exceeded",
                "enum": ["reject", "queue", "throttle", "log_only", null],
                "default": "reject",
                "examples": ["reject", "throttle", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether rate limit is active",
                "default": true,
                "examples": [true, false]
            },
            "priority": {
                "type": ["integer", "null"],
                "description": "Priority when multiple limits apply (higher = evaluated first)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 100, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"tier": "free", "plan": "basic"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When config was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When config was last updated"
            }
        },
        "required": ["limit", "window", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['rate', 'limit', 'throttle', 'api', 'security', 'quota'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Security class templates successfully created: Session, APIKeyAuth, SecurityEvent, IPWhitelist, RateLimit';
END $$;
