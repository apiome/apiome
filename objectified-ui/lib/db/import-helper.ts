'use server';

import { createProject, createVersion, createClass, addPropertyToClass, createProperty } from './helper';
import { ImportSourceKind, getImporter, NormalizedClass } from '../importers';

export type ImportJobState = 'queued' | 'running' | 'completed' | 'failed' | 'canceled';

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
    applyNamingConvention?: boolean;
    dryRun?: boolean;
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
}

const jobs = new Map<string, JobState>();

const rndId = () => Math.random().toString(36).slice(2);
const now = () => Date.now();

function emit(job: JobState, level: ImportLogLevel, code: string, message: string, context?: any) {
  job.events.push({ id: rndId(), ts: now(), level, code, message, context });
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

async function writeClassWithProperties(
  projectId: string,
  versionId: string,
  cls: NormalizedClass,
  job: JobState,
  propertyIdMap: Map<string, string>
) {
  const resClass = JSON.parse(await createClass(versionId, cls.name, cls.description || null, cls.schema || { type: 'object' }));
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
        await addPropertyToClass(classId, propertyId, p.name, p.description || null, p.data, parentId)
      );
      if (!addRes.success) throw new Error(addRes.error || 'Failed to add property');
      const newId = addRes.classProperty.id as string;
      if (p.children && p.children.length) await linkRec(classId, p.children, newId);
    }
  };

  await linkRec(classId, cls.properties || [], null);
}

export async function startImport(input: ImportJobInput) {
  const jobId = rndId();
  const job: JobState = { input, state: 'queued', events: [], percent: 0 };
  jobs.set(jobId, job);

  (async () => {
    try {
      job.state = 'running';
      emit(job, 'info', 'INIT', 'Initializing import job');
      setProgress(job, 'initializing', 1, 0);

      const importer = getImporter(input.sourceKind);
      if (!importer) throw new Error(`No importer registered for ${input.sourceKind}`);
      const norm = importer.normalize({ document: input.document, options: { selectedSchemas: input.options.selectedSchemas } });
      if (norm.warnings.length) emit(job, 'warn', 'NORMALIZE_WARN', norm.warnings.join('\n'));

      if (job.canceled) throw new Error('Import canceled');

      setProgress(job, 'creating-project', 1, 0, input.project.name);
      const resProj = JSON.parse(await createProject(input.tenantId, input.userId, input.project.name, input.project.description || '', input.project.slug));
      if (!resProj.success) throw new Error(resProj.error || 'Failed to create project');
      const projectId = resProj.project.id as string;
      emit(job, 'info', 'PROJECT_CREATED', `Created project: ${input.project.name}`, { projectId });

      if (job.canceled) throw new Error('Import canceled');

      setProgress(job, 'creating-version', 2, 1, input.version.versionId);
      const resVer = JSON.parse(await createVersion(projectId, input.userId, input.version.versionId, input.version.description || '', 'Imported from specification'));
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
          await createProperty(projectId, propName, payload.description || null, payload.data)
        );
        if (!resCreateProp.success) {
          // If it still fails (maybe due to existing property from a previous import), log and skip
          emit(job, 'warn', 'PROPERTY_CREATE_WARN', `Could not create property "${propName}": ${resCreateProp.error}`);
          continue;
        }
        emit(job, 'info', 'DEBUG_PROPERTY_CREATED', `Property created with ID: ${resCreateProp.property.id}`);
        propertyIdMap.set(sig, resCreateProp.property.id);
      }
      emit(job, 'info', 'PROPERTIES_CREATED', `Created ${propertyIdMap.size} properties in library`);

      // Create classes and link properties
      setProgress(job, 'creating-classes', 2 + norm.classes.length, 2);
      let classCount = 0;
      for (const cls of norm.classes) {
        if (job.canceled) throw new Error('Import canceled');
        setProgress(job, 'creating-classes', 2 + norm.classes.length, 2 + classCount, cls.name);
        await writeClassWithProperties(projectId, versionId, cls, job, propertyIdMap);
        emit(job, 'info', 'CLASS_CREATED', `Imported class: ${cls.name}`);
        classCount++;
      }

      setProgress(job, 'finalizing', 2 + norm.classes.length, 2 + norm.classes.length);
      job.state = 'completed';
      job.result = { projectId, versionId };
      emit(job, 'info', 'DONE', 'Import completed successfully', job.result);
    } catch (err: any) {
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

export async function getImportStatus(jobId: string) {
  const job = jobs.get(jobId);
  if (!job) return { jobId, state: 'failed' as ImportJobState, percent: 0, events: [{ id: rndId(), ts: now(), level: 'error' as ImportLogLevel, code: 'NOT_FOUND', message: 'Job not found' }] };
  return { jobId, state: job.state, percent: job.percent, events: job.events.slice(-200), progress: job.progress, summary: job.result };
}

export async function cancelImport(jobId: string) {
  const job = jobs.get(jobId);
  if (!job) return { success: false };
  job.canceled = true;
  return { success: true };
}

