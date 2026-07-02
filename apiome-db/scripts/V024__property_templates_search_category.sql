-- Property Templates: Search Category
-- These templates define common patterns for searching, filtering, and querying data
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO apiome, public;

-- =============================================================================
-- BASIC SEARCH FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'query',
           'Free-text search query string.',
           'search',
           '{
               "type": "string",
               "description": "Search query string",
               "examples": ["machine learning", "user:john status:active", "price>100"],
               "minLength": 1,
               "maxLength": 1000
           }',
           ARRAY['query', 'search', 'text', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'queryNullable',
           'Optional free-text search query string.',
           'search',
           '{
               "type": ["string", "null"],
               "description": "Optional search query string",
               "examples": ["machine learning", null],
               "maxLength": 1000
           }',
           ARRAY['query', 'search', 'text', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchTerm',
           'Simple search term for basic text matching.',
           'search',
           '{
               "type": "string",
               "description": "Simple search term",
               "examples": ["laptop", "john doe", "invoice-2024"],
               "minLength": 1,
               "maxLength": 255
           }',
           ARRAY['search', 'term', 'simple', 'text'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'keywords',
           'Array of search keywords.',
           'search',
           '{
               "type": "array",
               "description": "Search keywords",
               "items": {
                   "type": "string",
                   "minLength": 1,
                   "maxLength": 100
               },
               "examples": [
                   ["machine", "learning", "python"],
                   ["urgent", "bug", "production"]
               ]
           }',
           ARRAY['keywords', 'search', 'array', 'terms'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phrase',
           'Exact phrase to search for.',
           'search',
           '{
               "type": "string",
               "description": "Exact phrase to match",
               "examples": ["machine learning engineer", "out of stock", "pending approval"],
               "minLength": 1,
               "maxLength": 500
           }',
           ARRAY['phrase', 'exact', 'search', 'text'],
           true,
           true
       );

-- =============================================================================
-- FILTER FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filter',
           'Generic filter object with field-value pairs.',
           'search',
           '{
               "type": "object",
               "description": "Filter criteria as field-value pairs",
               "additionalProperties": true,
               "examples": [
                   {"status": "active", "type": "premium"},
                   {"category": "electronics", "inStock": true}
               ]
           }',
           ARRAY['filter', 'criteria', 'generic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filterNullable',
           'Optional filter object.',
           'search',
           '{
               "type": ["object", "null"],
               "description": "Optional filter criteria",
               "additionalProperties": true,
               "examples": [
                   {"status": "active"},
                   null
               ]
           }',
           ARRAY['filter', 'criteria', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filters',
           'Array of filter conditions.',
           'search',
           '{
               "type": "array",
               "description": "Array of filter conditions",
               "items": {
                   "type": "object",
                   "properties": {
                       "field": {
                           "type": "string",
                           "description": "Field to filter on"
                       },
                       "operator": {
                           "type": "string",
                           "description": "Filter operator",
                           "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "startsWith", "endsWith", "exists", "regex"]
                       },
                       "value": {
                           "description": "Filter value"
                       }
                   },
                   "required": ["field", "operator", "value"]
               },
               "examples": [
                   [
                       {"field": "status", "operator": "eq", "value": "active"},
                       {"field": "price", "operator": "gte", "value": 100}
                   ]
               ]
           }',
           ARRAY['filters', 'array', 'conditions', 'operators'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filterExpression',
           'Complex filter expression with logical operators.',
           'search',
           '{
               "type": "object",
               "description": "Complex filter expression",
               "properties": {
                   "and": {
                       "type": "array",
                       "description": "Conditions combined with AND",
                       "items": {}
                   },
                   "or": {
                       "type": "array",
                       "description": "Conditions combined with OR",
                       "items": {}
                   },
                   "not": {
                       "description": "Negated condition"
                   },
                   "field": {
                       "type": "string",
                       "description": "Field name for simple condition"
                   },
                   "operator": {
                       "type": "string",
                       "description": "Comparison operator"
                   },
                   "value": {
                       "description": "Comparison value"
                   }
               },
               "examples": [
                   {
                       "and": [
                           {"field": "status", "operator": "eq", "value": "active"},
                           {
                               "or": [
                                   {"field": "priority", "operator": "eq", "value": "high"},
                                   {"field": "urgent", "operator": "eq", "value": true}
                               ]
                           }
                       ]
                   }
               ]
           }',
           ARRAY['filter', 'expression', 'complex', 'logical'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filterGroup',
           'Group of filters with logical combination.',
           'search',
           '{
               "type": "object",
               "description": "Group of filters",
               "properties": {
                   "logic": {
                       "type": "string",
                       "description": "Logical operator for combining filters",
                       "enum": ["and", "or"],
                       "default": "and"
                   },
                   "filters": {
                       "type": "array",
                       "description": "Filter conditions",
                       "items": {
                           "type": "object",
                           "properties": {
                               "field": {"type": "string"},
                               "operator": {"type": "string"},
                               "value": {}
                           },
                           "required": ["field", "operator", "value"]
                       }
                   }
               },
               "required": ["filters"],
               "examples": [
                   {
                       "logic": "and",
                       "filters": [
                           {"field": "status", "operator": "eq", "value": "active"},
                           {"field": "createdAt", "operator": "gte", "value": "2024-01-01"}
                       ]
                   }
               ]
           }',
           ARRAY['filter', 'group', 'logical', 'composite'],
           true,
           true
       );

