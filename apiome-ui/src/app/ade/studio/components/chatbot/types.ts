/**
 * Studio AI chatbot — shared types (#258, #259).
 *
 * The chat surface is intentionally backend-agnostic so the same UI can host
 * the offline demo responder today and the Ollama transport when enabled
 * (#259, #265). Anything UI-facing lives here.
 */

import type { ChatStudioContext } from './chat-context';

/** Token hints passed with each streaming update from Ollama-backed responders (#521). */
export interface ChatStreamAccumulatedMeta {
  /** Rough prompt size from the serialized chat payload (characters ÷ 4). */
  estimatedPromptTokens: number;
  /** Rough completion size from accumulated assistant text so far (characters ÷ 4). */
  estimatedCompletionTokens: number;
  /** Exact counts from Ollama when the server forwards usage on the final SSE chunk. */
  measured?: {
    promptTokens: number;
    completionTokens: number;
  };
}

export type ChatRole = 'user' | 'assistant';

export type ChatFeedback = 'up' | 'down';

export interface ChatMessage {
  /** Stable id for keys, regenerate, and feedback toggles. */
  id: string;
  role: ChatRole;
  /** Markdown source. Rendered with `react-markdown` + chatbot components. */
  content: string;
  /** True while the assistant turn is still streaming/thinking. */
  pending?: boolean;
  /** Most recent feedback the user gave on an assistant message, if any. */
  feedback?: ChatFeedback;
}

export interface ChatSendContext {
  /** Full transcript including the new user message — useful for backends. */
  messages: ChatMessage[];
  /** Convenience pointer to the just-sent user message. */
  prompt: string;
  /** True when the caller asked the assistant to redo its previous answer. */
  isRegenerate: boolean;
  /**
   * Snapshot of the user's Studio workspace (#259): current project / version,
   * loaded classes and properties, and any canvas selection. Responders should
   * treat this as authoritative grounding for the user's request — it is
   * captured at the moment the message is sent so later edits don't leak
   * back into earlier turns.
   */
  studioContext?: ChatStudioContext;
  /**
   * Ollama model tag (e.g. `qwen2.5:latest`) when using `createOllamaChatResponder` (#265).
   */
  ollamaModel?: string;
  /**
   * When `class_skeleton`, `/api/ollama/chat` uses the JSON Schema class task (same as Create Class with AI; #532 refinement).
   */
  ollamaTask?: 'class_skeleton';
  /**
   * Called as streamed assistant text grows (e.g. Ollama SSE). Receives the full
   * accumulated markdown seen so far — NOT the latest delta chunk. The shell passes
   * this so the pending bubble updates live; responders that do not stream can ignore it (#520).
   * When present, `meta` carries live token estimates and optional measured usage (#521).
   */
  onStreamAccumulated?: (accumulatedMarkdown: string, meta?: ChatStreamAccumulatedMeta) => void;
  /**
   * When the UI stops generation (#522), the shell aborts this signal. Streaming
   * responders should pass it to `fetch` and/or body readers so work unwinds promptly.
   */
  signal?: AbortSignal;
}

/**
 * Adapter the chat shell calls when the user submits or regenerates. Returns
 * the assistant's full markdown reply. When the shell supplies `onStreamAccumulated`,
 * streaming responders should invoke it as content arrives; the shell still uses
 * the resolved return value as the final assistant text. Streaming callers may pass
 * a second argument to `onStreamAccumulated` for token usage (#521).
 */
export type ChatSendFn = (ctx: ChatSendContext) => Promise<string>;
