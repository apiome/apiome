-- Property Templates: Pagination Category
-- These templates define common patterns for paginating data and result sets
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- =============================================================================
-- BASIC PAGINATION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'page',
           'Current page number (1-indexed).',
           'pagination',
           '{
               "type": "integer",
               "description": "Current page number (1-indexed)",
               "examples": [1, 2, 5, 10],
               "minimum": 1,
               "default": 1
           }',
           ARRAY['page', 'number', 'offset-based'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'pageZeroIndexed',
           'Current page number (0-indexed).',
           'pagination',
           '{
               "type": "integer",
               "description": "Current page number (0-indexed)",
               "examples": [0, 1, 4, 9],
               "minimum": 0,
               "default": 0
           }',
           ARRAY['page', 'number', 'zero-indexed', 'offset-based'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'limit',
           'Maximum number of items to return per page.',
           'pagination',
           '{
               "type": "integer",
               "description": "Maximum items per page",
               "examples": [10, 20, 50, 100],
               "minimum": 1,
               "maximum": 1000,
               "default": 20
           }',
           ARRAY['limit', 'size', 'per-page'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'pageSize',
           'Number of items per page (alias for limit).',
           'pagination',
           '{
               "type": "integer",
               "description": "Number of items per page",
               "examples": [10, 20, 50, 100],
               "minimum": 1,
               "maximum": 1000,
               "default": 20
           }',
           ARRAY['page-size', 'size', 'per-page', 'limit'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'offset',
           'Number of items to skip before returning results.',
           'pagination',
           '{
               "type": "integer",
               "description": "Number of items to skip",
               "examples": [0, 20, 40, 100],
               "minimum": 0,
               "default": 0
           }',
           ARRAY['offset', 'skip', 'offset-based'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'skip',
           'Number of items to skip (alias for offset).',
           'pagination',
           '{
               "type": "integer",
               "description": "Number of items to skip",
               "examples": [0, 20, 40, 100],
               "minimum": 0,
               "default": 0
           }',
           ARRAY['skip', 'offset', 'offset-based'],
           true,
           true
       );

-- =============================================================================
-- COUNT AND TOTAL FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'totalCount',
           'Total number of items across all pages.',
           'pagination',
           '{
               "type": "integer",
               "description": "Total number of items",
               "examples": [0, 42, 150, 10000],
               "minimum": 0
           }',
           ARRAY['total', 'count', 'items'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'totalPages',
           'Total number of pages available.',
           'pagination',
           '{
               "type": "integer",
               "description": "Total number of pages",
               "examples": [1, 5, 10, 100],
               "minimum": 0
           }',
           ARRAY['total', 'pages', 'count'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'count',
           'Number of items in the current page/result set.',
           'pagination',
           '{
               "type": "integer",
               "description": "Number of items in current result",
               "examples": [0, 10, 20, 50],
               "minimum": 0
           }',
           ARRAY['count', 'items', 'current'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'returnedCount',
           'Actual number of items returned in the response.',
           'pagination',
           '{
               "type": "integer",
               "description": "Actual number of items returned",
               "examples": [0, 10, 20, 47],
               "minimum": 0
           }',
           ARRAY['returned', 'count', 'actual'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'estimatedCount',
           'Estimated total count (when exact count is expensive).',
           'pagination',
           '{
               "type": ["integer", "null"],
               "description": "Estimated total count",
               "examples": [10000, 50000, null],
               "minimum": 0
           }',
           ARRAY['estimated', 'count', 'approximate', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'hasMore',
           'Indicates if more items are available beyond the current page.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether more items are available",
               "examples": [true, false]
           }',
           ARRAY['has-more', 'boolean', 'next'],
           true,
           true
       );

