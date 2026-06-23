-- Communication Class Templates
-- Adds communication class templates for direct messaging, threads, attachments, and chat rooms
-- These templates provide reusable patterns for messaging and chat systems

SET search_path TO odb, public;

-- =============================================================================
-- Message - Direct messaging between users
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Message',
    'Direct message between users with content, status, and metadata.',
    'communication',
    $JSON${
        "type": "object",
        "description": "Direct message between users",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the message"
            },
            "threadId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Conversation thread ID"
            },
            "senderId": {
                "type": "string",
                "format": "uuid",
                "description": "User ID of sender"
            },
            "recipientId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID of recipient (null for group messages)"
            },
            "content": {
                "type": "string",
                "description": "Message content (plain text)",
                "minLength": 1,
                "maxLength": 10000,
                "examples": ["Hello! How are you?", "Meeting at 3pm?"]
            },
            "contentHtml": {
                "type": ["string", "null"],
                "description": "Message content (HTML formatted)",
                "maxLength": 20000,
                "examples": ["<p>Hello! <strong>How are you?</strong></p>", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Message type",
                "enum": ["text", "image", "file", "system", "reply", "forward", "other", null],
                "default": "text",
                "examples": ["text", "image", "file", null]
            },
            "status": {
                "type": ["string", "null"],
                "description": "Message delivery status",
                "enum": ["pending", "sent", "delivered", "read", "failed", null],
                "default": "pending",
                "examples": ["sent", "delivered", "read", null]
            },
            "parentMessageId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent message ID (for replies)"
            },
            "forwardedFromId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Original message ID (for forwards)"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional message metadata",
                "additionalProperties": true,
                "examples": [{"clientId": "web_v1", "editCount": 0}, null]
            },
            "sentAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was sent"
            },
            "deliveredAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was delivered"
            },
            "readAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was read"
            },
            "editedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was last edited"
            },
            "deletedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was deleted (soft delete)"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When message was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When message was last updated"
            }
        },
        "required": ["senderId", "content", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['message', 'dm', 'direct', 'messaging', 'communication', 'chat'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Thread - Conversation threads
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Thread',
    'Conversation thread with participants, metadata, and last message tracking.',
    'communication',
    $JSON${
        "type": "object",
        "description": "Conversation thread",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the thread"
            },
            "type": {
                "type": ["string", "null"],
                "description": "Thread type",
                "enum": ["direct", "group", "channel", null],
                "default": "direct",
                "examples": ["direct", "group", null]
            },
            "participantIds": {
                "type": "array",
                "description": "User IDs of participants",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "minItems": 1,
                "examples": [["user-1", "user-2"], ["user-1", "user-2", "user-3"]]
            },
            "title": {
                "type": ["string", "null"],
                "description": "Thread title (for group/channel)",
                "maxLength": 255,
                "examples": ["Project Team", "Support Chat", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Thread description",
                "maxLength": 1000,
                "examples": ["Discussion for Acme project", null]
            },
            "lastMessageId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "ID of most recent message"
            },
            "lastMessageAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When last message was sent"
            },
            "lastMessagePreview": {
                "type": ["string", "null"],
                "description": "Preview of last message",
                "maxLength": 200,
                "examples": ["Hello! How are you?", "See you tomorrow", null]
            },
            "messageCount": {
                "type": ["integer", "null"],
                "description": "Total message count",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 100, null]
            },
            "unreadCount": {
                "type": ["integer", "null"],
                "description": "Unread message count (per participant)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, null]
            },
            "isArchived": {
                "type": ["boolean", "null"],
                "description": "Whether thread is archived",
                "default": false,
                "examples": [true, false, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional thread metadata",
                "additionalProperties": true,
                "examples": [{"topic": "support", "tags": ["urgent"]}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When thread was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When thread was last updated"
            }
        },
        "required": ["participantIds", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['thread', 'conversation', 'messaging', 'communication', 'chat'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- MessageAttachment - Message attachments
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'MessageAttachment',
    'Attachment on a message (file, image, link) with metadata.',
    'communication',
    $JSON${
        "type": "object",
        "description": "Message attachment",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the attachment"
            },
            "messageId": {
                "type": "string",
                "format": "uuid",
                "description": "Parent message ID"
            },
            "type": {
                "type": "string",
                "description": "Attachment type",
                "enum": ["file", "image", "video", "audio", "link", "other"],
                "examples": ["file", "image", "link"]
            },
            "filename": {
                "type": ["string", "null"],
                "description": "Original filename",
                "maxLength": 255,
                "examples": ["document.pdf", "photo.jpg", null]
            },
            "mimeType": {
                "type": ["string", "null"],
                "description": "MIME type",
                "maxLength": 100,
                "examples": ["application/pdf", "image/jpeg", "image/png", null]
            },
            "size": {
                "type": ["integer", "null"],
                "description": "File size in bytes",
                "minimum": 0,
                "examples": [1024, 1048576, null]
            },
            "url": {
                "type": "string",
                "format": "uri",
                "description": "URL to access the attachment",
                "maxLength": 2048,
                "examples": ["https://storage.example.com/attachments/abc123.pdf", "https://example.com/doc"]
            },
            "thumbnailUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Thumbnail URL (for images/videos)",
                "maxLength": 2048,
                "examples": ["https://storage.example.com/thumbs/abc123.jpg", null]
            },
            "title": {
                "type": ["string", "null"],
                "description": "Attachment title (for links)",
                "maxLength": 500,
                "examples": ["Project Brief", "Meeting Notes", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Attachment description",
                "maxLength": 1000,
                "examples": ["Q4 project overview", null]
            },
            "width": {
                "type": ["integer", "null"],
                "description": "Image/video width in pixels",
                "minimum": 1,
                "examples": [1920, 800, null]
            },
            "height": {
                "type": ["integer", "null"],
                "description": "Image/video height in pixels",
                "minimum": 1,
                "examples": [1080, 600, null]
            },
            "duration": {
                "type": ["number", "null"],
                "description": "Audio/video duration in seconds",
                "minimum": 0,
                "examples": [120.5, 30, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional attachment metadata",
                "additionalProperties": true,
                "examples": [{"storageKey": "attachments/abc123"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When attachment was created"
            }
        },
        "required": ["messageId", "type", "url", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['attachment', 'message', 'file', 'communication', 'chat', 'media'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ChatRoom - Group chat spaces
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ChatRoom',
    'Group chat room with members, settings, and metadata.',
    'communication',
    $JSON${
        "type": "object",
        "description": "Group chat room",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the chat room"
            },
            "name": {
                "type": "string",
                "description": "Room name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Engineering Team", "Project Alpha", "Support - Tier 1"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 255,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["engineering-team", "project-alpha", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Room description",
                "maxLength": 1000,
                "examples": ["Daily standups and engineering discussions", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Room type",
                "enum": ["public", "private", "direct", "channel", null],
                "default": "private",
                "examples": ["public", "private", "channel", null]
            },
            "ownerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID of room owner/admin"
            },
            "memberIds": {
                "type": "array",
                "description": "User IDs of room members",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "minItems": 0,
                "default": [],
                "examples": [["user-1", "user-2", "user-3"], []]
            },
            "threadId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated conversation thread ID"
            },
            "avatarUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Room avatar image URL"
            },
            "memberCount": {
                "type": ["integer", "null"],
                "description": "Number of members (denormalized)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 50, null]
            },
            "messageCount": {
                "type": ["integer", "null"],
                "description": "Total message count (denormalized)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 100, 1000, null]
            },
            "lastActivityAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When last message was sent"
            },
            "isArchived": {
                "type": ["boolean", "null"],
                "description": "Whether room is archived",
                "default": false,
                "examples": [true, false, null]
            },
            "settings": {
                "type": ["object", "null"],
                "description": "Room settings",
                "additionalProperties": true,
                "examples": [{"allowGuests": false, "moderation": "enabled", "historyRetentionDays": 90}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional room metadata",
                "additionalProperties": true,
                "examples": [{"projectId": "proj-123", "tags": ["engineering", "urgent"]}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When room was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When room was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['chat', 'room', 'group', 'communication', 'messaging', 'channel'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Communication class templates successfully created: Message, Thread, MessageAttachment, ChatRoom';
END $$;
