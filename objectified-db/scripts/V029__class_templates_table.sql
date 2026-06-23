-- Class Templates Table
-- Stores reusable class templates that can be added to versions
-- Templates are stored as JSON Schema format class definitions with properties

SET search_path TO odb, public;

-- Drop existing table if exists
DROP TABLE IF EXISTS class_templates CASCADE;

CREATE TABLE class_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Template metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,  -- e.g., 'user', 'product', 'order', 'payment', 'address', 'common', etc.

    -- JSON Schema class definition
    schema JSONB NOT NULL,  -- The full class schema including type, properties, required fields, etc.

    -- Template classification
    tags TEXT[] DEFAULT '{}',  -- Array of tags for discoverability

    -- Ownership and visibility
    tenant_id UUID REFERENCES tenants(id),  -- NULL means system-wide/global template
    created_by UUID REFERENCES users(id),
    is_system BOOLEAN NOT NULL DEFAULT false,  -- True for built-in system templates
    is_public BOOLEAN NOT NULL DEFAULT true,  -- Whether template is visible to other tenants

    -- Usage tracking
    usage_count INTEGER NOT NULL DEFAULT 0,

    -- Soft delete and timestamps
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Ensure template names are unique within category for system templates
    -- and unique per tenant for tenant-specific templates
    CONSTRAINT class_templates_name_category_unique
        UNIQUE NULLS NOT DISTINCT (tenant_id, category, name)
);

-- Table comment
COMMENT ON TABLE class_templates IS 'Stores reusable class templates that can be quickly added to versions. Templates contain full JSON Schema class definitions with properties for rapid schema creation.';

-- Column comments
COMMENT ON COLUMN class_templates.id IS 'Unique identifier for the template';
COMMENT ON COLUMN class_templates.name IS 'Display name of the template (e.g., "User Account", "Product Listing", "Shipping Address")';
COMMENT ON COLUMN class_templates.description IS 'Detailed description of what the class template represents and how to use it';
COMMENT ON COLUMN class_templates.category IS 'Category for organizing templates (user, product, order, payment, address, common, audit, security, content, etc.)';
COMMENT ON COLUMN class_templates.schema IS 'Full JSON Schema class definition including type, properties, required fields, examples, etc.';
COMMENT ON COLUMN class_templates.tags IS 'Array of tags for search and filtering';
COMMENT ON COLUMN class_templates.tenant_id IS 'Owner tenant - NULL for system-wide templates';
COMMENT ON COLUMN class_templates.created_by IS 'User who created the template';
COMMENT ON COLUMN class_templates.is_system IS 'True for built-in system templates that cannot be modified';
COMMENT ON COLUMN class_templates.is_public IS 'Whether template is visible to users outside the owning tenant';
COMMENT ON COLUMN class_templates.usage_count IS 'Number of times this template has been used';
COMMENT ON COLUMN class_templates.enabled IS 'Flag indicating if the template is currently active';
COMMENT ON COLUMN class_templates.deleted_at IS 'Soft delete timestamp';
COMMENT ON COLUMN class_templates.created_at IS 'Timestamp when the template was created';
COMMENT ON COLUMN class_templates.updated_at IS 'Timestamp when the template was last modified';

-- Indices for performance

-- Index on category for filtering
CREATE INDEX idx_class_templates_category ON class_templates(category) WHERE deleted_at IS NULL;

-- Index on tenant_id for tenant-specific queries
CREATE INDEX idx_class_templates_tenant_id ON class_templates(tenant_id) WHERE deleted_at IS NULL;

-- Index on is_system for finding built-in templates
CREATE INDEX idx_class_templates_is_system ON class_templates(is_system) WHERE deleted_at IS NULL AND enabled = true;

-- Index on is_public for finding shareable templates
CREATE INDEX idx_class_templates_is_public ON class_templates(is_public) WHERE deleted_at IS NULL AND enabled = true;

-- GIN index on tags for efficient tag-based searching
CREATE INDEX idx_class_templates_tags_gin ON class_templates USING GIN (tags);

-- GIN index on schema for JSON queries
CREATE INDEX idx_class_templates_schema_gin ON class_templates USING GIN (schema);

-- Index for popular templates (by usage)
CREATE INDEX idx_class_templates_usage ON class_templates(usage_count DESC) WHERE deleted_at IS NULL AND enabled = true;

