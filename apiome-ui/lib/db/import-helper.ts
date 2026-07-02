'use server';

import {
  PoolClient,
  getTransactionClient,
  beginTransaction,
  commitTransaction,
  rollbackTransaction,
  releaseClient,
  createProjectTx,
  mergeProjectImportOpenApiFieldsTx,
  createVersionTx,
  createPropertiesBatchTx,
  PropertyInsert,
  createClassTx,
  addPropertiesToClassBatchTx,
  ClassPropertyInsert,
  getClassesWithPropertiesAndTagsTx,
  getLatestVersionUuidForProjectTx,
  getProjectIdBySlugTx,
  getVersionUuidForCatalogVersionLineTx,
  listProjectLibraryPropertiesTx,
} from './import-transaction';
import { ImportSourceKind, getImporter, NormalizedClass, NormalizedProperty } from '../importers';
import { randomUUID } from 'crypto';
import { withRetry } from '../retry';
import { permanentDeleteProject } from './helper';
import { extractPaths, extractSecuritySchemes } from '../../src/app/utils/openapi-import';
import { importOpenAPIPathsAndSecurity } from './import-openapi-paths-security';
import { recordTenantRepositoryImport, upsertRepositoryImportSpec } from './repository-import-metrics';
import { mergeOpenApiDocumentIntoCatalogTargets } from '../rest-spec-import-merge';

export type ImportJobState = 'queued' | 'running' | 'pending-approval' | 'committing' | 'completed' | 'failed' | 'canceled' | 'rolled-back';

export type ImportLogLevel = 'info' | 'warn' | 'error';

export interface ImportEvent {
  id: string;
  ts: number;
  level: ImportLogLevel;
  code: string;
  message: string;
  context?: any;
}

export interface ProgressEvent {
  phase:
    | 'initializing'
    | 'creating-project'
    | 'creating-version'
    | 'creating-properties'
    | 'creating-classes'
    | 'linking-properties'
    | 'verifying'
    | 'finalizing';
  total: number;
  completed: number;
  currentItem?: string;
}

export interface ImportStatus {
  jobId: string;
  state: ImportJobState;
  percent: number;
  events: ImportEvent[];
  progress?: ProgressEvent;
  summary?: any;
}

export interface ImportJobInput {
  tenantId: string;
  userId: string;
  sourceKind: ImportSourceKind;
  document: any;
  project: { name: string; slug: string; description?: string | null };
  version: { versionId: string; description?: string | null };
  /** JSON merged into apiome.projects.metadata when creating a new project (REST import: OpenAPI info.contact, etc.). */
  projectMetadata?: Record<string, unknown> | null;
  options: {
    selectedSchemas: string[];
    autoLayout?: boolean;
    createRelationships?: boolean;
    /** When true, apply naming convention to class and property names (#581) */
    applyNamingConvention?: boolean;
    /** Convention for class names (default: PascalCase) */
    classNamingConvention?: 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';
    /** Convention for property names (default: camelCase) */
    propertyNamingConvention?: 'PascalCase' | 'camelCase' | 'snake_case' | 'kebab-case' | 'none';
    /** Optional map: schema key → class name (#753) */
    classNameMap?: Record<string, string>;
    /** Optional prefix applied to every class name after naming convention (#755) */
    classPrefix?: string;
    /** Optional suffix applied to every class name after naming convention (#755) */
    classSuffix?: string;
    /** Optional type mapping: external type key → internal JSON Schema (#757) */
    typeMapping?: Record<string, any>;
    /** Optional default values per type during import (#758). Key = external type key (e.g. "string", "integer"). */
    defaultValues?: Record<string, any>;
    /** Optional required field overrides per schema/property during import (#759). schema key -> { property name -> boolean }. */
    requiredOverrides?: Record<string, Record<string, boolean>>;
    /** Optional property description overrides per schema/property during import (#760). schema key -> { property name -> description }. */
    descriptionOverrides?: Record<string, Record<string, string>>;
    /** When true, auto-generate example values for properties that do not have an example (#761). */
    generateExamples?: boolean;
    dryRun?: boolean;
    /** When true, commit each class separately and skip failures (no single transaction). */
    incrementalMode?: boolean;
    /**
     * When true, if the catalog version line already exists for the project, finish successfully
     * without importing classes again (REST/CLI idempotency).
     */
    skipDuplicateVersions?: boolean;
  };
  /** When set, project creation is skipped and a new version is imported into this catalog project. */
  existingProjectId?: string;
  /** When set, a metric row is recorded after a successful import (repository file browser). */
  repositorySource?: {
    repositoryId: string;
    branch: string;
    path: string;
    blobSha?: string | null;
    /** Explicit importer format override used for this file, when forced (source descriptor, RAR-1.3). */
    formatOverride?: string | null;
    /** MIME type used to read the file, when known (source descriptor, RAR-1.3). */
    contentType?: string | null;
  };
}

function isDuplicateCatalogVersionLineError(message: string | undefined): boolean {
  // Matches the duplicate-version errors from createVersionTx, which now embed the version id and
  // project slug (e.g. `A version with ID "37" already exists in project "adyen-checkout-api"`) as
  // well as the legacy phrasing.
  return Boolean(message && /^A version with .+ already exists/i.test(message));
}

/** Merge OpenAPI/Swagger `document.info` into project description + projects.metadata (all import entry points). */
function enrichImportInputWithOpenApiInfo(input: ImportJobInput): ImportJobInput {
  if (input.sourceKind !== 'openapi') return input;
  const merged = mergeOpenApiDocumentIntoCatalogTargets(
    {
      project: input.project,
      version: {
        versionId: input.version.versionId,
        description: input.version.description ?? null,
      },
    },
    input.document,
    'openapi',
  );
  const combinedMeta =
    merged.projectMetadata || input.projectMetadata
      ? { ...(merged.projectMetadata ?? {}), ...(input.projectMetadata ?? {}) }
      : undefined;
  const projectMetadata =
    combinedMeta && Object.keys(combinedMeta).length > 0 ? combinedMeta : undefined;
  return {
    ...input,
    project: merged.project,
    version: merged.version,
    projectMetadata,
  };
}

interface JobState {
  input: ImportJobInput;
  state: ImportJobState;
  events: ImportEvent[];
  progress?: ProgressEvent;
  percent: number;
  result?: { projectId?: string; versionId?: string };
  canceled?: boolean;
  // Transaction state
  transactionClient?: PoolClient;
  transactionPending?: boolean;
  // Per-phase / per-DB-op timing accumulator (see finalizeBenchmark).
  bench?: Bench;
  summary?: {
    classesCreated: number;
    propertiesCreated: number;
    pathsImported: number;
    warnings: number;
    failed: number;
    totalTime?: number;
    sourceName?: string;
    projectName?: string;
    versionId?: string;
    dryRun?: boolean;
    /** True when import was run in incremental mode (skip failures, commit as we go). */
    incrementalMode?: boolean;
    /** True when import exited early because the catalog version line already existed (`skipDuplicateVersions`). */
    skippedDuplicateVersion?: boolean;
    /** Per-phase / per-DB-op timing breakdown for diagnosing slow imports (see finalizeBenchmark). */
    benchmark?: {
      totalMs: number;
      spans: Array<{ name: string; ms: number; count: number; avgMs: number; pct: number }>;
    };
    classes: Array<{ name: string; status: 'success' | 'warning' | 'failed' }>;
    verification?: {
      passed: boolean;
      classesVerified: number;
      propertiesVerified: number;
      mismatches: Array<{
        type: 'missing_class' | 'missing_property' | 'property_mismatch' | 'schema_mismatch';
        className: string;
        propertyName?: string;
        expected?: any;
        actual?: any;
        message: string;
      }>;
    };
  };
}

