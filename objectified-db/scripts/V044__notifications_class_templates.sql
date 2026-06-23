-- Notifications Class Templates
-- Adds notification class templates for push, email, SMS, and user preference settings
-- These templates provide reusable patterns for multi-channel notification systems

SET search_path TO odb, public;

-- =============================================================================
-- PushNotification - Mobile/web push messages
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PushNotification',
    'Mobile and web push notification structure with title, body, actions, and delivery metadata.',
    'notification',
    $JSON${
        "type": "object",
        "description": "Push notification for mobile or web",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the push notification"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Recipient user ID"
            },
            "deviceToken": {
                "type": ["string", "null"],
                "description": "FCM/APNs device token or web push subscription ID",
                "maxLength": 500,
                "examples": ["fcm_token_abc...", "apns_token_xyz...", null]
            },
            "channel": {
                "type": ["string", "null"],
                "description": "Push channel",
                "enum": ["ios", "android", "web", "desktop", null],
                "examples": ["ios", "android", "web", null]
            },
            "title": {
                "type": "string",
                "description": "Notification title",
                "maxLength": 100,
                "examples": ["New message", "Order shipped", "Reminder"]
            },
            "body": {
                "type": ["string", "null"],
                "description": "Notification body text",
                "maxLength": 500,
                "examples": ["You have a new message from John", "Your order #1234 has shipped", null]
            },
            "imageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Optional image URL for rich push",
                "maxLength": 500,
                "examples": ["https://cdn.example.com/notification.jpg", null]
            },
            "iconUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Icon URL (web push)",
                "maxLength": 500,
                "examples": ["https://cdn.example.com/icon.png", null]
            },
            "badge": {
                "type": ["integer", "null"],
                "description": "Badge count (e.g., unread count)",
                "minimum": 0,
                "examples": [1, 5, 10, null]
            },
            "sound": {
                "type": ["string", "null"],
                "description": "Sound name (default, custom, or null for silent)",
                "maxLength": 100,
                "examples": ["default", "alert.wav", null]
            },
            "clickAction": {
                "type": ["string", "null"],
                "description": "URL or deep link when notification is clicked",
                "maxLength": 500,
                "examples": ["https://app.example.com/orders/123", "myapp://orders/123", null]
            },
            "data": {
                "type": ["object", "null"],
                "description": "Custom key-value payload for app handling",
                "additionalProperties": true,
                "examples": [{"orderId": "123", "screen": "OrderDetail"}, null]
            },
            "actions": {
                "type": ["array", "null"],
                "description": "Action buttons",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": { "type": "string" },
                        "title": { "type": "string" },
                        "icon": { "type": "string" }
                    },
                    "required": ["action", "title"]
                },
                "examples": [[{"action": "view", "title": "View"}, {"action": "dismiss", "title": "Dismiss"}], null]
            },
            "ttl": {
                "type": ["integer", "null"],
                "description": "Time-to-live in seconds",
                "minimum": 0,
                "examples": [3600, 86400, null]
            },
            "priority": {
                "type": ["string", "null"],
                "description": "Delivery priority",
                "enum": ["high", "normal", "low", null],
                "default": "normal",
                "examples": ["high", "normal", null]
            },
            "status": {
                "type": ["string", "null"],
                "description": "Delivery status",
                "enum": ["pending", "sent", "delivered", "failed", "clicked", null],
                "examples": ["pending", "sent", "failed", null]
            },
            "sentAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When notification was sent"
            },
            "failureReason": {
                "type": ["string", "null"],
                "description": "Error message if delivery failed",
                "maxLength": 500,
                "examples": ["Invalid token", "Token expired", null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When notification was created"
            }
        },
        "required": ["title", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['push', 'notification', 'mobile', 'web', 'fcm', 'apns'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- EmailNotification - Email-specific data
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'EmailNotification',
    'Email notification structure with recipients, subject, body, and delivery metadata.',
    'notification',
    $JSON${
        "type": "object",
        "description": "Email notification with delivery data",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the email notification"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Recipient user ID"
            },
            "to": {
                "type": "string",
                "format": "email",
                "description": "Primary recipient email address",
                "examples": ["user@example.com", "support@acme.com"]
            },
            "toName": {
                "type": ["string", "null"],
                "description": "Recipient display name",
                "maxLength": 255,
                "examples": ["John Doe", "Support Team", null]
            },
            "cc": {
                "type": ["array", "null"],
                "description": "CC recipients",
                "items": {
                    "type": "string",
                    "format": "email"
                },
                "examples": [["cc@example.com"], null]
            },
            "bcc": {
                "type": ["array", "null"],
                "description": "BCC recipients",
                "items": {
                    "type": "string",
                    "format": "email"
                },
                "examples": [["bcc@example.com"], null]
            },
            "replyTo": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Reply-to address",
                "examples": ["noreply@example.com", "support@example.com", null]
            },
            "fromEmail": {
                "type": ["string", "null"],
                "format": "email",
                "description": "From email address",
                "examples": ["noreply@example.com", null]
            },
            "fromName": {
                "type": ["string", "null"],
                "description": "From display name",
                "maxLength": 255,
                "examples": ["Acme Inc", "Support", null]
            },
            "subject": {
                "type": "string",
                "description": "Email subject",
                "maxLength": 500,
                "examples": ["Your order confirmation", "Password reset requested"]
            },
            "bodyHtml": {
                "type": ["string", "null"],
                "description": "HTML body content",
                "examples": ["<h1>Hello</h1><p>Your order...</p>", null]
            },
            "bodyText": {
                "type": ["string", "null"],
                "description": "Plain text body (fallback)",
                "examples": ["Hello,\n\nYour order...", null]
            },
            "templateId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Reference to email template used"
            },
            "templateName": {
                "type": ["string", "null"],
                "description": "Template name/identifier",
                "maxLength": 100,
                "examples": ["order-confirmation", "password-reset", null]
            },
            "templateVariables": {
                "type": ["object", "null"],
                "description": "Variables passed to template",
                "additionalProperties": true,
                "examples": [{"userName": "John", "orderId": "123"}, null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Notification type",
                "enum": ["transactional", "marketing", "system", "alert", "other", null],
                "examples": ["transactional", "system", null]
            },
            "status": {
                "type": ["string", "null"],
                "description": "Delivery status",
                "enum": ["pending", "queued", "sent", "delivered", "opened", "clicked", "bounced", "failed", null],
                "examples": ["pending", "sent", "delivered", null]
            },
            "providerId": {
                "type": ["string", "null"],
                "description": "Provider message ID (SendGrid, etc.)",
                "maxLength": 255,
                "examples": ["msg_abc123", null]
            },
            "sentAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When email was sent"
            },
            "openedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When email was first opened (if tracked)"
            },
            "clickedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When link was first clicked (if tracked)"
            },
            "bounceReason": {
                "type": ["string", "null"],
                "description": "Bounce reason if delivery failed",
                "maxLength": 500,
                "examples": ["Invalid address", "Mailbox full", null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When notification was created"
            }
        },
        "required": ["to", "subject", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['email', 'notification', 'mail', 'transactional', 'delivery'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- SMSNotification - Text message data
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'SMSNotification',
    'SMS/text message notification structure with recipient, content, and delivery metadata.',
    'notification',
    $JSON${
        "type": "object",
        "description": "SMS text message notification",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the SMS notification"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Recipient user ID"
            },
            "to": {
                "type": "string",
                "description": "Recipient phone number (E.164 format)",
                "pattern": "^\\+[1-9]\\d{1,14}$",
                "maxLength": 20,
                "examples": ["+15551234567", "+442071234567"]
            },
            "message": {
                "type": "string",
                "description": "SMS body text",
                "minLength": 1,
                "maxLength": 1600,
                "examples": ["Your verification code is 123456", "Your order has shipped. Track: https://..."]
            },
            "segmentCount": {
                "type": ["integer", "null"],
                "description": "Number of SMS segments (160 chars each for GSM-7)",
                "minimum": 1,
                "examples": [1, 2, 3, null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Message type",
                "enum": ["transactional", "promotional", "verification", "alert", "other", null],
                "examples": ["verification", "transactional", null]
            },
            "status": {
                "type": ["string", "null"],
                "description": "Delivery status",
                "enum": ["pending", "queued", "sent", "delivered", "failed", "undelivered", null],
                "examples": ["pending", "sent", "delivered", null]
            },
            "providerId": {
                "type": ["string", "null"],
                "description": "Provider message SID (Twilio, etc.)",
                "maxLength": 100,
                "examples": ["SM1234567890", null]
            },
            "providerStatus": {
                "type": ["string", "null"],
                "description": "Raw status from provider",
                "maxLength": 50,
                "examples": ["queued", "sent", "delivered", null]
            },
            "sentAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When SMS was sent"
            },
            "deliveredAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When SMS was delivered (if available)"
            },
            "failureReason": {
                "type": ["string", "null"],
                "description": "Error code or message if delivery failed",
                "maxLength": 500,
                "examples": ["Invalid number", "Unsubscribed", null]
            },
            "failureCode": {
                "type": ["string", "null"],
                "description": "Provider error code",
                "maxLength": 50,
                "examples": ["21614", "30003", null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When notification was created"
            }
        },
        "required": ["to", "message", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['sms', 'text', 'notification', 'mobile', 'twilio', 'messaging'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- NotificationPreference - User opt-in/opt-out settings
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'NotificationPreference',
    'User notification opt-in/opt-out preferences per channel and category.',
    'notification',
    $JSON${
        "type": "object",
        "description": "User notification preference settings",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the preference record"
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "User ID these preferences belong to"
            },
            "channel": {
                "type": "string",
                "description": "Notification channel",
                "enum": ["email", "push", "sms", "in_app", "webhook"],
                "examples": ["email", "push", "sms"]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Notification category or type",
                "maxLength": 100,
                "examples": ["marketing", "transactional", "alerts", "product_updates", null]
            },
            "isEnabled": {
                "type": "boolean",
                "description": "Whether user has opted in to this channel/category",
                "default": true,
                "examples": [true, false]
            },
            "optedInAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When user opted in"
            },
            "optedOutAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When user opted out"
            },
            "quietHoursStart": {
                "type": ["string", "null"],
                "description": "Start of quiet hours (no notifications) - local time HH:mm",
                "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$",
                "maxLength": 5,
                "examples": ["22:00", "21:30", null]
            },
            "quietHoursEnd": {
                "type": ["string", "null"],
                "description": "End of quiet hours - local time HH:mm",
                "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$",
                "maxLength": 5,
                "examples": ["08:00", "09:00", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "User timezone for quiet hours",
                "maxLength": 50,
                "examples": ["America/New_York", "Europe/London", null]
            },
            "frequency": {
                "type": ["string", "null"],
                "description": "Preferred frequency (for digest-style)",
                "enum": ["immediate", "daily", "weekly", "never", null],
                "examples": ["immediate", "daily", null]
            },
            "digestDay": {
                "type": ["string", "null"],
                "description": "Day for weekly digest (0=Sunday, 6=Saturday)",
                "enum": ["0", "1", "2", "3", "4", "5", "6", null],
                "examples": ["0", "1", null]
            },
            "digestTime": {
                "type": ["string", "null"],
                "description": "Time for digest - HH:mm",
                "pattern": "^([01]?[0-9]|2[0-3]):[0-5][0-9]$",
                "maxLength": 5,
                "examples": ["09:00", "18:00", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional channel-specific preferences",
                "additionalProperties": true,
                "examples": [{"topics": ["orders", "shipping"]}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When preference was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When preference was last updated"
            }
        },
        "required": ["userId", "channel", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['notification', 'preference', 'opt-in', 'opt-out', 'consent', 'settings'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Notifications class templates successfully created: PushNotification, EmailNotification, SMSNotification, NotificationPreference';
END $$;