-- Full text search index on name and description
CREATE INDEX idx_class_templates_search ON class_templates
    USING GIN (to_tsvector('english', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- Insert some default system class templates
INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public) VALUES
-- User & Auth Templates
('User', 'Standard user account with common fields', 'user', '{
  "type": "object",
  "description": "Represents a user account in the system",
  "properties": {
    "id": { "type": "string", "format": "uuid", "description": "Unique identifier" },
    "email": { "type": "string", "format": "email", "description": "User email address" },
    "username": { "type": "string", "minLength": 3, "maxLength": 50, "description": "Username for login" },
    "firstName": { "type": "string", "description": "First name" },
    "lastName": { "type": "string", "description": "Last name" },
    "displayName": { "type": "string", "description": "Display name shown in UI" },
    "avatarUrl": { "type": "string", "format": "uri", "description": "URL to avatar image" },
    "isActive": { "type": "boolean", "default": true, "description": "Whether user is active" },
    "createdAt": { "type": "string", "format": "date-time", "description": "Account creation timestamp" },
    "updatedAt": { "type": "string", "format": "date-time", "description": "Last update timestamp" }
  },
  "required": ["email"]
}', ARRAY['user', 'account', 'identity', 'auth'], true, true),

('UserProfile', 'Extended user profile information', 'user', '{
  "type": "object",
  "description": "Extended profile information for a user",
  "properties": {
    "userId": { "type": "string", "format": "uuid", "description": "Reference to user" },
    "bio": { "type": "string", "maxLength": 500, "description": "User biography" },
    "website": { "type": "string", "format": "uri", "description": "Personal website URL" },
    "location": { "type": "string", "description": "Geographic location" },
    "timezone": { "type": "string", "description": "User timezone" },
    "language": { "type": "string", "description": "Preferred language code" },
    "dateOfBirth": { "type": "string", "format": "date", "description": "Date of birth" },
    "phoneNumber": { "type": "string", "description": "Phone number" }
  },
  "required": ["userId"]
}', ARRAY['user', 'profile', 'personal'], true, true),

-- Address Templates
('Address', 'Standard postal address', 'address', '{
  "type": "object",
  "description": "Physical mailing address",
  "properties": {
    "street1": { "type": "string", "description": "Street address line 1" },
    "street2": { "type": "string", "description": "Street address line 2" },
    "city": { "type": "string", "description": "City name" },
    "state": { "type": "string", "description": "State or province" },
    "postalCode": { "type": "string", "description": "Postal/ZIP code" },
    "country": { "type": "string", "description": "Country code (ISO 3166-1)" },
    "isPrimary": { "type": "boolean", "default": false, "description": "Primary address flag" },
    "label": { "type": "string", "enum": ["home", "work", "billing", "shipping", "other"], "description": "Address type" }
  },
  "required": ["street1", "city", "country"]
}', ARRAY['address', 'location', 'postal', 'shipping'], true, true),

-- Product Templates
('Product', 'E-commerce product definition', 'product', '{
  "type": "object",
  "description": "Product available for purchase",
  "properties": {
    "id": { "type": "string", "format": "uuid", "description": "Unique identifier" },
    "sku": { "type": "string", "description": "Stock keeping unit" },
    "name": { "type": "string", "description": "Product name" },
    "description": { "type": "string", "description": "Product description" },
    "price": { "type": "number", "minimum": 0, "description": "Price in default currency" },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$", "description": "ISO 4217 currency code" },
    "category": { "type": "string", "description": "Product category" },
    "imageUrl": { "type": "string", "format": "uri", "description": "Main product image" },
    "inStock": { "type": "boolean", "default": true, "description": "Availability status" },
    "quantity": { "type": "integer", "minimum": 0, "description": "Available quantity" },
    "createdAt": { "type": "string", "format": "date-time" },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["name", "price"]
}', ARRAY['product', 'ecommerce', 'catalog', 'inventory'], true, true),

-- Order Templates
('Order', 'E-commerce order', 'order', '{
  "type": "object",
  "description": "Customer order",
  "properties": {
    "id": { "type": "string", "format": "uuid", "description": "Order ID" },
    "orderNumber": { "type": "string", "description": "Human-readable order number" },
    "customerId": { "type": "string", "format": "uuid", "description": "Customer reference" },
    "status": { "type": "string", "enum": ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled"], "description": "Order status" },
    "subtotal": { "type": "number", "minimum": 0, "description": "Subtotal before tax/shipping" },
    "tax": { "type": "number", "minimum": 0, "description": "Tax amount" },
    "shipping": { "type": "number", "minimum": 0, "description": "Shipping cost" },
    "total": { "type": "number", "minimum": 0, "description": "Total order amount" },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$", "description": "Currency code" },
    "notes": { "type": "string", "description": "Order notes" },
    "createdAt": { "type": "string", "format": "date-time" },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["customerId", "total"]
}', ARRAY['order', 'ecommerce', 'purchase', 'transaction'], true, true),

('OrderItem', 'Line item within an order', 'order', '{
  "type": "object",
  "description": "Individual item in an order",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "orderId": { "type": "string", "format": "uuid", "description": "Parent order reference" },
    "productId": { "type": "string", "format": "uuid", "description": "Product reference" },
    "name": { "type": "string", "description": "Product name at time of order" },
    "quantity": { "type": "integer", "minimum": 1, "description": "Quantity ordered" },
    "unitPrice": { "type": "number", "minimum": 0, "description": "Price per unit" },
    "totalPrice": { "type": "number", "minimum": 0, "description": "Line item total" }
  },
  "required": ["orderId", "productId", "quantity", "unitPrice"]
}', ARRAY['order', 'item', 'line-item', 'ecommerce'], true, true),

-- Payment Templates
('Payment', 'Payment transaction record', 'payment', '{
  "type": "object",
  "description": "Payment transaction",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "orderId": { "type": "string", "format": "uuid", "description": "Associated order" },
    "amount": { "type": "number", "minimum": 0, "description": "Payment amount" },
    "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "method": { "type": "string", "enum": ["credit_card", "debit_card", "paypal", "bank_transfer", "crypto", "other"], "description": "Payment method" },
    "status": { "type": "string", "enum": ["pending", "processing", "completed", "failed", "refunded", "cancelled"], "description": "Payment status" },
    "transactionId": { "type": "string", "description": "External transaction ID" },
    "processedAt": { "type": "string", "format": "date-time" },
    "createdAt": { "type": "string", "format": "date-time" }
  },
  "required": ["amount", "currency", "method"]
}', ARRAY['payment', 'transaction', 'finance', 'billing'], true, true),

-- Common/Utility Templates
('AuditLog', 'Audit trail entry', 'common', '{
  "type": "object",
  "description": "Audit log entry for tracking changes",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "entityType": { "type": "string", "description": "Type of entity modified" },
    "entityId": { "type": "string", "description": "ID of entity modified" },
    "action": { "type": "string", "enum": ["create", "update", "delete", "archive", "restore"], "description": "Action performed" },
    "userId": { "type": "string", "format": "uuid", "description": "User who performed action" },
    "changes": { "type": "object", "description": "JSON diff of changes" },
    "ipAddress": { "type": "string", "description": "IP address of requester" },
    "userAgent": { "type": "string", "description": "User agent string" },
    "timestamp": { "type": "string", "format": "date-time" }
  },
  "required": ["entityType", "entityId", "action", "timestamp"]
}', ARRAY['audit', 'log', 'tracking', 'history'], true, true),

('Tag', 'Generic tagging entity', 'common', '{
  "type": "object",
  "description": "Tag for categorizing content",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "name": { "type": "string", "description": "Tag name" },
    "slug": { "type": "string", "description": "URL-friendly slug" },
    "color": { "type": "string", "pattern": "^#[0-9A-Fa-f]{6}$", "description": "Hex color code" },
    "description": { "type": "string", "description": "Tag description" }
  },
  "required": ["name"]
}', ARRAY['tag', 'label', 'category', 'metadata'], true, true),

