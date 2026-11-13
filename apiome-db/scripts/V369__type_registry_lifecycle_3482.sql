-- Type-registry lifecycle: version-root status and type deprecation — #3482,
-- ROADMAP_TYPE_REGISTRY_GOVERNANCE.md §12 Issue 7.5.
--
-- Problem: type collections evolve and old types must be retired. A namespace recorded only the
-- name of its version root (`v0`, `v1`), not whether that root is the stable one or a draft still
-- being worked on, and a type had no way to say "do not start using me".
--
-- Solution: two additive changes to the existing registry tables (same database, `apiome` schema).
--
--   1. `apiome.type_namespaces.root_status` — `stable` (the default, and what every existing row
--      becomes) or `draft`. A draft root is one whose types may still change shape; the API and
--      the Namespaces screen list and filter the two apart.
--
--   2. `apiome.primitives` gains the deprecation record: when it was deprecated, the optional
--      sunset date, an optional message and an optional replacement type. Deprecation is an
--      advisory marker — existing and new bindings and `$ref`s keep working — so nothing else in
--      the schema refers to these columns.
--
-- Idempotent: safe to re-run.

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------
-- 1. Version-root status
-- ---------------------------------------------------------------------------------------------

ALTER TABLE apiome.type_namespaces
    ADD COLUMN IF NOT EXISTS root_status TEXT NOT NULL DEFAULT 'stable';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'type_namespaces_root_status_ck'
          AND conrelid = 'apiome.type_namespaces'::regclass
    ) THEN
        ALTER TABLE apiome.type_namespaces
            ADD CONSTRAINT type_namespaces_root_status_ck
            CHECK (root_status IN ('stable', 'draft'));
    END IF;
END $$;

COMMENT ON COLUMN apiome.type_namespaces.root_status IS
    'Lifecycle of the namespace''s version root (#3482): stable (default) or draft. '
    'System-core namespaces are always stable.';

-- ---------------------------------------------------------------------------------------------
-- 2. Type deprecation
-- ---------------------------------------------------------------------------------------------

ALTER TABLE apiome.primitives
    ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sunset_date DATE,
    ADD COLUMN IF NOT EXISTS deprecation_message TEXT,
    ADD COLUMN IF NOT EXISTS replacement_id UUID
        REFERENCES apiome.primitives(id) ON DELETE SET NULL;

DO $$
BEGIN
    -- The sunset date, message and replacement only mean something on a deprecated type.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'primitives_deprecation_details_ck'
          AND conrelid = 'apiome.primitives'::regclass
    ) THEN
        ALTER TABLE apiome.primitives
            ADD CONSTRAINT primitives_deprecation_details_ck
            CHECK (
                deprecated_at IS NOT NULL
                OR (sunset_date IS NULL AND deprecation_message IS NULL AND replacement_id IS NULL)
            );
    END IF;

    -- A type cannot name itself as its own replacement.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'primitives_replacement_not_self_ck'
          AND conrelid = 'apiome.primitives'::regclass
    ) THEN
        ALTER TABLE apiome.primitives
            ADD CONSTRAINT primitives_replacement_not_self_ck
            CHECK (replacement_id IS NULL OR replacement_id <> id);
    END IF;
END $$;

COMMENT ON COLUMN apiome.primitives.deprecated_at IS
    'When the type was deprecated (#3482); NULL while it is active. Advisory: bindings and $refs keep working.';
COMMENT ON COLUMN apiome.primitives.sunset_date IS
    'Optional date after which the type should no longer be used (#3482). Only set on a deprecated type.';
COMMENT ON COLUMN apiome.primitives.deprecation_message IS
    'Optional note shown with the deprecation — why, and what to do instead (#3482).';
COMMENT ON COLUMN apiome.primitives.replacement_id IS
    'Optional type to use instead (#3482). Cleared when that type is deleted.';

-- Listing the deprecated types of a tenant (and their sunset dates) without scanning every type.
CREATE INDEX IF NOT EXISTS idx_primitives_deprecated
    ON apiome.primitives (tenant_id, sunset_date)
    WHERE deprecated_at IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE 'Type-registry lifecycle columns added: type_namespaces.root_status, primitives deprecation record (#3482).';
END $$;
