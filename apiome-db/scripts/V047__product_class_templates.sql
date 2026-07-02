-- Product Class Templates
-- Adds product class templates for variants, inventory, categories, reviews, and pricing
-- These templates provide reusable patterns for e-commerce product management

SET search_path TO apiome, public;

-- =============================================================================
-- ProductVariant - Size/color/style options
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ProductVariant',
    'Product variant with size, color, style, and other option combinations.',
    'product',
    $JSON${
        "type": "object",
        "description": "Product variant with options",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the variant"
            },
            "productId": {
                "type": "string",
                "format": "uuid",
                "description": "Parent product ID"
            },
            "sku": {
                "type": ["string", "null"],
                "description": "Variant-specific SKU",
                "maxLength": 100,
                "examples": ["TSHIRT-RED-L", "SHOE-BLACK-42", null]
            },
            "barcode": {
                "type": ["string", "null"],
                "description": "Barcode or UPC",
                "maxLength": 100,
                "examples": ["1234567890123", null]
            },
            "options": {
                "type": "object",
                "description": "Variant option values (size, color, style, etc.)",
                "additionalProperties": true,
                "examples": [
                    {"size": "Large", "color": "Red"},
                    {"size": "42", "color": "Black", "width": "D"},
                    {"material": "Cotton", "pattern": "Striped"}
                ]
            },
            "price": {
                "type": ["number", "null"],
                "description": "Variant-specific price (overrides product base price)",
                "minimum": 0,
                "examples": [29.99, 49.95, null]
            },
            "compareAtPrice": {
                "type": ["number", "null"],
                "description": "Original/compare-at price for showing discounts",
                "minimum": 0,
                "examples": [39.99, 59.95, null]
            },
            "cost": {
                "type": ["number", "null"],
                "description": "Cost per unit (for profit calculation)",
                "minimum": 0,
                "examples": [15.00, 25.00, null]
            },
            "weight": {
                "type": ["number", "null"],
                "description": "Weight in specified unit",
                "minimum": 0,
                "examples": [0.5, 2.0, null]
            },
            "weightUnit": {
                "type": ["string", "null"],
                "description": "Weight unit",
                "enum": ["lb", "kg", "oz", "g", null],
                "examples": ["lb", "kg", null]
            },
            "imageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Variant-specific image URL"
            },
            "isAvailable": {
                "type": "boolean",
                "description": "Whether variant is available for purchase",
                "default": true,
                "examples": [true, false]
            },
            "inventoryQuantity": {
                "type": ["integer", "null"],
                "description": "Available quantity (if tracked at variant level)",
                "minimum": 0,
                "examples": [10, 0, null]
            },
            "inventoryPolicy": {
                "type": ["string", "null"],
                "description": "Inventory tracking policy",
                "enum": ["track", "continue", "deny", null],
                "examples": ["track", "continue", null]
            },
            "position": {
                "type": ["integer", "null"],
                "description": "Display order/position",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1, 10, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional variant metadata",
                "additionalProperties": true,
                "examples": [{"customField": "value"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When variant was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When variant was last updated"
            }
        },
        "required": ["productId", "options", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['product', 'variant', 'option', 'size', 'color', 'style', 'ecommerce'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Inventory - Stock levels and locations
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Inventory',
    'Inventory tracking with stock levels, locations, and reservation management.',
    'product',
    $JSON${
        "type": "object",
        "description": "Inventory stock level and location",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the inventory record"
            },
            "productId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product ID (null if variant-specific)"
            },
            "variantId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product variant ID (null if product-level)"
            },
            "locationId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Warehouse/location ID"
            },
            "locationName": {
                "type": ["string", "null"],
                "description": "Location name",
                "maxLength": 255,
                "examples": ["Main Warehouse", "Store #1", null]
            },
            "quantity": {
                "type": "integer",
                "description": "Available quantity",
                "minimum": 0,
                "examples": [100, 0, 50]
            },
            "reservedQuantity": {
                "type": ["integer", "null"],
                "description": "Reserved quantity (pending orders)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 5, 10, null]
            },
            "availableQuantity": {
                "type": ["integer", "null"],
                "description": "Available quantity (quantity - reservedQuantity)",
                "minimum": 0,
                "examples": [95, 0, null]
            },
            "reorderPoint": {
                "type": ["integer", "null"],
                "description": "Reorder point threshold",
                "minimum": 0,
                "examples": [20, 50, null]
            },
            "reorderQuantity": {
                "type": ["integer", "null"],
                "description": "Quantity to reorder when at reorder point",
                "minimum": 1,
                "examples": [100, 200, null]
            },
            "cost": {
                "type": ["number", "null"],
                "description": "Cost per unit at this location",
                "minimum": 0,
                "examples": [10.00, 25.50, null]
            },
            "status": {
                "type": ["string", "null"],
                "description": "Inventory status",
                "enum": ["in_stock", "low_stock", "out_of_stock", "backordered", "discontinued", null],
                "examples": ["in_stock", "low_stock", "out_of_stock", null]
            },
            "lastRestockedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When inventory was last restocked"
            },
            "lastCountedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When physical count was last performed"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional inventory metadata",
                "additionalProperties": true,
                "examples": [{"bin": "A-12", "supplier": "Supplier A"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When inventory record was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When inventory was last updated"
            }
        },
        "required": ["quantity", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['inventory', 'stock', 'warehouse', 'location', 'product', 'ecommerce'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ProductCategory - Product categorization
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ProductCategory',
    'Product category for organization and navigation with hierarchy support.',
    'product',
    $JSON${
        "type": "object",
        "description": "Product category",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the category"
            },
            "name": {
                "type": "string",
                "description": "Category name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Electronics", "Clothing", "Home & Garden"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 255,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["electronics", "clothing", "home-garden", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Category description",
                "maxLength": 2000,
                "examples": ["Electronic devices and accessories", null]
            },
            "parentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent category ID for hierarchy"
            },
            "level": {
                "type": ["integer", "null"],
                "description": "Category level in hierarchy (0 = root)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1, 2, null]
            },
            "path": {
                "type": ["string", "null"],
                "description": "Category path (e.g., /electronics/computers/laptops)",
                "maxLength": 500,
                "examples": ["/electronics", "/electronics/computers", null]
            },
            "imageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Category image URL"
            },
            "icon": {
                "type": ["string", "null"],
                "description": "Icon identifier or name",
                "maxLength": 50,
                "examples": ["electronics", "clothing", null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether category is active",
                "default": true,
                "examples": [true, false]
            },
            "isFeatured": {
                "type": ["boolean", "null"],
                "description": "Whether category is featured",
                "default": false,
                "examples": [true, false, null]
            },
            "sortOrder": {
                "type": ["integer", "null"],
                "description": "Display sort order",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1, 10, null]
            },
            "productCount": {
                "type": ["integer", "null"],
                "description": "Number of products in this category (denormalized)",
                "minimum": 0,
                "default": 0,
                "examples": [0, 50, 100, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional category metadata",
                "additionalProperties": true,
                "examples": [{"seoTitle": "Best Electronics", "seoDescription": "..."}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When category was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When category was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['category', 'product', 'taxonomy', 'organization', 'ecommerce'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ProductReview - Product reviews and ratings
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ProductReview',
    'Product review with rating, text, images, and moderation status.',
    'product',
    $JSON${
        "type": "object",
        "description": "Product review and rating",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the review"
            },
            "productId": {
                "type": "string",
                "format": "uuid",
                "description": "Product ID being reviewed"
            },
            "variantId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product variant ID (if reviewing specific variant)"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who wrote the review"
            },
            "userName": {
                "type": ["string", "null"],
                "description": "User display name (denormalized)",
                "maxLength": 255,
                "examples": ["John Doe", "Jane S.", null]
            },
            "orderId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Order ID (for verified purchase)"
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
                "description": "Review text content",
                "maxLength": 5000,
                "examples": ["This product exceeded my expectations...", null]
            },
            "pros": {
                "type": ["array", "null"],
                "description": "List of pros/positive points",
                "items": {
                    "type": "string",
                    "maxLength": 200
                },
                "examples": [["Fast shipping", "Good quality"], null]
            },
            "cons": {
                "type": ["array", "null"],
                "description": "List of cons/negative points",
                "items": {
                    "type": "string",
                    "maxLength": 200
                },
                "examples": [["Expensive", "Limited colors"], null]
            },
            "images": {
                "type": ["array", "null"],
                "description": "Review image URLs",
                "items": {
                    "type": "string",
                    "format": "uri"
                },
                "examples": [["https://cdn.example.com/review1.jpg"], null]
            },
            "isVerified": {
                "type": "boolean",
                "description": "Whether this is a verified purchase",
                "default": false,
                "examples": [true, false]
            },
            "isApproved": {
                "type": "boolean",
                "description": "Whether review is approved for display",
                "default": false,
                "examples": [true, false]
            },
            "isFeatured": {
                "type": ["boolean", "null"],
                "description": "Whether review is featured",
                "default": false,
                "examples": [true, false, null]
            },
            "helpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 50, null]
            },
            "notHelpfulCount": {
                "type": ["integer", "null"],
                "description": "Number of users who found this not helpful",
                "minimum": 0,
                "default": 0,
                "examples": [0, 2, 5, null]
            },
            "response": {
                "type": ["object", "null"],
                "description": "Merchant response to review",
                "properties": {
                    "text": { "type": "string", "maxLength": 2000 },
                    "respondedBy": { "type": "string", "format": "uuid" },
                    "respondedAt": { "type": "string", "format": "date-time" }
                },
                "examples": [{"text": "Thank you for your feedback!", "respondedBy": "merchant-id", "respondedAt": "2026-01-25T10:00:00Z"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When review was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When review was last updated"
            }
        },
        "required": ["productId", "rating", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['review', 'rating', 'product', 'feedback', 'ecommerce', 'user-generated'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ProductPrice - Pricing with currency and tax
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ProductPrice',
    'Product pricing with base price, currency, tax information, and discount support.',
    'product',
    $JSON${
        "type": "object",
        "description": "Product pricing information",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the price record"
            },
            "productId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product ID (null if variant-specific)"
            },
            "variantId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product variant ID (null if product-level)"
            },
            "basePrice": {
                "type": "number",
                "description": "Base price before discounts and tax",
                "minimum": 0,
                "examples": [29.99, 99.95, 0.00]
            },
            "compareAtPrice": {
                "type": ["number", "null"],
                "description": "Original/compare-at price for showing discounts",
                "minimum": 0,
                "examples": [39.99, 119.95, null]
            },
            "salePrice": {
                "type": ["number", "null"],
                "description": "Sale/discounted price",
                "minimum": 0,
                "examples": [24.99, 79.95, null]
            },
            "cost": {
                "type": ["number", "null"],
                "description": "Cost per unit (for profit calculation)",
                "minimum": 0,
                "examples": [15.00, 50.00, null]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", "GBP"]
            },
            "taxRate": {
                "type": ["number", "null"],
                "description": "Tax rate as decimal (e.g., 0.08 for 8%)",
                "minimum": 0,
                "maximum": 1,
                "examples": [0.08, 0.20, null]
            },
            "taxAmount": {
                "type": ["number", "null"],
                "description": "Calculated tax amount",
                "minimum": 0,
                "examples": [2.40, 15.99, null]
            },
            "taxIncluded": {
                "type": ["boolean", "null"],
                "description": "Whether tax is included in base price",
                "default": false,
                "examples": [true, false, null]
            },
            "taxClass": {
                "type": ["string", "null"],
                "description": "Tax class/category",
                "maxLength": 100,
                "examples": ["standard", "reduced", "exempt", null]
            },
            "effectivePrice": {
                "type": ["number", "null"],
                "description": "Effective price (salePrice or basePrice, with tax if applicable)",
                "minimum": 0,
                "examples": [32.39, 99.95, null]
            },
            "discountAmount": {
                "type": ["number", "null"],
                "description": "Discount amount",
                "minimum": 0,
                "examples": [5.00, 20.00, null]
            },
            "discountPercent": {
                "type": ["number", "null"],
                "description": "Discount percentage",
                "minimum": 0,
                "maximum": 100,
                "examples": [10, 25, null]
            },
            "minQuantity": {
                "type": ["integer", "null"],
                "description": "Minimum quantity for this price (tiered pricing)",
                "minimum": 1,
                "examples": [1, 10, 100, null]
            },
            "maxQuantity": {
                "type": ["integer", "null"],
                "description": "Maximum quantity for this price (tiered pricing)",
                "minimum": 1,
                "examples": [9, 99, null]
            },
            "validFrom": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When price becomes valid"
            },
            "validUntil": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When price expires"
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether price is active",
                "default": true,
                "examples": [true, false]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional pricing metadata",
                "additionalProperties": true,
                "examples": [{"promotionId": "promo-123"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When price was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When price was last updated"
            }
        },
        "required": ["basePrice", "currency", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['price', 'pricing', 'product', 'currency', 'tax', 'discount', 'ecommerce'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Product class templates successfully created: ProductVariant, Inventory, ProductCategory, ProductReview, ProductPrice';
END $$;
