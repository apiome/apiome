/**
 * Tests for the Ollama-backed Studio chat responder (#265).
 */

import { createOllamaChatResponder } from '../../src/app/ade/studio/components/chatbot/ollama-chat-responder';
import type { ChatMessage, ChatStreamAccumulatedMeta } from '../../src/app/ade/studio/components/chatbot/types';

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

  it('invokes onStreamAccumulated with accumulated text for each content chunk', async () => {
    const deltas: string[] = [];
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
      onStreamAccumulated: (acc) => deltas.push(acc),
    });

    expect(out).toBe('Hello world');
    expect(deltas).toEqual(['Hello', 'Hello world']);
  });

  it('passes token meta with each chunk and measured usage when the server sends it (#521)', async () => {
    const metas: ChatStreamAccumulatedMeta[] = [];
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse([
        'data: {"content":"Hi","done":false}\n\n',
        'data: {"content":"!","done":true,"usage":{"promptTokens":100,"completionTokens":2}}\n\n',
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
      onStreamAccumulated: (_acc, meta) => {
        if (meta) metas.push(meta);
      },
    });

    expect(out).toBe('Hi!');
    expect(metas.length).toBeGreaterThanOrEqual(2);
    expect(metas[0].estimatedPromptTokens).toBeGreaterThan(0);
    expect(metas[0].estimatedCompletionTokens).toBeGreaterThan(0);
    expect(metas[0].measured).toBeUndefined();
    const withMeasured = metas.find((m) => m.measured);
    expect(withMeasured?.measured).toEqual({ promptTokens: 100, completionTokens: 2 });
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

  it('includes schemaContextFingerprint in POST body when studio context has classes (#526)', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse(['data: {"content":"ok","done":true}\n\n', 'data: [DONE]\n\n']),
    );

    const responder = createOllamaChatResponder();
    await responder({
      messages: [{ id: 'u1', role: 'user', content: 'Hi' }],
      prompt: 'Hi',
      isRegenerate: false,
      ollamaModel: 'llama3.2:latest',
      studioContext: {
        project: { id: 'p1', name: 'Demo' },
        version: { id: 'v1', label: '1.0' },
        classes: [{ id: 'c1', name: 'User', schema: { type: 'object' } }],
        properties: [],
        selectedClassIds: [],
      },
    });

    const init = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as { schemaContextFingerprint?: string };
    expect(body.schemaContextFingerprint).toMatch(/^[0-9a-f]{64}$/);
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

  it('passes AbortSignal to fetch when provided (#522)', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse(['data: {"content":"x","done":true}\n\n', 'data: [DONE]\n\n']),
    );

    const ac = new AbortController();
    const responder = createOllamaChatResponder();
    await responder({
      messages: [{ id: 'u1', role: 'user', content: 'Hi' }],
      prompt: 'Hi',
      isRegenerate: false,
      ollamaModel: 'm',
      signal: ac.signal,
    });

    const init = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    expect(init.signal).toBe(ac.signal);
  });

  it('sends task class_skeleton and studio lists when ollamaTask is set (#532)', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      mockSseResponse(['data: {"content":"ok","done":true}\n\n', 'data: [DONE]\n\n']),
    );

    const responder = createOllamaChatResponder();
    await responder({
      messages: [{ id: 'u1', role: 'user', content: 'Refine' }],
      prompt: 'Refine',
      isRegenerate: false,
      ollamaModel: 'llama3.2:latest',
      ollamaTask: 'class_skeleton',
      studioContext: {
        project: { id: 'p1', name: 'Demo' },
        version: { id: 'v1', label: '1.0' },
        classes: [{ id: 'c1', name: 'User', schema: {} }],
        properties: [{ id: 'pr1', name: 'email', type: 'string', format: 'email' }],
        selectedClassIds: [],
      },
    });

    const init = (global.fetch as jest.Mock).mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string) as {
      task?: string;
      existingClassNames?: string[];
      existingProperties?: Array<{ name: string }>;
      versionId?: string;
    };
    expect(body.task).toBe('class_skeleton');
    expect(body.existingClassNames).toEqual(['User']);
    expect(body.existingProperties?.[0]?.name).toBe('email');
    expect(body.versionId).toBe('v1');
  });

  it('returns Generation stopped. when fetch aborts before any body (#522)', async () => {
    global.fetch = jest.fn().mockImplementation((_url: string, init?: RequestInit) => {
      const signal = init?.signal;
      return new Promise<Response>((_resolve, reject) => {
        const onAbort = () => {
          reject(new DOMException('Aborted', 'AbortError'));
        };
        if (signal?.aborted) {
          queueMicrotask(onAbort);
          return;
        }
        signal?.addEventListener('abort', onAbort, { once: true });
      });
    });

    const ac = new AbortController();
    const responder = createOllamaChatResponder();
    const p = responder({
      messages: [{ id: 'u1', role: 'user', content: 'Hi' }],
      prompt: 'Hi',
      isRegenerate: false,
      ollamaModel: 'm',
      signal: ac.signal,
    });
    ac.abort();
    await expect(p).resolves.toBe('Generation stopped.');
  });
});
