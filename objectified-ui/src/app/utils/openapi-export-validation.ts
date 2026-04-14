/**
 * OpenAPI export validation for Studio Code download (#2655 / P-16).
 * Uses @seriousme/openapi-schema-validator (OAS JSON Schema for 3.2.x) plus semantic checks.
 */

export type OpenAPIExportIssueSeverity = 'error' | 'warning';

export interface OpenAPIExportIssue {
  severity: OpenAPIExportIssueSeverity;
  message: string;
  /** JSON Pointer–style path when known */
  path?: string;
}

export interface OpenAPIExportValidationResult {
  errors: OpenAPIExportIssue[];
  warnings: OpenAPIExportIssue[];
  /** False if the schema validator threw (caller should surface limitation; do not claim full validation). */
  schemaValidationCompleted: boolean;
  /** Human-readable note on validator behavior (release notes / UI). */
  validatorNote: string;
}

export const VALIDATOR_NOTE =
  'Document structure is validated with @seriousme/openapi-schema-validator against the OpenAPI 3.2 JSON Schema, plus Objectified checks for operationId, path parameters, and local $ref targets.';

const HTTP_METHODS = new Set([
  'get',
  'put',
  'post',
  'delete',
  'options',
  'head',
  'patch',
  'trace',
]);

/** Encode a string as a JSON Pointer segment (RFC 6901: `~` → `~0`, `/` → `~1`). */
function encodeJsonPointerSegment(s: string): string {
  return s.replace(/~/g, '~0').replace(/\//g, '~1');
}

function pathTemplateParamNames(pathKey: string): string[] {
  const re = /\{([^}]+)\}/g;
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(pathKey)) !== null) {
    out.push(m[1]);
  }
  return out;
}

export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Merge OpenAPI path-level and operation-level parameters; later entries win on (name,in). */
function mergeParameters(
  pathLevel: unknown,
  opLevel: unknown
): Array<Record<string, unknown>> {
  const pathArr = Array.isArray(pathLevel) ? pathLevel : [];
  const opArr = Array.isArray(opLevel) ? opLevel : [];
  const byKey = new Map<string, Record<string, unknown>>();
  for (const p of pathArr) {
    if (!isPlainObject(p)) continue;
    const name = typeof p.name === 'string' ? p.name : '';
    const inn = typeof p.in === 'string' ? p.in : '';
    byKey.set(`${inn}:${name}`, p);
  }
  for (const p of opArr) {
    if (!isPlainObject(p)) continue;
    const name = typeof p.name === 'string' ? p.name : '';
    const inn = typeof p.in === 'string' ? p.in : '';
    byKey.set(`${inn}:${name}`, p);
  }
  return [...byKey.values()];
}

function collectLocalJsonPointers(obj: unknown, refs: Set<string>, basePath: string): void {
  if (obj === null || obj === undefined) return;
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => collectLocalJsonPointers(item, refs, `${basePath}/${i}`));
    return;
  }
  if (!isPlainObject(obj)) return;
  const ref = obj.$ref;
  if (typeof ref === 'string' && ref.startsWith('#/')) {
    refs.add(ref);
  }
  for (const [k, v] of Object.entries(obj)) {
    collectLocalJsonPointers(v, refs, `${basePath}/${k}`);
  }
}

function localPointerExists(doc: Record<string, unknown>, pointer: string): boolean {
  if (!pointer.startsWith('#/')) return true;
  const segments = pointer.slice(2).split('/').map((s) => s.replace(/~1/g, '/').replace(/~0/g, '~'));
  let node: unknown = doc;
  for (const seg of segments) {
    if (node === null || typeof node !== 'object') return false;
    if (!Object.prototype.hasOwnProperty.call(node as object, seg)) return false;
    node = (node as Record<string, unknown>)[seg];
  }
  return node !== undefined;
}

export function formatSchemaValidatorErrors(errors: unknown): OpenAPIExportIssue[] {
  if (errors === undefined || errors === null) return [];
  if (Array.isArray(errors)) {
    return errors.map((e: unknown, i: number) => {
      if (isPlainObject(e)) {
        const instancePath =
          typeof e.instancePath === 'string'
            ? e.instancePath
            : typeof (e as { path?: string }).path === 'string'
              ? (e as { path: string }).path
              : undefined;
        const msg =
          typeof e.message === 'string'
            ? e.message
            : typeof (e as { keyword?: string }).keyword === 'string'
              ? `Schema validation (${(e as { keyword: string }).keyword})`
              : JSON.stringify(e);
        return {
          severity: 'error' as const,
          message: msg,
          path: instancePath,
        };
      }
      return { severity: 'error' as const, message: String(e), path: `[${i}]` };
    });
  }
  if (typeof errors === 'string') {
    return [{ severity: 'error', message: errors }];
  }
  return [{ severity: 'error', message: JSON.stringify(errors) }];
}