-- =============================================================================
-- FILTER OPERATOR FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filterOperator',
           'Comparison operator for filter conditions.',
           'search',
           '{
               "type": "string",
               "description": "Filter comparison operator",
               "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "startsWith", "endsWith", "exists", "regex", "between"],
               "examples": ["eq", "gte", "contains"]
           }',
           ARRAY['filter', 'operator', 'comparison', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'filterCondition',
           'Single filter condition with field, operator, and value.',
           'search',
           '{
               "type": "object",
               "description": "Single filter condition",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Field to filter on"
                   },
                   "operator": {
                       "type": "string",
                       "description": "Comparison operator",
                       "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "startsWith", "endsWith", "exists", "regex", "between"]
                   },
                   "value": {
                       "description": "Value to compare against"
                   }
               },
               "required": ["field", "operator", "value"],
               "examples": [
                   {"field": "status", "operator": "eq", "value": "active"},
                   {"field": "price", "operator": "between", "value": [100, 500]},
                   {"field": "tags", "operator": "in", "value": ["featured", "sale"]}
               ]
           }',
           ARRAY['filter', 'condition', 'single', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'rangeFilter',
           'Range filter with min and max values.',
           'search',
           '{
               "type": "object",
               "description": "Range filter",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Field to filter on"
                   },
                   "min": {
                       "description": "Minimum value (inclusive)"
                   },
                   "max": {
                       "description": "Maximum value (inclusive)"
                   },
                   "minExclusive": {
                       "type": "boolean",
                       "description": "Exclude minimum value",
                       "default": false
                   },
                   "maxExclusive": {
                       "type": "boolean",
                       "description": "Exclude maximum value",
                       "default": false
                   }
               },
               "required": ["field"],
               "examples": [
                   {"field": "price", "min": 100, "max": 500},
                   {"field": "date", "min": "2024-01-01", "max": "2024-12-31"},
                   {"field": "rating", "min": 4, "max": null}
               ]
           }',
           ARRAY['filter', 'range', 'min', 'max'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateRangeFilter',
           'Date-specific range filter.',
           'search',
           '{
               "type": "object",
               "description": "Date range filter",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Date field to filter on"
                   },
                   "from": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "Start date (inclusive)"
                   },
                   "to": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "End date (inclusive)"
                   },
                   "preset": {
                       "type": ["string", "null"],
                       "description": "Preset date range",
                       "enum": ["today", "yesterday", "thisWeek", "lastWeek", "thisMonth", "lastMonth", "thisQuarter", "lastQuarter", "thisYear", "lastYear", "last7Days", "last30Days", "last90Days", null]
                   }
               },
               "required": ["field"],
               "examples": [
                   {"field": "createdAt", "from": "2024-01-01T00:00:00Z", "to": "2024-12-31T23:59:59Z", "preset": null},
                   {"field": "updatedAt", "from": null, "to": null, "preset": "last30Days"}
               ]
           }',
           ARRAY['filter', 'date', 'range', 'preset'],
           true,
           true
       );

-- =============================================================================
-- SORT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sort',
           'Sort specification with field and direction.',
           'search',
           '{
               "type": "object",
               "description": "Sort specification",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Field to sort by"
                   },
                   "direction": {
                       "type": "string",
                       "description": "Sort direction",
                       "enum": ["asc", "desc"],
                       "default": "asc"
                   }
               },
               "required": ["field"],
               "examples": [
                   {"field": "createdAt", "direction": "desc"},
                   {"field": "name", "direction": "asc"}
               ]
           }',
           ARRAY['sort', 'order', 'single'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortArray',
           'Array of sort specifications for multi-field sorting.',
           'search',
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
                       "direction": {
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
                       {"field": "priority", "direction": "desc"},
                       {"field": "createdAt", "direction": "asc"}
                   ]
               ]
           }',
           ARRAY['sort', 'array', 'multiple', 'order'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortString',
           'Sort specification as a compact string.',
           'search',
           '{
               "type": "string",
               "description": "Sort as string (field:direction,...)",
               "examples": ["createdAt:desc", "name:asc", "priority:desc,createdAt:asc", "-createdAt,+name"],
               "pattern": "^[+-]?[a-zA-Z0-9_.]+(:(?:asc|desc))?(,[+-]?[a-zA-Z0-9_.]+(:(?:asc|desc))?)*$"
           }',
           ARRAY['sort', 'string', 'compact'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortDirection',
           'Sort direction enumeration.',
           'search',
           '{
               "type": "string",
               "description": "Sort direction",
               "enum": ["asc", "desc", "ascending", "descending"],
               "examples": ["asc", "desc"]
           }',
           ARRAY['sort', 'direction', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortNullHandling',
           'How to handle null values in sorting.',
           'search',
           '{
               "type": "string",
               "description": "Null value handling in sort",
               "enum": ["nullsFirst", "nullsLast", "default"],
               "examples": ["nullsFirst", "nullsLast"],
               "default": "default"
           }',
           ARRAY['sort', 'nulls', 'handling'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'sortWithNulls',
           'Sort specification with null handling.',
           'search',
           '{
               "type": "object",
               "description": "Sort with null handling",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Field to sort by"
                   },
                   "direction": {
                       "type": "string",
                       "description": "Sort direction",
                       "enum": ["asc", "desc"],
                       "default": "asc"
                   },
                   "nulls": {
                       "type": "string",
                       "description": "Null handling",
                       "enum": ["first", "last"],
                       "default": "last"
                   }
               },
               "required": ["field"],
               "examples": [
                   {"field": "completedAt", "direction": "desc", "nulls": "last"},
                   {"field": "priority", "direction": "asc", "nulls": "first"}
               ]
           }',
           ARRAY['sort', 'nulls', 'composite'],
           true,
           true
       );