-- =============================================================================
-- CURSOR-BASED PAGINATION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cursor',
           'Opaque cursor string for cursor-based pagination.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Pagination cursor",
               "examples": ["eyJpZCI6MTIzfQ==", "MjAyNC0wMS0xNVQxMjowMDowMFo=", null],
               "maxLength": 500
           }',
           ARRAY['cursor', 'opaque', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'nextCursor',
           'Cursor to fetch the next page of results.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Cursor for next page",
               "examples": ["eyJpZCI6MTQ1fQ==", null],
               "maxLength": 500
           }',
           ARRAY['cursor', 'next', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'prevCursor',
           'Cursor to fetch the previous page of results.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Cursor for previous page",
               "examples": ["eyJpZCI6MTAwfQ==", null],
               "maxLength": 500
           }',
           ARRAY['cursor', 'previous', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'startCursor',
           'Cursor pointing to the first item in the result set.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Cursor for first item in results",
               "examples": ["eyJpZCI6MTIzfQ==", null],
               "maxLength": 500
           }',
           ARRAY['cursor', 'start', 'first', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'endCursor',
           'Cursor pointing to the last item in the result set.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Cursor for last item in results",
               "examples": ["eyJpZCI6MTQ1fQ==", null],
               "maxLength": 500
           }',
           ARRAY['cursor', 'end', 'last', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'after',
           'Cursor to fetch items after this position (forward pagination).',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Fetch items after this cursor",
               "examples": ["eyJpZCI6MTIzfQ==", null],
               "maxLength": 500
           }',
           ARRAY['after', 'cursor', 'forward', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'before',
           'Cursor to fetch items before this position (backward pagination).',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "Fetch items before this cursor",
               "examples": ["eyJpZCI6MTQ1fQ==", null],
               "maxLength": 500
           }',
           ARRAY['before', 'cursor', 'backward', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'first',
           'Number of items to fetch from the beginning (forward pagination).',
           'pagination',
           '{
               "type": ["integer", "null"],
               "description": "Number of items from start",
               "examples": [10, 20, 50, null],
               "minimum": 1,
               "maximum": 100
           }',
           ARRAY['first', 'forward', 'cursor-based', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'last',
           'Number of items to fetch from the end (backward pagination).',
           'pagination',
           '{
               "type": ["integer", "null"],
               "description": "Number of items from end",
               "examples": [10, 20, 50, null],
               "minimum": 1,
               "maximum": 100
           }',
           ARRAY['last', 'backward', 'cursor-based', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- NAVIGATION FLAGS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'hasNextPage',
           'Indicates if a next page exists.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether a next page exists",
               "examples": [true, false]
           }',
           ARRAY['has-next', 'boolean', 'navigation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'hasPreviousPage',
           'Indicates if a previous page exists.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether a previous page exists",
               "examples": [true, false]
           }',
           ARRAY['has-previous', 'boolean', 'navigation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'isFirstPage',
           'Indicates if this is the first page.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether this is the first page",
               "examples": [true, false]
           }',
           ARRAY['first', 'boolean', 'navigation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'isLastPage',
           'Indicates if this is the last page.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether this is the last page",
               "examples": [true, false]
           }',
           ARRAY['last', 'boolean', 'navigation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'isEmpty',
           'Indicates if the result set is empty.',
           'pagination',
           '{
               "type": "boolean",
               "description": "Whether the result set is empty",
               "examples": [true, false]
           }',
           ARRAY['empty', 'boolean', 'status'],
           true,
           true
       );