('File', 'File/attachment metadata', 'common', '{
  "type": "object",
  "description": "File or attachment metadata",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "name": { "type": "string", "description": "Original filename" },
    "mimeType": { "type": "string", "description": "MIME type" },
    "size": { "type": "integer", "minimum": 0, "description": "File size in bytes" },
    "url": { "type": "string", "format": "uri", "description": "Download URL" },
    "thumbnailUrl": { "type": "string", "format": "uri", "description": "Thumbnail URL" },
    "uploadedBy": { "type": "string", "format": "uuid", "description": "Uploader user ID" },
    "uploadedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["name", "url"]
}', ARRAY['file', 'attachment', 'upload', 'media'], true, true),

-- Content Templates
('BlogPost', 'Blog article content', 'content', '{
  "type": "object",
  "description": "Blog post or article",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "title": { "type": "string", "description": "Post title" },
    "slug": { "type": "string", "description": "URL slug" },
    "excerpt": { "type": "string", "description": "Short excerpt" },
    "content": { "type": "string", "description": "Full content (HTML/Markdown)" },
    "authorId": { "type": "string", "format": "uuid", "description": "Author user ID" },
    "status": { "type": "string", "enum": ["draft", "published", "archived"], "description": "Publication status" },
    "featuredImageUrl": { "type": "string", "format": "uri" },
    "publishedAt": { "type": "string", "format": "date-time" },
    "createdAt": { "type": "string", "format": "date-time" },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["title", "content"]
}', ARRAY['blog', 'post', 'article', 'content', 'cms'], true, true),

