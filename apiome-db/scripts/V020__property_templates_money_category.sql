-- Property Templates: Money Category
-- These templates define common monetary patterns for storing currency amounts and financial data
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO apiome, public;

-- =============================================================================
-- BASIC AMOUNT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amount',
           'Numeric monetary amount. Use with a separate currency field for complete money representation.',
           'money',
           '{
               "type": "number",
               "description": "Monetary amount",
               "examples": [99.99, 1000, 49.95, 0.01],
               "minimum": 0
           }',
           ARRAY['amount', 'money', 'numeric', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amountSigned',
           'Signed numeric monetary amount allowing negative values for debits, refunds, or adjustments.',
           'money',
           '{
               "type": "number",
               "description": "Signed monetary amount (positive or negative)",
               "examples": [99.99, -50.00, 1000, -25.50]
           }',
           ARRAY['amount', 'money', 'numeric', 'signed', 'debit', 'credit'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amountInteger',
           'Monetary amount as integer in minor currency units (e.g., cents). Avoids floating-point precision issues.',
           'money',
           '{
               "type": "integer",
               "description": "Monetary amount in minor units (e.g., cents)",
               "examples": [9999, 100000, 4995, 1],
               "minimum": 0
           }',
           ARRAY['amount', 'money', 'integer', 'cents', 'minor-units'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amountIntegerSigned',
           'Signed monetary amount as integer in minor currency units. Allows negative values.',
           'money',
           '{
               "type": "integer",
               "description": "Signed monetary amount in minor units (e.g., cents)",
               "examples": [9999, -5000, 100000, -2550]
           }',
           ARRAY['amount', 'money', 'integer', 'cents', 'minor-units', 'signed'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amountString',
           'Monetary amount as a string to preserve exact decimal representation.',
           'money',
           '{
               "type": "string",
               "description": "Monetary amount as string for precision",
               "examples": ["99.99", "1000.00", "49.95", "0.01"],
               "pattern": "^-?[0-9]+(\\.[0-9]{1,4})?$"
           }',
           ARRAY['amount', 'money', 'string', 'precision'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'amountNullable',
           'Nullable monetary amount for optional price fields.',
           'money',
           '{
               "type": ["number", "null"],
               "description": "Optional monetary amount",
               "examples": [99.99, 1000, null],
               "minimum": 0
           }',
           ARRAY['amount', 'money', 'numeric', 'nullable', 'optional'],
           true,
           true
       );

