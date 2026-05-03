/**
 * Conversation persistence for the Studio AI chatbot (#261).
 *
 * The chat surface keeps a working transcript in component state, but users
 * also expect their conversations to survive a panel close, a tab reload, or
 * a switch to another canvas. This module owns the small, UI-agnostic data
 * model that the chatbot persists to (today) `localStorage` and the helpers
 * the UI uses to:
 *
 *   - List, search, and export past conversations
 *   - Save / replace the active conversation as new turns arrive
 *   - Scope conversations to the current project / version so unrelated
 *     workspaces stay separate
 *   - Clear a single conversation or every conversation in a scope
 *
 * The storage backend is pluggable: the production UI uses
 * {@link createLocalStorageConversationStorage}, while tests use
 * {@link createMemoryConversationStorage} for deterministic, DOM-free runs.
 *
 * The Ollama transport (live in #265) and any future server-side history can replace
 * the storage adapter without touching the chat shell.
 */

import type { ChatMessage } from './types';

/** Local-storage key used by the default browser adapter. */
export const CHAT_HISTORY_STORAGE_KEY = 'objectified.studio.chatbot.conversations.v1';
/** Per-conversation title cap — keeps the history list scannable. */
export const CHAT_HISTORY_TITLE_CHAR_CAP = 80;
/** Hard cap on persisted conversations per scope; oldest are pruned first. */
export const CHAT_HISTORY_MAX_CONVERSATIONS = 50;

export interface StoredConversationScope {
  /** Project the conversation belongs to. `null` means "no project context". */
  projectId: string | null;
  /** Version inside the project. `null` means "no version selected". */
  versionId: string | null;
}

export interface StoredConversation extends StoredConversationScope {
  id: string;
  title: string;
  /** Epoch ms — when the conversation was first created. */
  createdAt: number;
  /** Epoch ms — when the conversation was last edited. */
  updatedAt: number;
  messages: ChatMessage[];
}

export interface ConversationStorage {
  /** Returns every persisted conversation. Errors must be swallowed. */
  read(): StoredConversation[];
  /** Persists the full list, replacing any prior contents. */
  write(conversations: StoredConversation[]): void;
}

export interface ConversationStore {
  /** Newest-first list of conversations matching `scope`, or all when omitted. */
  list(scope?: Partial<StoredConversationScope>): StoredConversation[];
  get(id: string): StoredConversation | null;
  /** Inserts or replaces by id. Returns the saved conversation. */
  save(conversation: StoredConversation): StoredConversation;
  remove(id: string): void;
  /** Removes every conversation in `scope`, or every conversation when omitted. */
  clear(scope?: Partial<StoredConversationScope>): void;
  /**
   * Case-insensitive substring search across title + message content within
   * the optional `scope`. Empty queries return the full scoped list.
   */
  search(query: string, scope?: Partial<StoredConversationScope>): StoredConversation[];
}

/**
 * Create a store backed by an arbitrary {@link ConversationStorage}. The
 * store handles ordering, capping, and scope filtering so adapters stay
 * trivial.
 */
export function createConversationStore(storage: ConversationStorage): ConversationStore {
  function readSorted(): StoredConversation[] {
    const all = storage.read();
    return [...all].sort((a, b) => b.updatedAt - a.updatedAt);
  }

  return {
    list(scope) {
      const all = readSorted();
      return scope ? all.filter((c) => matchesScope(c, scope)) : all;
    },
    get(id) {
      return storage.read().find((c) => c.id === id) ?? null;
    },
    save(conversation) {
      const current = storage.read();
      const next = current.filter((c) => c.id !== conversation.id);
      next.push(conversation);
      next.sort((a, b) => b.updatedAt - a.updatedAt);
      storage.write(pruneToCap(next));
      return conversation;
    },
    remove(id) {
      const current = storage.read();
      const next = current.filter((c) => c.id !== id);
      if (next.length !== current.length) storage.write(next);
    },
    clear(scope) {
      const current = storage.read();
      const next = scope ? current.filter((c) => !matchesScope(c, scope)) : [];
      storage.write(next);
    },
    search(query, scope) {
      const all = readSorted();
      const scoped = scope ? all.filter((c) => matchesScope(c, scope)) : all;
      const q = query.trim().toLowerCase();
      if (q.length === 0) return scoped;
      return scoped.filter((c) => conversationMatchesQuery(c, q));
    },
  };
}

function matchesScope(
  conversation: StoredConversation,
  scope: Partial<StoredConversationScope>,
): boolean {
  if (Object.prototype.hasOwnProperty.call(scope, 'projectId')) {
    if ((scope.projectId ?? null) !== conversation.projectId) return false;
  }
  if (Object.prototype.hasOwnProperty.call(scope, 'versionId')) {
    if ((scope.versionId ?? null) !== conversation.versionId) return false;
  }
  return true;
}

function conversationMatchesQuery(
  conversation: StoredConversation,
  loweredQuery: string,
): boolean {
  if (conversation.title.toLowerCase().includes(loweredQuery)) return true;
  return conversation.messages.some((m) =>
    m.content.toLowerCase().includes(loweredQuery),
  );
}

function pruneToCap(conversations: StoredConversation[]): StoredConversation[] {
  if (conversations.length <= CHAT_HISTORY_MAX_CONVERSATIONS) return conversations;
  const byScope = new Map<string, StoredConversation[]>();
  for (const conv of conversations) {
    const key = scopeKey(conv);
    const bucket = byScope.get(key);
    if (bucket) bucket.push(conv);
    else byScope.set(key, [conv]);
  }
  const kept: StoredConversation[] = [];
  for (const bucket of byScope.values()) {
    bucket.sort((a, b) => b.updatedAt - a.updatedAt);
    kept.push(...bucket.slice(0, CHAT_HISTORY_MAX_CONVERSATIONS));
  }
  kept.sort((a, b) => b.updatedAt - a.updatedAt);
  return kept;
}

