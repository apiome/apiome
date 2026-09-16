-- Branch-to-draft binding — GNC-2.1 (#4737).
--
-- Importing a repository file produces a *snapshot*: a revision that records which repo and which
-- commit it came from, and nothing that survives as a relationship. Nobody can ask "which branch is
-- this draft the API review of?", and a later push to that branch has nowhere to land. This
-- migration adds the durable review unit: a **binding** pins one draft version to one provider,
-- repository, ref, and source path, together with the digest of the source it was last
-- synchronized with, and every observed movement of that ref becomes an explicit, auditable
-- **sync candidate** instead of quietly rewriting the draft.
--
--   draft_repository_bindings    — one draft version <-> one repository ref + path, plus its digest.
--   draft_binding_sync_candidates — one observed ref update awaiting a decision.
--
-- Six rules shape the schema:
--
--   1. **At most one active binding per draft.** A partial unique index on ``version_id`` where
--      ``released_at IS NULL`` allows any number of released bindings but only one live one, so
--      "bind this draft somewhere else" is release-then-bind rather than an in-place rewrite.
--      That a version is a *draft* — unpublished — is enforced by apiome-rest rather than by a
--      trigger reading ``versions``, exactly as COL-2.1 (V261) enforces it for reviews; a binding
--      whose version is published later stays readable and stops accepting candidates.
--
--   2. **Binding history is retained.** Re-binding and unbinding stamp ``released_at`` /
--      ``released_by`` / ``release_reason``; the row itself stays, carrying the ref, path, commit
--      and digest it was bound at. A released binding is never rewritten (trigger), so "what was
--      this draft bound to in March, and against which source" stays answerable.
--
--   3. **A binding carries the source digest it was last synchronized with.** ``commit_sha`` and
--      ``source_digest`` move — and only those, while the binding is active — as candidates are
--      applied; the pair is the base GNC-2.3's three-way synchronization diffs against. Which
--      repository, which ref, which path a binding names never change: that would be a different
--      review unit, and is a new binding.
--
--   4. **A ref update is a candidate, not a write.** Every observed movement of a bound ref inserts
--      a ``pending`` row naming the commit and digest it moved *from* and the commit it moved *to*.
--      Nothing about the draft changes. Redelivery is idempotent twice over: one pending candidate
--      per (binding, target commit), and one candidate per (binding, provider delivery id).
--
--   5. **A resolved candidate is frozen.** ``pending`` moves once, to ``applied`` (the draft is in
--      sync with that commit), ``dismissed`` (the update is deliberately not being taken), or
--      ``superseded`` (a newer candidate on the same binding replaced it). A trigger refuses every
--      other change, whichever writer attempts it, so the candidate ledger is append-and-settle.
--
--   6. **Scope never leaks across a tenant, and history survives its people and its registration.**
--      A binding carries its tenant, project, and version and is removed with any of them;
--      candidates are removed with their binding. Deleting a *user* keeps what they bound
--      (``ON DELETE SET NULL``), and de-registering a repository keeps the binding row — its
--      provider, full name, and URL are stored on the binding itself precisely so the history
--      survives (``repository_id`` goes to NULL and apiome-rest treats the binding as unusable).
--
-- Authorization is **not** in this schema: binding requires ``versions:edit`` *and* a proven read
-- of the repository at that ref through a stored credential, which apiome-rest
-- (``app.draft_binding_store``) performs before any row is written. Every bind, re-bind, release,
-- candidate, and resolution is also written to ``workflow_audit`` (``binding.*`` actions) by
-- apiome-rest, in the same transaction as the change it records.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.draft_binding_sync_candidates;
--   DROP TABLE IF EXISTS apiome.draft_repository_bindings;
--   DROP FUNCTION IF EXISTS apiome.draft_binding_sync_candidates_guard_resolved();
--   DROP FUNCTION IF EXISTS apiome.draft_repository_bindings_guard_identity();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- draft_repository_bindings — one draft version bound to one repository ref and path.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS draft_repository_bindings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope, carried so a project's binding list and a version's binding each hit one index.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- The registered repository the binding was authorized through, when there is one. Rule 6:
    -- de-registering the repository must not erase the binding history, so this goes to NULL and
    -- the provider coordinates below keep the row self-describing.
    repository_id UUID REFERENCES tenant_repositories(id) ON DELETE SET NULL,

    -- Rule 3: the provider coordinates, immutable for the life of the binding.
    provider VARCHAR(32) NOT NULL
        CONSTRAINT draft_repository_bindings_provider_check
        CHECK (provider IN ('github', 'gitlab', 'bitbucket')),
    repo_full_name VARCHAR(512) NOT NULL
        CONSTRAINT draft_repository_bindings_repo_full_name_check
        CHECK (length(btrim(repo_full_name)) > 0),
    repo_url TEXT NOT NULL
        CONSTRAINT draft_repository_bindings_repo_url_check
        CHECK (length(btrim(repo_url)) > 0),
    ref VARCHAR(255) NOT NULL
        CONSTRAINT draft_repository_bindings_ref_check
        CHECK (length(btrim(ref)) > 0),
    -- The path or glob selecting the source inside the repository. Empty means the whole tree.
    path TEXT NOT NULL DEFAULT '',

    -- Rule 3: the source this binding is currently in sync with. Both move together.
    commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT draft_repository_bindings_commit_sha_check
        CHECK (length(btrim(commit_sha)) > 0),
    source_digest VARCHAR(128) NOT NULL
        CONSTRAINT draft_repository_bindings_source_digest_check
        CHECK (length(btrim(source_digest)) > 0),
    -- When the pair above last moved; equal to created_at until a candidate is applied.
    synchronized_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 2: set when the binding stops being the draft's active one; NULL while it is.
    released_at TIMESTAMP WITH TIME ZONE,
    released_by UUID REFERENCES users(id) ON DELETE SET NULL,
    release_reason VARCHAR(32)
        CONSTRAINT draft_repository_bindings_release_reason_check
        CHECK (release_reason IS NULL OR release_reason IN ('replaced', 'unbound', 'repository_removed')),

    -- An active binding has neither a releaser nor a reason.
    CONSTRAINT draft_repository_bindings_released_check
        CHECK (released_at IS NOT NULL OR (released_by IS NULL AND release_reason IS NULL))
);