-- =============================================================================
-- CURRENCY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currency',
           'ISO 4217 three-letter currency code.',
           'money',
           '{
               "type": "string",
               "description": "ISO 4217 currency code",
               "examples": ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF"],
               "pattern": "^[A-Z]{3}$",
               "minLength": 3,
               "maxLength": 3
           }',
           ARRAY['currency', 'iso4217', 'code'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currencyNumeric',
           'ISO 4217 numeric currency code.',
           'money',
           '{
               "type": "string",
               "description": "ISO 4217 numeric currency code",
               "examples": ["840", "978", "826", "392", "124"],
               "pattern": "^[0-9]{3}$",
               "minLength": 3,
               "maxLength": 3
           }',
           ARRAY['currency', 'iso4217', 'numeric', 'code'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currencySymbol',
           'Currency symbol for display purposes.',
           'money',
           '{
               "type": "string",
               "description": "Currency symbol",
               "examples": ["$", "Fr"],
               "minLength": 1,
               "maxLength": 5
           }',
           ARRAY['currency', 'symbol', 'display'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currencyName',
           'Full currency name.',
           'money',
           '{
               "type": "string",
               "description": "Full currency name",
               "examples": ["US Dollar", "Euro", "British Pound Sterling", "Japanese Yen", "Swiss Franc"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['currency', 'name', 'display'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currencyInfo',
           'Complete currency information including code, symbol, and metadata.',
           'money',
           '{
               "type": "object",
               "description": "Complete currency information",
               "properties": {
                   "code": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "numericCode": {
                       "type": "string",
                       "description": "ISO 4217 numeric code",
                       "pattern": "^[0-9]{3}$"
                   },
                   "name": {
                       "type": "string",
                       "description": "Full currency name"
                   },
                   "symbol": {
                       "type": "string",
                       "description": "Currency symbol"
                   },
                   "decimalDigits": {
                       "type": "integer",
                       "description": "Number of decimal places",
                       "minimum": 0,
                       "maximum": 4
                   }
               },
               "required": ["code", "name", "symbol", "decimalDigits"],
               "examples": [
                   {
                       "code": "USD",
                       "numericCode": "840",
                       "name": "US Dollar",
                       "symbol": "$",
                       "decimalDigits": 2
                   }
               ]
           }',
           ARRAY['currency', 'composite', 'metadata', 'complete'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE MONEY OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'money',
           'Standard money object with amount and currency code.',
           'money',
           '{
               "type": "object",
               "description": "Money with amount and currency",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Monetary amount"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 99.99, "currency": "USD"},
                   {"amount": 79.99, "currency": "EUR"},
                   {"amount": 10000, "currency": "JPY"}
               ]
           }',
           ARRAY['money', 'composite', 'amount', 'currency', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'moneyInteger',
           'Money object with amount in minor units (cents) for precision.',
           'money',
           '{
               "type": "object",
               "description": "Money with amount in minor units",
               "properties": {
                   "amountMinor": {
                       "type": "integer",
                       "description": "Amount in minor units (e.g., cents)"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "decimalPlaces": {
                       "type": "integer",
                       "description": "Number of decimal places for this currency",
                       "minimum": 0,
                       "maximum": 4,
                       "default": 2
                   }
               },
               "required": ["amountMinor", "currency"],
               "examples": [
                   {"amountMinor": 9999, "currency": "USD", "decimalPlaces": 2},
                   {"amountMinor": 7999, "currency": "EUR", "decimalPlaces": 2},
                   {"amountMinor": 10000, "currency": "JPY", "decimalPlaces": 0}
               ]
           }',
           ARRAY['money', 'composite', 'integer', 'minor-units', 'precision'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'moneyString',
           'Money object with string amount for exact decimal representation.',
           'money',
           '{
               "type": "object",
               "description": "Money with string amount for precision",
               "properties": {
                   "amount": {
                       "type": "string",
                       "description": "Monetary amount as string",
                       "pattern": "^-?[0-9]+(\\.[0-9]{1,4})?$"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": "99.99", "currency": "USD"},
                   {"amount": "1234.5678", "currency": "BTC"},
                   {"amount": "10000", "currency": "JPY"}
               ]
           }',
           ARRAY['money', 'composite', 'string', 'precision'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'moneySigned',
           'Signed money object allowing negative amounts for debits or refunds.',
           'money',
           '{
               "type": "object",
               "description": "Signed money allowing negative amounts",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Signed monetary amount"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 99.99, "currency": "USD"},
                   {"amount": -50.00, "currency": "USD"},
                   {"amount": -25.50, "currency": "EUR"}
               ]
           }',
           ARRAY['money', 'composite', 'signed', 'debit', 'credit'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'moneyNullable',
           'Nullable money object for optional monetary fields.',
           'money',
           '{
               "type": ["object", "null"],
               "description": "Optional money object",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Monetary amount"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 99.99, "currency": "USD"},
                   null
               ]
           }',
           ARRAY['money', 'composite', 'nullable', 'optional'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'moneyFormatted',
           'Money object with formatted display string.',
           'money',
           '{
               "type": "object",
               "description": "Money with formatted display string",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Monetary amount"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "formatted": {
                       "type": "string",
                       "description": "Formatted amount for display"
                   }
               },
               "required": ["amount", "currency", "formatted"],
               "examples": [
                   {"amount": 1234.56, "currency": "USD", "formatted": "$1,234.56"}
               ]
           }',
           ARRAY['money', 'composite', 'formatted', 'display'],
           true,
           true
       );

