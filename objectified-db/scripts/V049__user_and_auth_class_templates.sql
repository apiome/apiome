-- User and Auth Class Templates
-- Adds user and authentication class templates for profiles, roles, permissions, 2FA, and password reset
-- These templates provide reusable patterns for user management and access control

SET search_path TO odb, public;

-- =============================================================================
-- EnhancedUserProfile - Extended user information (enhanced version)
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'EnhancedUserProfile',
    'Enhanced user profile with social links, preferences, and extended metadata.',
    'user',
    $JSON${
        "type": "object",
        "description": "Enhanced user profile information",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the profile"
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "Reference to user"
            },
            "bio": {
                "type": ["string", "null"],
                "description": "User biography",
                "maxLength": 1000,
                "examples": ["Software developer passionate about clean code", null]
            },
            "website": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Personal website URL",
                "examples": ["https://johndoe.com", null]
            },
            "location": {
                "type": ["string", "null"],
                "description": "Geographic location",
                "maxLength": 255,
                "examples": ["San Francisco, CA", "London, UK", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "User timezone (IANA identifier)",
                "maxLength": 50,
                "examples": ["America/New_York", "Europe/London", null]
            },
            "language": {
                "type": ["string", "null"],
                "description": "Preferred language code (ISO 639-1)",
                "maxLength": 10,
                "examples": ["en", "es", "fr", null]
            },
            "dateOfBirth": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Date of birth"
            },
            "phoneNumber": {
                "type": ["string", "null"],
                "description": "Phone number",
                "maxLength": 50,
                "examples": ["+1-555-123-4567", null]
            },
            "socialLinks": {
                "type": ["object", "null"],
                "description": "Social media links",
                "additionalProperties": true,
                "examples": [{"twitter": "@johndoe", "github": "johndoe", "linkedin": "in/johndoe"}, null]
            },
            "avatarUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Profile avatar image URL"
            },
            "coverImageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Profile cover image URL"
            },
            "preferences": {
                "type": ["object", "null"],
                "description": "User preferences",
                "additionalProperties": true,
                "examples": [{"theme": "dark", "notifications": true}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional profile metadata",
                "additionalProperties": true,
                "examples": [{"customField": "value"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When profile was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When profile was last updated"
            }
        },
        "required": ["userId", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['user', 'profile', 'personal', 'social', 'preferences'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Role - RBAC role definitions
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Role',
    'Role-based access control (RBAC) role definition with permissions and hierarchy.',
    'user',
    $JSON${
        "type": "object",
        "description": "RBAC role definition",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the role"
            },
            "name": {
                "type": "string",
                "description": "Role name",
                "maxLength": 100,
                "minLength": 1,
                "examples": ["admin", "editor", "viewer", "customer"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 100,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["admin", "editor", "viewer", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Role description",
                "maxLength": 500,
                "examples": ["Full system access", "Can edit content", null]
            },
            "permissions": {
                "type": ["array", "null"],
                "description": "Array of permission IDs or names",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "permissionNames": {
                "type": ["array", "null"],
                "description": "Array of permission names (alternative to permission IDs)",
                "items": {
                    "type": "string",
                    "maxLength": 100
                },
                "examples": [["users:read", "users:write", "orders:read"], null]
            },
            "parentRoleId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent role ID for role hierarchy"
            },
            "isSystem": {
                "type": ["boolean", "null"],
                "description": "Whether this is a system role (cannot be deleted)",
                "default": false,
                "examples": [true, false, null]
            },
            "isDefault": {
                "type": ["boolean", "null"],
                "description": "Whether this is the default role for new users",
                "default": false,
                "examples": [true, false, null]
            },
            "priority": {
                "type": ["integer", "null"],
                "description": "Role priority/level (higher = more permissions)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 100, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional role metadata",
                "additionalProperties": true,
                "examples": [{"color": "#3B82F6"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When role was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When role was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['role', 'rbac', 'permission', 'access', 'authorization', 'user'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Permission - Granular access controls
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Permission',
    'Granular permission definition for fine-grained access control.',
    'user',
    $JSON${
        "type": "object",
        "description": "Permission definition",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the permission"
            },
            "name": {
                "type": "string",
                "description": "Permission name (e.g., users:read, orders:write)",
                "maxLength": 100,
                "minLength": 1,
                "examples": ["users:read", "orders:write", "admin:all"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 100,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["users-read", "orders-write", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Permission description",
                "maxLength": 500,
                "examples": ["Read user data", "Create and update orders", null]
            },
            "resource": {
                "type": ["string", "null"],
                "description": "Resource this permission applies to",
                "maxLength": 100,
                "examples": ["users", "orders", "products", null]
            },
            "action": {
                "type": ["string", "null"],
                "description": "Action allowed",
                "enum": ["read", "write", "create", "update", "delete", "execute", "all", null],
                "examples": ["read", "write", "all", null]
            },
            "conditions": {
                "type": ["object", "null"],
                "description": "Additional conditions for permission (e.g., own resources only)",
                "additionalProperties": true,
                "examples": [{"ownOnly": true, "status": "active"}, null]
            },
            "isSystem": {
                "type": ["boolean", "null"],
                "description": "Whether this is a system permission (cannot be deleted)",
                "default": false,
                "examples": [true, false, null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Permission category for organization",
                "maxLength": 100,
                "examples": ["users", "orders", "admin", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional permission metadata",
                "additionalProperties": true,
                "examples": [{"group": "user-management"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When permission was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When permission was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['permission', 'access', 'control', 'authorization', 'rbac', 'user'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- TwoFactorAuth - 2FA configuration
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'TwoFactorAuth',
    'Two-factor authentication configuration and backup codes.',
    'user',
    $JSON${
        "type": "object",
        "description": "Two-factor authentication configuration",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the 2FA record"
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "User ID"
            },
            "method": {
                "type": "string",
                "description": "2FA method",
                "enum": ["totp", "sms", "email", "app", "hardware_key"],
                "examples": ["totp", "sms", "app"]
            },
            "isEnabled": {
                "type": "boolean",
                "description": "Whether 2FA is enabled",
                "default": false,
                "examples": [true, false]
            },
            "secret": {
                "type": ["string", "null"],
                "description": "Encrypted TOTP secret (never store unencrypted)",
                "maxLength": 500,
                "examples": ["encrypted_secret_ref", null]
            },
            "secretRef": {
                "type": ["string", "null"],
                "description": "Reference to encrypted secret in secure store",
                "maxLength": 500,
                "examples": ["vault:secret/data/2fa#secret", null]
            },
            "phoneNumber": {
                "type": ["string", "null"],
                "description": "Phone number for SMS 2FA",
                "maxLength": 50,
                "examples": ["+1-555-123-4567", null]
            },
            "email": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Email for email 2FA",
                "examples": ["user@example.com", null]
            },
            "backupCodes": {
                "type": ["array", "null"],
                "description": "Backup codes (hashed in storage)",
                "items": {
                    "type": "string",
                    "maxLength": 100
                },
                "examples": [[], null]
            },
            "backupCodesHash": {
                "type": ["array", "null"],
                "description": "Hashed backup codes",
                "items": {
                    "type": "string",
                    "maxLength": 255
                },
                "examples": [[], null]
            },
            "recoveryCodes": {
                "type": ["array", "null"],
                "description": "Recovery codes (hashed in storage)",
                "items": {
                    "type": "string",
                    "maxLength": 100
                },
                "examples": [[], null]
            },
            "lastUsedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When 2FA was last used"
            },
            "enabledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When 2FA was enabled"
            },
            "disabledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When 2FA was disabled"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional 2FA metadata",
                "additionalProperties": true,
                "examples": [{"deviceName": "iPhone 12"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When 2FA was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When 2FA was last updated"
            }
        },
        "required": ["userId", "method", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['2fa', 'two-factor', 'mfa', 'auth', 'security', 'user'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- PasswordReset - Password recovery tokens
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PasswordReset',
    'Password reset token and recovery request tracking.',
    'user',
    $JSON${
        "type": "object",
        "description": "Password reset token and request",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the reset request"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null if email not found)"
            },
            "email": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Email address for reset (for privacy, may not match user email)",
                "examples": ["user@example.com", null]
            },
            "token": {
                "type": ["string", "null"],
                "description": "Reset token (hashed in storage)",
                "maxLength": 500,
                "examples": ["reset_token_abc123...", null]
            },
            "tokenHash": {
                "type": ["string", "null"],
                "description": "Hashed reset token for verification",
                "maxLength": 255,
                "examples": ["sha256:...", null]
            },
            "status": {
                "type": "string",
                "description": "Reset request status",
                "enum": ["pending", "used", "expired", "revoked"],
                "default": "pending",
                "examples": ["pending", "used", "expired"]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address of reset request",
                "maxLength": 45,
                "examples": ["192.168.1.1", "2001:db8::1", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent of reset request",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "expiresAt": {
                "type": "string",
                "format": "date-time",
                "description": "When reset token expires"
            },
            "usedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When token was used"
            },
            "revokedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When token was revoked"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When reset request was created"
            }
        },
        "required": ["status", "expiresAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['password', 'reset', 'recovery', 'token', 'auth', 'user', 'security'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'User and Auth class templates successfully created: EnhancedUserProfile, Role, Permission, TwoFactorAuth, PasswordReset';
END $$;