const jobs = new Map<string, JobState>();

async function recordRepositoryImportMetricIfApplicable(job: JobState): Promise<void> {
  const src = job.input.repositorySource;
  if (!src?.repositoryId?.trim()) return;
  const projectId = job.result?.projectId;
  const versionUuid = job.result?.versionId;
  if (!projectId || !versionUuid) return;
  const repositorySource = {
    repositoryId: src.repositoryId.trim(),
    branch: src.branch,
    path: src.path,
    blobSha: src.blobSha ?? null,
  };
  try {
    await recordTenantRepositoryImport({
      tenantId: job.input.tenantId,
      repositorySource,
      projectId,
      versionUuid,
      importedByUserId: job.input.userId,
    });
  } catch (err) {
    console.error('[import-helper] recordTenantRepositoryImport failed:', err);
  }
  // Persist the exact import spec alongside the audit row (RAR-1.2) so a future
  // auto-refresh replays the user's original options instead of importer
  // defaults. Keyed on (repository_id, branch, path): re-importing the same file
  // updates the row rather than duplicating it. Best-effort, like the audit row —
  // a capture failure must not fail an otherwise-successful import.
  try {
    await upsertRepositoryImportSpec({
      tenantId: job.input.tenantId,
      repositorySource,
      projectId,
      sourceKind: job.input.sourceKind,
      options: job.input.options as unknown as Record<string, unknown>,
      formatOverride: src.formatOverride ?? null,
      contentType: src.contentType ?? null,
      createdByUserId: job.input.userId,
    });
  } catch (err) {
    console.error('[import-helper] upsertRepositoryImportSpec failed:', err);
  }
}

const rndId = () => Math.random().toString(36).slice(2);
const now = () => Date.now();

function emit(job: JobState, level: ImportLogLevel, code: string, message: string, context?: any) {
  job.events.push({ id: rndId(), ts: now(), level, code, message, context });
  // Track warnings in summary
  if (level === 'warn' && job.summary) {
    job.summary.warnings++;
  }
}

function setProgress(job: JobState, phase: ProgressEvent['phase'], total: number, completed: number, currentItem?: string) {
  job.progress = { phase, total, completed, currentItem };
  job.percent = total > 0 ? Math.floor((completed / total) * 100) : 0;
}

// ---------------------------------------------------------------------------
// Import benchmarking (#perf): accumulate wall-clock time + call counts per named
// span so a slow import can be attributed to a phase (parse vs DB writes) and to
// the specific DB op (e.g. addPropertyToClass) driving the cost. Spans are summed
// across the whole job; `db:*` spans count round-trips and surface N+1 patterns.
// ---------------------------------------------------------------------------

interface BenchMark {
  ms: number;
  count: number;
}

type Bench = Record<string, BenchMark>;

/** Add an elapsed measurement to a named span (creating it on first use). */
function benchAdd(bench: Bench | undefined, name: string, ms: number): void {
  if (!bench) return;
  const m = bench[name] || (bench[name] = { ms: 0, count: 0 });
  m.ms += ms;
  m.count += 1;
}

/** Time an async operation into a named span and return its result. */
async function benchTime<T>(bench: Bench | undefined, name: string, fn: () => Promise<T>): Promise<T> {
  const t = Date.now();
  try {
    return await fn();
  } finally {
    benchAdd(bench, name, Date.now() - t);
  }
}

/** Record a completed phase: accumulate its time AND emit a streaming PHASE_TIMING event so
 * the phase timing is visible (e.g. in apiome-rest logs) while the import is still running,
 * not only in the final BENCHMARK summary. */
function recordPhase(job: JobState, name: string, ms: number): void {
  benchAdd(job.bench, name, ms);
  emit(job, 'info', 'PHASE_TIMING', `Phase ${name} completed in ${ms}ms`, { phase: name, ms });
}

/** Time an async phase, accumulate it, and emit a streaming PHASE_TIMING event when it finishes. */
async function benchPhase<T>(job: JobState, name: string, fn: () => Promise<T>): Promise<T> {
  const t = Date.now();
  try {
    return await fn();
  } finally {
    recordPhase(job, name, Date.now() - t);
  }
}

/** Build the benchmark report (spans sorted slowest-first, with % of total job time). */
function buildBenchmarkReport(bench: Bench, totalMs: number): {
  totalMs: number;
  spans: Array<{ name: string; ms: number; count: number; avgMs: number; pct: number }>;
} {
  const spans = Object.entries(bench)
    .map(([name, m]) => ({
      name,
      ms: m.ms,
      count: m.count,
      avgMs: m.count > 0 ? Math.round((m.ms / m.count) * 100) / 100 : 0,
      pct: totalMs > 0 ? Math.round((m.ms / totalMs) * 1000) / 10 : 0,
    }))
    .sort((a, b) => b.ms - a.ms);
  return { totalMs, spans };
}

/** Attach the benchmark to the job summary and emit it as a single log event. Runs on every
 * terminal path (success, skip, failure) so timings are always available for diagnosis. */
function finalizeBenchmark(job: JobState, startTime: number): void {
  if (!job.bench) return;
  const totalMs = Date.now() - startTime;
  const report = buildBenchmarkReport(job.bench, totalMs);
  if (job.summary) job.summary.benchmark = report;
  const top = report.spans
    .slice(0, 12)
    .map((s) => `${s.name}=${s.ms}ms (${s.count}x, avg ${s.avgMs}ms, ${s.pct}%)`)
    .join(', ');
  emit(
    job,
    'info',
    'BENCHMARK',
    `Import timing — total ${totalMs}ms. Slowest spans: ${top || '(none recorded)'}`,
    { totalMs, spans: report.spans },
  );
  // Also log to stderr so it lands in the REST worker / server logs. NOTE: stdout is
  // reserved for the worker's NDJSON status protocol — only ever use console.error here.
  console.error(`[import-benchmark] total=${totalMs}ms ${top}`);
}

/** REST/CLI imports into an existing project skip createProjectTx — persist enriched OpenAPI info here. */
async function mergeOpenApiIntoExistingProjectIfNeeded(
  client: PoolClient,
  job: JobState,
  input: ImportJobInput,
  existingProjectId: string | undefined,
): Promise<void> {
  const existing = existingProjectId?.trim();
  if (!existing || input.sourceKind !== 'openapi') return;

  const patch = input.projectMetadata;
  const patchKeys = patch ? Object.keys(patch) : [];
  const specDesc = (input.project.description ?? '').trim();
  if (patchKeys.length === 0 && specDesc === '') return;

  const resRaw = await withRetry(
    () =>
      mergeProjectImportOpenApiFieldsTx(client, existing, {
        descriptionFromSpec: specDesc || null,
        metadataPatch: patch ?? undefined,
      }),
    { maxAttempts: 3, initialDelayMs: 500, label: 'mergeProjectImportOpenApiFields' },
  );
  const res = JSON.parse(resRaw) as { success: boolean; error?: string };
  if (!res.success) {
    throw new Error(res.error || 'Failed to merge OpenAPI info into existing project');
  }
  emit(job, 'info', 'PROJECT_CATALOG_MERGED', 'Merged OpenAPI info.description and info metadata into existing catalog project.', {
    projectId: existing,
  });
}

