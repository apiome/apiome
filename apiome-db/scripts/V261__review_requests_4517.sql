-- Review requests & decisions — COL-2.1 (#4517).
--
-- "Is this version OK to publish?" has been asked in Slack screenshots, leaving nothing behind for
-- governance or audit. This migration adds the record: a draft version can be sent for review to
-- named reviewers, each reviewer records a decision, and the whole history of who approved or
-- requested changes — and on which content — stays queryable after the fact. It is the base for
-- the review page (COL-2.2), the approval publish gate (COL-2.3), review status surfaces (COL-2.4),
-- and review notifications (COL-3.1).
--
--   reviews          — one request for review of one version, with its current state and round.
--   review_reviewers — one reviewer's decision in one round of a review.
--
-- Six rules shape the schema:
--
--   1. **``draft`` is not a stored state.** A version without an open review is a draft for review
--      purposes. A review row starts ``in_review`` and moves to ``approved`` or
--      ``changes_requested``; the transitions themselves are enforced by apiome-rest
--      (``app.review_lifecycle``), as the ticket asks.
--
--   2. **One open review per version.** A partial unique index allows any number of closed
--      (withdrawn) reviews but only one whose ``closed_at`` is NULL.
--
--   3. **A review is requested in rounds.** ``reviews.round`` is the current round. A re-request —
--      only allowed once the spec has changed — starts the next round with fresh ``pending`` rows,
--      so a stale approval can never carry over to changed content. ``spec_fingerprint`` records
--      the content the current round is judging (a hash of the rebuilt OpenAPI document).
--
--   4. **Decisions are immutable history.** A reviewer row goes from ``pending`` to a decision
--      exactly once, and only on the current round of an open review that is ``in_review``. A
--      trigger refuses every other change to a decision, whichever writer attempts it. Rows of an
--      earlier round are never rewritten; a reviewer who had not decided before a re-request keeps
--      a ``pending`` row in that round, and the round number says it was superseded.
--
--   5. **A closed review is frozen.** Withdrawing stamps ``closed_at``; after that a trigger
--      refuses changes to the review's state, round, fingerprint, or closure.
--
--   6. **Scope never leaks across a tenant, and history survives its people.** A review carries its
--      tenant, project, and version and is removed with any of them; reviewer rows are removed
--      with their review. Deleting a *user* keeps the decisions they recorded
--      (``ON DELETE SET NULL``).
--
-- Every transition and decision is also written to ``workflow_audit`` (``review.*`` actions) by
-- apiome-rest, in the same transaction as the change it records.
--
-- There is deliberately **no new RBAC resource**: requesting, re-requesting, and withdrawing need
-- ``versions:edit``; recording a decision needs ``projects:view`` and an assignment as reviewer —
-- which a role grid cannot express, so apiome-rest (``app.review_store``) enforces it.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.review_reviewers;
--   DROP TABLE IF EXISTS apiome.reviews;
--   DROP FUNCTION IF EXISTS apiome.review_reviewers_guard_decision();
--   DROP FUNCTION IF EXISTS apiome.reviews_guard_closed();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- reviews — one request for review of one version.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope, carried so a project's review list and a version's review status each hit one index.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Rule 1: the stored states. ``draft`` is the absence of an open review.
    state VARCHAR(24) NOT NULL DEFAULT 'in_review'
        CONSTRAINT reviews_state_check CHECK (state IN ('in_review', 'approved', 'changes_requested')),

    -- Rule 3: the current round, and the content it judges.
    round INTEGER NOT NULL DEFAULT 1
        CONSTRAINT reviews_round_check CHECK (round >= 1),
    spec_fingerprint VARCHAR(128) NOT NULL
        CONSTRAINT reviews_spec_fingerprint_check CHECK (length(btrim(spec_fingerprint)) > 0),

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Moves on every request, re-request, decision, and withdrawal; the list read orders by it.
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Set when the review is withdrawn; NULL while it is open.
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by UUID REFERENCES users(id) ON DELETE SET NULL,

    -- An open review has nobody who closed it.
    CONSTRAINT reviews_closed_by_check CHECK (closed_at IS NOT NULL OR closed_by IS NULL)
);

-- Rule 2: at most one open review per version.
CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_open_version
    ON reviews (version_id) WHERE closed_at IS NULL;

-- A project's reviews, most recently active first.
CREATE INDEX IF NOT EXISTS idx_reviews_project_updated
    ON reviews (project_id, updated_at DESC);

-- A version's reviews, open and closed.
CREATE INDEX IF NOT EXISTS idx_reviews_version_created
    ON reviews (version_id, created_at DESC);

-- Tenant-wide reads and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_reviews_tenant
    ON reviews (tenant_id);

COMMENT ON TABLE reviews IS
    'A request for review of one draft (unpublished) project version, decided by named reviewers in rounds (COL-2.1, #4517)';
COMMENT ON COLUMN reviews.tenant_id IS 'Owning tenant; a review is never readable outside it';
COMMENT ON COLUMN reviews.project_id IS 'Project the reviewed version belongs to';
COMMENT ON COLUMN reviews.version_id IS 'Version (revision) under review';
COMMENT ON COLUMN reviews.requested_by IS 'Who requested the review; NULL once that user is deleted';
COMMENT ON COLUMN reviews.state IS
    'in_review | approved | changes_requested. A version with no open review is a draft; transitions are enforced by apiome-rest';