-- =============================================================================
-- FIELD SELECTION
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fields',
           'Array of field names to include in response.',
           'search',
           '{
               "type": "array",
               "description": "Fields to include in response",
               "items": {
                   "type": "string"
               },
               "uniqueItems": true,
               "examples": [
                   ["id", "name", "email"],
                   ["id", "title", "createdAt", "status"]
               ]
           }',
           ARRAY['fields', 'select', 'projection', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fieldsString',
           'Comma-separated list of fields to include.',
           'search',
           '{
               "type": "string",
               "description": "Comma-separated field names",
               "examples": ["id,name,email", "id,title,createdAt,status"],
               "pattern": "^[a-zA-Z0-9_.]+(,[a-zA-Z0-9_.]+)*$"
           }',
           ARRAY['fields', 'select', 'string', 'csv'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'include',
           'Fields or relations to include in response.',
           'search',
           '{
               "type": "array",
               "description": "Fields or relations to include",
               "items": {
                   "type": "string"
               },
               "uniqueItems": true,
               "examples": [
                   ["author", "comments"],
                   ["user", "organization", "permissions"]
               ]
           }',
           ARRAY['include', 'relations', 'expand', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'exclude',
           'Fields to exclude from response.',
           'search',
           '{
               "type": "array",
               "description": "Fields to exclude from response",
               "items": {
                   "type": "string"
               },
               "uniqueItems": true,
               "examples": [
                   ["password", "secret"],
                   ["internalNotes", "adminComments"]
               ]
           }',
           ARRAY['exclude', 'omit', 'fields', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fieldSelection',
           'Field selection with include and exclude options.',
           'search',
           '{
               "type": "object",
               "description": "Field selection configuration",
               "properties": {
                   "include": {
                       "type": ["array", "null"],
                       "description": "Fields to include",
                       "items": {"type": "string"}
                   },
                   "exclude": {
                       "type": ["array", "null"],
                       "description": "Fields to exclude",
                       "items": {"type": "string"}
                   }
               },
               "examples": [
                   {"include": ["id", "name", "email"], "exclude": null},
                   {"include": null, "exclude": ["password", "secret"]}
               ]
           }',
           ARRAY['fields', 'selection', 'include', 'exclude', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'expand',
           'Relations or nested objects to expand/populate.',
           'search',
           '{
               "type": "array",
               "description": "Relations to expand",
               "items": {
                   "type": "string"
               },
               "uniqueItems": true,
               "examples": [
                   ["author", "comments.author"],
                   ["user.profile", "organization"]
               ]
           }',
           ARRAY['expand', 'populate', 'relations', 'nested'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'expandConfig',
           'Detailed expansion configuration with field selection.',
           'search',
           '{
               "type": "array",
               "description": "Expansion configuration",
               "items": {
                   "type": "object",
                   "properties": {
                       "relation": {
                           "type": "string",
                           "description": "Relation to expand"
                       },
                       "fields": {
                           "type": ["array", "null"],
                           "description": "Fields to include from expanded relation",
                           "items": {"type": "string"}
                       },
                       "nested": {
                           "type": ["array", "null"],
                           "description": "Nested relations to expand",
                           "items": {"type": "string"}
                       }
                   },
                   "required": ["relation"]
               },
               "examples": [
                   [
                       {"relation": "author", "fields": ["id", "name"], "nested": null},
                       {"relation": "comments", "fields": ["id", "text", "createdAt"], "nested": ["author"]}
                   ]
               ]
           }',
           ARRAY['expand', 'config', 'detailed', 'relations'],
           true,
           true
       );