// Stable JSON stringify that sorts object keys to ensure consistent signatures
function stableStringify(obj: any): string {
  if (obj === null || obj === undefined) return JSON.stringify(obj);
  if (typeof obj !== 'object') return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return '[' + obj.map(item => stableStringify(item)).join(',') + ']';
  }
  const sortedKeys = Object.keys(obj).sort();
  const pairs = sortedKeys.map(key => JSON.stringify(key) + ':' + stableStringify(obj[key]));
  return '{' + pairs.join(',') + '}';
}

type NormalizedModel = { classes: NormalizedClass[] };

async function buildPropertyIdMapForImport(
  client: PoolClient,
  projectId: string,
  norm: NormalizedModel,
  job: JobState,
  reuseLibraryFromProject: boolean
): Promise<Map<string, string>> {
  const propertyMap = new Map<string, { data: any; description?: string; names: Set<string> }>();

  const collectProperties = (props: any[]) => {
    for (const p of props || []) {
      const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
      if (!isReference) {
        const sig = stableStringify(p.data);
        if (!propertyMap.has(sig)) {
          propertyMap.set(sig, { data: p.data, description: p.description, names: new Set<string>() });
        }
        propertyMap.get(sig)!.names.add(p.name);
      }
      if (p.children) collectProperties(p.children);
    }
  };

  for (const cls of norm.classes) {
    collectProperties(cls.properties || []);
  }

  const propertyIdMap = new Map<string, string>();
  const usedNames = new Set<string>();
  const sigToLibraryId = new Map<string, string>();

  if (reuseLibraryFromProject) {
    const rows = await benchTime(job.bench, 'db:listLibraryProperties', () =>
      listProjectLibraryPropertiesTx(client, projectId)
    );
    for (const row of rows) {
      usedNames.add(row.name);
      const sig = stableStringify(row.data);
      if (!sigToLibraryId.has(sig)) sigToLibraryId.set(sig, row.id);
    }
    emit(job, 'info', 'LIBRARY_REUSE', `Loaded ${rows.length} property library row(s) for cross-revision reuse`, {
      projectId,
    });
  }

  emit(
    job,
    'info',
    'CREATING_PROPERTIES',
    `Ensuring ${propertyMap.size} unique property shape(s) in project library` +
      (reuseLibraryFromProject ? ` (${sigToLibraryId.size} existing shape(s) indexed)` : '')
  );

  // #perf: resolve reuses inline, then create every brand-new shape in a single batched
  // INSERT instead of one round-trip per shape. UUIDs are assigned here so the new ids
  // populate propertyIdMap directly (no RETURNING round-trip needed). A per-shape unique
  // name is derived up front so the batch can't self-collide.
  const toCreate: Array<{ sig: string; row: PropertyInsert }> = [];
  for (const [sig, payload] of propertyMap.entries()) {
    if (job.canceled) throw new Error('Import canceled');

    const reusedId = sigToLibraryId.get(sig);
    if (reusedId) {
      propertyIdMap.set(sig, reusedId);
      continue;
    }

    const baseName = Array.from(payload.names)[0];
    let propName = baseName;
    let suffix = 1;
    while (usedNames.has(propName)) {
      propName = `${baseName}_${suffix}`;
      suffix++;
    }
    usedNames.add(propName);

    const id = randomUUID();
    toCreate.push({
      sig,
      row: { id, projectId, name: propName, description: payload.description || null, data: payload.data },
    });
    // Optimistically register the id; failures (rare) are unwound after the batch.
    propertyIdMap.set(sig, id);
    sigToLibraryId.set(sig, id);
    if (job.summary) job.summary.propertiesCreated++;
  }

  if (toCreate.length > 0) {
    const batchRes = JSON.parse(
      await benchTime(job.bench, 'db:createPropertiesBatch', () =>
        createPropertiesBatchTx(client, toCreate.map((t) => t.row))
      )
    );
    if (!batchRes.success) {
      throw new Error(batchRes.error || 'Failed to create project library properties');
    }
    // Unwind any rows the per-row fallback couldn't insert so class linking won't point at
    // a non-existent library id.
    const failedNames = new Set<string>((batchRes.failed || []).map((f: { name: string }) => f.name));
    if (failedNames.size > 0) {
      for (const { sig, row } of toCreate) {
        if (!failedNames.has(row.name)) continue;
        const err = (batchRes.failed as Array<{ name: string; error: string }>).find((f) => f.name === row.name);
        emit(job, 'warn', 'PROPERTY_CREATE_WARN', `Could not create property "${row.name}": ${err?.error || 'insert failed'}`);
        propertyIdMap.delete(sig);
        sigToLibraryId.delete(sig);
        if (job.summary) job.summary.propertiesCreated--;
      }
    }
  }

  emit(job, 'info', 'PROPERTIES_READY', `Resolved ${propertyIdMap.size} property library id(s) for class linking`);
  return propertyIdMap;
}

// Normalize property data for comparison - removes volatile fields and normalizes structure
function normalizePropertyData(data: any): any {
  if (!data || typeof data !== 'object') return data;

  const normalized: any = {};
  const keysToSkip = ['description']; // Description is stored separately

  for (const key of Object.keys(data).sort()) {
    if (keysToSkip.includes(key)) continue;
    const value = data[key];
    if (value === null || value === undefined) continue;
    if (typeof value === 'object') {
      normalized[key] = normalizePropertyData(value);
    } else {
      normalized[key] = value;
    }
  }

  return normalized;
}

// Compare two property data objects for equivalence
function comparePropertyData(expected: any, actual: any): { match: boolean; diff?: string } {
  const expectedNorm = normalizePropertyData(expected);
  const actualNorm = normalizePropertyData(actual);

  const expectedStr = stableStringify(expectedNorm);
  const actualStr = stableStringify(actualNorm);

  if (expectedStr === actualStr) {
    return { match: true };
  }

  return {
    match: false,
    diff: `Expected: ${expectedStr.substring(0, 200)}... Actual: ${actualStr.substring(0, 200)}...`
  };
}

// Build a property tree from flat database properties
function buildPropertyTree(properties: any[]): Map<string, any> {
  const byId = new Map<string, any>();
  const roots = new Map<string, any>();

  // First pass: index by id
  for (const p of properties) {
    byId.set(p.id, { ...p, children: [] });
  }

  // Second pass: build tree
  for (const p of properties) {
    const node = byId.get(p.id)!;
    if (p.parent_id && byId.has(p.parent_id)) {
      byId.get(p.parent_id)!.children.push(node);
    } else {
      roots.set(p.name, node);
    }
  }

  return roots;
}

