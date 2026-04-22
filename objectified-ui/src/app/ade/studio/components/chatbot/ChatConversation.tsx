'use client';

import * as React from 'react';
import { Sparkles } from 'lucide-react';

import { ChatBubble } from './ChatBubble';
import { ChatComposer } from './ChatComposer';
import { createDemoChatResponder } from './demo-responder';
import type { DetectedOpenApiSpec } from './openapi-detection';
import type { ChatFeedback, ChatMessage, ChatSendFn } from './types';

/**
 * Studio AI chat conversation surface (#258).
 *
 * Owns the message transcript, scroll behaviour, and request lifecycle for
 * the chatbot panel. Stateless from the caller's perspective: pass an
 * `onSendMessage` adapter to swap the offline demo for a real backend.
 *
 * The shell guarantees the design rules from the issue:
 *   - User and assistant bubbles are visually distinct
 *   - Typing indicator is shown while the assistant is composing
 *   - Markdown / code / OpenAPI affordances are delegated to `ChatBubble`
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
}: ChatConversationProps) {
  const responder = React.useMemo(() => onSendMessage ?? createDemoChatResponder(), [onSendMessage]);
  const [messages, setMessages] = React.useState<ChatMessage[]>(() => initialMessages ?? []);
  const [isBusy, setIsBusy] = React.useState(false);
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const requestIdRef = React.useRef(0);

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

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
        reply = await responder({ messages: transcript, prompt, isRegenerate });
      } catch (error) {
        console.error('Chat assistant failed to respond', error);
        reply = 'Sorry — the assistant could not respond. Please try again.';
      }

      // Drop the response if a newer turn started while we were waiting.
      if (requestIdRef.current !== requestId) return;

      setMessages((current) =>
        current.map((message) =>
          message.id === pendingId ? { ...message, content: reply, pending: false } : message
        )
      );
      setIsBusy(false);
    },
    [responder]
  );

  const handleSend = React.useCallback(
    (text: string) => {
      const userMessage: ChatMessage = { id: createId(), role: 'user', content: text };
      const nextTranscript = [...messages, userMessage];
      setMessages(nextTranscript);
      void runAssistantTurn(nextTranscript, text, false);
    },
    [messages, runAssistantTurn]
  );

  const handleRegenerate = React.useCallback(() => {
    if (isBusy) return;
    // Find the last user prompt and the assistant reply that followed it.
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

  const showEmptyState = messages.length === 0;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="studio-ai-chat-conversation">
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

      <ChatComposer onSend={handleSend} isBusy={isBusy} />
    </div>
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
