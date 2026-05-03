/**
 * @jest-environment jsdom
 */

import {
  CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY,
  persistOllamaModelChoiceForScope,
  persistOllamaModelTenantDefault,
  readOllamaModelDefaults,
  resolvePreferredOllamaModel,
  writeOllamaModelDefaults,
} from '../../src/app/ade/studio/components/chatbot/ollama-model-defaults';

function createMemoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear() {
      m.clear();
    },
    getItem(key: string) {
      return m.get(key) ?? null;
    },
    key() {
      return null;
    },
    removeItem(key: string) {
      m.delete(key);
    },
    setItem(key: string, value: string) {
      m.set(key, value);
    },
  } as Storage;
}

describe('ollama-model-defaults (#266)', () => {
  it('resolvePreferredOllamaModel prefers project over tenant over first listed', () => {
    const storage = createMemoryStorage();
    writeOllamaModelDefaults(storage, {
      v: 1,
      byTenant: { t1: 'tenant-model:latest' },
      byProject: { 't1::p1': 'project-model:latest' },
    });

    const names = ['first:latest', 'project-model:latest', 'tenant-model:latest'] as const;
    expect(
      resolvePreferredOllamaModel({
        tenantId: 't1',
        projectId: 'p1',
        availableModelNames: names,
        storage,
      }),
    ).toBe('project-model:latest');

    expect(
      resolvePreferredOllamaModel({
        tenantId: 't1',
        projectId: 'p2',
        availableModelNames: names,
        storage,
      }),
    ).toBe('tenant-model:latest');

    expect(
      resolvePreferredOllamaModel({
        tenantId: 't2',
        projectId: 'p1',
        availableModelNames: names,
        storage,
      }),
    ).toBe('first:latest');
  });

  it('ignores stored tags that are no longer installed', () => {
    const storage = createMemoryStorage();
    writeOllamaModelDefaults(storage, {
      v: 1,
      byTenant: {},
      byProject: { 't1::p1': 'ghost:latest' },
    });

    expect(
      resolvePreferredOllamaModel({
        tenantId: 't1',
        projectId: 'p1',
        availableModelNames: ['only:latest'],
        storage,
      }),
    ).toBe('only:latest');
  });

  it('persistOllamaModelChoiceForScope writes project composite key when both ids exist', () => {
    const storage = createMemoryStorage();
    persistOllamaModelChoiceForScope({
      tenantId: 't1',
      projectId: 'p1',
      modelName: 'pick:latest',
      storage,
    });
    const raw = storage.getItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const data = readOllamaModelDefaults(storage);
    expect(data.byProject['t1::p1']).toBe('pick:latest');
    expect(Object.keys(data.byTenant)).toHaveLength(0);
  });

  it('persistOllamaModelChoiceForScope writes tenant when project is missing', () => {
    const storage = createMemoryStorage();
    persistOllamaModelChoiceForScope({
      tenantId: 't1',
      projectId: null,
      modelName: 'solo:latest',
      storage,
    });
    const data = readOllamaModelDefaults(storage);
    expect(data.byTenant.t1).toBe('solo:latest');
  });

  it('persistOllamaModelTenantDefault updates tenant map without removing project entries', () => {
    const storage = createMemoryStorage();
    persistOllamaModelChoiceForScope({
      tenantId: 't1',
      projectId: 'p1',
      modelName: 'a:latest',
      storage,
    });
    persistOllamaModelTenantDefault({
      tenantId: 't1',
      modelName: 'b:latest',
      storage,
    });
    const data = readOllamaModelDefaults(storage);
    expect(data.byProject['t1::p1']).toBe('a:latest');
    expect(data.byTenant.t1).toBe('b:latest');
  });
});