-- Rule 1: at most one active binding per draft version.
CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_repository_bindings_active_version
    ON draft_repository_bindings (version_id) WHERE released_at IS NULL;

-- The webhook lookup: "which drafts are bound to this repository's ref?" (rule 4).
CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_repo_ref_active
    ON draft_repository_bindings (repository_id, ref) WHERE released_at IS NULL;

-- A project's bindings, newest first — the history read.
CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_project_created
    ON draft_repository_bindings (project_id, created_at DESC);

-- One version's bindings, active and released.
CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_version_created
    ON draft_repository_bindings (version_id, created_at DESC);

-- Tenant-wide reads and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_draft_repository_bindings_tenant
    ON draft_repository_bindings (tenant_id);

COMMENT ON TABLE draft_repository_bindings IS
    'One draft (unpublished) project version bound to one repository provider, ref and source path, with the digest of the source it is synchronized with (GNC-2.1, #4737)';
COMMENT ON COLUMN draft_repository_bindings.tenant_id IS 'Owning tenant; a binding is never readable outside it';
COMMENT ON COLUMN draft_repository_bindings.project_id IS 'Project the bound version belongs to';
COMMENT ON COLUMN draft_repository_bindings.version_id IS 'The bound draft version (revision); at most one active binding each';
COMMENT ON COLUMN draft_repository_bindings.repository_id IS
    'Registered tenant repository the binding was authorized through; NULL once that registration is removed, which leaves the binding readable but unusable';
COMMENT ON COLUMN draft_repository_bindings.provider IS 'github | gitlab | bitbucket';
COMMENT ON COLUMN draft_repository_bindings.repo_full_name IS 'Lowercased owner/name, matched against a webhook delivery''s repository';
COMMENT ON COLUMN draft_repository_bindings.ref IS 'Branch or tag the draft is the review unit of';
COMMENT ON COLUMN draft_repository_bindings.path IS 'Path or glob selecting the source inside the repository; empty selects the whole tree';
COMMENT ON COLUMN draft_repository_bindings.commit_sha IS 'Commit the binding is currently synchronized with; moves only as a candidate is applied';
COMMENT ON COLUMN draft_repository_bindings.source_digest IS
    'Digest (sha256) of the selected source at commit_sha; the base GNC-2.3 diffs a ref update against';
COMMENT ON COLUMN draft_repository_bindings.synchronized_at IS 'When commit_sha/source_digest last moved';
COMMENT ON COLUMN draft_repository_bindings.released_at IS 'When the binding stopped being the draft''s active one; NULL while it is';
COMMENT ON COLUMN draft_repository_bindings.release_reason IS
    'replaced (re-bound elsewhere) | unbound (explicitly removed) | repository_removed';

