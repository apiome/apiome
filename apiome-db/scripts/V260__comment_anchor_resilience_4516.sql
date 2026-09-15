-- Comment anchor resilience — COL-1.4 (#4516).
--
-- V259 (COL-1.1) anchors a comment thread to an element by the element's primary key. That already
-- makes a thread survive a **rename or a move**: both are an UPDATE of the element row keyed by its
-- id, so the anchor never changes and nothing here fires. What V259 left open is **deletion** — a
-- thread whose element is gone would point at nothing and silently disappear from every surface that
-- draws threads on elements. This migration makes deletion explicit:
--
--   1. **A deleted element orphans its threads.** ``status`` gains ``orphaned``. The thread keeps its
--      comments, its old ``anchor_type``/``anchor_id`` (the id of the element that was deleted), and
--      any resolution stamp it had, so relinking a resolved thread brings it back resolved.
--
--   2. **The last-known label is captured at the moment of deletion.** ``anchor_label`` holds the
--      element's human-readable name as it was when it was deleted (``Customer``,
--      ``Customer.email``, ``/customers/{id}``, ``GET /customers/{id}``), read from the row being
--      deleted, so the Discussion panel can still say what the thread was about. ``orphaned_at``
--      records when. Both are set exactly while a thread is orphaned; relinking clears them.
--
--   3. **Orphaning is a database trigger, not a service hook.** Elements are deleted by many writers:
--      the class/property/path/operation DELETE routes, the whole-version rewrite that applies a
--      source change (soft-deletes every class, delete-and-recreates every path), and foreign-key
--      cascades (a path takes its operations, a class takes its properties). A trigger sees every one
--      of them — the API, a migration, or a psql session — and reads the exact row being removed.
--      Soft deletes (``classes.deleted_at``, ``properties.deleted_at``) orphan on the transition to
--      deleted; hard deletes orphan BEFORE the row goes, while its label and children are still there.
--
--   4. **A version anchor is never orphaned.** A thread about a version is removed with the version
--      (V259's cascade); there is no element left to relink to.
--
-- Relinking (re-attaching an orphaned thread to another element of its version) is an API action:
-- apiome-rest proves the target exists and moves the anchor in one guarded UPDATE.
--
-- Rollback notes (reverse carefully in shared environments; orphaned threads must first be relinked
-- or deleted, or the restored status CHECK will refuse them):
--   DROP TRIGGER IF EXISTS trg_classes_comment_orphan_soft_delete ON apiome.classes;
--   DROP TRIGGER IF EXISTS trg_classes_comment_orphan_delete ON apiome.classes;
--   DROP TRIGGER IF EXISTS trg_class_properties_comment_orphan_delete ON apiome.class_properties;
--   DROP TRIGGER IF EXISTS trg_properties_comment_orphan_soft_delete ON apiome.properties;
--   DROP TRIGGER IF EXISTS trg_properties_comment_orphan_delete ON apiome.properties;
--   DROP TRIGGER IF EXISTS trg_version_path_comment_orphan_delete ON apiome.version_path;
--   DROP TRIGGER IF EXISTS trg_path_operation_comment_orphan_delete ON apiome.path_operation;
--   DROP FUNCTION IF EXISTS apiome.comment_threads_orphan_class();
--   DROP FUNCTION IF EXISTS apiome.comment_threads_orphan_class_property();
--   DROP FUNCTION IF EXISTS apiome.comment_threads_orphan_property();
--   DROP FUNCTION IF EXISTS apiome.comment_threads_orphan_path();
--   DROP FUNCTION IF EXISTS apiome.comment_threads_orphan_operation();
--   DROP FUNCTION IF EXISTS apiome.orphan_comment_threads(VARCHAR, UUID, TEXT);
--   DROP INDEX IF EXISTS apiome.idx_comment_threads_live_anchor;
--   ALTER TABLE apiome.comment_threads DROP CONSTRAINT IF EXISTS comment_threads_orphan_check;
--   (restore V259's comment_threads_status_check and comment_threads_resolution_check)
--   ALTER TABLE apiome.comment_threads DROP COLUMN IF EXISTS anchor_label, DROP COLUMN IF EXISTS orphaned_at;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- 1. Orphan state on comment_threads.
-- ---------------------------------------------------------------------------------------------------
ALTER TABLE comment_threads ADD COLUMN IF NOT EXISTS anchor_label VARCHAR(512);
ALTER TABLE comment_threads ADD COLUMN IF NOT EXISTS orphaned_at TIMESTAMP WITH TIME ZONE;

-- Widen the status vocabulary (V259 rule 3 planned this as a plain constraint swap).
ALTER TABLE comment_threads DROP CONSTRAINT IF EXISTS comment_threads_status_check;
ALTER TABLE comment_threads ADD CONSTRAINT comment_threads_status_check
    CHECK (status IN ('open', 'resolved', 'orphaned'));

-- An orphaned thread keeps whatever resolution it had, so relinking can restore it; an open or a
-- resolved thread still carries resolved_at exactly when resolved.
ALTER TABLE comment_threads DROP CONSTRAINT IF EXISTS comment_threads_resolution_check;
ALTER TABLE comment_threads ADD CONSTRAINT comment_threads_resolution_check
    CHECK (status = 'orphaned' OR (status = 'resolved') = (resolved_at IS NOT NULL));

-- Rules 2 and 4: an orphaned thread says when it was orphaned and what it was about, a live thread
-- carries neither, and a version anchor is never orphaned.
ALTER TABLE comment_threads DROP CONSTRAINT IF EXISTS comment_threads_orphan_check;
ALTER TABLE comment_threads ADD CONSTRAINT comment_threads_orphan_check
    CHECK (
        (status = 'orphaned') = (orphaned_at IS NOT NULL)
        AND (status = 'orphaned') = (anchor_label IS NOT NULL)
        AND (status <> 'orphaned' OR anchor_type <> 'version')
    );

-- The triggers' lookup: live threads on one element id, whatever its version. Partial, because an
-- orphaned thread is never orphaned twice and a delete should not scan the ones that already are.
CREATE INDEX IF NOT EXISTS idx_comment_threads_live_anchor
    ON comment_threads (anchor_id) WHERE status <> 'orphaned';

COMMENT ON COLUMN comment_threads.status IS
    'open | resolved | orphaned (the anchored element was deleted; relink to re-attach)';
COMMENT ON COLUMN comment_threads.anchor_label IS
    'Last-known human-readable label of the deleted element (e.g. Customer.email, GET /customers), captured when the thread was orphaned; NULL exactly when not orphaned';
COMMENT ON COLUMN comment_threads.orphaned_at IS
    'When the anchored element was deleted; NULL exactly when the thread is not orphaned';

-- ---------------------------------------------------------------------------------------------------
-- 2. The one orphaning statement every trigger calls.
-- ---------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION apiome.orphan_comment_threads(
    p_anchor_type VARCHAR,
    p_anchor_id UUID,
    p_label TEXT
)
RETURNS INTEGER AS $$
DECLARE
    v_orphaned INTEGER;
BEGIN
    UPDATE apiome.comment_threads
    SET status = 'orphaned',
        orphaned_at = CURRENT_TIMESTAMP,
        -- Never NULL (the orphan CHECK needs a label): fall back to the element kind and id.
        anchor_label = LEFT(
            COALESCE(NULLIF(btrim(p_label), ''), p_anchor_type || ' ' || p_anchor_id::text), 512
        ),
        updated_at = CURRENT_TIMESTAMP,
        -- A status change is activity: the orphaned thread rises to the top of the list.
        last_activity_at = CURRENT_TIMESTAMP
    WHERE anchor_type = p_anchor_type
      AND anchor_id = p_anchor_id
      AND status <> 'orphaned';
    GET DIAGNOSTICS v_orphaned = ROW_COUNT;
    RETURN v_orphaned;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apiome.orphan_comment_threads(VARCHAR, UUID, TEXT) IS
    'Marks every live comment thread on one element orphaned, recording the element''s last-known label (COL-1.4, #4516). Returns how many threads it orphaned.';

-- ---------------------------------------------------------------------------------------------------
-- 3. Per-table triggers.
-- ---------------------------------------------------------------------------------------------------

-- A class: its own threads, and the threads on each of its properties (labelled Class.property).
-- Fires on the soft delete every writer uses, and on a hard delete of a class that was still live.
CREATE OR REPLACE FUNCTION apiome.comment_threads_orphan_class()
RETURNS TRIGGER AS $$
DECLARE
    v_id UUID;
    v_name TEXT;
    v_version_id UUID;
    v_property RECORD;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_id := OLD.id; v_name := OLD.name; v_version_id := OLD.version_id;
    ELSE
        v_id := NEW.id; v_name := NEW.name; v_version_id := NEW.version_id;
    END IF;

    -- A whole-version rewrite soft-deletes every class; a version nobody has commented on costs one
    -- index probe per class instead of one per property.
    IF EXISTS (
        SELECT 1 FROM apiome.comment_threads t
        WHERE t.version_id = v_version_id AND t.status <> 'orphaned'
    ) THEN
        PERFORM apiome.orphan_comment_threads('class', v_id, v_name);
        FOR v_property IN
            SELECT cp.id, cp.name FROM apiome.class_properties cp WHERE cp.class_id = v_id
        LOOP
            PERFORM apiome.orphan_comment_threads('property', v_property.id, v_name || '.' || v_property.name);
        END LOOP;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_classes_comment_orphan_soft_delete ON apiome.classes;
CREATE TRIGGER trg_classes_comment_orphan_soft_delete
    AFTER UPDATE OF deleted_at ON apiome.classes
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
    EXECUTE FUNCTION apiome.comment_threads_orphan_class();

DROP TRIGGER IF EXISTS trg_classes_comment_orphan_delete ON apiome.classes;
CREATE TRIGGER trg_classes_comment_orphan_delete
    BEFORE DELETE ON apiome.classes
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL)
    EXECUTE FUNCTION apiome.comment_threads_orphan_class();

-- A property on a class (hard delete, including a nested property removed with its parent).
CREATE OR REPLACE FUNCTION apiome.comment_threads_orphan_class_property()
RETURNS TRIGGER AS $$
DECLARE
    v_class_name TEXT;
BEGIN
    -- The owning class may already be gone when this runs as part of a class's own cascade; its
    -- trigger has then orphaned these threads with the full label, and this call finds nothing.
    SELECT c.name INTO v_class_name FROM apiome.classes c WHERE c.id = OLD.class_id;
    PERFORM apiome.orphan_comment_threads('property', OLD.id, COALESCE(v_class_name || '.', '') || OLD.name);
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_class_properties_comment_orphan_delete ON apiome.class_properties;
CREATE TRIGGER trg_class_properties_comment_orphan_delete
    BEFORE DELETE ON apiome.class_properties
    FOR EACH ROW
    EXECUTE FUNCTION apiome.comment_threads_orphan_class_property();

-- A property in the project's library (soft delete, or a hard delete of a live one).
CREATE OR REPLACE FUNCTION apiome.comment_threads_orphan_property()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM apiome.orphan_comment_threads('property', OLD.id, OLD.name);
        RETURN OLD;
    END IF;
    PERFORM apiome.orphan_comment_threads('property', NEW.id, NEW.name);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_properties_comment_orphan_soft_delete ON apiome.properties;
CREATE TRIGGER trg_properties_comment_orphan_soft_delete
    AFTER UPDATE OF deleted_at ON apiome.properties
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
    EXECUTE FUNCTION apiome.comment_threads_orphan_property();

DROP TRIGGER IF EXISTS trg_properties_comment_orphan_delete ON apiome.properties;
CREATE TRIGGER trg_properties_comment_orphan_delete
    BEFORE DELETE ON apiome.properties
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL)
    EXECUTE FUNCTION apiome.comment_threads_orphan_property();

