'use client';

import * as React from 'react';
import { ArrowLeft, MessageSquare, Search, Trash2 } from 'lucide-react';

import type { StoredConversation } from './conversation-store';

/**
 * Browse / search past conversations (#261).
 *
 * Mounted inside the chatbot panel when the user opens "history". The
 * surface is intentionally read-only-ish: opening a conversation hands the
 * id back to the chat shell which swaps it into the active transcript, and
 * the destructive actions (delete one, clear all) are confirmed by the
 * shell before they fire.
 */
export interface ConversationHistoryPanelProps {
  conversations: StoredConversation[];
  /** Marks the currently-open conversation in the list, if any. */
  activeId?: string | null;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
  onClose: () => void;
}

export function ConversationHistoryPanel({
  conversations,
  activeId,
  onOpen,
  onDelete,
  onClearAll,
  onClose,
}: ConversationHistoryPanelProps) {
  const [query, setQuery] = React.useState('');
  const trimmed = query.trim().toLowerCase();
  const filtered = React.useMemo(() => {
    if (trimmed.length === 0) return conversations;
    return conversations.filter((conv) => matchesQuery(conv, trimmed));
  }, [conversations, trimmed]);

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-testid="studio-ai-chat-history-panel"
    >
      <div className="flex items-center justify-between gap-2 border-b border-gray-200 px-3 py-2 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            aria-label="Back to conversation"
            data-testid="studio-ai-chat-history-back"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Past conversations
          </p>
        </div>
        <button
          type="button"
          onClick={onClearAll}
          disabled={conversations.length === 0}
          data-testid="studio-ai-chat-history-clear-all"
          className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-700/60 dark:bg-gray-900 dark:text-red-300 dark:hover:bg-red-950/40"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Clear all
        </button>
      </div>

      <div className="border-b border-gray-200 px-3 py-2 dark:border-gray-700">
        <label className="relative block">
          <span className="sr-only">Search conversations</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search conversations…"
            data-testid="studio-ai-chat-history-search"
            className="w-full rounded-md border border-gray-300 bg-white py-1.5 pl-8 pr-2 text-sm text-gray-900 placeholder:text-gray-400 focus-visible:border-indigo-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500"
          />
        </label>
      </div>

      <div
        className="flex-1 overflow-y-auto"
        data-testid="studio-ai-chat-history-list"
      >
        {conversations.length === 0 ? (
          <EmptyHistoryState />
        ) : filtered.length === 0 ? (
          <NoMatchesState query={query} />
        ) : (
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {filtered.map((conversation) => (
              <HistoryRow
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === activeId}
                onOpen={() => onOpen(conversation.id)}
                onDelete={() => onDelete(conversation.id)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface HistoryRowProps {
  conversation: StoredConversation;
  isActive: boolean;
  onOpen: () => void;
  onDelete: () => void;
}

function HistoryRow({ conversation, isActive, onOpen, onDelete }: HistoryRowProps) {
  const messageCount = conversation.messages.filter((m) => !m.pending).length;
  const updated = formatRelativeTime(conversation.updatedAt);

  return (
    <li
      data-testid="studio-ai-chat-history-row"
      data-conversation-id={conversation.id}
      data-active={isActive ? 'true' : 'false'}
      className={`group flex items-start gap-2 px-3 py-2 transition-colors ${
        isActive
          ? 'bg-indigo-50 dark:bg-indigo-900/30'
          : 'hover:bg-gray-50 dark:hover:bg-gray-800/60'
      }`}
    >
      <button
        type="button"
        onClick={onOpen}
        data-testid="studio-ai-chat-history-open"
        className="flex flex-1 items-start gap-2 text-left focus-visible:outline-none"
      >
        <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-gray-400 group-hover:text-indigo-500 dark:text-gray-500" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {conversation.title}
          </span>
          <span className="truncate text-xs text-gray-500 dark:text-gray-400">
            {messageCount} {messageCount === 1 ? 'message' : 'messages'} · {updated}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete conversation: ${conversation.title}`}
        data-testid="studio-ai-chat-history-delete"
        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 group-hover:opacity-100 dark:hover:bg-red-950/40 dark:hover:text-red-300"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

function EmptyHistoryState() {
  return (
    <div
      className="flex h-full flex-col items-center justify-center px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
      data-testid="studio-ai-chat-history-empty"
    >
      <MessageSquare className="mb-2 h-6 w-6 text-gray-300 dark:text-gray-600" />
      <p className="font-medium text-gray-700 dark:text-gray-300">No conversations yet</p>
      <p className="mt-1 max-w-xs text-xs">
        Start a new chat and your conversations will be saved here so you can revisit them
        later.
      </p>
    </div>
  );
}

function NoMatchesState({ query }: { query: string }) {
  return (
    <div
      className="flex h-full flex-col items-center justify-center px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
      data-testid="studio-ai-chat-history-no-matches"
    >
      <Search className="mb-2 h-6 w-6 text-gray-300 dark:text-gray-600" />
      <p className="font-medium text-gray-700 dark:text-gray-300">No matches</p>
      <p className="mt-1 max-w-xs text-xs">
        Nothing in your history matches &ldquo;{query}&rdquo;. Try a different search term.
      </p>
    </div>
  );
}

function matchesQuery(conversation: StoredConversation, lowered: string): boolean {
  if (conversation.title.toLowerCase().includes(lowered)) return true;
  return conversation.messages.some((m) =>
    m.content.toLowerCase().includes(lowered),
  );
}

function formatRelativeTime(timestamp: number, now: number = Date.now()): string {
  const diff = Math.max(0, now - timestamp);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString();
}