/**
 * Semantic rules: duplicate operationId, path `{param}` coverage, local $ref targets,
 * documentation warnings. Runs without the external validator.
 */
export function validateOpenAPISemantics(spec: Record<string, unknown>): OpenAPIExportIssue[] {
  const issues: OpenAPIExportIssue[] = [];
  const operationIds = new Map<string, string>();

  const paths = spec.paths;
  if (!isPlainObject(paths)) {
    return issues;
  }

  for (const [pathKey, pathItem] of Object.entries(paths)) {
    if (!isPlainObject(pathItem)) continue;

    const templateNames = new Set(pathTemplateParamNames(pathKey));

    for (const method of HTTP_METHODS) {
      const op = pathItem[method];
      if (!isPlainObject(op)) continue;

      const oid = op.operationId;
      if (typeof oid === 'string' && oid.length > 0) {
        const loc = `${pathKey} ${method.toUpperCase()}`;
        const prev = operationIds.get(oid);
        if (prev !== undefined) {
          issues.push({
            severity: 'error',
            message: `Duplicate operationId "${oid}" (also used at ${prev}).`,
            path: `/paths/${encodeJsonPointerSegment(pathKey)}/${method}/operationId`,
          });
        } else {
          operationIds.set(oid, loc);
        }
      }

      const params = mergeParameters(pathItem.parameters, op.parameters);
      const pathParams = params.filter(
        (p) => isPlainObject(p) && p.in === 'path' && typeof p.name === 'string'
      ) as Array<{ name: string }>;
      const pathParamNames = new Set(pathParams.map((p) => p.name));

      for (const name of templateNames) {
        if (!pathParamNames.has(name)) {
          issues.push({
            severity: 'error',
            message: `Path template "{${name}}" has no matching path parameter on ${method.toUpperCase()} ${pathKey}.`,
            path: `/paths/${encodeJsonPointerSegment(pathKey)}`,
          });
        }
      }
      for (const name of pathParamNames) {
        if (!templateNames.has(name)) {
          issues.push({
            severity: 'error',
            message: `Path parameter "${name}" is not present in the path template ${pathKey}.`,
            path: `/paths/${encodeJsonPointerSegment(pathKey)}/${method}/parameters`,
          });
        }
      }

      const summary = op.summary;
      const description = op.description;
      const hasDoc =
        (typeof summary === 'string' && summary.trim().length > 0) ||
        (typeof description === 'string' && description.trim().length > 0);
      if (!hasDoc) {
        issues.push({
          severity: 'warning',
          message: `Operation ${method.toUpperCase()} ${pathKey} has no summary or description.`,
          path: `/paths/${encodeJsonPointerSegment(pathKey)}/${method}`,
        });
      }

      const responses = op.responses;
      if (isPlainObject(responses)) {
        for (const [code, resp] of Object.entries(responses)) {
          if (!isPlainObject(resp)) continue;
          const rd = resp.description;
          if (typeof rd !== 'string' || rd.trim().length === 0) {
            issues.push({
              severity: 'warning',
              message: `Response ${code} for ${method.toUpperCase()} ${pathKey} has no description.`,
              path: `/paths/${encodeJsonPointerSegment(pathKey)}/${method}/responses/${code}`,
            });
          }
        }
      }
    }
  }

  const refs = new Set<string>();
  collectLocalJsonPointers(spec, refs, '#');
  for (const ref of refs) {
    if (!ref.startsWith('#/')) {
      issues.push({
        severity: 'warning',
        message: `External or non-local $ref is not verified in export: ${ref}`,
        path: ref,
      });
      continue;
    }
    if (!localPointerExists(spec, ref)) {
      issues.push({
        severity: 'error',
        message: `Unresolved local $ref: ${ref}`,
        path: ref,
      });
    }
  }

  return issues;
}

/**
 * Full validation (`validateOpenAPIExport`) runs in a **server action** — the schema validator uses Node (`fs`) and cannot ship to the browser bundle.
 * @see `./openapi-export-validation-server`
 */