-- =============================================================================
-- PRICE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'price',
           'Standard price object for products or services.',
           'money',
           '{
               "type": "object",
               "description": "Price for a product or service",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Price amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 29.99, "currency": "USD"},
                   {"amount": 49.95, "currency": "EUR"}
               ]
           }',
           ARRAY['price', 'money', 'product', 'service'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'priceWithTax',
           'Price object including tax information.',
           'money',
           '{
               "type": "object",
               "description": "Price with tax breakdown",
               "properties": {
                   "subtotal": {
                       "type": "number",
                       "description": "Price before tax",
                       "minimum": 0
                   },
                   "tax": {
                       "type": "number",
                       "description": "Tax amount",
                       "minimum": 0
                   },
                   "total": {
                       "type": "number",
                       "description": "Total price including tax",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "taxRate": {
                       "type": ["number", "null"],
                       "description": "Tax rate as decimal (e.g., 0.0825 for 8.25%)",
                       "minimum": 0,
                       "maximum": 1
                   },
                   "taxType": {
                       "type": ["string", "null"],
                       "description": "Type of tax applied"
                   }
               },
               "required": ["subtotal", "tax", "total", "currency"],
               "examples": [
                   {
                       "subtotal": 100.00,
                       "tax": 8.25,
                       "total": 108.25,
                       "currency": "USD",
                       "taxRate": 0.0825,
                       "taxType": "sales_tax"
                   }
               ]
           }',
           ARRAY['price', 'money', 'tax', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'priceRange',
           'Price range with minimum and maximum values.',
           'money',
           '{
               "type": "object",
               "description": "Price range",
               "properties": {
                   "min": {
                       "type": "number",
                       "description": "Minimum price",
                       "minimum": 0
                   },
                   "max": {
                       "type": "number",
                       "description": "Maximum price",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["min", "max", "currency"],
               "examples": [
                   {"min": 10.00, "max": 50.00, "currency": "USD"},
                   {"min": 100, "max": 500, "currency": "EUR"}
               ]
           }',
           ARRAY['price', 'money', 'range', 'min', 'max'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'unitPrice',
           'Price per unit with quantity information.',
           'money',
           '{
               "type": "object",
               "description": "Unit price with quantity",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Price per unit",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "unit": {
                       "type": "string",
                       "description": "Unit of measurement"
                   },
                   "quantity": {
                       "type": "number",
                       "description": "Quantity per unit",
                       "minimum": 0,
                       "default": 1
                   }
               },
               "required": ["amount", "currency", "unit"],
               "examples": [
                   {"amount": 2.99, "currency": "USD", "unit": "lb", "quantity": 1},
                   {"amount": 15.00, "currency": "EUR", "unit": "kg", "quantity": 1},
                   {"amount": 9.99, "currency": "USD", "unit": "pack", "quantity": 6}
               ]
           }',
           ARRAY['price', 'money', 'unit', 'quantity'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'tieredPrice',
           'Tiered pricing structure with volume discounts.',
           'money',
           '{
               "type": "object",
               "description": "Tiered pricing with volume discounts",
               "properties": {
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "tiers": {
                       "type": "array",
                       "description": "Price tiers",
                       "items": {
                           "type": "object",
                           "properties": {
                               "minQuantity": {
                                   "type": "integer",
                                   "description": "Minimum quantity for this tier",
                                   "minimum": 0
                               },
                               "maxQuantity": {
                                   "type": ["integer", "null"],
                                   "description": "Maximum quantity (null for unlimited)"
                               },
                               "unitPrice": {
                                   "type": "number",
                                   "description": "Price per unit in this tier",
                                   "minimum": 0
                               }
                           },
                           "required": ["minQuantity", "unitPrice"]
                       }
                   }
               },
               "required": ["currency", "tiers"],
               "examples": [
                   {
                       "currency": "USD",
                       "tiers": [
                           {"minQuantity": 1, "maxQuantity": 10, "unitPrice": 10.00},
                           {"minQuantity": 11, "maxQuantity": 50, "unitPrice": 8.00},
                           {"minQuantity": 51, "maxQuantity": null, "unitPrice": 6.00}
                       ]
                   }
               ]
           }',
           ARRAY['price', 'money', 'tiered', 'volume', 'discount'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'recurringPrice',
           'Recurring price for subscriptions with billing period.',
           'money',
           '{
               "type": "object",
               "description": "Recurring subscription price",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Price per billing period",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "interval": {
                       "type": "string",
                       "description": "Billing interval",
                       "enum": ["day", "week", "month", "quarter", "year"]
                   },
                   "intervalCount": {
                       "type": "integer",
                       "description": "Number of intervals between billings",
                       "minimum": 1,
                       "default": 1
                   }
               },
               "required": ["amount", "currency", "interval"],
               "examples": [
                   {"amount": 9.99, "currency": "USD", "interval": "month", "intervalCount": 1},
                   {"amount": 99.99, "currency": "USD", "interval": "year", "intervalCount": 1},
                   {"amount": 29.99, "currency": "EUR", "interval": "month", "intervalCount": 3}
               ]
           }',
           ARRAY['price', 'money', 'recurring', 'subscription', 'billing'],
           true,
           true
       );

