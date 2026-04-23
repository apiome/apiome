/**
 * Tests for the conversation persistence layer (#261).
 *
 * Pins the storage adapter contract, scope filtering, search, export, and
 * the safety net around quota / SSR conditions so the chat surface can rely
 * on the store without defensive boilerplate.
 */

import {
  CHAT_HISTORY_MAX_CONVERSATIONS,
  CHAT_HISTORY_TITLE_CHAR_CAP,
  buildStoredConversation,
  createConversationStore,
  createLocalStorageConversationStorage,
  createMemoryConversationStorage,
  deriveConversationTitle,
  exportConversationToMarkdown,
  exportConversationsToMarkdown,
  type StoredConversation,
} from '../../src/app/ade/studio/components/chatbot/conversation-store';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

function user(content: string, id = `u-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'user', content };
}

function assistant(content: string, id = `a-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'assistant', content };
}

function makeConversation(overrides: Partial<StoredConversation> = {}): StoredConversation {
  return {
    id: overrides.id ?? 'c-1',
    projectId: overrides.projectId ?? null,
    versionId: overrides.versionId ?? null,
    title: overrides.title ?? 'Sample',
    createdAt: overrides.createdAt ?? 100,
    updatedAt: overrides.updatedAt ?? 200,
    messages: overrides.messages ?? [user('hi'), assistant('hello')],
  };
}

describe('deriveConversationTitle', () => {
  it('falls back to a sentinel when the transcript is empty', () => {
    expect(deriveConversationTitle([])).toBe('Untitled conversation');
  });

  it('uses the first user prompt as the title and collapses whitespace', () => {
    const messages: ChatMessage[] = [
      user('  Sketch a   schema\nfor users  '),
      assistant('done'),
    ];
    expect(deriveConversationTitle(messages)).toBe('Sketch a schema for users');
  });

  it('skips pending or empty messages when picking the title seed', () => {
    const messages: ChatMessage[] = [
      { id: 'p', role: 'user', content: '   ' },
      assistant('hello'),
    ];
    expect(deriveConversationTitle(messages)).toBe('hello');
  });

  it('caps long titles at the configured character budget', () => {
    const long = 'word '.repeat(40).trim();
    const title = deriveConversationTitle([user(long)]);
    expect(title.length).toBeLessThanOrEqual(CHAT_HISTORY_TITLE_CHAR_CAP);
    expect(title.endsWith('…')).toBe(true);
  });
});