-- =============================================================================
-- FULL-TEXT SEARCH FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fullTextQuery',
           'Full-text search query with options.',
           'search',
           '{
               "type": "object",
               "description": "Full-text search query",
               "properties": {
                   "query": {
                       "type": "string",
                       "description": "Search query text"
                   },
                   "fields": {
                       "type": ["array", "null"],
                       "description": "Fields to search in",
                       "items": {"type": "string"}
                   },
                   "matchType": {
                       "type": "string",
                       "description": "How to match terms",
                       "enum": ["all", "any", "phrase", "prefix", "fuzzy"],
                       "default": "all"
                   },
                   "fuzziness": {
                       "type": ["integer", "string", "null"],
                       "description": "Fuzziness level for fuzzy matching"
                   }
               },
               "required": ["query"],
               "examples": [
                   {"query": "machine learning python", "fields": ["title", "description"], "matchType": "all", "fuzziness": null},
                   {"query": "developr", "fields": null, "matchType": "fuzzy", "fuzziness": 1}
               ]
           }',
           ARRAY['fulltext', 'search', 'query', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchHighlight',
           'Configuration for search result highlighting.',
           'search',
           '{
               "type": "object",
               "description": "Search highlighting configuration",
               "properties": {
                   "enabled": {
                       "type": "boolean",
                       "description": "Enable highlighting",
                       "default": false
                   },
                   "fields": {
                       "type": ["array", "null"],
                       "description": "Fields to highlight",
                       "items": {"type": "string"}
                   },
                   "preTag": {
                       "type": "string",
                       "description": "Tag before highlighted term",
                       "default": "<em>"
                   },
                   "postTag": {
                       "type": "string",
                       "description": "Tag after highlighted term",
                       "default": "</em>"
                   },
                   "fragmentSize": {
                       "type": ["integer", "null"],
                       "description": "Size of highlight fragments"
                   },
                   "numberOfFragments": {
                       "type": ["integer", "null"],
                       "description": "Number of fragments to return"
                   }
               },
               "examples": [
                   {
                       "enabled": true,
                       "fields": ["title", "description"],
                       "preTag": "<mark>",
                       "postTag": "</mark>",
                       "fragmentSize": 150,
                       "numberOfFragments": 3
                   }
               ]
           }',
           ARRAY['search', 'highlight', 'snippet', 'config'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchBoost',
           'Field boosting configuration for search relevance.',
           'search',
           '{
               "type": "object",
               "description": "Field boost configuration",
               "additionalProperties": {
                   "type": "number",
                   "description": "Boost factor for field",
                   "minimum": 0
               },
               "examples": [
                   {"title": 2.0, "description": 1.0, "tags": 1.5},
                   {"name": 3.0, "email": 1.0, "bio": 0.5}
               ]
           }',
           ARRAY['search', 'boost', 'relevance', 'weight'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchSuggestion',
           'Search suggestion/autocomplete result.',
           'search',
           '{
               "type": "object",
               "description": "Search suggestion",
               "properties": {
                   "text": {
                       "type": "string",
                       "description": "Suggested text"
                   },
                   "highlighted": {
                       "type": ["string", "null"],
                       "description": "Highlighted suggestion"
                   },
                   "score": {
                       "type": ["number", "null"],
                       "description": "Relevance score"
                   },
                   "frequency": {
                       "type": ["integer", "null"],
                       "description": "Frequency count"
                   },
                   "metadata": {
                       "type": ["object", "null"],
                       "description": "Additional metadata"
                   }
               },
               "required": ["text"],
               "examples": [
                   {"text": "machine learning", "highlighted": "<em>machine</em> learning", "score": 0.95, "frequency": 1250, "metadata": null}
               ]
           }',
           ARRAY['search', 'suggestion', 'autocomplete', 'result'],
           true,
           true
       );

-- =============================================================================
-- SEARCH RESULT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchScore',
           'Relevance score for a search result.',
           'search',
           '{
               "type": "number",
               "description": "Search relevance score",
               "examples": [0.95, 0.87, 0.65, 1.0],
               "minimum": 0
           }',
           ARRAY['search', 'score', 'relevance'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchRank',
           'Rank position in search results.',
           'search',
           '{
               "type": "integer",
               "description": "Position in search results",
               "examples": [1, 2, 10, 100],
               "minimum": 1
           }',
           ARRAY['search', 'rank', 'position'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchHighlights',
           'Highlighted snippets from search results.',
           'search',
           '{
               "type": "object",
               "description": "Highlighted search snippets by field",
               "additionalProperties": {
                   "type": "array",
                   "items": {"type": "string"}
               },
               "examples": [
                   {
                       "title": ["Introduction to <em>Machine Learning</em>"],
                       "description": ["This course covers <em>machine learning</em> fundamentals...", "Advanced <em>machine learning</em> techniques..."]
                   }
               ]
           }',
           ARRAY['search', 'highlights', 'snippets', 'result'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchResultItem',
           'Single search result with score and highlights.',
           'search',
           '{
               "type": "object",
               "description": "Search result item",
               "properties": {
                   "item": {
                       "description": "The matched item"
                   },
                   "score": {
                       "type": "number",
                       "description": "Relevance score",
                       "minimum": 0
                   },
                   "highlights": {
                       "type": ["object", "null"],
                       "description": "Highlighted snippets",
                       "additionalProperties": {
                           "type": "array",
                           "items": {"type": "string"}
                       }
                   },
                   "matchedFields": {
                       "type": ["array", "null"],
                       "description": "Fields that matched",
                       "items": {"type": "string"}
                   }
               },
               "required": ["item", "score"],
               "examples": [
                   {
                       "item": {"id": "123", "title": "Machine Learning Guide"},
                       "score": 0.95,
                       "highlights": {"title": ["<em>Machine Learning</em> Guide"]},
                       "matchedFields": ["title", "description"]
                   }
               ]
           }',
           ARRAY['search', 'result', 'item', 'composite'],
           true,
           true
       );

