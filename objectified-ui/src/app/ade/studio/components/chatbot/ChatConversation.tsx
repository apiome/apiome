'use client';

import * as React from 'react';
import { Download, History, Loader2, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react';

import { ChatBubble } from './ChatBubble';
import { ChatComposer } from './ChatComposer';
import { ChatContextChip } from './ChatContextChip';
import type { ChatStudioContext } from './chat-context';
import { isChatStudioContextEmpty } from './chat-context';
import { ConversationHistoryPanel } from './ConversationHistoryPanel';
import {
  buildStoredConversation,
  createConversationStore,
  createLocalStorageConversationStorage,
  exportConversationToMarkdown,
  type ConversationStore,
  type StoredConversation,
  type StoredConversationScope,
} from './conversation-store';
import { createDemoChatResponder } from './demo-responder';
import {
  persistOllamaModelChoiceForScope,
  persistOllamaModelTenantDefault,
  resolvePreferredOllamaModel,
} from './ollama-model-defaults';
import { createOllamaChatResponder } from './ollama-chat-responder';
import type { DetectedOpenApiSpec } from './openapi-detection';
import type { ChatFeedback, ChatMessage, ChatSendFn } from './types';

/**
 * Studio AI chat conversation surface (#258, #259, #260, #261).
 *
 * Owns the message transcript, scroll behaviour, and request lifecycle for
 * the chatbot panel. Stateless from the caller's perspective: pass an
 * `onSendMessage` adapter to swap the offline demo for a real backend.
 *
 * The shell guarantees the design rules from the issue:
 *   - User and assistant bubbles are visually distinct
 *   - Typing indicator is shown while the assistant is composing
 *   - Markdown / code / OpenAPI affordances are delegated to `ChatBubble`
 *   - When a `studioContext` snapshot is provided (#259), each send captures
 *     the snapshot at that moment and forwards it to the responder, and a
 *     small "Sharing context" chip lets the user inspect what is being sent
 *   - Conversations are auto-persisted per project / version (#261), with a
 *     toolbar for new / history / export / clear and a browse + search
 *     surface tucked behind the history button
 *   - With `ollamaTransport` (#265), lists generative models from Ollama and
 *     sends turns through `/api/ollama/chat`; falls back to the demo when the
 *     server has no models or the list request fails.
 *   - With `tenantId` + `studioContext.project` (#266), the chosen model is
 *     remembered per project (and optionally per tenant) in localStorage so
 *     each workspace reopens on its preferred tag when Ollama still exposes it.
 */
export interface ChatConversationProps {
  /** Adapter invoked to produce assistant replies. Defaults to the demo responder. */
  onSendMessage?: ChatSendFn;
  /** Called when the user clicks "Import OpenAPI spec" on a message. */
  onImportSpec?: (spec: DetectedOpenApiSpec) => void;
  /** Optional starter messages — useful for tests and previews. */
  initialMessages?: ChatMessage[];
  /** Optional empty-state body copy. */
  emptyStateMessage?: string;
  /**
   * Optional Studio workspace snapshot (#259). When supplied, the snapshot is
   * captured on every send and threaded through the responder so it can
   * ground its replies in the user's project, version, classes, properties,
   * and current canvas selection.
   */
  studioContext?: ChatStudioContext;
  /**
   * Optional persistence backend (#261). Defaults to a localStorage-backed
   * store. Tests inject a memory-backed store to assert persistence
   * behaviour without touching the DOM.
   */
  conversationStore?: ConversationStore;
  /**
   * Restore the most recent persisted conversation in the active scope on
   * mount. Defaults to `true`. Tests opt out for deterministic empty-state
   * runs.
   */
  restoreLastConversation?: boolean;
  /**
   * Confirmation hook for destructive actions (clear, clear-all). Defaults
   * to `window.confirm` when available. Returning `false` aborts the action.
   */
  confirmAction?: (message: string) => boolean;
  /**
   * Override how exported markdown is delivered. Defaults to triggering a
   * browser download. Tests inject a spy to assert the markdown content.
   */
  onExportConversation?: (input: { filename: string; markdown: string }) => void;
  /**
   * Load models from `/api/ollama/models` and use the selected tag with the
   * Ollama chat route. Ignored when `onSendMessage` is provided.
   */
  ollamaTransport?: boolean;
  /**
   * Current tenant id from the signed-in session (#266). With `studioContext.project`,
   * model choice is persisted per project; with tenant alone, per tenant.
   */
  tenantId?: string | null;
}

const PROMPT_SUGGESTIONS: readonly string[] = [
  'Sketch a User class with email, password hash, and roles',
  'Generate an OpenAPI spec for a small catalog API',
  'How would I model a multi-tenant audit log?',
];

export function ChatConversation({
  onSendMessage,
  onImportSpec,
  initialMessages,
  emptyStateMessage,
  studioContext,
  conversationStore,
  restoreLastConversation = true,
  confirmAction,
  onExportConversation,
  ollamaTransport = false,
  tenantId,
}: ChatConversationProps) {
  type OllamaModelRow = { name: string };
  type ModelsStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

  const [ollamaModels, setOllamaModels] = React.useState<OllamaModelRow[]>([]);
  const [selectedOllamaModel, setSelectedOllamaModel] = React.useState('');
  const [modelsStatus, setModelsStatus] = React.useState<ModelsStatus>(() =>
    ollamaTransport ? 'loading' : 'idle',
  );
  const [modelsRetryToken, bumpModelsRetry] = React.useReducer((n: number) => n + 1, 0);
  const ollamaModelScopeKeyRef = React.useRef<string | null>(null);

  const demoResponder = React.useMemo(() => createDemoChatResponder(), []);
  const ollamaResponder = React.useMemo(() => createOllamaChatResponder(), []);

  const handleSelectOllamaModel = React.useCallback(
    (name: string) => {
      setSelectedOllamaModel(name);
      persistOllamaModelChoiceForScope({
        tenantId: tenantId ?? null,
        projectId: studioContext?.project?.id ?? null,
        modelName: name,
        storage: typeof window !== 'undefined' ? window.localStorage : null,
      });
    },
    [tenantId, studioContext?.project?.id],
  );

  const handlePersistTenantOllamaDefault = React.useCallback(() => {
    persistOllamaModelTenantDefault({
      tenantId: tenantId ?? null,
      modelName: selectedOllamaModel,
      storage: typeof window !== 'undefined' ? window.localStorage : null,
    });
  }, [tenantId, selectedOllamaModel]);

  React.useEffect(() => {
    if (!ollamaTransport) {
      ollamaModelScopeKeyRef.current = null;
      setModelsStatus('idle');
      setOllamaModels([]);
      setSelectedOllamaModel('');
      return;
    }

    let cancelled = false;
    setModelsStatus('loading');
    const ls = typeof window !== 'undefined' ? window.localStorage : null;
    const scopeKeyNow = `${tenantId ?? ''}::${studioContext?.project?.id ?? ''}`;

    function applyErrorState() {
      setOllamaModels([]);
      setSelectedOllamaModel('');
      setModelsStatus('error');
    }

    async function loadModels() {
      try {
        const res = await fetch('/api/ollama/models');
        if (!res.ok) {
          if (!cancelled) applyErrorState();
          return;
        }
        const data = (await res.json()) as {
          success?: boolean;
          models?: OllamaModelRow[];
        };
        if (cancelled) return;
        if (data.success === false) {
          applyErrorState();
        } else if (data.success && Array.isArray(data.models) && data.models.length > 0) {
          setOllamaModels(data.models);
          setSelectedOllamaModel((prev) => {
            const names = data.models!.map((m) => m.name);
            const prevScope = ollamaModelScopeKeyRef.current;
            ollamaModelScopeKeyRef.current = scopeKeyNow;
            const scopeUnchanged = prevScope === scopeKeyNow;
            if (scopeUnchanged && prev && names.includes(prev)) return prev;
            return resolvePreferredOllamaModel({
              tenantId: tenantId ?? null,
              projectId: studioContext?.project?.id ?? null,
              availableModelNames: names,
              storage: ls,
            });
          });
          setModelsStatus('ready');
        } else {
          setOllamaModels([]);
          setSelectedOllamaModel('');
          setModelsStatus('empty');
        }
      } catch {
        if (!cancelled) applyErrorState();
      }
    }

    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [
    ollamaTransport,
    modelsRetryToken,
    tenantId,
    studioContext?.project?.id,
  ]);

  const useLiveOllama =
    ollamaTransport && modelsStatus === 'ready' && ollamaModels.length > 0 && selectedOllamaModel.length > 0;

  const responder = React.useMemo(() => {
    if (onSendMessage) return onSendMessage;
    if (useLiveOllama) return ollamaResponder;
    return demoResponder;
  }, [onSendMessage, useLiveOllama, ollamaResponder, demoResponder]);
  const store = React.useMemo<ConversationStore>(
    () => conversationStore ?? createConversationStore(createLocalStorageConversationStorage()),
    [conversationStore],
  );
  const scope = React.useMemo<StoredConversationScope>(
    () => ({
      projectId: studioContext?.project?.id ?? null,
      versionId: studioContext?.version?.id ?? null,
    }),
    [studioContext?.project?.id, studioContext?.version?.id],
  );

  const [messages, setMessages] = React.useState<ChatMessage[]>(() => initialMessages ?? []);
  const [isBusy, setIsBusy] = React.useState(false);
  const [view, setView] = React.useState<'chat' | 'history'>('chat');
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [activeCreatedAt, setActiveCreatedAt] = React.useState<number | null>(null);
  const [historyVersion, bumpHistoryVersion] = React.useReducer((n: number) => n + 1, 0);

  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const requestIdRef = React.useRef(0);
  const studioContextRef = React.useRef<ChatStudioContext | undefined>(studioContext);
  const lastRestoreScopeRef = React.useRef<string | null>(null);
  // Set to true only by user-originated transcript changes (send / regenerate).
  // Cleared by the persist effect after saving, and reset to false whenever
  // messages are loaded from the store (restore / open-from-history) so we
  // never re-persist a conversation that already matches what is stored.
  const pendingPersistRef = React.useRef(false);
  React.useEffect(() => {
    studioContextRef.current = studioContext;
  }, [studioContext]);

  const hasStudioContext = !!studioContext && !isChatStudioContextEmpty(studioContext);

  // Restore the most recent conversation when the scope changes.
  React.useEffect(() => {
    if (!restoreLastConversation) return;
    if (initialMessages && initialMessages.length > 0) return;
    const key = scopeKey(scope);
    if (lastRestoreScopeRef.current === key) return;
    lastRestoreScopeRef.current = key;
    // Any pending persist from the previous scope is no longer valid — the
    // messages it refers to belong to the old scope and must not be saved
    // under the new one.
    pendingPersistRef.current = false;
    const latest = store.list(scope)[0];
    if (latest) {
      setMessages(latest.messages);
      setActiveId(latest.id);
      setActiveCreatedAt(latest.createdAt);
    } else {
      setMessages([]);
      setActiveId(null);
      setActiveCreatedAt(null);
    }
  }, [restoreLastConversation, initialMessages, scope, store]);

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  // Auto-persist whenever the transcript settles (no pending turns).
  // Guard: only run when the change was user-originated (send / regenerate),
  // not when messages were loaded from the store (restore / open-from-history).
  // This prevents unnecessary `updatedAt` rewrites that would reorder history
  // and avoids writing the old transcript under a newly-switched scope.
  React.useEffect(() => {
    if (!pendingPersistRef.current) return;
    if (messages.length === 0) return;
    if (messages.some((m) => m.pending)) return;
    if (!messages.some((m) => m.role === 'user')) return;
    pendingPersistRef.current = false;
    const conversation = buildStoredConversation({
      id: activeId ?? undefined,
      scope,
      messages,
      createdAt: activeCreatedAt ?? undefined,
    });
    store.save(conversation);
    if (!activeId) {
      setActiveId(conversation.id);
      setActiveCreatedAt(conversation.createdAt);
    }
    bumpHistoryVersion();
  }, [messages, scope, store, activeId, activeCreatedAt]);

  const lastAssistantId = React.useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const m = messages[i];
      if (m.role === 'assistant' && !m.pending) return m.id;
    }
    return null;
  }, [messages]);

  const runAssistantTurn = React.useCallback(
    async (transcript: ChatMessage[], prompt: string, isRegenerate: boolean) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      const pendingId = createId();
      const pendingMessage: ChatMessage = {
        id: pendingId,
        role: 'assistant',
        content: '',
        pending: true,
      };
      setIsBusy(true);
      setMessages([...transcript, pendingMessage]);

      let reply: string;
      try {
        reply = await responder({
          messages: transcript,
          prompt,
          isRegenerate,
          studioContext: studioContextRef.current,
          ollamaModel: useLiveOllama ? selectedOllamaModel : undefined,
        });
      } catch (error) {
        console.error('Chat assistant failed to respond', error);
        reply = 'Sorry — the assistant could not respond. Please try again.';
      }

      if (requestIdRef.current !== requestId) return;

      setMessages((current) =>
        current.map((message) =>
          message.id === pendingId ? { ...message, content: reply, pending: false } : message
        )
      );
      setIsBusy(false);
    },
    [responder, useLiveOllama, selectedOllamaModel]
  );

  const handleSend = React.useCallback(
    (text: string) => {
      const userMessage: ChatMessage = { id: createId(), role: 'user', content: text };
      const nextTranscript = [...messages, userMessage];
      pendingPersistRef.current = true;
      setMessages(nextTranscript);
      void runAssistantTurn(nextTranscript, text, false);
    },
    [messages, runAssistantTurn]
  );

  const handleRegenerate = React.useCallback(() => {
    if (isBusy) return;
    let lastUserIndex = -1;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'user') {
        lastUserIndex = i;
        break;
      }
    }
    if (lastUserIndex === -1) return;
    const trimmedTranscript = messages.slice(0, lastUserIndex + 1);
    const prompt = messages[lastUserIndex].content;
    pendingPersistRef.current = true;
    setMessages(trimmedTranscript);
    void runAssistantTurn(trimmedTranscript, prompt, true);
  }, [isBusy, messages, runAssistantTurn]);

  const handleFeedback = React.useCallback(
    (messageId: string, feedback: ChatFeedback) => {
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, feedback: message.feedback === feedback ? undefined : feedback }
            : message
        )
      );
    },
    []
  );

  const askConfirm = React.useCallback(
    (message: string) => {
      const fn = confirmAction ?? defaultConfirm;
      try {
        return fn(message);
      } catch {
        return true;
      }
    },
    [confirmAction],
  );

  const resetActive = React.useCallback(() => {
    setMessages([]);
    setActiveId(null);
    setActiveCreatedAt(null);
  }, []);

  const handleNewConversation = React.useCallback(() => {
    requestIdRef.current += 1;
    setIsBusy(false);
    pendingPersistRef.current = false;
    resetActive();
    setView('chat');
  }, [resetActive]);

  const handleClearCurrent = React.useCallback(() => {
    if (messages.length === 0) return;
    if (!askConfirm('Clear the current conversation? It will be removed from your history.')) return;
    requestIdRef.current += 1;
    setIsBusy(false);
    pendingPersistRef.current = false;
    if (activeId) store.remove(activeId);
    resetActive();
    bumpHistoryVersion();
    setView('chat');
  }, [messages.length, askConfirm, activeId, store, resetActive]);

  const handleExportCurrent = React.useCallback(() => {
    if (messages.length === 0) return;
    const conversation = buildStoredConversation({
      id: activeId ?? undefined,
      scope,
      messages,
      createdAt: activeCreatedAt ?? undefined,
    });
    const markdown = exportConversationToMarkdown(conversation);
    const filename = buildExportFilename(conversation);
    if (onExportConversation) {
      onExportConversation({ filename, markdown });
      return;
    }
    triggerMarkdownDownload(filename, markdown);
  }, [messages, activeId, scope, activeCreatedAt, onExportConversation]);

  const handleOpenHistory = React.useCallback(() => {
    setView('history');
  }, []);
  const handleCloseHistory = React.useCallback(() => {
    setView('chat');
  }, []);

  const handleOpenStored = React.useCallback(
    (id: string) => {
      const conversation = store.get(id);
      if (!conversation) return;
      // Loading from store — do not trigger an auto-persist for this change.
      pendingPersistRef.current = false;
      setMessages(conversation.messages);
      setActiveId(conversation.id);
      setActiveCreatedAt(conversation.createdAt);
      setView('chat');
    },
    [store],
  );

  const handleDeleteStored = React.useCallback(
    (id: string) => {
      if (!askConfirm('Delete this conversation? This cannot be undone.')) return;
      store.remove(id);
      if (activeId === id) {
        resetActive();
      }
      bumpHistoryVersion();
    },
    [store, activeId, resetActive, askConfirm],
  );

  const handleClearAllStored = React.useCallback(() => {
    if (!askConfirm('Clear every saved conversation in this scope? This cannot be undone.')) return;
    store.clear(scope);
    resetActive();
    bumpHistoryVersion();
  }, [askConfirm, store, scope, resetActive]);

  const storedConversations = React.useMemo(
    () => store.list(scope),
    // historyVersion lets us re-derive after save / remove / clear without
    // relying on the store being a referentially-stable object across runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [store, scope, historyVersion],
  );

  const showEmptyState = messages.length === 0;
  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="studio-ai-chat-conversation">
      {ollamaTransport && view === 'chat' && (
        <OllamaModelBar
          status={ollamaTransport && modelsStatus === 'idle' ? 'loading' : modelsStatus}
          models={ollamaModels}
          selectedModel={selectedOllamaModel}
          onSelectModel={handleSelectOllamaModel}
          onRetry={bumpModelsRetry}
          showTenantDefaultButton={Boolean(tenantId && studioContext?.project?.id)}
          onPersistTenantDefault={handlePersistTenantOllamaDefault}
        />
      )}
      <ChatToolbar
        onNew={handleNewConversation}
        onHistory={handleOpenHistory}
        onExport={handleExportCurrent}
        onClear={handleClearCurrent}
        canExport={hasMessages}
        canClear={hasMessages}
        historyCount={storedConversations.length}
      />

      {view === 'history' ? (
        <ConversationHistoryPanel
          conversations={storedConversations}
          activeId={activeId}
          onOpen={handleOpenStored}
          onDelete={handleDeleteStored}
          onClearAll={handleClearAllStored}
          onClose={handleCloseHistory}
        />
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-3" data-testid="studio-ai-chat-messages">
            {showEmptyState ? (
              <EmptyState
                message={emptyStateMessage}
                suggestions={PROMPT_SUGGESTIONS}
                onSelect={handleSend}
              />
            ) : (
              <div className="space-y-4">
                {messages.map((message) => (
                  <ChatBubble
                    key={message.id}
                    message={message}
                    isLatestAssistant={message.id === lastAssistantId}
                    onRegenerate={message.id === lastAssistantId ? handleRegenerate : undefined}
                    onFeedback={(feedback) => handleFeedback(message.id, feedback)}
                    onImportSpec={onImportSpec}
                  />
                ))}
                <div ref={messagesEndRef} aria-hidden />
              </div>
            )}
          </div>

          {hasStudioContext && (
            <div className="border-t border-gray-200 bg-white px-3 py-2 dark:border-gray-700 dark:bg-gray-900">
              <ChatContextChip studioContext={studioContext!} />
            </div>
          )}

          <ChatComposer onSend={handleSend} isBusy={isBusy} />
        </>
      )}
    </div>
  );
}

type OllamaModelBarStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

interface OllamaModelBarProps {
  status: OllamaModelBarStatus;
  models: Array<{ name: string }>;
  selectedModel: string;
  onSelectModel: (name: string) => void;
  onRetry: () => void;
  showTenantDefaultButton?: boolean;
  onPersistTenantDefault?: () => void;
}

function OllamaModelBar({
  status,
  models,
  selectedModel,
  onSelectModel,
  onRetry,
  showTenantDefaultButton,
  onPersistTenantDefault,
}: OllamaModelBarProps) {
  if (status === 'idle') return null;

  return (
    <div
      className="flex flex-wrap items-center gap-2 border-b border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-900/60"
      data-testid="studio-ai-chat-ollama-model-bar"
    >
      {status === 'loading' && (
        <span className="inline-flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
          Loading models from Ollama…
        </span>
      )}
      {status === 'error' && (
        <>
          <span className="text-xs text-red-600 dark:text-red-400">
            Could not reach Ollama. Using the offline assistant.
          </span>
          <button
            type="button"
            onClick={onRetry}
            data-testid="studio-ai-chat-ollama-retry-models"
            className="inline-flex h-7 items-center gap-1 rounded-md border border-gray-300 bg-white px-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Retry
          </button>
        </>
      )}
      {status === 'empty' && (
        <span className="text-xs text-gray-600 dark:text-gray-400">
          No generative models in Ollama. Pull one (for example Qwen 2.5 or Llama 3.2) or continue with the
          offline assistant.
        </span>
      )}
      {status === 'ready' && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-wrap items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
            <span className="font-medium text-gray-600 dark:text-gray-400">Model</span>
            <select
              data-testid="studio-ai-chat-ollama-model-select"
              className="max-w-[min(100%,18rem)] rounded-md border border-gray-300 bg-white px-2 py-1 font-mono text-xs text-gray-900 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              value={selectedModel}
              onChange={(e) => onSelectModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          {showTenantDefaultButton && onPersistTenantDefault && (
            <button
              type="button"
              data-testid="studio-ai-chat-ollama-tenant-default"
              title="Remember this model as the default for every project in this tenant (project-specific defaults still win when set)."
              onClick={onPersistTenantDefault}
              className="inline-flex h-7 items-center rounded-md border border-gray-300 bg-white px-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              Tenant default
            </button>
          )}
        </div>
      )}
    </div>
  );
}

