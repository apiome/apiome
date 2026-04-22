'use client';

import * as React from 'react';
import type { Components } from 'react-markdown';
import { Bot, Download, RefreshCw, ThumbsDown, ThumbsUp, User } from 'lucide-react';

import { Markdown } from '@/app/components/ui/Markdown';
import { ChatCodeBlock } from './ChatCodeBlock';
import { ChatTypingIndicator } from './ChatTypingIndicator';
import { detectOpenApiSpecs, type DetectedOpenApiSpec } from './openapi-detection';
import type { ChatFeedback, ChatMessage } from './types';

/**
 * Chat bubble (#258).
 *
 * Renders a single message — user or assistant — with the design rules from
 * the chatbot interface guidelines:
 *   - bubbles are visually distinct (color, alignment, avatar) by role
 *   - assistant content is rendered as markdown via the shared `<Markdown>`
 *     component, with the chat-specific `<ChatCodeBlock>` for fences
 *   - assistant messages expose Regenerate and thumbs up/down feedback
 *   - assistant messages with a recognizably-OpenAPI ```json``` block expose
 *     a one-click Import button
 */
export interface ChatBubbleProps {
  message: ChatMessage;
  /** True if this is the most recent assistant message (regenerate target). */
  isLatestAssistant?: boolean;
  onRegenerate?: () => void;
  onFeedback?: (feedback: ChatFeedback) => void;
  /** Receives the raw JSON of the spec the user chose to import. */
  onImportSpec?: (spec: DetectedOpenApiSpec) => void;
}

export function ChatBubble({
  message,
  isLatestAssistant = false,
  onRegenerate,
  onFeedback,
  onImportSpec,
}: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const specs = React.useMemo(
    () => (isUser ? [] : detectOpenApiSpecs(message.content)),
    [isUser, message.content]
  );

  const containerAlignment = isUser ? 'justify-end' : 'justify-start';
  const stackAlignment = isUser ? 'items-end' : 'items-start';
  const bubbleSurface = isUser
    ? 'bg-indigo-600 text-white'
    : 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100';

  return (
    <div
      data-testid="studio-ai-chat-bubble"
      data-role={message.role}
      data-message-id={message.id}
      className={`flex w-full gap-3 ${containerAlignment}`}
    >
      {!isUser && <Avatar role="assistant" />}

      <div className={`flex max-w-[85%] flex-col gap-1.5 ${stackAlignment}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${bubbleSurface}`}
        >
          {message.pending && !message.content ? (
            <ChatTypingIndicator />
          ) : isUser ? (
            <p className="m-0 whitespace-pre-wrap">{message.content}</p>
          ) : (
            <AssistantMarkdown content={message.content} />
          )}
        </div>

        {!isUser && !message.pending && message.content && (
          <AssistantActions
            message={message}
            isLatest={isLatestAssistant}
            specs={specs}
            onRegenerate={onRegenerate}
            onFeedback={onFeedback}
            onImportSpec={onImportSpec}
          />
        )}
      </div>

      {isUser && <Avatar role="user" />}
    </div>
  );
}

function Avatar({ role }: { role: 'user' | 'assistant' }) {
  const isUser = role === 'user';
  return (
    <span
      aria-hidden
      className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white shadow-sm ${
        isUser
          ? 'bg-indigo-600'
          : 'bg-gradient-to-br from-purple-500 to-indigo-600'
      }`}
    >
      {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
    </span>
  );
}

interface AssistantActionsProps {
  message: ChatMessage;
  isLatest: boolean;
  specs: DetectedOpenApiSpec[];
  onRegenerate?: () => void;
  onFeedback?: (feedback: ChatFeedback) => void;
  onImportSpec?: (spec: DetectedOpenApiSpec) => void;
}

function AssistantActions({
  message,
  isLatest,
  specs,
  onRegenerate,
  onFeedback,
  onImportSpec,
}: AssistantActionsProps) {
  const feedback = message.feedback;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {isLatest && onRegenerate && (
        <ActionButton
          onClick={onRegenerate}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          label="Regenerate response"
          testId="studio-ai-chat-regenerate"
        />
      )}
      {onFeedback && (
        <>
          <ActionButton
            onClick={() => onFeedback('up')}
            icon={<ThumbsUp className="h-3.5 w-3.5" />}
            label="Mark response as helpful"
            testId="studio-ai-chat-thumbs-up"
            active={feedback === 'up'}
          />
          <ActionButton
            onClick={() => onFeedback('down')}
            icon={<ThumbsDown className="h-3.5 w-3.5" />}
            label="Mark response as not helpful"
            testId="studio-ai-chat-thumbs-down"
            active={feedback === 'down'}
          />
        </>
      )}
      {onImportSpec &&
        specs.map((spec, index) => (
          <button
            key={`spec-${index}`}
            type="button"
            onClick={() => onImportSpec(spec)}
            data-testid={`studio-ai-chat-import-spec-${index}`}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
          >
            <Download className="h-3.5 w-3.5" />
            {specs.length > 1 ? `Import spec ${index + 1}` : 'Import OpenAPI spec'}
          </button>
        ))}
    </div>
  );
}

interface ActionButtonProps {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  testId: string;
  active?: boolean;
}

function ActionButton({ onClick, icon, label, testId, active }: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active}
      data-testid={testId}
      data-active={active ? 'true' : 'false'}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100 ${
        active ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200' : ''
      }`}
    >
      {icon}
    </button>
  );
}

const ASSISTANT_MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-3 text-sm font-semibold first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h3>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-indigo-600 underline-offset-2 hover:underline dark:text-indigo-300"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-gray-300 pl-3 italic text-gray-600 dark:border-gray-600 dark:text-gray-300">
      {children}
    </blockquote>
  ),
  code: (codeProps) => {
    const { className, children } = codeProps as {
      className?: string;
      children?: React.ReactNode;
    };
    const langMatch = /language-(\w+)/.exec(className || '');
    const isInline = !langMatch;
    if (isInline) {
      return (
        <code className="rounded bg-gray-200 px-1 py-0.5 font-mono text-[12px] text-gray-900 dark:bg-gray-700 dark:text-gray-100">
          {children}
        </code>
      );
    }
    const text = React.Children.toArray(children)
      .map((child) => (typeof child === 'string' ? child : ''))
      .join('');
    return <ChatCodeBlock code={text} language={langMatch?.[1]} />;
  },
  pre: ({ children }) => <>{children}</>,
};

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <Markdown variant="bare" components={ASSISTANT_MARKDOWN_COMPONENTS}>
      {content}
    </Markdown>
  );
}