-- =============================================================================
-- AGGREGATION AND FACET FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'facet',
           'Facet/aggregation result for a field.',
           'search',
           '{
               "type": "object",
               "description": "Facet result",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Faceted field name"
                   },
                   "buckets": {
                       "type": "array",
                       "description": "Facet buckets",
                       "items": {
                           "type": "object",
                           "properties": {
                               "value": {
                                   "description": "Bucket value"
                               },
                               "count": {
                                   "type": "integer",
                                   "description": "Number of items",
                                   "minimum": 0
                               }
                           },
                           "required": ["value", "count"]
                       }
                   },
                   "total": {
                       "type": ["integer", "null"],
                       "description": "Total unique values"
                   }
               },
               "required": ["field", "buckets"],
               "examples": [
                   {
                       "field": "category",
                       "buckets": [
                           {"value": "electronics", "count": 150},
                           {"value": "clothing", "count": 120},
                           {"value": "books", "count": 80}
                       ],
                       "total": 10
                   }
               ]
           }',
           ARRAY['facet', 'aggregation', 'bucket', 'count'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'facets',
           'Multiple facet results.',
           'search',
           '{
               "type": "object",
               "description": "Multiple facet results by field",
               "additionalProperties": {
                   "type": "array",
                   "items": {
                       "type": "object",
                       "properties": {
                           "value": {},
                           "count": {"type": "integer", "minimum": 0}
                       },
                       "required": ["value", "count"]
                   }
               },
               "examples": [
                   {
                       "category": [
                           {"value": "electronics", "count": 150},
                           {"value": "clothing", "count": 120}
                       ],
                       "brand": [
                           {"value": "Apple", "count": 50},
                           {"value": "Samsung", "count": 45}
                       ]
                   }
               ]
           }',
           ARRAY['facets', 'aggregations', 'multiple'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'facetRequest',
           'Request configuration for facets.',
           'search',
           '{
               "type": "array",
               "description": "Facet request configuration",
               "items": {
                   "type": "object",
                   "properties": {
                       "field": {
                           "type": "string",
                           "description": "Field to facet on"
                       },
                       "size": {
                           "type": "integer",
                           "description": "Maximum buckets to return",
                           "minimum": 1,
                           "default": 10
                       },
                       "minCount": {
                           "type": "integer",
                           "description": "Minimum count threshold",
                           "minimum": 0,
                           "default": 1
                       },
                       "sortBy": {
                           "type": "string",
                           "description": "Sort buckets by",
                           "enum": ["count", "value"],
                           "default": "count"
                       },
                       "sortOrder": {
                           "type": "string",
                           "description": "Sort direction",
                           "enum": ["asc", "desc"],
                           "default": "desc"
                       }
                   },
                   "required": ["field"]
               },
               "examples": [
                   [
                       {"field": "category", "size": 10, "minCount": 1, "sortBy": "count", "sortOrder": "desc"},
                       {"field": "brand", "size": 20, "minCount": 5, "sortBy": "value", "sortOrder": "asc"}
                   ]
               ]
           }',
           ARRAY['facet', 'request', 'config', 'aggregation'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'rangeFacet',
           'Range-based facet for numeric fields.',
           'search',
           '{
               "type": "object",
               "description": "Range facet result",
               "properties": {
                   "field": {
                       "type": "string",
                       "description": "Faceted field"
                   },
                   "ranges": {
                       "type": "array",
                       "description": "Range buckets",
                       "items": {
                           "type": "object",
                           "properties": {
                               "from": {
                                   "type": ["number", "null"],
                                   "description": "Range start"
                               },
                               "to": {
                                   "type": ["number", "null"],
                                   "description": "Range end"
                               },
                               "count": {
                                   "type": "integer",
                                   "description": "Items in range",
                                   "minimum": 0
                               },
                               "label": {
                                   "type": ["string", "null"],
                                   "description": "Display label"
                               }
                           },
                           "required": ["count"]
                       }
                   }
               },
               "required": ["field", "ranges"],
               "examples": [
                   {
                       "field": "price",
                       "ranges": [
                           {"from": null, "to": 50, "count": 120, "label": "Under $50"},
                           {"from": 50, "to": 100, "count": 85, "label": "$50 - $100"},
                           {"from": 100, "to": 200, "count": 60, "label": "$100 - $200"},
                           {"from": 200, "to": null, "count": 35, "label": "Over $200"}
                       ]
                   }
               ]
           }',
           ARRAY['facet', 'range', 'numeric', 'bucket'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE SEARCH REQUEST/RESPONSE OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchRequest',
           'Complete search request with query, filters, sort, and pagination.',
           'search',
           '{
               "type": "object",
               "description": "Complete search request",
               "properties": {
                   "query": {
                       "type": ["string", "null"],
                       "description": "Search query string"
                   },
                   "filters": {
                       "type": ["array", "object", "null"],
                       "description": "Filter conditions"
                   },
                   "sort": {
                       "type": ["array", "object", "null"],
                       "description": "Sort specification"
                   },
                   "fields": {
                       "type": ["array", "null"],
                       "description": "Fields to return",
                       "items": {"type": "string"}
                   },
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
                   "facets": {
                       "type": ["array", "null"],
                       "description": "Facets to compute"
                   },
                   "highlight": {
                       "type": ["object", "null"],
                       "description": "Highlighting configuration"
                   }
               },
               "examples": [
                   {
                       "query": "machine learning",
                       "filters": [{"field": "status", "operator": "eq", "value": "published"}],
                       "sort": [{"field": "createdAt", "direction": "desc"}],
                       "fields": ["id", "title", "description"],
                       "page": 1,
                       "pageSize": 20,
                       "facets": [{"field": "category"}],
                       "highlight": {"enabled": true, "fields": ["title", "description"]}
                   }
               ]
           }',
           ARRAY['search', 'request', 'complete', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchResponse',
           'Complete search response with results, pagination, and facets.',
           'search',
           '{
               "type": "object",
               "description": "Complete search response",
               "properties": {
                   "items": {
                       "type": "array",
                       "description": "Search results",
                       "items": {}
                   },
                   "totalCount": {
                       "type": "integer",
                       "description": "Total matching items",
                       "minimum": 0
                   },
                   "page": {
                       "type": "integer",
                       "description": "Current page",
                       "minimum": 1
                   },
                   "pageSize": {
                       "type": "integer",
                       "description": "Items per page"
                   },
                   "totalPages": {
                       "type": "integer",
                       "description": "Total pages",
                       "minimum": 0
                   },
                   "hasNextPage": {
                       "type": "boolean",
                       "description": "Whether more pages exist"
                   },
                   "facets": {
                       "type": ["object", "null"],
                       "description": "Facet results"
                   },
                   "query": {
                       "type": ["string", "null"],
                       "description": "Query that was executed"
                   },
                   "took": {
                       "type": ["integer", "null"],
                       "description": "Time taken in milliseconds"
                   }
               },
               "required": ["items", "totalCount"],
               "examples": [
                   {
                       "items": [{"id": "1", "title": "Result 1"}, {"id": "2", "title": "Result 2"}],
                       "totalCount": 150,
                       "page": 1,
                       "pageSize": 20,
                       "totalPages": 8,
                       "hasNextPage": true,
                       "facets": {
                           "category": [{"value": "tech", "count": 80}]
                       },
                       "query": "machine learning",
                       "took": 45
                   }
               ]
           }',
           ARRAY['search', 'response', 'complete', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchMetadata',
           'Metadata about a search operation.',
           'search',
           '{
               "type": "object",
               "description": "Search operation metadata",
               "properties": {
                   "query": {
                       "type": ["string", "null"],
                       "description": "Executed query"
                   },
                   "took": {
                       "type": "integer",
                       "description": "Time taken in milliseconds",
                       "minimum": 0
                   },
                   "timedOut": {
                       "type": "boolean",
                       "description": "Whether search timed out",
                       "default": false
                   },
                   "totalHits": {
                       "type": "integer",
                       "description": "Total matching documents",
                       "minimum": 0
                   },
                   "maxScore": {
                       "type": ["number", "null"],
                       "description": "Highest relevance score"
                   },
                   "shards": {
                       "type": ["object", "null"],
                       "description": "Shard statistics"
                   }
               },
               "required": ["took", "totalHits"],
               "examples": [
                   {
                       "query": "machine learning",
                       "took": 45,
                       "timedOut": false,
                       "totalHits": 1250,
                       "maxScore": 15.7,
                       "shards": null
                   }
               ]
           }',
           ARRAY['search', 'metadata', 'stats', 'performance'],
           true,
           true
       );

