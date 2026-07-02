/**
 * Live 0–100 PATH QUALITY for Studio Paths (#2656).
 * Weighted dimensions align with the roadmap: operationId, documentation, parameter typing,
 * error responses, $ref resolution, response content, duplicate operationIds.
 */

import { getNumericScoreTier, letterGradeFromOverallPercent } from '@/app/utils/numeric-score-tier';

const METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'] as const;

const W_OPERATION_ID = 0.15;
const W_DESCRIPTIONS = 0.2;
const W_PARAM_TYPING = 0.15;
const W_ERROR_RESPONSES = 0.15;
const W_REFS = 0.15;
const W_RESPONSE_CONTENT = 0.1;
const W_DUPLICATE_OP_IDS = 0.1;

function formatWeightLabel(weight: number): string {
  return `${weight * 100}%`;
}

/** Human-readable weight labels for PATH QUALITY dialog derived from {@link computePathQuality} weights. */
export const PATH_QUALITY_WEIGHT_LABELS = {
  operationId: formatWeightLabel(W_OPERATION_ID),
  descriptions: formatWeightLabel(W_DESCRIPTIONS),
  parameterTyping: formatWeightLabel(W_PARAM_TYPING),
  errorResponses: formatWeightLabel(W_ERROR_RESPONSES),
  references: formatWeightLabel(W_REFS),
  responseContent: formatWeightLabel(W_RESPONSE_CONTENT),
  duplicateOperationIds: formatWeightLabel(W_DUPLICATE_OP_IDS),
};

export interface PathQualityBreakdownRow {
  id:
    | 'operationId'
    | 'descriptions'
    | 'parameterTyping'
    | 'errorResponses'
    | 'references'
    | 'responseContent'
    | 'duplicateOperationIds';
  label: string;
  value: number;
  effectiveWeight: number;
  contribution: number;
}

export interface PathQualityIssue {
  id: string;
  message: string;
  /** React Flow node id when the path is open on the Paths canvas (operation node id = DB id). */
  focusNodeId?: string;
}

export interface PathQualityDetail {
  overall: number;
  letterGrade: ReturnType<typeof letterGradeFromOverallPercent>;
  tier: ReturnType<typeof getNumericScoreTier>;
  rows: PathQualityBreakdownRow[];
  issues: PathQualityIssue[];
}

function schemaLooksTyped(schema: unknown): boolean {
  if (schema === null || schema === undefined) return false;
  if (typeof schema !== 'object') return false;
  const s = schema as Record<string, unknown>;
  if (typeof s.$ref === 'string' && s.$ref.length > 0) return true;
  if (Array.isArray(s.oneOf) && s.oneOf.length > 0) return true;
  if (Array.isArray(s.anyOf) && s.anyOf.length > 0) return true;
  if (Array.isArray(s.allOf) && s.allOf.length > 0) return true;
  if (s.not !== undefined) return true;
  if (typeof s.type === 'string' && s.type.length > 0) return true;
  return false;
}

function collectRefsFromValue(value: unknown, out: Set<string>): void {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) {
    for (const v of value) collectRefsFromValue(v, out);
    return;
  }
  if (typeof value !== 'object') return;
  const o = value as Record<string, unknown>;
  if (typeof o.$ref === 'string' && o.$ref.startsWith('#/')) {
    out.add(o.$ref);
  }
  for (const v of Object.values(o)) {
    collectRefsFromValue(v, out);
  }
}

