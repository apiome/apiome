-- Comment threads & comments — COL-1.1 (#4513).
--
-- Discussion about a specification has had nowhere to live inside Apiome: a second designer who
-- wants to question a class, a property, a path, or an operation does it in Slack or email, and
-- the remark is lost to everyone who opens the element later. This migration adds the storage the
-- whole collaboration roadmap builds on — the Studio thread UI (COL-1.2), the Discussion panel
-- (COL-1.3), anchor resilience (COL-1.4), notification fan-out (COL-3.1), and review threads
-- (COL-2.1).
--
--   comment_threads — one conversation anchored to one element of one version of a project.
--   comments        — the Markdown replies in a thread, with the members each one mentions.
--
-- Five rules shape the schema:
--
--   1. **A thread anchors by stable element id, never by coordinates.** ``anchor_type`` names the
--      kind of element (class | property | path | operation | version) and ``anchor_id`` is that
--      element's primary key. Canvas positions move on every layout; a primary key does not, which
--      is exactly what COL-1.4's rename/move resilience depends on. The anchor is polymorphic, so
--      there is no foreign key to the element — the API proves the element exists in the thread's
--      version when the thread is opened, and COL-1.4 owns what happens when it later disappears.
--
--   2. **A version anchor is the thread's own version.** For ``anchor_type = 'version'`` the
--      anchor and ``version_id`` must be the same id, so "a thread about this version" has exactly
--      one spelling rather than two that list differently.
--
--   3. **Status is a closed vocabulary, and resolution is recorded.** ``status`` is ``open`` or
--      ``resolved``; a resolved thread carries when (and by whom) it was resolved, and an open one
--      carries neither — so a reopened thread cannot keep a stale resolution stamp. Both
--      vocabularies are CHECK constraints rather than ENUM types, matching the rest of the schema
--      and letting COL-1.4 widen ``status`` (``orphaned``) with a plain constraint swap.
--
--   4. **Mentions are resolved once, on the server, and stored.** ``comments.mentions`` holds the
--      user ids the ``@name`` tokens in ``body`` resolved to at write time. It is the source of
--      truth for notification fan-out (COL-3.1) and for the "mentions me" filter, so it is GIN
--      indexed and capped rather than re-derived from Markdown on every read.
--
--   5. **Scope never leaks across a tenant, and deletion follows ownership.** A thread carries its
--      tenant, project, and version and is removed with any of them; a comment is removed with its
--      thread. Deleting a *user* keeps what they wrote (``ON DELETE SET NULL``) — a discussion that
--      loses its middle is harder to follow than one with an anonymous participant.
--
-- There is deliberately **no new RBAC resource**: read access to a project grants commenting, and
-- editing or deleting a comment is limited to its author or a tenant administrator — both enforced
-- by apiome-rest (``app.comment_store``), neither expressible as a role grid.
--
-- Rollback notes (reverse carefully in shared environments):
--   DROP TABLE IF EXISTS apiome.comments;
--   DROP TABLE IF EXISTS apiome.comment_threads;

SET search_path TO apiome, public;

-- ---------------------------------------------------------------------------------------------------
-- comment_threads — one conversation anchored to one element of one version.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comment_threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Scope. All three are carried so the Discussion panel's project read and the Studio's
    -- per-version read each hit one index without a join through versions.
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,

    -- The element under discussion, by stable primary key (rule 1).
    anchor_type VARCHAR(16) NOT NULL
        CONSTRAINT comment_threads_anchor_type_check
            CHECK (anchor_type IN ('class', 'property', 'path', 'operation', 'version')),
    anchor_id UUID NOT NULL,

    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CONSTRAINT comment_threads_status_check CHECK (status IN ('open', 'resolved')),

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Moves on every reply and every resolve/reopen; the list read orders by it, so the thread
    -- somebody just answered rises to the top.
    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Rule 2: a version anchor is the thread's own version.
    CONSTRAINT comment_threads_version_anchor_check
        CHECK (anchor_type <> 'version' OR anchor_id = version_id),

    -- Rule 3: a resolved thread says when it was resolved; an open one does not.
    CONSTRAINT comment_threads_resolution_check
        CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
);

