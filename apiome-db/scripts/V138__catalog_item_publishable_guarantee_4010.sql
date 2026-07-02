-- Catalog item entity & non-publishable guarantee (#4010, MFI-23.1).
--
-- MFI-EPIC-23 introduces a **Catalog** screen for imports that are *OpenAPI-worthy but not OpenAPI*
-- (gRPC, GraphQL, AsyncAPI, OData, WSDL, …). Such an import must not silently become a publishable
-- Project, because it may be incomplete: it lands as a *catalog item* instead, where it can be
-- viewed/linted/inspected exactly like a project but is **never a publish candidate**. The only path
-- out of the catalog to a publishable artifact is the MFI-EPIC-22 convert-to-OpenAPI flow, which
-- mints a *new* publishable Project — it never flips an existing catalog item.
--
-- A catalog item is modelled as a **projection over the existing `projects` + `versions` tables**
-- (no new versioning mechanism, per the ticket): the version already carries `source_format` /
-- `protocol` (V136, MFI-7.1), `format_metadata` / `source_tool_versions` (V137/V136), and
-- `quality_score` / `quality_grade` (V124). The one thing missing is the hard Project-vs-Catalog
-- boundary, which this migration adds at the data layer (not just in the UI):
--
--   * a single `publishable` flag on `projects` — `true` for OpenAPI/Swagger Projects (the existing
--     behaviour, hence the `DEFAULT true` so every pre-existing project is unaffected), `false` for
--     catalog items; and
--   * a write-once guarantee: once a project's `publishable` flag is set it can never change, so a
--     catalog item (`publishable = false`) can never be promoted into a publishable Project by a
--     stray UPDATE — the "no publish" rule is enforced in the database, not hidden in the UI.
--
-- Catalog items are listed exactly like projects (tenant-scoped, soft-deleted) and are simply the
-- `publishable = false` slice of `projects`; a partial composite index backs both list surfaces.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TRIGGER IF EXISTS trigger_projects_publishable_immutable ON apiome.projects;
--   DROP FUNCTION IF EXISTS apiome.projects_forbid_publishable_change();
--   DROP INDEX IF EXISTS apiome.idx_projects_tenant_publishable;
--   ALTER TABLE apiome.projects DROP COLUMN IF EXISTS publishable;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- The Project-vs-Catalog boundary: `publishable`.
-- ---------------------------------------------------------------------------------------------------
-- DEFAULT true keeps every existing project (and every future OpenAPI/Swagger import) publishable
-- exactly as before; non-OpenAPI imports (MFI-23.7) insert the row with `publishable = false`.
ALTER TABLE apiome.projects
  ADD COLUMN IF NOT EXISTS publishable BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN apiome.projects.publishable IS
  'Project-vs-Catalog boundary (MFI-23.1): true = publishable Project (OpenAPI/Swagger import); '
  'false = non-publishable catalog item (OpenAPI-worthy non-OpenAPI import). Write-once: enforced '
  'immutable by trigger so a catalog item can never be promoted to publishable except via the '
  'MFI-EPIC-22 convert flow, which mints a new Project.';

-- Both list surfaces (projects dashboard = publishable, catalog screen = catalog items) filter
-- tenant-scoped, live rows by `publishable`; this partial composite index serves both.
CREATE INDEX IF NOT EXISTS idx_projects_tenant_publishable
  ON apiome.projects(tenant_id, publishable) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------------------------------
-- Write-once guarantee: `publishable` is immutable once the row exists.
-- ---------------------------------------------------------------------------------------------------
-- A catalog item is `publishable = false` and must stay that way; equally, a publishable Project
-- must not be silently demoted. The flag is decided at creation (import routing, MFI-23.7) and never
-- changes. The trigger only fires when the value actually changes (IS DISTINCT FROM), so ordinary
-- UPDATEs that rewrite a project's other columns — even if they re-assert the same `publishable`
-- value — pass untouched.
CREATE OR REPLACE FUNCTION projects_forbid_publishable_change()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.publishable IS DISTINCT FROM OLD.publishable THEN
        RAISE EXCEPTION
            'projects.publishable is immutable (project %): a catalog item cannot be promoted to a '
            'publishable Project, and a Project cannot be demoted to a catalog item',
            OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_projects_publishable_immutable ON apiome.projects;
CREATE TRIGGER trigger_projects_publishable_immutable
    BEFORE UPDATE ON apiome.projects
    FOR EACH ROW
    EXECUTE FUNCTION projects_forbid_publishable_change();

COMMENT ON FUNCTION projects_forbid_publishable_change() IS
  'Trigger guard enforcing the write-once publishable flag on projects, so catalog items '
  '(publishable=false) can never be promoted to publishable Projects by an UPDATE (#4010, MFI-23.1).';
