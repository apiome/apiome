/**
 * Helper functions for loading path data for OpenAPI export
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

import type {
  PathInfo,
  OperationInfo,
  PathParameter,
  RequestBodyInfo,
  ResponseInfo,
  ContentTypeInfo,
  PathOperationDescription,
  PathParameterLocation,
} from '../utils/openapi-paths-generator';

/** The part of `pg.Pool` / `pg.PoolClient` the loaders use. */
export interface PathsQueryable {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows carry no column types
  query: (text: string, params?: unknown[]) => Promise<{ rows: Record<string, any>[] }>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- pg rows carry no column types
type Row = Record<string, any>;

/** Parse a JSON column that `pg` may hand back as text. */
function json(value: unknown): unknown {
  return typeof value === 'string' ? JSON.parse(value) : value;
}

/** Group rows by their `op_key` column (dropped from the rows), keeping row order. */
function byOperation(rows: Row[]): Map<string, Row[]> {
  const grouped = new Map<string, Row[]>();
  for (const { op_key: key, ...row } of rows) {
    const list = grouped.get(String(key));
    if (list) list.push(row);
    else grouped.set(String(key), [row]);
  }
  return grouped;
}

/** Every `apiome.path_operation` of the version, joined so each detail read covers all of them. */
const OPS_OF_VERSION = `
  INNER JOIN apiome.path_operation po ON po.id = link.path_operation_id
  INNER JOIN apiome.version_path vp ON vp.id = po.version_path_id`;

/**
 * The six set-based reads behind {@link loadPathsForOpenAPIExport} (DBP-1.6, #7189): one per
 * table, whatever the number of paths and operations. They return the rows the per-operation
 * reads did; a request body's or response's content types keep their physical (`ctid`) order,
 * which is what those reads returned.
 */
export const PATHS_EXPORT_QUERIES = {
  paths: `
      SELECT
        id,
        pathname,
        metadata->>'summary' as summary,
        metadata->>'description' as description
      FROM apiome.version_path
      WHERE version_id = $1
      ORDER BY pathname
    `,
  operations: `
      SELECT po.id, po.version_path_id, po.operation, po.metadata
      FROM apiome.path_operation po
      INNER JOIN apiome.version_path vp ON vp.id = po.version_path_id
      WHERE vp.version_id = $1
      ORDER BY po.version_path_id, CASE po.operation
        WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
        WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
      END
    `,
  descriptions: `
      SELECT
        link.path_operation_id AS op_key,
        link.id,
        link.summary,
        link.description,
        link.operation_id,
        link.metadata->'tags' as tags,
        (link.metadata->>'deprecated')::boolean as deprecated,
        link.metadata->'external_docs' as external_docs,
        link.metadata->'security' as security,
        link.metadata->>'security_description' as security_description,
        link.metadata->>'x-security-description' as x_security_description,
        (link.metadata->>'x-private')::boolean as x_private_meta,
        (link.metadata->>'x_private')::boolean as x_private_alt
      FROM apiome.path_operation_description link${OPS_OF_VERSION}
      WHERE vp.version_id = $1
    `,
  parameters: `
      SELECT link.path_operation_id AS op_key,
        spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
      FROM apiome.shared_path_parameter spp
      INNER JOIN apiome.path_operation_parameter_link link ON spp.id = link.shared_path_parameter_id${OPS_OF_VERSION}
      WHERE vp.version_id = $1
      ORDER BY link.path_operation_id,
        CASE spp.in_location WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4 END, spp.name
    `,
  requestBodies: `
      SELECT link.path_operation_id AS op_key, rb.id, rb.name, rb.description, rb.required,
        COALESCE(json_agg(json_build_object(
          'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
          'class_name', c.name, 'inline_schema', rbc.inline_schema,
          'encoding', rbc.encoding, 'examples', rbc.examples,
          'item_schema', rbc.item_schema
        ) ORDER BY rbc.ctid) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
      FROM apiome.shared_path_request_body rb
      INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id${OPS_OF_VERSION}
      LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
      LEFT JOIN apiome.classes c ON rbc.class_id = c.id
      WHERE vp.version_id = $1
      GROUP BY link.path_operation_id, rb.id
    `,
  responses: `
      SELECT
        link.path_operation_id AS op_key,
        spr.id,
        spr.status_code,
        spr.description,
        spr.data,
        spr.class_id,
        c.name as class_name,
        spr.inline_schema,
        COALESCE(
          json_agg(
            json_build_object(
              'id', rc.id,
              'media_type', rc.media_type,
              'class_id', rc.class_id,
              'class_name', rc_class.name,
              'inline_schema', rc.inline_schema,
              'examples', rc.examples,
              'item_schema', rc.item_schema
            ) ORDER BY rc.ctid
          ) FILTER (WHERE rc.id IS NOT NULL),
          '[]'
        ) as content_types
      FROM apiome.shared_path_response spr
      INNER JOIN apiome.path_operation_response_link link ON spr.id = link.shared_path_response_id${OPS_OF_VERSION}
      LEFT JOIN apiome.classes c ON spr.class_id = c.id
      LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
      LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
      WHERE vp.version_id = $1
      GROUP BY link.path_operation_id, spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name, spr.inline_schema
      ORDER BY link.path_operation_id, spr.status_code
    `,
} as const;

/** Map a `path_operation_description` row to the generator's description shape. */
function toDescription(d: Row): PathOperationDescription {
  const securityRaw = d.security;
  let security: PathOperationDescription['security'];
  if (Array.isArray(securityRaw) && securityRaw.length > 0) {
    security = securityRaw as PathOperationDescription['security'];
  } else if (securityRaw) {
    const parsed = json(securityRaw);
    security = (Array.isArray(parsed) ? parsed : [parsed]) as PathOperationDescription['security'];
  }
  const securityDescription =
    (d.security_description as string) || (d.x_security_description as string) || undefined;
  const xPrivate = d.x_private_meta === true || d.x_private_alt === true ? true : undefined;
  return {
    id: d.id,
    summary: d.summary,
    description: d.description,
    operationId: d.operation_id,
    tags: d.tags ? (json(d.tags) as string[]) : undefined,
    deprecated: d.deprecated,
    externalDocs: d.external_docs ? (json(d.external_docs) as PathOperationDescription['externalDocs']) : undefined,
    security,
    securityDescription,
    'x-private': xPrivate,
  };
}

/** Map a linked `shared_path_parameter` row. */
function toParameter(p: Row): PathParameter {
  return {
    id: p.id as string,
    name: p.name as string,
    in_location: p.in_location as PathParameterLocation,
    summary: p.summary as string | undefined,
    description: p.description as string | undefined,
    data: p.data ? (json(p.data) as PathParameter['data']) : {},
  };
}

/** Map a linked request body row with its content types. */
function toRequestBody(rb: Row): RequestBodyInfo {
  const cts = (rb.content_types || []).map((ct: Row) => ({
    id: ct.id,
    media_type: ct.media_type,
    class_id: ct.class_id,
    class_name: ct.class_name,
    inline_schema: ct.inline_schema ? json(ct.inline_schema) : null,
    encoding: ct.encoding ? json(ct.encoding) : null,
    examples: ct.examples ? json(ct.examples) : null,
    item_schema: ct.item_schema === true,
  })) as ContentTypeInfo[];
  return { id: rb.id, name: rb.name, description: rb.description, required: rb.required, content_types: cts };
}

/** Map a linked response row with its content types. */
function toResponse(r: Row): ResponseInfo {
  return {
    id: r.id as string,
    status_code: r.status_code as string,
    description: r.description as string | undefined,
    data: r.data ? (json(r.data) as ResponseInfo['data']) : undefined,
    class_id: r.class_id as string | null,
    class_name: r.class_name as string | null,
    inline_schema: r.inline_schema ? (json(r.inline_schema) as ResponseInfo['inline_schema']) : null,
    content_types: (Array.isArray(r.content_types) ? r.content_types : []).map((ct: Row) => ({
      id: ct.id as string,
      media_type: ct.media_type as string,
      class_id: ct.class_id as string | undefined,
      class_name: ct.class_name as string | undefined,
      inline_schema: ct.inline_schema ? json(ct.inline_schema) : null,
      examples: ct.examples ? json(ct.examples) : null,
      item_schema: ct.item_schema === true,
    })) as ResponseInfo['content_types'],
  };
}

/**
 * Read a version's paths with full operation details, in at most six statements (DBP-1.6, #7189).
 *
 * @param client - Query target: the caller's transaction client, or the pool.
 * @param versionId - The version (`versions.id`).
 * @returns The paths by pathname, each with its operations in method order.
 */
export async function readPathsForOpenAPIExport(client: PathsQueryable, versionId: string): Promise<PathInfo[]> {
  const pathRows = (await client.query(PATHS_EXPORT_QUERIES.paths, [versionId])).rows;
  if (pathRows.length === 0) return [];
  const opRows = (await client.query(PATHS_EXPORT_QUERIES.operations, [versionId])).rows;
  const details =
    opRows.length === 0
      ? null
      : {
          descriptions: byOperation((await client.query(PATHS_EXPORT_QUERIES.descriptions, [versionId])).rows),
          parameters: byOperation((await client.query(PATHS_EXPORT_QUERIES.parameters, [versionId])).rows),
          requestBodies: byOperation((await client.query(PATHS_EXPORT_QUERIES.requestBodies, [versionId])).rows),
          responses: byOperation((await client.query(PATHS_EXPORT_QUERIES.responses, [versionId])).rows),
        };

  const operationsByPath = new Map<string, OperationInfo[]>();
  for (const opRow of opRows) {
    const key = String(opRow.id);
    const description = details?.descriptions.get(key)?.[0];
    const requestBody = details?.requestBodies.get(key)?.[0];
    // Original method token of an imported OpenAPI 3.2 query / additionalOperations entry (OA4, #3501).
    const opMetadata = json(opRow.metadata) as { httpMethod?: unknown } | null | undefined;
    const httpMethod = typeof opMetadata?.httpMethod === 'string' ? opMetadata.httpMethod : undefined;
    const operation: OperationInfo = {
      id: opRow.id,
      operation: opRow.operation,
      ...(httpMethod ? { httpMethod } : {}),
      description: description ? toDescription(description) : undefined,
      parameters: (details?.parameters.get(key) ?? []).map(toParameter),
      requestBody: requestBody ? toRequestBody(requestBody) : null,
      responses: (details?.responses.get(key) ?? []).map(toResponse),
    };
    const pathKey = String(opRow.version_path_id);
    const list = operationsByPath.get(pathKey);
    if (list) list.push(operation);
    else operationsByPath.set(pathKey, [operation]);
  }
  return pathRows.map((pathRow) => ({
    id: pathRow.id,
    pathname: pathRow.pathname,
    summary: pathRow.summary,
    description: pathRow.description,
    operations: operationsByPath.get(String(pathRow.id)) ?? [],
  }));
}

/**
 * Load all paths with full operation details for OpenAPI export.
 *
 * @param versionId - The version (`versions.id`).
 * @param client - Query target; pass the caller's transaction client so the read sees its
 *   uncommitted rows and does not check out another pool connection. Defaults to the pool.
 * @returns JSON `{ success: true, paths }`, or `{ success: false, error }`.
 */
export async function loadPathsForOpenAPIExport(
  versionId: string,
  client: PathsQueryable = connectionPool,
): Promise<string> {
  try {
    if (!versionId) {
      console.error('[Paths Export] No version ID provided');
      return JSON.stringify({ success: false, error: 'No version ID provided' });
    }
    const paths = await readPathsForOpenAPIExport(client, versionId);
    if (paths.length === 0) {
      console.warn('[Paths Export] No paths found for version. Create paths in the Paths tab.');
    }
    return JSON.stringify({ success: true, paths });
  } catch (error: unknown) {
    console.error('[Paths Export] Error loading paths for OpenAPI export:', error);
    return JSON.stringify({ success: false, error: error instanceof Error ? error.message : 'Unknown error' });
  }
}

/**
 * Load classes referenced by paths
 */
export async function loadReferencedClassesForPaths(versionId: string, classNames: string[]): Promise<string> {
  if (classNames.length === 0) return JSON.stringify({ success: true, classes: [] });
  try {
    const classesQuery = `SELECT id, name, description, schema FROM apiome.classes WHERE version_id = $1 AND name = ANY($2)`;
    const classesResult = await connectionPool.query(classesQuery, [versionId, classNames]);
    // Every class's properties in one statement (DBP-1.6, #7189), each class's in name order.
    const classIds = classesResult.rows.map((cls: Record<string, unknown>) => cls.id);
    const propsResult =
      classIds.length === 0
        ? { rows: [] }
        : await connectionPool.query(
            `SELECT id, name, description, data, parent_id, class_id FROM apiome.class_properties WHERE class_id = ANY($1::uuid[]) ORDER BY name`,
            [classIds],
          );
    const propsByClass = new Map<string, Record<string, unknown>[]>();
    for (const { class_id: classId, ...prop } of propsResult.rows as Record<string, unknown>[]) {
      const list = propsByClass.get(String(classId));
      if (list) list.push(prop);
      else propsByClass.set(String(classId), [prop]);
    }
    const classesWithProps = classesResult.rows.map((cls: Record<string, unknown>) => ({
      ...cls,
      schema: cls.schema ? json(cls.schema) : {},
      properties: (propsByClass.get(String(cls.id)) ?? []).map((p) => ({ ...p, data: p.data ? json(p.data) : {} })),
    }));
    return JSON.stringify({ success: true, classes: classesWithProps });
  } catch (error: unknown) {
    console.error('Error loading referenced classes:', error);
    return JSON.stringify({ success: false, error: error instanceof Error ? error.message : 'Unknown error' });
  }
}