function decodeJsonPointerSegment(segment: string): string {
  // RFC 6901: ~1 → '/', ~0 → '~' (in that order)
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

function resolveInternalRef(ref: string, specRoot: Record<string, unknown>): boolean {
  if (!ref.startsWith('#/')) return true;
  const parts = ref.slice(2).split('/').filter(Boolean).map(decodeJsonPointerSegment);
  let cur: unknown = specRoot;
  for (const p of parts) {
    if (cur === null || typeof cur !== 'object') return false;
    cur = (cur as Record<string, unknown>)[p];
  }
  return cur !== undefined;
}

function opDocPresent(op: Record<string, unknown>): boolean {
  const summary = op.summary;
  const description = op.description;
  const hasSummary = typeof summary === 'string' && summary.trim().length > 0;
  const hasDesc = typeof description === 'string' && description.trim().length > 0;
  return hasSummary || hasDesc;
}

function pathItemDocPresent(pathItem: Record<string, unknown>): boolean {
  const summary = pathItem.summary;
  const description = pathItem.description;
  const hasSummary = typeof summary === 'string' && summary.trim().length > 0;
  const hasDesc = typeof description === 'string' && description.trim().length > 0;
  return hasSummary || hasDesc;
}

function paramHasDescription(param: Record<string, unknown>): boolean {
  const d = param.description;
  return typeof d === 'string' && d.trim().length > 0;
}

function statusIsError(code: string): boolean {
  const n = parseInt(code, 10);
  return !Number.isNaN(n) && n >= 400;
}

function responseHasUsefulContent(res: Record<string, unknown>): boolean {
  const content = res.content;
  if (content && typeof content === 'object' && Object.keys(content as object).length > 0) {
    return true;
  }
  const desc = res.description;
  if (typeof desc === 'string' && desc.trim().length > 0) {
    return true;
  }
  return false;
}

/**
 * Computes PATH QUALITY from the OpenAPI `paths` map and optional full spec for $ref resolution.
 */
export function computePathQuality(
  pathsObject: Record<string, unknown>,
  mergedSpec: Record<string, unknown> | null | undefined
): PathQualityDetail {
  const specRoot = mergedSpec && typeof mergedSpec === 'object' ? mergedSpec : ({} as Record<string, unknown>);

  let totalOps = 0;
  let opsWithOperationId = 0;
  let opsWithNonEmptyOperationId = 0;
  const distinctOperationIdStrings = new Set<string>();
  let opPathDocHits = 0;
  let paramTypingChecks = 0;
  let paramTypingHits = 0;
  let paramDescChecks = 0;
  let paramDescHits = 0;
  let errorChecks = 0;
  let errorHits = 0;
  let contentChecks = 0;
  let contentHits = 0;

  const operationIds = new Map<string, number>();
  const refsInPaths = new Set<string>();
  const issues: PathQualityIssue[] = [];
  let issueSeq = 0;
  const addIssue = (message: string, focusNodeId?: string) => {
    issueSeq += 1;
    issues.push({ id: `pq-${issueSeq}`, message, focusNodeId });
  };

  for (const [pathKey, pathVal] of Object.entries(pathsObject)) {
    if (!pathVal || typeof pathVal !== 'object') continue;
    const pathItem = pathVal as Record<string, unknown>;
    collectRefsFromValue(pathItem, refsInPaths);

    for (const method of METHODS) {
      const rawOp = pathItem[method];
      if (!rawOp || typeof rawOp !== 'object') continue;
      const op = rawOp as Record<string, unknown>;
      totalOps += 1;

      const opDbId =
        typeof op['x-apiome-operation-id'] === 'string' ? (op['x-apiome-operation-id'] as string) : undefined;
      const focusNodeId = opDbId;

      const oid = op.operationId;
      if (typeof oid === 'string' && oid.trim().length > 0) {
        opsWithOperationId += 1;
        const k = oid.trim();
        opsWithNonEmptyOperationId += 1;
        distinctOperationIdStrings.add(k);
        operationIds.set(k, (operationIds.get(k) ?? 0) + 1);
      } else {
        addIssue(`${pathKey} ${method.toUpperCase()}: missing operationId`, focusNodeId);
      }

      if (opDocPresent(op) || pathItemDocPresent(pathItem)) {
        opPathDocHits += 1;
      } else {
        addIssue(`${pathKey} ${method.toUpperCase()}: add a summary or description on the operation or path`, focusNodeId);
      }

      const params = op.parameters;
      if (Array.isArray(params)) {
        for (const p of params) {
          if (!p || typeof p !== 'object') continue;
          const param = p as Record<string, unknown>;
          paramTypingChecks += 1;
          if (schemaLooksTyped(param.schema)) {
            paramTypingHits += 1;
          } else {
            const pname = typeof param.name === 'string' ? param.name : '(parameter)';
            addIssue(`${pathKey} ${method.toUpperCase()}: parameter "${pname}" needs a typed schema`, focusNodeId);
          }
          paramDescChecks += 1;
          if (paramHasDescription(param)) {
            paramDescHits += 1;
          } else {
            const pname = typeof param.name === 'string' ? param.name : '(parameter)';
            addIssue(`${pathKey} ${method.toUpperCase()}: parameter "${pname}" has no description`, focusNodeId);
          }
        }
      }

      const methodUpper = method.toUpperCase();
      if (methodUpper !== 'OPTIONS' && methodUpper !== 'HEAD') {
        errorChecks += 1;
        const responses = op.responses;
        let hasErr = false;
        if (responses && typeof responses === 'object') {
          for (const code of Object.keys(responses as object)) {
            if (statusIsError(code)) {
              hasErr = true;
              break;
            }
          }
        }
        if (hasErr) {
          errorHits += 1;
        } else {
          addIssue(
            `${pathKey} ${method.toUpperCase()}: add at least one 4xx/5xx response for error handling`,
            focusNodeId
          );
        }
      }

      const responses = op.responses;
      if (responses && typeof responses === 'object') {
        for (const [code, resVal] of Object.entries(responses as Record<string, unknown>)) {
          if (!resVal || typeof resVal !== 'object') continue;
          const res = resVal as Record<string, unknown>;
          const n = parseInt(code, 10);
          if (Number.isNaN(n)) continue;
          if (n >= 200 && n < 300 && n !== 204) {
            contentChecks += 1;
            if (responseHasUsefulContent(res)) {
              contentHits += 1;
            } else {
              addIssue(
                `${pathKey} ${method.toUpperCase()}: ${code} response has no content or description`,
                focusNodeId
              );
            }
          }
        }
      }

    }
  }

  for (const [opid, count] of operationIds.entries()) {
    if (count > 1) {
      addIssue(`Duplicate operationId "${opid}" (${count} operations)`);
    }
  }

  let refChecks = 0;
  let refHits = 0;
  for (const ref of refsInPaths) {
    refChecks += 1;
    if (resolveInternalRef(ref, specRoot)) {
      refHits += 1;
    } else {
      addIssue(`Broken $ref: ${ref}`);
    }
  }

  const scoreOperationId = totalOps === 0 ? 100 : (opsWithOperationId / totalOps) * 100;
  const scoreOpPathDoc = totalOps === 0 ? 100 : (opPathDocHits / totalOps) * 100;
  const scoreParamDocs = paramDescChecks === 0 ? 100 : (paramDescHits / paramDescChecks) * 100;
  const scoreDescriptions =
    paramDescChecks === 0 ? scoreOpPathDoc : scoreOpPathDoc * 0.55 + scoreParamDocs * 0.45;
  const scoreParamTyping = paramTypingChecks === 0 ? 100 : (paramTypingHits / paramTypingChecks) * 100;
  const scoreErrors = errorChecks === 0 ? 100 : (errorHits / errorChecks) * 100;
  const scoreRefs = refChecks === 0 ? 100 : (refHits / refChecks) * 100;
  const scoreContent = contentChecks === 0 ? 100 : (contentHits / contentChecks) * 100;
  const scoreDup =
    opsWithNonEmptyOperationId === 0
      ? 100
      : (distinctOperationIdStrings.size / opsWithNonEmptyOperationId) * 100;

  const rawOverall =
    W_OPERATION_ID * scoreOperationId +
    W_DESCRIPTIONS * scoreDescriptions +
    W_PARAM_TYPING * scoreParamTyping +
    W_ERROR_RESPONSES * scoreErrors +
    W_REFS * scoreRefs +
    W_RESPONSE_CONTENT * scoreContent +
    W_DUPLICATE_OP_IDS * scoreDup;

  const overall = totalOps === 0 ? 0 : Math.min(100, Math.max(0, Math.round(rawOverall)));

  const tier = getNumericScoreTier(overall);
  const letterGrade = letterGradeFromOverallPercent(overall);

  const rows: PathQualityBreakdownRow[] = [
    {
      id: 'operationId',
      label: 'operationId present',
      value: scoreOperationId,
      effectiveWeight: W_OPERATION_ID,
      contribution: W_OPERATION_ID * scoreOperationId,
    },
    {
      id: 'descriptions',
      label: 'Documentation (path, operation, parameters)',
      value: scoreDescriptions,
      effectiveWeight: W_DESCRIPTIONS,
      contribution: W_DESCRIPTIONS * scoreDescriptions,
    },
    {
      id: 'parameterTyping',
      label: 'Parameter schemas typed',
      value: scoreParamTyping,
      effectiveWeight: W_PARAM_TYPING,
      contribution: W_PARAM_TYPING * scoreParamTyping,
    },
    {
      id: 'errorResponses',
      label: 'Error responses (4xx/5xx)',
      value: scoreErrors,
      effectiveWeight: W_ERROR_RESPONSES,
      contribution: W_ERROR_RESPONSES * scoreErrors,
    },
    {
      id: 'references',
      label: '$ref resolution (paths → components)',
      value: scoreRefs,
      effectiveWeight: W_REFS,
      contribution: W_REFS * scoreRefs,
    },
    {
      id: 'responseContent',
      label: '2xx response content or description',
      value: scoreContent,
      effectiveWeight: W_RESPONSE_CONTENT,
      contribution: W_RESPONSE_CONTENT * scoreContent,
    },
    {
      id: 'duplicateOperationIds',
      label: 'Unique operationIds',
      value: scoreDup,
      effectiveWeight: W_DUPLICATE_OP_IDS,
      contribution: W_DUPLICATE_OP_IDS * scoreDup,
    },
  ];

  return {
    overall,
    letterGrade,
    tier,
    rows,
    issues: issues.sort((a, b) => a.message.localeCompare(b.message)),
  };
}

/** When the merged spec has no path operations, the header should show an em dash instead of a score. */
export function pathQualityHasOperations(pathsObject: Record<string, unknown>): boolean {
  let n = 0;
  for (const pathVal of Object.values(pathsObject)) {
    if (!pathVal || typeof pathVal !== 'object') continue;
    const pathItem = pathVal as Record<string, unknown>;
    for (const method of METHODS) {
      if (pathItem[method] && typeof pathItem[method] === 'object') n += 1;
    }
  }
  return n > 0;
}
