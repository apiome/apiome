-- Payment Class Templates
-- Adds payment class templates for payment intents, methods, subscriptions, transactions, and payouts
-- These templates provide reusable patterns for payment processing and financial transactions

SET search_path TO odb, public;

-- =============================================================================
-- PaymentIntent - Pre-authorization data
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PaymentIntent',
    'Payment intent for pre-authorization, capturing payment details before finalizing transaction.',
    'payment',
    $JSON${
        "type": "object",
        "description": "Payment intent for pre-authorization",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the payment intent"
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
            "amount": {
                "type": "number",
                "description": "Amount to be charged",
                "minimum": 0,
                "examples": [99.99, 250.00]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "status": {
                "type": "string",
                "description": "Payment intent status",
                "enum": ["requires_payment_method", "requires_confirmation", "requires_action", "processing", "succeeded", "canceled", "requires_capture"],
                "default": "requires_payment_method",
                "examples": ["requires_payment_method", "processing", "succeeded"]
            },
            "paymentMethodId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Selected payment method ID"
            },
            "paymentMethodType": {
                "type": ["string", "null"],
                "description": "Type of payment method",
                "enum": ["card", "bank_account", "paypal", "apple_pay", "google_pay", "other", null],
                "examples": ["card", "paypal", null]
            },
            "captureMethod": {
                "type": ["string", "null"],
                "description": "When to capture payment",
                "enum": ["automatic", "manual", null],
                "default": "automatic",
                "examples": ["automatic", "manual", null]
            },
            "confirmationMethod": {
                "type": ["string", "null"],
                "description": "Confirmation method",
                "enum": ["automatic", "manual", null],
                "default": "automatic",
                "examples": ["automatic", "manual", null]
            },
            "clientSecret": {
                "type": ["string", "null"],
                "description": "Client secret for frontend confirmation (never expose in API responses)",
                "maxLength": 500,
                "examples": ["pi_xxx_secret_yyy", null]
            },
            "providerIntentId": {
                "type": ["string", "null"],
                "description": "Payment intent ID from provider (Stripe, etc.)",
                "maxLength": 255,
                "examples": ["pi_1234567890", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"orderNumber": "ORD-123", "source": "web"}, null]
            },
            "nextAction": {
                "type": ["object", "null"],
                "description": "Next action required (3D Secure, etc.)",
                "additionalProperties": true,
                "examples": [{"type": "use_stripe_sdk", "use_stripe_sdk": {"type": "three_d_secure_redirect"}}, null]
            },
            "canceledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payment intent was canceled"
            },
            "expiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payment intent expires"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When payment intent was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payment intent was last updated"
            }
        },
        "required": ["amount", "currency", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['payment', 'intent', 'authorization', 'pre-auth', 'stripe'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- PaymentMethod - Saved payment instruments
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PaymentMethod',
    'Saved payment method/instrument for customers with secure token references.',
    'payment',
    $JSON${
        "type": "object",
        "description": "Saved payment method/instrument",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the payment method"
            },
            "customerId": {
                "type": "string",
                "format": "uuid",
                "description": "Customer ID who owns this payment method"
            },
            "type": {
                "type": "string",
                "description": "Payment method type",
                "enum": ["card", "bank_account", "paypal", "apple_pay", "google_pay", "other"],
                "examples": ["card", "bank_account", "paypal"]
            },
            "isDefault": {
                "type": "boolean",
                "description": "Whether this is the default payment method",
                "default": false,
                "examples": [true, false]
            },
            "providerMethodId": {
                "type": ["string", "null"],
                "description": "Payment method ID from provider (Stripe, etc.)",
                "maxLength": 255,
                "examples": ["pm_1234567890", null]
            },
            "card": {
                "type": ["object", "null"],
                "description": "Card details (masked)",
                "properties": {
                    "brand": {
                        "type": ["string", "null"],
                        "enum": ["visa", "mastercard", "amex", "discover", "jcb", "diners", "unionpay", "other", null]
                    },
                    "last4": {
                        "type": ["string", "null"],
                        "pattern": "^\\d{4}$",
                        "maxLength": 4
                    },
                    "expMonth": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": 12
                    },
                    "expYear": {
                        "type": ["integer", "null"],
                        "minimum": 2000
                    },
                    "funding": {
                        "type": ["string", "null"],
                        "enum": ["credit", "debit", "prepaid", "unknown", null]
                    }
                },
                "examples": [{"brand": "visa", "last4": "4242", "expMonth": 12, "expYear": 2025}, null]
            },
            "bankAccount": {
                "type": ["object", "null"],
                "description": "Bank account details (masked)",
                "properties": {
                    "bankName": { "type": ["string", "null"] },
                    "accountType": { "type": ["string", "null"], "enum": ["checking", "savings", null] },
                    "last4": { "type": ["string", "null"], "pattern": "^\\d{4}$" },
                    "routingNumber": { "type": ["string", "null"], "maxLength": 20 }
                },
                "examples": [{"bankName": "Chase", "accountType": "checking", "last4": "0000"}, null]
            },
            "billingDetails": {
                "type": ["object", "null"],
                "description": "Billing address associated with payment method",
                "additionalProperties": true,
                "examples": [{"name": "John Doe", "email": "john@example.com", "address": {"street": "123 Main St", "city": "New York", "state": "NY", "zip": "10001"}}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"nickname": "Work Card"}, null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether payment method is active",
                "default": true,
                "examples": [true, false]
            },
            "lastUsedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payment method was last used"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When payment method was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payment method was last updated"
            }
        },
        "required": ["customerId", "type", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['payment', 'method', 'card', 'bank', 'saved', 'instrument'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Subscription - Recurring payment plans
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Subscription',
    'Recurring subscription with billing cycle, plan details, and status management.',
    'payment',
    $JSON${
        "type": "object",
        "description": "Recurring subscription",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the subscription"
            },
            "customerId": {
                "type": "string",
                "format": "uuid",
                "description": "Customer ID"
            },
            "planId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Subscription plan ID"
            },
            "planName": {
                "type": ["string", "null"],
                "description": "Plan name",
                "maxLength": 255,
                "examples": ["Pro Monthly", "Enterprise Annual", null]
            },
            "status": {
                "type": "string",
                "description": "Subscription status",
                "enum": ["active", "canceled", "past_due", "unpaid", "trialing", "paused", "expired"],
                "default": "active",
                "examples": ["active", "canceled", "past_due"]
            },
            "billingCycle": {
                "type": ["string", "null"],
                "description": "Billing cycle",
                "enum": ["daily", "weekly", "monthly", "quarterly", "yearly", null],
                "examples": ["monthly", "yearly", null]
            },
            "billingInterval": {
                "type": ["integer", "null"],
                "description": "Billing interval (e.g., 1 for monthly, 3 for quarterly)",
                "minimum": 1,
                "examples": [1, 3, 12, null]
            },
            "amount": {
                "type": ["number", "null"],
                "description": "Recurring amount",
                "minimum": 0,
                "examples": [29.99, 299.00, null]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "trialEndsAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When trial period ends"
            },
            "currentPeriodStart": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Start of current billing period"
            },
            "currentPeriodEnd": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "End of current billing period"
            },
            "canceledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When subscription was canceled"
            },
            "cancelAtPeriodEnd": {
                "type": ["boolean", "null"],
                "description": "Whether to cancel at end of current period",
                "default": false,
                "examples": [true, false, null]
            },
            "cancelReason": {
                "type": ["string", "null"],
                "description": "Reason for cancellation",
                "maxLength": 500,
                "examples": ["Customer requested", "Payment failed", null]
            },
            "paymentMethodId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Default payment method ID"
            },
            "providerSubscriptionId": {
                "type": ["string", "null"],
                "description": "Subscription ID from provider (Stripe, etc.)",
                "maxLength": 255,
                "examples": ["sub_1234567890", null]
            },
            "quantity": {
                "type": ["integer", "null"],
                "description": "Subscription quantity (for metered/seat-based)",
                "minimum": 1,
                "default": 1,
                "examples": [1, 5, 10, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"teamId": "team-123"}, null]
            },
            "startedAt": {
                "type": "string",
                "format": "date-time",
                "description": "When subscription started"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When subscription was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When subscription was last updated"
            }
        },
        "required": ["customerId", "status", "startedAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['subscription', 'recurring', 'billing', 'payment', 'plan'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Transaction - Payment transaction records
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Transaction',
    'Payment transaction record with provider integration, fees, and detailed status tracking.',
    'payment',
    $JSON${
        "type": "object",
        "description": "Payment transaction record",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the transaction"
            },
            "transactionNumber": {
                "type": ["string", "null"],
                "description": "Human-readable transaction number",
                "maxLength": 100,
                "examples": ["TXN-2026-001", "T123456", null]
            },
            "orderId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated order ID"
            },
            "paymentIntentId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated payment intent ID"
            },
            "subscriptionId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Associated subscription ID (for recurring payments)"
            },
            "customerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Customer ID"
            },
            "paymentMethodId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Payment method used"
            },
            "type": {
                "type": "string",
                "description": "Transaction type",
                "enum": ["charge", "refund", "authorization", "capture", "void", "adjustment", "payout"],
                "examples": ["charge", "refund", "authorization"]
            },
            "amount": {
                "type": "number",
                "description": "Transaction amount (positive for charges, negative for refunds)",
                "examples": [99.99, -50.00, 250.00]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "fee": {
                "type": ["number", "null"],
                "description": "Processing fee amount",
                "minimum": 0,
                "examples": [2.90, 0, null]
            },
            "netAmount": {
                "type": ["number", "null"],
                "description": "Net amount after fees (amount - fee)",
                "examples": [97.09, 0, null]
            },
            "status": {
                "type": "string",
                "description": "Transaction status",
                "enum": ["pending", "processing", "completed", "failed", "canceled", "refunded", "disputed"],
                "default": "pending",
                "examples": ["pending", "completed", "failed"]
            },
            "providerTransactionId": {
                "type": ["string", "null"],
                "description": "Transaction ID from payment provider",
                "maxLength": 255,
                "examples": ["ch_1234567890", "txn_abc123", null]
            },
            "providerStatus": {
                "type": ["string", "null"],
                "description": "Status from payment provider",
                "maxLength": 50,
                "examples": ["succeeded", "pending", "failed", null]
            },
            "providerResponse": {
                "type": ["object", "null"],
                "description": "Raw response from payment provider",
                "additionalProperties": true,
                "examples": [{"id": "ch_123", "status": "succeeded"}, null]
            },
            "failureReason": {
                "type": ["string", "null"],
                "description": "Reason for failure",
                "maxLength": 500,
                "examples": ["Insufficient funds", "Card declined", null]
            },
            "failureCode": {
                "type": ["string", "null"],
                "description": "Provider error code",
                "maxLength": 50,
                "examples": ["card_declined", "insufficient_funds", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Transaction description",
                "maxLength": 500,
                "examples": ["Order #1234", "Monthly subscription", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"orderNumber": "ORD-123"}, null]
            },
            "processedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When transaction was processed"
            },
            "settledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When transaction was settled (funds available)"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When transaction was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When transaction was last updated"
            }
        },
        "required": ["type", "amount", "currency", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['transaction', 'payment', 'charge', 'refund', 'finance'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Payout - Vendor/affiliate payments
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Payout',
    'Payout to vendors, affiliates, or partners with bank transfer details and status tracking.',
    'payment',
    $JSON${
        "type": "object",
        "description": "Payout to vendor, affiliate, or partner",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the payout"
            },
            "payoutNumber": {
                "type": ["string", "null"],
                "description": "Human-readable payout number",
                "maxLength": 100,
                "examples": ["PAYOUT-2026-001", "P123456", null]
            },
            "recipientId": {
                "type": "string",
                "format": "uuid",
                "description": "Recipient (vendor, affiliate, partner) ID"
            },
            "recipientType": {
                "type": ["string", "null"],
                "description": "Type of recipient",
                "enum": ["vendor", "affiliate", "partner", "contractor", "other", null],
                "examples": ["vendor", "affiliate", null]
            },
            "amount": {
                "type": "number",
                "description": "Payout amount",
                "minimum": 0,
                "examples": [500.00, 1250.50]
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR"]
            },
            "fee": {
                "type": ["number", "null"],
                "description": "Processing fee (deducted from amount)",
                "minimum": 0,
                "examples": [2.50, 0, null]
            },
            "netAmount": {
                "type": ["number", "null"],
                "description": "Net amount after fees (amount - fee)",
                "minimum": 0,
                "examples": [497.50, 0, null]
            },
            "status": {
                "type": "string",
                "description": "Payout status",
                "enum": ["pending", "processing", "in_transit", "paid", "failed", "canceled", "reversed"],
                "default": "pending",
                "examples": ["pending", "processing", "paid"]
            },
            "method": {
                "type": ["string", "null"],
                "description": "Payout method",
                "enum": ["bank_transfer", "ach", "wire", "check", "paypal", "crypto", "other", null],
                "examples": ["bank_transfer", "ach", null]
            },
            "bankAccount": {
                "type": ["object", "null"],
                "description": "Bank account details for transfer",
                "properties": {
                    "accountHolderName": { "type": ["string", "null"] },
                    "accountNumber": { "type": ["string", "null"], "maxLength": 50 },
                    "routingNumber": { "type": ["string", "null"], "maxLength": 20 },
                    "bankName": { "type": ["string", "null"] },
                    "accountType": { "type": ["string", "null"], "enum": ["checking", "savings", null] },
                    "swiftCode": { "type": ["string", "null"], "maxLength": 20 }
                },
                "examples": [{"accountHolderName": "Acme Corp", "routingNumber": "123456789", "accountType": "checking"}, null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Payout description",
                "maxLength": 500,
                "examples": ["Q1 2026 affiliate commission", "Vendor payment for order #123", null]
            },
            "periodStart": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Start of payout period"
            },
            "periodEnd": {
                "type": ["string", "null"],
                "format": "date",
                "description": "End of payout period"
            },
            "providerPayoutId": {
                "type": ["string", "null"],
                "description": "Payout ID from provider (Stripe, PayPal, etc.)",
                "maxLength": 255,
                "examples": ["po_1234567890", null]
            },
            "providerStatus": {
                "type": ["string", "null"],
                "description": "Status from payout provider",
                "maxLength": 50,
                "examples": ["paid", "pending", "failed", null]
            },
            "failureReason": {
                "type": ["string", "null"],
                "description": "Reason for failure",
                "maxLength": 500,
                "examples": ["Invalid bank account", "Insufficient balance", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional metadata",
                "additionalProperties": true,
                "examples": [{"commissionRate": "0.10", "orders": ["ord-1", "ord-2"]}, null]
            },
            "scheduledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payout is scheduled"
            },
            "processedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payout was processed"
            },
            "paidAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payout was paid/transferred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When payout was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When payout was last updated"
            }
        },
        "required": ["recipientId", "amount", "currency", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['payout', 'vendor', 'affiliate', 'commission', 'payment', 'transfer'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Payment class templates successfully created: PaymentIntent, PaymentMethod, Subscription, Transaction, Payout';
END $$;
