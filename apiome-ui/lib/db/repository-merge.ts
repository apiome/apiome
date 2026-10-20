/**
 * Multi-repository merge into one API surface (REPO-5.7, #2792) — storage.
 *
 * The rules live in `lib/repository-merge.ts`; this module reads what they need from the parent
 * version and writes what they decide:
 *
 * - {@link loadIncomingSource} / {@link loadParentEntities} build the planner's input.
 * - {@link loadCarriedPaths} reads the carried paths of the parent version in the import's
 *   parsed-path shape, so they are written by the same path importer as the incoming ones.
 * - {@link applyRepositoryMerge} runs inside the import's transaction once the new version
 *   exists: it records the contributing files (`project_repository_sources`), copies the carried
 *   classes and the parent's security schemes, and writes the per-entity provenance
 *   (`version_entity_sources`).
 *
 * Every function takes the query target explicitly (`Pool` or the import's `PoolClient`), so
 * writes stay in the caller's transaction.
 */

import { extractPaths, type ParsedPath } from '../../src/app/utils/openapi-import';
import { generatePathsForOpenAPI, type PathInfo } from '../utils/openapi-paths-generator';
import { loadPathsForOpenAPIExport } from './helper-paths-export';
import {
  isSameSource,
  sourceLineageKey,
  type MergeEntityKind,
  type MergeSource,
  type ParentEntity,
  type RepositoryMergePlan,
} from '../repository-merge';

/** A result row as `pg` returns it: column name → value, untyped. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows carry no column types
export type DbRow = Record<string, any>;

/** The part of `pg.Pool` / `pg.PoolClient` this module uses. */
export interface Queryable {
  query: (text: string, params?: unknown[]) => Promise<{ rows: DbRow[]; rowCount?: number | null }>;
}

/** The repository file being imported, as the import job describes it. */
export interface RepositoryFileRef {
  repositoryId: string;
  branch: string;
  path: string;
  blobSha?: string | null;
}

/**
 * Describe the importing file as a merge source, with its source row when it already has one.
 *
 * @param q - Query target.
 * @param tenantId - The importing tenant; a repository of another tenant is never matched.
 * @param projectId - The target project, or null when the import creates the project.
 * @param file - The repository file.
 * @returns The source, or null when the repository is not a live repository of the tenant (the
 *   import then proceeds without merge or provenance, as before REPO-5.7).
 */
export async function loadIncomingSource(
  q: Queryable,
  tenantId: string,
  projectId: string | null,
  file: RepositoryFileRef,
): Promise<MergeSource | null> {
  const res = await q.query(
    `SELECT tr.repository_full_name, prs.id AS source_id, prs.precedence
       FROM apiome.tenant_repositories tr
       LEFT JOIN apiome.project_repository_sources prs
         ON prs.project_id = $3::uuid AND prs.repository_id = tr.id
        AND prs.branch = $4 AND prs.path = $5
      WHERE tr.id = $2::uuid AND tr.tenant_id = $1::uuid AND tr.deleted_at IS NULL`,
    [tenantId, file.repositoryId, projectId, file.branch, file.path],
  );
  const row = res.rows[0];
  if (!row) return null;
  return {
    sourceId: row.source_id ?? null,
    repositoryId: file.repositoryId,
    repositoryFullName: String(row.repository_full_name || file.repositoryId),
    branch: file.branch,
    path: file.path,
    precedence: row.precedence ?? null,
    blobSha: file.blobSha ?? null,
  };
}

/**
 * Every class and path of a version, with the contributing file that defined it.
 *
 * A provenance row whose source was removed (the repository was deleted, or the project) reads as
 * unattributed. A version with no provenance at all that was imported from a repository file
 * before REPO-5.7 (a `tenant_repository_imports` row) is attributed wholly to that file, so the
 * first merge after an upgrade keeps it.
 *
 * @param q - Query target.
 * @param tenantId - The importing tenant.
 * @param projectId - The project the version belongs to.
 * @param versionId - The parent version (`versions.id`).
 * @returns The entities, classes then paths, each ordered by key.
 */
