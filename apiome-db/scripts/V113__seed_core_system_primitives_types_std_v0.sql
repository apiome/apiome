-- Seed core system primitives & types (std/v0) — #3449, ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §6 Issue 1.4.
--
-- The earlier 20260124-140000.sql seeded 36 ISO-aligned system primitives as FLAT JSON Schemas
-- with no namespace and no $ref graph. This migration seeds the registry-shaped baseline the
-- type registry actually addresses: the `std/v0` namespaces, with the JSON Schema 2020-12
-- registry columns (namespace / base_uri / schema_id / draft / source / refs) the #3447 migration
-- added populated, and composite types carrying RELATIVE $ref chains recorded in `refs`.
--
-- Two system namespaces are seeded as is_system / is_public rows, visible to every tenant:
--
--   std/v0/primitives  — the seven JSON Schema base types (string, number, integer, boolean,
--                        null, array, object). No $ref edges (refs = []).
--   std/v0/types       — derived & composite types that reference the primitives by relative
--                        $ref: date / date-time / time / uuid / email / uri (string + format),
--                        decimal (number), currency-code (string + ISO-4217 pattern), and money
--                        (object { amount: ./decimal, currency: ./currency-code }).
--
-- Relative $ref resolution model (verified against docs/planning/mockups/.../type-resolver.html):
--   resolution base = each type's base_uri (its namespace rooted at https://api.apiome.app/types/)
--   $ref            = ../primitives/string   (source: std/v0/types/date, base .../std/v0/types/)
--   resolved        = https://api.apiome.app/types/std/v0/primitives/string         ✓
-- Each edge is stored in `refs` as {relative_ref, resolved_target, status}, where resolved_target
-- is the namespace-path form (e.g. std/v0/primitives/string) the resolver surfaces.
--
-- Seeding is idempotent: rows are inserted per tenant (matching the 20260124 system-primitive
-- convention) and guarded by ON CONFLICT (tenant_id, category, name) DO NOTHING, so re-running the
-- migration — or applying it to a database that already has the rows — is a no-op. The leaf names
-- (string, date, money, …) do not collide with the existing flat ISO primitives, whose names are
-- display-cased (e.g. 'Email Address', 'UUID', 'Date (ISO 8601)').
--
-- NOTE: std/v0/primitives/string already serves plain strings, so no redundant std/v0/types/string
-- alias is seeded — it would collide with the primitive on the legacy (tenant_id, category, name)
-- uniqueness key, and no seeded type references it (the seed graph resolves with 0 unresolved refs).

SET search_path TO apiome, public;

-- All std/v0 rows for one tenant, cross-joined onto every live tenant below.
-- Columns: leaf name, description, JSON Schema base category, namespace, schema document, $ref edges.
WITH seed (name, description, category, namespace, schema, refs) AS (
    VALUES
        -- ── std/v0/primitives — the seven JSON Schema base types (no $ref edges) ──────────────
        ('string', 'JSON Schema base string type.', 'string', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/string","title":"String","type":"string"}',
         '[]'),
        ('number', 'JSON Schema base number type (integer or floating-point).', 'number', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/number","title":"Number","type":"number"}',
         '[]'),
        ('integer', 'JSON Schema base integer type.', 'integer', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/integer","title":"Integer","type":"integer"}',
         '[]'),
        ('boolean', 'JSON Schema base boolean type.', 'boolean', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/boolean","title":"Boolean","type":"boolean"}',
         '[]'),
        ('null', 'JSON Schema base null type.', 'null', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/null","title":"Null","type":"null"}',
         '[]'),
        ('array', 'JSON Schema base array type.', 'array', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/array","title":"Array","type":"array"}',
         '[]'),
        ('object', 'JSON Schema base object type.', 'object', 'std/v0/primitives',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/primitives/object","title":"Object","type":"object"}',
         '[]'),

        -- ── std/v0/types — derived & composite types (relative $ref chains) ───────────────────
        ('date', 'Calendar date (ISO 8601, YYYY-MM-DD): the string primitive with format date.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/date","title":"Date","$ref":"../primitives/string","format":"date"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('date-time', 'Timestamp (ISO 8601 with timezone): the string primitive with format date-time.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/date-time","title":"Date-Time","$ref":"../primitives/string","format":"date-time"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('time', 'Time of day (ISO 8601, HH:mm:ss): the string primitive with format time.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/time","title":"Time","$ref":"../primitives/string","format":"time"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('uuid', 'UUID (RFC 4122): the string primitive with format uuid.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/uuid","title":"UUID","$ref":"../primitives/string","format":"uuid"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('email', 'Email address (RFC 5322): the string primitive with format email.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/email","title":"Email","$ref":"../primitives/string","format":"email"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('uri', 'URI (RFC 3986): the string primitive with format uri.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/uri","title":"URI","$ref":"../primitives/string","format":"uri"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('decimal', 'Arbitrary-precision decimal: the number primitive.', 'number', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/decimal","title":"Decimal","$ref":"../primitives/number"}',
         '[{"relative_ref":"../primitives/number","resolved_target":"std/v0/primitives/number","status":"resolved"}]'),
        ('currency-code', 'ISO 4217 three-letter currency code: the string primitive with an uppercase pattern.', 'string', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/currency-code","title":"Currency Code","$ref":"../primitives/string","pattern":"^[A-Z]{3}$"}',
         '[{"relative_ref":"../primitives/string","resolved_target":"std/v0/primitives/string","status":"resolved"}]'),
        ('money', 'Monetary amount: an object pairing a decimal amount with an ISO 4217 currency code.', 'object', 'std/v0/types',
         '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://api.apiome.app/types/std/v0/types/money","title":"Money","type":"object","properties":{"amount":{"$ref":"./decimal"},"currency":{"$ref":"./currency-code"}},"required":["amount","currency"],"additionalProperties":false}',
         '[{"relative_ref":"./decimal","resolved_target":"std/v0/types/decimal","status":"resolved"},{"relative_ref":"./currency-code","resolved_target":"std/v0/types/currency-code","status":"resolved"}]')
)
INSERT INTO primitives (
    tenant_id, name, description, category, schema, tags,
    namespace, base_uri, schema_id, draft, source, refs,
    is_system, is_public
)
SELECT
    t.id,
    s.name,
    s.description,
    s.category,
    s.schema::jsonb,
    -- Discoverability tags: the std layer + the namespace leaf (primitives | types).
    ARRAY['std', 'std/v0', split_part(s.namespace, '/', 3)]::text[],
    s.namespace,
    -- base_uri: the namespace rooted at the registry's resolution base, trailing slash.
    'https://api.apiome.app/types/' || s.namespace || '/',
    -- schema_id ($id): base_uri + leaf name.
    'https://api.apiome.app/types/' || s.namespace || '/' || s.name,
    '2020-12',
    'human',
    s.refs::jsonb,
    true,
    true
FROM tenants t
CROSS JOIN seed s
WHERE t.deleted_at IS NULL
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion.
DO $$
BEGIN
    RAISE NOTICE 'std/v0 core system primitives & types seeded (7 primitives + 9 types per tenant).';
END $$;
