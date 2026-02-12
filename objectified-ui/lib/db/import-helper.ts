'use server';

import {
  PoolClient,
  getTransactionClient,
  beginTransaction,
  commitTransaction,
  rollbackTransaction,
  releaseClient,
  createProjectTx,
  createVersionTx,
  createPropertyTx,
  createClassTx,
  addPropertyToClassTx,
  getClassesWithPropertiesAndTagsTx
} from './import-transaction';
import { ImportSourceKind, getImporter, NormalizedClass, NormalizedProperty } from '../importers';
import { withRetry } from '../retry';
import { permanentDeleteProject } from './helper';

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
    dryRun?: boolean;
    /** When true, commit each class separately and skip failures (no single transaction). */
    incrementalMode?: boolean;
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
  summary?: {
    classesCreated: number;
    propertiesCreated: number;
    warnings: number;
    failed: number;
    totalTime?: number;
    sourceName?: string;
    projectName?: string;
    versionId?: string;
    dryRun?: boolean;
    /** True when import was run in incremental mode (skip failures, commit as we go). */
    incrementalMode?: boolean;
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
  const resClass = JSON.parse(await createClassTx(client, versionId, cls.name, cls.description || null, cls.schema || { type: 'object' }));
  if (!resClass.success) throw new Error(resClass.error || 'Failed to create class');
  const classId = resClass.class.id as string;

  const linkRec = async (classId: string, props: any[], parentId: string | null = null) => {
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
          // Still process children if any
          if (p.children && p.children.length) {
            emit(job, 'warn', 'SKIP_CHILDREN', `Also skipping ${p.children.length} child properties of "${p.name}"`);
          }
          continue;
        }
      }
      emit(job, 'info', 'DEBUG_CLASS_PROPERTY', `Adding property to class: ${p.name}`, {
        description: p.description,
        propertyId,
        parentId
      });
      const addRes = JSON.parse(
        await addPropertyToClassTx(client, classId, propertyId, p.name, p.description || null, p.data, parentId)
      );
      if (!addRes.success) {
        // Graceful degradation: log and continue with remaining properties
        emit(job, 'warn', 'PROPERTY_LINK_FAILED', `Could not add property "${p.name}" to class "${cls.name}": ${addRes.error}`, {
          className: cls.name,
          propertyName: p.name
        });
        if (job.summary) job.summary.warnings++;
        continue;
      }
      const newId = addRes.classProperty.id as string;
      if (p.children && p.children.length) await linkRec(classId, p.children, newId);
    }
  };

  await linkRec(classId, cls.properties || [], null);
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

  const job: JobState = {
    input,
    state: 'queued',
    events: [],
    percent: 0,
    transactionPending: false,
    summary: {
      classesCreated: 0,
      propertiesCreated: 0,
      warnings: 0,
      failed: 0,
      sourceName: input.project.name,
      projectName: input.project.name,
      versionId: input.version.versionId,
      classes: []
    }
  };
  jobs.set(jobId, job);

  (async () => {
    let client: PoolClient | null = null;
    const isDryRun = input.options.dryRun === true;

    try {
      job.state = 'running';
      emit(job, 'info', 'INIT', isDryRun ? 'Initializing dry run (preview only - no changes will be saved)' : 'Initializing import job');
      setProgress(job, 'initializing', 1, 0);

      const importer = getImporter(input.sourceKind);
      if (!importer) throw new Error(`No importer registered for ${input.sourceKind}`);
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
        },
      });
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
        emit(job, 'info', 'DRY_RUN', 'Dry run mode - simulating import (no database changes)');
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
        if (job.summary) job.summary.propertiesCreated = propertyMap.size;

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
        const resProj = JSON.parse(
          await withRetry(
            () => createProjectTx(client!, input.tenantId, input.userId, input.project.name, input.project.description || '', input.project.slug),
            { maxAttempts: 3, initialDelayMs: 500, label: 'createProject' }
          )
        );
        if (!resProj.success) throw new Error(resProj.error || 'Failed to create project');
        const projectId = resProj.project.id as string;
        emit(job, 'info', 'PROJECT_CREATED', `Created project: ${input.project.name}`, { projectId });
        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'creating-version', 2, 1, input.version.versionId);
        const resVer = JSON.parse(
          await withRetry(
            () => createVersionTx(client!, projectId, input.userId, input.version.versionId, input.version.description || '', 'Imported from specification'),
            { maxAttempts: 3, initialDelayMs: 500, label: 'createVersion' }
          )
        );
        if (!resVer.success) throw new Error(resVer.error || 'Failed to create version');
        const versionId = resVer.version.id as string;
        emit(job, 'info', 'VERSION_CREATED', `Created version: ${input.version.versionId}`, { versionId });

        const propertyMapInc = new Map<string, { data: any; description?: string; names: Set<string> }>();
        const propertyIdMapInc = new Map<string, string>();
        const collectPropertiesInc = (props: any[]) => {
          for (const p of props || []) {
            const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
            if (!isReference) {
              const sig = stableStringify(p.data);
              if (!propertyMapInc.has(sig)) {
                propertyMapInc.set(sig, { data: p.data, description: p.description, names: new Set<string>() });
              }
              propertyMapInc.get(sig)!.names.add(p.name);
            }
            if (p.children) collectPropertiesInc(p.children);
          }
        };
        for (const cls of norm.classes) collectPropertiesInc(cls.properties || []);

        emit(job, 'info', 'CREATING_PROPERTIES', `Creating ${propertyMapInc.size} unique properties in library`);
        const usedNamesInc = new Set<string>();
        for (const [sig, payload] of propertyMapInc.entries()) {
          if (job.canceled) throw new Error('Import canceled');
          let baseName = Array.from(payload.names)[0];
          let propName = baseName;
          let suffix = 1;
          while (usedNamesInc.has(propName)) {
            propName = `${baseName}_${suffix}`;
            suffix++;
          }
          usedNamesInc.add(propName);
          emit(job, 'info', 'DEBUG_PROPERTY', `Creating property: ${propName}`, { dataType: payload.data.type });
          const resProp = JSON.parse(
            await createPropertyTx(client!, projectId, propName, payload.description || null, payload.data)
          );
          if (!resProp.success) {
            emit(job, 'warn', 'PROPERTY_CREATE_WARN', `Could not create property "${propName}": ${resProp.error}`);
            continue;
          }
          propertyIdMapInc.set(sig, resProp.property.id);
          if (job.summary) job.summary.propertiesCreated++;
        }
        emit(job, 'info', 'PROPERTIES_CREATED', `Created ${propertyIdMapInc.size} properties in library`);

        setProgress(job, 'creating-classes', 2 + norm.classes.length, 2);
        let classCountInc = 0;
        for (const cls of norm.classes) {
          if (job.canceled) throw new Error('Import canceled');
          setProgress(job, 'creating-classes', 2 + norm.classes.length, 2 + classCountInc, cls.name);
          try {
            await beginTransaction(client!);
            await writeClassWithProperties(client!, projectId, versionId, cls, job, propertyIdMapInc);
            await commitTransaction(client!);
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

        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'verifying', 3 + norm.classes.length, 2 + norm.classes.length, 'Verifying import...');
        const verificationResultInc = await verifyImport(client!, versionId, norm.classes, job);
        if (job.summary) job.summary.verification = verificationResultInc;
        if (!verificationResultInc.passed && job.summary) job.summary.warnings++;

        setProgress(job, 'finalizing', 3 + norm.classes.length, 3 + norm.classes.length);
        job.state = 'completed';
        job.result = { projectId, versionId };
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
      const resProj = JSON.parse(
        await withRetry(
          () => createProjectTx(client!, input.tenantId, input.userId, input.project.name, input.project.description || '', input.project.slug),
          { maxAttempts: 3, initialDelayMs: 500, label: 'createProject' }
        )
      );
      if (!resProj.success) throw new Error(resProj.error || 'Failed to create project');
      const projectId = resProj.project.id as string;
      emit(job, 'info', 'PROJECT_CREATED', `Created project: ${input.project.name}`, { projectId });

      if (job.canceled) throw new Error('Import canceled');

      setProgress(job, 'creating-version', 2, 1, input.version.versionId);
      const resVer = JSON.parse(
        await withRetry(
          () => createVersionTx(client!, projectId, input.userId, input.version.versionId, input.version.description || '', 'Imported from specification'),
          { maxAttempts: 3, initialDelayMs: 500, label: 'createVersion' }
        )
      );
      if (!resVer.success) throw new Error(resVer.error || 'Failed to create version');
      const versionId = resVer.version.id as string;
      emit(job, 'info', 'VERSION_CREATED', `Created version: ${input.version.versionId}`, { versionId });

      // Build property library: collect all unique non-reference properties
      // Key: JSON signature of the property data
      // Value: { data, description, names } - tracks which names this property appears under
      const propertyMap = new Map<string, { data: any; description?: string; names: Set<string> }>();
      const propertyIdMap = new Map<string, string>(); // sig -> propertyId

      const collectProperties = (props: any[]) => {
        for (const p of props || []) {
          const isReference = p.data.$ref || (p.data.type === 'array' && p.data.items?.$ref);
          if (!isReference) {
            const sig = stableStringify(p.data);
            if (!propertyMap.has(sig)) {
              propertyMap.set(sig, { data: p.data, description: p.description, names: new Set<string>() });
            }
            // Track all names this property appears under
            propertyMap.get(sig)!.names.add(p.name);
          }
          if (p.children) collectProperties(p.children);
        }
      };

      for (const cls of norm.classes) {
        collectProperties(cls.properties || []);
      }

      // Create properties in the library using the first/most common name
      // If name conflicts, append a numeric suffix
      emit(job, 'info', 'CREATING_PROPERTIES', `Creating ${propertyMap.size} unique properties in library`);
      const usedNames = new Set<string>();

      for (const [sig, payload] of propertyMap.entries()) {
        if (job.canceled) throw new Error('Import canceled');

        // Use the first name from the set of names this property appears under
        // If the name is already used, append a suffix
        let baseName = Array.from(payload.names)[0];
        let propName = baseName;
        let suffix = 1;
        while (usedNames.has(propName)) {
          propName = `${baseName}_${suffix}`;
          suffix++;
        }
        usedNames.add(propName);

        emit(job, 'info', 'DEBUG_PROPERTY', `Creating property: ${propName} (used as: ${Array.from(payload.names).join(', ')})`, {
          description: payload.description,
          dataType: payload.data.type
        });
        const resCreateProp = JSON.parse(
          await createPropertyTx(client, projectId, propName, payload.description || null, payload.data)
        );
        if (!resCreateProp.success) {
          // If it still fails (maybe due to existing property from a previous import), log and skip
          emit(job, 'warn', 'PROPERTY_CREATE_WARN', `Could not create property "${propName}": ${resCreateProp.error}`);
          continue;
        }
        emit(job, 'info', 'DEBUG_PROPERTY_CREATED', `Property created with ID: ${resCreateProp.property.id}`);
        propertyIdMap.set(sig, resCreateProp.property.id);
        if (job.summary) job.summary.propertiesCreated++;
      }
      emit(job, 'info', 'PROPERTIES_CREATED', `Created ${propertyIdMap.size} properties in library`);

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
  if (!job) return { jobId, state: 'failed' as ImportJobState, percent: 0, events: [{ id: rndId(), ts: now(), level: 'error' as ImportLogLevel, code: 'NOT_FOUND', message: 'Job not found' }] };
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

