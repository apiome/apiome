/**
 * Arazzo `sourceDescriptions` resolution and validation for the Projects importer
 * (AZ2, #3505).
 *
 * An Arazzo document names the API descriptions its steps call in `sourceDescriptions`
 * (`name`, `type` = `openapi` | `arazzo`, `url`). A step then names its target with
 * `operationId` (bare, `<source>.<operationId>`, or `$sourceDescriptions.<source>.<operationId>`)
 * or `operationPath` (`{$sourceDescriptions.<source>.url}#/paths/<pointer>/<method>`).
 *
 * {@link resolveArazzoSources} registers and validates each source against the documents
 * supplied with the import (the "bundle", keyed by member path, matched the same way the
 * Catalog importer matches a fileset), then resolves every step reference to an operation
 * of an in-bundle OpenAPI source. Nothing is dropped silently: every problem is a
 * structured {@link ArazzoResolutionIssue}, and an unresolved step keeps its raw reference.
 * The returned {@link ArazzoResolution} is the map the Workflow / WorkflowStep model (#2773)
 * consumes; persisting it is not done here.
 */

/** Arazzo documents are walked untyped, like the OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { listPathItemOperations } from '../../src/app/utils/openapi-path-operations';

/** Source types the Projects importer can resolve steps against. */
export const RECOGNIZED_SOURCE_TYPES = ['openapi', 'arazzo'] as const;

/** A recognized source type. */
export type ArazzoSourceType = (typeof RECOGNIZED_SOURCE_TYPES)[number];

/** Stable codes for {@link ArazzoResolutionIssue}. */
export type ArazzoResolutionIssueCode =
  /** A `sourceDescriptions` entry has no `name` or no `url`. */
  | 'SOURCE_INVALID'
  /** Two entries share a `name`; the first is kept. */
  | 'SOURCE_DUPLICATE'
  /** The declared `type` is neither `openapi` nor `arazzo`. */
  | 'SOURCE_TYPE_UNSUPPORTED'
  /** No document supplied with the import matches the source's `url`. */
  | 'SOURCE_NOT_IN_BUNDLE'
  /** The matched document is not the declared `type` (e.g. an Arazzo file declared `openapi`). */
  | 'SOURCE_TYPE_MISMATCH'
  /** A step's `operationId` / `operationPath` did not resolve; its raw reference is kept. */
  | 'STEP_REFERENCE_UNRESOLVED';

/** A structured resolution problem. */
export interface ArazzoResolutionIssue {
  code: ArazzoResolutionIssueCode;
  message: string;
  /** The `sourceDescriptions` name involved, when there is one. */
  source?: string;
  workflowId?: string;
  stepId?: string;
}

/** One registered `sourceDescriptions` entry. */
export interface ArazzoSourceRecord {
  name: string;
  /** The declared `type`, as written (absent when the entry declares none). */
  type?: string;
  url?: string;
  /**
   * - `resolved` — matched to a supplied document of a recognized type;
   * - `not-in-bundle` — no supplied document matches its `url`;
   * - `unsupported-type` — its declared type cannot be resolved against;
   * - `type-mismatch` — matched a document of another type.
   */
  status: 'resolved' | 'not-in-bundle' | 'unsupported-type' | 'type-mismatch';
  /** The bundle member path it matched, when resolved. */
  path?: string;
  /** The kind of the matched document (`openapi` / `arazzo`), when matched. */
  documentKind?: ArazzoSourceType;
}

/** An OpenAPI operation a step resolved to. */
export interface ResolvedOperation {
  operationId?: string;
  /** Path template, e.g. `/pets/{petId}`. */
  path: string;
  /** Upper-cased HTTP method, as the Projects importer stores it (`GET`, `QUERY`). */
  method: string;
}

/** How one workflow step's target resolved. */
export interface ArazzoStepResolution {
  workflowId: string;
  stepId: string;
  /** Which field named the target; `none` when the step names nothing. */
  kind: 'operationId' | 'operationPath' | 'workflowId' | 'none';
  /** The raw reference string, always kept. */
  reference?: string;
  /**
   * - `resolved` — {@link operation} is set;
   * - `unresolved` — kept raw, with a `STEP_REFERENCE_UNRESOLVED` issue;
   * - `not-applicable` — the step calls a workflow or names no target.
   */
  status: 'resolved' | 'unresolved' | 'not-applicable';
  /** The source the reference resolved in, or the one it named. */
  sourceName?: string;
  operation?: ResolvedOperation;
  /** Why an unresolved reference failed, in a few words. */
  reason?: string;
}

