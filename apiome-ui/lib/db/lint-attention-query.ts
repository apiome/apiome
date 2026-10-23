/**
 * Which revisions "need attention" for lint (HIVE-12.5, #5612).
 *
 * Home's **Needs attention** panel (`./dashboard-home.ts`) lists them; the `/ade` launcher's
 * hero counts them ("2 need attention"). Both read this one definition, so the chip and the
 * panel it leads to can never disagree about what counts:
 *
 * - **unpublished** revisions only — a blocking finding matters because it is what the publish
 *   gate will reject, and a published revision is already past that gate;
 * - in a live project of a workspace the reader **belongs to** (`tenant_users`);
 * - whose **stored** lint report counts at least one `error` — nothing is linted here, and
 *   `jsonb_typeof(…) = 'number'` guards the cast so one malformed report cannot abort the
 *   statement for the whole workspace.
 *
 * Not a `'use server'` module, like `./pinned-projects-query.ts` beside it: exporting a
 * function that takes a user id from a server-actions module would let any browser call it
 * with someone else's id. Callers resolve the user from their own session first.
 */

/** The slice of `pg`'s `Pool` these reads need. */
export type LintAttentionQueryRunner = (
  sql: string,
  params: unknown[],
) => Promise<{ rows: Record<string, unknown>[] }>;

/**
 * `FROM … WHERE …` shared by the list and the count. Parameter `$1` is the reader's user id.
 */
export const LINT_ATTENTION_FROM_WHERE = `FROM apiome.versions v
     JOIN apiome.projects p ON p.id = v.project_id
     WHERE p.tenant_id IN (SELECT tenant_id FROM apiome.tenant_users WHERE user_id = $1)
       AND p.deleted_at IS NULL
       AND v.deleted_at IS NULL
       AND v.published = false
       AND jsonb_typeof(v.quality_report->'severity_counts'->'error') = 'number'
       AND (v.quality_report->'severity_counts'->>'error')::int > 0`;

/** The count, for the launcher chip. Parameter `$1` is the reader's user id. */
export const LINT_ATTENTION_COUNT_SQL = `SELECT count(*)::int AS attention_count
     ${LINT_ATTENTION_FROM_WHERE}`;

/**
 * How many revisions need attention for lint, across the reader's workspaces.
 *
 * @param query The query runner — `connectionPool.query`, or a stub in tests.
 * @param userId The reader, already resolved from the caller's session.
 * @returns The count; `0` when the row is missing or not a non-negative number.
 */
export async function countLintAttention(
  query: LintAttentionQueryRunner,
  userId: string,
): Promise<number> {
  const result = await query(LINT_ATTENTION_COUNT_SQL, [userId]);
  const value = Number(result.rows[0]?.attention_count);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}
