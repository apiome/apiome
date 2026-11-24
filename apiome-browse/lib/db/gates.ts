/**
 * The gates every public Browse read applies, as SQL fragments (DBP-1.27, #7210).
 *
 * A version is public when it is published, `visibility = 'public'` and not deleted, in a project
 * and a tenant that are not deleted. `apiome.browse_public_projects` (V431) holds one row per
 * project that has such a version, so a statement that joins it needs no version probe to know the
 * project is public — but it still names the tenant and project gates, which are a column
 * comparison on rows it reads anyway, so a reader never depends on a summary refresh having run.
 */

/** A version aliased `v` is published, public and not deleted. */
export const PUBLIC_VERSION_ROW_GATES = `v.published = true
         AND v.visibility = 'public'
         AND v.deleted_at IS NULL`;

/** A tenant aliased `t` and a project aliased `p` are not deleted. */
export const LIVE_OWNER_GATES = `t.deleted_at IS NULL
         AND p.deleted_at IS NULL`;

/**
 * The public versions of one project, newest first: the order every Browse surface uses for
 * "latest" (`id` only breaks a tie, as in the summary table).
 */
export const NEWEST_VERSION_ORDER = 'v.published_at DESC NULLS LAST, v.created_at DESC, v.id DESC';
