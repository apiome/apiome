-- API change check suite — GNC-3.1 (#4740).
--
-- GNC-2.2 (V265) gave a bound draft somewhere to record a verdict about a commit and a status adapter
-- to put it on the pull request, and deliberately decided nothing: every verdict it carried was
-- somebody else's. The platform already *has* the answers — a stored lint grade (GOV), a breaking
-- classification and per-consumer verdicts (CTG), contract-test evidence (ECA), a generated client
-- kit (SDK) — but a pull-request author had to read five of them to learn one thing. This migration
-- holds the one verdict that aggregates them:
--
--   apiome.api_check_suite_policy — which of the suite's components a tenant (or one project)
--                                   requires, and whether a passing suite is required to publish.
--   apiome.api_check_suite_runs   — one row per distinct evaluation of a version: the four-state
--                                   verdict, every component behind it with its evidence, and the
--                                   exact policy it was judged under.
--
-- Five rules shape the schema:
--
--   1. **One verdict, four states.** A run is `pending | pass | fail | skipped` — V265's vocabulary,
--      because a run's verdict is what becomes the provider check. A run that could not judge the
--      draft at all (the branch has moved to a commit the draft has not caught up with, or a commit
--      that does not touch the specification) is recorded with `evaluated = FALSE`, and the CHECK
--      below forbids such a placeholder from claiming `pass` or `fail`: a verdict about bytes nobody
--      judged is exactly the green tick with nothing behind it that this table exists to prevent.
--
--   2. **A run is identified by what it judged, not by when.** `UNIQUE (version_id,
--      input_fingerprint)`: the fingerprint covers the draft's content digest, the commit, both
--      policies, and every component's verdict and evidence. Re-running the suite over unchanged
--      inputs collides with the row that already says so, which is what makes a re-run idempotent —
--      the same evidence ids come back, not a new almost-identical record.
--
--   3. **A run carries the policy it was judged under.** Both policy bodies (the suite's own and the
--      CTG-4.5 deploy-gate thresholds its CTG components are judged against) are snapshotted onto
--      the row with their fingerprints. That is why `api_check_suite_policy` may stay mutable, like
--      V254's `deploy_gate_policy`, even though this table stores verdicts: a stored verdict never
--      has to be explained by joining back to a policy row that has since moved.
--
--   4. **Evaluations are evidence: appended, never rewritten.** A BEFORE UPDATE trigger refuses every
--      change except the single one a foreign key performs on its own — `created_by` going to NULL
--      when the evaluating user is deleted. (V212's blanket guard would make deleting such a user
--      fail outright; this one does not.) DELETE is left to the cascades, for the reason V265 gives:
--      a BEFORE DELETE guard would also block every cascade that removes a project or a tenant.
--
--   5. **Nothing here can hold a credential.** A run is published through GNC-2.2, which resolves the
--      repository token in server memory; neither table has a column one could occupy.
--
-- The migration also adds one index to ECA-1.3's `verification_run`. The suite reads contract
-- evidence for a *revision*, but a run is keyed by the suite digest it executed — and that digest
-- covers the reference string it was compiled from, so the same revision spelled two ways yields two
-- digests. `source->>'revision_id'` is the resolved coordinate V212 already records on every run
-- compiled from a version, so "the newest run of this revision" needs an index, not a column.
--
-- And it corrects one index of GNC-2.2's publish ledger (V265), because the suite's re-run
-- idempotency depends on it. `UNIQUE (check_run_id, request_fingerprint)` made a verdict's *failed*
-- publish attempt occupy the one slot its later *successful* retry needed: the retry reached the
-- provider, collided in the ledger, and was never recorded — so the provider's check-run id was
-- never written back, and every later re-run POSTed a new check run onto the pull request instead
-- of moving the one already there. The ledger is now unique per verdict **per outcome**: a verdict
-- is still dispatched at most once, still ledgered as suppressed or failed at most once, and a
-- dispatch that follows a failure is evidence that lands.
--
-- **No new RBAC resource.** Running the suite records a verdict on a pull request, which GNC-2.2
-- already keeps behind `versions:edit`; reading it is `projects:view`; a policy that can block
-- publishing is a governance setting, kept to tenant administrators exactly as the COL-2.3 approval
-- policy is.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP INDEX IF EXISTS apiome.uq_provider_check_deliveries_fingerprint_outcome;
--   (recreating V265's uq_provider_check_deliveries_fingerprint fails once a verdict has both a
--    failed and a dispatched row — which is the state this migration exists to allow)
--   DROP INDEX IF EXISTS apiome.idx_verification_run_source_revision;
--   DROP TABLE IF EXISTS apiome.api_check_suite_runs;
--   DROP TABLE IF EXISTS apiome.api_check_suite_policy;
--   DROP FUNCTION IF EXISTS apiome.api_check_suite_runs_append_only();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- api_check_suite_policy — which components the suite requires, for a tenant or one of its projects.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_check_suite_policy (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope, as V254: `project_id NULL` is the tenant-wide policy; a row naming a project is that
    -- project's override. Both cascade — a policy pointing at nothing is invisible configuration.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

    -- The `gnc.check-suite-policy.v1` body, validated by apiome-rest before it reaches this column:
    -- a requirement (`required` | `advisory` | `off`) per component, and `requiredForPublish`. One
    -- body rather than columns so an absent component (take the documented default) and a named one
    -- stay distinguishable.
    policy JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT api_check_suite_policy_object_check
            CHECK (jsonb_typeof(policy) = 'object'),

    -- SHA-256 over the canonical body. Stamped on every run judged under it (rule 3).
    content_fingerprint VARCHAR(71) NOT NULL
        CONSTRAINT api_check_suite_policy_fingerprint_check
            CHECK (length(btrim(content_fingerprint)) > 0),

    -- Provenance. `ON DELETE SET NULL`: a departing administrator must not take the policy with them.
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One tenant-wide policy…
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_check_suite_policy_tenant
    ON api_check_suite_policy (tenant_id)
    WHERE project_id IS NULL;

-- …and at most one override per project.
CREATE UNIQUE INDEX IF NOT EXISTS idx_api_check_suite_policy_project
    ON api_check_suite_policy (tenant_id, project_id)
    WHERE project_id IS NOT NULL;

COMMENT ON TABLE api_check_suite_policy IS
    'GNC-3.1 (#4740): which API change check suite components a tenant (project_id NULL) or one of its projects requires, and whether a passing suite is required to publish. At most one row per scope; an absent row means the documented default.';
COMMENT ON COLUMN api_check_suite_policy.policy IS
    'gnc.check-suite-policy.v1 body: components (lint|breaking|consumers|contract|sdk -> required|advisory|off) and requiredForPublish. An absent component takes its documented default.';
COMMENT ON COLUMN api_check_suite_policy.content_fingerprint IS
    'sha256: digest of the canonical policy body, snapshotted onto every run judged under it.';

-- ---------------------------------------------------------------------------------------------------
-- api_check_suite_runs — one row per distinct evaluation of a version (rules 1–5).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_check_suite_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- The binding the verdict was reported through, and the commit it is about, when the version is
    -- bound to a repository ref. A run of an unbound draft names neither and is recorded all the
    -- same: the verdict is about the draft, the provider is only one place it is shown. A run goes
    -- with its binding, as V265's check runs do.
    binding_id UUID REFERENCES draft_repository_bindings(id) ON DELETE CASCADE,
    commit_sha VARCHAR(64)
        CONSTRAINT api_check_suite_runs_commit_sha_check
        CHECK (commit_sha IS NULL OR length(btrim(commit_sha)) > 0),
    pr_number INTEGER
        CONSTRAINT api_check_suite_runs_pr_number_check
        CHECK (pr_number IS NULL OR pr_number > 0),
    -- The provider check the verdict became, by V265's identity: (binding, commit, name).
    check_name VARCHAR(128) NOT NULL
        CONSTRAINT api_check_suite_runs_check_name_check
        CHECK (length(btrim(check_name)) > 0),

    -- Rule 1: whether the components were judged against the draft at all.
    evaluated BOOLEAN NOT NULL,
    state VARCHAR(16) NOT NULL
        CONSTRAINT api_check_suite_runs_state_check
        CHECK (state IN ('pending', 'pass', 'fail', 'skipped')),
    -- A stable, machine-readable reason for the state (`required-component-failed`,
    -- `draft-not-synchronized`, …). A client branches on this, never on prose.
    reason VARCHAR(64) NOT NULL
        CONSTRAINT api_check_suite_runs_reason_check
        CHECK (length(btrim(reason)) > 0),

    -- The draft as judged: a *document* fingerprint (the rebuilt OpenAPI), the same one GNC-2.3's
    -- merge results and the lint report's freshness rule use, so "the draft changed" means one
    -- thing everywhere. The publish gate matches a run to the draft by this value.
    draft_digest VARCHAR(71) NOT NULL
        CONSTRAINT api_check_suite_runs_draft_digest_check
        CHECK (length(btrim(draft_digest)) > 0),

    -- Rule 3: the suite policy in force — fingerprinted over its component requirements, the part
    -- that decides a verdict (turning `requiredForPublish` on must not stale every evaluation)…
    policy_source VARCHAR(16) NOT NULL
        CONSTRAINT api_check_suite_runs_policy_source_check
        CHECK (policy_source IN ('default', 'tenant', 'project')),
    policy_fingerprint VARCHAR(71) NOT NULL,
    policy JSONB NOT NULL
        CONSTRAINT api_check_suite_runs_policy_object_check
        CHECK (jsonb_typeof(policy) = 'object'),
    -- …and the CTG-4.5 thresholds its lint, breaking and consumer components were judged against.
    thresholds_source VARCHAR(16) NOT NULL
        CONSTRAINT api_check_suite_runs_thresholds_source_check
        CHECK (thresholds_source IN ('default', 'tenant', 'project')),
    thresholds_fingerprint VARCHAR(71) NOT NULL,
    thresholds JSONB NOT NULL
        CONSTRAINT api_check_suite_runs_thresholds_object_check
        CHECK (jsonb_typeof(thresholds) = 'object'),

    -- Every component: its requirement, state, reason, the evidence it read (ids, digests, counts)
    -- and a link to that evidence. The drill-down *is* this column.
    components JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT api_check_suite_runs_components_array_check
        CHECK (jsonb_typeof(components) = 'array'),

    -- Rule 2: sha256 over everything the verdict is a function of.
    input_fingerprint VARCHAR(71) NOT NULL
        CONSTRAINT api_check_suite_runs_input_fingerprint_check
        CHECK (length(btrim(input_fingerprint)) > 0),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 1: a run that judged nothing may only wait or decline — never pass or fail.
    CONSTRAINT api_check_suite_runs_placeholder_check
        CHECK (evaluated OR state IN ('pending', 'skipped')),
    -- A commit is only meaningful through a binding; a binding always names one.
    CONSTRAINT api_check_suite_runs_binding_commit_check
        CHECK ((binding_id IS NULL) = (commit_sha IS NULL))
);

-- Rule 2: the re-run idempotency key.
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_check_suite_runs_input
    ON api_check_suite_runs (version_id, input_fingerprint);

-- A version's evaluations, newest first — the history read and the publish gate's read.
CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_version_created
    ON api_check_suite_runs (version_id, created_at DESC);

-- One commit's evaluations — "what did the suite say about this commit?".
CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_binding_commit
    ON api_check_suite_runs (binding_id, commit_sha, created_at DESC)
    WHERE binding_id IS NOT NULL;

-- Tenant-wide reads and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_api_check_suite_runs_tenant_created
    ON api_check_suite_runs (tenant_id, created_at DESC);

COMMENT ON TABLE api_check_suite_runs IS
    'GNC-3.1 (#4740): one row per distinct API change check suite evaluation of a version — the pending|pass|fail|skipped verdict, every component behind it with its evidence, and the policies it was judged under. Append-only. Holds no credential.';
COMMENT ON COLUMN api_check_suite_runs.evaluated IS
    'FALSE for a placeholder that could not judge the draft (branch ahead of the draft, or a commit that does not touch the specification); such a row is only ever pending or skipped';
COMMENT ON COLUMN api_check_suite_runs.reason IS 'Stable reason code for the state; branch on this, never on prose';
COMMENT ON COLUMN api_check_suite_runs.draft_digest IS
    'sha256 of the draft document as judged; the publish gate matches a run to the draft by this value';
COMMENT ON COLUMN api_check_suite_runs.policy IS 'The gnc.check-suite-policy.v1 body the run was judged under, snapshotted';
COMMENT ON COLUMN api_check_suite_runs.policy_fingerprint IS
    'sha256 of the component requirements the run was judged under; the publish gate matches on it';
COMMENT ON COLUMN api_check_suite_runs.thresholds IS 'The ctg.gate-policy.v1 thresholds the CTG components were judged against, snapshotted';
COMMENT ON COLUMN api_check_suite_runs.components IS
    'Every component: requirement, state, reason, detail, the evidence read and a link to it — the drill-down';
COMMENT ON COLUMN api_check_suite_runs.input_fingerprint IS
    'sha256 over the draft digest, commit, both policies and every component verdict; the re-run idempotency key';

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: an evaluation is evidence. The only permitted change is the one a foreign key makes on its
-- own: `created_by` going to NULL when that user is deleted. Everything else — the verdict, the
-- components, the policies, the identity — is refused.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.api_check_suite_runs_append_only()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.created_by IS NOT NULL
       AND NEW.created_by IS NULL
       AND (to_jsonb(NEW) - 'created_by') = (to_jsonb(OLD) - 'created_by') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'api_check_suite_runs is append-only: an evaluation is evidence and cannot be rewritten'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.api_check_suite_runs_append_only() IS
    'Refuses UPDATE on api_check_suite_runs except the ON DELETE SET NULL of created_by (GNC-3.1). DELETE is left to the cascades.';

DROP TRIGGER IF EXISTS trg_api_check_suite_runs_append_only ON api_check_suite_runs;
CREATE TRIGGER trg_api_check_suite_runs_append_only
    BEFORE UPDATE ON api_check_suite_runs
    FOR EACH ROW
    EXECUTE FUNCTION apiome.api_check_suite_runs_append_only();

-- ---------------------------------------------------------------------------------------------------
-- "The newest contract run of this revision" — the suite's executable-contract evidence.
-- ---------------------------------------------------------------------------------------------------
-- Partial, because a run recorded without a resolved revision (an inline suite upload) is not
-- reachable by this question anyway. The accessor repeats the expression and the predicate exactly
-- so the planner can use it.
CREATE INDEX IF NOT EXISTS idx_verification_run_source_revision
    ON verification_run (tenant_id, (source ->> 'revision_id'), created_at DESC)
    WHERE source ? 'revision_id';

-- ---------------------------------------------------------------------------------------------------
-- GNC-2.2's publish ledger: one row per verdict per *outcome*.
-- ---------------------------------------------------------------------------------------------------
-- Created before the old index is dropped, so the ledger is never without a uniqueness guarantee.
-- apiome-rest's accessor names exactly these three columns in its ON CONFLICT target, and reads a
-- verdict's dispatched row first, so "already published" still means "a dispatch exists".
CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_check_deliveries_fingerprint_outcome
    ON provider_check_deliveries (check_run_id, request_fingerprint, outcome);

DROP INDEX IF EXISTS uq_provider_check_deliveries_fingerprint;
