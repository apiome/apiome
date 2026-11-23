/**
 * Explicit row projections shared by the UI's direct-SQL modules (DBP-1.13, #7196).
 *
 * No statement under `lib/db` selects or returns `*`: a new column — a password hash, a
 * 1536-dimension embedding — must be asked for by name before it travels. The lists here are
 * the ones more than one module needs; a list only one module needs lives in that module.
 */

/**
 * Render a column list, optionally qualified by a table alias.
 *
 * @param names The column names.
 * @param alias The table alias to qualify each with, if any.
 * @returns `a.id, a.name, …` (or `id, name, …`).
 */
export const columnList = (names: readonly string[], alias?: string) =>
  names.map((name) => (alias ? `${alias}.${name}` : name)).join(', ');

/** Every column of `apiome.projects`. */
export const PROJECT_COLUMNS = [
  'id',
  'tenant_id',
  'creator_id',
  'name',
  'description',
  'slug',
  'enabled',
  'deleted_at',
  'created_at',
  'updated_at',
  'metadata',
  'change_report_template_version_id',
  'pre_delete_enabled',
  'publishable',
  'repository_federation',
] as const;

/**
 * `apiome.versions` without its search columns: `mcp_public_embedding` (a 1536-dimension vector)
 * and `mcp_public_doc_tsv` are index inputs, never row data.
 */
export const VERSION_COLUMNS = [
  'id',
  'project_id',
  'creator_id',
  'version_id',
  'description',
  'change_log',
  'enabled',
  'published',
  'deleted_at',
  'created_at',
  'updated_at',
  'published_at',
  'visibility',
  'parent_version_id',
  'merge_parent_version_id',
  'revision_locked',
  'forked_from_revision_id',
  'upstream_project_id',
  'metadata',
  'commit_author',
  'commit_message',
  'external_ref',
  'published_immutable',
  'source_commit_sha',
  'source_committed_at',
  'quality_score',
  'quality_grade',
  'quality_report_fingerprint',
  'source_format',
  'protocol',
  'source_tool_versions',
  'format_metadata',
  'mock_enabled',
  'mock_settings',
  'quality_report',
  'unpublish_reason',
  'unpublished_at',
  'unpublished_by',
  'pruned_at',
  'content_stamp',
  'import_pending_at',
  'import_pending',
] as const;

/** Every column of `apiome.properties`. */
export const PROPERTY_COLUMNS =
  'id, project_id, name, description, data, enabled, deleted_at, created_at, updated_at, data_digest';

/** Every column of `apiome.classes`. */
export const CLASS_COLUMNS =
  'id, version_id, name, description, schema, enabled, deleted_at, created_at, updated_at, ' +
  'canvas_metadata, domain_id';

/** Every column of `apiome.class_properties`. */
export const CLASS_PROPERTY_COLUMNS =
  'id, class_id, property_id, name, description, data, parent_id, primitive_id, primitive_ref';