COMMENT ON COLUMN reviews.round IS
    'Current round; each re-request after a spec change starts the next one with fresh pending reviewer rows';
COMMENT ON COLUMN reviews.spec_fingerprint IS
    'Fingerprint (sha256 of the rebuilt OpenAPI document) of the content the current round judges';
COMMENT ON COLUMN reviews.updated_at IS 'Latest request, re-request, decision, or withdrawal; the list read orders by it';
COMMENT ON COLUMN reviews.closed_at IS 'When the review was withdrawn; NULL while it is open. A closed review is frozen';
COMMENT ON COLUMN reviews.closed_by IS 'Who withdrew the review; NULL while it is open';

-- ---------------------------------------------------------------------------------------------------
-- review_reviewers — one reviewer's decision in one round.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_reviewers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    round INTEGER NOT NULL
        CONSTRAINT review_reviewers_round_check CHECK (round >= 1),

    -- Rule 6: a deleted user's decisions stay, without their id.
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,

    decision VARCHAR(24) NOT NULL DEFAULT 'pending'
        CONSTRAINT review_reviewers_decision_check
            CHECK (decision IN ('approve', 'request_changes', 'pending')),

    -- An optional explanation, written with the decision. The API enforces the same bound.
    note TEXT
        CONSTRAINT review_reviewers_note_check CHECK (note IS NULL OR length(note) <= 5000),

    decided_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- A decided row says when it was decided; a pending one does not, and carries no note.
    CONSTRAINT review_reviewers_decided_check CHECK ((decision = 'pending') = (decided_at IS NULL)),
    CONSTRAINT review_reviewers_pending_note_check CHECK (decision <> 'pending' OR note IS NULL),

    -- A reviewer appears once per round.
    CONSTRAINT review_reviewers_round_user_key UNIQUE (review_id, round, user_id)
);

-- A review's rounds, in order.
CREATE INDEX IF NOT EXISTS idx_review_reviewers_review_round
    ON review_reviewers (review_id, round);

-- "Reviews waiting on me" (review status surfaces and notifications).
CREATE INDEX IF NOT EXISTS idx_review_reviewers_user_pending
    ON review_reviewers (user_id) WHERE decision = 'pending';

COMMENT ON TABLE review_reviewers IS
    'One reviewer''s decision in one round of a review; decisions are immutable history (COL-2.1, #4517)';
COMMENT ON COLUMN review_reviewers.review_id IS 'Review this decision belongs to; removed with it';
COMMENT ON COLUMN review_reviewers.round IS 'Round of the review this row was created for; never changes';
COMMENT ON COLUMN review_reviewers.user_id IS 'The reviewer; NULL once that user is deleted';
COMMENT ON COLUMN review_reviewers.decision IS
    'approve | request_changes | pending. Set once from pending, on the current round of an open review in review';
COMMENT ON COLUMN review_reviewers.note IS 'Optional explanation recorded with the decision, up to 5000 characters';
COMMENT ON COLUMN review_reviewers.decided_at IS 'When the decision was recorded; NULL exactly while pending';

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: a recorded decision never changes.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.review_reviewers_guard_decision()
RETURNS TRIGGER AS $$
DECLARE
    parent_state VARCHAR(24);
    parent_round INTEGER;
    parent_closed_at TIMESTAMP WITH TIME ZONE;
BEGIN
    -- Which review, which round, and which reviewer a row is for never change. The one exception
    -- is the user id going to NULL, which is how ON DELETE SET NULL removes a deleted user.
    IF NEW.review_id IS DISTINCT FROM OLD.review_id
       OR NEW.round IS DISTINCT FROM OLD.round
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR (NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL) THEN
        RAISE EXCEPTION 'review_reviewers: a reviewer row keeps its review, round, reviewer, and creation time'
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.decision <> 'pending' THEN
        IF NEW.decision IS DISTINCT FROM OLD.decision
           OR NEW.note IS DISTINCT FROM OLD.note
           OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
            RAISE EXCEPTION 'review_reviewers: a recorded decision is immutable history; re-request the review to collect a new one'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.decision <> 'pending' THEN
        SELECT r.state, r.round, r.closed_at
          INTO parent_state, parent_round, parent_closed_at
          FROM apiome.reviews r
         WHERE r.id = NEW.review_id;
        IF parent_closed_at IS NOT NULL OR parent_state <> 'in_review' OR parent_round <> NEW.round THEN
            RAISE EXCEPTION 'review_reviewers: a decision is recorded only on the current round of an open review that is in review'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_review_reviewers_guard_decision ON review_reviewers;
CREATE TRIGGER trg_review_reviewers_guard_decision
    BEFORE UPDATE ON review_reviewers
    FOR EACH ROW
    EXECUTE FUNCTION apiome.review_reviewers_guard_decision();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: a closed review is frozen.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.reviews_guard_closed()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.closed_at IS NOT NULL
       AND (NEW.state IS DISTINCT FROM OLD.state
            OR NEW.round IS DISTINCT FROM OLD.round
            OR NEW.spec_fingerprint IS DISTINCT FROM OLD.spec_fingerprint
            OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
            OR NEW.version_id IS DISTINCT FROM OLD.version_id) THEN
        RAISE EXCEPTION 'reviews: a withdrawn review is closed history; request a new review instead'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_reviews_guard_closed ON reviews;
CREATE TRIGGER trg_reviews_guard_closed
    BEFORE UPDATE ON reviews
    FOR EACH ROW
    EXECUTE FUNCTION apiome.reviews_guard_closed();
