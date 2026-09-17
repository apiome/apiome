-- Three-way spec synchronization — GNC-2.3 (#4739).
--
-- V264 gave a draft a durable relationship to a repository ref and remembered the **source digest**
-- of the files that relationship resolved to; a push to that ref became a *sync candidate* saying
-- "this moved". V265 gave the platform somewhere to record a verdict about a commit. Neither can
-- answer the question a reviewer actually has when a bound branch moves: *what changed, and does it
-- collide with what I have been editing?*
--
-- Three documents diverge: the **base** (the selection at the commit the binding is synchronized
-- with), **Git** (the selection at the commit the ref moved to) and the **draft** (the version as it
-- stands in this platform). Overwriting any of them with either of the others destroys work or
-- invalidates a review. This migration adds the two tables a semantic three-way merge needs:
--
--   apiome.draft_sync_plans     — one merge result: the three digests it was computed from, what
--                                 merged cleanly, and how much did not.
--   apiome.draft_sync_conflicts — one row per overlapping change, carrying base/incoming/current
--                                 side by side with the place in the repository source it is at.
--
-- Five rules shape the schema:
--
--   1. **A plan is a reading, never a write.** Nothing here points back at the canonical model, and
--      no column of `versions` is touched by anything that writes these rows. A merge result is
--      evidence about three documents; applying it to a draft is a separate, explicit act that this
--      migration deliberately gives no storage to. That is what "an active draft is never
--      overwritten" means once it reaches the schema: there is no path from a provider delivery to
--      a draft, only to a row a person reads.
--
--   2. **A plan is identified by the three documents it merged.** `UNIQUE (binding_id,
--      plan_fingerprint)`, where the fingerprint is taken over the binding, the base commit, the Git
--      commit and the draft's content digest. Re-running the merge for an unchanged trio collides
--      with the row that already exists instead of fanning out a second, differently-numbered
--      answer to the same question — which is what makes a rerun idempotent, and what lets a reread
--      skip two provider reads entirely.
--
--   3. **All three digests are recorded, and they are three different kinds of thing.**
--      `base_digest` and `git_digest` are `app.draft_bindings.source_digest` over a *fileset* (every
--      member's path and body); `draft_digest` is
--      `app.version_quality_capture.openapi_source_fingerprint` over the *document* the canonical
--      model reconstructs. Both spell themselves `sha256:…`. Storing all three is what lets a later
--      reader prove which bytes a merge result describes, and detect that one of them has moved.
--
--   4. **A conflict names a place, not just a value.** `pointer` (RFC 6901) locates it in the
--      document; `source_file` and `source_line` locate it in the repository file the incoming side
--      was read from, so "resolve this" is a link and not a search. `scope` and `group_key` are the
--      same grouping vocabulary the source-change review already speaks
--      (`app.source_change_review.scope_for_pointer`), so one conflict list can be read the way
--      every other change list in the product is.
--
--   5. **A settlement is final.** A conflict is resolved once, towards `git` or `draft`, and the
--      trigger refuses to move it afterwards — the same rule V264 put on a sync candidate. A record
--      of "what we decided to do about this collision" that anyone can quietly re-decide is not a
--      record of anything.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.draft_sync_conflicts;
--   DROP TABLE IF EXISTS apiome.draft_sync_plans;
--   DROP FUNCTION IF EXISTS apiome.draft_sync_conflicts_guard_settlement();
--   DROP FUNCTION IF EXISTS apiome.draft_sync_plans_guard_identity();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- draft_sync_plans — one three-way merge result for one binding.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS draft_sync_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. The binding is the authorization (V264 wrote it only after proving the repository
    -- read); project and version are carried rather than joined so the reviewer-facing read is one
    -- index hit and a plan still explains itself in the audit trail.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    binding_id UUID NOT NULL REFERENCES draft_repository_bindings(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- The movement this merge is about, when one drove it. NULL for a merge computed directly
    -- against a commit. ON DELETE SET NULL: a plan outlives the candidate row, because the merge
    -- result is the durable evidence and the candidate is the notification that prompted it.
    candidate_id UUID REFERENCES draft_binding_sync_candidates(id) ON DELETE SET NULL,

    -- Rule 3, side one: the merge base — the commit the binding was synchronized with, and the
    -- fileset digest V264 recorded for it. A merge whose base digest no longer describes what that
    -- commit holds (a force-push over it) is refused in apiome-rest before a row is written.
    base_commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT draft_sync_plans_base_commit_check
        CHECK (length(btrim(base_commit_sha)) > 0),
    base_digest VARCHAR(128) NOT NULL
        CONSTRAINT draft_sync_plans_base_digest_check
        CHECK (length(btrim(base_digest)) > 0),

    -- Rule 3, side two: the incoming commit and the fileset digest actually read there. Never the
    -- digest a delivery payload asserted: apiome-rest reads the selection itself.
    git_commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT draft_sync_plans_git_commit_check
        CHECK (length(btrim(git_commit_sha)) > 0),
    git_digest VARCHAR(128) NOT NULL
        CONSTRAINT draft_sync_plans_git_digest_check
        CHECK (length(btrim(git_digest)) > 0),

    -- Rule 3, side three: the draft's own content fingerprint, over the reconstructed document
    -- rather than over any file. A draft has no commit, so this is the only thing that can say
    -- "these are the bytes we merged against".
    draft_digest VARCHAR(128) NOT NULL
        CONSTRAINT draft_sync_plans_draft_digest_check
        CHECK (length(btrim(draft_digest)) > 0),

    -- Rule 2: sha256 over (binding, base commit, git commit, draft digest) — the rerun key.
    plan_fingerprint VARCHAR(128) NOT NULL
        CONSTRAINT draft_sync_plans_fingerprint_check
        CHECK (length(btrim(plan_fingerprint)) > 0),

    -- clean       — the repository changed nothing since the base; there is nothing to merge.
    -- mergeable   — incoming changes exist and none of them overlap the draft's own.
    -- conflicted  — at least one overlap is outstanding.
    -- resolved    — every conflict has been settled towards one side.
    status VARCHAR(16) NOT NULL
        CONSTRAINT draft_sync_plans_status_check
        CHECK (status IN ('clean', 'mergeable', 'conflicted', 'resolved')),

    -- What the merge did, counted. `auto_applied` is the acceptance criterion "non-overlapping
    -- changes apply deterministically" made countable; `local` is what the draft changed and the
    -- repository did not, which the merge keeps untouched; `agreed` is where both sides made the
    -- same change, which is not a conflict.
    auto_applied_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_auto_applied_check CHECK (auto_applied_count >= 0),
    local_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_local_check CHECK (local_count >= 0),
    agreed_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_agreed_check CHECK (agreed_count >= 0),
    conflict_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_conflict_check CHECK (conflict_count >= 0),
    -- True when the merge found more collisions than one plan stores. A result that quietly
    -- dropped findings would read as *less* conflicted than it is, which is the one direction this
    -- table must never be wrong in, so the fact is on the row rather than implied by a full page.
    conflicts_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    unresolved_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_unresolved_check
        CHECK (unresolved_count >= 0 AND unresolved_count <= conflict_count),

    -- The deterministic incoming changes the merge folded in, each with its pointer, kind, grouping
    -- and the before/after values. A reviewer reads this to see what would land; a later apply path
    -- replays it. Oversized values are replaced by a marker in apiome-rest before they get here.
    changes JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT draft_sync_plans_changes_check CHECK (jsonb_typeof(changes) = 'array'),

    -- Where the incoming document was read from, relative to the repository root, and how many
    -- files the selection resolved to. Presentation facts, so a plan can link to its source.
    source_file TEXT NOT NULL DEFAULT '',
    source_member_count INTEGER NOT NULL DEFAULT 0
        CONSTRAINT draft_sync_plans_member_count_check CHECK (source_member_count >= 0),

    -- Rule 1, recorded: why this merge result may not be turned into an edit of the draft, as it
    -- stood when the merge was computed. `none` is the ordinary case.
    --   review_decided    — an open review on this version already holds a recorded decision.
    --   version_published — the version is no longer a draft.
    guard VARCHAR(32) NOT NULL DEFAULT 'none'
        CONSTRAINT draft_sync_plans_guard_check
        CHECK (guard IN ('none', 'review_decided', 'version_published')),

    computed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A plan with conflicts is `conflicted` until they are all settled, and `resolved` once none
    -- are outstanding; a plan without conflicts is never either. The three facts are one fact told
    -- three ways, so they may not disagree.
    CONSTRAINT draft_sync_plans_conflict_status_check
        CHECK (
            (status IN ('clean', 'mergeable') AND conflict_count = 0 AND unresolved_count = 0)
            OR (status = 'conflicted' AND conflict_count > 0 AND unresolved_count > 0)
            OR (status = 'resolved' AND conflict_count > 0 AND unresolved_count = 0)
        ),
    -- Rule 1 again, as a constraint rather than a convention: a clean merge changed nothing.
    CONSTRAINT draft_sync_plans_clean_check
        CHECK (status <> 'clean' OR auto_applied_count = 0)
);

-- Rule 2: the rerun key. Same binding, same three documents — same row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_sync_plans_fingerprint
    ON draft_sync_plans (binding_id, plan_fingerprint);

-- The panel's read: this version's merge results, newest first.
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_version_created
    ON draft_sync_plans (version_id, created_at DESC);

-- One binding's merge results, newest first.
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_binding_created
    ON draft_sync_plans (binding_id, created_at DESC);

-- "What is waiting on somebody in this tenant?" and the tenant deletion path.
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_tenant_conflicted
    ON draft_sync_plans (tenant_id, created_at DESC) WHERE status = 'conflicted';

-- The candidate read: the merge results raised for one observed movement.
CREATE INDEX IF NOT EXISTS idx_draft_sync_plans_candidate
    ON draft_sync_plans (candidate_id) WHERE candidate_id IS NOT NULL;

COMMENT ON TABLE draft_sync_plans IS
    'One semantic three-way merge of a bound draft against its repository ref: the base, Git and draft digests it was computed from, what merged deterministically, and how much conflicted (GNC-2.3, #4739). A reading, never a write: nothing here edits a draft.';
COMMENT ON COLUMN draft_sync_plans.binding_id IS
    'The branch-to-draft binding the merge is about; a plan inherits that binding''s proven repository access and is removed with it';
COMMENT ON COLUMN draft_sync_plans.candidate_id IS
    'The observed ref movement that prompted the merge, when one did; NULL-ed rather than removed, because the merge result outlives the notification';
COMMENT ON COLUMN draft_sync_plans.base_digest IS
    'Fileset digest of the selection at base_commit_sha — the last synchronized digest the merge is measured against';
COMMENT ON COLUMN draft_sync_plans.git_digest IS
    'Fileset digest of the selection actually read at git_commit_sha; never a digest a delivery payload asserted';
COMMENT ON COLUMN draft_sync_plans.draft_digest IS
    'Content fingerprint of the reconstructed draft document; a draft has no commit, so this is what pins the third side';
COMMENT ON COLUMN draft_sync_plans.plan_fingerprint IS
    'sha256 over (binding, base commit, git commit, draft digest) — the rerun idempotency key, computable before any provider read';
COMMENT ON COLUMN draft_sync_plans.status IS
    'clean (nothing incoming) | mergeable (no overlap) | conflicted (overlaps outstanding) | resolved (every conflict settled)';
COMMENT ON COLUMN draft_sync_plans.changes IS
    'The non-overlapping incoming changes the merge applied deterministically, each with pointer, kind, scope, group and before/after values';
COMMENT ON COLUMN draft_sync_plans.conflicts_truncated IS
    'True when the merge found more collisions than a plan stores; the stored ones are a page of a longer list, never the whole of it';
COMMENT ON COLUMN draft_sync_plans.guard IS
    'Why this result may not be turned into an edit of the draft, as it stood when the merge ran: none | review_decided | version_published';

-- ---------------------------------------------------------------------------------------------------
-- draft_sync_conflicts — one overlapping change, with all three sides and where it lives (rule 4).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS draft_sync_conflicts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    plan_id UUID NOT NULL REFERENCES draft_sync_plans(id) ON DELETE CASCADE,
    -- Carried rather than joined: the tenant's conflict read is one index hit, and a tenant
    -- deletion removes the rows directly.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Rule 4: where in the document. The root pointer is the empty string, so this is not
    -- length-checked — an empty pointer is a legal, meaningful value.
    pointer TEXT NOT NULL,
    -- The grouping vocabulary of app.source_change_review, so one conflict list reads like every
    -- other change list in the product.
    scope VARCHAR(16) NOT NULL
        CONSTRAINT draft_sync_conflicts_scope_check
        CHECK (scope IN ('document', 'path', 'operation', 'component', 'schema')),
    group_key VARCHAR(255) NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',

    -- What each side did to the base at this pointer. Both are always present: a conflict exists
    -- exactly when both sides moved the same place to different values.
    git_kind VARCHAR(16) NOT NULL
        CONSTRAINT draft_sync_conflicts_git_kind_check
        CHECK (git_kind IN ('addition', 'update', 'deletion')),
    draft_kind VARCHAR(16) NOT NULL
        CONSTRAINT draft_sync_conflicts_draft_kind_check
        CHECK (draft_kind IN ('addition', 'update', 'deletion')),

    -- The three sides, side by side. JSON null, false and an empty container are all legal values,
    -- so these are nullable columns holding `jsonb` rather than a sentinel: a missing value is
    -- expressed by the *kind* (an addition has no base value), never by the column being NULL.
    base_value JSONB,
    git_value JSONB,
    draft_value JSONB,

    -- Rule 4: where in the repository. The file is relative to the repository root, and the line is
    -- 1-based; both are best-effort, because a value the incoming document does not spell out
    -- (a deletion) has no line to point at.
    source_file TEXT NOT NULL DEFAULT '',
    source_line INTEGER
        CONSTRAINT draft_sync_conflicts_source_line_check
        CHECK (source_line IS NULL OR source_line > 0),
    source_url TEXT NOT NULL DEFAULT '',

    -- Rule 5: which side won, once somebody decided. `git` takes the incoming value; `draft` keeps
    -- what the version already has. There is no third option, because a merge result is not an
    -- editor.
    resolution VARCHAR(16)
        CONSTRAINT draft_sync_conflicts_resolution_check
        CHECK (resolution IS NULL OR resolution IN ('git', 'draft')),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolution_note TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Settled and unsettled are one fact told twice; they may not disagree.
    CONSTRAINT draft_sync_conflicts_settled_check
        CHECK ((resolution IS NULL) = (resolved_at IS NULL)),
    CONSTRAINT draft_sync_conflicts_resolver_check
        CHECK (resolved_at IS NOT NULL OR (resolved_by IS NULL AND resolution_note IS NULL))
);

-- One conflict per pointer per plan: the same collision described twice is one collision.
CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_sync_conflicts_pointer
    ON draft_sync_conflicts (plan_id, pointer);

-- The panel's read: one plan's conflicts, in a stable order.
CREATE INDEX IF NOT EXISTS idx_draft_sync_conflicts_plan_created
    ON draft_sync_conflicts (plan_id, created_at);

-- "What is still waiting on somebody?" and the tenant deletion path.
CREATE INDEX IF NOT EXISTS idx_draft_sync_conflicts_tenant_open
    ON draft_sync_conflicts (tenant_id, created_at DESC) WHERE resolution IS NULL;

COMMENT ON TABLE draft_sync_conflicts IS
    'One overlapping change in a three-way merge, carrying the base, incoming and current values side by side with the repository file and line it lives at (GNC-2.3, #4739)';
COMMENT ON COLUMN draft_sync_conflicts.pointer IS 'RFC 6901 pointer of the collision; the empty string is the document root and is a legal value';
COMMENT ON COLUMN draft_sync_conflicts.scope IS 'document | path | operation | component | schema — app.source_change_review''s grouping vocabulary';
COMMENT ON COLUMN draft_sync_conflicts.git_kind IS 'What the repository did to the base here: addition | update | deletion';
COMMENT ON COLUMN draft_sync_conflicts.draft_kind IS 'What the draft did to the base here: addition | update | deletion';
COMMENT ON COLUMN draft_sync_conflicts.source_line IS '1-based line in source_file where the incoming value begins; NULL when the incoming document does not spell it out';
COMMENT ON COLUMN draft_sync_conflicts.resolution IS 'git (take the incoming value) | draft (keep what the version has); final once set';

-- ---------------------------------------------------------------------------------------------------
-- Rule 2 + rule 3: what a plan merged never changes.
--
-- Only the outcome moves — status, the counts, the applied changes, the guard, updated_at — and it
-- moves exactly once per conflict settled. Which binding, which commits, which digests, which
-- fingerprint: those are the identity, and changing one would silently repoint a merge result at
-- documents it was never computed from. `candidate_id` is exempt in one direction only, so the
-- ON DELETE SET NULL above can do its work.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.draft_sync_plans_guard_identity()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.base_commit_sha IS DISTINCT FROM OLD.base_commit_sha
       OR NEW.base_digest IS DISTINCT FROM OLD.base_digest
       OR NEW.git_commit_sha IS DISTINCT FROM OLD.git_commit_sha
       OR NEW.git_digest IS DISTINCT FROM OLD.git_digest
       OR NEW.draft_digest IS DISTINCT FROM OLD.draft_digest
       OR NEW.plan_fingerprint IS DISTINCT FROM OLD.plan_fingerprint
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR (NEW.candidate_id IS DISTINCT FROM OLD.candidate_id AND NEW.candidate_id IS NOT NULL) THEN
        RAISE EXCEPTION 'draft_sync_plans: what a merge was computed from never changes — compute it again'
            USING ERRCODE = 'check_violation';
    END IF;

    -- How many collisions a merge found is part of the merge, not part of settling it.
    IF NEW.conflict_count IS DISTINCT FROM OLD.conflict_count
       OR NEW.conflicts_truncated IS DISTINCT FROM OLD.conflicts_truncated THEN
        RAISE EXCEPTION 'draft_sync_plans: conflict_count is what the merge found; it does not change as conflicts are settled'
            USING ERRCODE = 'check_violation';
    END IF;

    -- Settling is one-way: outstanding collisions are only ever resolved, never re-opened.
    IF NEW.unresolved_count > OLD.unresolved_count THEN
        RAISE EXCEPTION 'draft_sync_plans: unresolved_count never increases — a settled conflict stays settled'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_sync_plans_guard_identity ON draft_sync_plans;
CREATE TRIGGER trg_draft_sync_plans_guard_identity
    BEFORE UPDATE ON draft_sync_plans
    FOR EACH ROW
    EXECUTE FUNCTION apiome.draft_sync_plans_guard_identity();

-- ---------------------------------------------------------------------------------------------------
-- Rule 4 + rule 5: a conflict describes one place, and is settled once.
--
-- The pointer, the scope, the three sides and the source location are what the merge found; only
-- the settlement moves, and only from unsettled to settled. Re-deciding a collision after the fact
-- would make the record of a decision worth nothing — the same rule V264 put on a sync candidate.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.draft_sync_conflicts_guard_settlement()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.pointer IS DISTINCT FROM OLD.pointer
       OR NEW.scope IS DISTINCT FROM OLD.scope
       OR NEW.git_kind IS DISTINCT FROM OLD.git_kind
       OR NEW.draft_kind IS DISTINCT FROM OLD.draft_kind
       OR NEW.base_value IS DISTINCT FROM OLD.base_value
       OR NEW.git_value IS DISTINCT FROM OLD.git_value
       OR NEW.draft_value IS DISTINCT FROM OLD.draft_value
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'draft_sync_conflicts: what a conflict is never changes — it is a finding, not a note'
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.resolution IS NOT NULL AND NEW.resolution IS DISTINCT FROM OLD.resolution THEN
        RAISE EXCEPTION 'draft_sync_conflicts: a conflict is settled once; settlements are final'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_sync_conflicts_guard_settlement ON draft_sync_conflicts;
CREATE TRIGGER trg_draft_sync_conflicts_guard_settlement
    BEFORE UPDATE ON draft_sync_conflicts
    FOR EACH ROW
    EXECUTE FUNCTION apiome.draft_sync_conflicts_guard_settlement();
