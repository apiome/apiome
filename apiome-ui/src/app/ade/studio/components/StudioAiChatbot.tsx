'use client';

/**
 * Studio AI Chatbot — placement chrome + chat surface (#257, #258, #259, #265).
 *
 * Provides the launcher and panel surfaces for the studio chatbot:
 *   - Floating launcher bubble in the bottom right corner of the canvas
 *   - Slide-out panel anchored to the right edge of the studio
 *   - Full-screen chat mode for complex conversations
 *   - Keyboard shortcut to toggle (⌘+Shift+A on macOS, Ctrl+Shift+A elsewhere)
 *
 * The chat surface itself follows the chatbot interface guidelines (#258):
 * message bubbles distinguished by role, typing indicator while the assistant
 * is working, markdown + syntax-highlighted code blocks with copy buttons,
 * regenerate / thumbs up / thumbs down message actions, and one-click import
 * for ```json``` blocks that look like OpenAPI specs.
 *
 * Context awareness (#259): callers can pass a `studioContext` snapshot
 * (project, version, classes, properties, canvas selection) which is
 * forwarded to the responder on every send, and surfaced in-panel via a
 * "Sharing context" chip so users always see what the assistant can see.
 *
 * Ollama model listing and selection (#265): the conversation loads tags from
 * `/api/ollama/models` and sends each turn through `/api/ollama/chat` when a
 * model is available; otherwise the offline demo responder keeps the panel usable.
 *
 * Default model preferences (#266): when `tenantId` is passed with a project in
 * `studioContext`, the user's model choice is stored per project (and can be
 * promoted to the whole tenant via the chat toolbar).
 */

import * as React from 'react';
import { usePathname } from 'next/navigation';
import { toast } from 'sonner';
import { Bot, Maximize2, Minimize2, Sparkles, X } from 'lucide-react';
import { matchesStudioAiChatbotShortcut } from '@/app/utils/studio-keybindings';
import { ChatConversation } from './chatbot/ChatConversation';
import type { StudioChatWorkspaceAction } from './chatbot/assistant-action-detection';
import type { ChatStudioContext } from './chatbot/chat-context';
import type { DetectedOpenApiSpec } from './chatbot/openapi-detection';

/**
 * Open/closed state for the chatbot panel. `slide` is the default expanded mode
 * (right-anchored drawer); `fullscreen` covers the canvas area for longer
 * conversations.
 */
export type StudioAiChatbotMode = 'closed' | 'slide' | 'fullscreen';

/**
 * Pathname prefixes where the chatbot launcher is allowed to appear. Restricted
 * to canvas-style surfaces so the bubble does not float above the dashboard,
 * admin, or auth pages.
 */
const CHATBOT_CANVAS_PATH_PREFIXES: readonly string[] = [
  '/ade/studio/editor',
  '/ade/studio/paths',
];

const SLIDE_PANEL_WIDTH_CLASSES = 'w-full max-w-md sm:w-[26rem]';

export function isStudioAiChatbotPath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return CHATBOT_CANVAS_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export interface StudioAiChatbotProps {
  /**
   * Override the path-based gating used in production. Useful for tests and
   * for previewing the placement on other surfaces.
   */
  forceVisible?: boolean;
  /** Optional initial mode (defaults to `closed`). */
  initialMode?: StudioAiChatbotMode;
  /**
   * Snapshot of the user's Studio workspace (#259). Forwarded to the chat
   * conversation so the responder can ground its replies in the active
   * project, version, classes, properties, and canvas selection.
   */
  studioContext?: ChatStudioContext;
  /** Current tenant id from the session (#266) — enables per-tenant/project Ollama defaults. */
  tenantId?: string | null;
  /** Studio layout handler for assistant quick-action buttons (#518). */
  onChatWorkspaceAction?: (action: StudioChatWorkspaceAction) => void | Promise<void>;
}

/**
 * Mounts the chatbot launcher and panel. Safe to render once at the studio
 * layout level; it gates itself based on the current pathname.
 */
