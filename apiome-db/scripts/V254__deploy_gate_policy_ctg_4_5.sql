-- Deploy-gating status API — CTG-4.5 (#4502).
--
-- CTG-3.1 (V178) recorded whether a publish was breaking, CTG-4.1/4.2 (V251) recorded who consumes
-- what, CTG-4.3 (V252) recorded whether the deployment still matches its contract, and CTG-4.4
-- (V253) recorded when it last did. GOV has recorded a lint grade on the revision since V124. A CD
-- pipeline asking "can I promote this?" therefore had five places to look and no rule for combining
-- them, so every team wrote its own.
--
-- The endpoint that answers the question in one call needs exactly one thing the database does not
-- already hold: **where the bar is**. That is this migration.
--
--   deploy_gate_policy — one tenant's (or one project's) thresholds: the lint grade below which the
--                        gate warns or fails, the breaking severity that fails it, how many
--                        breaking consumers are tolerated, and how stale a verification may be.
--
-- Four rules shape the schema:
--
--   1. **Two scopes, one shape.** ``project_id IS NULL`` is the tenant-wide policy; a row naming a
--      project overrides it for that project only. Two partial unique indexes keep exactly one row
--      per scope, so "the policy in force" is a lookup rather than a reduction over history.
--
--   2. **The row is mutable, and that is deliberate.** Every other policy table in the platform
--      (ECA-3.1 verification policy, IXH-2.3 quality policy) is append-only because a *stored*
--      evaluation has to stay explicable against the policy version it was judged under. The gate
--      stores no verdict — it is computed on demand and returns its policy fingerprint inline —
--      so there is no past judgment for a version history to explain. Attribution of a change
--      lives in ``access_audit``, which is where every other governance edit is already recorded.
--
--   3. **An absent row is not an absent policy.** A tenant that has never configured anything gets
--      the documented default, which is why every threshold column lives inside one JSONB body
--      rather than as nullable columns: "unset" and "set to null" are different answers (null
--      disables a rung; unset takes the default), and a JSONB body can say both.
--
--   4. **A policy cannot outlive its scope.** Both foreign keys cascade: deleting a project drops
--      its override, deleting a tenant drops everything. A threshold pointing at nothing would be
--      invisible configuration that silently reappears if an id were ever reused.
--
-- The migration also adds one index to CTG-4.3's report table. The gate is anchored on a *project*,
-- but a report is addressed by the ``version_ref`` string it was requested with (which may spell
-- the project as a slug or an id, and the version as a label, a revision id, or ``latest``).
-- ``artifact_kind``/``artifact_id`` are the resolved coordinates V252 already stores, so asking
-- "the newest report for this project" needs an index, not a new column.
--
-- **No new RBAC resource.** Reading a gate is reading the status of a published version
-- (``versions:view``, which is also what a CI runner's API key resolves to). Changing where the bar
-- sits is the same class of decision as changing where verification points, which V211's
-- ``verification_targets`` resource already keeps out of an Editor's hands — the identical argument
-- CTG-4.4 made for schedules. ``seed_builtin_roles`` is deliberately untouched: adding a resource
-- costs four synchronised edits (the role grid, the REST ``Resource`` enum, the enforcement call
-- sites, and the UI role matrix), and a permission that would always be granted alongside an
-- existing one earns none of them.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP INDEX IF EXISTS apiome.idx_provider_verification_report_artifact;
--   DROP TABLE IF EXISTS apiome.deploy_gate_policy;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- deploy_gate_policy — where the bar sits, for a tenant or for one of its projects.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deploy_gate_policy (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope (rule 1). ``project_id NULL`` is the tenant-wide policy; a row naming a project is that
    -- project's override. Both cascade (rule 4).
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- The thresholds themselves (rule 3), validated by the application against the documented
    -- ``ctg.gate-policy.v1`` shape before they reach this column. Stored as one body so an unset
    -- threshold (take the default) and a null one (disable that rung) stay distinguishable.
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT deploy_gate_policy_thresholds_object_check
            CHECK (jsonb_typeof(thresholds) = 'object'),

    -- SHA-256 over the canonical threshold body. Returned on every gate response so a pipeline can
    -- tell "the verdict changed because the API changed" from "because somebody moved the bar".
    content_fingerprint VARCHAR(71) NOT NULL,

    -- Provenance. ``ON DELETE SET NULL``: a departing user must not take a tenant's gate with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Rule 1, enforced: one tenant-wide policy…
CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_gate_policy_tenant
    ON deploy_gate_policy (tenant_id)
    WHERE project_id IS NULL;

-- …and at most one override per project.
CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_gate_policy_project
    ON deploy_gate_policy (tenant_id, project_id)
    WHERE project_id IS NOT NULL;

COMMENT ON TABLE deploy_gate_policy IS
    'CTG-4.5 (#4502): deploy-gate thresholds for a tenant (project_id NULL) or one of its projects. '
    'At most one row per scope; an absent row means the documented default policy.';

COMMENT ON COLUMN deploy_gate_policy.thresholds IS
    'ctg.gate-policy.v1 body: per-signal warn/fail thresholds for lint, breaking, consumers and '
    'verification. A null threshold disables that rung; an absent one takes the documented default.';

COMMENT ON COLUMN deploy_gate_policy.content_fingerprint IS
    'sha256: digest of the canonical threshold body, echoed on every gate response so a changed '
    'verdict can be attributed to a changed bar.';

-- ---------------------------------------------------------------------------------------------------
-- "The newest conformance report for this project" — the gate's verification fallback.
-- ---------------------------------------------------------------------------------------------------
-- V252 indexes reports by the ``version_ref`` string they were requested with. The gate is anchored
-- on a project id and must find evidence however the ref was spelled, so it reads the resolved
-- coordinates instead. Partial, because a report whose artifact could not be resolved is not
-- reachable by this question anyway.
CREATE INDEX IF NOT EXISTS idx_provider_verification_report_artifact
    ON provider_verification_report (tenant_id, artifact_kind, artifact_id, created_at DESC)
    WHERE artifact_id IS NOT NULL;