-- =============================================================================
-- KEYSET/SEEK PAGINATION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekKey',
           'Key value for keyset/seek pagination.',
           'pagination',
           '{
               "type": ["string", "integer", "null"],
               "description": "Key value for seek pagination",
               "examples": ["2024-01-15T12:00:00Z", 12345, "abc123", null]
           }',
           ARRAY['seek', 'key', 'keyset', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekAfter',
           'Fetch items with key greater than this value.',
           'pagination',
           '{
               "type": ["string", "integer", "null"],
               "description": "Fetch items after this key value",
               "examples": ["2024-01-15T12:00:00Z", 12345, null]
           }',
           ARRAY['seek', 'after', 'keyset', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekBefore',
           'Fetch items with key less than this value.',
           'pagination',
           '{
               "type": ["string", "integer", "null"],
               "description": "Fetch items before this key value",
               "examples": ["2024-01-15T12:00:00Z", 12345, null]
           }',
           ARRAY['seek', 'before', 'keyset', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekId',
           'ID-based seek key for pagination.',
           'pagination',
           '{
               "type": ["string", "null"],
               "description": "ID for seek-based pagination",
               "examples": ["550e8400-e29b-41d4-a716-446655440000", "12345", null]
           }',
           ARRAY['seek', 'id', 'keyset', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekTimestamp',
           'Timestamp-based seek key for pagination.',
           'pagination',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp for seek-based pagination",
               "examples": ["2024-01-15T12:00:00Z", null]
           }',
           ARRAY['seek', 'timestamp', 'keyset', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE PAGINATION REQUEST OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'pageRequest',
           'Page-based pagination request parameters.',
           'pagination',
           '{
               "type": "object",
               "description": "Page-based pagination request",
               "properties": {
                   "page": {
                       "type": "integer",
                       "description": "Page number (1-indexed)",
                       "minimum": 1,
                       "default": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   }
               },
               "examples": [
                   {"page": 1, "pageSize": 20},
                   {"page": 3, "pageSize": 50}
               ]
           }',
           ARRAY['pagination', 'request', 'page-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'offsetRequest',
           'Offset-based pagination request parameters.',
           'pagination',
           '{
               "type": "object",
               "description": "Offset-based pagination request",
               "properties": {
                   "offset": {
                       "type": "integer",
                       "description": "Number of items to skip",
                       "minimum": 0,
                       "default": 0
                   },
                   "limit": {
                       "type": "integer",
                       "description": "Maximum items to return",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   }
               },
               "examples": [
                   {"offset": 0, "limit": 20},
                   {"offset": 40, "limit": 20}
               ]
           }',
           ARRAY['pagination', 'request', 'offset-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cursorRequest',
           'Cursor-based pagination request parameters.',
           'pagination',
           '{
               "type": "object",
               "description": "Cursor-based pagination request",
               "properties": {
                   "cursor": {
                       "type": ["string", "null"],
                       "description": "Pagination cursor"
                   },
                   "limit": {
                       "type": "integer",
                       "description": "Maximum items to return",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   },
                   "direction": {
                       "type": "string",
                       "description": "Pagination direction",
                       "enum": ["forward", "backward"],
                       "default": "forward"
                   }
               },
               "examples": [
                   {"cursor": null, "limit": 20, "direction": "forward"},
                   {"cursor": "eyJpZCI6MTIzfQ==", "limit": 20, "direction": "forward"}
               ]
           }',
           ARRAY['pagination', 'request', 'cursor-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'relayRequest',
           'Relay-style cursor pagination request (GraphQL Connection spec).',
           'pagination',
           '{
               "type": "object",
               "description": "Relay-style pagination request",
               "properties": {
                   "first": {
                       "type": ["integer", "null"],
                       "description": "Number of items from start",
                       "minimum": 1,
                       "maximum": 100
                   },
                   "after": {
                       "type": ["string", "null"],
                       "description": "Cursor to start after"
                   },
                   "last": {
                       "type": ["integer", "null"],
                       "description": "Number of items from end",
                       "minimum": 1,
                       "maximum": 100
                   },
                   "before": {
                       "type": ["string", "null"],
                       "description": "Cursor to start before"
                   }
               },
               "examples": [
                   {"first": 20, "after": null, "last": null, "before": null},
                   {"first": 20, "after": "eyJpZCI6MTIzfQ==", "last": null, "before": null},
                   {"first": null, "after": null, "last": 20, "before": "eyJpZCI6MTQ1fQ=="}
               ]
           }',
           ARRAY['pagination', 'request', 'relay', 'graphql', 'cursor-based'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'seekRequest',
           'Keyset/seek-based pagination request parameters.',
           'pagination',
           '{
               "type": "object",
               "description": "Keyset/seek pagination request",
               "properties": {
                   "seekKey": {
                       "type": ["string", "integer", "null"],
                       "description": "Key value to seek from"
                   },
                   "seekDirection": {
                       "type": "string",
                       "description": "Direction to seek",
                       "enum": ["after", "before"],
                       "default": "after"
                   },
                   "limit": {
                       "type": "integer",
                       "description": "Maximum items to return",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   }
               },
               "examples": [
                   {"seekKey": null, "seekDirection": "after", "limit": 20},
                   {"seekKey": "2024-01-15T12:00:00Z", "seekDirection": "after", "limit": 20}
               ]
           }',
           ARRAY['pagination', 'request', 'keyset', 'seek', 'composite'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE PAGINATION RESPONSE/METADATA OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'pageInfo',
           'Basic page information for pagination responses.',
           'pagination',
           '{
               "type": "object",
               "description": "Basic pagination info",
               "properties": {
                   "page": {
                       "type": "integer",
                       "description": "Current page number",
                       "minimum": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page"
                   },
                   "totalCount": {
                       "type": "integer",
                       "description": "Total number of items",
                       "minimum": 0
                   },
                   "totalPages": {
                       "type": "integer",
                       "description": "Total number of pages",
                       "minimum": 0
                   }
               },
               "required": ["page", "pageSize", "totalCount", "totalPages"],
               "examples": [
                   {"page": 1, "pageSize": 20, "totalCount": 95, "totalPages": 5},
                   {"page": 3, "pageSize": 50, "totalCount": 125, "totalPages": 3}
               ]
           }',
           ARRAY['pagination', 'info', 'page-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'pageInfoExtended',
           'Extended page information with navigation flags.',
           'pagination',
           '{
               "type": "object",
               "description": "Extended pagination info",
               "properties": {
                   "page": {
                       "type": "integer",
                       "description": "Current page number",
                       "minimum": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page"
                   },
                   "totalCount": {
                       "type": "integer",
                       "description": "Total number of items",
                       "minimum": 0
                   },
                   "totalPages": {
                       "type": "integer",
                       "description": "Total number of pages",
                       "minimum": 0
                   },
                   "count": {
                       "type": "integer",
                       "description": "Items in current page",
                       "minimum": 0
                   },
                   "hasNextPage": {
                       "type": "boolean",
                       "description": "Whether next page exists"
                   },
                   "hasPreviousPage": {
                       "type": "boolean",
                       "description": "Whether previous page exists"
                   },
                   "isFirstPage": {
                       "type": "boolean",
                       "description": "Whether this is first page"
                   },
                   "isLastPage": {
                       "type": "boolean",
                       "description": "Whether this is last page"
                   }
               },
               "required": ["page", "pageSize", "totalCount", "totalPages", "hasNextPage", "hasPreviousPage"],
               "examples": [
                   {
                       "page": 2,
                       "pageSize": 20,
                       "totalCount": 95,
                       "totalPages": 5,
                       "count": 20,
                       "hasNextPage": true,
                       "hasPreviousPage": true,
                       "isFirstPage": false,
                       "isLastPage": false
                   }
               ]
           }',
           ARRAY['pagination', 'info', 'extended', 'navigation', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'offsetInfo',
           'Offset-based pagination information.',
           'pagination',
           '{
               "type": "object",
               "description": "Offset-based pagination info",
               "properties": {
                   "offset": {
                       "type": "integer",
                       "description": "Current offset",
                       "minimum": 0
                   },
                   "limit": {
                       "type": "integer",
                       "description": "Items per request"
                   },
                   "count": {
                       "type": "integer",
                       "description": "Items returned",
                       "minimum": 0
                   },
                   "totalCount": {
                       "type": "integer",
                       "description": "Total items available",
                       "minimum": 0
                   },
                   "hasMore": {
                       "type": "boolean",
                       "description": "Whether more items exist"
                   }
               },
               "required": ["offset", "limit", "count", "totalCount", "hasMore"],
               "examples": [
                   {"offset": 20, "limit": 20, "count": 20, "totalCount": 95, "hasMore": true},
                   {"offset": 80, "limit": 20, "count": 15, "totalCount": 95, "hasMore": false}
               ]
           }',
           ARRAY['pagination', 'info', 'offset-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cursorInfo',
           'Cursor-based pagination information.',
           'pagination',
           '{
               "type": "object",
               "description": "Cursor-based pagination info",
               "properties": {
                   "count": {
                       "type": "integer",
                       "description": "Items returned",
                       "minimum": 0
                   },
                   "hasNextPage": {
                       "type": "boolean",
                       "description": "Whether next page exists"
                   },
                   "hasPreviousPage": {
                       "type": "boolean",
                       "description": "Whether previous page exists"
                   },
                   "startCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor for first item"
                   },
                   "endCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor for last item"
                   },
                   "nextCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor for next page"
                   },
                   "prevCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor for previous page"
                   }
               },
               "required": ["count", "hasNextPage", "hasPreviousPage"],
               "examples": [
                   {
                       "count": 20,
                       "hasNextPage": true,
                       "hasPreviousPage": true,
                       "startCursor": "eyJpZCI6MTIzfQ==",
                       "endCursor": "eyJpZCI6MTQyfQ==",
                       "nextCursor": "eyJpZCI6MTQzfQ==",
                       "prevCursor": "eyJpZCI6MTIyfQ=="
                   }
               ]
           }',
           ARRAY['pagination', 'info', 'cursor-based', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'relayPageInfo',
           'Relay-style PageInfo object (GraphQL Connection spec).',
           'pagination',
           '{
               "type": "object",
               "description": "Relay-style PageInfo",
               "properties": {
                   "hasNextPage": {
                       "type": "boolean",
                       "description": "Whether more edges exist forward"
                   },
                   "hasPreviousPage": {
                       "type": "boolean",
                       "description": "Whether more edges exist backward"
                   },
                   "startCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor of first edge"
                   },
                   "endCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor of last edge"
                   }
               },
               "required": ["hasNextPage", "hasPreviousPage"],
               "examples": [
                   {
                       "hasNextPage": true,
                       "hasPreviousPage": false,
                       "startCursor": "YXJyYXljb25uZWN0aW9uOjA=",
                       "endCursor": "YXJyYXljb25uZWN0aW9uOjE5"
                   }
               ]
           }',
           ARRAY['pagination', 'info', 'relay', 'graphql', 'cursor-based'],
           true,
           true
       );

