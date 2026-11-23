/**
 * Home's dashboard counters, read through the per-revision count rollup (DBP-1.15, #7198).
 *
 * The stat strip on Home and the `/ade` launcher show, across the reader's workspaces, how many
 * projects, revisions, classes, library properties and class properties exist, plus how many the
 * reader created and when they last created something. Counting the classes and class properties
 * of every revision on each load took about 1.2 s on the scale database's large tenant.
 *
 * Two statements now, run one after the other ({@link loadDashboardStats}):
 *
 * 1. {@link DASHBOARD_COUNTS_REFRESH_SQL} brings `apiome.version_content_counts` (V423) up to date
 *    for the revisions the counters read: those of the reader's workspaces and those the reader
 *    created. A row is current while its `content_stamp` equals the revision's — the V403 triggers
 *    bump that stamp on every change to the revision's classes, class properties and properties —
 *    so only missing or stale rows are recounted. A published revision is counted once.
 * 2. {@link DASHBOARD_STATS_SQL} reads the counters, summing the rollup instead of the class
 *    tables.
 *
 * Cost on the scale database's large tenant (50,000 revisions): about 280 ms for a refresh with
 * nothing stale and 150 ms for the read — both touch every revision of the workspace once — against
 * about 1,600 ms for the old query. Home serves the result from a 60 s cache
 * (`getDashboardStats`), so a repeat load runs neither.
 *
 * The counts are the ones the old single query returned: every join it counted through is
 * many-to-one, so `COUNT(*)` equals its `COUNT(DISTINCT pk)`, and the rollup holds exactly the
 * live classes and their class properties per revision.
 *
 * Not a `'use server'` module: the functions take a user id, which only a caller that resolved it
 * from the session may pass.
 */

/** The slice of `pg`'s `Pool` these statements need. */
export type DashboardStatsQueryRunner = (
  sql: string,
  params: unknown[],
) => Promise<{ rows: Record<string, unknown>[] }>;

/** The reader's workspaces. Parameter `$1` is the reader's user id. */
const MEMBER_TENANTS = '(SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $1)';

/**
 * Recount the revisions whose rollup row is missing or stale. Parameter `$1` is the reader.
 *
 * `OFFSET 0` keeps the stale filter ahead of the recount, so a warm rollup recounts nothing; rows
 * are written in id order so two readers refreshing the same workspace lock them in the same order.
 */
export const DASHBOARD_COUNTS_REFRESH_SQL = `INSERT INTO apiome.version_content_counts AS r
    (version_id, content_stamp, class_count, class_property_count, max_class_created_at, counted_at)
  SELECT s.id, s.content_stamp, cc.class_count, cc.class_property_count, cc.max_class_created_at, now()
  FROM (
    SELECT t.id, t.content_stamp
    FROM (
      SELECT v.id, v.content_stamp
      FROM apiome.versions v
      JOIN apiome.projects p ON p.id = v.project_id
      WHERE p.tenant_id IN ${MEMBER_TENANTS}
      UNION
      SELECT v.id, v.content_stamp FROM apiome.versions v WHERE v.creator_id = $1
    ) t
    LEFT JOIN apiome.version_content_counts k ON k.version_id = t.id
    WHERE k.version_id IS NULL OR k.content_stamp <> t.content_stamp
    ORDER BY t.id
    OFFSET 0
  ) s
  CROSS JOIN LATERAL (
    SELECT COUNT(*)::int AS class_count,
           COALESCE(SUM((SELECT COUNT(*) FROM apiome.class_properties cp WHERE cp.class_id = c.id)), 0)::int
             AS class_property_count,
           MAX(c.created_at) AS max_class_created_at
    FROM apiome.classes c
    WHERE c.version_id = s.id AND c.deleted_at IS NULL
  ) cc
  ON CONFLICT (version_id) DO UPDATE SET
    content_stamp = EXCLUDED.content_stamp,
    class_count = EXCLUDED.class_count,
    class_property_count = EXCLUDED.class_property_count,
    max_class_created_at = EXCLUDED.max_class_created_at,
    counted_at = EXCLUDED.counted_at`;

/**
 * The counters, after {@link DASHBOARD_COUNTS_REFRESH_SQL}. Parameter `$1` is the reader.
 *
 * The revision-level counts come from one pass over the workspaces' live revisions; the reader's
 * "last activity" is the newest of their projects, their revisions and the live classes of their
 * revisions (`max_class_created_at`).
 */
export const DASHBOARD_STATS_SQL = `SELECT
    (SELECT COUNT(*) FROM apiome.tenant_users WHERE user_id = $1) AS total_tenants,
    (SELECT COUNT(*) FROM apiome.tenant_administrators WHERE user_id = $1) AS admin_tenants,
    (SELECT COUNT(*) FROM apiome.projects p
      WHERE p.tenant_id IN ${MEMBER_TENANTS} AND p.deleted_at IS NULL) AS total_projects,
    (SELECT COUNT(*) FROM apiome.projects WHERE creator_id = $1 AND deleted_at IS NULL) AS created_projects,
    m.total_versions,
    (SELECT COUNT(*) FROM apiome.versions WHERE creator_id = $1 AND deleted_at IS NULL) AS created_versions,
    m.published_versions,
    m.total_classes,
    (SELECT COUNT(*) FROM apiome.properties pr JOIN apiome.projects p ON pr.project_id = p.id
      WHERE p.tenant_id IN ${MEMBER_TENANTS} AND pr.deleted_at IS NULL) AS total_properties,
    m.total_class_properties,
    GREATEST(
      (SELECT MAX(created_at) FROM apiome.projects WHERE creator_id = $1),
      (SELECT MAX(created_at) FROM apiome.versions WHERE creator_id = $1),
      (SELECT MAX(k.max_class_created_at)
         FROM apiome.versions v
         JOIN apiome.version_content_counts k ON k.version_id = v.id
        WHERE v.creator_id = $1)
    ) AS last_activity
  FROM (
    SELECT COUNT(*) AS total_versions,
           COUNT(*) FILTER (WHERE v.published) AS published_versions,
           COALESCE(SUM(k.class_count), 0) AS total_classes,
           COALESCE(SUM(k.class_property_count), 0) AS total_class_properties
    FROM apiome.versions v
    JOIN apiome.projects p ON p.id = v.project_id
    LEFT JOIN apiome.version_content_counts k ON k.version_id = v.id
    WHERE p.tenant_id IN ${MEMBER_TENANTS}
      AND v.deleted_at IS NULL
  ) m`;

/**
 * Bring the rollup up to date for the reader, then read their counters.
 *
 * @param query The query runner — `connectionPool.query`, or a stub in tests.
 * @param userId The reader, already resolved from the caller's session.
 * @returns The counters row (`pg` returns the counts as strings).
 */
export async function loadDashboardStats(
  query: DashboardStatsQueryRunner,
  userId: string,
): Promise<Record<string, unknown> | undefined> {
  await query(DASHBOARD_COUNTS_REFRESH_SQL, [userId]);
  const result = await query(DASHBOARD_STATS_SQL, [userId]);
  return result.rows[0];
}