-- =============================================================================
-- AUTOCOMPLETE AND SUGGESTION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'autocompleteRequest',
           'Autocomplete/typeahead request.',
           'search',
           '{
               "type": "object",
               "description": "Autocomplete request",
               "properties": {
                   "prefix": {
                       "type": "string",
                       "description": "Text prefix to complete"
                   },
                   "field": {
                       "type": ["string", "null"],
                       "description": "Field to autocomplete on"
                   },
                   "limit": {
                       "type": "integer",
                       "description": "Maximum suggestions",
                       "minimum": 1,
                       "maximum": 50,
                       "default": 10
                   },
                   "fuzzy": {
                       "type": "boolean",
                       "description": "Enable fuzzy matching",
                       "default": false
                   },
                   "contexts": {
                       "type": ["object", "null"],
                       "description": "Context filters"
                   }
               },
               "required": ["prefix"],
               "examples": [
                   {"prefix": "mach", "field": "title", "limit": 10, "fuzzy": true, "contexts": null},
                   {"prefix": "new yo", "field": "city", "limit": 5, "fuzzy": false, "contexts": {"country": "US"}}
               ]
           }',
           ARRAY['autocomplete', 'typeahead', 'request', 'suggestion'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'autocompleteResponse',
           'Autocomplete/typeahead response.',
           'search',
           '{
               "type": "object",
               "description": "Autocomplete response",
               "properties": {
                   "suggestions": {
                       "type": "array",
                       "description": "Autocomplete suggestions",
                       "items": {
                           "type": "object",
                           "properties": {
                               "text": {
                                   "type": "string",
                                   "description": "Suggestion text"
                               },
                               "highlighted": {
                                   "type": ["string", "null"],
                                   "description": "Highlighted text"
                               },
                               "score": {
                                   "type": ["number", "null"],
                                   "description": "Relevance score"
                               },
                               "payload": {
                                   "type": ["object", "null"],
                                   "description": "Additional data"
                               }
                           },
                           "required": ["text"]
                       }
                   },
                   "prefix": {
                       "type": "string",
                       "description": "Original prefix"
                   }
               },
               "required": ["suggestions", "prefix"],
               "examples": [
                   {
                       "suggestions": [
                           {"text": "machine learning", "highlighted": "<em>mach</em>ine learning", "score": 0.95, "payload": {"category": "tech"}},
                           {"text": "machine vision", "highlighted": "<em>mach</em>ine vision", "score": 0.85, "payload": null}
                       ],
                       "prefix": "mach"
                   }
               ]
           }',
           ARRAY['autocomplete', 'typeahead', 'response', 'suggestion'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'didYouMean',
           'Spelling correction suggestion.',
           'search',
           '{
               "type": "object",
               "description": "Spelling correction",
               "properties": {
                   "original": {
                       "type": "string",
                       "description": "Original query"
                   },
                   "suggested": {
                       "type": "string",
                       "description": "Corrected query"
                   },
                   "highlighted": {
                       "type": ["string", "null"],
                       "description": "Highlighted correction"
                   },
                   "confidence": {
                       "type": ["number", "null"],
                       "description": "Confidence score",
                       "minimum": 0,
                       "maximum": 1
                   }
               },
               "required": ["original", "suggested"],
               "examples": [
                   {"original": "machien lerning", "suggested": "machine learning", "highlighted": "<em>machine</em> <em>learning</em>", "confidence": 0.92}
               ]
           }',
           ARRAY['spelling', 'correction', 'suggestion', 'did-you-mean'],
           true,
           true
       );

