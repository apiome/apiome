/**
 * Anchor labels for the Project Discussion panel — COL-1.3 (#4515).
 *
 * apiome-rest's thread list names an element only by kind and id. The panel needs its name (to
 * show it) and, for the Studio deep link, the class name or pathname its selection address is
 * spelled with. No single REST read answers that for classes, properties, paths *and* operations at
 * once, so the BFF list route resolves the ids of the threads REST just returned — which REST has
 * already authorized — with one query per element kind.
 *
 * Every query is bound to the caller's tenant and the project in the URL, so an id from another
 * project resolves to nothing. Ids that are not UUIDs are dropped before querying.
 *
 * This module deliberately has no `'use server'` directive: it is an internal utility of the BFF
 * route, not a server action a browser could call.
 */

import {
  classAnchorLabel,
  commentAnchorKey,
  isUuid,
  operationAnchorLabel,
  propertyAnchorLabel,
  type CommentAnchorContext,
  type CommentAnchorType,
} from '../comment-discussion';

/** Runs one parameterized query and returns its rows (`pg`'s `Pool.query` shape). */
export type AnchorLabelQuery = (
  sql: string,
  params: unknown[]
) => Promise<{ rows: Array<Record<string, unknown>> }>;

/** One element to label. */
export interface AnchorRef {
  /** The element kind. */
  anchor_type: CommentAnchorType;
  /** The element id. */
  anchor_id: string;
}

/** Whose elements may be labelled. */
export interface AnchorLabelScope {
  /** The caller's tenant id, from the session. */
  tenantId: string;
  /** The project in the URL: its id or its slug. */
  projectRef: string;
}

/** Joins a version to its project and binds both to the scope (`$1` tenant, `$2` project). */
const PROJECT_SCOPE_SQL = `
  JOIN apiome.versions v ON v.id = {versionColumn}
  JOIN apiome.projects p ON p.id = v.project_id
  WHERE p.tenant_id::text = $1
    AND (p.id::text = $2 OR p.slug = $2)`;

/**
 * The scoping clause for a table reached through its version.
 *
 * @param versionColumn - The column holding the version id, e.g. `c.version_id`.
 * @returns The JOIN + WHERE fragment.
 */
function scopedThroughVersion(versionColumn: string): string {
  return PROJECT_SCOPE_SQL.replace('{versionColumn}', versionColumn);
}

/** Class names by class id. */
export const CLASS_LABEL_SQL = `
  SELECT c.id::text AS id, c.name AS class_name
  FROM apiome.classes c${scopedThroughVersion('c.version_id')}
    AND c.id = ANY($3::uuid[])`;

/** Property and owning-class names by `class_properties` id. */
export const CLASS_PROPERTY_LABEL_SQL = `
  SELECT cp.id::text AS id, cp.name AS property_name, c.name AS class_name
  FROM apiome.class_properties cp
  JOIN apiome.classes c ON c.id = cp.class_id${scopedThroughVersion('c.version_id')}
    AND cp.id = ANY($3::uuid[])`;

/** Library property names by `properties` id (a library belongs to the project, not a version). */
export const LIBRARY_PROPERTY_LABEL_SQL = `
  SELECT pr.id::text AS id, pr.name AS property_name
  FROM apiome.properties pr
  JOIN apiome.projects p ON p.id = pr.project_id
  WHERE p.tenant_id::text = $1
    AND (p.id::text = $2 OR p.slug = $2)
    AND pr.id = ANY($3::uuid[])`;

/** Pathnames by `version_path` id. */
export const PATH_LABEL_SQL = `
  SELECT vp.id::text AS id, vp.pathname AS pathname
  FROM apiome.version_path vp${scopedThroughVersion('vp.version_id')}
    AND vp.id = ANY($3::uuid[])`;

/** Methods and pathnames by `path_operation` id. */
export const OPERATION_LABEL_SQL = `
  SELECT po.id::text AS id, po.operation AS method, vp.pathname AS pathname
  FROM apiome.path_operation po
  JOIN apiome.version_path vp ON vp.id = po.version_path_id${scopedThroughVersion('vp.version_id')}
    AND po.id = ANY($3::uuid[])`;