export async function loadParentEntities(
  q: Queryable,
  tenantId: string,
  projectId: string,
  versionId: string,
): Promise<ParentEntity[]> {
  const res = await q.query(
    `WITH ents AS (
       SELECT 'class'::text AS kind, c.name::text AS key
         FROM apiome.classes c
        WHERE c.version_id = $1::uuid AND c.deleted_at IS NULL
       UNION
       SELECT 'path'::text, vp.pathname::text
         FROM apiome.version_path vp
        WHERE vp.version_id = $1::uuid
     )
     SELECT e.kind, e.key,
            (ves.id IS NOT NULL) AS has_row,
            prs.id AS source_id, prs.precedence, prs.repository_id,
            ves.repository_full_name, prs.branch, prs.path, ves.blob_sha
       FROM ents e
       LEFT JOIN apiome.version_entity_sources ves
         ON ves.version_id = $1::uuid AND ves.entity_kind = e.kind AND ves.entity_key = e.key
       LEFT JOIN apiome.project_repository_sources prs ON prs.id = ves.source_id
      ORDER BY e.kind, e.key`,
    [versionId],
  );
  const rows = res.rows;

  if (rows.length > 0 && !rows.some((r) => r.has_row)) {
    const legacy = await loadLegacyImportSource(q, tenantId, projectId, versionId);
    if (legacy) {
      return rows.map((r) => ({ kind: r.kind as MergeEntityKind, key: String(r.key), source: legacy }));
    }
  }

  return rows.map((r) => ({
    kind: r.kind as MergeEntityKind,
    key: String(r.key),
    source: r.source_id
      ? {
          sourceId: String(r.source_id),
          repositoryId: String(r.repository_id),
          repositoryFullName: String(r.repository_full_name),
          branch: String(r.branch),
          path: String(r.path),
          precedence: r.precedence == null ? null : Number(r.precedence),
          blobSha: r.blob_sha ?? null,
        }
      : null,
  }));
}

/**
 * The repository file a version was imported from before provenance existed, if any.
 *
 * @returns The newest `tenant_repository_imports` file for the version whose repository is still
 *   a live repository of the tenant, with its source row when one exists.
 */
async function loadLegacyImportSource(
  q: Queryable,
  tenantId: string,
  projectId: string,
  versionId: string,
): Promise<MergeSource | null> {
  const res = await q.query(
    `SELECT tri.repository_id, tri.branch, tri.path, tri.blob_sha, tr.repository_full_name,
            prs.id AS source_id, prs.precedence
       FROM apiome.tenant_repository_imports tri
       JOIN apiome.tenant_repositories tr
         ON tr.id = tri.repository_id AND tr.tenant_id = $1::uuid AND tr.deleted_at IS NULL
       LEFT JOIN apiome.project_repository_sources prs
         ON prs.project_id = $2::uuid AND prs.repository_id = tri.repository_id
        AND prs.branch = tri.branch AND prs.path = tri.path
      WHERE tri.version_id = $3::uuid AND tri.tenant_id = $1::uuid
      ORDER BY tri.created_at DESC
      LIMIT 1`,
    [tenantId, projectId, versionId],
  );
  const row = res.rows[0];
  if (!row) return null;
  return {
    sourceId: row.source_id ?? null,
    repositoryId: String(row.repository_id),
    repositoryFullName: String(row.repository_full_name || row.repository_id),
    branch: String(row.branch),
    path: String(row.path),
    precedence: row.precedence == null ? null : Number(row.precedence),
    blobSha: row.blob_sha ?? null,
  };
}

/**
 * The parent version's carried paths, parsed exactly like the paths of an imported document.
 *
 * Reuses the OpenAPI export of the version (`loadPathsForOpenAPIExport` →
 * `generatePathsForOpenAPI`) and the import's path parser (`extractPaths`): a carried path goes
 * through the same round trip as any exported-then-imported path, and its `$ref`s resolve to the
 * carried classes by name.
 *
 * @param parentVersionId - The parent version.
 * @param pathnames - The carried pathnames.
 * @returns The parsed paths (in pathname order); empty when there is nothing to carry.
 * @throws Error when the parent's paths cannot be read — a merge never silently drops paths.
 */
export async function loadCarriedPaths(parentVersionId: string, pathnames: readonly string[]): Promise<ParsedPath[]> {
  if (pathnames.length === 0) return [];
  const loaded = JSON.parse(await loadPathsForOpenAPIExport(parentVersionId)) as {
    success?: boolean;
    paths?: PathInfo[];
    error?: string;
  };
  if (!loaded.success) {
    throw new Error(`Could not read the paths carried forward from the parent version: ${loaded.error ?? 'unknown error'}`);
  }
  const wanted = new Set(pathnames);
  const paths = (loaded.paths ?? []).filter((p) => wanted.has(p.pathname));
  return extractPaths({ paths: generatePathsForOpenAPI(paths) });
}

/** Inputs to {@link applyRepositoryMerge}. */
export interface ApplyRepositoryMergeInput {
  tenantId: string;
  projectId: string;
  userId: string;
  /** The version the import just created. */
  versionId: string;
  /** Its parent, or null for the project's first version. */
  parentVersionId: string | null;
  /** The importing file. */
  incoming: MergeSource;
  /** The plan the import was checked against (must have no conflicts). */
  plan: RepositoryMergePlan;
  /** Classes the importing file wrote. */
  incomingClasses: readonly string[];
  /** Paths the importing file writes. */
  incomingPaths: readonly string[];
}