export function StudioAiChatbot({
  forceVisible,
  initialMode = 'closed',
  studioContext,
  tenantId,
  onChatWorkspaceAction,
}: StudioAiChatbotProps = {}) {
  const pathname = usePathname();
  const [mode, setMode] = React.useState<StudioAiChatbotMode>(initialMode);

  const visible = forceVisible || isStudioAiChatbotPath(pathname);

  const open = mode !== 'closed';
  const close = React.useCallback(() => setMode('closed'), []);
  const toggle = React.useCallback(() => {
    setMode((prev) => (prev === 'closed' ? 'slide' : 'closed'));
  }, []);

  React.useEffect(() => {
    if (!visible) return;
    const handler = (ev: KeyboardEvent) => {
      if (!matchesStudioAiChatbotShortcut(ev)) return;
      ev.preventDefault();
      toggle();
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, [visible, toggle]);

  React.useEffect(() => {
    if (!open) return;
    const handler = (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape' || ev.defaultPrevented) return;
      ev.preventDefault();
      close();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, close]);

  if (!visible) return null;

  return (
    <>
      {!open && <ChatbotLauncher onOpen={() => setMode('slide')} />}
      {open && (
        <ChatbotPanel
          mode={mode}
          onModeChange={setMode}
          onClose={close}
          studioContext={studioContext}
          tenantId={tenantId}
          onChatWorkspaceAction={onChatWorkspaceAction}
        />
      )}
    </>
  );
}

interface ChatbotLauncherProps {
  onOpen: () => void;
}

function ChatbotLauncher({ onOpen }: ChatbotLauncherProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Open AI chatbot"
      data-testid="studio-ai-chatbot-launcher"
      className="fixed bottom-8 right-6 z-[1300] inline-flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 text-white shadow-xl ring-1 ring-black/10 transition-transform hover:scale-105 hover:shadow-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:ring-white/10"
    >
      <Sparkles className="h-6 w-6" />
    </button>
  );
}

interface ChatbotPanelProps {
  mode: Exclude<StudioAiChatbotMode, 'closed'>;
  onModeChange: (mode: StudioAiChatbotMode) => void;
  onClose: () => void;
  studioContext?: ChatStudioContext;
  tenantId?: string | null;
  onChatWorkspaceAction?: (action: StudioChatWorkspaceAction) => void | Promise<void>;
}

function ChatbotPanel({
  mode,
  onModeChange,
  onClose,
  studioContext,
  tenantId,
  onChatWorkspaceAction,
}: ChatbotPanelProps) {
  const isFullscreen = mode === 'fullscreen';

  const containerClasses = isFullscreen
    ? 'fixed inset-4 sm:inset-8'
    : `fixed bottom-8 right-6 top-32 ${SLIDE_PANEL_WIDTH_CLASSES}`;

  const toggleFullscreen = () =>
    onModeChange(isFullscreen ? 'slide' : 'fullscreen');

  // Import is previewed in the chat shell (#519) before this runs; until
  // project-aware import lands in a follow-up, surface the detected spec via a toast.
  const handleImportSpec = React.useCallback((spec: DetectedOpenApiSpec) => {
    const title = (spec.spec.info as { title?: string } | undefined)?.title ?? 'OpenAPI spec';
    toast.success(`Ready to import: ${title}`, {
      description: `${spec.version ? `OpenAPI ${spec.version}` : 'OpenAPI document'} captured from the chat.`,
    });
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-label="AI chatbot"
      data-testid="studio-ai-chatbot-panel"
      data-mode={mode}
      className={`${containerClasses} z-[1301] flex flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-900`}
    >
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 bg-gradient-to-r from-purple-50 to-indigo-50 px-4 py-3 dark:border-gray-700 dark:from-purple-950/40 dark:to-indigo-950/40">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 text-white">
            <Bot className="h-4 w-4" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              AI Chatbot
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {isFullscreen ? 'Full-screen chat' : 'Studio side panel'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit full-screen chat' : 'Expand chat to full screen'}
            data-testid="studio-ai-chatbot-toggle-fullscreen"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
          >
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI chatbot"
            data-testid="studio-ai-chatbot-close"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col">
        <ChatConversation
          onImportSpec={handleImportSpec}
          onChatWorkspaceAction={onChatWorkspaceAction}
          studioContext={studioContext}
          tenantId={tenantId}
          ollamaTransport
        />
      </div>

      <footer className="border-t border-gray-200 bg-gray-50 px-4 py-2 text-[11px] text-gray-500 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-400">
        Toggle this panel any time with{' '}
        <kbd className="rounded border border-gray-300 bg-white px-1.5 py-0.5 font-mono text-[10px] text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200">
          ⌘⇧A
        </kbd>
        {' / '}
        <kbd className="rounded border border-gray-300 bg-white px-1.5 py-0.5 font-mono text-[10px] text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200">
          Ctrl+Shift+A
        </kbd>
        .
      </footer>
    </div>
  );
}

export default StudioAiChatbot;