/**
 * Read a text column.
 *
 * @param row - A result row.
 * @param column - The column name.
 * @returns The value when it is a non-empty string, else null.
 */
function text(row: Record<string, unknown>, column: string): string | null {
  const value = row[column];
  return typeof value === 'string' && value !== '' ? value : null;
}

/**
 * The default query runner: the app's shared `pg` pool, loaded on first use so importing this
 * module (in tests, say) opens no connection.
 *
 * @param sql - The statement.
 * @param params - Its parameters.
 * @returns The result rows.
 */
const poolQuery: AnchorLabelQuery = async (sql, params) => {
  // `lib/db/db` is CommonJS (`module.exports = pool`); pulled in with require like every other consumer.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const connectionPool = require('./db');
  return connectionPool.query(sql, params);
};

/**
 * Resolve the names of anchored elements.
 *
 * @param scope - The caller's tenant and the project in the URL.
 * @param anchors - The elements to label; duplicates, version anchors and non-UUID ids are
 *   ignored.
 * @param query - The query runner (defaults to the shared pool; injected by tests).
 * @returns A map from {@link commentAnchorKey} to the element's context. An element that no longer
 *   exists, or is outside the scope, is absent.
 */
export async function resolveCommentAnchorContexts(
  scope: Readonly<AnchorLabelScope>,
  anchors: readonly AnchorRef[],
  query: AnchorLabelQuery = poolQuery
): Promise<Map<string, CommentAnchorContext>> {
  const idsByType: Record<Exclude<CommentAnchorType, 'version'>, Set<string>> = {
    class: new Set(),
    property: new Set(),
    path: new Set(),
    operation: new Set(),
  };
  for (const anchor of anchors) {
    if (anchor.anchor_type === 'version' || !isUuid(anchor.anchor_id)) continue;
    idsByType[anchor.anchor_type]?.add(anchor.anchor_id.toLowerCase());
  }

  const contexts = new Map<string, CommentAnchorContext>();
  if (!scope.tenantId || !scope.projectRef) return contexts;

  /**
   * Run one label query when there are ids to look up.
   *
   * @param sql - The statement.
   * @param ids - The ids to bind as `$3`.
   * @returns The rows, or none without ids.
   */
  const run = async (sql: string, ids: Set<string>) =>
    ids.size === 0 ? [] : (await query(sql, [scope.tenantId, scope.projectRef, [...ids]])).rows;

  const [classes, classProperties, libraryProperties, paths, operations] = await Promise.all([
    run(CLASS_LABEL_SQL, idsByType.class),
    run(CLASS_PROPERTY_LABEL_SQL, idsByType.property),
    run(LIBRARY_PROPERTY_LABEL_SQL, idsByType.property),
    run(PATH_LABEL_SQL, idsByType.path),
    run(OPERATION_LABEL_SQL, idsByType.operation),
  ]);

  for (const row of classes) {
    const id = text(row, 'id');
    const className = text(row, 'class_name');
    if (!id || !className) continue;
    contexts.set(commentAnchorKey('class', id), { label: classAnchorLabel(className), className });
  }
  // Library rows first, so a property on a class — the richer context — wins an id collision.
  for (const row of [...libraryProperties, ...classProperties]) {
    const id = text(row, 'id');
    const propertyName = text(row, 'property_name');
    if (!id || !propertyName) continue;
    const className = text(row, 'class_name');
    contexts.set(commentAnchorKey('property', id), {
      label: propertyAnchorLabel(className, propertyName),
      className,
      propertyName,
    });
  }
  for (const row of paths) {
    const id = text(row, 'id');
    const pathname = text(row, 'pathname');
    if (!id || !pathname) continue;
    contexts.set(commentAnchorKey('path', id), { label: pathname, pathname });
  }
  for (const row of operations) {
    const id = text(row, 'id');
    const method = text(row, 'method');
    const pathname = text(row, 'pathname');
    if (!id || !method || !pathname) continue;
    contexts.set(commentAnchorKey('operation', id), {
      label: operationAnchorLabel(method, pathname),
      method,
      pathname,
    });
  }
  return contexts;
}
