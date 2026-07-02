-- Preload ISO Standard Primitives
-- Adds comprehensive industry-standard ISO primitives to the system
-- These primitives follow JSON Schema specifications and ISO standards

SET search_path TO apiome, public;

-- Get the test tenant ID for seeding (will be used for all tenants)
-- This approach ensures all tenants get the same standard primitives

-- STRING PRIMITIVES
-- Email Address - RFC 5321/5322
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Email Address',
    'A valid email address following RFC 5321/5322 standard. Format: local-part@domain.',
    'string',
    '{"type": "string", "format": "email", "maxLength": 254, "description": "Valid email address in RFC 5322 format"}'::jsonb,
    ARRAY['email', 'contact', 'communication', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- UUID - RFC 4122
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'UUID',
    'A universally unique identifier (UUID) in standard format per RFC 4122. Supports UUID v1, v3, v4, and v5.',
    'string',
    '{"type": "string", "format": "uuid", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "description": "UUID in standard format (RFC 4122)"}'::jsonb,
    ARRAY['uuid', 'identifier', 'id', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Uniform Resource Identifier (URI) - RFC 3986
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Uniform Resource Identifier (URI)',
    'A uniform resource identifier following RFC 3986. Includes URLs, URNs, and other resource identifiers.',
    'string',
    '{"type": "string", "format": "uri", "maxLength": 2048, "description": "URI following RFC 3986"}'::jsonb,
    ARRAY['uri', 'url', 'identifier', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- URL (Subtype of URI) - RFC 1738
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Uniform Resource Locator (URL)',
    'A uniform resource locator following RFC 1738. Supports HTTP, HTTPS, FTP, and other common schemes.',
    'string',
    '{"type": "string", "format": "uri", "pattern": "^[a-zA-Z][a-zA-Z0-9+.-]*://", "maxLength": 2048, "description": "URL with a valid scheme"}'::jsonb,
    ARRAY['url', 'link', 'uri', 'web', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Date - ISO 8601
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Date (ISO 8601)',
    'A date value in ISO 8601 format: YYYY-MM-DD. Represents a calendar date without time zone.',
    'string',
    '{"type": "string", "format": "date", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "Date in ISO 8601 format (YYYY-MM-DD)"}'::jsonb,
    ARRAY['date', 'iso8601', 'iso-standard', 'calendar'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- DateTime - ISO 8601
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Date-Time (ISO 8601)',
    'A date-time value in ISO 8601 format with optional timezone. Format: YYYY-MM-DDTHH:mm:ss[.sss][Z|±HH:mm]',
    'string',
    '{"type": "string", "format": "date-time", "description": "Date-time in ISO 8601 format with timezone"}'::jsonb,
    ARRAY['datetime', 'timestamp', 'iso8601', 'iso-standard', 'temporal'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Time - ISO 8601
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Time (ISO 8601)',
    'A time value in ISO 8601 format: HH:mm:ss[.sss]. Represents time of day without date.',
    'string',
    '{"type": "string", "format": "time", "pattern": "^([0-1][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,3})?$", "description": "Time in ISO 8601 format (HH:mm:ss)"}'::jsonb,
    ARRAY['time', 'iso8601', 'iso-standard', 'temporal'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Duration - ISO 8601
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Duration (ISO 8601)',
    'A duration or period in ISO 8601 format. Format: P[n]Y[n]M[n]DT[n]H[n]M[n]S',
    'string',
    '{"type": "string", "pattern": "^P(?:\\d+Y)?(?:\\d+M)?(?:\\d+D)?(?:T(?:\\d+H)?(?:\\d+M)?(?:\\d+(?:\\.\\d+)?S)?)?$", "description": "Duration in ISO 8601 format"}'::jsonb,
    ARRAY['duration', 'iso8601', 'iso-standard', 'temporal', 'period'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- IPv4 Address - RFC 791
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'IPv4 Address',
    'An IPv4 address in dotted decimal notation (RFC 791). Format: 0.0.0.0 to 255.255.255.255',
    'string',
    '{"type": "string", "format": "ipv4", "description": "IPv4 address in dotted decimal notation"}'::jsonb,
    ARRAY['ipv4', 'ip-address', 'network', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- IPv6 Address - RFC 4291
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'IPv6 Address',
    'An IPv6 address in standard notation (RFC 4291). Supports full, compressed, and IPv4-mapped formats.',
    'string',
    '{"type": "string", "format": "ipv6", "description": "IPv6 address in standard notation"}'::jsonb,
    ARRAY['ipv6', 'ip-address', 'network', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Phone Number - E.164 (ITU-T)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Phone Number (E.164)',
    'An international phone number in E.164 format (ITU-T standard). Format: +[1-9]{1,15}',
    'string',
    '{"type": "string", "pattern": "^\\+[1-9]\\d{1,14}$", "minLength": 7, "maxLength": 15, "description": "International phone number in E.164 format"}'::jsonb,
    ARRAY['phone', 'contact', 'telephone', 'e164', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- IBAN - ISO 13616
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'International Bank Account Number (IBAN)',
    'An international bank account number following ISO 13616. Format: 2-letter country code, 2 check digits, followed by country-specific structure.',
    'string',
    '{"type": "string", "pattern": "^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$", "minLength": 15, "maxLength": 34, "description": "IBAN following ISO 13616"}'::jsonb,
    ARRAY['iban', 'banking', 'finance', 'account', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- ISO 3166-1 Country Code
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Country Code (ISO 3166-1)',
    'A two-letter or three-letter country code following ISO 3166-1. Represents sovereign states and territories.',
    'string',
    '{"type": "string", "pattern": "^[A-Z]{2}$", "minLength": 2, "maxLength": 2, "description": "ISO 3166-1 alpha-2 country code"}'::jsonb,
    ARRAY['country', 'iso3166', 'geography', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- ISO 639-1 Language Code
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Language Code (ISO 639-1)',
    'A two-letter language code following ISO 639-1. Represents natural languages.',
    'string',
    '{"type": "string", "pattern": "^[a-z]{2}$", "minLength": 2, "maxLength": 2, "description": "ISO 639-1 language code"}'::jsonb,
    ARRAY['language', 'iso639', 'locale', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- ISO 4217 Currency Code
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Currency Code (ISO 4217)',
    'A three-letter currency code following ISO 4217. Represents worldwide currencies.',
    'string',
    '{"type": "string", "pattern": "^[A-Z]{3}$", "minLength": 3, "maxLength": 3, "description": "ISO 4217 currency code"}'::jsonb,
    ARRAY['currency', 'iso4217', 'money', 'finance', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Hash (SHA-256)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'SHA-256 Hash',
    'A cryptographic hash using the SHA-256 algorithm. Produces a 256-bit (64 hexadecimal character) hash value.',
    'string',
    '{"type": "string", "pattern": "^[a-f0-9]{64}$", "minLength": 64, "maxLength": 64, "description": "SHA-256 hash in hexadecimal format"}'::jsonb,
    ARRAY['hash', 'sha256', 'cryptography', 'security', 'digest'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Base64 Encoded String
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Base64 String',
    'A string encoded in Base64 format (RFC 4648). Commonly used for binary data representation.',
    'string',
    '{"type": "string", "pattern": "^[A-Za-z0-9+/]*={0,2}$", "description": "Base64 encoded string (RFC 4648)"}'::jsonb,
    ARRAY['base64', 'encoding', 'binary', 'rfc4648', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- JSON String
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'JSON String',
    'A string containing valid JSON. Used for storing serialized JSON objects or arrays.',
    'string',
    '{"type": "string", "contentMediaType": "application/json", "description": "Valid JSON string"}'::jsonb,
    ARRAY['json', 'data-format', 'serialization'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- NUMERIC PRIMITIVES
-- Integer
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Integer',
    'A whole number without a fractional part. Range: -2^53+1 to 2^53-1 in JSON Schema.',
    'integer',
    '{"type": "integer", "description": "Whole number integer"}'::jsonb,
    ARRAY['integer', 'number', 'numeric', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Positive Integer
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Positive Integer',
    'An integer greater than zero. Used for quantities, counts, and identifiers.',
    'integer',
    '{"type": "integer", "minimum": 1, "description": "Integer greater than zero"}'::jsonb,
    ARRAY['positive-integer', 'integer', 'numeric', 'count'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Non-Negative Integer
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Non-Negative Integer',
    'An integer greater than or equal to zero. Used for quantities and non-negative values.',
    'integer',
    '{"type": "integer", "minimum": 0, "description": "Integer greater than or equal to zero"}'::jsonb,
    ARRAY['non-negative-integer', 'integer', 'numeric', 'count'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Percentage (Integer)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Percentage (Integer)',
    'An integer percentage value between 0 and 100 inclusive.',
    'integer',
    '{"type": "integer", "minimum": 0, "maximum": 100, "description": "Integer percentage (0-100)"}'::jsonb,
    ARRAY['percentage', 'ratio', 'numeric', 'integer'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Number (Floating Point)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Decimal Number',
    'A numeric value that can have a fractional part. Includes integers, decimals, and numbers in exponential notation.',
    'number',
    '{"type": "number", "description": "Floating-point number"}'::jsonb,
    ARRAY['number', 'decimal', 'float', 'numeric', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Percentage (Number)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Percentage (Decimal)',
    'A decimal percentage value between 0.0 and 100.0 inclusive.',
    'number',
    '{"type": "number", "minimum": 0.0, "maximum": 100.0, "description": "Decimal percentage (0.0-100.0)"}'::jsonb,
    ARRAY['percentage', 'ratio', 'numeric', 'number'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Probability
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Probability',
    'A probability value between 0.0 and 1.0 inclusive. Represents the likelihood of an event.',
    'number',
    '{"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "Probability value (0.0-1.0)"}'::jsonb,
    ARRAY['probability', 'ratio', 'numeric', 'number', 'statistics'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Monetary Amount
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Monetary Amount',
    'A decimal number representing a monetary amount. Use with currency codes for complete financial data.',
    'number',
    '{"type": "number", "minimum": 0, "description": "Monetary amount"}'::jsonb,
    ARRAY['money', 'finance', 'currency', 'amount', 'numeric'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- BOOLEAN PRIMITIVES
-- Boolean
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Boolean',
    'A boolean value representing true or false. Used for flags, switches, and binary choices.',
    'boolean',
    '{"type": "boolean", "description": "True or false boolean value"}'::jsonb,
    ARRAY['boolean', 'flag', 'switch', 'binary', 'iso-standard'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- ARRAY PRIMITIVES
-- String Array
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'String Array',
    'An array of string values. Used for lists of text items, tags, or keywords.',
    'array',
    '{"type": "array", "items": {"type": "string"}, "description": "Array of strings"}'::jsonb,
    ARRAY['array', 'list', 'string', 'collection'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Integer Array
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Integer Array',
    'An array of integer values. Used for lists of whole numbers.',
    'array',
    '{"type": "array", "items": {"type": "integer"}, "description": "Array of integers"}'::jsonb,
    ARRAY['array', 'list', 'integer', 'collection', 'numeric'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Number Array
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Number Array',
    'An array of numeric values. Used for lists of floating-point numbers.',
    'array',
    '{"type": "array", "items": {"type": "number"}, "description": "Array of numbers"}'::jsonb,
    ARRAY['array', 'list', 'number', 'collection', 'numeric'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Boolean Array
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Boolean Array',
    'An array of boolean values. Used for lists of true/false values.',
    'array',
    '{"type": "array", "items": {"type": "boolean"}, "description": "Array of booleans"}'::jsonb,
    ARRAY['array', 'list', 'boolean', 'collection'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Object (JSON Object)
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'JSON Object',
    'An object (key-value pairs). Used for structured data with named properties.',
    'object',
    '{"type": "object", "description": "JSON object with properties"}'::jsonb,
    ARRAY['object', 'map', 'dictionary', 'json', 'structured-data'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- ENUM PRIMITIVES
-- HTTP Status Code
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'HTTP Status Code',
    'An HTTP status code (100-599). Represents the result of an HTTP request.',
    'integer',
    '{"type": "integer", "enum": [100, 101, 200, 201, 202, 203, 204, 205, 206, 300, 301, 302, 303, 304, 305, 306, 307, 308, 400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 415, 416, 417, 421, 422, 423, 424, 425, 426, 428, 429, 431, 451, 500, 501, 502, 503, 504, 505, 506, 507, 508, 510, 511], "description": "Standard HTTP status code"}'::jsonb,
    ARRAY['http', 'status-code', 'web', 'api', 'enum'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Boolean as String Enum
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Boolean String',
    'A string representation of a boolean value: "true" or "false".',
    'string',
    '{"type": "string", "enum": ["true", "false"], "description": "String representation of boolean"}'::jsonb,
    ARRAY['boolean', 'string', 'enum'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log Entry
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Log Level',
    'A log level indicating severity: DEBUG, INFO, WARN, ERROR, FATAL.',
    'string',
    '{"type": "string", "enum": ["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"], "description": "Log severity level"}'::jsonb,
    ARRAY['logging', 'enum', 'severity', 'monitoring'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Null/Empty value
INSERT INTO primitives (tenant_id, name, description, category, schema, tags, is_system, is_public)
SELECT t.id,
    'Null Value',
    'A null value representing the absence of data.',
    'null',
    '{"type": "null", "description": "Null value"}'::jsonb,
    ARRAY['null', 'empty', 'nil', 'none'],
    true,
    true
FROM tenants t
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Add index for faster queries on tags
CREATE INDEX IF NOT EXISTS idx_primitives_tags_gin ON primitives USING GIN(tags);

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'ISO standard primitives successfully preloaded for all tenants';
END $$;
