/**
 * Import OpenAPI paths and security schemes into an existing version (#425).
 * Call after importProjectFromOpenAPI when the spec contains paths or components.securitySchemes.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');
import type { ParsedPath, ParsedOperation, ParsedParameter, ParsedSecurityScheme } from '../../src/app/utils/openapi-import';
import type { PathParameterLocation } from '../utils/openapi-paths-generator';
import { buildStoredInlineSchema } from '../utils/inline-schema-utils';
import { randomUUID } from 'crypto';
import { bulkInsert, type BulkQueryable } from './import-bulk';

/**
 * The version's live classes, for resolving `$ref`s. `deleted_at IS NULL` is what lets the
 * partial `(version_id, name)` index answer it, and keeps a `$ref` from resolving to a
 * soft-deleted class (DBP-1.9, #7192).
 */
export const CLASS_LOOKUP_SQL =
  'SELECT id, name FROM apiome.classes WHERE version_id = $1 AND deleted_at IS NULL';

function getRefSchemaName(ref: string | undefined): string | null {
  if (!ref || typeof ref !== 'string') return null;
  const m = ref.match(/#\/components\/schemas\/(.+)/);
  return m ? m[1] : null;
}

/**
 * Build the `path_operation.metadata` for an imported operation.
 *
 * @param op - the parsed operation.
 * @returns `deprecated`, plus the original method token and where it was declared for an
 *   OpenAPI 3.2 `query` / `additionalOperations` operation (OA4, #3501); null when empty.
 */
export function buildPathOperationMetadata(
  op: Pick<ParsedOperation, 'deprecated' | 'httpMethod' | 'methodSource'>
): Record<string, unknown> | null {
  const metadata: Record<string, unknown> = {};
  if (op.deprecated) metadata.deprecated = true;
  if (op.httpMethod) metadata.httpMethod = op.httpMethod;
  if (op.methodSource) metadata.methodSource = op.methodSource;
  return Object.keys(metadata).length > 0 ? metadata : null;
}

/**
 * Build the `shared_path_parameter.data` for an imported parameter.
 *
 * @param p - the parsed parameter.
 * @returns its schema (default `{ type: 'string' }`), with `required: true` when required and the
 *   `content` media type (`contentMediaType`) of a parameter declared with `content`, such as an
 *   OpenAPI 3.2 `in: querystring` parameter (#7048).
 */
export function buildParameterData(
  p: Pick<ParsedParameter, 'schema' | 'required' | 'contentMediaType'>
): Record<string, unknown> {
  const base: Record<string, unknown> = p.schema && typeof p.schema === 'object' ? { ...p.schema } : { type: 'string' };
  if (p.required === true) base.required = true;
  if (p.contentMediaType) base.contentMediaType = p.contentMediaType;
  return base;
}

/** Columns of each table the import writes, in insert order (see {@link PathImportRows}). */
const PATH_IMPORT_COLUMNS = {
  version_path: ['id', 'version_id', 'pathname', 'metadata'],
  shared_path_parameter: ['id', 'version_path_id', 'name', 'in_location', 'summary', 'description', 'data'],
  path_operation: ['id', 'version_path_id', 'operation', 'metadata'],
  path_operation_description: ['path_operation_id', 'summary', 'description', 'operation_id', 'metadata'],
  path_operation_parameter_link: ['path_operation_id', 'shared_path_parameter_id', 'metadata'],
  shared_path_request_body: ['id', 'version_path_id', 'name', 'description', 'required'],
  shared_path_request_body_content: [
    'shared_path_request_body_id',
    'media_type',
    'class_id',
    'inline_schema',
    'item_schema',
  ],
  path_operation_request_body_link: ['path_operation_id', 'shared_path_request_body_id', 'metadata'],
  shared_path_response: [
    'id',
    'version_path_id',
    'status_code',
    'description',
    'data',
    'class_id',
    'inline_schema',
    'schema_mode',
  ],
  shared_path_response_content: ['shared_path_response_id', 'media_type', 'class_id', 'inline_schema', 'item_schema'],
  path_operation_response_link: ['path_operation_id', 'shared_path_response_id', 'metadata'],
} as const;

/** A table the paths import writes. Parents come before their children. */
type PathImportTable = keyof typeof PATH_IMPORT_COLUMNS;

/** One row to insert, keyed by column name. */
type Row = Record<string, unknown>;

/** Every row a paths import writes, per table. */
export type PathImportRows = Record<PathImportTable, Row[]>;

/** The stored inline schema of a response media type that names no schema. */
const EMPTY_OBJECT_SCHEMA = { type: 'object', properties: [] };

/**
 * Build every row a paths import writes, with ids assigned here so a child row names its parent
 * without a round trip (DBP-1.9, #7192).
 *
 * What the per-row statements used to settle with `ON CONFLICT` is settled here instead:
 *
 * - a path-level parameter declared twice keeps the first row and takes the later description
 *   and data;
 * - an operation parameter that matches a path's parameter (same name and location) links to it
 *   rather than adding a row;
 * - operations of one path that answer the same status code share one response row: the later
 *   description wins, and data, class and inline schema are kept when the later one has none;
 * - a response media type is written once per response.
 *
 * @param versionId The version the paths belong to.
 * @param paths The parsed paths.
 * @param classNameToId The version's live classes, by name; a `$ref` to one becomes its id.
 * @param newId Id source (defaults to `crypto.randomUUID`); tests pass a counter.
 * @returns The rows, per table.
 */
export function buildPathImportRows(
  versionId: string,
  paths: ParsedPath[],
  classNameToId: ReadonlyMap<string, string>,
  newId: () => string = randomUUID,
): PathImportRows {
  const rows: PathImportRows = {
    version_path: [],
    shared_path_parameter: [],
    path_operation: [],
    path_operation_description: [],
    path_operation_parameter_link: [],
    shared_path_request_body: [],
    shared_path_request_body_content: [],
    path_operation_request_body_link: [],
    shared_path_response: [],
    shared_path_response_content: [],
    path_operation_response_link: [],
  };
  const classIdFor = (ref: string | undefined): string | null => {
    const refName = ref ? getRefSchemaName(ref) : null;
    return refName ? classNameToId.get(refName) ?? null : null;
  };

  for (const pathItem of paths) {
    const versionPathId = newId();
    rows.version_path.push({
      id: versionPathId,
      version_id: versionId,
      pathname: pathItem.path,
      metadata:
        pathItem.summary || pathItem.description
          ? { summary: pathItem.summary, description: pathItem.description }
          : null,
    });

    const parametersByKey = new Map<string, Row>();
    for (const p of pathItem.parameters ?? []) {
      const inLoc = (p.in || 'query') as PathParameterLocation;
      const key = `${p.name}:${inLoc}`;
      const existing = parametersByKey.get(key);
      if (existing) {
        existing.description = p.description || null;
        existing.data = buildParameterData(p);
        continue;
      }
      const row: Row = {
        id: newId(),
        version_path_id: versionPathId,
        name: p.name,
        in_location: inLoc,
        summary: null,
        description: p.description || null,
        data: buildParameterData(p),
      };
      parametersByKey.set(key, row);
      rows.shared_path_parameter.push(row);
    }

    const responsesByStatus = new Map<string, { row: Row; mediaTypes: Set<string> }>();
    for (const op of pathItem.operations) {
      const pathOperationId = newId();
      rows.path_operation.push({
        id: pathOperationId,
        version_path_id: versionPathId,
        operation: op.method,
        metadata: buildPathOperationMetadata(op),
      });

      const descMetadata: Record<string, unknown> = {};
      if (op.tags?.length) descMetadata.tags = op.tags;
      if (op.deprecated === true) descMetadata.deprecated = true;
      rows.path_operation_description.push({
        path_operation_id: pathOperationId,
        summary: op.summary ?? null,
        description: op.description ?? null,
        operation_id: op.operationId ?? null,
        metadata: Object.keys(descMetadata).length > 0 ? descMetadata : null,
      });

      const linkedParameters = new Set<string>();
      for (const p of op.parameters || []) {
        const inLoc = (p.in || 'query') as PathParameterLocation;
        const key = `${p.name}:${inLoc}`;
        let parameter = parametersByKey.get(key);
        if (!parameter) {
          parameter = {
            id: newId(),
            version_path_id: versionPathId,
            name: p.name,
            in_location: inLoc,
            summary: null,
            description: p.description || null,
            data: buildParameterData(p),
          };
          parametersByKey.set(key, parameter);
          rows.shared_path_parameter.push(parameter);
        }
        if (linkedParameters.has(key)) continue;
        linkedParameters.add(key);
        rows.path_operation_parameter_link.push({
          path_operation_id: pathOperationId,
          shared_path_parameter_id: parameter.id,
          metadata: null,
        });
      }

      if (op.requestBody?.content && Object.keys(op.requestBody.content).length > 0) {
        const requestBodyId = newId();
        rows.shared_path_request_body.push({
          id: requestBodyId,
          version_path_id: versionPathId,
          name: op.operationId
            ? op.operationId
            : `RequestBody_${op.method}_${pathItem.path.replace(/^\//, '').replace(/\//g, '_') || 'root'}`,
          description: op.requestBody.description ?? null,
          required: op.requestBody.required === true,
        });
        for (const [mediaType, content] of Object.entries(op.requestBody.content)) {
          const classId = classIdFor(content.$ref);
          const inlineSchema =
            !content.$ref && content.schema
              ? buildStoredInlineSchema(content.schema as Record<string, unknown>)
              : null;
          if (!classId && !inlineSchema) continue;
          rows.shared_path_request_body_content.push({
            shared_path_request_body_id: requestBodyId,
            media_type: mediaType,
            class_id: classId,
            inline_schema: inlineSchema,
            item_schema: Boolean(content.streamKind),
          });
        }
        rows.path_operation_request_body_link.push({
          path_operation_id: pathOperationId,
          shared_path_request_body_id: requestBodyId,
          metadata: null,
        });
      }

      for (const [statusCode, res] of Object.entries(op.responses ?? {})) {
        const hasContent = Boolean(res.content && typeof res.content === 'object' && Object.keys(res.content).length > 0);
        const contentEntries = hasContent ? Object.entries(res.content!) : [];
        const dataObj: Record<string, unknown> = {};
        if (res.headers && Object.keys(res.headers || {}).length > 0) dataObj.headers = res.headers;
        if (res.links && Object.keys(res.links || {}).length > 0) dataObj.links = res.links;
        let classId: string | null = null;
        let inlineSchema: Record<string, unknown> | null = null;
        if (contentEntries.length > 0) {
          const [, first] = contentEntries[0];
          classId = classIdFor(first?.$ref);
          inlineSchema =
            !first?.$ref && first?.schema
              ? buildStoredInlineSchema(first.schema as Record<string, unknown>)
              : { ...EMPTY_OBJECT_SCHEMA };
        }
        const incoming = {
          description: res.description ?? null,
          data: Object.keys(dataObj).length > 0 ? dataObj : hasContent ? null : {},
          class_id: classId,
          inline_schema: classId ? null : inlineSchema,
          schema_mode: classId ? 'class' : 'object',
        };

        let response = responsesByStatus.get(statusCode);
        if (!response) {
          response = {
            row: { id: newId(), version_path_id: versionPathId, status_code: statusCode, ...incoming },
            mediaTypes: new Set<string>(),
          };
          responsesByStatus.set(statusCode, response);
          rows.shared_path_response.push(response.row);
        } else {
          response.row.description = incoming.description;
          response.row.data = incoming.data ?? response.row.data;
          response.row.class_id = incoming.class_id ?? response.row.class_id;
          response.row.inline_schema = incoming.inline_schema ?? response.row.inline_schema;
          response.row.schema_mode = incoming.schema_mode;
        }

        for (const [mediaType, mediaObj] of contentEntries) {
          if (response.mediaTypes.has(mediaType)) continue;
          response.mediaTypes.add(mediaType);
          const contentClassId = classIdFor(mediaObj?.$ref);
          rows.shared_path_response_content.push({
            shared_path_response_id: response.row.id,
            media_type: mediaType,
            class_id: contentClassId,
            inline_schema: contentClassId
              ? null
              : !mediaObj?.$ref && mediaObj?.schema
                ? buildStoredInlineSchema(mediaObj.schema as Record<string, unknown>)
                : { ...EMPTY_OBJECT_SCHEMA },
            item_schema: Boolean(mediaObj?.streamKind),
          });
        }
        rows.path_operation_response_link.push({
          path_operation_id: pathOperationId,
          shared_path_response_id: response.row.id,
          metadata: null,
        });
      }
    }
  }
  return rows;
}

/**
 * Write a version's security schemes in one statement; a scheme the version already has is
 * replaced. A name listed twice keeps its last definition.
 *
 * @param client The import's client.
 * @param versionId The version.
 * @param schemes The parsed schemes.
 */
async function importSecuritySchemes(
  client: BulkQueryable,
  versionId: string,
  schemes: ParsedSecurityScheme[],
): Promise<void> {
  const byName = new Map<string, Row>();
  for (const s of schemes) {
    byName.set(s.scheme_name, {
      version_id: versionId,
      scheme_name: s.scheme_name,
      scheme_type: s.scheme_type,
      in_location: s.in_location ?? null,
      param_name: s.param_name ?? null,
      http_scheme: s.http_scheme ?? null,
      description: s.description ?? null,
      data: s.data && Object.keys(s.data).length > 0 ? s.data : {},
    });
  }
  await bulkInsert(
    client,
    'version_security_scheme',
    ['version_id', 'scheme_name', 'scheme_type', 'in_location', 'param_name', 'http_scheme', 'description', 'data'],
    [...byName.values()],
    {
      conflict: `ON CONFLICT (version_id, scheme_name) DO UPDATE SET
         scheme_type = EXCLUDED.scheme_type,
         in_location = EXCLUDED.in_location,
         param_name = EXCLUDED.param_name,
         http_scheme = EXCLUDED.http_scheme,
         description = EXCLUDED.description,
         data = EXCLUDED.data,
         updated_at = CURRENT_TIMESTAMP`,
    },
  );
}

/** A pooled client: what {@link importOpenAPIPathsAndSecurity} checks out when it is given none. */
type ImportClient = BulkQueryable & { release?: () => void };

/**
 * Import paths, operations, parameters, request bodies, and responses.
 * Resolves $ref to class_id when the referenced class exists in the version.
 *
 * One transaction and one statement per table (DBP-1.9, #7192): about fifteen statements for
 * any specification of up to 5,000 rows per table.
 *
 * @param versionId The version to write into.
 * @param paths The parsed paths.
 * @param securitySchemes The parsed security schemes.
 * @param existingClient A client the caller already holds and is not using in a transaction; the
 *   import runs on it (one client per import job) and leaves it checked out. Omitted, a client is
 *   taken from the pool and released.
 * @returns `success`, or the error that rolled the import back.
 */
export async function importOpenAPIPathsAndSecurity(
  versionId: string,
  paths: ParsedPath[],
  securitySchemes: ParsedSecurityScheme[],
  existingClient?: BulkQueryable,
): Promise<{ success: boolean; error?: string }> {
  const client: ImportClient = existingClient ?? (await connectionPool.connect());
  try {
    await client.query('BEGIN');

    if (securitySchemes.length > 0) {
      await importSecuritySchemes(client, versionId, securitySchemes);
    }

    if (paths.length > 0) {
      const classRows = await client.query(CLASS_LOOKUP_SQL, [versionId]);
      const classNameToId = new Map<string, string>();
      for (const r of classRows.rows) {
        classNameToId.set(r.name, r.id);
      }
      const rows = buildPathImportRows(versionId, paths, classNameToId);
      for (const table of Object.keys(PATH_IMPORT_COLUMNS) as PathImportTable[]) {
        await bulkInsert(client, table, PATH_IMPORT_COLUMNS[table], rows[table]);
      }
    }

    await client.query('COMMIT');
    return { success: true };
  } catch (err) {
    try {
      await client.query('ROLLBACK');
    } catch {}
    return { success: false, error: (err as Error | undefined)?.message || 'Import paths/security failed' };
  } finally {
    if (!existingClient) client.release?.();
  }
}

/**
 * Server action: import paths and security schemes from OpenAPI into an existing version (#566).
 * Call from Paths Designer to capture paths from a pasted/uploaded spec.
 */
export async function importPathsFromOpenAPIForVersion(
  versionId: string,
  paths: ParsedPath[],
  securitySchemes: ParsedSecurityScheme[]
): Promise<{ success: boolean; error?: string }> {
  if (!versionId) {
    return { success: false, error: 'Version is required' };
  }
  if (!paths?.length && !securitySchemes?.length) {
    return { success: false, error: 'Spec has no paths or security schemes to import' };
  }
  return importOpenAPIPathsAndSecurity(versionId, paths || [], securitySchemes || []);
}