// Verify a single class against its expected normalized form
function verifyClass(
  expectedClass: NormalizedClass,
  dbClass: any,
  mismatches: Array<any>
): { propertiesVerified: number } {
  let propertiesVerified = 0;

  // Build property tree from database
  const dbPropertyTree = buildPropertyTree(dbClass.properties || []);

  // Verify each expected property exists in database
  const verifyProperties = (expectedProps: NormalizedProperty[], dbProps: Map<string, any>, path: string = '') => {
    for (const expectedProp of expectedProps) {
      const fullPath = path ? `${path}.${expectedProp.name}` : expectedProp.name;
      const dbProp = dbProps.get(expectedProp.name);

      if (!dbProp) {
        // Check if this property might have been skipped (no library entry)
        // This is a warning case, not a failure
        mismatches.push({
          type: 'missing_property',
          className: expectedClass.name,
          propertyName: fullPath,
          expected: expectedProp.data,
          message: `Property "${fullPath}" not found in database for class "${expectedClass.name}"`
        });
        continue;
      }

      propertiesVerified++;

      // Compare property data
      const comparison = comparePropertyData(expectedProp.data, dbProp.data);
      if (!comparison.match) {
        mismatches.push({
          type: 'property_mismatch',
          className: expectedClass.name,
          propertyName: fullPath,
          expected: expectedProp.data,
          actual: dbProp.data,
          message: `Property data mismatch for "${fullPath}" in class "${expectedClass.name}": ${comparison.diff}`
        });
      }

      // Recursively verify children
      if (expectedProp.children && expectedProp.children.length > 0) {
        const childMap = new Map<string, any>();
        for (const child of dbProp.children || []) {
          childMap.set(child.name, child);
        }
        verifyProperties(expectedProp.children, childMap, fullPath);
      }
    }
  };

  verifyProperties(expectedClass.properties || [], dbPropertyTree);

  return { propertiesVerified };
}

// Main verification function - verifies imported data matches the original schema
async function verifyImport(
  client: PoolClient,
  versionId: string,
  normalizedClasses: NormalizedClass[],
  job: JobState
): Promise<{
  passed: boolean;
  classesVerified: number;
  propertiesVerified: number;
  mismatches: Array<any>;
}> {
  const mismatches: Array<any> = [];
  let classesVerified = 0;
  let totalPropertiesVerified = 0;

  emit(job, 'info', 'VERIFY_START', `Starting import verification for ${normalizedClasses.length} classes`);

  // Fetch all classes with properties from database using transaction client
  const dbClassesJson = await getClassesWithPropertiesAndTagsTx(client, versionId);
  const dbClasses = JSON.parse(dbClassesJson);

  // Build a map of database classes by name
  const dbClassMap = new Map<string, any>();
  for (const dbClass of dbClasses) {
    dbClassMap.set(dbClass.name, dbClass);
  }

  // Verify each expected class
  for (const expectedClass of normalizedClasses) {
    const dbClass = dbClassMap.get(expectedClass.name);

    if (!dbClass) {
      mismatches.push({
        type: 'missing_class',
        className: expectedClass.name,
        message: `Class "${expectedClass.name}" not found in database after import`
      });
      continue;
    }

    classesVerified++;

    // Verify class schema matches (basic check on discriminator and type)
    if (expectedClass.schema) {
      const expectedHasDiscriminator = !!expectedClass.schema.discriminator;
      const dbSchema = dbClass.schema || {};
      const dbHasDiscriminator = !!dbSchema.discriminator;

      if (expectedHasDiscriminator !== dbHasDiscriminator) {
        mismatches.push({
          type: 'schema_mismatch',
          className: expectedClass.name,
          expected: { hasDiscriminator: expectedHasDiscriminator },
          actual: { hasDiscriminator: dbHasDiscriminator },
          message: `Schema discriminator mismatch for class "${expectedClass.name}"`
        });
      }
    }

    // Verify properties
    const result = verifyClass(expectedClass, dbClass, mismatches);
    totalPropertiesVerified += result.propertiesVerified;
  }

  // Check for extra classes in database that weren't expected
  for (const dbClass of dbClasses) {
    const wasExpected = normalizedClasses.some(nc => nc.name === dbClass.name);
    if (!wasExpected) {
      emit(job, 'warn', 'VERIFY_EXTRA_CLASS', `Database contains class "${dbClass.name}" that was not in import`);
    }
  }

  const passed = mismatches.length === 0;

  if (passed) {
    emit(job, 'info', 'VERIFY_PASS', `Verification passed: ${classesVerified} classes, ${totalPropertiesVerified} properties verified`);
  } else {
    // Non-critical: log as warning so import can continue (graceful degradation)
    emit(job, 'warn', 'VERIFY_MISMATCHES', `Verification found ${mismatches.length} mismatch(es)`, {
      mismatches: mismatches.slice(0, 10) // Limit to first 10 for logging
    });
  }

  return {
    passed,
    classesVerified,
    propertiesVerified: totalPropertiesVerified,
    mismatches
  };
}

async function writeClassWithProperties(
  client: PoolClient,
  projectId: string,
  versionId: string,
  cls: NormalizedClass,
  job: JobState,
  propertyIdMap: Map<string, string>
) {
  const resClass = JSON.parse(await benchTime(job.bench, 'db:createClass', () =>
    createClassTx(client, versionId, cls.name, cls.description || null, cls.schema || { type: 'object' })
  ));
  if (!resClass.success) throw new Error(resClass.error || 'Failed to create class');
  const classId = resClass.class.id as string;

  // #perf: flatten the whole property tree into one insert batch instead of issuing
  // a DB round-trip per property. Each row's UUID is assigned here so parent/child
  // links resolve client-side; the entire class then writes in a single statement.
  const rows: ClassPropertyInsert[] = [];

  const collect = (props: any[], parentId: string | null) => {
    for (const p of props || []) {
      if (job.canceled) return;
      let propertyId: string | null = null;
      const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
      if (!isReference) {
        const sig = stableStringify(p.data);
        propertyId = propertyIdMap.get(sig) || null;

        // Database constraint requires: property_id IS NOT NULL OR data contains $ref
        // If this is not a reference and we don't have a propertyId, skip with warning
        if (propertyId === null) {
          emit(job, 'warn', 'SKIP_PROPERTY', `Skipping property "${p.name}" in class "${cls.name}" - no library entry found`, {
            className: cls.name,
            propertyName: p.name,
            dataType: p.data.type,
            signature: sig.substring(0, 200)
          });
          // A skipped parent drops its subtree (children can't reference a missing parent)
          if (p.children && p.children.length) {
            emit(job, 'warn', 'SKIP_CHILDREN', `Also skipping ${p.children.length} child properties of "${p.name}"`);
          }
          continue;
        }
      }
      const id = randomUUID();
      rows.push({ id, classId, propertyId, name: p.name, description: p.description || null, data: p.data, parentId });
      if (p.children && p.children.length) collect(p.children, id);
    }
  };

  collect(cls.properties || [], null);

  if (job.canceled || rows.length === 0) return;

  const addRes = JSON.parse(
    await benchTime(job.bench, 'db:addPropertiesToClassBatch', () =>
      addPropertiesToClassBatchTx(client, rows)
    )
  );
  if (!addRes.success) {
    // Catastrophic batch failure (couldn't even recover the transaction) — surface it so
    // the caller rolls back and marks the class failed.
    throw new Error(addRes.error || `Failed to add properties to class "${cls.name}"`);
  }
  // Graceful degradation (#733): any individual rows the per-row fallback couldn't insert
  // are reported (and warned on) without failing the whole class.
  for (const f of (addRes.failed || []) as Array<{ name: string; error: string }>) {
    emit(job, 'warn', 'PROPERTY_LINK_FAILED', `Could not add property "${f.name}" to class "${cls.name}": ${f.error}`, {
      className: cls.name,
      propertyName: f.name,
    });
  }
}

