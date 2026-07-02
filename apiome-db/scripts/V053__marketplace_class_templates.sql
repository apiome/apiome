-- Marketplace Class Templates
-- Adds marketplace class templates for vendors, commissions, disputes, and escrow
-- These templates provide reusable patterns for multi-vendor marketplace platforms

SET search_path TO apiome, public;

-- =============================================================================
-- Vendor - Seller/supplier profiles
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Vendor',
    'Marketplace vendor/seller profile with verification, ratings, and payout settings.',
    'marketplace',
    $JSON${
        "type": "object",
        "description": "Marketplace vendor/seller profile",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the vendor"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (if linked to platform user)"
            },
            "businessName": {
                "type": "string",
                "description": "Business/company name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Acme Supplies", "Artisan Crafts Co", "Tech Gadgets LLC"]
            },
            "slug": {
                "type": ["string", "null"],
                "description": "URL-friendly slug",
                "maxLength": 255,
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "examples": ["acme-supplies", "artisan-crafts", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Vendor description",
                "maxLength": 5000,
                "examples": ["Premium office supplies since 2010", null]
            },
            "logoUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Vendor logo URL"
            },
            "coverImageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Vendor cover/storefront image URL"
            },
            "status": {
                "type": ["string", "null"],
                "description": "Vendor status",
                "enum": ["pending", "active", "suspended", "inactive", "rejected", null],
                "default": "pending",
                "examples": ["active", "pending", "suspended", null]
            },
            "isVerified": {
                "type": ["boolean", "null"],
                "description": "Whether vendor is verified",
                "default": false,
                "examples": [true, false, null]
            },
            "verificationLevel": {
                "type": ["string", "null"],
                "description": "Verification level",
                "enum": ["none", "basic", "verified", "premium", null],
                "examples": ["none", "verified", null]
            },
            "rating": {
                "type": ["number", "null"],
                "description": "Average rating (e.g., 1-5)",
                "minimum": 0,
                "maximum": 5,
                "examples": [4.5, 4.8, null]
            },
            "reviewCount": {
                "type": ["integer", "null"],
                "description": "Number of reviews",
                "minimum": 0,
                "default": 0,
                "examples": [0, 100, 1000, null]
            },
            "orderCount": {
                "type": ["integer", "null"],
                "description": "Total orders fulfilled",
                "minimum": 0,
                "default": 0,
                "examples": [0, 500, 10000, null]
            },
            "payoutAccountId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Linked payout/bank account ID"
            },
            "commissionRate": {
                "type": ["number", "null"],
                "description": "Commission rate (0-1, e.g., 0.15 for 15%)",
                "minimum": 0,
                "maximum": 1,
                "examples": [0.10, 0.15, null]
            },
            "taxId": {
                "type": ["string", "null"],
                "description": "Tax ID (VAT, EIN, etc.)",
                "maxLength": 50,
                "examples": ["US-12-3456789", "GB123456789", null]
            },
            "contactEmail": {
                "type": ["string", "null"],
                "format": "email",
                "description": "Vendor contact email"
            },
            "contactPhone": {
                "type": ["string", "null"],
                "description": "Vendor contact phone",
                "maxLength": 50,
                "examples": ["+1-555-123-4567", null]
            },
            "websiteUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Vendor website URL"
            },
            "address": {
                "type": ["object", "null"],
                "description": "Business address",
                "additionalProperties": true,
                "examples": [{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001", "country": "US"}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional vendor metadata",
                "additionalProperties": true,
                "examples": [{"categories": ["electronics", "gadgets"], "foundedYear": 2015}, null]
            },
            "approvedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When vendor was approved"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When vendor was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When vendor was last updated"
            }
        },
        "required": ["businessName", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['vendor', 'seller', 'marketplace', 'supplier', 'merchant'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Commission - Marketplace fee structures
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Commission',
    'Marketplace commission/fee structure with tiers and rules.',
    'marketplace',
    $JSON${
        "type": "object",
        "description": "Marketplace commission/fee structure",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the commission structure"
            },
            "name": {
                "type": "string",
                "description": "Commission structure name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Standard 15%", "Premium 10%", "New Seller 20%"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Commission structure description",
                "maxLength": 1000,
                "examples": ["Standard marketplace commission for all categories", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Commission type",
                "enum": ["percentage", "fixed", "tiered", "hybrid", null],
                "default": "percentage",
                "examples": ["percentage", "tiered", "hybrid", null]
            },
            "rate": {
                "type": ["number", "null"],
                "description": "Commission rate (0-1 for percentage, e.g., 0.15 for 15%)",
                "minimum": 0,
                "maximum": 1,
                "examples": [0.10, 0.15, 0.20, null]
            },
            "fixedAmount": {
                "type": ["number", "null"],
                "description": "Fixed fee per transaction",
                "minimum": 0,
                "examples": [0.30, 1.00, 0, null]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency for fixed amount",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "minAmount": {
                "type": ["number", "null"],
                "description": "Minimum commission amount",
                "minimum": 0,
                "examples": [0.50, 1.00, null]
            },
            "maxAmount": {
                "type": ["number", "null"],
                "description": "Maximum commission amount (cap)",
                "minimum": 0,
                "examples": [100, 500, null]
            },
            "tiers": {
                "type": ["array", "null"],
                "description": "Tiered commission rules",
                "items": {
                    "type": "object",
                    "properties": {
                        "minVolume": { "type": "number", "minimum": 0 },
                        "maxVolume": { "type": "number", "minimum": 0 },
                        "rate": { "type": "number", "minimum": 0, "maximum": 1 },
                        "fixedAmount": { "type": "number", "minimum": 0 }
                    },
                    "required": ["rate"]
                },
                "examples": [[{"minVolume": 0, "maxVolume": 10000, "rate": 0.20}, {"minVolume": 10000, "maxVolume": null, "rate": 0.15}], null]
            },
            "appliesTo": {
                "type": ["string", "null"],
                "description": "What commission applies to",
                "enum": ["order_total", "product_price", "shipping", "all", null],
                "examples": ["order_total", "product_price", null]
            },
            "categoryIds": {
                "type": ["array", "null"],
                "description": "Category IDs this commission applies to (null = all)",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "vendorIds": {
                "type": ["array", "null"],
                "description": "Vendor IDs this commission applies to (null = all)",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "isDefault": {
                "type": ["boolean", "null"],
                "description": "Whether this is the default commission structure",
                "default": false,
                "examples": [true, false, null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether structure is active",
                "default": true,
                "examples": [true, false]
            },
            "effectiveFrom": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When commission becomes effective"
            },
            "effectiveUntil": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When commission expires"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional commission metadata",
                "additionalProperties": true,
                "examples": [{"region": "US", "promo": "new_seller"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When commission structure was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When commission was last updated"
            }
        },
        "required": ["name", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['commission', 'fee', 'marketplace', 'revenue', 'pricing'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Dispute - Buyer/seller disputes
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Dispute',
    'Buyer-seller dispute with resolution tracking and evidence.',
    'marketplace',
    $JSON${
        "type": "object",
        "description": "Marketplace dispute between buyer and seller",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the dispute"
            },
            "disputeNumber": {
                "type": ["string", "null"],
                "description": "Human-readable dispute number",
                "maxLength": 100,
                "examples": ["DSP-2026-001", "D123456", null]
            },
            "orderId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated order ID"
            },
            "buyerId": {
                "type": "string",
                "format": "uuid",
                "description": "Buyer user ID"
            },
            "vendorId": {
                "type": "string",
                "format": "uuid",
                "description": "Vendor/seller ID"
            },
            "reason": {
                "type": ["string", "null"],
                "description": "Dispute reason",
                "enum": ["item_not_received", "item_not_as_described", "defective", "wrong_item", "quality_issue", "refund_not_received", "unauthorized_charge", "other", null],
                "examples": ["item_not_received", "item_not_as_described", null]
            },
            "reasonDetail": {
                "type": ["string", "null"],
                "description": "Detailed dispute description",
                "maxLength": 2000,
                "examples": ["Item never arrived, tracking shows delivered but not received", null]
            },
            "status": {
                "type": "string",
                "description": "Dispute status",
                "enum": ["open", "under_review", "evidence_required", "pending_decision", "resolved", "closed", "refunded", "rejected"],
                "default": "open",
                "examples": ["open", "under_review", "resolved"]
            },
            "claimAmount": {
                "type": ["number", "null"],
                "description": "Amount claimed by buyer",
                "minimum": 0,
                "examples": [99.99, 0, null]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "resolution": {
                "type": ["string", "null"],
                "description": "Resolution outcome",
                "enum": ["refund_full", "refund_partial", "replacement", "favor_buyer", "favor_seller", "withdrawn", "split", "other", null],
                "examples": ["refund_full", "refund_partial", null]
            },
            "resolutionAmount": {
                "type": ["number", "null"],
                "description": "Amount refunded/resolved",
                "minimum": 0,
                "examples": [99.99, 50.00, null]
            },
            "assignedTo": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Staff user ID assigned to dispute"
            },
            "evidence": {
                "type": ["array", "null"],
                "description": "Evidence (URLs, document IDs)",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": { "type": "string" },
                        "url": { "type": "string", "format": "uri" },
                        "uploadedBy": { "type": "string", "format": "uuid" },
                        "uploadedAt": { "type": "string", "format": "date-time" }
                    },
                    "required": ["type", "url"]
                },
                "examples": [[{"type": "image", "url": "https://...", "uploadedBy": "user-123", "uploadedAt": "2026-01-25T10:00:00Z"}], null]
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Internal resolution notes",
                "maxLength": 5000,
                "examples": ["Buyer provided proof of non-delivery", null]
            },
            "resolvedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When dispute was resolved"
            },
            "closedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When dispute was closed"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional dispute metadata",
                "additionalProperties": true,
                "examples": [{"escalated": true, "priority": "high"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When dispute was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When dispute was last updated"
            }
        },
        "required": ["orderId", "buyerId", "vendorId", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['dispute', 'marketplace', 'resolution', 'buyer', 'seller', 'claim'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Escrow - Payment hold mechanisms
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Escrow',
    'Escrow payment hold with release conditions and status tracking.',
    'marketplace',
    $JSON${
        "type": "object",
        "description": "Escrow payment hold",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the escrow"
            },
            "escrowNumber": {
                "type": ["string", "null"],
                "description": "Human-readable escrow number",
                "maxLength": 100,
                "examples": ["ESC-2026-001", "E123456", null]
            },
            "orderId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated order ID"
            },
            "buyerId": {
                "type": "string",
                "format": "uuid",
                "description": "Buyer user ID"
            },
            "vendorId": {
                "type": "string",
                "format": "uuid",
                "description": "Vendor/seller ID"
            },
            "amount": {
                "type": "number",
                "description": "Escrow amount",
                "minimum": 0,
                "examples": [99.99, 500.00]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "fee": {
                "type": ["number", "null"],
                "description": "Escrow fee",
                "minimum": 0,
                "examples": [2.99, 0, null]
            },
            "status": {
                "type": "string",
                "description": "Escrow status",
                "enum": ["pending", "funded", "held", "released", "released_partial", "refunded", "disputed", "released_to_seller", "cancelled"],
                "default": "pending",
                "examples": ["pending", "funded", "held", "released"]
            },
            "releaseCondition": {
                "type": ["string", "null"],
                "description": "Condition for release",
                "enum": ["delivery_confirmed", "time_elapsed", "buyer_approval", "dispute_resolved", "manual", null],
                "examples": ["delivery_confirmed", "buyer_approval", null]
            },
            "releaseAfterDays": {
                "type": ["integer", "null"],
                "description": "Auto-release after N days (if time_elapsed)",
                "minimum": 1,
                "examples": [7, 14, 30, null]
            },
            "paymentIntentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Payment intent ID (captured amount)"
            },
            "transactionId": {
                "type": ["string", "null"],
                "description": "Payment provider transaction ID",
                "maxLength": 255,
                "examples": ["ch_1234567890", null]
            },
            "disputeId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated dispute ID (if disputed)"
            },
            "fundedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When funds were captured/held"
            },
            "releasedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When funds were released to vendor"
            },
            "refundedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When funds were refunded to buyer"
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When escrow expires (if applicable)"
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional escrow metadata",
                "additionalProperties": true,
                "examples": [{"holdReason": "awaiting_delivery"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When escrow was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When escrow was last updated"
            }
        },
        "required": ["orderId", "buyerId", "vendorId", "amount", "currency", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['escrow', 'marketplace', 'payment', 'hold', 'release', 'buyer-protection'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Marketplace class templates successfully created: Vendor, Commission, Dispute, Escrow';
END $$;