-- =============================================================================
-- PAGINATED RESPONSE WRAPPERS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'paginatedResponse',
           'Generic paginated response wrapper with items and metadata.',
           'pagination',
           '{
               "type": "object",
               "description": "Generic paginated response",
               "properties": {
                   "items": {
                       "type": "array",
                       "description": "Array of result items",
                       "items": {}
                   },
                   "pagination": {
                       "type": "object",
                       "description": "Pagination metadata",
                       "properties": {
                           "page": {"type": "integer", "minimum": 1},
                           "pageSize": {"type": "integer"},
                           "totalCount": {"type": "integer", "minimum": 0},
                           "totalPages": {"type": "integer", "minimum": 0},
                           "hasNextPage": {"type": "boolean"},
                           "hasPreviousPage": {"type": "boolean"}
                       },
                       "required": ["page", "pageSize", "totalCount", "totalPages"]
                   }
               },
               "required": ["items", "pagination"],
               "examples": [
                   {
                       "items": [{"id": 1}, {"id": 2}, {"id": 3}],
                       "pagination": {
                           "page": 1,
                           "pageSize": 20,
                           "totalCount": 3,
                           "totalPages": 1,
                           "hasNextPage": false,
                           "hasPreviousPage": false
                       }
                   }
               ]
           }',
           ARRAY['pagination', 'response', 'wrapper', 'generic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cursorPaginatedResponse',
           'Cursor-based paginated response wrapper.',
           'pagination',
           '{
               "type": "object",
               "description": "Cursor-based paginated response",
               "properties": {
                   "items": {
                       "type": "array",
                       "description": "Array of result items",
                       "items": {}
                   },
                   "pageInfo": {
                       "type": "object",
                       "description": "Cursor pagination info",
                       "properties": {
                           "hasNextPage": {"type": "boolean"},
                           "hasPreviousPage": {"type": "boolean"},
                           "startCursor": {"type": ["string", "null"]},
                           "endCursor": {"type": ["string", "null"]}
                       },
                       "required": ["hasNextPage", "hasPreviousPage"]
                   },
                   "totalCount": {
                       "type": ["integer", "null"],
                       "description": "Total count (if available)",
                       "minimum": 0
                   }
               },
               "required": ["items", "pageInfo"],
               "examples": [
                   {
                       "items": [{"id": 1}, {"id": 2}],
                       "pageInfo": {
                           "hasNextPage": true,
                           "hasPreviousPage": false,
                           "startCursor": "eyJpZCI6MX0=",
                           "endCursor": "eyJpZCI6Mn0="
                       },
                       "totalCount": 100
                   }
               ]
           }',
           ARRAY['pagination', 'response', 'cursor-based', 'wrapper'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'relayConnection',
           'Relay-style Connection object (GraphQL Connection spec).',
           'pagination',
           '{
               "type": "object",
               "description": "Relay-style Connection",
               "properties": {
                   "edges": {
                       "type": "array",
                       "description": "Array of Edge objects",
                       "items": {
                           "type": "object",
                           "properties": {
                               "node": {
                                   "description": "The actual item"
                               },
                               "cursor": {
                                   "type": "string",
                                   "description": "Cursor for this edge"
                               }
                           },
                           "required": ["node", "cursor"]
                       }
                   },
                   "pageInfo": {
                       "type": "object",
                       "description": "Pagination info",
                       "properties": {
                           "hasNextPage": {"type": "boolean"},
                           "hasPreviousPage": {"type": "boolean"},
                           "startCursor": {"type": ["string", "null"]},
                           "endCursor": {"type": ["string", "null"]}
                       },
                       "required": ["hasNextPage", "hasPreviousPage"]
                   },
                   "totalCount": {
                       "type": ["integer", "null"],
                       "description": "Total count (optional)",
                       "minimum": 0
                   }
               },
               "required": ["edges", "pageInfo"],
               "examples": [
                   {
                       "edges": [
                           {"node": {"id": 1, "name": "Item 1"}, "cursor": "YXJyYXljb25uZWN0aW9uOjA="},
                           {"node": {"id": 2, "name": "Item 2"}, "cursor": "YXJyYXljb25uZWN0aW9uOjE="}
                       ],
                       "pageInfo": {
                           "hasNextPage": true,
                           "hasPreviousPage": false,
                           "startCursor": "YXJyYXljb25uZWN0aW9uOjA=",
                           "endCursor": "YXJyYXljb25uZWN0aW9uOjE="
                       },
                       "totalCount": 100
                   }
               ]
           }',
           ARRAY['pagination', 'relay', 'connection', 'graphql', 'edges'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'infiniteScrollResponse',
           'Response format optimized for infinite scroll UIs.',
           'pagination',
           '{
               "type": "object",
               "description": "Infinite scroll response",
               "properties": {
                   "items": {
                       "type": "array",
                       "description": "Array of items",
                       "items": {}
                   },
                   "nextCursor": {
                       "type": ["string", "null"],
                       "description": "Cursor to load more items"
                   },
                   "hasMore": {
                       "type": "boolean",
                       "description": "Whether more items can be loaded"
                   },
                   "count": {
                       "type": "integer",
                       "description": "Number of items returned",
                       "minimum": 0
                   }
               },
               "required": ["items", "hasMore"],
               "examples": [
                   {
                       "items": [{"id": 1}, {"id": 2}, {"id": 3}],
                       "nextCursor": "eyJpZCI6M30=",
                       "hasMore": true,
                       "count": 3
                   },
                   {
                       "items": [{"id": 98}, {"id": 99}, {"id": 100}],
                       "nextCursor": null,
                       "hasMore": false,
                       "count": 3
                   }
               ]
           }',
           ARRAY['pagination', 'infinite-scroll', 'response', 'cursor-based'],
           true,
           true
       );