export async function startImport(input: ImportJobInput) {
  const jobId = rndId();
  const startTime = Date.now();

  // Validate required IDs early
  if (!input.tenantId) {
    throw new Error('Tenant ID is required for import. Please ensure you have selected a tenant.');
  }
  if (!input.userId) {
    throw new Error('User ID is required for import. Please ensure you are logged in.');
  }

  const jobInput = enrichImportInputWithOpenApiInfo(input);

  const job: JobState = {
    input: jobInput,
    state: 'queued',
    events: [],
    percent: 0,
    transactionPending: false,
    bench: {},
    summary: {
      classesCreated: 0,
      propertiesCreated: 0,
      pathsImported: 0,
      warnings: 0,
      failed: 0,
      sourceName: jobInput.project.name,
      projectName: jobInput.project.name,
      versionId: jobInput.version.versionId,
      classes: []
    }
  };
  jobs.set(jobId, job);

  (async () => {
    const input = job.input;
    let client: PoolClient | null = null;
    const isDryRun = input.options.dryRun === true;

    try {
      job.state = 'running';
      emit(job, 'info', 'INIT', isDryRun ? 'Initializing dry run (preview only - no changes will be saved)' : 'Initializing import job');
      setProgress(job, 'initializing', 1, 0);

      const importer = getImporter(input.sourceKind);
      if (!importer) throw new Error(`No importer registered for ${input.sourceKind}`);
      const _normalizeStart = Date.now();
      const norm = importer.normalize({
        document: input.document,
        options: {
          selectedSchemas: input.options.selectedSchemas,
          applyNamingConvention: input.options.applyNamingConvention,
          classNamingConvention: input.options.classNamingConvention,
          propertyNamingConvention: input.options.propertyNamingConvention,
          classNameMap: input.options.classNameMap,
          classPrefix: input.options.classPrefix,
          classSuffix: input.options.classSuffix,
          typeMapping: input.options.typeMapping,
          defaultValues: input.options.defaultValues,
          requiredOverrides: input.options.requiredOverrides,
          descriptionOverrides: input.options.descriptionOverrides,
          generateExamples: input.options.generateExamples,
        },
      });
      recordPhase(job, 'parse:normalize', Date.now() - _normalizeStart);
      if (norm.warnings.length) emit(job, 'warn', 'NORMALIZE_WARN', norm.warnings.join('\n'));

      // Log normalized class info for debugging
      for (const cls of norm.classes) {
        emit(job, 'info', 'DEBUG_NORMALIZED_CLASS', `Normalized class: ${cls.name}`, {
          propertyCount: cls.properties?.length || 0,
          properties: cls.properties?.map(p => p.name).join(', ') || 'none',
          hasDiscriminator: !!cls.schema?.discriminator
        });
      }

      if (job.canceled) throw new Error('Import canceled');

      if (isDryRun) {
        // Dry run: no DB transaction, just compute what would be created and emit summary
        setProgress(job, 'creating-project', 1, 0, input.project.name);
        const existingDry = input.existingProjectId?.trim();
        emit(
          job,
          'info',
          'DRY_RUN',
          existingDry
            ? `Dry run mode - simulating import into existing project "${input.project.name}" (no database changes)`
            : 'Dry run mode - simulating import (no database changes)'
        );
        setProgress(job, 'creating-version', 2, 1, input.version.versionId);

        const propertyMap = new Map<string, { data: any; description?: string; names: Set<string> }>();
        const collectProperties = (props: any[]) => {
          for (const p of props || []) {
            const isReference = p.data?.$ref || (p.data?.type === 'array' && p.data?.items?.$ref);
            if (!isReference) {
              const sig = stableStringify(p.data);
              if (!propertyMap.has(sig)) {
                propertyMap.set(sig, { data: p.data, description: p.description, names: new Set<string>() });
              }
              propertyMap.get(sig)!.names.add(p.name);
            }
            if (p.children) collectProperties(p.children);
          }
        };
        for (const cls of norm.classes) {
          collectProperties(cls.properties || []);
        }

        emit(job, 'info', 'CREATING_PROPERTIES', `Would create ${propertyMap.size} unique properties in library`);
        if (job.summary) {
          job.summary.propertiesCreated = propertyMap.size;
          if (input.sourceKind === 'openapi' && input.document) {
            job.summary.pathsImported = extractPaths(input.document).length;
          }
        }

        setProgress(job, 'creating-classes', 2 + norm.classes.length, 2);
        for (let i = 0; i < norm.classes.length; i++) {
          if (job.canceled) throw new Error('Import canceled');
          const cls = norm.classes[i];
          setProgress(job, 'creating-classes', 2 + norm.classes.length, 2 + i, cls.name);
          emit(job, 'info', 'CLASS_CREATED', `Would import class: ${cls.name}`);
          if (job.summary) {
            job.summary.classesCreated++;
            job.summary.classes.push({ name: cls.name, status: 'success' });
          }
        }

        setProgress(job, 'finalizing', 3 + norm.classes.length, 3 + norm.classes.length);
        job.state = 'completed';
        if (job.summary) {
          job.summary.dryRun = true;
          job.summary.totalTime = Date.now() - startTime;
        }
        job.percent = 100;
        emit(job, 'info', 'DRY_RUN_COMPLETE', 'Dry run complete. No changes were saved. Run without "Dry run" to import for real.');
        return;
      }

      const incrementalMode = input.options.incrementalMode === true;

      // Get a transaction client (with retry for transient connection errors)
      client = await withRetry(() => getTransactionClient(), {
        maxAttempts: 3,
        initialDelayMs: 500,
        label: 'getTransactionClient'
      });
      job.transactionClient = client;

      if (incrementalMode) {
        // Incremental mode: no single transaction; commit as we go and skip failures
        emit(job, 'info', 'INCREMENTAL_MODE', 'Importing in incremental mode — each class is committed separately; failed classes are skipped.');
        // Project and version run in autocommit (no BEGIN)
        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'creating-project', 1, 0, input.project.name);
        let projectId: string;
        // Reuse an existing project when one is explicitly targeted, or when a project with the same
        // slug already exists in the tenant (a new version of an existing API). Only a duplicate
        // project *and* version is rejected — caught at version creation below.
        const existingInc =
          input.existingProjectId?.trim() ||
          (await getProjectIdBySlugTx(client!, input.tenantId, input.project.slug)) ||
          null;
        if (existingInc) {
          projectId = existingInc;
          emit(job, 'info', 'EXISTING_PROJECT', `Using existing project: ${input.project.name}`, { projectId });
          await mergeOpenApiIntoExistingProjectIfNeeded(client!, job, input, existingInc);
        } else {
          const resProj = JSON.parse(
            await withRetry(
              () =>
                createProjectTx(
                  client!,
                  input.tenantId,
                  input.userId,
                  input.project.name,
                  input.project.description || '',
                  input.project.slug,
                  input.projectMetadata ?? undefined,
                ),
              { maxAttempts: 3, initialDelayMs: 500, label: 'createProject' }
            )
          );
          if (!resProj.success) throw new Error(resProj.error || 'Failed to create project');
          projectId = resProj.project.id as string;
          emit(job, 'info', 'PROJECT_CREATED', `Created project: ${input.project.name}`, { projectId });
        }
        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'creating-version', 2, 1, input.version.versionId);
        const reuseLibraryInc = Boolean(existingInc);
        const parentVersionUuidInc = reuseLibraryInc
          ? await getLatestVersionUuidForProjectTx(client!, projectId)
          : null;
        const resVer = JSON.parse(
          await withRetry(
            () =>
              createVersionTx(
                client!,
                projectId,
                input.userId,
                input.version.versionId,
                input.version.description || '',
                parentVersionUuidInc
                  ? 'Imported from specification (follow-on revision in same project)'
                  : 'Imported from specification',
                { parentVersionUuid: parentVersionUuidInc ?? undefined, projectSlug: input.project.slug }
              ),
            { maxAttempts: 3, initialDelayMs: 500, label: 'createVersion' }
          )
        );
        if (!resVer.success) {
          const verErr = resVer.error || 'Failed to create version';
          if (input.options.skipDuplicateVersions === true && isDuplicateCatalogVersionLineError(verErr)) {
            const existingUuid = await getVersionUuidForCatalogVersionLineTx(
              client!,
              projectId,
              input.version.versionId
            );
            if (!existingUuid) throw new Error(verErr);
            emit(
              job,
              'info',
              'DUPLICATE_VERSION_SKIPPED',
              `Catalog version "${input.version.versionId}" already exists for this project; skipping import.`,
              { projectId, versionRecordId: existingUuid }
            );
            job.result = { projectId, versionId: existingUuid };
            setProgress(job, 'finalizing', 3, 3, 'Skipped — version already exists');
            job.state = 'completed';
            job.percent = 100;
            if (job.summary) {
              job.summary.totalTime = Date.now() - startTime;
              job.summary.incrementalMode = true;
              job.summary.skippedDuplicateVersion = true;
            }
            emit(job, 'info', 'IMPORT_SKIPPED_NOOP', 'Import finished without changes (duplicate catalog version line).', job.result);
            await releaseClient(client!);
            job.transactionClient = undefined;
            return;
          }
          throw new Error(verErr);
        }
        const versionId = resVer.version.id as string;
        emit(job, 'info', 'VERSION_CREATED', `Created version: ${input.version.versionId}`, {
          versionId,
          parentVersionUuid: parentVersionUuidInc ?? undefined,
        });

        // The property-library build uses SAVEPOINT-protected batch inserts, which require an
        // open transaction. The incremental project/version steps above run in autocommit, so
        // wrap the library build in its own short transaction (committed before the per-class
        // loop) — consistent with the per-class begin/commit pattern below.
        let propertyIdMapInc: Map<string, string>;
        await benchTime(job.bench, 'db:beginTransaction', () => beginTransaction(client!));
        try {
          propertyIdMapInc = await benchPhase(job, 'phase:buildPropertyLibrary', () =>
            buildPropertyIdMapForImport(
              client!,
              projectId,
              norm,
              job,
              reuseLibraryInc
            )
          );
          await benchTime(job.bench, 'db:commitTransaction', () => commitTransaction(client!));
        } catch (libErr) {
          try {
            await rollbackTransaction(client!);
          } catch (_) { /* ignore */ }
          throw libErr;
        }

        setProgress(job, 'creating-classes', 2 + norm.classes.length, 2);
        let classCountInc = 0;
        const _writeClassesStart = Date.now();
        for (const cls of norm.classes) {
          if (job.canceled) throw new Error('Import canceled');
          setProgress(job, 'creating-classes', 2 + norm.classes.length, 2 + classCountInc, cls.name);
          try {
            await benchTime(job.bench, 'db:beginTransaction', () => beginTransaction(client!));
            await writeClassWithProperties(client!, projectId, versionId, cls, job, propertyIdMapInc);
            await benchTime(job.bench, 'db:commitTransaction', () => commitTransaction(client!));
            emit(job, 'info', 'CLASS_CREATED', `Imported class: ${cls.name}`);
            if (job.summary) {
              job.summary.classesCreated++;
              job.summary.classes.push({ name: cls.name, status: 'success' });
            }
          } catch (classErr: any) {
            try {
              await rollbackTransaction(client!);
            } catch (_) { /* ignore */ }
            emit(job, 'error', 'CLASS_FAILED', `Failed to create class ${cls.name}: ${classErr?.message}`);
            if (job.summary) {
              job.summary.failed++;
              job.summary.classes.push({ name: cls.name, status: 'failed' });
            }
          }
          classCountInc++;
        }
        recordPhase(job, 'phase:writeClasses', Date.now() - _writeClassesStart);

        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'verifying', 3 + norm.classes.length, 2 + norm.classes.length, 'Verifying import...');
        const verificationResultInc = await benchPhase(job, 'phase:verify', () =>
          verifyImport(client!, versionId, norm.classes, job)
        );
        if (job.summary) job.summary.verification = verificationResultInc;
        if (!verificationResultInc.passed && job.summary) job.summary.warnings++;

        if (input.sourceKind === 'openapi' && input.document) {
          const paths = extractPaths(input.document);
          const securitySchemes = extractSecuritySchemes(input.document);
          if (paths.length > 0 || securitySchemes.length > 0) {
            emit(job, 'info', 'IMPORTING_PATHS', `Importing ${paths.length} path(s) and ${securitySchemes.length} security scheme(s)...`);
            const pathResult = await benchPhase(job, 'phase:importPaths', () =>
              importOpenAPIPathsAndSecurity(versionId, paths, securitySchemes)
            );
            if (pathResult.success) {
              if (job.summary) job.summary.pathsImported = paths.length;
              emit(job, 'info', 'PATHS_IMPORTED', 'Paths and security schemes imported.');
            } else {
              emit(job, 'warn', 'PATHS_IMPORT_WARN', `Paths/security import had issues: ${pathResult.error}`);
            }
          }
        }

        job.result = { projectId, versionId };
        await recordRepositoryImportMetricIfApplicable(job);

        setProgress(job, 'finalizing', 3 + norm.classes.length, 3 + norm.classes.length);
        job.state = 'completed';
        if (job.summary) {
          job.summary.totalTime = Date.now() - startTime;
          job.summary.incrementalMode = true;
        }
        emit(job, 'info', 'INCREMENTAL_COMPLETE', 'Incremental import complete. Successful classes were saved; failed classes were skipped.', job.result);
        await releaseClient(client!);
        job.transactionClient = undefined;
        return;
      }

      // Transaction mode: single transaction, pending-approval to commit or rollback
      await withRetry(() => beginTransaction(client!), {
        maxAttempts: 3,
        initialDelayMs: 300,
        label: 'beginTransaction'
      });
      job.transactionPending = true;
      emit(job, 'info', 'TRANSACTION_STARTED', 'Database transaction started - changes will be committed only after approval');

      if (job.canceled) throw new Error('Import canceled');

      setProgress(job, 'creating-project', 1, 0, input.project.name);
      let projectId: string;
      // Reuse an existing project when one is explicitly targeted, or when a project with the same
      // slug already exists in the tenant (a new version of an existing API). Only a duplicate
      // project *and* version is rejected — caught at version creation below.
      const existingTx =
        input.existingProjectId?.trim() ||
        (await getProjectIdBySlugTx(client!, input.tenantId, input.project.slug)) ||
        null;
      if (existingTx) {
        projectId = existingTx;
        emit(job, 'info', 'EXISTING_PROJECT', `Using existing project: ${input.project.name}`, { projectId });
        await mergeOpenApiIntoExistingProjectIfNeeded(client!, job, input, existingTx);
      } else {
        const resProj = JSON.parse(
          await withRetry(
            () =>
              createProjectTx(
                client!,
                input.tenantId,
                input.userId,
                input.project.name,
                input.project.description || '',
                input.project.slug,
                input.projectMetadata ?? undefined,
              ),
            { maxAttempts: 3, initialDelayMs: 500, label: 'createProject' }
          )
        );
        if (!resProj.success) throw new Error(resProj.error || 'Failed to create project');
        projectId = resProj.project.id as string;
        emit(job, 'info', 'PROJECT_CREATED', `Created project: ${input.project.name}`, { projectId });
      }

      if (job.canceled) throw new Error('Import canceled');

      setProgress(job, 'creating-version', 2, 1, input.version.versionId);
      const reuseLibraryTx = Boolean(existingTx);
      const parentVersionUuidTx = reuseLibraryTx
        ? await getLatestVersionUuidForProjectTx(client!, projectId)
        : null;
      const resVer = JSON.parse(
        await withRetry(
          () =>
            createVersionTx(
              client!,
              projectId,
              input.userId,
              input.version.versionId,
              input.version.description || '',
              parentVersionUuidTx
                ? 'Imported from specification (follow-on revision in same project)'
                : 'Imported from specification',
              { parentVersionUuid: parentVersionUuidTx ?? undefined, projectSlug: input.project.slug }
            ),
          { maxAttempts: 3, initialDelayMs: 500, label: 'createVersion' }
        )
      );
      if (!resVer.success) {
        const verErr = resVer.error || 'Failed to create version';
        if (input.options.skipDuplicateVersions === true && isDuplicateCatalogVersionLineError(verErr)) {
          const existingUuid = await getVersionUuidForCatalogVersionLineTx(
            client!,
            projectId,
            input.version.versionId
          );
          if (!existingUuid) throw new Error(verErr);
          if (job.transactionPending) {
            await rollbackTransaction(client!);
            job.transactionPending = false;
            emit(job, 'info', 'TRANSACTION_ROLLED_BACK', 'Transaction rolled back after duplicate-version skip');
          }
          emit(
            job,
            'info',
            'DUPLICATE_VERSION_SKIPPED',
            `Catalog version "${input.version.versionId}" already exists for this project; skipping import.`,
            { projectId, versionRecordId: existingUuid }
          );
          job.result = { projectId, versionId: existingUuid };
          setProgress(job, 'finalizing', 3, 3, 'Skipped — version already exists');
          job.state = 'completed';
          job.percent = 100;
          if (job.summary) {
            job.summary.totalTime = Date.now() - startTime;
            job.summary.skippedDuplicateVersion = true;
          }
          emit(job, 'info', 'IMPORT_SKIPPED_NOOP', 'Import finished without changes (duplicate catalog version line).', job.result);
          await releaseClient(client!);
          job.transactionClient = undefined;
          return;
        }
        throw new Error(verErr);
      }
      const versionId = resVer.version.id as string;
      emit(job, 'info', 'VERSION_CREATED', `Created version: ${input.version.versionId}`, {
        versionId,
        parentVersionUuid: parentVersionUuidTx ?? undefined,
      });

      const propertyIdMap = await buildPropertyIdMapForImport(client, projectId, norm, job, reuseLibraryTx);

      // Create classes and link properties
      setProgress(job, 'creating-classes', 2 + norm.classes.length, 2);
      let classCount = 0;
      for (const cls of norm.classes) {
        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'creating-classes', 2 + norm.classes.length, 2 + classCount, cls.name);
        try {
          await writeClassWithProperties(client, projectId, versionId, cls, job, propertyIdMap);
          emit(job, 'info', 'CLASS_CREATED', `Imported class: ${cls.name}`);
          if (job.summary) {
            job.summary.classesCreated++;
            job.summary.classes.push({ name: cls.name, status: 'success' });
          }
        } catch (classErr: any) {
          emit(job, 'error', 'CLASS_FAILED', `Failed to create class ${cls.name}: ${classErr?.message}`);
          if (job.summary) {
            job.summary.failed++;
            job.summary.classes.push({ name: cls.name, status: 'failed' });
          }
        }
        classCount++;
      }

      // Verification phase - sanity check imported data matches schema
      if (job.canceled) throw new Error('Import canceled');
      setProgress(job, 'verifying', 3 + norm.classes.length, 2 + norm.classes.length, 'Verifying import...');

      const verificationResult = await verifyImport(client, versionId, norm.classes, job);

      if (job.summary) {
        job.summary.verification = verificationResult;
      }

      // Graceful degradation: verification mismatches are non-critical — continue to pending-approval
      if (!verificationResult.passed) {
        emit(job, 'warn', 'VERIFY_MISMATCHES', `Verification found ${verificationResult.mismatches.length} mismatch(es). You can still commit this import and review in Canvas.`, {
          mismatchCount: verificationResult.mismatches.length,
          firstMessage: verificationResult.mismatches[0]?.message
        });
        if (job.summary) job.summary.warnings++;
      }

      setProgress(job, 'finalizing', 3 + norm.classes.length, 3 + norm.classes.length);

      // Set state to pending-approval - waiting for user to accept or reject
      job.state = 'pending-approval';
      job.result = { projectId, versionId };
      if (job.summary) {
        job.summary.totalTime = Date.now() - startTime;
      }
      emit(job, 'info', 'PENDING_APPROVAL', 'Import ready for review. Accept to commit changes or reject to rollback.', job.result);

      // Note: Transaction is NOT committed here - it stays open until user accepts or rejects

    } catch (err: any) {
      // Rollback transaction on any error
      if (client && job.transactionPending) {
        try {
          await rollbackTransaction(client);
          job.transactionPending = false;
          emit(job, 'info', 'TRANSACTION_ROLLED_BACK', 'Transaction rolled back due to error');
        } catch (rollbackErr) {
          emit(job, 'error', 'ROLLBACK_FAILED', `Failed to rollback transaction: ${rollbackErr}`);
        }
      }

      // Release client on error
      if (client) {
        try {
          await releaseClient(client);
          job.transactionClient = undefined;
        } catch (releaseErr) {
          emit(job, 'error', 'RELEASE_FAILED', `Failed to release client: ${releaseErr}`);
        }
      }

      if (job.canceled) {
        job.state = 'canceled';
        emit(job, 'warn', 'CANCELED', 'Import canceled by user');
      } else {
        job.state = 'failed';
        emit(job, 'error', 'FAILED', err?.message || 'Import failed');
      }
    } finally {
      // Always surface the timing breakdown (success, early-skip, or failure) so slow
      // imports can be diagnosed without re-running. Best-effort: never mask the outcome.
      try {
        finalizeBenchmark(job, startTime);
      } catch {
        /* benchmarking must never affect the import result */
      }
    }
  })();

  return { jobId };
}

