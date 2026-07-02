-- Migration rule templates: pre-defined rules for data extraction/transformation.
-- Used by the migration UI to suggest rule types (split, concat, URL lookup, etc.).

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS migration_rule_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(64) NOT NULL DEFAULT 'General',
    rule_type VARCHAR(32) NOT NULL CHECK (rule_type IN ('simple', 'script', 'sparkSql')),
    rule_content TEXT NOT NULL,
    min_inputs INT NOT NULL DEFAULT 1 CHECK (min_inputs >= 1),
    min_outputs INT NOT NULL DEFAULT 1 CHECK (min_outputs >= 1),
    input_labels JSONB,
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE migration_rule_templates IS 'Pre-defined migration rule templates (split, concat, URL lookup, etc.) for extraction/transformation';
COMMENT ON COLUMN migration_rule_templates.name IS 'Display name of the template';
COMMENT ON COLUMN migration_rule_templates.description IS 'Short description of what the rule does';
COMMENT ON COLUMN migration_rule_templates.category IS 'Category for grouping (e.g. String, Lookup, Combine)';
COMMENT ON COLUMN migration_rule_templates.rule_type IS 'simple, script, or sparkSql';
COMMENT ON COLUMN migration_rule_templates.rule_content IS 'Template expression/script; use "value" for single input, "a"/"b" for multiple';
COMMENT ON COLUMN migration_rule_templates.min_inputs IS 'Minimum number of source properties required';
COMMENT ON COLUMN migration_rule_templates.min_outputs IS 'Minimum number of destination properties required';
COMMENT ON COLUMN migration_rule_templates.input_labels IS 'Optional array of suggested input names, e.g. ["value", "separator"]';
COMMENT ON COLUMN migration_rule_templates.sort_order IS 'Display order in the template list';

CREATE UNIQUE INDEX IF NOT EXISTS idx_migration_rule_templates_name ON migration_rule_templates(name);
CREATE INDEX IF NOT EXISTS idx_migration_rule_templates_category ON migration_rule_templates(category);
CREATE INDEX IF NOT EXISTS idx_migration_rule_templates_sort_order ON migration_rule_templates(sort_order);

-- Seed built-in templates (upsert by name so re-run is safe)
INSERT INTO migration_rule_templates (name, description, category, rule_type, rule_content, min_inputs, min_outputs, input_labels, sort_order)
VALUES
    ('Pass through', 'Copy value as-is; normalize null/empty to empty string.', 'General', 'simple', 'value == null || value === "" ? "" : String(value)', 1, 1, '["value"]', 0),
    ('Split string', 'Split one value into two outputs by a delimiter (edit "-" in the expression to change).', 'String', 'simple', '[value.split("-")[0] || "", value.split("-")[1] || ""]', 1, 2, '["value"]', 10),
    ('Concatenate', 'Join two or more inputs into one output with a separator (edit " " in the expression).', 'String', 'simple', '[a, b].filter(Boolean).join(" ")', 2, 1, '["a", "b"]', 20),
    ('Default value', 'Use a default when input is null or empty (edit "default" in the expression).', 'General', 'simple', 'value == null || value === "" ? "default" : String(value)', 1, 1, '["value"]', 30),
    ('Trim whitespace', 'Trim leading and trailing whitespace from the input.', 'String', 'simple', '(value || "").trim()', 1, 1, '["value"]', 40),
    ('Extract from JSON', 'Parse JSON input and extract a path (edit the path in the script).', 'Transform', 'script', 'try { const o = JSON.parse(value); return o.path ?? ""; } catch { return ""; }', 1, 1, '["value"]', 50),
    ('URL lookup (script)', 'Call a URL with input as parameter and return a field from the response. Edit URL and response path; runs server-side in Spark.', 'Lookup', 'script', 'const url = `https://example.com/lookup/${value}`;\nconst res = await fetch(url);\nconst data = await res.json();\nreturn data.result ?? "";', 1, 1, '["value"]', 60),
    ('Combine first and last name', 'Join first and last name properties into a single full name.', 'String', 'simple', '[a, b].filter(Boolean).join(" ")', 2, 1, '["first", "last"]', 70),
    ('Format as JSON', 'Serialize the input value as a JSON string.', 'Transform', 'simple', 'JSON.stringify(value)', 1, 1, '["value"]', 80),
    ('Lowercase', 'Convert string to lowercase.', 'String', 'simple', '(value || "").toLowerCase()', 1, 1, '["value"]', 90),
    ('Uppercase', 'Convert string to uppercase.', 'String', 'simple', '(value || "").toUpperCase()', 1, 1, '["value"]', 100)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    rule_type = EXCLUDED.rule_type,
    rule_content = EXCLUDED.rule_content,
    min_inputs = EXCLUDED.min_inputs,
    min_outputs = EXCLUDED.min_outputs,
    input_labels = EXCLUDED.input_labels,
    sort_order = EXCLUDED.sort_order,
    updated_at = CURRENT_TIMESTAMP;