-- =============================================================================
-- SORTING AND ORDERING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortField',
           'Field name to sort by.',
           'pagination',
           '{
               "type": "string",
               "description": "Field to sort by",
               "examples": ["createdAt", "name", "updatedAt", "id", "price"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['sort', 'field', 'order'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortOrder',
           'Sort direction (ascending or descending).',
           'pagination',
           '{
               "type": "string",
               "description": "Sort direction",
               "enum": ["asc", "desc"],
               "examples": ["asc", "desc"],
               "default": "asc"
           }',
           ARRAY['sort', 'order', 'direction'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortBy',
           'Combined sort specification.',
           'pagination',
           '{
               "type": "object",
               "description": "Sort specification",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Field to sort by"
                   },
                   "order": {
                       "type": "string",
                       "description": "Sort direction",
                       "enum": ["asc", "desc"],
                       "default": "asc"
                   }
               },
               "required": ["field"],
               "examples": [
                   {"field": "createdAt", "order": "desc"},
                   {"field": "name", "order": "asc"}
               ]
           }',
           ARRAY['sort', 'specification', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortByMultiple',
           'Multiple sort specifications for compound sorting.',
           'pagination',
           '{
               "type": "array",
               "description": "Multiple sort specifications",
               "items": {
                   "type": "object",
                   "properties": {
                       "field": {
                           "type": "string",
                           "description": "Field to sort by"
                       },
                       "order": {
                           "type": "string",
                           "description": "Sort direction",
                           "enum": ["asc", "desc"],
                           "default": "asc"
                       }
                   },
                   "required": ["field"]
               },
               "examples": [
                   [
                       {"field": "lastName", "order": "asc"},
                       {"field": "firstName", "order": "asc"}
                   ],
                   [
                       {"field": "priority", "order": "desc"},
                       {"field": "createdAt", "order": "asc"}
                   ]
               ]
           }',
           ARRAY['sort', 'multiple', 'compound', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortString',
           'Sort specification as a string (e.g., "createdAt:desc").',
           'pagination',
           '{
               "type": "string",
               "description": "Sort as string (field:direction)",
               "examples": ["createdAt:desc", "name:asc", "price:desc,name:asc"],
               "pattern": "^[a-zA-Z0-9_]+(:(asc|desc))?(,[a-zA-Z0-9_]+(:(asc|desc))?)*$"
           }',
           ARRAY['sort', 'string', 'compact'],
           true,
           true
       );