describe('createConversationStore (memory adapter)', () => {
  it('lists conversations newest-first', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'a', updatedAt: 1 }));
    store.save(makeConversation({ id: 'b', updatedAt: 3 }));
    store.save(makeConversation({ id: 'c', updatedAt: 2 }));
    expect(store.list().map((c) => c.id)).toEqual(['b', 'c', 'a']);
  });

  it('upserts by id rather than appending duplicates', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'a', title: 'first', updatedAt: 1 }));
    store.save(makeConversation({ id: 'a', title: 'second', updatedAt: 5 }));
    const list = store.list();
    expect(list).toHaveLength(1);
    expect(list[0].title).toBe('second');
  });

  it('filters by scope using project + version null-safe equality', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'global' }));
    store.save(makeConversation({ id: 'p1-only', projectId: 'p1' }));
    store.save(makeConversation({ id: 'p1-v1', projectId: 'p1', versionId: 'v1' }));
    store.save(makeConversation({ id: 'p2-v1', projectId: 'p2', versionId: 'v1' }));

    expect(store.list({ projectId: 'p1', versionId: 'v1' }).map((c) => c.id)).toEqual(['p1-v1']);
    expect(store.list({ projectId: 'p1' }).map((c) => c.id).sort()).toEqual(['p1-only', 'p1-v1']);
    expect(store.list({ projectId: null, versionId: null }).map((c) => c.id)).toEqual(['global']);
  });

  it('removes a single conversation by id without touching others', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'a', updatedAt: 1 }));
    store.save(makeConversation({ id: 'b', updatedAt: 2 }));
    store.remove('a');
    expect(store.list().map((c) => c.id)).toEqual(['b']);
    // Removing an unknown id is a no-op.
    expect(() => store.remove('missing')).not.toThrow();
  });

  it('clears every conversation in a scope', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'p1-a', projectId: 'p1', versionId: 'v1' }));
    store.save(makeConversation({ id: 'p1-b', projectId: 'p1', versionId: 'v1' }));
    store.save(makeConversation({ id: 'p2-a', projectId: 'p2', versionId: 'v1' }));
    store.clear({ projectId: 'p1', versionId: 'v1' });
    expect(store.list().map((c) => c.id)).toEqual(['p2-a']);
  });

  it('clears every conversation when no scope is provided', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'a' }));
    store.save(makeConversation({ id: 'b', projectId: 'p1' }));
    store.clear();
    expect(store.list()).toEqual([]);
  });

  it('searches across titles and message content case-insensitively', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(
      makeConversation({
        id: 'a',
        title: 'Cart schema',
        messages: [user('design cart')],
        updatedAt: 1,
      }),
    );
    store.save(
      makeConversation({
        id: 'b',
        title: 'Catalog',
        messages: [user('product catalog'), assistant('here is a SKU map')],
        updatedAt: 2,
      }),
    );
    store.save(
      makeConversation({
        id: 'c',
        title: 'Auth',
        messages: [user('login flow')],
        updatedAt: 3,
      }),
    );
    expect(store.search('cart').map((c) => c.id)).toEqual(['a']);
    expect(store.search('SKU').map((c) => c.id)).toEqual(['b']);
    expect(store.search('').map((c) => c.id)).toEqual(['c', 'b', 'a']);
  });

  it('search respects the optional scope', () => {
    const store = createConversationStore(createMemoryConversationStorage());
    store.save(makeConversation({ id: 'p1', projectId: 'p1', title: 'cart', updatedAt: 2 }));
    store.save(makeConversation({ id: 'p2', projectId: 'p2', title: 'cart', updatedAt: 1 }));
    expect(store.search('cart', { projectId: 'p1' }).map((c) => c.id)).toEqual(['p1']);
  });

  it('prunes stored conversations per scope when the cap is exceeded', () => {
    const adapter = createMemoryConversationStorage();
    const store = createConversationStore(adapter);
    for (let i = 0; i < CHAT_HISTORY_MAX_CONVERSATIONS + 5; i += 1) {
      store.save(
        makeConversation({
          id: `p1-${i}`,
          projectId: 'p1',
          versionId: 'v1',
          updatedAt: 1000 + i,
        }),
      );
    }
    const all = adapter.read();
    expect(all.filter((c) => c.projectId === 'p1')).toHaveLength(CHAT_HISTORY_MAX_CONVERSATIONS);
    // Newest survive — the very latest must still be present.
    const ids = all.map((c) => c.id);
    expect(ids).toContain(`p1-${CHAT_HISTORY_MAX_CONVERSATIONS + 4}`);
    expect(ids).not.toContain('p1-0');
  });

  it('caps separately per scope so unrelated projects do not evict each other', () => {
    const adapter = createMemoryConversationStorage();
    const store = createConversationStore(adapter);
    store.save(makeConversation({ id: 'p1-only', projectId: 'p1', updatedAt: 1 }));
    for (let i = 0; i < CHAT_HISTORY_MAX_CONVERSATIONS + 3; i += 1) {
      store.save(makeConversation({ id: `p2-${i}`, projectId: 'p2', updatedAt: 100 + i }));
    }
    expect(adapter.read().some((c) => c.id === 'p1-only')).toBe(true);
  });
});

describe('createLocalStorageConversationStorage', () => {
  it('round-trips conversations through a real storage instance', () => {
    const memory = new Map<string, string>();
    const storage: Storage = {
      get length() {
        return memory.size;
      },
      clear: () => memory.clear(),
      getItem: (key) => memory.get(key) ?? null,
      key: (i) => Array.from(memory.keys())[i] ?? null,
      removeItem: (key) => {
        memory.delete(key);
      },
      setItem: (key, value) => {
        memory.set(key, value);
      },
    };
    const adapter = createLocalStorageConversationStorage('test-key', () => storage);
    adapter.write([makeConversation({ id: 'a', updatedAt: 1 })]);
    expect(adapter.read()).toEqual([makeConversation({ id: 'a', updatedAt: 1 })]);
  });

  it('returns an empty list when storage is unavailable (SSR / private mode)', () => {
    const adapter = createLocalStorageConversationStorage('test-key', () => null);
    expect(adapter.read()).toEqual([]);
    expect(() => adapter.write([makeConversation()])).not.toThrow();
  });

  it('swallows JSON parse errors and returns an empty list', () => {
    const memory = new Map<string, string>([['test-key', 'not-json']]);
    const storage: Storage = {
      get length() {
        return memory.size;
      },
      clear: () => memory.clear(),
      getItem: (key) => memory.get(key) ?? null,
      key: (i) => Array.from(memory.keys())[i] ?? null,
      removeItem: (key) => {
        memory.delete(key);
      },
      setItem: (key, value) => {
        memory.set(key, value);
      },
    };
    const adapter = createLocalStorageConversationStorage('test-key', () => storage);
    expect(adapter.read()).toEqual([]);
  });

  it('drops malformed entries when reading', () => {
    const payload = JSON.stringify([
      makeConversation({ id: 'good' }),
      { id: 'bad', random: true },
    ]);
    const memory = new Map<string, string>([['test-key', payload]]);
    const storage: Storage = {
      get length() {
        return memory.size;
      },
      clear: () => memory.clear(),
      getItem: (key) => memory.get(key) ?? null,
      key: (i) => Array.from(memory.keys())[i] ?? null,
      removeItem: (key) => {
        memory.delete(key);
      },
      setItem: (key, value) => {
        memory.set(key, value);
      },
    };
    const adapter = createLocalStorageConversationStorage('test-key', () => storage);
    expect(adapter.read().map((c) => c.id)).toEqual(['good']);
  });

  it('drops conversations whose messages array contains malformed entries', () => {
    const badMessages = JSON.stringify([
      makeConversation({ id: 'good' }),
      {
        id: 'bad-msgs',
        title: 'Looks fine',
        createdAt: 1,
        updatedAt: 2,
        projectId: null,
        versionId: null,
        // messages entries lack the required id/role/content shape
        messages: ['string', null, { notAMessage: true }],
      },
    ]);
    const memory = new Map<string, string>([['test-key', badMessages]]);
    const storage: Storage = {
      get length() {
        return memory.size;
      },
      clear: () => memory.clear(),
      getItem: (key) => memory.get(key) ?? null,
      key: (i) => Array.from(memory.keys())[i] ?? null,
      removeItem: (key) => {
        memory.delete(key);
      },
      setItem: (key, value) => {
        memory.set(key, value);
      },
    };
    const adapter = createLocalStorageConversationStorage('test-key', () => storage);
    // The conversation with malformed messages must be silently dropped so
    // downstream code cannot call m.content.toLowerCase() on a non-string.
    expect(adapter.read().map((c) => c.id)).toEqual(['good']);
  });

  it('swallows quota errors during write', () => {
    const storage: Storage = {
      length: 0,
      clear: () => {},
      getItem: () => null,
      key: () => null,
      removeItem: () => {},
      setItem: () => {
        throw new DOMException('Quota exceeded', 'QuotaExceededError');
      },
    };
    const adapter = createLocalStorageConversationStorage('test-key', () => storage);
    expect(() => adapter.write([makeConversation()])).not.toThrow();
  });
});

