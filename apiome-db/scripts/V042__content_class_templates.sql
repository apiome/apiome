-- Content Class Templates
-- Adds content management class templates for media galleries, tags, comments, ratings, articles, and FAQs
-- These templates provide reusable patterns for content-driven applications

SET search_path TO apiome, public;

-- =============================================================================
-- MediaGallery - Collection of images/videos
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'MediaGallery',
    'Collection of images and videos with metadata, ordering, and display options.',
    'content',
    $JSON${
        "type": "object",
        "description": "Collection of media items (images and videos)",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the gallery"
            },
            "title": {
                "type": ["string", "null"],
                "description": "Gallery title",
                "maxLength": 255,
                "examples": ["Product Photos", "Event Gallery", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Gallery description",
                "maxLength": 1000,
                "examples": ["Collection of product images", null]
            },
            "items": {
                "type": "array",
                "description": "Array of media items in the gallery",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "format": "uuid",
                            "description": "Media item identifier"
                        },
                        "type": {
                            "type": "string",
                            "enum": ["image", "video"],
                            "description": "Type of media"
                        },
                        "url": {
                            "type": "string",
                            "format": "uri",
                            "description": "URL to the media file"
                        },
                        "thumbnailUrl": {
                            "type": ["string", "null"],
                            "format": "uri",
                            "description": "URL to thumbnail image"
                        },
                        "alt": {
                            "type": ["string", "null"],
                            "description": "Alt text for accessibility",
                            "maxLength": 500
                        },
                        "caption": {
                            "type": ["string", "null"],
                            "description": "Caption for the media",
                            "maxLength": 500
                        },
                        "width": {
                            "type": ["integer", "null"],
                            "description": "Width in pixels",
                            "minimum": 1
                        },
                        "height": {
                            "type": ["integer", "null"],
                            "description": "Height in pixels",
                            "minimum": 1
                        },
                        "duration": {
                            "type": ["number", "null"],
                            "description": "Duration in seconds (for videos)",
                            "minimum": 0
                        },
                        "order": {
                            "type": ["integer", "null"],
                            "description": "Display order in gallery",
                            "minimum": 0,
                            "default": 0
                        }
                    },
                    "required": ["type", "url"]
                },
                "minItems": 0,
                "default": []
            },
            "layout": {
                "type": ["string", "null"],
                "description": "Gallery layout style",
                "enum": ["grid", "carousel", "masonry", "slider", null],
                "default": "grid",
                "examples": ["grid", "carousel", null]
            },
            "maxItems": {
                "type": ["integer", "null"],
                "description": "Maximum number of items to display",
                "minimum": 1,
                "examples": [10, 20, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the gallery was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When the gallery was last updated"
            }
        },
        "required": ["items", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['media', 'gallery', 'images', 'videos', 'content', 'collection'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ContentTag - Tag for categorization and search (content category)
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ContentTag',
    'Tag for categorizing and searching content items with metadata and relationships.',
    'content',
    $JSON${
        "type": "object",
        "description": "Tag for content categorization and search",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the tag"
            },
            "name": {
                "type": "string",
                "description": "Tag name",
                "maxLength": 100,
                "minLength": 1,
                "examples": ["technology", "tutorial", "announcement"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 100,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["technology", "tutorial", "announcement", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Tag description",
                "maxLength": 500,
                "examples": ["Content related to technology", null]
            },
            "color": {
                "type": ["string", "null"],
                "description": "Hex color code for visual identification",
                "pattern": "^#[0-9A-Fa-f]{6}$",
                "examples": ["#3B82F6", "#10B981", null]
            },
            "icon": {
                "type": ["string", "null"],
                "description": "Icon identifier or name",
                "maxLength": 50,
                "examples": ["tag", "label", null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Tag category for grouping",
                "maxLength": 50,
                "examples": ["topic", "type", "difficulty", null]
            },
            "usageCount": {
                "type": ["integer", "null"],
                "description": "Number of times this tag has been used",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 100, null]
            },
            "isFeatured": {
                "type": ["boolean", "null"],
                "description": "Whether this tag is featured/promoted",
                "default": false,
                "examples": [true, false, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When the tag was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When the tag was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['tag', 'label', 'category', 'content', 'metadata', 'taxonomy'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ContentComment - Enhanced user-generated content comment
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ContentComment',
    'Enhanced user-generated comment with moderation, reactions, and threading support.',
    'content',
    $JSON${
        "type": "object",
        "description": "User-generated comment on content",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the comment"
            },
            "entityType": {
                "type": "string",
                "description": "Type of entity being commented on",
                "maxLength": 100,
                "examples": ["Article", "Post", "Product", "Video"]
            },
            "entityId": {
                "type": "string",
                "description": "ID of entity being commented on",
                "maxLength": 255,
                "examples": ["abc123", "550e8400-e29b-41d4-a716-446655440000"]
            },
            "authorId": {
                "type": "string",
                "format": "uuid",
                "description": "Comment author user ID"
            },
            "authorName": {
                "type": ["string", "null"],
                "description": "Author display name (denormalized for performance)",
                "maxLength": 255,
                "examples": ["John Doe", "Jane Smith", null]
            },
            "parentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent comment ID for threaded replies"
            },
            "content": {
                "type": "string",
                "description": "Comment text content",
                "minLength": 1,
                "maxLength": 10000
            },
            "contentHtml": {
                "type": ["string", "null"],
                "description": "HTML formatted content",
                "maxLength": 20000,
                "examples": ["<p>Great article!</p>", null]
            },
            "isApproved": {
                "type": "boolean",
                "description": "Whether comment is approved for display",
                "default": false,
                "examples": [true, false]
            },
            "isPinned": {
                "type": ["boolean", "null"],
                "description": "Whether comment is pinned to top",
                "default": false,
                "examples": [true, false, null]
            },
            "isEdited": {
                "type": ["boolean", "null"],
                "description": "Whether comment has been edited",
                "default": false,
                "examples": [true, false, null]
            },
            "editedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When comment was last edited"
            },
            "likeCount": {
                "type": ["integer", "null"],
                "description": "Number of likes/reactions",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 100, null]
            },
            "replyCount": {
                "type": ["integer", "null"],
                "description": "Number of replies to this comment",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 20, null]
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
        "required": ["entityType", "entityId", "authorId", "content", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['comment', 'reply', 'discussion', 'content', 'user-generated', 'moderation'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Rating - Star ratings with review text
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Rating',
    'Star rating with optional review text, helpful votes, and moderation.',
    'content',
    $JSON${
        "type": "object",
        "description": "Rating with review text",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the rating"
            },
            "entityType": {
                "type": "string",
                "description": "Type of entity being rated",
                "maxLength": 100,
                "examples": ["Product", "Service", "Article", "Course"]
            },
            "entityId": {
                "type": "string",
                "description": "ID of entity being rated",
                "maxLength": 255,
                "examples": ["abc123", "550e8400-e29b-41d4-a716-446655440000"]
            },
            "userId": {
                "type": "string",
                "format": "uuid",
                "description": "User who submitted the rating"
            },
            "userName": {
                "type": ["string", "null"],
                "description": "User display name (denormalized)",
                "maxLength": 255,
                "examples": ["John Doe", "Jane Smith", null]
            },
            "rating": {
                "type": "integer",
                "description": "Star rating (1-5)",
                "minimum": 1,
                "maximum": 5,
                "examples": [1, 3, 5]
            },
            "title": {
                "type": ["string", "null"],
                "description": "Review title",
                "maxLength": 200,
                "examples": ["Great product!", "Could be better", null]
            },
            "review": {
                "type": ["string", "null"],
                "description": "Detailed review text",
                "maxLength": 5000,
                "examples": ["This product exceeded my expectations...", null]
            },
            "isVerified": {
                "type": ["boolean", "null"],
                "description": "Whether this is a verified purchase/review",
                "default": false,
                "examples": [true, false, null]
            },
            "isApproved": {
                "type": "boolean",
                "description": "Whether rating is approved for display",
                "default": false,
                "examples": [true, false]
            },
            "helpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 20, null]
            },
            "notHelpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this not helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 2, 5, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When rating was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When rating was last updated"
            }
        },
        "required": ["entityType", "entityId", "userId", "rating", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['rating', 'review', 'stars', 'feedback', 'content', 'user-generated'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Article - Blog/documentation content
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Article',
    'Article for blog posts, documentation, or general content with rich text, metadata, and publishing controls.',
    'content',
    $JSON${
        "type": "object",
        "description": "Article for blog, documentation, or content",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the article"
            },
            "title": {
                "type": "string",
                "description": "Article title",
                "maxLength": 500,
                "minLength": 1,
                "examples": ["Getting Started with TypeScript", "API Documentation"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 500,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["getting-started-with-typescript", "api-documentation", null]
            },
            "excerpt": {
                "type": ["string", "null"],
                "description": "Short excerpt or summary",
                "maxLength": 500,
                "examples": ["Learn the basics of TypeScript...", null]
            },
            "content": {
                "type": "string",
                "description": "Full article content (HTML/Markdown)",
                "minLength": 1
            },
            "contentHtml": {
                "type": ["string", "null"],
                "description": "Rendered HTML content",
                "examples": ["<p>Article content...</p>", null]
            },
            "authorId": {
                "type": "string",
                "format": "uuid",
                "description": "Author user ID"
            },
            "authorName": {
                "type": ["string", "null"],
                "description": "Author display name (denormalized)",
                "maxLength": 255,
                "examples": ["John Doe", "Jane Smith", null]
            },
            "status": {
                "type": "string",
                "description": "Publication status",
                "enum": ["draft", "published", "archived", "scheduled"],
                "default": "draft",
                "examples": ["draft", "published", "archived"]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Article category",
                "maxLength": 100,
                "examples": ["Tutorial", "Documentation", "News", null]
            },
            "tags": {
                "type": ["array", "null"],
                "description": "Array of tag names or IDs",
                "items": {
                    "type": "string"
                },
                "examples": [["typescript", "programming"], ["api", "docs"], null]
            },
            "featuredImageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "URL to featured image"
            },
            "readingTime": {
                "type": ["integer", "null"],
                "description": "Estimated reading time in minutes",
                "minimum": 1,
                "examples": [5, 10, 15, null]
            },
            "viewCount": {
                "type": ["integer", "null"],
                "description": "Number of views",
                "minimum": 0,
                "default": 0,
                "examples": [0, 100, 1000, null]
            },
            "publishedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Publication date and time"
            },
            "scheduledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Scheduled publication date and time"
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
        "required": ["title", "content", "authorId", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['article', 'blog', 'post', 'content', 'documentation', 'cms'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- FAQ - Question and answer pairs
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'FAQ',
    'Frequently asked question with answer, categorization, and helpful tracking.',
    'content',
    $JSON${
        "type": "object",
        "description": "Frequently asked question and answer",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the FAQ"
            },
            "question": {
                "type": "string",
                "description": "The question",
                "minLength": 1,
                "maxLength": 500,
                "examples": ["How do I reset my password?", "What is your refund policy?"]
            },
            "answer": {
                "type": "string",
                "description": "The answer",
                "minLength": 1,
                "maxLength": 10000
            },
            "answerHtml": {
                "type": ["string", "null"],
                "description": "HTML formatted answer",
                "maxLength": 20000,
                "examples": ["<p>To reset your password...</p>", null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "FAQ category",
                "maxLength": 100,
                "examples": ["Account", "Billing", "Technical", null]
            },
            "tags": {
                "type": ["array", "null"],
                "description": "Tags for categorization",
                "items": {
                    "type": "string"
                },
                "examples": [["password", "security"], ["billing", "payment"], null]
            },
            "order": {
                "type": ["integer", "null"],
                "description": "Display order within category",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1, 10, null]
            },
            "isFeatured": {
                "type": ["boolean", "null"],
                "description": "Whether this FAQ is featured/promoted",
                "default": false,
                "examples": [true, false, null]
            },
            "isPublished": {
                "type": "boolean",
                "description": "Whether FAQ is published and visible",
                "default": true,
                "examples": [true, false]
            },
            "viewCount": {
                "type": ["integer", "null"],
                "description": "Number of times this FAQ has been viewed",
                "minimum": 0,
                "default": 0,
                "examples": [0, 100, 1000, null]
            },
            "helpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 50, 200, null]
            },
            "notHelpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this not helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 10, null]
            },
            "relatedFaqIds": {
                "type": ["array", "null"],
                "description": "IDs of related FAQs",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When FAQ was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When FAQ was last updated"
            }
        },
        "required": ["question", "answer", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['faq', 'question', 'answer', 'help', 'support', 'content'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Content class templates successfully created: MediaGallery, ContentTag, ContentComment, Rating, Article, FAQ';
END $$;