-- =============================================================================
-- PAGINATION WITH SORTING COMBINED
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'paginationRequest',
           'Complete pagination request with sorting.',
           'pagination',
           '{
               "type": "object",
               "description": "Complete pagination request",
               "properties": {
                   "page": {
                       "type": "integer",
                       "description": "Page number",
                       "minimum": 1,
                       "default": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   },
                   "sortBy": {
                       "type": ["string", "null"],
                       "description": "Field to sort by"
                   },
                   "sortOrder": {
                       "type": "string",
                       "description": "Sort direction",
                       "enum": ["asc", "desc"],
                       "default": "asc"
                   }
               },
               "examples": [
                   {"page": 1, "pageSize": 20, "sortBy": "createdAt", "sortOrder": "desc"},
                   {"page": 2, "pageSize": 50, "sortBy": "name", "sortOrder": "asc"}
               ]
           }',
           ARRAY['pagination', 'request', 'sort', 'complete'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'queryParams',
           'Common query parameters for list endpoints.',
           'pagination',
           '{
               "type": "object",
               "description": "List endpoint query parameters",
               "properties": {
                   "page": {
                       "type": "integer",
                       "description": "Page number",
                       "minimum": 1,
                       "default": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page",
                       "minimum": 1,
                       "maximum": 100,
                       "default": 20
                   },
                   "sortBy": {
                       "type": ["string", "null"],
                       "description": "Sort field"
                   },
                   "sortOrder": {
                       "type": "string",
                       "description": "Sort direction",
                       "enum": ["asc", "desc"],
                       "default": "desc"
                   },
                   "search": {
                       "type": ["string", "null"],
                       "description": "Search query"
                   },
                   "filter": {
                       "type": ["object", "null"],
                       "description": "Filter criteria"
                   }
               },
               "examples": [
                   {
                       "page": 1,
                       "pageSize": 20,
                       "sortBy": "createdAt",
                       "sortOrder": "desc",
                       "search": "example",
                       "filter": {"status": "active"}
                   }
               ]
           }',
           ARRAY['pagination', 'query', 'params', 'search', 'filter'],
           true,
           true
       );