/**
 * Commit the import transaction - called when user accepts the import
 */
export async function commitImport(jobId: string): Promise<{ success: boolean; error?: string }> {
  const job = jobs.get(jobId);
  if (!job) {
    return { success: false, error: 'Job not found' };
  }

  if (job.state !== 'pending-approval') {
    return { success: false, error: `Cannot commit import in state: ${job.state}` };
  }

  if (!job.transactionClient || !job.transactionPending) {
    return { success: false, error: 'No pending transaction to commit' };
  }

  try {
    job.state = 'committing';
    emit(job, 'info', 'COMMITTING', 'Committing import transaction...');

    await withRetry(() => commitTransaction(job.transactionClient!), {
      maxAttempts: 3,
      initialDelayMs: 500,
      label: 'commitTransaction'
    });
    job.transactionPending = false;

    emit(job, 'info', 'COMMITTED', 'Import transaction committed successfully');

    // Release the client
    await releaseClient(job.transactionClient);
    job.transactionClient = undefined;

    const versionId = job.result?.versionId as string | undefined;
    if (versionId && job.input.sourceKind === 'openapi' && job.input.document) {
      const paths = extractPaths(job.input.document);
      const securitySchemes = extractSecuritySchemes(job.input.document);
      if (paths.length > 0 || securitySchemes.length > 0) {
        emit(job, 'info', 'IMPORTING_PATHS', `Importing ${paths.length} path(s) and ${securitySchemes.length} security scheme(s)...`);
        const pathResult = await importOpenAPIPathsAndSecurity(versionId, paths, securitySchemes);
        if (pathResult.success) {
          if (job.summary) job.summary.pathsImported = paths.length;
          emit(job, 'info', 'PATHS_IMPORTED', 'Paths and security schemes imported.');
        } else {
          emit(job, 'warn', 'PATHS_IMPORT_WARN', `Paths/security import had issues: ${pathResult.error}`);
        }
      }
    }

    await recordRepositoryImportMetricIfApplicable(job);

    job.state = 'completed';
    emit(job, 'info', 'DONE', 'Import completed successfully', job.result);

    return { success: true };
  } catch (err: any) {
    emit(job, 'error', 'COMMIT_FAILED', `Failed to commit transaction: ${err?.message}`);
    job.state = 'failed';

    // Try to release the client
    if (job.transactionClient) {
      try {
        await releaseClient(job.transactionClient);
        job.transactionClient = undefined;
      } catch (releaseErr) {
        // Ignore release errors
      }
    }

    return { success: false, error: err?.message || 'Failed to commit transaction' };
  }
}

