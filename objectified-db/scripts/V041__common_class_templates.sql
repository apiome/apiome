-- Common Class Templates
-- Adds common utility class templates for money, coordinates, date ranges, file uploads, pagination, sorting, and audit tracking
-- These templates provide reusable patterns for common data structures

SET search_path TO odb, public;

-- =============================================================================
-- Money - Currency and amount with formatting
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Money',
    'Monetary value with currency code and optional formatting for display.',
    'common',
    $JSON${
        "type": "object",
        "description": "Monetary value with currency and formatting",
        "properties": {
            "amount": {
                "type": "number",
                "description": "Monetary amount",
                "minimum": 0,
                "examples": [99.99, 1000, 49.95, 0.01]
            },
            "currency": {
                "type": "string",
                "description": "ISO 4217 currency code",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", "GBP", "JPY"]
            },
            "formatted": {
                "type": ["string", "null"],
                "description": "Formatted amount for display (e.g., $1,234.56)",
                "maxLength": 100,
                "examples": ["$1,234.56", "€1.234,56", "£1,234.56", null]
            },
            "amountMinor": {
                "type": ["integer", "null"],
                "description": "Amount in minor currency units (e.g., cents) for precision",
                "minimum": 0,
                "examples": [9999, 100000, 4995, null]
            },
            "decimalPlaces": {
                "type": ["integer", "null"],
                "description": "Number of decimal places for this currency",
                "minimum": 0,
                "maximum": 4,
                "default": 2,
                "examples": [2, 0, 3, null]
            }
        },
        "required": ["amount", "currency"]
    }$JSON$::jsonb,
    ARRAY['money', 'currency', 'finance', 'payment', 'amount'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Coordinates - Lat/lng for location data
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Coordinates',
    'Geographic coordinates (latitude and longitude) for location data.',
    'common',
    $JSON${
        "type": "object",
        "description": "Geographic coordinates",
        "properties": {
            "latitude": {
                "type": "number",
                "description": "Latitude coordinate",
                "minimum": -90,
                "maximum": 90,
                "examples": [37.4220656, -33.8688197, 51.5073509]
            },
            "longitude": {
                "type": "number",
                "description": "Longitude coordinate",
                "minimum": -180,
                "maximum": 180,
                "examples": [-122.0840897, 151.2092955, -0.1277583]
            },
            "accuracy": {
                "type": ["number", "null"],
                "description": "Accuracy in meters",
                "minimum": 0,
                "examples": [10.5, 100, null]
            },
            "altitude": {
                "type": ["number", "null"],
                "description": "Altitude in meters above sea level",
                "examples": [100.5, 0, -50, null]
            },
            "heading": {
                "type": ["number", "null"],
                "description": "Direction of travel in degrees (0-360)",
                "minimum": 0,
                "maximum": 360,
                "examples": [90, 180, 270, null]
            },
            "speed": {
                "type": ["number", "null"],
                "description": "Speed in meters per second",
                "minimum": 0,
                "examples": [5.5, 10, null]
            }
        },
        "required": ["latitude", "longitude"]
    }$JSON$::jsonb,
    ARRAY['coordinates', 'location', 'geolocation', 'gps', 'latlng'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- DateRange - Start/end dates with validation
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'DateRange',
    'Date range with start and end dates, including validation to ensure end is after start.',
    'common',
    $JSON${
        "type": "object",
        "description": "Date range with start and end dates",
        "properties": {
            "startDate": {
                "type": "string",
                "format": "date",
                "description": "Start date of the range (inclusive)",
                "examples": ["2026-01-01", "2026-06-15"]
            },
            "endDate": {
                "type": "string",
                "format": "date",
                "description": "End date of the range (inclusive)",
                "examples": ["2026-12-31", "2026-06-30"]
            },
            "startDateTime": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Start date and time of the range (inclusive)",
                "examples": ["2026-01-01T00:00:00Z", "2026-06-15T09:00:00Z", null]
            },
            "endDateTime": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "End date and time of the range (inclusive)",
                "examples": ["2026-12-31T23:59:59Z", "2026-06-30T17:00:00Z", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "Timezone for the date range (IANA timezone identifier)",
                "maxLength": 50,
                "examples": ["America/New_York", "Europe/London", "Asia/Tokyo", null]
            },
            "isAllDay": {
                "type": ["boolean", "null"],
                "description": "Whether this is an all-day range (ignores time components)",
                "default": false,
                "examples": [true, false, null]
            }
        },
        "required": ["startDate", "endDate"]
    }$JSON$::jsonb,
    ARRAY['date', 'range', 'period', 'interval', 'temporal'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- FileUpload - File metadata and storage references
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'FileUpload',
    'File upload metadata including storage references, MIME type, size, and upload tracking.',
    'common',
    $JSON${
        "type": "object",
        "description": "File upload metadata and storage information",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the file"
            },
            "filename": {
                "type": "string",
                "description": "Original filename",
                "maxLength": 255,
                "examples": ["document.pdf", "image.jpg", "data.csv"]
            },
            "mimeType": {
                "type": "string",
                "description": "MIME type of the file",
                "maxLength": 100,
                "examples": ["application/pdf", "image/jpeg", "text/csv"]
            },
            "size": {
                "type": "integer",
                "description": "File size in bytes",
                "minimum": 0,
                "examples": [1024, 1048576, 5242880]
            },
            "url": {
                "type": "string",
                "format": "uri",
                "description": "URL to access/download the file",
                "examples": ["https://storage.example.com/files/abc123.pdf", "s3://bucket/files/abc123.pdf"]
            },
            "storagePath": {
                "type": ["string", "null"],
                "description": "Storage path or key (e.g., S3 key, file system path)",
                "maxLength": 500,
                "examples": ["uploads/2026/01/abc123.pdf", "s3://bucket/files/abc123.pdf", null]
            },
            "storageProvider": {
                "type": ["string", "null"],
                "description": "Storage provider or service name",
                "enum": ["s3", "gcs", "azure", "local", "cdn", "other", null],
                "examples": ["s3", "local", "gcs", null]
            },
            "thumbnailUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "URL to thumbnail image (for images/videos)",
                "examples": ["https://storage.example.com/thumbs/abc123.jpg", null]
            },
            "uploadedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who uploaded the file"
            },
            "uploadedAt": {
                "type": "string",
                "format": "date-time",
                "description": "Timestamp when file was uploaded"
            },
            "checksum": {
                "type": ["string", "null"],
                "description": "File checksum/hash for integrity verification (e.g., SHA-256)",
                "maxLength": 64,
                "examples": ["a1b2c3d4e5f6...", null]
            },
            "checksumAlgorithm": {
                "type": ["string", "null"],
                "description": "Algorithm used for checksum",
                "enum": ["md5", "sha1", "sha256", "sha512", null],
                "examples": ["sha256", "md5", null]
            }
        },
        "required": ["filename", "mimeType", "size", "url", "uploadedAt"]
    }$JSON$::jsonb,
    ARRAY['file', 'upload', 'storage', 'attachment', 'media'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Pagination - Offset/limit/total for list responses
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Pagination',
    'Pagination metadata for list responses including offset, limit, total count, and page information.',
    'common',
    $JSON${
        "type": "object",
        "description": "Pagination information for list responses",
        "properties": {
            "offset": {
                "type": "integer",
                "description": "Number of items to skip",
                "minimum": 0,
                "default": 0,
                "examples": [0, 10, 20, 50]
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of items to return",
                "minimum": 1,
                "maximum": 1000,
                "default": 20,
                "examples": [10, 20, 50, 100]
            },
            "total": {
                "type": ["integer", "null"],
                "description": "Total number of items available (null if unknown)",
                "minimum": 0,
                "examples": [100, 0, null]
            },
            "page": {
                "type": ["integer", "null"],
                "description": "Current page number (1-based, calculated from offset/limit)",
                "minimum": 1,
                "examples": [1, 2, 5, null]
            },
            "pageSize": {
                "type": ["integer", "null"],
                "description": "Items per page (same as limit, for convenience)",
                "minimum": 1,
                "examples": [10, 20, 50, null]
            },
            "hasMore": {
                "type": ["boolean", "null"],
                "description": "Whether there are more items available",
                "examples": [true, false, null]
            },
            "hasPrevious": {
                "type": ["boolean", "null"],
                "description": "Whether there are previous items",
                "examples": [true, false, null]
            }
        },
        "required": ["offset", "limit"]
    }$JSON$::jsonb,
    ARRAY['pagination', 'paging', 'list', 'query', 'response'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- SortOptions - Field and direction for queries
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'SortOptions',
    'Sorting options for queries with field name and sort direction.',
    'common',
    $JSON${
        "type": "object",
        "description": "Sorting options for queries",
        "properties": {
            "field": {
                "type": "string",
                "description": "Field name to sort by",
                "maxLength": 100,
                "examples": ["createdAt", "name", "price", "updatedAt"]
            },
            "direction": {
                "type": "string",
                "description": "Sort direction",
                "enum": ["asc", "desc", "ASC", "DESC"],
                "default": "asc",
                "examples": ["asc", "desc"]
            },
            "nullsFirst": {
                "type": ["boolean", "null"],
                "description": "Whether null values should appear first (true) or last (false)",
                "examples": [true, false, null]
            }
        },
        "required": ["field", "direction"]
    }$JSON$::jsonb,
    ARRAY['sort', 'ordering', 'query', 'filter'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- AuditTimestamps - Created/updated/deleted tracking
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'AuditTimestamps',
    'Standard audit timestamps for tracking when records are created, updated, and deleted.',
    'common',
    $JSON${
        "type": "object",
        "description": "Audit timestamps for record lifecycle tracking",
        "properties": {
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "Timestamp when the record was created",
                "examples": ["2026-01-25T10:30:00Z"]
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Timestamp when the record was last updated",
                "examples": ["2026-01-25T15:45:00Z", null]
            },
            "deletedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Timestamp when the record was soft-deleted (null if not deleted)",
                "examples": [null, "2026-01-25T20:00:00Z"]
            },
            "createdBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who created the record"
            },
            "updatedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who last updated the record"
            },
            "deletedBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who deleted the record"
            },
            "version": {
                "type": ["integer", "null"],
                "description": "Version number for optimistic locking",
                "minimum": 0,
                "default": 1,
                "examples": [1, 2, 10, null]
            }
        },
        "required": ["createdAt"]
    }$JSON$::jsonb,
    ARRAY['audit', 'timestamps', 'tracking', 'lifecycle', 'created', 'updated', 'deleted'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Common class templates successfully created: Money, Coordinates, DateRange, FileUpload, Pagination, SortOptions, AuditTimestamps';
END $$;
