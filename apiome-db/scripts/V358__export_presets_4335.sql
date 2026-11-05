-- Export presets — MFX-39.3 (#4335).
--
-- An export is a target list, each target's emit options (MFX-1.4) and, since MFX-38.4, where the
-- result is delivered. Teams re-enter the same combination for every nightly sync or release; a
-- preset saves it once per workspace, by name, so the UI, the CLI (`apiome export --preset
-- nightly-sync`) and the REST job submit (`"preset": "nightly-sync"`) can apply it.
--
--   `export_presets` — one row per preset: a unique name, a description, `targets` — the ordered
--   `[{target, options}]` list, each target's options already validated against its emitter's
--   schema when stored — and an optional delivery profile the export is delivered with on completion.
--
-- Three rules shape it:
--
--   * **Tenant-scoped.** A preset belongs to one tenant and is named uniquely within it.
--   * **Never a secret.** Options are emit options; the delivery credential stays behind its profile
--     (V357), referenced `ON DELETE SET NULL` — deleting the profile leaves a preset without delivery.
--   * **Validated, not trusted.** The application re-validates every target's options when a preset is
--     applied, so an emitter whose option schema changed refuses the stale preset instead of guessing.
--
-- **No new RBAC resource.** Managing a preset is `projects:edit` (reading: `projects:view`), as a
-- delivery profile is; applying one is whatever the export it starts needs.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.export_presets;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS export_presets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name VARCHAR(120) NOT NULL,
    description TEXT,

    -- The ordered [{target, options}] list; one entry is a single-target export.
    targets JSONB NOT NULL
        CONSTRAINT export_presets_targets_check
            CHECK (jsonb_typeof(targets) = 'array' AND jsonb_array_length(targets) BETWEEN 1 AND 16),

    delivery_profile_id UUID REFERENCES export_delivery_profiles(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,

    CONSTRAINT export_presets_name_unique UNIQUE (tenant_id, name)
);

COMMENT ON TABLE export_presets IS
    'MFX-39.3 (#4335): a tenant''s saved export combinations — an ordered target list with each '
    'target''s validated emit options, and an optional delivery profile (MFX-38.4).';
