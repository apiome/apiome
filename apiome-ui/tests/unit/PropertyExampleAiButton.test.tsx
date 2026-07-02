jest.mock('@lib/ollama-chat-sse', () => ({
  accumulateOllamaSse: jest.fn(),
}));

jest.mock('../../src/app/components/ui/Button', () => ({
  Button: ({ disabled, ...props }: JSX.IntrinsicElements['button']) => (
    <button {...props} data-disabled={String(Boolean(disabled))} />
  ),
}));

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PropertyExampleAiButton } from '../../src/app/components/ade/studio/PropertyExampleAiButton';
import { EMPTY_CHAT_STUDIO_CONTEXT } from '../../src/app/ade/studio/components/chatbot/chat-context';

describe('PropertyExampleAiButton (#622)', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('keeps the latest request busy when an earlier generate is aborted', async () => {
    let chatCallCount = 0;
    let resolveSecondChat: ((value: Response) => void) | null = null;

    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/api/ollama/models')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ success: true, models: [{ name: 'mistral' }] }),
        } as Response);
      }
      if (!url.includes('/api/ollama/chat')) {
        return Promise.reject(new Error(`unexpected fetch: ${url}`));
      }

      chatCallCount += 1;
      if (chatCallCount === 1) {
        return new Promise<Response>((_resolve, reject) => {
          const onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
          if (init?.signal?.aborted) {
            queueMicrotask(onAbort);
            return;
          }
          init?.signal?.addEventListener('abort', onAbort, { once: true });
        });
      }

      return new Promise<Response>((resolve) => {
        resolveSecondChat = resolve;
      });
    }) as typeof fetch;

    render(
      <PropertyExampleAiButton
        tenantId="tenant-1"
        projectId="project-1"
        versionId={null}
        propertyName="email"
        propertySchema={{ type: 'string', format: 'email' }}
        existingClasses={[]}
        existingProperties={[]}
        studioContext={EMPTY_CHAT_STUDIO_CONTEXT}
        onGenerated={jest.fn()}
      />,
    );

    const generateButton = await screen.findByTestId('property-example-ai-generate');
    await waitFor(() => expect(generateButton).toHaveAttribute('data-disabled', 'false'));

    fireEvent.click(generateButton);
    fireEvent.click(generateButton);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getByTestId('property-example-ai-stop')).toBeInTheDocument());
    expect(generateButton).toHaveTextContent('Generating…');
    expect(generateButton).toHaveAttribute('data-disabled', 'true');

    resolveSecondChat?.({
      ok: false,
      text: async () => 'stopped for test',
    } as Response);

    await waitFor(() => expect(screen.queryByTestId('property-example-ai-stop')).not.toBeInTheDocument());
  });
});