-- A path: its own threads, and the threads on each of its operations (labelled METHOD /path) while
-- they are still readable — the cascade removes the operations right after.
CREATE OR REPLACE FUNCTION apiome.comment_threads_orphan_path()
RETURNS TRIGGER AS $$
DECLARE
    v_operation RECORD;
BEGIN
    IF EXISTS (
        SELECT 1 FROM apiome.comment_threads t
        WHERE t.version_id = OLD.version_id AND t.status <> 'orphaned'
    ) THEN
        PERFORM apiome.orphan_comment_threads('path', OLD.id, OLD.pathname);
        FOR v_operation IN
            SELECT po.id, po.operation FROM apiome.path_operation po WHERE po.version_path_id = OLD.id
        LOOP
            PERFORM apiome.orphan_comment_threads(
                'operation', v_operation.id, upper(v_operation.operation) || ' ' || OLD.pathname
            );
        END LOOP;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_version_path_comment_orphan_delete ON apiome.version_path;
CREATE TRIGGER trg_version_path_comment_orphan_delete
    BEFORE DELETE ON apiome.version_path
    FOR EACH ROW
    EXECUTE FUNCTION apiome.comment_threads_orphan_path();

-- An operation deleted on its own.
CREATE OR REPLACE FUNCTION apiome.comment_threads_orphan_operation()
RETURNS TRIGGER AS $$
DECLARE
    v_pathname TEXT;
