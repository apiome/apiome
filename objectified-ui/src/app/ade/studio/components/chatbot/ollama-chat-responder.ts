/**
 * Ollama-backed `ChatSendFn` for the Studio AI chatbot (#265).
 *
 * Posts to `/api/ollama/chat` with the model from context, maps the transcript
 * to Ollama message shape, injects Studio context into the latest user turn,
 * and accumulates the SSE stream into a single markdown string.
 */

import { injectChatContext } from './chat-context';
import type { ChatMessage, ChatSendContext, ChatSendFn } from './types';

export function createOllamaChatResponder(): ChatSendFn {
  return async (ctx: ChatSendContext) => {
    const model = ctx.ollamaModel?.trim();
    if (!model) {
      return 'No model is selected. Choose a model from the list above.';
    }

    const messages = buildOllamaChatMessages(ctx.messages, ctx.studioContext);

    const response = await fetch('/api/ollama/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, messages }),
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

    const text = await accumulateOllamaSseFromResponse(response);
    return text.trim().length > 0 ? text : 'The model returned an empty reply.';
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

async function accumulateOllamaSseFromResponse(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return '';

  const decoder = new TextDecoder();
  let buffer = '';
  let accumulated = '';

  while (true) {
    const { done, value } = await reader.read();
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
        const event = JSON.parse(data) as { content?: string };
        if (event.content) accumulated += event.content;
      } catch {
        /* ignore malformed SSE lines */
      }
    }
  }

  return accumulated;
}
