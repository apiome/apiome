-- Ownership on catalog entities — CDG-2.2 (#5961).
--
-- Nothing in the catalog said who is responsible for an item, so findings went to whoever was
-- looking. This migration records an owner team per entity, and the *suggestions* importers make.
--
--   entity_owners — one row per (entity, team, source). An entity is a project, a catalog item, an
--                   MCP endpoint, a consumer or a connector; its owner is a CDG-2.1 team.
--
-- Rules the database keeps:
--
--   1. **One confirmed owner per entity, any number of suggestions.** A partial unique index allows
--      a single `confirmed` row per entity; suggestions are unique per (entity, team, source) so a
--      re-import refreshes rather than duplicates them.
--
--   2. **Nothing is inferred silently.** Importers (gateway tags, CODEOWNERS, `x-apiome-owner`,
--      `info.contact`) only ever write `suggested` rows, each with its `source` and `source_ref`.
--      Routing (CDG-2.3) reads `confirmed` rows only. Confirming records who and when.
--
--   3. **A deleted team owns nothing.** Rows cascade with a hard-deleted team; reads also ignore
--      rows of soft-deleted teams (CDG-2.1 `teams.deleted_at`).
--
--   4. **CODEOWNERS suggestions follow the link.** `repository_file_scan` stores the CODEOWNERS
--      owners that match each scanned file in `tenant_repository_files.codeowners`. Whenever a
--      path is linked to a project (`repository_import_spec`, written by both apiome-ui and
--      apiome-rest) or a linked file's owners change, a trigger refreshes that project's
--      `codeowners` suggestions. An owner `@org/<team-slug>` suggests the team with that slug;
--      user and e-mail owners suggest nothing.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TRIGGER IF EXISTS trg_repository_import_spec_codeowners ON apiome.repository_import_spec;
--   DROP TRIGGER IF EXISTS trg_tenant_repository_files_codeowners ON apiome.tenant_repository_files;
--   DROP FUNCTION IF EXISTS apiome.repository_import_spec_codeowners_trigger();
--   DROP FUNCTION IF EXISTS apiome.tenant_repository_files_codeowners_trigger();
--   DROP FUNCTION IF EXISTS apiome.refresh_codeowner_suggestions(UUID, TEXT, TEXT, UUID);
--   ALTER TABLE apiome.tenant_repository_files DROP COLUMN IF EXISTS codeowners;
--   DROP TABLE IF EXISTS apiome.entity_owners;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- entity_owners
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_owners (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    entity_kind VARCHAR(32) NOT NULL
        CONSTRAINT entity_owners_kind_check
            CHECK (entity_kind IN ('project', 'catalog_item', 'mcp_endpoint', 'consumer', 'connector')),
    -- No foreign key: the id points into a different table per kind. Reads join the entity.
    entity_id UUID NOT NULL,

    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,

    status VARCHAR(16) NOT NULL
        CONSTRAINT entity_owners_status_check CHECK (status IN ('confirmed', 'suggested')),
    source VARCHAR(32) NOT NULL
        CONSTRAINT entity_owners_source_check
            CHECK (source IN ('manual', 'gateway_tag', 'codeowners', 'spec_extension',
                              'backstage', 'compass', 'hub')),
    -- Where the suggestion came from, verbatim: the tag, the CODEOWNERS owner, the extension key.
    source_ref TEXT,

    confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A confirmed row says when it was confirmed; a suggestion has not been.
    CONSTRAINT entity_owners_confirmed_stamp_check
        CHECK ((status = 'confirmed') = (confirmed_at IS NOT NULL))
);

-- Rule 1: one confirmed owner per entity.
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_owners_one_confirmed
    ON entity_owners (tenant_id, entity_kind, entity_id)
    WHERE status = 'confirmed';

-- Rule 1: one suggestion per (entity, team, source).
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_owners_suggestion
    ON entity_owners (tenant_id, entity_kind, entity_id, team_id, source)
    WHERE status = 'suggested';

-- The envelope read: every list joins on (entity_id) with the kind.
CREATE INDEX IF NOT EXISTS idx_entity_owners_entity
    ON entity_owners (entity_id, entity_kind);

-- "What does this team own" — team deletes (CDG-2.1) and owner routing (CDG-2.3).
CREATE INDEX IF NOT EXISTS idx_entity_owners_team
    ON entity_owners (team_id, status);

COMMENT ON TABLE entity_owners IS
    'Owner team of a catalog entity: one confirmed owner plus any number of suggestions (CDG-2.2, #5961)';
COMMENT ON COLUMN entity_owners.entity_kind IS 'project | catalog_item | mcp_endpoint | consumer | connector';
COMMENT ON COLUMN entity_owners.status IS 'confirmed (routes findings) | suggested (shown with its source; never routes)';
COMMENT ON COLUMN entity_owners.source IS 'manual | gateway_tag | codeowners | spec_extension | backstage | compass | hub';
COMMENT ON COLUMN entity_owners.source_ref IS 'Where a suggestion came from, verbatim (tag, CODEOWNERS owner, extension key)';

-- ---------------------------------------------------------------------------------------------------
-- CODEOWNERS
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE tenant_repository_files
    ADD COLUMN IF NOT EXISTS codeowners TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

COMMENT ON COLUMN tenant_repository_files.codeowners IS
    'Owners the branch CODEOWNERS file assigns to this path (last matching rule), as written: @org/team, @user, email (CDG-2.2)';

-- Refresh one project's codeowners suggestions from the file its spec path points at.
CREATE OR REPLACE FUNCTION apiome.refresh_codeowner_suggestions(
    p_repository_id UUID, p_branch TEXT, p_path TEXT, p_project_id UUID
)
RETURNS void AS $$
DECLARE
    v_tenant UUID;
    v_kind TEXT;
    v_refs TEXT[];
BEGIN
    SELECT p.tenant_id, CASE WHEN p.publishable THEN 'project' ELSE 'catalog_item' END
      INTO v_tenant, v_kind
      FROM apiome.projects p
     WHERE p.id = p_project_id;
    IF v_tenant IS NULL THEN
        RETURN;
    END IF;

    SELECT f.codeowners INTO v_refs
      FROM apiome.tenant_repository_files f
     WHERE f.repository_id = p_repository_id AND f.branch = p_branch AND f.path = p_path;
    v_refs := COALESCE(v_refs, ARRAY[]::TEXT[]);

    -- Drop suggestions the file no longer makes.
    DELETE FROM apiome.entity_owners eo
     WHERE eo.tenant_id = v_tenant
       AND eo.entity_id = p_project_id
       AND eo.status = 'suggested'
       AND eo.source = 'codeowners'
       AND NOT (eo.source_ref = ANY (v_refs));

    -- Suggest every live team an `@org/<slug>` owner names.
    INSERT INTO apiome.entity_owners (tenant_id, entity_kind, entity_id, team_id, status, source, source_ref)
    SELECT v_tenant, v_kind, p_project_id, t.id, 'suggested', 'codeowners', ref
      FROM unnest(v_refs) AS ref
      JOIN apiome.teams t
        ON t.tenant_id = v_tenant
       AND t.deleted_at IS NULL
       AND t.slug = lower(substring(ref FROM '^@[^/]+/(.+)$'))
    ON CONFLICT (tenant_id, entity_kind, entity_id, team_id, source) WHERE status = 'suggested'
    DO UPDATE SET source_ref = EXCLUDED.source_ref, updated_at = CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION apiome.repository_import_spec_codeowners_trigger()
RETURNS trigger AS $$
BEGIN
    PERFORM apiome.refresh_codeowner_suggestions(NEW.repository_id, NEW.branch, NEW.path, NEW.project_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_repository_import_spec_codeowners ON repository_import_spec;
CREATE TRIGGER trg_repository_import_spec_codeowners
    AFTER INSERT OR UPDATE OF repository_id, branch, path, project_id ON repository_import_spec
    FOR EACH ROW EXECUTE FUNCTION apiome.repository_import_spec_codeowners_trigger();

CREATE OR REPLACE FUNCTION apiome.tenant_repository_files_codeowners_trigger()
RETURNS trigger AS $$
DECLARE
    s RECORD;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.codeowners IS NOT DISTINCT FROM OLD.codeowners THEN
        RETURN NEW;
    END IF;
    FOR s IN
        SELECT spec.project_id FROM apiome.repository_import_spec spec
         WHERE spec.repository_id = NEW.repository_id AND spec.branch = NEW.branch AND spec.path = NEW.path
    LOOP
        PERFORM apiome.refresh_codeowner_suggestions(NEW.repository_id, NEW.branch, NEW.path, s.project_id);
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tenant_repository_files_codeowners ON tenant_repository_files;
CREATE TRIGGER trg_tenant_repository_files_codeowners
    AFTER INSERT OR UPDATE OF codeowners ON tenant_repository_files
    FOR EACH ROW EXECUTE FUNCTION apiome.tenant_repository_files_codeowners_trigger();
