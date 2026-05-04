/**
 * Ollama-backed `ChatSendFn` for the Studio AI chatbot (#265).
 *
 * Posts to `/api/ollama/chat` with the model from context, maps the transcript
 * to Ollama message shape, injects Studio context into the latest user turn,
 * and reads the SSE stream. When `onStreamAccumulated` is set on the context (#520),
 * each chunk is forwarded so the UI can render incrementally; the returned
 * string is still the full accumulated markdown. Token estimates and Ollama-reported
 * usage are forwarded on the same callback (#521).
 */

import { computeStudioSchemaFingerprint } from '@lib/studio-schema-fingerprint';
import { injectChatContext, isChatStudioContextEmpty } from './chat-context';
import type {
  ChatMessage,
  ChatSendContext,
  ChatSendFn,
  ChatStreamAccumulatedMeta,
} from './types';
import { isAbortError } from './abort-errors';

export function createOllamaChatResponder(): ChatSendFn {
  return async (ctx: ChatSendContext) => {
    const model = ctx.ollamaModel?.trim();
    if (!model) {
      return 'No model is selected. Choose a model from the list above.';
    }

    const messages = buildOllamaChatMessages(ctx.messages, ctx.studioContext);
    const estimatedPromptTokens = approximateTokensFromJson(JSON.stringify(messages));
    let lastAccumulated = '';

    const forwardDelta = (accumulatedMarkdown: string, meta: ChatStreamAccumulatedMeta) => {
      lastAccumulated = accumulatedMarkdown;
      ctx.onStreamAccumulated?.(accumulatedMarkdown, meta);
    };

    let schemaContextFingerprint: string | undefined;
    if (ctx.studioContext && !isChatStudioContextEmpty(ctx.studioContext)) {
      try {
        schemaContextFingerprint = await computeStudioSchemaFingerprint(ctx.studioContext);
      } catch {
        /* Web Crypto unavailable: skip optional cache-busting fingerprint */
      }
    }

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model,
          messages,
          ...(schemaContextFingerprint ? { schemaContextFingerprint } : {}),
        }),
        signal: ctx.signal,
      });

      if (!response.ok) {
        let detail = '';
        try {
          detail = await response.text();
        } catch {
          /* ignore */
        }
        throw new Error(detail || `Chat request failed (${response.status})`);
      }

      const text = await accumulateOllamaSseFromResponse(response, {
        estimatedPromptTokens,
        onDelta: forwardDelta,
        signal: ctx.signal,
      });
      const trimmed = text.trim();
      if (trimmed.length > 0) return trimmed;
      if (ctx.signal?.aborted) return 'Generation stopped.';
      return 'The model returned an empty reply.';
    } catch (error) {
      if (ctx.signal?.aborted && isAbortError(error)) {
        const t = lastAccumulated.trim();
        return t.length > 0 ? lastAccumulated : 'Generation stopped.';
      }
      throw error;
    }
  };
}

function buildOllamaChatMessages(
  transcript: ChatMessage[],
  studioContext: ChatSendContext['studioContext'],
): Array<{ role: string; content: string }> {
  let lastUserIdx = -1;
  for (let i = transcript.length - 1; i >= 0; i -= 1) {
    if (transcript[i].role === 'user') {
      lastUserIdx = i;
      break;
    }
  }

  const out: Array<{ role: string; content: string }> = [];
  for (let i = 0; i < transcript.length; i += 1) {
    const m = transcript[i];
    if (m.role !== 'user' && m.role !== 'assistant') continue;
    const content =
      i === lastUserIdx && m.role === 'user'
        ? injectChatContext(m.content, studioContext)
        : m.content;
    out.push({ role: m.role, content });
  }
  return out;
}

/** Rough token count (÷4 chars) for live UI; not a tokenizer. */
function approximateTokensFromJson(serialized: string): number {
  if (serialized.length === 0) return 0;
  return Math.max(1, Math.ceil(serialized.length / 4));
}

function approximateCompletionTokens(markdown: string): number {
  if (markdown.length === 0) return 0;
  return Math.max(1, Math.ceil(markdown.length / 4));
}

async function accumulateOllamaSseFromResponse(
  response: Response,
  options: {
    estimatedPromptTokens: number;
    onDelta?: (accumulatedMarkdown: string, meta: ChatStreamAccumulatedMeta) => void;
    signal?: AbortSignal;
  },
): Promise<string> {
  const { estimatedPromptTokens, onDelta, signal } = options;
  const reader = response.body?.getReader();
  if (!reader) return '';

  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';

  function emitIfNeeded(
    contentAppended: boolean,
    usage?: { promptTokens?: number; completionTokens?: number },
  ): void {
    if (!onDelta) return;
    const estimatedCompletionTokens = approximateCompletionTokens(accumulated);
    const meta: ChatStreamAccumulatedMeta = {
      estimatedPromptTokens,
      estimatedCompletionTokens,
    };
    if (usage && (typeof usage.promptTokens === 'number' || typeof usage.completionTokens === 'number')) {
      meta.measured = {
        promptTokens:
          typeof usage.promptTokens === 'number' ? usage.promptTokens : estimatedPromptTokens,
        completionTokens:
          typeof usage.completionTokens === 'number'
            ? usage.completionTokens
            : estimatedCompletionTokens,
      };
    }
    if (!contentAppended && !meta.measured) return;
    onDelta(accumulated, meta);
  }

  while (true) {
    if (signal?.aborted) {
      await reader.cancel().catch(() => {});
      break;
    }
    let readResult: ReadableStreamReadResult<Uint8Array>;
    try {
      readResult = await reader.read();
    } catch (error) {
      if (signal?.aborted && isAbortError(error)) {
        break;
      }
      throw error;
    }
    const { done, value } = readResult;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') continue;
      try {
        const event = JSON.parse(data) as {
          content?: string;
          usage?: { promptTokens?: number; completionTokens?: number };
        };
        let appended = false;
        if (event.content) {
          accumulated += event.content;
          appended = true;
        }
        emitIfNeeded(appended, event.usage);
      } catch {
        /* ignore malformed SSE lines */
      }
    }
  }

  return accumulated;
}