/** What {@link applyRepositoryMerge} wrote. */
export interface ApplyRepositoryMergeResult {
  /** The importing file's source row. */
  sourceId: string;
  classesCarried: number;
  provenanceRows: number;
}

/**
 * Record the merge of one repository file into the version the import just created.
 *
 * Runs inside the import's transaction. Carried paths are not written here: they are imported
 * with the incoming paths (see {@link loadCarriedPaths}).
 *
 * @param client - The import's transaction client.
 * @param input - The new version, the importing file, and the conflict-free plan.
 * @returns The importing file's source row and counts.
 * @throws Error when the plan still has conflicts.
 */
export async function applyRepositoryMerge(
  client: Queryable,
  input: ApplyRepositoryMergeInput,
): Promise<ApplyRepositoryMergeResult> {
  const { plan } = input;
  if (plan.conflicts.length > 0) {
    throw new Error('applyRepositoryMerge called with an unresolved conflict');
  }

  // Source rows first: carried files that have none yet (attributed from a pre-REPO-5.7 import)
  // contributed before the importing file, so they take their precedence first.
  const sourceIds = new Map<string, string>();
  for (const source of plan.sources) {
    if (isSameSource(source, input.incoming)) continue;
    const id = source.sourceId ?? (await ensureSourceRow(client, input, source, false));
    sourceIds.set(sourceLineageKey(source), id);
  }
  const incomingSourceId = await ensureSourceRow(client, input, input.incoming, true);
  sourceIds.set(sourceLineageKey(input.incoming), incomingSourceId);

  let classesCarried = 0;
  if (plan.mode === 'multi-source' && input.parentVersionId) {
    const carriedClasses = plan.carried.filter((e) => e.kind === 'class').map((e) => e.key);
    classesCarried = await copyClassesTx(client, input.parentVersionId, input.versionId, carriedClasses);
    if (plan.carried.some((e) => e.kind === 'path')) {
      await copySecuritySchemesTx(client, input.parentVersionId, input.versionId);
    }
  }

  const rows: ProvenanceRow[] = [];
  const own = (kind: MergeEntityKind, key: string): ProvenanceRow => ({
    kind,
    key,
    source: input.incoming,
    sourceId: incomingSourceId,
    carriedFrom: null,
  });
  for (const key of new Set(input.incomingClasses)) rows.push(own('class', key));
  for (const key of new Set(input.incomingPaths)) rows.push(own('path', key));
  for (const entity of plan.carried) {
    if (!entity.source) continue;
    rows.push({
      kind: entity.kind,
      key: entity.key,
      source: entity.source,
      sourceId: sourceIds.get(sourceLineageKey(entity.source)) ?? null,
      carriedFrom: input.parentVersionId,
    });
  }
  await writeProvenanceTx(client, input.versionId, rows);

  return { sourceId: incomingSourceId, classesCarried, provenanceRows: rows.length };
}

/**
 * Insert a project's source row for a file, or touch the existing one.
 *
 * A new row takes the next precedence of the project. `touch` (the importing file) moves
 * `last_version_id` / `last_blob_sha` to this import; a carried file's existing row is left alone.
 *
 * @returns The source row id.
 */
async function ensureSourceRow(
  client: Queryable,
  input: ApplyRepositoryMergeInput,
  source: MergeSource,
  touch: boolean,
): Promise<string> {
  const versionForNew = touch ? input.versionId : input.parentVersionId;
  const res = await client.query(
    `INSERT INTO apiome.project_repository_sources (
       tenant_id, project_id, repository_id, branch, path, precedence,
       first_version_id, last_version_id, last_blob_sha, created_by
     )
     SELECT $1::uuid, $2::uuid, $3::uuid, $4, $5,
            COALESCE((SELECT MAX(precedence) FROM apiome.project_repository_sources WHERE project_id = $2::uuid), 0) + 1,
            $6::uuid, $6::uuid, $7, $8::uuid
     ON CONFLICT (project_id, repository_id, branch, path) DO UPDATE SET
       last_version_id = CASE WHEN $9::boolean THEN EXCLUDED.last_version_id ELSE apiome.project_repository_sources.last_version_id END,
       last_blob_sha = CASE WHEN $9::boolean THEN EXCLUDED.last_blob_sha ELSE apiome.project_repository_sources.last_blob_sha END,
       updated_at = CASE WHEN $9::boolean THEN CURRENT_TIMESTAMP ELSE apiome.project_repository_sources.updated_at END
     RETURNING id`,
    [
      input.tenantId,
      input.projectId,
      source.repositoryId,
      source.branch,
      source.path,
      versionForNew,
      source.blobSha ?? null,
      input.userId,
      touch,
    ],
  );
  return String(res.rows[0].id);
}

/**
 * Copy named live classes, with their property links (nested properties keep their parents),
 * from one version to another. Domains are version-scoped, so a copied class is unassigned.
 *
 * @returns How many classes were copied.
 */
