'use client';

import * as React from 'react';
import type { Components } from 'react-markdown';
import { Bot, ClipboardCopy, Download, ListChecks, ListPlus, Pencil, Plus, RefreshCw, ThumbsDown, ThumbsUp, User } from 'lucide-react';
import { toast } from 'sonner';

import { Markdown } from '@/app/components/ui/Markdown';
import { ChatCodeBlock } from './ChatCodeBlock';
import { ChatTypingIndicator } from './ChatTypingIndicator';
import {
  detectChatQuickActions,
  type DetectedChatQuickAction,
  type StudioChatWorkspaceAction,
} from './assistant-action-detection';
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
 *     a **Preview changes** button (#519) that opens the import preview flow in the shell
 *   - assistant messages that include quick-action CTAs expose matching buttons (#518)
 */
export interface ChatBubbleProps {
  message: ChatMessage;
  /** True if this is the most recent assistant message (regenerate target). */
  isLatestAssistant?: boolean;
  onRegenerate?: () => void;
  onFeedback?: (feedback: ChatFeedback) => void;
  /** When the user clicks "Preview changes" on a ```json``` OpenAPI block (opens the preview dialog in the shell). */
  onRequestImportSpecPreview?: (spec: DetectedOpenApiSpec) => void;
  /** Opens the class-schema preview dialog before `create_class` workspace actions (#528). */
  onRequestClassCreatePreview?: (assistantMarkdown: string) => void;
  /** Studio layout wires class/property flows for quick-action buttons (#518). */
  onChatWorkspaceAction?: (action: StudioChatWorkspaceAction) => void | Promise<void>;
}

export function ChatBubble({
  message,
  isLatestAssistant = false,
  onRegenerate,
  onFeedback,
  onRequestImportSpecPreview,
  onRequestClassCreatePreview,
  onChatWorkspaceAction,
}: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const specs = React.useMemo(
    () => (isUser ? [] : detectOpenApiSpecs(message.content)),
    [isUser, message.content]
  );
  const quickActions = React.useMemo(
    () => (isUser ? [] : detectChatQuickActions(message.content)),
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
            <p className="m-0 whitespace-pre-wrap text-white!">{message.content}</p>
          ) : (
            <AssistantMarkdown content={message.content} />
          )}
        </div>

        {!isUser && !message.pending && message.content && (
          <AssistantActions
            message={message}
            isLatest={isLatestAssistant}
            specs={specs}
            quickActions={quickActions}
            onRegenerate={onRegenerate}
            onFeedback={onFeedback}
            onRequestImportSpecPreview={onRequestImportSpecPreview}
            onRequestClassCreatePreview={onRequestClassCreatePreview}
            onChatWorkspaceAction={onChatWorkspaceAction}
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
  quickActions: DetectedChatQuickAction[];
  onRegenerate?: () => void;
  onFeedback?: (feedback: ChatFeedback) => void;
  onRequestImportSpecPreview?: (spec: DetectedOpenApiSpec) => void;
  onRequestClassCreatePreview?: (assistantMarkdown: string) => void;
  onChatWorkspaceAction?: (action: StudioChatWorkspaceAction) => void | Promise<void>;
}

function AssistantActions({
  message,
  isLatest,
  specs,
  quickActions,
  onRegenerate,
  onFeedback,
  onRequestImportSpecPreview,
  onRequestClassCreatePreview,
  onChatWorkspaceAction,
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
      {onRequestImportSpecPreview &&
        specs.map((spec, index) => (
          <button
            key={`spec-${index}`}
            type="button"
            onClick={() => onRequestImportSpecPreview(spec)}
            data-testid={`studio-ai-chat-import-spec-${index}`}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
          >
            <Download className="h-3.5 w-3.5" />
            {specs.length > 1 ? `Preview changes (${index + 1})` : 'Preview changes'}
          </button>
        ))}
      {quickActions.map((action, index) => (
        <QuickActionButton
          key={`quick-${action.kind}-${index}`}
          action={action}
          index={index}
          assistantMessageMarkdown={message.content}
          onRequestClassCreatePreview={onRequestClassCreatePreview}
          onChatWorkspaceAction={onChatWorkspaceAction}
        />
      ))}
    </div>
  );
}

function QuickActionButton({
  action,
  index,
  assistantMessageMarkdown,
  onRequestClassCreatePreview,
  onChatWorkspaceAction,
}: {
  action: DetectedChatQuickAction;
  index: number;
  assistantMessageMarkdown: string;
  onRequestClassCreatePreview?: (markdown: string) => void;
  onChatWorkspaceAction?: (a: StudioChatWorkspaceAction) => void | Promise<void>;
}) {
  if (action.kind === 'copy_generated_payload') {
    return (
      <button
        type="button"
        data-testid={`studio-ai-chat-quick-copy-${index}`}
        onClick={async () => {
          if (typeof navigator === 'undefined' || !navigator.clipboard) {
            toast.error('Clipboard is not available in this environment.');
            return;
          }
          try {
            await navigator.clipboard.writeText(action.payload);
            toast.success('Copied JSON/YAML to clipboard.');
          } catch {
            toast.error('Could not copy to the clipboard.');
          }
        }}
        className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-medium text-gray-800 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
      >
        <ClipboardCopy className="h-3.5 w-3.5" />
        Copy JSON/YAML
      </button>
    );
  }

  if (!onChatWorkspaceAction) return null;

  const meta: Record<
    StudioChatWorkspaceAction['kind'],
    { label: string; icon: React.ReactNode; testId: string }
  > = {
    create_class: {
      label: 'Create this class',
      icon: <Plus className="h-3.5 w-3.5" />,
      testId: 'studio-ai-chat-quick-create-class',
    },
    batch_add_properties: {
      label: 'Add these properties',
      icon: <ListPlus className="h-3.5 w-3.5" />,
      testId: 'studio-ai-chat-quick-batch-properties',
    },
    apply_current_class: {
      label: 'Apply to current class',
      icon: <Pencil className="h-3.5 w-3.5" />,
      testId: 'studio-ai-chat-quick-apply-class',
    },
    open_property_suggestions: {
      label: 'Open AI property suggestions',
      icon: <ListChecks className="h-3.5 w-3.5" />,
      testId: 'studio-ai-chat-quick-open-property-suggestions',
    },
  };

  const { label, icon, testId } = meta[action.kind];

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={() => {
        if (action.kind === 'create_class' && onRequestClassCreatePreview) {
          onRequestClassCreatePreview(assistantMessageMarkdown);
          return;
        }
        void onChatWorkspaceAction?.({ kind: action.kind });
      }}
      className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800 transition-colors hover:bg-emerald-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-100 dark:hover:bg-emerald-900/50"
    >
      {icon}
      {label}
    </button>
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
