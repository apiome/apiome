-- Support Class Templates
-- Adds support class templates for tickets, comments, SLAs, and knowledge base
-- These templates provide reusable patterns for customer support systems

SET search_path TO odb, public;

-- =============================================================================
-- Ticket - Customer support tickets
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Ticket',
    'Customer support ticket with priority, status, and assignment tracking.',
    'support',
    $JSON${
        "type": "object",
        "description": "Customer support ticket",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the ticket"
            },
            "ticketNumber": {
                "type": ["string", "null"],
                "description": "Human-readable ticket number",
                "maxLength": 100,
                "examples": ["TKT-2026-001", "T123456", null]
            },
            "subject": {
                "type": "string",
                "description": "Ticket subject/title",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Unable to login", "Payment issue", "Feature request"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Detailed ticket description",
                "maxLength": 10000,
                "examples": ["I cannot log into my account. Getting error message when entering password.", null]
            },
            "status": {
                "type": "string",
                "description": "Ticket status",
                "enum": ["open", "in_progress", "waiting_customer", "waiting_agent", "resolved", "closed", "cancelled"],
                "default": "open",
                "examples": ["open", "in_progress", "resolved"]
            },
            "priority": {
                "type": ["string", "null"],
                "description": "Ticket priority",
                "enum": ["low", "normal", "high", "urgent", "critical", null],
                "default": "normal",
                "examples": ["normal", "high", "urgent", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Ticket type",
                "enum": ["question", "bug", "feature_request", "complaint", "compliment", "other", null],
                "examples": ["question", "bug", "feature_request", null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Ticket category",
                "maxLength": 100,
                "examples": ["billing", "technical", "account", "product", null]
            },
            "subcategory": {
                "type": ["string", "null"],
                "description": "Ticket subcategory",
                "maxLength": 100,
                "examples": ["payment", "refund", "login", "password", null]
            },
            "customerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Customer user ID"
            },
            "customerEmail": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Customer email (if not registered user)"
            },
            "assignedTo": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Assigned agent/support user ID"
            },
            "assignedTeam": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Assigned team ID"
            },
            "slaId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated SLA ID"
            },
            "firstResponseAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When first response was sent"
            },
            "firstResponseDueAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "SLA deadline for first response"
            },
            "resolvedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When ticket was resolved"
            },
            "resolvedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who resolved the ticket"
            },
            "resolution": {
                "type": ["string", "null"],
                "description": "Resolution summary",
                "maxLength": 2000,
                "examples": ["Issue resolved by resetting password", null]
            },
            "closedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When ticket was closed"
            },
            "closedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who closed the ticket"
            },
            "source": {
                "type": ["string", "null"],
                "description": "Ticket source",
                "enum": ["email", "web", "chat", "phone", "api", "social", "other", null],
                "examples": ["email", "web", "chat", null]
            },
            "tags": {
                "type": ["array", "null"],
                "description": "Ticket tags",
                "items": {
                    "type": "string",
                    "maxLength": 50
                },
                "examples": [["urgent", "billing"], ["bug", "v2.0"], null]
            },
            "customFields": {
                "type": ["object", "null"],
                "description": "Custom ticket fields",
                "additionalProperties": true,
                "examples": [{"orderNumber": "ORD-123", "productVersion": "2.1.0"}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional ticket metadata",
                "additionalProperties": true,
                "examples": [{"escalated": true, "vip": false}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When ticket was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When ticket was last updated"
            }
        },
        "required": ["subject", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['ticket', 'support', 'customer-service', 'help-desk', 'issue'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- TicketComment - Support conversation
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'TicketComment',
    'Support ticket comment/response in conversation thread.',
    'support',
    $JSON${
        "type": "object",
        "description": "Support ticket comment",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the comment"
            },
            "ticketId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated ticket ID"
            },
            "authorId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Comment author user ID"
            },
            "authorEmail": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Author email (if not registered user)"
            },
            "authorName": {
                "type": ["string", "null"],
                "description": "Author display name",
                "maxLength": 255,
                "examples": ["John Doe", "Support Agent", null]
            },
            "isInternal": {
                "type": ["boolean", "null"],
                "description": "Whether comment is internal (not visible to customer)",
                "default": false,
                "examples": [true, false, null]
            },
            "isAgent": {
                "type": ["boolean", "null"],
                "description": "Whether author is support agent",
                "default": false,
                "examples": [true, false, null]
            },
            "content": {
                "type": "string",
                "description": "Comment content",
                "minLength": 1,
                "maxLength": 10000,
                "examples": ["Thank you for contacting us. We are looking into this issue."]
            },
            "contentType": {
                "type": ["string", "null"],
                "description": "Content type",
                "enum": ["text", "html", "markdown", null],
                "default": "text",
                "examples": ["text", "html", "markdown", null]
            },
            "attachments": {
                "type": ["array", "null"],
                "description": "Attachment URLs or IDs",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": { "type": "string", "format": "uuid" },
                        "url": { "type": "string", "format": "uri" },
                        "filename": { "type": "string" },
                        "mimeType": { "type": "string" },
                        "size": { "type": "integer", "minimum": 0 }
                    },
                    "required": ["url", "filename"]
                },
                "examples": [[{"url": "https://...", "filename": "screenshot.png", "mimeType": "image/png", "size": 102400}], null]
            },
            "parentCommentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent comment ID (for threading)"
            },
            "statusChange": {
                "type": ["string", "null"],
                "description": "Status change triggered by this comment",
                "enum": ["open", "in_progress", "waiting_customer", "waiting_agent", "resolved", "closed", null],
                "examples": ["resolved", "in_progress", null]
            },
            "priorityChange": {
                "type": ["string", "null"],
                "description": "Priority change triggered by this comment",
                "enum": ["low", "normal", "high", "urgent", "critical", null],
                "examples": ["high", "urgent", null]
            },
            "isRead": {
                "type": ["boolean", "null"],
                "description": "Whether comment has been read",
                "default": false,
                "examples": [true, false, null]
            },
            "readAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When comment was read"
            },
            "readBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who read the comment"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional comment metadata",
                "additionalProperties": true,
                "examples": [{"edited": true, "editCount": 2}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When comment was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When comment was last updated"
            }
        },
        "required": ["ticketId", "content", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['comment', 'ticket', 'support', 'conversation', 'response'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- SLA - Service level agreements
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'SLA',
    'Service level agreement with response and resolution time targets.',
    'support',
    $JSON${
        "type": "object",
        "description": "Service level agreement",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the SLA"
            },
            "name": {
                "type": "string",
                "description": "SLA name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Standard Support", "Premium Support", "Enterprise SLA"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "SLA description",
                "maxLength": 2000,
                "examples": ["Standard support SLA with 24-hour response time", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether SLA is active",
                "default": true,
                "examples": [true, false]
            },
            "isDefault": {
                "type": ["boolean", "null"],
                "description": "Whether this is the default SLA",
                "default": false,
                "examples": [true, false, null]
            },
            "firstResponseTime": {
                "type": ["integer", "null"],
                "description": "First response time target (minutes)",
                "minimum": 0,
                "examples": [60, 240, 1440, null]
            },
            "firstResponseTimeBusinessHours": {
                "type": ["boolean", "null"],
                "description": "Whether first response time is business hours only",
                "default": false,
                "examples": [true, false, null]
            },
            "resolutionTime": {
                "type": ["integer", "null"],
                "description": "Resolution time target (minutes)",
                "minimum": 0,
                "examples": [480, 2880, 10080, null]
            },
            "resolutionTimeBusinessHours": {
                "type": ["boolean", "null"],
                "description": "Whether resolution time is business hours only",
                "default": false,
                "examples": [true, false, null]
            },
            "businessHours": {
                "type": ["object", "null"],
                "description": "Business hours definition",
                "properties": {
                    "timezone": { "type": "string" },
                    "days": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "day": { "type": "string", "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] },
                                "start": { "type": "string", "pattern": "^([0-1][0-9]|2[0-3]):[0-5][0-9]$" },
                                "end": { "type": "string", "pattern": "^([0-1][0-9]|2[0-3]):[0-5][0-9]$" },
                                "isOpen": { "type": "boolean", "default": true }
                            },
                            "required": ["day", "start", "end"]
                        }
                    }
                },
                "examples": [{"timezone": "America/New_York", "days": [{"day": "monday", "start": "09:00", "end": "17:00", "isOpen": true}, {"day": "tuesday", "start": "09:00", "end": "17:00", "isOpen": true}]}, null]
            },
            "appliesTo": {
                "type": ["string", "null"],
                "description": "What SLA applies to",
                "enum": ["all", "priority", "type", "category", "customer", null],
                "examples": ["all", "priority", "type", null]
            },
            "priorityLevels": {
                "type": ["array", "null"],
                "description": "Priority levels this SLA applies to",
                "items": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent", "critical"]
                },
                "examples": [["normal", "high"], ["urgent", "critical"], null]
            },
            "ticketTypes": {
                "type": ["array", "null"],
                "description": "Ticket types this SLA applies to",
                "items": {
                    "type": "string",
                    "enum": ["question", "bug", "feature_request", "complaint", "compliment", "other"]
                },
                "examples": [["question", "bug"], null]
            },
            "categories": {
                "type": ["array", "null"],
                "description": "Ticket categories this SLA applies to",
                "items": {
                    "type": "string"
                },
                "examples": [["billing", "technical"], null]
            },
            "customerIds": {
                "type": ["array", "null"],
                "description": "Customer IDs this SLA applies to (null = all)",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "escalationRules": {
                "type": ["array", "null"],
                "description": "Escalation rules",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger": { "type": "string", "enum": ["first_response_breach", "resolution_breach", "time_elapsed"] },
                        "timeMinutes": { "type": "integer", "minimum": 0 },
                        "action": { "type": "string", "enum": ["notify", "assign", "escalate", "change_priority"] },
                        "target": { "type": ["string", "null"] }
                    },
                    "required": ["trigger", "action"]
                },
                "examples": [[{"trigger": "first_response_breach", "timeMinutes": 0, "action": "escalate", "target": "manager"}], null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional SLA metadata",
                "additionalProperties": true,
                "examples": [{"contractId": "CTR-123", "renewalDate": "2026-12-31"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When SLA was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When SLA was last updated"
            }
        },
        "required": ["name", "isActive", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['sla', 'service-level', 'support', 'agreement', 'response-time'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- KnowledgeBase - Help documentation
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'KnowledgeBase',
    'Knowledge base article for help documentation and FAQs.',
    'support',
    $JSON${
        "type": "object",
        "description": "Knowledge base article",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the article"
            },
            "title": {
                "type": "string",
                "description": "Article title",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["How to reset your password", "Getting started guide", "Troubleshooting login issues"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 255,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["how-to-reset-password", "getting-started", null]
            },
            "content": {
                "type": ["string", "null"],
                "description": "Article content (HTML, Markdown, etc.)",
                "maxLength": 100000,
                "examples": ["<p>To reset your password...</p>", null]
            },
            "contentType": {
                "type": ["string", "null"],
                "description": "Content type",
                "enum": ["html", "markdown", "text", null],
                "default": "html",
                "examples": ["html", "markdown", "text", null]
            },
            "excerpt": {
                "type": ["string", "null"],
                "description": "Article excerpt/summary",
                "maxLength": 500,
                "examples": ["Learn how to reset your password in a few simple steps", null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Article category",
                "maxLength": 100,
                "examples": ["getting-started", "billing", "technical", "troubleshooting", null]
            },
            "subcategory": {
                "type": ["string", "null"],
                "description": "Article subcategory",
                "maxLength": 100,
                "examples": ["password", "payment", "api", null]
            },
            "status": {
                "type": "string",
                "description": "Article status",
                "enum": ["draft", "published", "archived", "review"],
                "default": "draft",
                "examples": ["draft", "published", "archived"]
            },
            "isFeatured": {
                "type": ["boolean", "null"],
                "description": "Whether article is featured",
                "default": false,
                "examples": [true, false, null]
            },
            "isPublic": {
                "type": "boolean",
                "description": "Whether article is publicly visible",
                "default": true,
                "examples": [true, false]
            },
            "authorId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Article author user ID"
            },
            "reviewerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Article reviewer user ID"
            },
            "tags": {
                "type": ["array", "null"],
                "description": "Article tags",
                "items": {
                    "type": "string",
                    "maxLength": 50
                },
                "examples": [["password", "security"], ["api", "integration"], null]
            },
            "relatedArticleIds": {
                "type": ["array", "null"],
                "description": "Related article IDs",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "viewCount": {
                "type": ["integer", "null"],
                "description": "Number of views",
                "minimum": 0,
                "default": 0,
                "examples": [0, 100, 1000, null]
            },
            "helpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of helpful votes",
                "minimum": 0,
                "default": 0,
                "examples": [0, 50, 200, null]
            },
            "notHelpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of not helpful votes",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 20, null]
            },
            "attachments": {
                "type": ["array", "null"],
                "description": "Attachment URLs or IDs",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": { "type": "string", "format": "uuid" },
                        "url": { "type": "string", "format": "uri" },
                        "filename": { "type": "string" },
                        "mimeType": { "type": "string" },
                        "size": { "type": "integer", "minimum": 0 }
                    },
                    "required": ["url", "filename"]
                },
                "examples": [[{"url": "https://...", "filename": "screenshot.png", "mimeType": "image/png", "size": 102400}], null]
            },
            "publishedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When article was published"
            },
            "lastReviewedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When article was last reviewed"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional article metadata",
                "additionalProperties": true,
                "examples": [{"seoKeywords": ["password", "reset"], "version": "1.0"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When article was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When article was last updated"
            }
        },
        "required": ["title", "status", "isPublic", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['knowledge-base', 'kb', 'article', 'documentation', 'help', 'faq'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Support class templates successfully created: Ticket, TicketComment, SLA, KnowledgeBase';
END $$;