interface ChatToolbarProps {
  onNew: () => void;
  onHistory: () => void;
  onExport: () => void;
  onClear: () => void;
  canExport: boolean;
  canClear: boolean;
  historyCount: number;
}

function ChatToolbar({
  onNew,
  onHistory,
  onExport,
  onClear,
  canExport,
  canClear,
  historyCount,
}: ChatToolbarProps) {
  return (
    <div
      className="flex items-center justify-between gap-1 border-b border-gray-200 bg-gray-50 px-2 py-1 dark:border-gray-700 dark:bg-gray-900/60"
      data-testid="studio-ai-chat-toolbar"
    >
      <div className="flex items-center gap-1">
        <ToolbarButton
          onClick={onNew}
          icon={<Plus className="h-3.5 w-3.5" />}
          label="Start a new conversation"
          testId="studio-ai-chat-new"
        >
          New
        </ToolbarButton>
        <ToolbarButton
          onClick={onHistory}
          icon={<History className="h-3.5 w-3.5" />}
          label={`Browse past conversations (${historyCount})`}
          testId="studio-ai-chat-history"
        >
          History {historyCount > 0 ? `(${historyCount})` : ''}
        </ToolbarButton>
      </div>
      <div className="flex items-center gap-1">
        <ToolbarButton
          onClick={onExport}
          icon={<Download className="h-3.5 w-3.5" />}
          label="Export current conversation as markdown"
          testId="studio-ai-chat-export"
          disabled={!canExport}
        >
          Export
        </ToolbarButton>
        <ToolbarButton
          onClick={onClear}
          icon={<Trash2 className="h-3.5 w-3.5" />}
          label="Clear current conversation"
          testId="studio-ai-chat-clear"
          disabled={!canClear}
          tone="danger"
        >
          Clear
        </ToolbarButton>
      </div>
    </div>
  );
}