BEGIN
    SELECT vp.pathname INTO v_pathname FROM apiome.version_path vp WHERE vp.id = OLD.version_path_id;
    PERFORM apiome.orphan_comment_threads(
        'operation', OLD.id, upper(OLD.operation) || COALESCE(' ' || v_pathname, '')
    );
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_path_operation_comment_orphan_delete ON apiome.path_operation;
CREATE TRIGGER trg_path_operation_comment_orphan_delete
    BEFORE DELETE ON apiome.path_operation
    FOR EACH ROW
    EXECUTE FUNCTION apiome.comment_threads_orphan_operation();

COMMENT ON FUNCTION apiome.comment_threads_orphan_class() IS
    'Orphans comment threads on a deleted class and on its properties (COL-1.4, #4516)';
COMMENT ON FUNCTION apiome.comment_threads_orphan_class_property() IS
    'Orphans comment threads on a deleted class property (COL-1.4, #4516)';
COMMENT ON FUNCTION apiome.comment_threads_orphan_property() IS
    'Orphans comment threads on a deleted library property (COL-1.4, #4516)';
COMMENT ON FUNCTION apiome.comment_threads_orphan_path() IS
    'Orphans comment threads on a deleted path and on its operations (COL-1.4, #4516)';
COMMENT ON FUNCTION apiome.comment_threads_orphan_operation() IS
    'Orphans comment threads on a deleted operation (COL-1.4, #4516)';