describe('exportConversationToMarkdown', () => {
  it('renders a heading, metadata bullets, and role sections', () => {
    const conversation = makeConversation({
      id: 'export-1',
      title: 'Cart schema',
      projectId: 'proj-1',
      versionId: 'ver-1',
      createdAt: Date.UTC(2026, 3, 1),
      updatedAt: Date.UTC(2026, 3, 2),
      messages: [user('design a cart'), assistant('here you go')],
    });
    const md = exportConversationToMarkdown(conversation);
    expect(md.startsWith('# Cart schema')).toBe(true);
    expect(md).toMatch(/Project: proj-1/);
    expect(md).toMatch(/Version: ver-1/);
    expect(md).toMatch(/## User/);
    expect(md).toMatch(/design a cart/);
    expect(md).toMatch(/## Assistant/);
    expect(md).toMatch(/here you go/);
  });

  it('omits pending messages from the export', () => {
    const conversation = makeConversation({
      messages: [user('hi'), { id: 'p', role: 'assistant', content: '', pending: true }],
    });
    const md = exportConversationToMarkdown(conversation);
    expect(md).not.toMatch(/_\(empty\)_/);
    expect(md).not.toMatch(/## Assistant/);
  });

  it('joins multiple conversations with horizontal-rule dividers', () => {
    const md = exportConversationsToMarkdown([
      makeConversation({ id: 'a', title: 'first' }),
      makeConversation({ id: 'b', title: 'second' }),
    ]);
    expect(md).toMatch(/# first[\s\S]*---[\s\S]*# second/);
  });

  it('returns an empty string for an empty list', () => {
    expect(exportConversationsToMarkdown([])).toBe('');
  });
});

describe('buildStoredConversation', () => {
  it('seeds id, title, and timestamps from the running transcript', () => {
    const now = jest.fn(() => 12345);
    const stored = buildStoredConversation({
      scope: { projectId: 'p1', versionId: 'v1' },
      messages: [user('Design a billing schema')],
      now,
    });
    expect(stored.projectId).toBe('p1');
    expect(stored.versionId).toBe('v1');
    expect(stored.title).toBe('Design a billing schema');
    expect(stored.createdAt).toBe(12345);
    expect(stored.updatedAt).toBe(12345);
    expect(stored.id).toMatch(/^chat-conv-/);
  });

  it('preserves the supplied id and createdAt while bumping updatedAt to "now"', () => {
    let count = 0;
    const now = () => 1000 + count++ * 10;
    const stored = buildStoredConversation({
      id: 'conv-existing',
      scope: { projectId: null, versionId: null },
      messages: [user('q')],
      createdAt: 50,
      now,
    });
    expect(stored.id).toBe('conv-existing');
    expect(stored.createdAt).toBe(50);
    expect(stored.updatedAt).toBeGreaterThanOrEqual(1000);
  });

  it('clones messages so mutating the returned object does not leak back', () => {
    const messages: ChatMessage[] = [user('q')];
    const stored = buildStoredConversation({
      scope: { projectId: null, versionId: null },
      messages,
    });
    stored.messages[0].content = 'mutated';
    expect(messages[0].content).toBe('q');
  });
});