interface ToolbarButtonProps {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  testId: string;
  disabled?: boolean;
  tone?: 'default' | 'danger';
  children: React.ReactNode;
}

function ToolbarButton({
  onClick,
  icon,
  label,
  testId,
  disabled,
  tone = 'default',
  children,
}: ToolbarButtonProps) {
  const toneClasses =
    tone === 'danger'
      ? 'text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-300 dark:hover:bg-red-950/40'
      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100';
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      data-testid={testId}
      className={`inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-50 ${toneClasses}`}
    >
      {icon}
      <span>{children}</span>
    </button>
  );
}

interface EmptyStateProps {
  message?: string;
  suggestions: readonly string[];
  onSelect: (prompt: string) => void;
}

function EmptyState({ message, suggestions, onSelect }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <span className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-purple-100 to-indigo-100 text-purple-600 dark:from-purple-900/40 dark:to-indigo-900/40 dark:text-purple-300">
        <Sparkles className="h-6 w-6" />
      </span>
      <h2 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">
        How can the Studio assistant help?
      </h2>
      <p className="mb-4 max-w-sm text-sm text-gray-600 dark:text-gray-400">
        {message ??
          'Describe what you want to model and the assistant will draft schemas you can import in one click. The conversation is private to you.'}
      </p>
      <ul className="grid w-full max-w-sm gap-2 text-left">
        {suggestions.map((suggestion) => (
          <li key={suggestion}>
            <button
              type="button"
              onClick={() => onSelect(suggestion)}
              data-testid="studio-ai-chat-suggestion"
              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 transition-colors hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-200 dark:hover:border-indigo-500 dark:hover:bg-indigo-900/30 dark:hover:text-indigo-200"
            >
              {suggestion}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

let counter = 0;
function createId(): string {
  counter += 1;
  return `chat-${Date.now().toString(36)}-${counter.toString(36)}`;
}

function scopeKey(scope: StoredConversationScope): string {
  return `${scope.projectId ?? '∅'}::${scope.versionId ?? '∅'}`;
}

function defaultConfirm(message: string): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.confirm(message);
  } catch {
    return true;
  }
}

function buildExportFilename(conversation: StoredConversation): string {
  const slug = conversation.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  const stamp = new Date(conversation.updatedAt).toISOString().slice(0, 10);
  const base = slug.length > 0 ? slug : 'conversation';
  return `studio-ai-${base}-${stamp}.md`;
}

function triggerMarkdownDownload(filename: string, markdown: string): void {
  if (typeof document === 'undefined' || typeof window === 'undefined') return;
  try {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.style.display = 'none';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    console.error('Failed to trigger conversation export download', error);
  }
}