-- ---------------------------------------------------------------------------------------------------
-- draft_binding_sync_candidates — one observed ref update awaiting a decision (rule 4).
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS draft_binding_sync_candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    binding_id UUID NOT NULL REFERENCES draft_repository_bindings(id) ON DELETE CASCADE,
    -- Carried rather than joined: the tenant's pending-candidate read is one index hit, and a
    -- tenant deletion removes the rows directly.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The ref the movement was seen on. Equal to the binding's ref; stored so a candidate still
    -- explains itself next to bindings of the same draft that named other refs.
    ref VARCHAR(255) NOT NULL
        CONSTRAINT draft_binding_sync_candidates_ref_check
        CHECK (length(btrim(ref)) > 0),

    -- Where the binding stood when the movement was observed, and where the ref moved to.
    from_commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT draft_binding_sync_candidates_from_commit_check
        CHECK (length(btrim(from_commit_sha)) > 0),
    from_digest VARCHAR(128) NOT NULL
        CONSTRAINT draft_binding_sync_candidates_from_digest_check
        CHECK (length(btrim(from_digest)) > 0),
    to_commit_sha VARCHAR(64) NOT NULL
        CONSTRAINT draft_binding_sync_candidates_to_commit_check
        CHECK (length(btrim(to_commit_sha)) > 0),
    -- NULL until the new source has actually been read; a webhook names a commit, not a document.
    to_digest VARCHAR(128),

    origin VARCHAR(16) NOT NULL
        CONSTRAINT draft_binding_sync_candidates_origin_check
        CHECK (origin IN ('webhook', 'manual', 'sweep')),
    -- The provider delivery that raised it, when one did; the redelivery idempotency key.
    delivery_id VARCHAR(255),

    -- Rule 5: the settled states.
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CONSTRAINT draft_binding_sync_candidates_status_check
        CHECK (status IN ('pending', 'applied', 'dismissed', 'superseded')),

    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detected_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolution_note TEXT,

    -- A pending candidate has nobody who resolved it, and a resolved one is not pending.
    CONSTRAINT draft_binding_sync_candidates_resolved_check
        CHECK ((status = 'pending') = (resolved_at IS NULL)),
    CONSTRAINT draft_binding_sync_candidates_resolver_check
        CHECK (resolved_at IS NOT NULL OR (resolved_by IS NULL AND resolution_note IS NULL))
);

-- Rule 4, first half: one outstanding candidate per (binding, target commit). A ten-commit push
-- that lands on one head raises one candidate; a redelivery of it raises none.
CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_binding_sync_candidates_pending
    ON draft_binding_sync_candidates (binding_id, to_commit_sha) WHERE status = 'pending';

-- Rule 4, second half: one candidate per provider delivery, so a redelivery cannot resurrect a
-- candidate somebody already dismissed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_binding_sync_candidates_delivery
    ON draft_binding_sync_candidates (binding_id, delivery_id) WHERE delivery_id IS NOT NULL;

-- One binding's candidates, newest first.
CREATE INDEX IF NOT EXISTS idx_draft_binding_sync_candidates_binding_detected
    ON draft_binding_sync_candidates (binding_id, detected_at DESC);

-- "What is outstanding in this tenant?" — the badge read and the tenant deletion path.
CREATE INDEX IF NOT EXISTS idx_draft_binding_sync_candidates_tenant_pending
    ON draft_binding_sync_candidates (tenant_id, detected_at DESC) WHERE status = 'pending';

COMMENT ON TABLE draft_binding_sync_candidates IS
    'One observed movement of a bound repository ref, awaiting an explicit decision; nothing about the draft changes until one is taken (GNC-2.1, #4737)';
COMMENT ON COLUMN draft_binding_sync_candidates.binding_id IS 'The binding whose ref moved';
COMMENT ON COLUMN draft_binding_sync_candidates.tenant_id IS 'Owning tenant; a candidate is never readable outside it';
COMMENT ON COLUMN draft_binding_sync_candidates.from_commit_sha IS 'The binding''s synchronized commit when the movement was observed';
COMMENT ON COLUMN draft_binding_sync_candidates.from_digest IS 'The binding''s source digest when the movement was observed';
COMMENT ON COLUMN draft_binding_sync_candidates.to_commit_sha IS 'The commit the ref now points at';
COMMENT ON COLUMN draft_binding_sync_candidates.to_digest IS
    'Digest of the selected source at to_commit_sha; NULL until that source has been read, because a delivery names a commit and not a document';
