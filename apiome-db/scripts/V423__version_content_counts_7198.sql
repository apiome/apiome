-- Per-revision content counts for the Home dashboard counters (DBP-1.15, #7198).
--
-- Home's stat strip and the /ade launcher (apiome-ui lib/db/helper.ts getDashboardStats) counted
-- every live class and class property of every revision in the reader's workspaces on each load —
-- about 1.2 s on the scale database's large tenant (5,000 projects, 256k classes, 836k class
-- properties), most of it the class-property join.
--
-- apiome.version_content_counts keeps, per revision, the three numbers that query needs:
--
--   * class_count            — live classes (classes.deleted_at IS NULL);
--   * class_property_count   — class properties of those live classes;
--   * max_class_created_at   — the newest live class's created_at (Home's "last activity").
--
-- Each row records the versions.content_stamp it was counted at. The content-stamp triggers (V403)
-- bump that stamp on every insert, update or delete of the revision's classes, class properties
-- and properties, so a row whose stamp still equals the revision's is exact. The dashboard query
-- recounts only the revisions whose row is missing or stale, in the same statement, and stores
-- the new rows; a published revision is counted once. Nothing else writes the table, and no
-- trigger maintains it, so imports pay nothing.
--
-- Rows go with their revision (ON DELETE CASCADE). The table is a cache: TRUNCATE is always safe,
-- and the next Home load refills it.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.version_content_counts;
--   (and restore the counting subqueries in getDashboardStats).

CREATE TABLE IF NOT EXISTS apiome.version_content_counts (
    version_id            uuid        PRIMARY KEY REFERENCES apiome.versions (id) ON DELETE CASCADE,
    content_stamp         bigint      NOT NULL CHECK (content_stamp >= 0),
    class_count           integer     NOT NULL CHECK (class_count >= 0),
    class_property_count  integer     NOT NULL CHECK (class_property_count >= 0),
    max_class_created_at  timestamptz,
    counted_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE apiome.version_content_counts IS
    'Cache (DBP-1.15, #7198): live class / class-property counts per revision at a content_stamp. '
    'A row is exact while its content_stamp equals versions.content_stamp. Safe to truncate.';
