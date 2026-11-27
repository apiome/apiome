-- Rename a pacticipant, and give it a display name — PFX-8.10 (#7307).
--
-- A pacticipant's `name` is the name pacts use (`"consumer": {"name": "Orders UI"}`), and its
-- `slug` (the handle, V432) is derived from the first one. Until now the name could only be set by
-- the first publish. PFX-8.10 lets a person rename it from the pacticipant's Settings tab, and the
-- rule is that **renaming keeps history and old names keep resolving**:
--
--   * The handle never changes, so every URL, CI job and stored reference stays valid.
--   * Each name the pacticipant is renamed *to*, and the name it had before, is kept in
--     `pacticipant_alias` with the handle the name reduces to (`Orders Web` → `orders-web`). apiome-rest resolves a reference by the handle first and by
--     an alias second, so a pact published under any name the pacticipant has had lands on it, and
--     nothing new is registered by accident.
--   * `display_name` is new and optional: what people read (`Orders UI (web)`), never what pacts
--     use. The Pact Broker document's `displayName` reads it, falling back to `name`.
--
-- An alias belongs to its pacticipant: it is removed with the row (a purge) and hidden with it
-- while it is soft-deleted (apiome-rest joins the live pacticipant). That is also why the handle is
-- not unique across aliases here: the soft-delete state lives on the parent, so apiome-rest checks
-- in the rename's transaction that no other live pacticipant has the handle or the alias.
--
-- Online: one nullable column without a default (catalog-only change) and a new, empty table.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.pacticipant_alias;
--   ALTER TABLE apiome.pacticipant DROP COLUMN IF EXISTS display_name;

SET search_path TO apiome, public;

ALTER TABLE pacticipant
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)
        CONSTRAINT pacticipant_display_name_not_blank_check
            CHECK (display_name IS NULL OR btrim(display_name) <> '');

CREATE TABLE IF NOT EXISTS pacticipant_alias (
    pacticipant_id UUID NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The handle the name reduces to; the same shape as pacticipant.slug (V432).
    slug VARCHAR(128) NOT NULL
        CONSTRAINT pacticipant_alias_slug_shape_check
            CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
    -- The name as it was written.
    name VARCHAR(255) NOT NULL
        CONSTRAINT pacticipant_alias_name_not_blank_check CHECK (btrim(name) <> ''),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Led by the pacticipant's composite key, so it also serves that foreign key's check.
    CONSTRAINT pacticipant_alias_pkey PRIMARY KEY (pacticipant_id, tenant_id, slug),
    CONSTRAINT pacticipant_alias_pacticipant_fk
        FOREIGN KEY (pacticipant_id, tenant_id)
        REFERENCES pacticipant (id, tenant_id) ON DELETE CASCADE
);

-- "Which pacticipant has this old name" — every resolution that misses the handle — and the
-- workspace FK check.
CREATE INDEX IF NOT EXISTS idx_pacticipant_alias_tenant_slug
    ON pacticipant_alias (tenant_id, slug);
CREATE INDEX IF NOT EXISTS idx_pacticipant_alias_created_by
    ON pacticipant_alias (created_by)
    WHERE created_by IS NOT NULL;

COMMENT ON COLUMN pacticipant.display_name IS
    'What people read (PFX-8.10, #7307); optional, never what pacts use. NULL reads as name';
COMMENT ON TABLE pacticipant_alias IS
    'Names a pacticipant has had, by the handle each reduces to; old names keep resolving (PFX-8.10, #7307)';
COMMENT ON COLUMN pacticipant_alias.slug IS
    'The handle the old or new name reduces to; resolved after pacticipant.slug';
