-- Orders Class Templates
-- Adds order management class templates for carts, order items, refunds, shipments, and invoices
-- These templates provide reusable patterns for e-commerce and order processing systems

SET search_path TO apiome, public;

-- =============================================================================
-- Cart - Shopping cart with items
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Cart',
    'Shopping cart with items, pricing, discounts, and session management.',
    'order',
    $JSON${
        "type": "object",
        "description": "Shopping cart with items and pricing",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the cart"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null for guest cart)"
            },
            "sessionId": {
                "type": ["string", "null"],
                "description": "Session ID for guest carts",
                "maxLength": 255,
                "examples": ["sess_abc123", null]
            },
            "items": {
                "type": "array",
                "description": "Cart items",
                "items": {
                    "type": "object",
                    "properties": {
                        "productId": {
                            "type": "string",
                            "format": "uuid",
                            "description": "Product ID"
                        },
                        "variantId": {
                            "type": ["string", "null"],
                            "format": "uuid",
                            "description": "Product variant ID (size, color, etc.)"
                        },
                        "name": {
                            "type": "string",
                            "description": "Product name",
                            "maxLength": 255
                        },
                        "sku": {
                            "type": ["string", "null"],
                            "description": "SKU at time of cart",
                            "maxLength": 100
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Quantity",
                            "minimum": 1
                        },
                        "unitPrice": {
                            "type": "number",
                            "description": "Price per unit",
                            "minimum": 0
                        },
                        "currency": {
                            "type": ["string", "null"],
                            "description": "Currency code",
                            "pattern": "^[A-Z]{3}$"
                        },
                        "imageUrl": {
                            "type": ["string", "null"],
                            "format": "uri",
                            "description": "Product image URL"
                        }
                    },
                    "required": ["productId", "name", "quantity", "unitPrice"]
                },
                "minItems": 0,
                "default": []
            },
            "subtotal": {
                "type": ["number", "null"],
                "description": "Subtotal before discounts/tax/shipping",
                "minimum": 0,
                "examples": [100.00, 0, null]
            },
            "discountAmount": {
                "type": ["number", "null"],
                "description": "Total discount amount",
                "minimum": 0,
                "examples": [10.00, 0, null]
            },
            "taxAmount": {
                "type": ["number", "null"],
                "description": "Estimated tax amount",
                "minimum": 0,
                "examples": [8.50, 0, null]
            },
            "shippingAmount": {
                "type": ["number", "null"],
                "description": "Estimated shipping cost",
                "minimum": 0,
                "examples": [5.99, 0, null]
            },
            "total": {
                "type": ["number", "null"],
                "description": "Total cart amount",
                "minimum": 0,
                "examples": [104.49, 0, null]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "couponCode": {
                "type": ["string", "null"],
                "description": "Applied coupon/promo code",
                "maxLength": 50,
                "examples": ["SAVE10", "FREESHIP", null]
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When cart expires (for abandoned cart recovery)"
            },
            "abandonedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When cart was marked as abandoned"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When cart was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When cart was last updated"
            }
        },
        "required": ["items", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['cart', 'shopping', 'basket', 'order', 'ecommerce'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- EnhancedOrderItem - Enhanced line item with additional fields
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'EnhancedOrderItem',
    'Enhanced order line item with discounts, taxes, variants, and fulfillment tracking.',
    'order',
    $JSON${
        "type": "object",
        "description": "Enhanced line item in an order",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the line item"
            },
            "orderId": {
                "type": "string",
                "format": "uuid",
                "description": "Parent order reference"
            },
            "productId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product reference"
            },
            "variantId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Product variant ID (size, color, etc.)"
            },
            "sku": {
                "type": ["string", "null"],
                "description": "SKU at time of order",
                "maxLength": 100,
                "examples": ["PROD-123-RED-L", null]
            },
            "name": {
                "type": "string",
                "description": "Product name at time of order",
                "maxLength": 500,
                "examples": ["T-Shirt - Red - Large"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Product description at time of order",
                "maxLength": 2000,
                "examples": ["100% cotton t-shirt", null]
            },
            "imageUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Product image URL at time of order"
            },
            "quantity": {
                "type": "integer",
                "description": "Quantity ordered",
                "minimum": 1,
                "examples": [1, 2, 5]
            },
            "unitPrice": {
                "type": "number",
                "description": "Price per unit at time of order",
                "minimum": 0,
                "examples": [29.99, 49.95]
            },
            "discountAmount": {
                "type": ["number", "null"],
                "description": "Discount amount for this line item",
                "minimum": 0,
                "examples": [5.00, 0, null]
            },
            "taxAmount": {
                "type": ["number", "null"],
                "description": "Tax amount for this line item",
                "minimum": 0,
                "examples": [2.40, 0, null]
            },
            "totalPrice": {
                "type": "number",
                "description": "Line item total (quantity * unitPrice - discount + tax)",
                "minimum": 0,
                "examples": [27.39, 99.90]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "fulfillmentStatus": {
                "type": ["string", "null"],
                "description": "Fulfillment status",
                "enum": ["pending", "processing", "shipped", "delivered", "cancelled", "returned", null],
                "examples": ["pending", "shipped", null]
            },
            "shipmentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated shipment ID"
            },
            "refundedQuantity": {
                "type": ["integer", "null"],
                "description": "Quantity refunded",
                "minimum": 0,
                "examples": [0, 1, 2, null]
            },
            "refundedAmount": {
                "type": ["number", "null"],
                "description": "Amount refunded",
                "minimum": 0,
                "examples": [0, 27.39, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional item metadata",
                "additionalProperties": true,
                "examples": [{"giftMessage": "Happy Birthday!"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When line item was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When line item was last updated"
            }
        },
        "required": ["orderId", "name", "quantity", "unitPrice", "totalPrice", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['order', 'item', 'line-item', 'ecommerce', 'fulfillment'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Refund - Refund requests and processing
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Refund',
    'Refund request and processing with amounts, reasons, status, and payment provider integration.',
    'order',
    $JSON${
        "type": "object",
        "description": "Refund request and processing",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the refund"
            },
            "orderId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated order ID"
            },
            "paymentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated payment ID"
            },
            "refundNumber": {
                "type": ["string", "null"],
                "description": "Human-readable refund number",
                "maxLength": 100,
                "examples": ["REF-2026-001", "R123456", null]
            },
            "amount": {
                "type": "number",
                "description": "Refund amount",
                "minimum": 0,
                "examples": [99.99, 50.00]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "reason": {
                "type": ["string", "null"],
                "description": "Refund reason",
                "enum": ["customer_request", "defective", "wrong_item", "not_delivered", "duplicate", "fraudulent", "other", null],
                "examples": ["customer_request", "defective", null]
            },
            "reasonText": {
                "type": ["string", "null"],
                "description": "Detailed refund reason text",
                "maxLength": 1000,
                "examples": ["Customer requested refund due to change of mind", null]
            },
            "status": {
                "type": "string",
                "description": "Refund status",
                "enum": ["pending", "processing", "approved", "completed", "rejected", "cancelled"],
                "default": "pending",
                "examples": ["pending", "processing", "completed"]
            },
            "refundType": {
                "type": ["string", "null"],
                "description": "Type of refund",
                "enum": ["full", "partial", null],
                "examples": ["full", "partial", null]
            },
            "items": {
                "type": ["array", "null"],
                "description": "Order items being refunded",
                "items": {
                    "type": "object",
                    "properties": {
                        "orderItemId": { "type": "string", "format": "uuid" },
                        "quantity": { "type": "integer", "minimum": 1 },
                        "amount": { "type": "number", "minimum": 0 }
                    },
                    "required": ["orderItemId", "quantity", "amount"]
                },
                "examples": [[{"orderItemId": "item-123", "quantity": 1, "amount": 29.99}], null]
            },
            "requestedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who requested the refund"
            },
            "processedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who processed the refund"
            },
            "providerRefundId": {
                "type": ["string", "null"],
                "description": "Refund ID from payment provider (Stripe, PayPal, etc.)",
                "maxLength": 255,
                "examples": ["re_abc123", "refund_xyz", null]
            },
            "providerStatus": {
                "type": ["string", "null"],
                "description": "Status from payment provider",
                "maxLength": 50,
                "examples": ["succeeded", "pending", "failed", null]
            },
            "requestedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When refund was requested"
            },
            "processedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When refund was processed"
            },
            "completedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When refund was completed"
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Internal notes about the refund",
                "maxLength": 2000,
                "examples": ["Customer called to request refund", null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When refund record was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When refund was last updated"
            }
        },
        "required": ["orderId", "amount", "currency", "status", "requestedAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['refund', 'order', 'payment', 'ecommerce', 'return'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Shipment - Tracking and delivery status
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Shipment',
    'Shipment tracking and delivery status with carrier information and tracking events.',
    'order',
    $JSON${
        "type": "object",
        "description": "Shipment tracking and delivery information",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the shipment"
            },
            "orderId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated order ID"
            },
            "shipmentNumber": {
                "type": ["string", "null"],
                "description": "Human-readable shipment number",
                "maxLength": 100,
                "examples": ["SHIP-2026-001", "S123456", null]
            },
            "trackingNumber": {
                "type": ["string", "null"],
                "description": "Carrier tracking number",
                "maxLength": 100,
                "examples": ["1Z999AA10123456784", "9400111899223197428490", null]
            },
            "carrier": {
                "type": ["string", "null"],
                "description": "Shipping carrier",
                "enum": ["ups", "fedex", "usps", "dhl", "amazon", "other", null],
                "examples": ["ups", "fedex", "usps", null]
            },
            "carrierName": {
                "type": ["string", "null"],
                "description": "Carrier display name",
                "maxLength": 100,
                "examples": ["UPS", "FedEx Ground", null]
            },
            "service": {
                "type": ["string", "null"],
                "description": "Shipping service level",
                "maxLength": 100,
                "examples": ["Ground", "Express", "Overnight", null]
            },
            "status": {
                "type": "string",
                "description": "Shipment status",
                "enum": ["pending", "label_created", "in_transit", "out_for_delivery", "delivered", "exception", "returned"],
                "default": "pending",
                "examples": ["pending", "in_transit", "delivered"]
            },
            "estimatedDeliveryDate": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Estimated delivery date"
            },
            "estimatedDeliveryTime": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Estimated delivery date and time"
            },
            "actualDeliveryDate": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Actual delivery date"
            },
            "actualDeliveryTime": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Actual delivery date and time"
            },
            "shippedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When shipment was shipped"
            },
            "deliveredAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When shipment was delivered"
            },
            "weight": {
                "type": ["number", "null"],
                "description": "Package weight in specified unit",
                "minimum": 0,
                "examples": [2.5, 10.0, null]
            },
            "weightUnit": {
                "type": ["string", "null"],
                "description": "Weight unit",
                "enum": ["lb", "kg", "oz", "g", null],
                "examples": ["lb", "kg", null]
            },
            "dimensions": {
                "type": ["object", "null"],
                "description": "Package dimensions",
                "properties": {
                    "length": { "type": "number", "minimum": 0 },
                    "width": { "type": "number", "minimum": 0 },
                    "height": { "type": "number", "minimum": 0 },
                    "unit": { "type": "string", "enum": ["in", "cm", "m"] }
                },
                "examples": [{"length": 12, "width": 8, "height": 6, "unit": "in"}, null]
            },
            "trackingUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Carrier tracking page URL",
                "examples": ["https://www.ups.com/track?tracknum=1Z999AA10123456784", null]
            },
            "events": {
                "type": ["array", "null"],
                "description": "Tracking events from carrier",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp": { "type": "string", "format": "date-time" },
                        "status": { "type": "string" },
                        "location": { "type": "string" },
                        "description": { "type": "string" }
                    },
                    "required": ["timestamp", "status"]
                },
                "examples": [[{"timestamp": "2026-01-25T10:00:00Z", "status": "in_transit", "location": "Chicago, IL", "description": "In transit"}], null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When shipment was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When shipment was last updated"
            }
        },
        "required": ["orderId", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['shipment', 'shipping', 'tracking', 'delivery', 'order', 'logistics'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Invoice - Billing documents
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Invoice',
    'Invoice/billing document with line items, taxes, payment status, and PDF generation metadata.',
    'order',
    $JSON${
        "type": "object",
        "description": "Invoice/billing document",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the invoice"
            },
            "invoiceNumber": {
                "type": "string",
                "description": "Human-readable invoice number",
                "maxLength": 100,
                "examples": ["INV-2026-001", "2026-0001", "INV123456"]
            },
            "orderId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated order ID"
            },
            "customerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Customer ID"
            },
            "billingAddress": {
                "type": ["object", "null"],
                "description": "Billing address",
                "additionalProperties": true,
                "examples": [{"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001"}, null]
            },
            "items": {
                "type": "array",
                "description": "Invoice line items",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": { "type": "string" },
                        "quantity": { "type": "integer", "minimum": 1 },
                        "unitPrice": { "type": "number", "minimum": 0 },
                        "total": { "type": "number", "minimum": 0 },
                        "taxAmount": { "type": "number", "minimum": 0 }
                    },
                    "required": ["description", "quantity", "unitPrice", "total"]
                },
                "minItems": 0,
                "default": []
            },
            "subtotal": {
                "type": "number",
                "description": "Subtotal before tax",
                "minimum": 0,
                "examples": [100.00, 250.50]
            },
            "taxAmount": {
                "type": ["number", "null"],
                "description": "Total tax amount",
                "minimum": 0,
                "examples": [8.00, 0, null]
            },
            "discountAmount": {
                "type": ["number", "null"],
                "description": "Total discount amount",
                "minimum": 0,
                "examples": [10.00, 0, null]
            },
            "shippingAmount": {
                "type": ["number", "null"],
                "description": "Shipping amount",
                "minimum": 0,
                "examples": [5.99, 0, null]
            },
            "total": {
                "type": "number",
                "description": "Total invoice amount",
                "minimum": 0,
                "examples": [103.99, 250.50]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "status": {
                "type": "string",
                "description": "Invoice status",
                "enum": ["draft", "pending", "sent", "paid", "overdue", "cancelled", "refunded"],
                "default": "draft",
                "examples": ["draft", "sent", "paid"]
            },
            "dueDate": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Payment due date"
            },
            "paidAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When invoice was paid"
            },
            "paidAmount": {
                "type": ["number", "null"],
                "description": "Amount paid",
                "minimum": 0,
                "examples": [103.99, 0, null]
            },
            "balance": {
                "type": ["number", "null"],
                "description": "Remaining balance",
                "minimum": 0,
                "examples": [0, 50.00, null]
            },
            "paymentMethod": {
                "type": ["string", "null"],
                "description": "Payment method used",
                "maxLength": 100,
                "examples": ["credit_card", "bank_transfer", null]
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Invoice notes",
                "maxLength": 2000,
                "examples": ["Payment terms: Net 30", null]
            },
            "pdfUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "URL to generated PDF invoice",
                "examples": ["https://storage.example.com/invoices/inv-123.pdf", null]
            },
            "issuedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When invoice was issued"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When invoice was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When invoice was last updated"
            }
        },
        "required": ["invoiceNumber", "subtotal", "total", "currency", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['invoice', 'billing', 'document', 'order', 'payment', 'accounting'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Orders class templates successfully created: Cart, EnhancedOrderItem, Refund, Shipment, Invoice';
END $$;