-- =============================================================================
-- DISCOUNT AND ADJUSTMENT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'discount',
           'Discount information with type and value.',
           'money',
           '{
               "type": "object",
               "description": "Discount information",
               "properties": {
                   "type": {
                       "type": "string",
                       "description": "Discount type",
                       "enum": ["percentage", "fixed", "freeShipping", "buyXgetY"]
                   },
                   "value": {
                       "type": "number",
                       "description": "Discount value (percentage or fixed amount)",
                       "minimum": 0
                   },
                   "currency": {
                       "type": ["string", "null"],
                       "description": "Currency for fixed discounts",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "code": {
                       "type": ["string", "null"],
                       "description": "Discount or promo code"
                   },
                   "description": {
                       "type": ["string", "null"],
                       "description": "Discount description"
                   }
               },
               "required": ["type", "value"],
               "examples": [
                   {"type": "percentage", "value": 20, "currency": null, "code": "SAVE20", "description": "20% off"},
                   {"type": "fixed", "value": 10.00, "currency": "USD", "code": "TENOFF", "description": "$10 off"}
               ]
           }',
           ARRAY['discount', 'money', 'promotion', 'coupon'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'discountAmount',
           'Simple discount amount in currency.',
           'money',
           '{
               "type": "object",
               "description": "Discount amount",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Discount amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 10.00, "currency": "USD"},
                   {"amount": 5.50, "currency": "EUR"}
               ]
           }',
           ARRAY['discount', 'money', 'amount'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'discountPercentage',
           'Percentage-based discount.',
           'money',
           '{
               "type": "number",
               "description": "Discount percentage (0-100)",
               "examples": [10, 20, 25, 50],
               "minimum": 0,
               "maximum": 100
           }',
           ARRAY['discount', 'percentage', 'rate'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'adjustment',
           'Price adjustment (positive or negative).',
           'money',
           '{
               "type": "object",
               "description": "Price adjustment",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Adjustment amount (positive or negative)"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "reason": {
                       "type": ["string", "null"],
                       "description": "Reason for adjustment"
                   },
                   "type": {
                       "type": "string",
                       "description": "Type of adjustment",
                       "enum": ["discount", "surcharge", "credit", "fee", "tax", "refund", "other"]
                   }
               },
               "required": ["amount", "currency", "type"],
               "examples": [
                   {"amount": -10.00, "currency": "USD", "reason": "Loyalty discount", "type": "discount"},
                   {"amount": 5.00, "currency": "USD", "reason": "Rush processing", "type": "surcharge"}
               ]
           }',
           ARRAY['adjustment', 'money', 'credit', 'debit'],
           true,
           true
       );

