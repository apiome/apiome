'use server';

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
} from '../utils/openapi-paths-generator';

/**
 * Load all paths with full operation details for OpenAPI export
 */
export async function loadPathsForOpenAPIExport(versionId: string): Promise<string> {
  try {
    if (!versionId) {
      console.error('[Paths Export] No version ID provided');
      return JSON.stringify({ success: false, error: 'No version ID provided' });
    }

    console.log('[Paths Export] Loading paths for version:', versionId);
    const pathsQuery = `
      SELECT 
        id, 
        pathname, 
        metadata->>'summary' as summary,
        metadata->>'description' as description
      FROM apiome.version_path
      WHERE version_id = $1
      ORDER BY pathname
    `;
    const pathsResult = await connectionPool.query(pathsQuery, [versionId]);
    console.log('[Paths Export] Found', pathsResult.rows.length, 'paths in database');

    if (pathsResult.rows.length === 0) {
      console.warn('[Paths Export] No paths found for version. Create paths in the Paths tab.');
    }

    const paths: PathInfo[] = [];

    for (const pathRow of pathsResult.rows) {
      const operationsQuery = `
        SELECT id, operation, metadata
        FROM apiome.path_operation
        WHERE version_path_id = $1
        ORDER BY CASE operation
          WHEN 'GET' THEN 1 WHEN 'POST' THEN 2 WHEN 'PUT' THEN 3
          WHEN 'PATCH' THEN 4 WHEN 'DELETE' THEN 5 ELSE 6
        END
      `;
      const operationsResult = await connectionPool.query(operationsQuery, [pathRow.id]);
      const operations: OperationInfo[] = [];

      for (const opRow of operationsResult.rows) {
        // Get operation description
        const descQuery = `
          SELECT 
            id, 
            summary, 
            description, 
            operation_id, 
            metadata->'tags' as tags,
            (metadata->>'deprecated')::boolean as deprecated,
            metadata->'external_docs' as external_docs,
            metadata->'security' as security,
            metadata->>'security_description' as security_description,
            metadata->>'x-security-description' as x_security_description,
            (metadata->>'x-private')::boolean as x_private_meta,
            (metadata->>'x_private')::boolean as x_private_alt
          FROM apiome.path_operation_description 
          WHERE path_operation_id = $1 
          LIMIT 1
        `;
        const descResult = await connectionPool.query(descQuery, [opRow.id]);
        let opDescription: PathOperationDescription | undefined;
        if (descResult.rows.length > 0) {
          const d = descResult.rows[0];
          const securityRaw = d.security;
          let security: PathOperationDescription['security'];
          if (Array.isArray(securityRaw) && securityRaw.length > 0) {
            security = securityRaw as PathOperationDescription['security'];
          } else if (securityRaw) {
            const parsed = typeof securityRaw === 'string' ? JSON.parse(securityRaw) : securityRaw;
            security = Array.isArray(parsed) ? parsed : [parsed];
          }
          const securityDescription =
            (d.security_description as string) || (d.x_security_description as string) || undefined;
          const xPrivate =
            (d.x_private_meta === true || d.x_private_alt === true) ? true : undefined;
          opDescription = {
            id: d.id,
            summary: d.summary,
            description: d.description,
            operationId: d.operation_id,
            tags: d.tags ? (typeof d.tags === 'string' ? JSON.parse(d.tags) : d.tags) : undefined,
            deprecated: d.deprecated,
            externalDocs: d.external_docs ? (typeof d.external_docs === 'string' ? JSON.parse(d.external_docs) : d.external_docs) : undefined,
            security,
            securityDescription,
            'x-private': xPrivate,
          };
        }

        // Get linked parameters
        const paramsQuery = `
          SELECT spp.id, spp.name, spp.in_location, spp.summary, spp.description, spp.data
          FROM apiome.shared_path_parameter spp
          INNER JOIN apiome.path_operation_parameter_link popl ON spp.id = popl.shared_path_parameter_id
          WHERE popl.path_operation_id = $1
          ORDER BY CASE spp.in_location WHEN 'path' THEN 1 WHEN 'query' THEN 2 WHEN 'header' THEN 3 ELSE 4 END, spp.name
        `;
        const paramsResult = await connectionPool.query(paramsQuery, [opRow.id]);
        const parameters: PathParameter[] = paramsResult.rows.map((p: Record<string, unknown>) => ({
          id: p.id as string, name: p.name as string,
          in_location: p.in_location as 'path' | 'query' | 'header' | 'cookie',
          summary: p.summary as string | undefined, description: p.description as string | undefined,
          data: p.data ? (typeof p.data === 'string' ? JSON.parse(p.data) : p.data) : {},
        }));

        // Get linked request body
        let requestBody: RequestBodyInfo | null = null;
        const rbQuery = `
          SELECT rb.id, rb.name, rb.description, rb.required,
            COALESCE(json_agg(json_build_object(
              'id', rbc.id, 'media_type', rbc.media_type, 'class_id', rbc.class_id,
              'class_name', c.name, 'inline_schema', rbc.inline_schema,
              'encoding', rbc.encoding, 'examples', rbc.examples
            )) FILTER (WHERE rbc.id IS NOT NULL), '[]') as content_types
          FROM apiome.shared_path_request_body rb
          INNER JOIN apiome.path_operation_request_body_link link ON rb.id = link.shared_path_request_body_id
          LEFT JOIN apiome.shared_path_request_body_content rbc ON rb.id = rbc.shared_path_request_body_id
          LEFT JOIN apiome.classes c ON rbc.class_id = c.id
          WHERE link.path_operation_id = $1
          GROUP BY rb.id
        `;
        const rbResult = await connectionPool.query(rbQuery, [opRow.id]);
        if (rbResult.rows.length > 0) {
          const rb = rbResult.rows[0];
          const cts = (rb.content_types || []).map((ct: Record<string, unknown>) => ({
            id: ct.id, media_type: ct.media_type, class_id: ct.class_id, class_name: ct.class_name,
            inline_schema: ct.inline_schema ? (typeof ct.inline_schema === 'string' ? JSON.parse(ct.inline_schema as string) : ct.inline_schema) : null,
            encoding: ct.encoding ? (typeof ct.encoding === 'string' ? JSON.parse(ct.encoding as string) : ct.encoding) : null,
            examples: ct.examples ? (typeof ct.examples === 'string' ? JSON.parse(ct.examples as string) : ct.examples) : null,
          })) as ContentTypeInfo[];
          requestBody = { id: rb.id, name: rb.name, description: rb.description, required: rb.required, content_types: cts };
        }

        // Get linked responses with content types
        const respQuery = `
          SELECT 
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
                  'examples', rc.examples
                )
              ) FILTER (WHERE rc.id IS NOT NULL),
              '[]'
            ) as content_types
          FROM apiome.shared_path_response spr
          INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
          LEFT JOIN apiome.classes c ON spr.class_id = c.id
          LEFT JOIN apiome.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
          LEFT JOIN apiome.classes rc_class ON rc.class_id = rc_class.id
          WHERE porl.path_operation_id = $1
          GROUP BY spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name, spr.inline_schema
          ORDER BY spr.status_code
        `;
        const respResult = await connectionPool.query(respQuery, [opRow.id]);
        const responses: ResponseInfo[] = respResult.rows.map((r: Record<string, unknown>) => ({
          id: r.id as string,
          status_code: r.status_code as string,
          description: r.description as string | undefined,
          data: r.data ? (typeof r.data === 'string' ? JSON.parse(r.data as string) : r.data) : undefined,
          class_id: r.class_id as string | null,
          class_name: r.class_name as string | null,
          inline_schema: r.inline_schema ? (typeof r.inline_schema === 'string' ? JSON.parse(r.inline_schema as string) : r.inline_schema) : null,
          content_types: (Array.isArray(r.content_types) ? r.content_types : []).map((ct: unknown) => {
            const ctRecord = ct as Record<string, unknown>;
            return {
              id: ctRecord.id as string,
              media_type: ctRecord.media_type as string,
              class_id: ctRecord.class_id as string | undefined,
              class_name: ctRecord.class_name as string | undefined,
              inline_schema: ctRecord.inline_schema ? (typeof ctRecord.inline_schema === 'string' ? JSON.parse(ctRecord.inline_schema as string) : ctRecord.inline_schema) : null,
              examples: ctRecord.examples ? (typeof ctRecord.examples === 'string' ? JSON.parse(ctRecord.examples as string) : ctRecord.examples) : null,
            };
          }),
        }));

        operations.push({ id: opRow.id, operation: opRow.operation, description: opDescription, parameters, requestBody, responses });
      }
      paths.push({ id: pathRow.id, pathname: pathRow.pathname, summary: pathRow.summary, description: pathRow.description, operations });
    }
    console.log('[Paths Export] Returning', paths.length, 'paths with operations');
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
    const classesWithProps = [];
    for (const cls of classesResult.rows) {
      const propsQuery = `SELECT id, name, description, data, parent_id FROM apiome.class_properties WHERE class_id = $1 ORDER BY name`;
      const propsResult = await connectionPool.query(propsQuery, [cls.id]);
      classesWithProps.push({
        ...cls, schema: cls.schema ? (typeof cls.schema === 'string' ? JSON.parse(cls.schema) : cls.schema) : {},
        properties: propsResult.rows.map((p: Record<string, unknown>) => ({ ...p, data: p.data ? (typeof p.data === 'string' ? JSON.parse(p.data as string) : p.data) : {} })),
      });
    }
    return JSON.stringify({ success: true, classes: classesWithProps });
  } catch (error: unknown) {
    console.error('Error loading referenced classes:', error);
    return JSON.stringify({ success: false, error: error instanceof Error ? error.message : 'Unknown error' });
  }
}
