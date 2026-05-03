/**
 * Studio AI chatbot — shared types (#258, #259).
 *
 * The chat surface is intentionally backend-agnostic so the same UI can host
 * the offline demo responder today and the Ollama transport when enabled
 * (#259, #265). Anything UI-facing lives here.
 */

import type { ChatStudioContext } from './chat-context';

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
}

/**
 * Adapter the chat shell calls when the user submits or regenerates. Returns
 * the assistant's full markdown reply. Implementations may stream internally;
 * the shell only renders the resolved value.
 */
export type ChatSendFn = (ctx: ChatSendContext) => Promise<string>;