-- =============================================================================
-- PAGINATION LINKS (HATEOAS)
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'paginationLinks',
           'HATEOAS-style pagination links.',
           'pagination',
           '{
               "type": "object",
               "description": "Pagination navigation links",
               "properties": {
                   "self": {
                       "type": "string",
                       "format": "uri",
                       "description": "Current page URL"
                   },
                   "first": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "First page URL"
                   },
                   "prev": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Previous page URL"
                   },
                   "next": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Next page URL"
                   },
                   "last": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Last page URL"
                   }
               },
               "required": ["self"],
               "examples": [
                   {
                       "self": "/api/items?page=2&pageSize=20",
                       "first": "/api/items?page=1&pageSize=20",
                       "prev": "/api/items?page=1&pageSize=20",
                       "next": "/api/items?page=3&pageSize=20",
                       "last": "/api/items?page=5&pageSize=20"
                   }
               ]
           }',
           ARRAY['pagination', 'links', 'hateoas', 'navigation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'linkHeader',
           'Link header format for pagination (RFC 5988).',
           'pagination',
           '{
               "type": "string",
               "description": "Link header for pagination",
               "examples": [
                   "</api/items?page=3>; rel=\"next\", </api/items?page=1>; rel=\"prev\", </api/items?page=1>; rel=\"first\", </api/items?page=5>; rel=\"last\""
               ]
           }',
           ARRAY['pagination', 'link-header', 'rfc5988', 'http'],
           true,
           true
       );