-- The Discussion panel's read: a project's threads, most recently active first.
CREATE INDEX IF NOT EXISTS idx_comment_threads_project_activity
    ON comment_threads (project_id, last_activity_at DESC);

-- The open/resolved filter over a project.
CREATE INDEX IF NOT EXISTS idx_comment_threads_project_status
    ON comment_threads (project_id, status);

-- The Studio's read: every thread on one element of one version (unresolved badges).
CREATE INDEX IF NOT EXISTS idx_comment_threads_version_anchor
    ON comment_threads (version_id, anchor_type, anchor_id);

-- Tenant-wide reads and tenant deletion.
CREATE INDEX IF NOT EXISTS idx_comment_threads_tenant
    ON comment_threads (tenant_id);

COMMENT ON TABLE comment_threads IS
    'A discussion anchored to one element (class, property, path, operation, or the version itself) of one project version (COL-1.1, #4513)';
COMMENT ON COLUMN comment_threads.tenant_id IS 'Owning tenant; a thread is never readable outside it';
COMMENT ON COLUMN comment_threads.project_id IS 'Project the discussed version belongs to';
COMMENT ON COLUMN comment_threads.version_id IS 'Version (revision) whose element the thread discusses';
COMMENT ON COLUMN comment_threads.anchor_type IS 'class | property | path | operation | version';
COMMENT ON COLUMN comment_threads.anchor_id IS
    'Primary key of the anchored element (classes, class_properties/properties, version_path, path_operation, or versions); a stable id, never canvas coordinates. Equals version_id for a version anchor';
COMMENT ON COLUMN comment_threads.status IS 'open | resolved';
COMMENT ON COLUMN comment_threads.resolved_by IS 'Who resolved the thread; NULL while it is open';
COMMENT ON COLUMN comment_threads.resolved_at IS 'When the thread was resolved; NULL exactly when it is open';
COMMENT ON COLUMN comment_threads.last_activity_at IS 'Latest reply or status change; the list read orders by it';

-- ---------------------------------------------------------------------------------------------------
-- comments — the Markdown replies in a thread.
-- ---------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    thread_id UUID NOT NULL REFERENCES comment_threads(id) ON DELETE CASCADE,
    author_id UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Markdown. A blank comment says nothing, and an unbounded one is a storage abuse vector; the
    -- API enforces the same bounds, this keeps them true for every writer.
    body TEXT NOT NULL
        CONSTRAINT comments_body_check CHECK (length(btrim(body)) > 0 AND length(body) <= 20000),

    -- Rule 4: user ids the body's @name tokens resolved to, server-side, at write time.
    mentions UUID[] NOT NULL DEFAULT ARRAY[]::UUID[]
        CONSTRAINT comments_mentions_cardinality_check CHECK (cardinality(mentions) <= 50),

    -- Set on every edit; NULL for a comment that was never edited.
    edited_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A thread's replies in the order they were written.
CREATE INDEX IF NOT EXISTS idx_comments_thread
    ON comments (thread_id, created_at);

-- The "mentions me" filter and COL-3.1's fan-out: array containment on the mentioned user.
CREATE INDEX IF NOT EXISTS idx_comments_mentions
    ON comments USING GIN (mentions);

-- A user's own comments.
CREATE INDEX IF NOT EXISTS idx_comments_author
    ON comments (author_id);

COMMENT ON TABLE comments IS 'One Markdown reply in a comment thread (COL-1.1, #4513)';
COMMENT ON COLUMN comments.thread_id IS 'Thread this comment belongs to; removed with it';
COMMENT ON COLUMN comments.author_id IS 'Who wrote the comment; NULL once that user is deleted';
COMMENT ON COLUMN comments.body IS 'Markdown text, 1-20000 characters';
COMMENT ON COLUMN comments.mentions IS
    'User ids the body''s @name tokens resolved to against tenant members, server-side at write time; source of truth for notification fan-out (COL-3.1)';
COMMENT ON COLUMN comments.edited_at IS 'Last edit time; NULL when never edited';
