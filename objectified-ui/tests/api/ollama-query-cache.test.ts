/**
 * Tests for Ollama chat query cache (#524 exact match, #525 semantic similarity).
 */

import {
  clearOllamaChatQueryCacheForTests,
  cosineSimilarity,
  findSemanticallySimilarCachedResponse,
  getCachedOllamaChatResponse,
  isOllamaQueryCacheDisabled,
  isOllamaSemanticCacheDisabled,
  normalizeSchemaContextFingerprint,
  ollamaChatCacheKey,
  ollamaChatMessagesFingerprint,
  ollamaChatSemanticContextKey,
  ollamaSemanticCacheThreshold,
  setCachedOllamaChatResponse,
  stableStringify,
} from '../../src/app/api/ollama/chat/query-cache';

describe('stableStringify', () => {
  it('orders object keys deterministically', () => {
    expect(stableStringify({ b: 1, a: 2 })).toBe(stableStringify({ a: 2, b: 1 }));
  });

  it('handles nested objects and arrays', () => {
    expect(stableStringify({ z: [{ m: 1, n: 2 }], a: 0 })).toBe(
      stableStringify({ a: 0, z: [{ n: 2, m: 1 }] }),
    );
  });
});

describe('ollamaChatCacheKey', () => {
  it('ignores model string outer whitespace', () => {
    const inner = { messages: [{ role: 'user', content: 'Hi' }] };
    expect(ollamaChatCacheKey({ model: '  qwen  ', ...inner })).toBe(
      ollamaChatCacheKey({ model: 'qwen', ...inner }),
    );
  });

  it('changes when messages change', () => {
    const a = ollamaChatCacheKey({
      model: 'm',
      messages: [{ role: 'user', content: 'a' }],
    });
    const b = ollamaChatCacheKey({
      model: 'm',
      messages: [{ role: 'user', content: 'b' }],
    });
    expect(a).not.toBe(b);
  });

  it('changes when schemaContextFingerprint differs (#526)', () => {
    const base = { model: 'm', messages: [{ role: 'user', content: 'same' }] };
    const k1 = ollamaChatCacheKey({ ...base, schemaContextFingerprint: 'aaa' });
    const k2 = ollamaChatCacheKey({ ...base, schemaContextFingerprint: 'bbb' });
    const kNone = ollamaChatCacheKey({ ...base });
    expect(k1).not.toBe(k2);
    expect(k1).not.toBe(kNone);
  });
});

describe('normalizeSchemaContextFingerprint', () => {
  it('returns null for empty or non-string', () => {
    expect(normalizeSchemaContextFingerprint(undefined)).toBeNull();
    expect(normalizeSchemaContextFingerprint('')).toBeNull();
    expect(normalizeSchemaContextFingerprint('   ')).toBeNull();
    expect(normalizeSchemaContextFingerprint(1)).toBeNull();
  });

  it('trims and caps length', () => {
    expect(normalizeSchemaContextFingerprint('  abcd  ')).toBe('abcd');
    const long = 'x'.repeat(200);
    expect(normalizeSchemaContextFingerprint(long)?.length).toBe(128);
  });
});

describe('LRU get/set', () => {
  const prevDisabled = process.env.OLLAMA_CHAT_CACHE_DISABLED;

  beforeEach(() => {
    clearOllamaChatQueryCacheForTests();
  });

  afterEach(() => {
    clearOllamaChatQueryCacheForTests();
    if (prevDisabled === undefined) delete process.env.OLLAMA_CHAT_CACHE_DISABLED;
    else process.env.OLLAMA_CHAT_CACHE_DISABLED = prevDisabled;
  });

  it('stores and returns a response for the same key', () => {
    const key = `524-store-${Math.random().toString(36).slice(2)}`;
    setCachedOllamaChatResponse(key, { text: 'hello', usage: { promptTokens: 1, completionTokens: 2 } });
    expect(getCachedOllamaChatResponse(key)).toEqual({
      text: 'hello',
      usage: { promptTokens: 1, completionTokens: 2 },
    });
  });

  it('does not store empty text', () => {
    const key = `524-empty-${Math.random().toString(36).slice(2)}`;
    setCachedOllamaChatResponse(key, { text: '   ' });
    expect(getCachedOllamaChatResponse(key)).toBeUndefined();
  });

  it('respects OLLAMA_CHAT_CACHE_DISABLED for reads and writes', () => {
    process.env.OLLAMA_CHAT_CACHE_DISABLED = '1';
    expect(isOllamaQueryCacheDisabled()).toBe(true);
    const key = `524-off-${Math.random().toString(36).slice(2)}`;
    setCachedOllamaChatResponse(key, { text: 'y' });
    expect(getCachedOllamaChatResponse(key)).toBeUndefined();
  });
});

describe('cosineSimilarity', () => {
  it('returns 1 for identical vectors', () => {
    expect(cosineSimilarity([1, 2, 3], [1, 2, 3])).toBeCloseTo(1, 5);
  });

  it('returns 0 for orthogonal vectors', () => {
    expect(cosineSimilarity([1, 0], [0, 1])).toBe(0);
  });
});

