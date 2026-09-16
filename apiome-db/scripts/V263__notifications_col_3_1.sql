-- Notification inbox & fan-out — COL-3.1 (#4521).
--
-- A mention, a review request, a decision, a resolved thread, or a publish is worthless if the
-- person concerned never learns about it. Until now Apiome had nowhere to put "this needs you":
-- the comment threads of COL-1.1 (#4513) and the reviews of COL-2.1 (#4517) could only be found by
-- opening the page they live on. This migration adds the storage the notification centre
-- (COL-3.2, #4522) reads, and the email (COL-3.3) and Slack/Teams (COL-3.4) workers will later fan
-- the same rows out to.
--
--   notifications — one row per recipient per event: "you were mentioned", "you were asked to
--                   review", "your review was decided", "a thread you were in was resolved",
--                   "a version you worked on was published".
--
-- Five rules shape the schema:
--
--   1. **One row per recipient, never one row per event.** Reading, counting, and marking read are
--      all per-user operations, so the inbox is stored per user. Resolving *which* users an event
--      concerns is apiome-rest's job (``app.notification_fanout``); this table only stores the
--      answer.
--
--   2. **The rows are written in the same transaction as the event that caused them.** apiome-rest
--      hands its drafts to the same accessor that writes the comment, the review decision, or the
--      publish, so a committed event and its inbox rows can never diverge — no queue, no worker, no
--      "the notification was lost because the process died after the commit".
--
--   3. **The type is a closed vocabulary, and the rest is payload.** ``type`` is one of five
--      strings a client branches on; ``payload`` is a JSON object holding what its deep link and
--      its sentence need (thread and comment ids, the review and its round, the anchor, an
--      excerpt). It is a CHECK constraint rather than an ENUM type, matching the rest of the schema,
--      so COL-3.3/3.4 can widen the vocabulary with a plain constraint swap.
--
--   4. **An inbox is capped, and the cap is the database's to keep.** A statement-level trigger
--      prunes everything past the newest ``retention_cap`` rows of each user an insert touched, so
--      the bound holds for every writer — including a future email worker or a backfill script —
--      rather than depending on each one to remember. Pruning is by age within the user's own
--      inbox and does **not** spare unread rows: an inbox nobody has read for five hundred events
--      is not an inbox, and a count that can grow without bound is a denial-of-service surface.
--
--   5. **Marking read is the only mutation.** A trigger refuses every other change to a stored
--      row, so "the notification you clicked is the notification that was written" is a schema
--      fact rather than a convention the API is trusted to keep.
--
-- Scope and lifetime follow ownership: a row is removed with its tenant, its recipient, and the
-- project or version it points at — a notification whose destination no longer exists is a dead
-- link, not history. The *actor* is the exception (``ON DELETE SET NULL``): "somebody mentioned
-- you" survives that somebody leaving, exactly as their comment does.
--
-- There is deliberately **no new RBAC resource**: an inbox is the caller's own, so apiome-rest
-- scopes every read and write to the authenticated user and no role grid can express it. Per-type
-- delivery preferences (COL-3.2) are **not** stored here yet — nothing is muted at write time.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.notifications;
--   DROP FUNCTION IF EXISTS apiome.notifications_enforce_retention();
--   DROP FUNCTION IF EXISTS apiome.notifications_guard_immutable();

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- notifications — one recipient's copy of one event.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Rule 1: whose inbox this row is in, and the tenant it belongs to. Both are carried so the
    -- unread count and the inbox list each hit one index without a join.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Rule 3: the closed vocabulary, mirrored by apiome-rest ``app.notifications.NOTIFICATION_TYPES``.
    type VARCHAR(32) NOT NULL
        CONSTRAINT notifications_type_check
            CHECK (type IN (
                'mention',
                'review_requested',
                'review_decision',
                'thread_resolved',
                'version_published'
            )),

    -- What the notification's sentence and its deep link need, as a JSON object. Never credentials,
    -- never a whole spec — ids, labels, and a short excerpt.
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT notifications_payload_object_check CHECK (jsonb_typeof(payload) = 'object'),

    -- Who caused the event. Kept as a column rather than in the payload so their display name is
    -- read fresh at list time and never goes stale in stored JSON.
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Where the notification points. A row dies with its destination (see the header).
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID REFERENCES versions(id) ON DELETE CASCADE,

    -- NULL means unread; the unread badge counts exactly these.
    read_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The inbox read ("my notifications, newest first") and the retention trigger's ranking.
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications (user_id, created_at DESC, id DESC);

-- The bell badge: unread rows of one user, countable per type without touching read ones.
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications (user_id, type) WHERE read_at IS NULL;

-- Tenant-wide reads and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_notifications_tenant
    ON notifications (tenant_id);

COMMENT ON TABLE notifications IS
    'One recipient''s copy of one collaboration event (mention, review request, decision, thread resolution, publish), written in the same transaction as the event (COL-3.1, #4521)';
COMMENT ON COLUMN notifications.tenant_id IS 'Owning tenant; an inbox row is never readable outside it';
COMMENT ON COLUMN notifications.user_id IS 'The recipient; the row is their copy and dies with their account';
COMMENT ON COLUMN notifications.type IS
    'mention | review_requested | review_decision | thread_resolved | version_published';
COMMENT ON COLUMN notifications.payload IS
    'JSON object with what the notification''s sentence and deep link need (thread/comment ids, review id and round, anchor, excerpt); never credentials or whole documents';
COMMENT ON COLUMN notifications.actor_id IS 'Who caused the event; NULL once that user is deleted';
COMMENT ON COLUMN notifications.project_id IS 'Project the notification points at; the row is removed with it';
COMMENT ON COLUMN notifications.version_id IS 'Version the notification points at; the row is removed with it';
COMMENT ON COLUMN notifications.read_at IS 'When the recipient read it; NULL exactly while unread';

-- ---------------------------------------------------------------------------------------------------
-- Rule 4: an inbox keeps only its newest rows.
--
-- Statement-level with a transition table, so one fan-out of fifty recipients prunes once rather
-- than fifty times. Only the users the statement actually touched are ranked.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.notifications_enforce_retention()
RETURNS TRIGGER AS $$
DECLARE
    -- Newest rows kept per user. Mirrored by apiome-rest ``app.notifications.RETENTION_PER_USER``;
    -- change both together or the API will advertise a cap the database does not keep.
    retention_cap CONSTANT INTEGER := 500;
BEGIN
    DELETE FROM apiome.notifications victim
     WHERE victim.id IN (
        SELECT ranked.id
          FROM (
                SELECT n.id,
                       row_number() OVER (
                           PARTITION BY n.user_id ORDER BY n.created_at DESC, n.id DESC
                       ) AS position
                  FROM apiome.notifications n
                 WHERE n.user_id IN (SELECT DISTINCT i.user_id FROM inserted i)
          ) ranked
         WHERE ranked.position > retention_cap
     );
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notifications_enforce_retention ON notifications;
CREATE TRIGGER trg_notifications_enforce_retention
    AFTER INSERT ON notifications
    REFERENCING NEW TABLE AS inserted
    FOR EACH STATEMENT
    EXECUTE FUNCTION apiome.notifications_enforce_retention();

-- ---------------------------------------------------------------------------------------------------
-- Rule 5: read_at is the only thing that moves.
--
-- The one exception is actor_id going to NULL, which is how ON DELETE SET NULL removes a user who
-- has left.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.notifications_guard_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.type IS DISTINCT FROM OLD.type
       OR NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR (NEW.actor_id IS DISTINCT FROM OLD.actor_id AND NEW.actor_id IS NOT NULL) THEN
        RAISE EXCEPTION 'notifications: a notification is what it was written as; only read_at may change'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notifications_guard_immutable ON notifications;
CREATE TRIGGER trg_notifications_guard_immutable
    BEFORE UPDATE ON notifications
    FOR EACH ROW
    EXECUTE FUNCTION apiome.notifications_guard_immutable();
