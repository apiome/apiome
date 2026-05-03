/**
 * Tests for the Ollama-backed Studio chat responder (#265).
 */

import { createOllamaChatResponder } from '../../src/app/ade/studio/components/chatbot/ollama-chat-responder';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

/** Minimal `Response` shape for `accumulateOllamaSseFromResponse` without relying on global `ReadableStream`. */
function mockSseResponse(sseLines: string[]) {
  const encoder = new TextEncoder();
  const payload = encoder.encode(sseLines.join(''));
  let sent = false;
  return {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          read(): Promise<{ done: boolean; value?: Uint8Array }> {
            if (!sent) {
              sent = true;
              return Promise.resolve({ done: false, value: payload });
            }
            return Promise.resolve({ done: true });
          },
        };
      },
    },
  };
}

describe('createOllamaChatResponder', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('returns a hint when no model is selected', async () => {
    global.fetch = jest.fn();
    const responder = createOllamaChatResponder();
    const messages: ChatMessage[] = [{ id: 'u1', role: 'user', content: 'Hi' }];
    const out = await responder({
      messages,
      prompt: 'Hi',
      isRegenerate: false,
    });
    expect(out).toMatch(/no model/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('posts transcript and accumulates SSE content', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse([
        'data: {"content":"Hello","done":false}\n\n',
        'data: {"content":" world","done":false}\n\n',
        'data: [DONE]\n\n',
      ]),
    );

    const responder = createOllamaChatResponder();
    const messages: ChatMessage[] = [{ id: 'u1', role: 'user', content: 'Hi' }];
    const out = await responder({
      messages,
      prompt: 'Hi',
      isRegenerate: false,
      ollamaModel: 'qwen2.5:latest',
    });

    expect(out).toBe('Hello world');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain('/api/ollama/chat');
    const body = JSON.parse(init.body as string) as { model: string; messages: Array<{ role: string; content: string }> };
    expect(body.model).toBe('qwen2.5:latest');
    expect(body.messages).toEqual([{ role: 'user', content: 'Hi' }]);
  });

  it('injects studio context into the latest user message only', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse(['data: {"content":"ok","done":true}\n\n', 'data: [DONE]\n\n']),
    );

    const responder = createOllamaChatResponder();
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: 'First' },
      { id: 'a1', role: 'assistant', content: 'Sure' },
      { id: 'u2', role: 'user', content: 'Second' },
    ];
    await responder({
      messages,
      prompt: 'Second',
      isRegenerate: false,
      ollamaModel: 'llama3.2:latest',
      studioContext: {
        project: { id: 'p1', name: 'Demo' },
        version: { id: 'v1', label: '1.0' },
        classes: [],
        properties: [],
        selectedClassIds: [],
      },
    });

    const init = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { messages: Array<{ role: string; content: string }> };
    expect(body.messages[0].content).toBe('First');
    expect(body.messages[1].content).toBe('Sure');
    expect(body.messages[2].content).toContain('Second');
    expect(body.messages[2].content).toContain('### Current Studio context');
    expect(body.messages[2].content).toContain('Demo');
  });

  it('throws when chat HTTP status is not ok', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ error: 'bad' }),
    });

    const responder = createOllamaChatResponder();
    await expect(
      responder({
        messages: [{ id: 'u1', role: 'user', content: 'Hi' }],
        prompt: 'Hi',
        isRegenerate: false,
        ollamaModel: 'm',
      }),
    ).rejects.toThrow();
  });
});