/**
 * Rollback the import transaction - called when user rejects the import or closes dialog
 */
export async function rollbackImport(jobId: string): Promise<{ success: boolean; error?: string }> {
  const job = jobs.get(jobId);
  if (!job) {
    return { success: false, error: 'Job not found' };
  }

  // Allow rollback from pending-approval or running states
  if (job.state !== 'pending-approval' && job.state !== 'running') {
    // Already finished (completed, failed, canceled, rolled-back)
    return { success: true };
  }

  if (!job.transactionClient || !job.transactionPending) {
    // No pending transaction
    job.state = 'rolled-back';
    return { success: true };
  }

  try {
    emit(job, 'info', 'ROLLING_BACK', 'Rolling back import transaction...');

    await rollbackTransaction(job.transactionClient);
    job.transactionPending = false;

    emit(job, 'info', 'ROLLED_BACK', 'Import transaction rolled back - no changes were saved');

    // Release the client
    await releaseClient(job.transactionClient);
    job.transactionClient = undefined;

    job.state = 'rolled-back';
    job.canceled = true;

    return { success: true };
  } catch (err: any) {
    emit(job, 'error', 'ROLLBACK_FAILED', `Failed to rollback transaction: ${err?.message}`);

    // Try to release the client
    if (job.transactionClient) {
      try {
        await releaseClient(job.transactionClient);
        job.transactionClient = undefined;
      } catch (releaseErr) {
        // Ignore release errors
      }
    }

    return { success: false, error: err?.message || 'Failed to rollback transaction' };
  }
}

