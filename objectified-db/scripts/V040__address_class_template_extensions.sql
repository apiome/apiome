-- Address Class Template Extensions
-- Adds specialized address templates that extend the base Address template
-- BillingAddress - extends Address with billing-specific fields
-- ShippingAddress - extends Address with delivery instructions
-- AddressValidation - standalone template for address verification metadata

SET search_path TO odb, public;

-- =============================================================================
-- BillingAddress - Extends Address with billing-specific fields
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'BillingAddress',
    'Billing address extending Address with billing-specific fields such as tax ID, company name, and payment information.',
    'address',
    $JSON${
        "type": "object",
        "description": "Billing address with additional billing-specific information",
        "allOf": [
            {
                "$ref": "#/components/schemas/Address"
            },
            {
                "type": "object",
                "properties": {
                    "taxId": {
                        "type": ["string", "null"],
                        "description": "Tax identification number (VAT, EIN, etc.)",
                        "maxLength": 50,
                        "examples": ["US-12-3456789", "GB123456789", null]
                    },
                    "companyName": {
                        "type": ["string", "null"],
                        "description": "Company or business name for billing",
                        "maxLength": 255,
                        "examples": ["Acme Corporation", "John Doe LLC", null]
                    },
                    "billingContactName": {
                        "type": ["string", "null"],
                        "description": "Contact person name for billing inquiries",
                        "maxLength": 255,
                        "examples": ["Jane Smith", "Accounts Payable", null]
                    },
                    "billingContactEmail": {
                        "type": ["string", "null"],
                        "format": "email",
                        "description": "Email address for billing contact",
                        "maxLength": 255,
                        "examples": ["billing@example.com", null]
                    },
                    "billingContactPhone": {
                        "type": ["string", "null"],
                        "description": "Phone number for billing contact",
                        "maxLength": 50,
                        "examples": ["+1-555-123-4567", null]
                    },
                    "paymentMethod": {
                        "type": ["string", "null"],
                        "description": "Preferred payment method",
                        "enum": ["credit_card", "debit_card", "bank_transfer", "check", "paypal", "other", null],
                        "examples": ["credit_card", "bank_transfer", null]
                    },
                    "paymentTerms": {
                        "type": ["string", "null"],
                        "description": "Payment terms (e.g., Net 30, Net 60)",
                        "maxLength": 50,
                        "examples": ["Net 30", "Net 60", "Due on Receipt", null]
                    },
                    "purchaseOrderNumber": {
                        "type": ["string", "null"],
                        "description": "Purchase order number if applicable",
                        "maxLength": 100,
                        "examples": ["PO-2026-001", null]
                    }
                }
            }
        ]
    }$JSON$::jsonb,
    ARRAY['address', 'billing', 'payment', 'invoice', 'finance'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ShippingAddress - Extends Address with delivery instructions
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ShippingAddress',
    'Shipping address extending Address with delivery instructions, preferred delivery times, and contact information for delivery.',
    'address',
    $JSON${
        "type": "object",
        "description": "Shipping address with delivery instructions and preferences",
        "allOf": [
            {
                "$ref": "#/components/schemas/Address"
            },
            {
                "type": "object",
                "properties": {
                    "deliveryInstructions": {
                        "type": ["string", "null"],
                        "description": "Special delivery instructions for the carrier",
                        "maxLength": 500,
                        "examples": ["Leave at front door", "Ring doorbell twice", "Use side entrance", null]
                    },
                    "preferredDeliveryTime": {
                        "type": ["string", "null"],
                        "description": "Preferred time window for delivery",
                        "maxLength": 100,
                        "examples": ["Morning (9am-12pm)", "Afternoon (12pm-5pm)", "Evening (5pm-8pm)", null]
                    },
                    "deliveryContactName": {
                        "type": ["string", "null"],
                        "description": "Contact person name for delivery",
                        "maxLength": 255,
                        "examples": ["John Doe", "Reception", null]
                    },
                    "deliveryContactPhone": {
                        "type": ["string", "null"],
                        "description": "Phone number for delivery contact",
                        "maxLength": 50,
                        "examples": ["+1-555-123-4567", null]
                    },
                    "accessCode": {
                        "type": ["string", "null"],
                        "description": "Access code, gate code, or building entry code",
                        "maxLength": 50,
                        "examples": ["1234", "#5678", "BUILDING-A", null]
                    },
                    "floor": {
                        "type": ["string", "null"],
                        "description": "Floor or level number",
                        "maxLength": 20,
                        "examples": ["3rd Floor", "Floor 5", "Ground Floor", null]
                    },
                    "apartmentNumber": {
                        "type": ["string", "null"],
                        "description": "Apartment, suite, or unit number",
                        "maxLength": 50,
                        "examples": ["Apt 4B", "Suite 500", "Unit 12", null]
                    },
                    "deliveryType": {
                        "type": ["string", "null"],
                        "description": "Type of delivery service preferred",
                        "enum": ["standard", "express", "overnight", "same_day", "pickup", "other", null],
                        "examples": ["standard", "express", null]
                    },
                    "signatureRequired": {
                        "type": ["boolean", "null"],
                        "description": "Whether signature is required upon delivery",
                        "default": false,
                        "examples": [true, false, null]
                    },
                    "leaveIfNoAnswer": {
                        "type": ["boolean", "null"],
                        "description": "Whether to leave package if no one answers",
                        "default": false,
                        "examples": [true, false, null]
                    }
                }
            }
        ]
    }$JSON$::jsonb,
    ARRAY['address', 'shipping', 'delivery', 'logistics', 'fulfillment'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- AddressValidation - Address verification metadata
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'AddressValidation',
    'Address validation and verification metadata for tracking address verification status, source, confidence, and corrections.',
    'address',
    $JSON${
        "type": "object",
        "description": "Metadata for address validation and verification",
        "properties": {
            "isValidated": {
                "type": "boolean",
                "description": "Whether the address has been validated",
                "default": false,
                "examples": [true, false]
            },
            "validationSource": {
                "type": ["string", "null"],
                "description": "Source or service used for validation",
                "enum": ["usps", "ups", "fedex", "google_maps", "smarty_streets", "loqate", "manual", "other", null],
                "examples": ["usps", "google_maps", "smarty_streets", null]
            },
            "validationDate": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Date and time when validation was performed",
                "examples": ["2026-01-25T10:30:00Z", null]
            },
            "confidenceScore": {
                "type": ["number", "null"],
                "description": "Confidence score of validation (0.0 to 1.0)",
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.95, 0.75, 0.5, null]
            },
            "validationStatus": {
                "type": ["string", "null"],
                "description": "Status of the validation",
                "enum": ["valid", "invalid", "partial", "ambiguous", "not_found", "pending", null],
                "examples": ["valid", "partial", "invalid", null]
            },
            "originalAddress": {
                "type": ["string", "null"],
                "description": "Original address string before validation",
                "maxLength": 500,
                "examples": ["123 Main St", "1600 Pennsylvania Ave NW", null]
            },
            "correctedAddress": {
                "type": ["string", "null"],
                "description": "Corrected or standardized address string",
                "maxLength": 500,
                "examples": ["123 Main Street", "1600 Pennsylvania Avenue NW", null]
            },
            "corrections": {
                "type": ["object", "null"],
                "description": "Detailed corrections made during validation",
                "additionalProperties": true,
                "examples": [
                    {
                        "streetAddress": "Changed 'St' to 'Street'",
                        "postalCode": "Added missing ZIP+4 extension"
                    },
                    null
                ]
            },
            "suggestions": {
                "type": ["array", "null"],
                "description": "Suggested address alternatives if validation found issues",
                "items": {
                    "type": "string"
                },
                "examples": [
                    ["123 Main Street", "123 Main St Apt 2"],
                    null
                ]
            },
            "warnings": {
                "type": ["array", "null"],
                "description": "Warnings or issues found during validation",
                "items": {
                    "type": "string"
                },
                "examples": [
                    ["Address may not receive mail delivery", "Missing apartment number"],
                    null
                ]
            },
            "errors": {
                "type": ["array", "null"],
                "description": "Errors found during validation",
                "items": {
                    "type": "string"
                },
                "examples": [
                    ["Invalid postal code", "Street name not found"],
                    null
                ]
            },
            "geocoded": {
                "type": ["boolean", "null"],
                "description": "Whether the address has been geocoded (has coordinates)",
                "default": false,
                "examples": [true, false, null]
            },
            "latitude": {
                "type": ["number", "null"],
                "description": "Latitude coordinate from geocoding",
                "minimum": -90,
                "maximum": 90,
                "examples": [37.4220656, null]
            },
            "longitude": {
                "type": ["number", "null"],
                "description": "Longitude coordinate from geocoding",
                "minimum": -180,
                "maximum": 180,
                "examples": [-122.0840897, null]
            },
            "geocodingAccuracy": {
                "type": ["string", "null"],
                "description": "Accuracy level of geocoding",
                "enum": ["rooftop", "rangeInterpolated", "geometric", "approximate", null],
                "examples": ["rooftop", "approximate", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "Timezone for the address location",
                "maxLength": 50,
                "examples": ["America/Los_Angeles", "Europe/London", null]
            },
            "carrierRoute": {
                "type": ["string", "null"],
                "description": "USPS carrier route code",
                "maxLength": 10,
                "examples": ["C001", "R123", null]
            },
            "deliveryPointCode": {
                "type": ["string", "null"],
                "description": "USPS delivery point code",
                "maxLength": 10,
                "examples": ["12", "AB", null]
            },
            "lastValidatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Last time this address was validated",
                "examples": ["2026-01-25T10:30:00Z", null]
            },
            "validationExpiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When validation expires (if applicable)",
                "examples": ["2027-01-25T10:30:00Z", null]
            }
        },
        "required": ["isValidated"]
    }$JSON$::jsonb,
    ARRAY['address', 'validation', 'verification', 'geocoding', 'metadata'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Create dependency records for templates that extend Address
-- =============================================================================

-- BillingAddress depends on Address (via allOf)
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    ba.id as template_id,
    a.id as depends_on_template_id,
    '#/components/schemas/Address' as ref_path,
    NULL as property_name,  -- NULL because this is schema-level inheritance via allOf, not a property reference
    true as is_required
FROM class_templates ba, class_templates a
WHERE ba.name = 'BillingAddress' AND ba.is_system = true
  AND a.name = 'Address' AND a.is_system = true
ON CONFLICT DO NOTHING;

-- ShippingAddress depends on Address (via allOf)
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    sa.id as template_id,
    a.id as depends_on_template_id,
    '#/components/schemas/Address' as ref_path,
    NULL as property_name,  -- NULL because this is schema-level inheritance via allOf, not a property reference
    true as is_required
FROM class_templates sa, class_templates a
WHERE sa.name = 'ShippingAddress' AND sa.is_system = true
  AND a.name = 'Address' AND a.is_system = true
ON CONFLICT DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Address class template extensions successfully created: BillingAddress, ShippingAddress, AddressValidation';
    RAISE NOTICE 'Dependency records created for BillingAddress and ShippingAddress extending Address';
END $$;
