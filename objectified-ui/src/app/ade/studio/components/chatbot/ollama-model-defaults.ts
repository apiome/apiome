/**
 * Persisted default Ollama model tags for the Studio chatbot (#266).
 *
 * Preferences are stored in localStorage (best-effort). Project-level defaults
 * override tenant-level defaults when both are set and the stored tag still
 * exists in the live model list from `/api/ollama/models`.
 */

export const CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY =
  'objectified.studio.chatbot.ollamaModelDefaults.v1';

export interface OllamaModelDefaultsV1 {
  v: 1;
  /** tenantId → model name */
  byTenant: Record<string, string>;
  /** `${tenantId}::${projectId}` → model name */
  byProject: Record<string, string>;
}

export type StorageLike = Pick<Storage, 'getItem' | 'setItem'> | null;

function emptyDefaults(): OllamaModelDefaultsV1 {
  return { v: 1, byTenant: {}, byProject: {} };
}

function projectCompositeKey(tenantId: string, projectId: string): string {
  return `${tenantId}::${projectId}`;
}

export function readOllamaModelDefaults(storage: StorageLike): OllamaModelDefaultsV1 {
  if (!storage) return emptyDefaults();
  try {
    const raw = storage.getItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);
    if (!raw) return emptyDefaults();
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return emptyDefaults();
    const o = parsed as Record<string, unknown>;
    if (o.v !== 1) return emptyDefaults();
    const byTenant = o.byTenant;
    const byProject = o.byProject;
    return {
      v: 1,
      byTenant:
        byTenant && typeof byTenant === 'object' && !Array.isArray(byTenant)
          ? { ...(byTenant as Record<string, string>) }
          : {},
      byProject:
        byProject && typeof byProject === 'object' && !Array.isArray(byProject)
          ? { ...(byProject as Record<string, string>) }
          : {},
    };
  } catch {
    return emptyDefaults();
  }
}

export function writeOllamaModelDefaults(
  storage: StorageLike,
  data: OllamaModelDefaultsV1,
): void {
  if (!storage) return;
  try {
    storage.setItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Quota / privacy mode — preferences are best-effort.
  }
}

/**
 * Pick the initial model tag from saved defaults, falling back to the first
 * available name when nothing matches.
 */
export function resolvePreferredOllamaModel(input: {
  tenantId: string | null | undefined;
  projectId: string | null | undefined;
  availableModelNames: readonly string[];
  storage: StorageLike;
}): string {
  const names = [...input.availableModelNames];
  if (names.length === 0) return '';
  const data = readOllamaModelDefaults(input.storage);
  const tenantId = input.tenantId?.trim() || null;
  const projectId = input.projectId?.trim() || null;

  if (tenantId && projectId) {
    const projectKey = projectCompositeKey(tenantId, projectId);
    const projectModel = data.byProject[projectKey];
    if (projectModel && names.includes(projectModel)) return projectModel;
  }

  if (tenantId) {
    const tenantModel = data.byTenant[tenantId];
    if (tenantModel && names.includes(tenantModel)) return tenantModel;
  }

  return names[0];
}

/**
 * Save the user's current choice as the default for the active workspace.
 * When both tenant and project are known, this updates the project default.
 * With only a tenant, it updates the tenant default.
 */
export function persistOllamaModelChoiceForScope(input: {
  tenantId: string | null | undefined;
  projectId: string | null | undefined;
  modelName: string;
  storage: StorageLike;
}): void {
  if (!input.storage) return;
  const tenantId = input.tenantId?.trim() || null;
  const projectId = input.projectId?.trim() || null;
  const modelName = input.modelName.trim();
  if (!modelName) return;

  const data = readOllamaModelDefaults(input.storage);
  if (tenantId && projectId) {
    data.byProject[projectCompositeKey(tenantId, projectId)] = modelName;
  } else if (tenantId) {
    data.byTenant[tenantId] = modelName;
  } else {
    return;
  }
  writeOllamaModelDefaults(input.storage, data);
}

/**
 * Store the selected tag as the tenant-wide default (all projects), without
 * clearing the per-project map entry.
 */
export function persistOllamaModelTenantDefault(input: {
  tenantId: string | null | undefined;
  modelName: string;
  storage: StorageLike;
}): void {
  if (!input.storage) return;
  const tenantId = input.tenantId?.trim() || null;
  const modelName = input.modelName.trim();
  if (!tenantId || !modelName) return;

  const data = readOllamaModelDefaults(input.storage);
  data.byTenant[tenantId] = modelName;
  writeOllamaModelDefaults(input.storage, data);
}
