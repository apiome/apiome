-- Per-user "changed since last view" seen-markers (#4640, V2-MCP-30.5 / MCAT-16.5).
--
-- Problem: the catalog grid can hint that an endpoint's surface "changed since your last visit"
-- (MCAT-10.8), but that hint is browser-local (localStorage) and there is no per-user, per-endpoint
-- record of *which* version a user last saw — so the Insight tab cannot summarize what actually
-- changed (and how breaking it is) since then.
--
-- Solution: a lightweight seen-marker keyed on (user, endpoint) that remembers the version snapshot
-- the user last viewed. The "changed since last view" digest diffs that remembered snapshot against
-- the endpoint's current version; the marker is advanced to the current version when the user views
-- the endpoint. One row per (user, endpoint) — `seen_at` is the last-viewed time (advanced on each
-- view via upsert), `created_at` the first-viewed time.
--
-- `last_seen_version_id` is a *soft pointer*: ON DELETE SET NULL (mirroring
-- `mcp_endpoints.current_version_id` and `mcp_test_invocations.version_id`) so that if the pointed-at
-- snapshot is ever pruned, the marker survives with a NULL pointer and the endpoint simply reads as
-- "new to you" again — never a dangling FK or a lost row. The (user, endpoint) FKs cascade: a marker
-- is meaningless once its user or endpoint is gone, and a tenant/endpoint teardown must be able to
-- reap it.
--
-- Rollback notes: purely additive. To roll back:
--   DROP TABLE IF EXISTS apiome.mcp_endpoint_views;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS mcp_endpoint_views (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The user whose "last seen" this marker records; reaped when the user is deleted.
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- The endpoint the marker is for; reaped when the endpoint (or its tenant) is hard-deleted.
    endpoint_id UUID NOT NULL REFERENCES mcp_endpoints(id) ON DELETE CASCADE,

    -- The snapshot the user last saw. Soft pointer: SET NULL when that version is pruned, so the
    -- marker survives (the endpoint then reads as "new to you") rather than dangling or cascading.
    last_seen_version_id UUID REFERENCES mcp_endpoint_versions(id) ON DELETE SET NULL,

    -- Last-viewed time — advanced to CURRENT_TIMESTAMP on each view (the upsert's ON CONFLICT path).
    seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- First-viewed time — set once on insert and never moved (standard house-style audit column).
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Exactly one marker per (user, endpoint); the upsert advances this row in place. The btree
    -- backing this constraint also serves the per-(user, endpoint) point lookup the digest runs.
    CONSTRAINT mcp_endpoint_views_user_endpoint_unique UNIQUE (user_id, endpoint_id)
);

-- Reverse lookup: every user who has seen a given endpoint (e.g. for endpoint teardown / analytics).
CREATE INDEX IF NOT EXISTS idx_mcp_endpoint_views_endpoint
    ON mcp_endpoint_views(endpoint_id);

COMMENT ON TABLE mcp_endpoint_views IS 'Per-user seen-marker (last-viewed version per endpoint) backing the "changed since last view" digest; upserted, one row per (user, endpoint) (#4640, V2-MCP-30.5)';
COMMENT ON COLUMN mcp_endpoint_views.id IS 'Unique identifier for the seen-marker row';
COMMENT ON COLUMN mcp_endpoint_views.user_id IS 'The user whose last-seen version this records; cascade-deleted with the user';
COMMENT ON COLUMN mcp_endpoint_views.endpoint_id IS 'The endpoint the marker is for; cascade-deleted with the endpoint/tenant';
COMMENT ON COLUMN mcp_endpoint_views.last_seen_version_id IS 'Snapshot the user last saw; SET NULL when the version is pruned (endpoint then reads as new-to-you)';
COMMENT ON COLUMN mcp_endpoint_views.seen_at IS 'When the user last viewed the endpoint; advanced on each view via upsert';
COMMENT ON COLUMN mcp_endpoint_views.created_at IS 'When the user first viewed the endpoint (marker row first created)';