-- =============================================================================
-- TAX FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'taxAmount',
           'Tax amount in currency.',
           'money',
           '{
               "type": "object",
               "description": "Tax amount",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Tax amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 8.25, "currency": "USD"},
                   {"amount": 19.00, "currency": "EUR"}
               ]
           }',
           ARRAY['tax', 'money', 'amount'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'taxRate',
           'Tax rate as a decimal.',
           'money',
           '{
               "type": "number",
               "description": "Tax rate as decimal (e.g., 0.0825 for 8.25%)",
               "examples": [0.0825, 0.19, 0.20, 0.07],
               "minimum": 0,
               "maximum": 1
           }',
           ARRAY['tax', 'rate', 'percentage'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'taxRatePercentage',
           'Tax rate as a percentage value.',
           'money',
           '{
               "type": "number",
               "description": "Tax rate as percentage (e.g., 8.25 for 8.25%)",
               "examples": [8.25, 19, 20, 7],
               "minimum": 0,
               "maximum": 100
           }',
           ARRAY['tax', 'rate', 'percentage'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'taxInfo',
           'Complete tax information including type, rate, and amount.',
           'money',
           '{
               "type": "object",
               "description": "Complete tax information",
               "properties": {
                   "type": {
                       "type": "string",
                       "description": "Type of tax",
                       "enum": ["salesTax", "vat", "gst", "hst", "pst", "excise", "customs", "other"]
                   },
                   "name": {
                       "type": ["string", "null"],
                       "description": "Tax name or label"
                   },
                   "rate": {
                       "type": "number",
                       "description": "Tax rate as decimal",
                       "minimum": 0,
                       "maximum": 1
                   },
                   "amount": {
                       "type": "number",
                       "description": "Calculated tax amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "jurisdiction": {
                       "type": ["string", "null"],
                       "description": "Tax jurisdiction"
                   },
                   "taxId": {
                       "type": ["string", "null"],
                       "description": "Tax registration ID"
                   }
               },
               "required": ["type", "rate", "amount", "currency"],
               "examples": [
                   {
                       "type": "salesTax",
                       "name": "California Sales Tax",
                       "rate": 0.0825,
                       "amount": 8.25,
                       "currency": "USD",
                       "jurisdiction": "CA",
                       "taxId": null
                   },
                   {
                       "type": "vat",
                       "name": "VAT",
                       "rate": 0.19,
                       "amount": 19.00,
                       "currency": "EUR",
                       "jurisdiction": "DE",
                       "taxId": "DE123456789"
                   }
               ]
           }',
           ARRAY['tax', 'money', 'composite', 'vat', 'sales-tax'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'taxBreakdown',
           'Multiple tax items breakdown.',
           'money',
           '{
               "type": "object",
               "description": "Tax breakdown with multiple tax items",
               "properties": {
                   "items": {
                       "type": "array",
                       "description": "Individual tax items",
                       "items": {
                           "type": "object",
                           "properties": {
                               "name": {"type": "string", "description": "Tax name"},
                               "rate": {"type": "number", "description": "Tax rate", "minimum": 0, "maximum": 1},
                               "amount": {"type": "number", "description": "Tax amount", "minimum": 0}
                           },
                           "required": ["name", "rate", "amount"]
                       }
                   },
                   "total": {
                       "type": "number",
                       "description": "Total tax amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["items", "total", "currency"],
               "examples": [
                   {
                       "items": [
                           {"name": "State Tax", "rate": 0.0625, "amount": 6.25},
                           {"name": "City Tax", "rate": 0.02, "amount": 2.00}
                       ],
                       "total": 8.25,
                       "currency": "USD"
                   }
               ]
           }',
           ARRAY['tax', 'money', 'breakdown', 'multiple'],
           true,
           true
       );

-- =============================================================================
-- EXCHANGE RATE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'exchangeRate',
           'Currency exchange rate.',
           'money',
           '{
               "type": "number",
               "description": "Exchange rate",
               "examples": [1.0856, 0.9215, 149.50, 1.35],
               "minimum": 0,
               "exclusiveMinimum": true
           }',
           ARRAY['exchange', 'rate', 'currency', 'conversion'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'exchangeRateInfo',
           'Complete exchange rate information with source and target currencies.',
           'money',
           '{
               "type": "object",
               "description": "Exchange rate information",
               "properties": {
                   "fromCurrency": {
                       "type": "string",
                       "description": "Source currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "toCurrency": {
                       "type": "string",
                       "description": "Target currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "rate": {
                       "type": "number",
                       "description": "Exchange rate",
                       "minimum": 0,
                       "exclusiveMinimum": true
                   },
                   "timestamp": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When the rate was captured"
                   },
                   "source": {
                       "type": ["string", "null"],
                       "description": "Rate data source"
                   }
               },
               "required": ["fromCurrency", "toCurrency", "rate", "timestamp"],
               "examples": [
                   {
                       "fromCurrency": "USD",
                       "toCurrency": "EUR",
                       "rate": 0.9215,
                       "timestamp": "2024-01-15T12:00:00Z",
                       "source": "ECB"
                   }
               ]
           }',
           ARRAY['exchange', 'rate', 'currency', 'conversion', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'convertedMoney',
           'Money with original and converted amounts.',
           'money',
           '{
               "type": "object",
               "description": "Money with currency conversion",
               "properties": {
                   "original": {
                       "type": "object",
                       "description": "Original amount",
                       "properties": {
                           "amount": {"type": "number"},
                           "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                       },
                       "required": ["amount", "currency"]
                   },
                   "converted": {
                       "type": "object",
                       "description": "Converted amount",
                       "properties": {
                           "amount": {"type": "number"},
                           "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                       },
                       "required": ["amount", "currency"]
                   },
                   "exchangeRate": {
                       "type": "number",
                       "description": "Exchange rate used",
                       "minimum": 0,
                       "exclusiveMinimum": true
                   },
                   "convertedAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When conversion was performed"
                   }
               },
               "required": ["original", "converted", "exchangeRate"],
               "examples": [
                   {
                       "original": {"amount": 100.00, "currency": "USD"},
                       "converted": {"amount": 92.15, "currency": "EUR"},
                       "exchangeRate": 0.9215,
                       "convertedAt": "2024-01-15T12:00:00Z"
                   }
               ]
           }',
           ARRAY['money', 'conversion', 'exchange', 'composite'],
           true,
           true
       );