/**
 * Rollback a completed import (#735): remove the project (and its version, classes, properties)
 * created by this import. Only allowed when the import has already been committed (state === 'completed').
 */
export async function rollbackCompletedImport(jobId: string): Promise<{ success: boolean; error?: string }> {
  const job = jobs.get(jobId);
  if (!job) {
    return { success: false, error: 'Job not found' };
  }

  if (job.state !== 'completed') {
    return { success: false, error: `Rollback of completed import is only allowed when the import has been committed (current state: ${job.state})` };
  }

  const projectId = job.result?.projectId;
  if (!projectId) {
    return { success: false, error: 'No project ID associated with this import' };
  }

  try {
    emit(job, 'info', 'ROLLBACK_STARTED', 'Rolling back completed import - removing imported project and data...');

    const raw = await permanentDeleteProject(projectId);
    const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!result.success) {
      emit(job, 'error', 'ROLLBACK_FAILED', result.error || 'Failed to delete project');
      return { success: false, error: result.error || 'Failed to delete project' };
    }

    job.state = 'rolled-back';
    job.result = undefined;
    emit(job, 'info', 'ROLLED_BACK', 'Completed import was rolled back - all imported data has been removed.');

    return { success: true };
  } catch (err: any) {
    const message = err?.message || 'Failed to rollback completed import';
    emit(job, 'error', 'ROLLBACK_FAILED', message);
    return { success: false, error: message };
  }
}

export async function getImportStatus(jobId: string) {
  const job = jobs.get(jobId);
  if (!job) {
    const ev: ImportEvent = {
      id: rndId(),
      ts: now(),
      level: 'error',
      code: 'NOT_FOUND',
      message: 'Job not found',
    };
    return { jobId, state: 'failed' as ImportJobState, percent: 0, events: [ev] };
  }
  return {
    jobId,
    state: job.state,
    percent: job.percent,
    events: job.events.slice(-200),
    progress: job.progress,
    summary: job.summary,
    transactionPending: job.transactionPending,
    result: job.result
  };
}

/**
 * Retry a failed or canceled import by re-running with the same input.
 * Returns a new job ID so the UI can switch to the new job.
 */
export async function retryImport(jobId: string): Promise<{ success: boolean; jobId?: string; error?: string }> {
  const job = jobs.get(jobId);
  if (!job) {
    return { success: false, error: 'Job not found' };
  }
  if (job.state !== 'failed' && job.state !== 'canceled') {
    return { success: false, error: `Import can only be retried when it has failed or was canceled (current state: ${job.state})` };
  }
  try {
    const { jobId: newJobId } = await startImport(job.input);
    return { success: true, jobId: newJobId };
  } catch (err: any) {
    return { success: false, error: err?.message || 'Failed to start retry' };
  }
}

export async function cancelImport(jobId: string) {
  const job = jobs.get(jobId);
  if (!job) return { success: false };

  job.canceled = true;

  // If there's a pending transaction, roll it back
  if (job.transactionClient && job.transactionPending) {
    return rollbackImport(jobId);
  }

  return { success: true };
}