function scopeKey(conversation: StoredConversationScope): string {
  return `${conversation.projectId ?? '∅'}::${conversation.versionId ?? '∅'}`;
}

/**
 * In-memory adapter — used by tests and any caller that doesn't want to
 * touch the browser. Mutating `initial` does not affect the adapter; the
 * adapter takes a defensive copy.
 */
export function createMemoryConversationStorage(
  initial: StoredConversation[] = [],
): ConversationStorage {
  let state = cloneList(initial);
  return {
    read: () => cloneList(state),
    write: (next) => {
      state = cloneList(next);
    },
  };
}

/**
 * Browser adapter — wraps `localStorage` with parse / stringify, defends
 * against quota errors, and degrades to a no-op when storage is unavailable
 * (e.g. SSR, private mode).
 */
export function createLocalStorageConversationStorage(
  storageKey: string = CHAT_HISTORY_STORAGE_KEY,
  storageFactory: () => Storage | null = defaultStorageFactory,
): ConversationStorage {
  return {
    read() {
      const storage = safeStorage(storageFactory);
      if (!storage) return [];
      try {
        const raw = storage.getItem(storageKey);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.filter(isStoredConversation);
      } catch {
        return [];
      }
    },
    write(conversations) {
      const storage = safeStorage(storageFactory);
      if (!storage) return;
      try {
        storage.setItem(storageKey, JSON.stringify(conversations));
      } catch {
        // Quota or serialization errors are intentionally swallowed —
        // history persistence is a best-effort enhancement.
      }
    },
  };
}

function defaultStorageFactory(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function safeStorage(factory: () => Storage | null): Storage | null {
  try {
    return factory();
  } catch {
    return null;
  }
}

function isStoredConversation(value: unknown): value is StoredConversation {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === 'string' &&
    typeof v.title === 'string' &&
    typeof v.createdAt === 'number' &&
    typeof v.updatedAt === 'number' &&
    Array.isArray(v.messages) &&
    v.messages.every(isChatMessage) &&
    (v.projectId === null || typeof v.projectId === 'string') &&
    (v.versionId === null || typeof v.versionId === 'string')
  );
}

function isChatMessage(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const m = value as Record<string, unknown>;
  return (
    typeof m.id === 'string' &&
    (m.role === 'user' || m.role === 'assistant' || m.role === 'system') &&
    typeof m.content === 'string'
  );
}

function cloneList(conversations: StoredConversation[]): StoredConversation[] {
  return conversations.map((c) => ({ ...c, messages: c.messages.map((m) => ({ ...m })) }));
}

/**
 * Pull a short, human-friendly title out of a transcript. Prefers the first
 * user prompt; falls back to the first assistant reply; returns
 * `'Untitled conversation'` when the transcript is empty.
 */
export function deriveConversationTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((m) => m.role === 'user' && m.content.trim().length > 0);
  const seed = firstUser ?? messages.find((m) => m.content.trim().length > 0);
  if (!seed) return 'Untitled conversation';
  const compact = seed.content.replace(/\s+/g, ' ').trim();
  if (compact.length <= CHAT_HISTORY_TITLE_CHAR_CAP) return compact;
  return `${compact.slice(0, CHAT_HISTORY_TITLE_CHAR_CAP - 1).trimEnd()}…`;
}

/** Render a single conversation as standalone markdown. */
export function exportConversationToMarkdown(conversation: StoredConversation): string {
  const lines: string[] = [`# ${conversation.title}`];
  const meta: string[] = [];
  meta.push(`Created: ${new Date(conversation.createdAt).toISOString()}`);
  meta.push(`Updated: ${new Date(conversation.updatedAt).toISOString()}`);
  if (conversation.projectId) meta.push(`Project: ${conversation.projectId}`);
  if (conversation.versionId) meta.push(`Version: ${conversation.versionId}`);
  lines.push('', meta.map((m) => `- ${m}`).join('\n'));

  for (const message of conversation.messages) {
    if (message.pending) continue;
    const heading = message.role === 'user' ? '## User' : '## Assistant';
    lines.push('', heading, '', message.content.trim().length > 0 ? message.content : '_(empty)_');
  }

  return `${lines.join('\n').trim()}\n`;
}

/**
 * Render multiple conversations as a single markdown document with `---`
 * dividers. Useful for "export all" affordances on the history panel.
 */
export function exportConversationsToMarkdown(conversations: StoredConversation[]): string {
  if (conversations.length === 0) return '';
  return conversations
    .map((conversation) => exportConversationToMarkdown(conversation).trimEnd())
    .join('\n\n---\n\n')
    .concat('\n');
}

/**
 * Convenience: build a {@link StoredConversation} from the running chat
 * state. Generates a stable id when one isn't provided so callers can keep
 * upserting through the chat lifecycle.
 */
export function buildStoredConversation(input: {
  id?: string;
  scope: StoredConversationScope;
  messages: ChatMessage[];
  createdAt?: number;
  updatedAt?: number;
  now?: () => number;
}): StoredConversation {
  const now = input.now ?? Date.now;
  const created = input.createdAt ?? now();
  return {
    id: input.id ?? generateConversationId(now),
    projectId: input.scope.projectId,
    versionId: input.scope.versionId,
    title: deriveConversationTitle(input.messages),
    createdAt: created,
    updatedAt: input.updatedAt ?? now(),
    messages: input.messages.map((m) => ({ ...m })),
  };
}

let conversationCounter = 0;
function generateConversationId(now: () => number): string {
  conversationCounter += 1;
  return `chat-conv-${now().toString(36)}-${conversationCounter.toString(36)}`;
}