-- =============================================================================
-- FINANCIAL SUMMARY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'orderTotal',
           'Order total with breakdown of subtotal, discounts, tax, and shipping.',
           'money',
           '{
               "type": "object",
               "description": "Order total breakdown",
               "properties": {
                   "subtotal": {
                       "type": "number",
                       "description": "Sum of line items before adjustments",
                       "minimum": 0
                   },
                   "discount": {
                       "type": "number",
                       "description": "Total discount amount",
                       "minimum": 0,
                       "default": 0
                   },
                   "shipping": {
                       "type": "number",
                       "description": "Shipping cost",
                       "minimum": 0,
                       "default": 0
                   },
                   "tax": {
                       "type": "number",
                       "description": "Total tax amount",
                       "minimum": 0,
                       "default": 0
                   },
                   "total": {
                       "type": "number",
                       "description": "Final total",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["subtotal", "total", "currency"],
               "examples": [
                   {
                       "subtotal": 100.00,
                       "discount": 10.00,
                       "shipping": 5.99,
                       "tax": 7.92,
                       "total": 103.91,
                       "currency": "USD"
                   }
               ]
           }',
           ARRAY['order', 'money', 'total', 'breakdown', 'summary'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'invoiceTotal',
           'Invoice total with payment status and balance.',
           'money',
           '{
               "type": "object",
               "description": "Invoice total with payment status",
               "properties": {
                   "subtotal": {
                       "type": "number",
                       "description": "Sum before tax",
                       "minimum": 0
                   },
                   "tax": {
                       "type": "number",
                       "description": "Tax amount",
                       "minimum": 0
                   },
                   "total": {
                       "type": "number",
                       "description": "Total amount due",
                       "minimum": 0
                   },
                   "amountPaid": {
                       "type": "number",
                       "description": "Amount already paid",
                       "minimum": 0,
                       "default": 0
                   },
                   "amountDue": {
                       "type": "number",
                       "description": "Remaining balance",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["subtotal", "tax", "total", "amountDue", "currency"],
               "examples": [
                   {
                       "subtotal": 1000.00,
                       "tax": 80.00,
                       "total": 1080.00,
                       "amountPaid": 500.00,
                       "amountDue": 580.00,
                       "currency": "USD"
                   }
               ]
           }',
           ARRAY['invoice', 'money', 'total', 'balance', 'payment'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'balance',
           'Account or wallet balance.',
           'money',
           '{
               "type": "object",
               "description": "Account balance",
               "properties": {
                   "available": {
                       "type": "number",
                       "description": "Available balance"
                   },
                   "pending": {
                       "type": "number",
                       "description": "Pending/held amount",
                       "default": 0
                   },
                   "total": {
                       "type": "number",
                       "description": "Total balance (available + pending)"
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["available", "total", "currency"],
               "examples": [
                   {
                       "available": 1500.00,
                       "pending": 250.00,
                       "total": 1750.00,
                       "currency": "USD"
                   }
               ]
           }',
           ARRAY['balance', 'money', 'account', 'wallet'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'multiCurrencyBalance',
           'Balance in multiple currencies.',
           'money',
           '{
               "type": "object",
               "description": "Multi-currency balance",
               "properties": {
                   "balances": {
                       "type": "array",
                       "description": "Balance in each currency",
                       "items": {
                           "type": "object",
                           "properties": {
                               "currency": {
                                   "type": "string",
                                   "description": "ISO 4217 currency code",
                                   "pattern": "^[A-Z]{3}$"
                               },
                               "available": {
                                   "type": "number",
                                   "description": "Available balance"
                               },
                               "pending": {
                                   "type": "number",
                                   "description": "Pending amount",
                                   "default": 0
                               }
                           },
                           "required": ["currency", "available"]
                       }
                   },
                   "primaryCurrency": {
                       "type": "string",
                       "description": "Primary reporting currency",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "totalInPrimary": {
                       "type": ["number", "null"],
                       "description": "Total converted to primary currency"
                   }
               },
               "required": ["balances"],
               "examples": [
                   {
                       "balances": [
                           {"currency": "USD", "available": 1000.00, "pending": 50.00},
                           {"currency": "EUR", "available": 500.00, "pending": 0},
                           {"currency": "GBP", "available": 250.00, "pending": 25.00}
                       ],
                       "primaryCurrency": "USD",
                       "totalInPrimary": 1923.45
                   }
               ]
           }',
           ARRAY['balance', 'money', 'multi-currency', 'composite'],
           true,
           true
       );

-- =============================================================================
-- PAYMENT METHOD FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'paymentMethod',
           'Payment method type.',
           'money',
           '{
               "type": "string",
               "description": "Payment method type",
               "enum": ["creditCard", "debitCard", "bankTransfer", "ach", "wire", "paypal", "applePay", "googlePay", "crypto", "cash", "check", "invoice", "other"],
               "examples": ["creditCard", "bankTransfer", "paypal"]
           }',
           ARRAY['payment', 'method', 'type', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cardBrand',
           'Credit or debit card brand.',
           'money',
           '{
               "type": "string",
               "description": "Card brand",
               "enum": ["visa", "mastercard", "amex", "discover", "dinersClub", "jcb", "unionPay", "maestro", "other"],
               "examples": ["visa", "mastercard", "amex"]
           }',
           ARRAY['card', 'brand', 'payment', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cardLast4',
           'Last 4 digits of a card number.',
           'money',
           '{
               "type": "string",
               "description": "Last 4 digits of card number",
               "examples": ["4242", "1234", "5678"],
               "pattern": "^[0-9]{4}$",
               "minLength": 4,
               "maxLength": 4
           }',
           ARRAY['card', 'last4', 'payment', 'masked'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cardInfo',
           'Card information for display (non-sensitive).',
           'money',
           '{
               "type": "object",
               "description": "Non-sensitive card information",
               "properties": {
                   "brand": {
                       "type": "string",
                       "description": "Card brand",
                       "enum": ["visa", "mastercard", "amex", "discover", "dinersClub", "jcb", "unionPay", "maestro", "other"]
                   },
                   "last4": {
                       "type": "string",
                       "description": "Last 4 digits",
                       "pattern": "^[0-9]{4}$"
                   },
                   "expiryMonth": {
                       "type": "integer",
                       "description": "Expiration month (1-12)",
                       "minimum": 1,
                       "maximum": 12
                   },
                   "expiryYear": {
                       "type": "integer",
                       "description": "Expiration year",
                       "minimum": 2020
                   },
                   "holderName": {
                       "type": ["string", "null"],
                       "description": "Cardholder name"
                   }
               },
               "required": ["brand", "last4", "expiryMonth", "expiryYear"],
               "examples": [
                   {
                       "brand": "visa",
                       "last4": "4242",
                       "expiryMonth": 12,
                       "expiryYear": 2025,
                       "holderName": "John Smith"
                   }
               ]
           }',
           ARRAY['card', 'payment', 'composite', 'display'],
           true,
           true
       );

-- =============================================================================
-- REFUND FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'refundAmount',
           'Refund amount.',
           'money',
           '{
               "type": "object",
               "description": "Refund amount",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Refund amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   }
               },
               "required": ["amount", "currency"],
               "examples": [
                   {"amount": 25.00, "currency": "USD"},
                   {"amount": 99.99, "currency": "EUR"}
               ]
           }',
           ARRAY['refund', 'money', 'amount'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'refundInfo',
           'Complete refund information.',
           'money',
           '{
               "type": "object",
               "description": "Complete refund information",
               "properties": {
                   "amount": {
                       "type": "number",
                       "description": "Refund amount",
                       "minimum": 0
                   },
                   "currency": {
                       "type": "string",
                       "description": "ISO 4217 currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "reason": {
                       "type": ["string", "null"],
                       "description": "Refund reason"
                   },
                   "type": {
                       "type": "string",
                       "description": "Refund type",
                       "enum": ["full", "partial", "credit"]
                   },
                   "status": {
                       "type": "string",
                       "description": "Refund status",
                       "enum": ["pending", "processing", "completed", "failed", "cancelled"]
                   },
                   "refundedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When refund was processed"
                   }
               },
               "required": ["amount", "currency", "type", "status"],
               "examples": [
                   {
                       "amount": 50.00,
                       "currency": "USD",
                       "reason": "Customer requested cancellation",
                       "type": "partial",
                       "status": "completed",
                       "refundedAt": "2024-01-15T14:30:00Z"
                   }
               ]
           }',
           ARRAY['refund', 'money', 'composite', 'status'],
           true,
           true
       );