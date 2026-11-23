-- Published-version indexes for the public browse surface (DBP-1.11, #7194).
--
-- versions had one index on `published` and none that covered `visibility`, so the browse home
-- page and every project card read the public, published rows by filtering a wider scan:
--
--   * idx_versions_public_published_recent — apiome-browse getRecentlyPublishedVersions (the
--     home page's "Recently published" rail): WHERE published AND visibility = 'public' AND
--     deleted_at IS NULL ORDER BY published_at DESC NULLS LAST, created_at DESC LIMIT n. Measured
--     on the scale database (200k versions, 45k of them public): 13.6 ms and 10,596 buffers before
--     (a scan of every live published version, then a top-n sort), 0.01 ms and 8 buffers after.
--   * idx_versions_project_published — apiome-browse latestPublicVersionJoinSql, the LATERAL that
--     finds each project's newest public published version for the project rails, the tenant's
--     project list and the project page (WHERE project_id = $1 AND published AND visibility =
--     'public' AND deleted_at IS NULL ORDER BY published_at DESC NULLS LAST, created_at DESC
--     LIMIT 1). Over the 4,900 projects of the large tenant: 13.0 ms before, 4.9 ms after (an
--     index scan in published order per project in place of a bitmap scan and sort).
--
-- Both are partial: unpublished, deleted and (for the first) private revisions get no entry, so
-- creating a draft revision costs nothing extra. Write cost, measured on the same database (22
-- indexes on versions before, 24 after) by inserting 20,000 versions, a quarter of them public and
-- published, in a rolled-back transaction: median 317.8 ms before, 338.3 ms after (+6%, about
-- 1 µs a row). Publishing 5,000 of them changed by less than the run-to-run noise.
--
-- Large databases: a migration runs in one transaction, so these are plain CREATE INDEX
-- statements and each blocks writes to versions while it builds (seconds per million rows). To
-- avoid that, build them first by hand with CREATE INDEX CONCURRENTLY (same names and
-- definitions); every statement here is IF NOT EXISTS, so the migration then does nothing.
--
-- Rollback notes:
--   DROP INDEX IF EXISTS apiome.idx_versions_public_published_recent;
--   DROP INDEX IF EXISTS apiome.idx_versions_project_published;

CREATE INDEX IF NOT EXISTS idx_versions_public_published_recent
    ON apiome.versions (published_at DESC NULLS LAST, created_at DESC)
    WHERE published AND visibility = 'public' AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_versions_project_published
    ON apiome.versions (project_id, published_at DESC NULLS LAST)
    WHERE published AND deleted_at IS NULL;