COMMENT ON COLUMN draft_binding_sync_candidates.origin IS 'webhook (a provider delivery) | manual (an explicit check) | sweep (the refresh cadence)';
COMMENT ON COLUMN draft_binding_sync_candidates.delivery_id IS 'Provider delivery id that raised it; the redelivery idempotency key';
COMMENT ON COLUMN draft_binding_sync_candidates.status IS
    'pending | applied (the draft is in sync with to_commit_sha) | dismissed | superseded (a newer candidate replaced it)';

-- ---------------------------------------------------------------------------------------------------
-- Rule 3 + rule 2: what a binding is never changes; a released binding changes at all.
--
-- Only the synchronized pair (commit_sha, source_digest, synchronized_at), the release columns, and
-- updated_at may move, and only while the binding is active. repository_id is allowed to go to NULL
-- — that is how ON DELETE SET NULL removes a de-registered repository, on active and released rows
-- alike.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.draft_repository_bindings_guard_identity()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.repo_full_name IS DISTINCT FROM OLD.repo_full_name
       OR NEW.repo_url IS DISTINCT FROM OLD.repo_url
       OR NEW.ref IS DISTINCT FROM OLD.ref
       OR NEW.path IS DISTINCT FROM OLD.path
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR (NEW.repository_id IS DISTINCT FROM OLD.repository_id AND NEW.repository_id IS NOT NULL) THEN
        RAISE EXCEPTION 'draft_repository_bindings: what a binding names never changes — release it and bind again'
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.released_at IS NOT NULL
       AND (NEW.commit_sha IS DISTINCT FROM OLD.commit_sha
            OR NEW.source_digest IS DISTINCT FROM OLD.source_digest
            OR NEW.synchronized_at IS DISTINCT FROM OLD.synchronized_at
            OR NEW.released_at IS DISTINCT FROM OLD.released_at
            OR NEW.release_reason IS DISTINCT FROM OLD.release_reason
            OR (NEW.released_by IS DISTINCT FROM OLD.released_by AND NEW.released_by IS NOT NULL)) THEN
        RAISE EXCEPTION 'draft_repository_bindings: a released binding is history and cannot be changed'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_repository_bindings_guard_identity ON draft_repository_bindings;
CREATE TRIGGER trg_draft_repository_bindings_guard_identity
    BEFORE UPDATE ON draft_repository_bindings
    FOR EACH ROW
    EXECUTE FUNCTION apiome.draft_repository_bindings_guard_identity();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: a candidate settles once.
--
-- Everything a candidate observed is fixed at detection; the only permitted change is pending ->
-- applied / dismissed / superseded, together with who resolved it, when, and why. A resolved row
-- never moves again — including back to pending.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.draft_binding_sync_candidates_guard_resolved()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.ref IS DISTINCT FROM OLD.ref
       OR NEW.from_commit_sha IS DISTINCT FROM OLD.from_commit_sha
       OR NEW.from_digest IS DISTINCT FROM OLD.from_digest
       OR NEW.to_commit_sha IS DISTINCT FROM OLD.to_commit_sha
       OR NEW.origin IS DISTINCT FROM OLD.origin
       OR NEW.delivery_id IS DISTINCT FROM OLD.delivery_id
       OR NEW.detected_at IS DISTINCT FROM OLD.detected_at
       OR (NEW.detected_by IS DISTINCT FROM OLD.detected_by AND NEW.detected_by IS NOT NULL) THEN
        RAISE EXCEPTION 'draft_binding_sync_candidates: what a candidate observed is fixed at detection'
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.status <> 'pending'
       AND (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.to_digest IS DISTINCT FROM OLD.to_digest
            OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at
            OR NEW.resolution_note IS DISTINCT FROM OLD.resolution_note
            OR (NEW.resolved_by IS DISTINCT FROM OLD.resolved_by AND NEW.resolved_by IS NOT NULL)) THEN
        RAISE EXCEPTION 'draft_binding_sync_candidates: a resolved candidate is history and cannot be changed'
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_draft_binding_sync_candidates_guard_resolved ON draft_binding_sync_candidates;
CREATE TRIGGER trg_draft_binding_sync_candidates_guard_resolved
    BEFORE UPDATE ON draft_binding_sync_candidates
    FOR EACH ROW
    EXECUTE FUNCTION apiome.draft_binding_sync_candidates_guard_resolved();