-- =============================================================================
-- SAVED SEARCH AND SEARCH HISTORY
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'savedSearch',
           'Saved search configuration.',
           'search',
           '{
               "type": "object",
               "description": "Saved search",
               "properties": {
                   "id": {
                       "type": "string",
                       "description": "Saved search ID"
                   },
                   "name": {
                       "type": "string",
                       "description": "Search name"
                   },
                   "query": {
                       "type": ["string", "null"],
                       "description": "Search query"
                   },
                   "filters": {
                       "type": ["array", "object", "null"],
                       "description": "Filter conditions"
                   },
                   "sort": {
                       "type": ["array", "object", "null"],
                       "description": "Sort specification"
                   },
                   "createdAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When created"
                   },
                   "updatedAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When last updated"
                   },
                   "isDefault": {
                       "type": "boolean",
                       "description": "Whether this is the default search",
                       "default": false
                   },
                   "isPublic": {
                       "type": "boolean",
                       "description": "Whether search is shared",
                       "default": false
                   }
               },
               "required": ["id", "name"],
               "examples": [
                   {
                       "id": "search-001",
                       "name": "Active Premium Users",
                       "query": null,
                       "filters": [
                           {"field": "status", "operator": "eq", "value": "active"},
                           {"field": "plan", "operator": "eq", "value": "premium"}
                       ],
                       "sort": [{"field": "createdAt", "direction": "desc"}],
                       "createdAt": "2024-01-15T10:00:00Z",
                       "updatedAt": "2024-01-15T10:00:00Z",
                       "isDefault": false,
                       "isPublic": true
                   }
               ]
           }',
           ARRAY['saved', 'search', 'config', 'persistent'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchHistoryItem',
           'Search history entry.',
           'search',
           '{
               "type": "object",
               "description": "Search history entry",
               "properties": {
                   "query": {
                       "type": "string",
                       "description": "Search query"
                   },
                   "timestamp": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When search was performed"
                   },
                   "resultCount": {
                       "type": ["integer", "null"],
                       "description": "Number of results",
                       "minimum": 0
                   },
                   "filters": {
                       "type": ["object", "null"],
                       "description": "Filters applied"
                   },
                   "selected": {
                       "type": ["string", "null"],
                       "description": "ID of selected result"
                   }
               },
               "required": ["query", "timestamp"],
               "examples": [
                   {
                       "query": "machine learning python",
                       "timestamp": "2024-01-15T14:30:00Z",
                       "resultCount": 150,
                       "filters": {"category": "tutorials"},
                       "selected": "doc-123"
                   }
               ]
           }',
           ARRAY['search', 'history', 'entry', 'tracking'],
           true,
           true
       );