export async function copyClassesTx(
  client: Queryable,
  fromVersionId: string,
  toVersionId: string,
  names: readonly string[],
): Promise<number> {
  if (names.length === 0) return 0;
  const classes = await client.query(
    `WITH src AS (
       SELECT id, name, description, schema, enabled, canvas_metadata
         FROM apiome.classes
        WHERE version_id = $1::uuid AND deleted_at IS NULL AND name = ANY($3::text[])
     ), ins AS (
       INSERT INTO apiome.classes (version_id, name, description, schema, enabled, canvas_metadata)
       SELECT $2::uuid, name, description, schema, enabled, canvas_metadata FROM src
       RETURNING id, name
     )
     SELECT src.id AS old_id, ins.id AS new_id FROM src JOIN ins ON ins.name = src.name`,
    [fromVersionId, toVersionId, [...names]],
  );
  const oldIds = classes.rows.map((r) => String(r.old_id));
  const newIds = classes.rows.map((r) => String(r.new_id));
  if (oldIds.length === 0) return 0;
  // One statement: every link gets a fresh id up front so a nested property's parent_id can be
  // mapped to its copied parent (foreign keys are checked at the end of the statement).
  await client.query(
    `WITH m AS MATERIALIZED (
       SELECT cp.id AS old_id, gen_random_uuid() AS new_id, cp.class_id, cp.property_id, cp.name,
              cp.description, cp.data, cp.parent_id, cp.primitive_id, cp.primitive_ref
         FROM apiome.class_properties cp
        WHERE cp.class_id = ANY($1::uuid[])
     )
     INSERT INTO apiome.class_properties (
       id, class_id, property_id, name, description, data, parent_id, primitive_id, primitive_ref
     )
     SELECT m.new_id, cm.new_class_id, m.property_id, m.name, m.description, m.data, pm.new_id,
            m.primitive_id, m.primitive_ref
       FROM m
       JOIN unnest($1::uuid[], $2::uuid[]) AS cm(old_class_id, new_class_id) ON cm.old_class_id = m.class_id
       LEFT JOIN m pm ON pm.old_id = m.parent_id`,
    [oldIds, newIds],
  );
  return oldIds.length;
}

/** Copy the parent's security schemes the new version does not define (carried paths use them). */
async function copySecuritySchemesTx(client: Queryable, fromVersionId: string, toVersionId: string): Promise<void> {
  await client.query(
    `INSERT INTO apiome.version_security_scheme
       (version_id, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data)
     SELECT $2::uuid, scheme_name, scheme_type, in_location, param_name, http_scheme, description, data
       FROM apiome.version_security_scheme
      WHERE version_id = $1::uuid
     ON CONFLICT (version_id, scheme_name) DO NOTHING`,
    [fromVersionId, toVersionId],
  );
}

/** One provenance row to write. */
interface ProvenanceRow {
  kind: MergeEntityKind;
  key: string;
  source: MergeSource;
  sourceId: string | null;
  carriedFrom: string | null;
}

/** Write a version's provenance rows in one statement (a re-run replaces a row). */
async function writeProvenanceTx(client: Queryable, versionId: string, rows: readonly ProvenanceRow[]): Promise<void> {
  if (rows.length === 0) return;
  await client.query(
    `INSERT INTO apiome.version_entity_sources (
       version_id, entity_kind, entity_key, source_id, repository_id, repository_full_name,
       branch, path, blob_sha, carried_from_version_id
     )
     SELECT $1::uuid, r.kind, r.key, r.source_id, r.repository_id, r.repository_full_name,
            r.branch, r.path, r.blob_sha, r.carried_from
       FROM unnest($2::text[], $3::text[], $4::uuid[], $5::uuid[], $6::text[], $7::text[], $8::text[], $9::text[], $10::uuid[])
         AS r(kind, key, source_id, repository_id, repository_full_name, branch, path, blob_sha, carried_from)
     ON CONFLICT (version_id, entity_kind, entity_key) DO UPDATE SET
       source_id = EXCLUDED.source_id,
       repository_id = EXCLUDED.repository_id,
       repository_full_name = EXCLUDED.repository_full_name,
       branch = EXCLUDED.branch,
       path = EXCLUDED.path,
       blob_sha = EXCLUDED.blob_sha,
       carried_from_version_id = EXCLUDED.carried_from_version_id`,
    [
      versionId,
      rows.map((r) => r.kind),
      rows.map((r) => r.key),
      rows.map((r) => r.sourceId),
      rows.map((r) => r.source.repositoryId),
      rows.map((r) => r.source.repositoryFullName),
      rows.map((r) => r.source.branch),
      rows.map((r) => r.source.path),
      rows.map((r) => r.source.blobSha ?? null),
      rows.map((r) => r.carriedFrom),
    ],
  );
}