/** The resolution map exposed on the import result (for #2773). */
export interface ArazzoResolution {
  sources: ArazzoSourceRecord[];
  steps: ArazzoStepResolution[];
  issues: ArazzoResolutionIssue[];
}

/** Input to {@link resolveArazzoSources}. */
export interface ResolveArazzoSourcesInput {
  /** The parsed Arazzo document. */
  document: any;
  /** Parsed documents supplied with the import, keyed by member path (e.g. `specs/petstore.yaml`). */
  sourceDocuments?: Record<string, unknown>;
  /** The Arazzo document's own member path, used to resolve relative `url`s; root when absent. */
  documentPath?: string;
}

/** `$sourceDescriptions.<name>.<operationId>`. */
const SOURCE_EXPRESSION = /^\$sourceDescriptions\.([A-Za-z0-9_-]+)\.(.+)$/;

/** `{$sourceDescriptions.<name>.url}#<json pointer>`. */
const SOURCE_PATH_EXPRESSION = /^\{\$sourceDescriptions\.([A-Za-z0-9_-]+)\.url\}(#.*)?$/;

/** Return a trimmed non-empty string, or undefined. */
function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

/**
 * Normalize a POSIX path: drop `.` segments and empty segments, apply `..`.
 *
 * @param path - a relative path.
 * @returns the normalized path, without a leading slash.
 */
function normalizePath(path: string): string {
  const out: string[] = [];
  for (const segment of path.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') out.pop();
    else out.push(segment);
  }
  return out.join('/');
}

/**
 * Bundle member paths a source `url` could name: the url itself, then (for a relative
 * url) the url resolved against the Arazzo document's directory and against the bundle
 * root. Mirrors the Catalog importer's fileset matching.
 *
 * @param url - the declared source url.
 * @param documentPath - the Arazzo document's member path.
 * @returns candidate keys, most specific first.
 */
function memberCandidates(url: string, documentPath?: string): string[] {
  const candidates = [url];
  const withoutFragment = url.split('#', 1)[0];
  if (!withoutFragment || url.includes('://')) return candidates;
  const relative = withoutFragment.replace(/^\/+/, '');
  const slash = documentPath ? documentPath.lastIndexOf('/') : -1;
  const directory = slash >= 0 ? documentPath!.slice(0, slash) : '';
  if (directory) candidates.push(normalizePath(`${directory}/${relative}`));
  candidates.push(normalizePath(relative));
  return Array.from(new Set(candidates));
}

/** The kind of a parsed document, from its version marker. */
function documentKind(doc: unknown): ArazzoSourceType | undefined {
  if (!doc || typeof doc !== 'object') return undefined;
  const d = doc as Record<string, unknown>;
  if (d.arazzo !== undefined) return 'arazzo';
  if (d.openapi !== undefined || d.swagger !== undefined) return 'openapi';
  return undefined;
}

/** Decode one JSON-pointer token (`~1` → `/`, `~0` → `~`, then percent-decoding). */
function decodePointerToken(token: string): string {
  const unescaped = token.replace(/~1/g, '/').replace(/~0/g, '~');
  try {
    return decodeURIComponent(unescaped);
  } catch {
    return unescaped;
  }
}

/** Operations of one OpenAPI document, indexed for lookup. */
interface OperationIndex {
  byId: Map<string, ResolvedOperation>;
  /** Keyed `<path> <METHOD>`. */
  byPathMethod: Map<string, ResolvedOperation>;
}

/**
 * Index an OpenAPI document's operations (fixed verbs, `query` and `additionalOperations`).
 *
 * @param doc - an OpenAPI document.
 * @returns the operations by `operationId` and by path + method.
 */
function indexOperations(doc: any): OperationIndex {
  const index: OperationIndex = { byId: new Map(), byPathMethod: new Map() };
  const paths = doc && typeof doc === 'object' ? doc.paths : undefined;
  if (!paths || typeof paths !== 'object') return index;
  for (const [path, pathItem] of Object.entries<any>(paths)) {
    for (const { normalizedMethod, operation } of listPathItemOperations(pathItem).operations) {
      const resolved: ResolvedOperation = { path, method: normalizedMethod };
      const operationId = text(operation.operationId);
      if (operationId) {
        resolved.operationId = operationId;
        if (!index.byId.has(operationId)) index.byId.set(operationId, resolved);
      }
      index.byPathMethod.set(`${path} ${normalizedMethod}`, resolved);
    }
  }
  return index;
}

/**
 * Register and validate a document's `sourceDescriptions`, then resolve every workflow
 * step's `operationId` / `operationPath` against the in-bundle OpenAPI sources.
 *
 * @param input - the Arazzo document, the documents supplied with the import, and the
 *   Arazzo document's member path.
 * @returns the sources, the per-step resolutions and the issues found.
 */
export function resolveArazzoSources(input: ResolveArazzoSourcesInput): ArazzoResolution {
  const { document, sourceDocuments = {}, documentPath } = input;
  const sources: ArazzoSourceRecord[] = [];
  const issues: ArazzoResolutionIssue[] = [];
  const indexes = new Map<string, OperationIndex>();

  // 1. Register and validate each source.
  const declared = Array.isArray(document?.sourceDescriptions) ? document.sourceDescriptions : [];
  declared.forEach((entry: any, position: number) => {
    const name = text(entry?.name);
    const url = text(entry?.url) ?? text(entry?.$ref);
    const type = text(entry?.type);
    if (!name || !url) {
      issues.push({
        code: 'SOURCE_INVALID',
        message: `sourceDescriptions[${position}] has no ${name ? 'url' : 'name'}; it was ignored.`,
        ...(name ? { source: name } : {}),
      });
      return;
    }
    if (sources.some((s) => s.name === name)) {
      issues.push({ code: 'SOURCE_DUPLICATE', source: name, message: `Source "${name}" is declared more than once; the first is kept.` });
      return;
    }

    const record: ArazzoSourceRecord = { name, url, status: 'not-in-bundle', ...(type ? { type } : {}) };
    sources.push(record);

    if (type && !(RECOGNIZED_SOURCE_TYPES as readonly string[]).includes(type)) {
      record.status = 'unsupported-type';
      issues.push({
        code: 'SOURCE_TYPE_UNSUPPORTED',
        source: name,
        message: `Source "${name}" has type "${type}"; only openapi and arazzo sources are resolved.`,
      });
      return;
    }

    const memberPath = memberCandidates(url, documentPath).find(
      (candidate) => candidate !== documentPath && Object.prototype.hasOwnProperty.call(sourceDocuments, candidate)
    );
    if (memberPath === undefined) {
      issues.push({
        code: 'SOURCE_NOT_IN_BUNDLE',
        source: name,
        message: `Source "${name}" (${url}) is not in the import bundle; steps that call it keep their raw reference.`,
      });
      return;
    }

    const matched = sourceDocuments[memberPath];
    const kind = documentKind(matched);
    if (!kind || (type && kind !== type)) {
      record.status = 'type-mismatch';
      issues.push({
        code: 'SOURCE_TYPE_MISMATCH',
        source: name,
        message: `Source "${name}" matched ${memberPath}, which is ${kind ? `an ${kind} document` : 'not an OpenAPI or Arazzo document'}${type ? `, not ${type}` : ''}.`,
      });
      return;
    }

    record.status = 'resolved';
    record.path = memberPath;
    record.documentKind = kind;
    if (kind === 'openapi') indexes.set(name, indexOperations(matched));
  });

  // 2. Resolve each step.
  const steps: ArazzoStepResolution[] = [];
  const workflows = Array.isArray(document?.workflows) ? document.workflows : [];
  for (const workflow of workflows) {
    const workflowId = text(workflow?.workflowId) ?? '';
    const workflowSteps = Array.isArray(workflow?.steps) ? workflow.steps : [];
    workflowSteps.forEach((step: any, position: number) => {
      const stepId = text(step?.stepId) ?? `step${position}`;
      const resolution = resolveStep(step, { workflowId, stepId, sources, indexes });
      steps.push(resolution);
      if (resolution.status === 'unresolved') {
        issues.push({
          code: 'STEP_REFERENCE_UNRESOLVED',
          workflowId,
          stepId,
          ...(resolution.sourceName ? { source: resolution.sourceName } : {}),
          message: `Step "${workflowId}.${stepId}" reference "${resolution.reference}" did not resolve (${resolution.reason}); the raw reference is kept.`,
        });
      }
    });
  }

  return { sources, steps, issues };
}

/** Context shared by the per-step resolution. */
interface StepContext {
  workflowId: string;
  stepId: string;
  sources: ArazzoSourceRecord[];
  indexes: Map<string, OperationIndex>;
}

/**
 * Resolve one step's target.
 *
 * @param step - the step object.
 * @param ctx - the workflow/step ids and the registered sources.
 * @returns the step resolution (never throws; unresolved references keep their raw string).
 */
function resolveStep(step: any, ctx: StepContext): ArazzoStepResolution {
  const base = { workflowId: ctx.workflowId, stepId: ctx.stepId };
  const operationId = text(step?.operationId);
  const operationPath = text(step?.operationPath);
  const workflowRef = text(step?.workflowId);

  if (operationId) return { ...base, kind: 'operationId', reference: operationId, ...resolveOperationId(operationId, ctx) };
  if (operationPath) return { ...base, kind: 'operationPath', reference: operationPath, ...resolveOperationPath(operationPath, ctx) };
  if (workflowRef) return { ...base, kind: 'workflowId', reference: workflowRef, status: 'not-applicable' };
  return { ...base, kind: 'none', status: 'not-applicable' };
}

/** Result fields of a step resolution. */
type ResolutionFields = Pick<ArazzoStepResolution, 'status' | 'sourceName' | 'operation' | 'reason'>;

/** Why a named source cannot be searched, or undefined when it can. */
function sourceProblem(name: string, ctx: StepContext): string | undefined {
  const source = ctx.sources.find((s) => s.name === name);
  if (!source) return `source "${name}" is not declared`;
  if (source.status !== 'resolved') return `source "${name}" is ${source.status.replace(/-/g, ' ')}`;
  if (!ctx.indexes.has(name)) return `source "${name}" is not an OpenAPI document`;
  return undefined;
}

/**
 * Resolve an `operationId`: `$sourceDescriptions.<source>.<id>`, `<source>.<id>` (when
 * `<source>` is a declared source), or a bare id searched across every in-bundle
 * OpenAPI source (it must match exactly one).
 */
function resolveOperationId(reference: string, ctx: StepContext): ResolutionFields {
  let sourceName: string | undefined;
  let id = reference;
  const expression = SOURCE_EXPRESSION.exec(reference);
  if (expression) {
    [, sourceName, id] = expression;
  } else {
    const dot = reference.indexOf('.');
    const prefix = dot > 0 ? reference.slice(0, dot) : '';
    if (prefix && ctx.sources.some((s) => s.name === prefix)) {
      sourceName = prefix;
      id = reference.slice(dot + 1);
    }
  }

  if (sourceName) {
    const problem = sourceProblem(sourceName, ctx);
    if (problem) return { status: 'unresolved', sourceName, reason: problem };
    const operation = ctx.indexes.get(sourceName)!.byId.get(id);
    return operation
      ? { status: 'resolved', sourceName, operation }
      : { status: 'unresolved', sourceName, reason: `no operation "${id}" in source "${sourceName}"` };
  }

  const matches = Array.from(ctx.indexes.entries()).filter(([, index]) => index.byId.has(id));
  if (matches.length === 1) {
    const [name, index] = matches[0];
    return { status: 'resolved', sourceName: name, operation: index.byId.get(id) };
  }
  if (matches.length > 1) {
    return { status: 'unresolved', reason: `"${id}" is in several sources (${matches.map(([n]) => n).join(', ')}); name the source` };
  }
  return { status: 'unresolved', reason: ctx.indexes.size === 0 ? 'no OpenAPI source is in the import bundle' : `no source has operation "${id}"` };
}

/**
 * Resolve an `operationPath`: `{$sourceDescriptions.<source>.url}#/paths/<path>/<method>`.
 */
function resolveOperationPath(reference: string, ctx: StepContext): ResolutionFields {
  const expression = SOURCE_PATH_EXPRESSION.exec(reference);
  if (!expression) return { status: 'unresolved', reason: 'not a {$sourceDescriptions.<name>.url}#/paths/... expression' };
  const [, sourceName, fragment = ''] = expression;
  const problem = sourceProblem(sourceName, ctx);
  if (problem) return { status: 'unresolved', sourceName, reason: problem };

  const tokens = fragment.replace(/^#/, '').split('/').slice(1).map(decodePointerToken);
  if (tokens.length !== 3 || tokens[0] !== 'paths') {
    return { status: 'unresolved', sourceName, reason: 'the pointer does not name #/paths/<path>/<method>' };
  }
  const [, path, method] = tokens;
  const operation = ctx.indexes.get(sourceName)!.byPathMethod.get(`${path} ${method.toUpperCase()}`);
  return operation
    ? { status: 'resolved', sourceName, operation }
    : { status: 'unresolved', sourceName, reason: `no ${method.toUpperCase()} ${path} in source "${sourceName}"` };
}

/**
 * Plain-text warnings for an import's warning list, one per issue.
 *
 * @param resolution - a resolution map.
 * @returns the issue messages, in order.
 */
export function arazzoResolutionWarnings(resolution: ArazzoResolution): string[] {
  return resolution.issues.map((issue) => issue.message);
}