-- =============================================================================
-- ELASTICSEARCH/OPENSEARCH SPECIFIC FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'elasticsearchQuery',
           'Elasticsearch Query DSL structure.',
           'search',
           '{
               "type": "object",
               "description": "Elasticsearch Query DSL",
               "properties": {
                   "query": {
                       "type": "object",
                       "description": "Query clause"
                   },
                   "from": {
                       "type": "integer",
                       "description": "Starting offset",
                       "minimum": 0,
                       "default": 0
                   },
                   "size": {
                       "type": "integer",
                       "description": "Number of results",
                       "minimum": 0,
                       "default": 10
                   },
                   "sort": {
                       "type": "array",
                       "description": "Sort clauses",
                       "items": {}
                   },
                   "aggs": {
                       "type": ["object", "null"],
                       "description": "Aggregations"
                   },
                   "highlight": {
                       "type": ["object", "null"],
                       "description": "Highlighting configuration"
                   },
                   "_source": {
                       "description": "Source filtering"
                   }
               },
               "examples": [
                   {
                       "query": {
                           "bool": {
                               "must": [{"match": {"title": "machine learning"}}],
                               "filter": [{"term": {"status": "published"}}]
                           }
                       },
                       "from": 0,
                       "size": 20,
                       "sort": [{"createdAt": "desc"}],
                       "aggs": {"categories": {"terms": {"field": "category"}}},
                       "highlight": {"fields": {"title": {}, "description": {}}},
                       "_source": ["id", "title", "description"]
                   }
               ]
           }',
           ARRAY['elasticsearch', 'query', 'dsl', 'advanced'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchAfter',
           'Search after values for deep pagination.',
           'search',
           '{
               "type": "array",
               "description": "Search after sort values for deep pagination",
               "items": {},
               "examples": [
                   [1705315800000, "doc-123"],
                   ["Smith", "John", "user-456"]
               ]
           }',
           ARRAY['search', 'after', 'deep-pagination', 'elasticsearch'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'scrollId',
           'Scroll ID for scrolling through large result sets.',
           'search',
           '{
               "type": "string",
               "description": "Scroll ID for paginating large results",
               "examples": ["DXF1ZXJ5QW5kRmV0Y2gBAAAAAAAAAD4WYm9laVYtZndUQlNsdDcwakFMNjU1QQ=="]
           }',
           ARRAY['scroll', 'id', 'pagination', 'elasticsearch'],
           true,
           true
       );

-- =============================================================================
-- SEARCH ANALYTICS FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchAnalytics',
           'Analytics data for search operations.',
           'search',
           '{
               "type": "object",
               "description": "Search analytics",
               "properties": {
                   "query": {
                       "type": "string",
                       "description": "Search query"
                   },
                   "searchCount": {
                       "type": "integer",
                       "description": "Number of times searched",
                       "minimum": 0
                   },
                   "clickCount": {
                       "type": "integer",
                       "description": "Number of result clicks",
                       "minimum": 0
                   },
                   "clickThroughRate": {
                       "type": "number",
                       "description": "Click-through rate",
                       "minimum": 0,
                       "maximum": 1
                   },
                   "avgResultsReturned": {
                       "type": "number",
                       "description": "Average results per search",
                       "minimum": 0
                   },
                   "avgPosition": {
                       "type": ["number", "null"],
                       "description": "Average clicked position"
                   },
                   "noResultsRate": {
                       "type": "number",
                       "description": "Rate of zero-result searches",
                       "minimum": 0,
                       "maximum": 1
                   }
               },
               "required": ["query", "searchCount"],
               "examples": [
                   {
                       "query": "machine learning",
                       "searchCount": 1500,
                       "clickCount": 450,
                       "clickThroughRate": 0.30,
                       "avgResultsReturned": 125.5,
                       "avgPosition": 2.3,
                       "noResultsRate": 0.02
                   }
               ]
           }',
           ARRAY['search', 'analytics', 'metrics', 'tracking'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'searchPerformance',
           'Performance metrics for search operations.',
           'search',
           '{
               "type": "object",
               "description": "Search performance metrics",
               "properties": {
                   "queryTime": {
                       "type": "integer",
                       "description": "Query execution time in ms",
                       "minimum": 0
                   },
                   "fetchTime": {
                       "type": ["integer", "null"],
                       "description": "Result fetch time in ms",
                       "minimum": 0
                   },
                   "totalTime": {
                       "type": "integer",
                       "description": "Total request time in ms",
                       "minimum": 0
                   },
                   "indexesSearched": {
                       "type": ["integer", "null"],
                       "description": "Number of indexes searched"
                   },
                   "shardsQueried": {
                       "type": ["integer", "null"],
                       "description": "Number of shards queried"
                   },
                   "cacheHit": {
                       "type": ["boolean", "null"],
                       "description": "Whether cache was used"
                   }
               },
               "required": ["totalTime"],
               "examples": [
                   {
                       "queryTime": 35,
                       "fetchTime": 10,
                       "totalTime": 45,
                       "indexesSearched": 1,
                       "shardsQueried": 5,
                       "cacheHit": false
                   }
               ]
           }',
           ARRAY['search', 'performance', 'timing', 'metrics'],
           true,
           true
       );