('Comment', 'User comment', 'content', '{
  "type": "object",
  "description": "User comment on content",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "entityType": { "type": "string", "description": "Type of entity being commented on" },
    "entityId": { "type": "string", "description": "ID of entity being commented on" },
    "authorId": { "type": "string", "format": "uuid", "description": "Comment author" },
    "parentId": { "type": "string", "format": "uuid", "description": "Parent comment for replies" },
    "content": { "type": "string", "description": "Comment text" },
    "isApproved": { "type": "boolean", "default": false },
    "createdAt": { "type": "string", "format": "date-time" },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["entityType", "entityId", "content"]
}', ARRAY['comment', 'reply', 'discussion', 'content'], true, true),

-- API/Integration Templates
('ApiKey', 'API key for authentication', 'security', '{
  "type": "object",
  "description": "API key for service authentication",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "name": { "type": "string", "description": "Key name/description" },
    "keyPrefix": { "type": "string", "description": "Visible key prefix" },
    "keyHash": { "type": "string", "description": "Hashed key value" },
    "permissions": { "type": "array", "items": { "type": "string" }, "description": "Granted permissions" },
    "expiresAt": { "type": "string", "format": "date-time", "description": "Expiration date" },
    "lastUsedAt": { "type": "string", "format": "date-time" },
    "isActive": { "type": "boolean", "default": true },
    "createdAt": { "type": "string", "format": "date-time" }
  },
  "required": ["name", "keyHash"]
}', ARRAY['api', 'key', 'auth', 'security', 'token'], true, true),

('Webhook', 'Webhook subscription', 'integration', '{
  "type": "object",
  "description": "Webhook subscription for event notifications",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "url": { "type": "string", "format": "uri", "description": "Callback URL" },
    "events": { "type": "array", "items": { "type": "string" }, "description": "Subscribed event types" },
    "secret": { "type": "string", "description": "Signing secret" },
    "isActive": { "type": "boolean", "default": true },
    "failureCount": { "type": "integer", "default": 0, "description": "Consecutive failure count" },
    "lastTriggeredAt": { "type": "string", "format": "date-time" },
    "createdAt": { "type": "string", "format": "date-time" }
  },
  "required": ["url", "events"]
}', ARRAY['webhook', 'callback', 'integration', 'events'], true, true),

-- Notification Templates
('Notification', 'User notification', 'notification', '{
  "type": "object",
  "description": "User notification",
  "properties": {
    "id": { "type": "string", "format": "uuid" },
    "userId": { "type": "string", "format": "uuid", "description": "Recipient user" },
    "type": { "type": "string", "description": "Notification type" },
    "title": { "type": "string", "description": "Notification title" },
    "message": { "type": "string", "description": "Notification message" },
    "data": { "type": "object", "description": "Additional data payload" },
    "isRead": { "type": "boolean", "default": false },
    "readAt": { "type": "string", "format": "date-time" },
    "createdAt": { "type": "string", "format": "date-time" }
  },
  "required": ["userId", "type", "message"]
}', ARRAY['notification', 'alert', 'message', 'inbox'], true, true);