describe('ollamaChatSemanticContextKey', () => {
  it('is unchanged by different message payloads for the same structural fields', () => {
    const base = { model: 'm', task: 'data_query', tableNames: ['A'] };
    const sk = ollamaChatSemanticContextKey(base);
    expect(sk).toBe(ollamaChatSemanticContextKey({ ...base }));
    expect(ollamaChatCacheKey({ ...base, messages: [{ role: 'user', content: 'a' }] })).not.toBe(
      ollamaChatCacheKey({ ...base, messages: [{ role: 'user', content: 'b' }] }),
    );
    expect(sk).toBe(ollamaChatSemanticContextKey(base));
  });

  it('changes when model or task changes', () => {
    const a = ollamaChatSemanticContextKey({ model: 'a', task: 't1' });
    const b = ollamaChatSemanticContextKey({ model: 'b', task: 't1' });
    const c = ollamaChatSemanticContextKey({ model: 'a', task: 't2' });
    expect(new Set([a, b, c]).size).toBe(3);
  });

  it('changes when versionId differs (prevents cross-tenant cache hits)', () => {
    const base = { model: 'm', task: 'class_skeleton' };
    const k1 = ollamaChatSemanticContextKey({ ...base, versionId: 'v1' });
    const k2 = ollamaChatSemanticContextKey({ ...base, versionId: 'v2' });
    const kNone = ollamaChatSemanticContextKey({ ...base });
    expect(k1).not.toBe(k2);
    expect(k1).not.toBe(kNone);
    expect(k2).not.toBe(kNone);
  });

  it('changes when schemaContextFingerprint differs (#526)', () => {
    const base = { model: 'm', task: undefined };
    const a = ollamaChatSemanticContextKey({ ...base, schemaContextFingerprint: 'f1' });
    const b = ollamaChatSemanticContextKey({ ...base, schemaContextFingerprint: 'f2' });
    expect(a).not.toBe(b);
  });
});

describe('ollamaChatMessagesFingerprint', () => {
  it('matches stableStringify of messages', () => {
    const m = [{ role: 'user', content: 'hello' }];
    expect(ollamaChatMessagesFingerprint(m)).toBe(stableStringify(m));
  });
});

describe('findSemanticallySimilarCachedResponse', () => {
  const prevSemanticOff = process.env.OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED;
  const prevCacheOff = process.env.OLLAMA_CHAT_CACHE_DISABLED;
  const prevThreshold = process.env.OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD;

  beforeEach(() => {
    clearOllamaChatQueryCacheForTests();
    delete process.env.OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED;
    delete process.env.OLLAMA_CHAT_CACHE_DISABLED;
    delete process.env.OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD;
  });

  afterEach(() => {
    clearOllamaChatQueryCacheForTests();
    if (prevSemanticOff === undefined) delete process.env.OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED;
    else process.env.OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED = prevSemanticOff;
    if (prevCacheOff === undefined) delete process.env.OLLAMA_CHAT_CACHE_DISABLED;
    else process.env.OLLAMA_CHAT_CACHE_DISABLED = prevCacheOff;
    if (prevThreshold === undefined) delete process.env.OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD;
    else process.env.OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD = prevThreshold;
  });

  it('returns the best entry above threshold with matching semantic context', () => {
    const ctx = 'ctx-525-' + Math.random().toString(36).slice(2);
    const query = [1, 0] as const;
    const e1 = [Math.cos(0.25), Math.sin(0.25)] as const;
    const e2 = [Math.cos(0.05), Math.sin(0.05)] as const;
    expect(cosineSimilarity([...query], [...e1])).toBeGreaterThanOrEqual(0.9);
    expect(cosineSimilarity([...query], [...e2])).toBeGreaterThan(cosineSimilarity([...query], [...e1]));
    setCachedOllamaChatResponse(`525-a-${Math.random().toString(36).slice(2)}`, {
      text: 'lower similarity',
      semanticContextKey: ctx,
      embedding: [...e1],
    });
    setCachedOllamaChatResponse(`525-b-${Math.random().toString(36).slice(2)}`, {
      text: 'higher similarity',
      semanticContextKey: ctx,
      embedding: [...e2],
    });
    const found = findSemanticallySimilarCachedResponse({
      semanticContextKey: ctx,
      embedding: [...query],
      threshold: 0.9,
    });
    expect(found?.entry.text).toBe('higher similarity');
  });

  it('returns both key and entry on semantic hit', () => {
    const ctx = 'ctx-525-key-' + Math.random().toString(36).slice(2);
    const hitKey = `525-key-${Math.random().toString(36).slice(2)}`;
    setCachedOllamaChatResponse(hitKey, {
      text: 'keyed entry',
      semanticContextKey: ctx,
      embedding: [1, 0],
    });
    const found = findSemanticallySimilarCachedResponse({
      semanticContextKey: ctx,
      embedding: [1, 0],
      threshold: 0.5,
    });
    expect(found).toBeDefined();
    expect(found?.key).toBe(hitKey);
    expect(found?.entry.text).toBe('keyed entry');
  });

  it('returns undefined when semantic cache is disabled', () => {
    process.env.OLLAMA_CHAT_CACHE_SEMANTIC_DISABLED = '1';
    expect(isOllamaSemanticCacheDisabled()).toBe(true);
    const ctx = 'ctx-off';
    setCachedOllamaChatResponse(`525-off-${Math.random().toString(36).slice(2)}`, {
      text: 'x',
      semanticContextKey: ctx,
      embedding: [1, 0, 0],
    });
    expect(
      findSemanticallySimilarCachedResponse({
        semanticContextKey: ctx,
        embedding: [1, 0, 0],
        threshold: 0.5,
      }),
    ).toBeUndefined();
  });

  it('respects OLLAMA_CHAT_CACHE_SEMANTIC_THRESHOLD default', () => {
    expect(ollamaSemanticCacheThreshold()).toBe(0.92);
  });
});
