/**
 * AI property suggestions dialog — bulk **Add all suggested** control (#274).
 */

jest.mock('@lib/ollama-chat-sse', () => ({
  accumulateOllamaSse: jest.fn(async () =>
    [
      '```json',
      JSON.stringify({
        thinking: '',
        summary: '',
        suggestions: [{ name: 'alpha', description: 'd', schema: { type: 'string' } }],
      }),
      '```',
    ].join('\n'),
  ),
}));

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AiPropertySuggestionsDialog } from '../../src/app/components/ade/studio/AiPropertySuggestionsDialog';
import { EMPTY_CHAT_STUDIO_CONTEXT } from '../../src/app/ade/studio/components/chatbot/chat-context';

(global as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const modelsPayload = { success: true, models: [{ name: 'mistral' }] };

function stubFetch(): void {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/ollama/models')) {
      return Promise.resolve({
        ok: true,
        json: async () => modelsPayload,
      } as Response);
    }
    if (url.includes('/api/ollama/chat')) {
      return Promise.resolve({ ok: true } as Response);
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  }) as typeof fetch;
}

describe('AiPropertySuggestionsDialog', () => {
  beforeEach(() => {
    stubFetch();
  });

  it('shows Add all suggested after generate and forwards seeds on click', async () => {
    const user = userEvent.setup();
    const onClose = jest.fn();
    const onAcceptAllPropertySuggestions = jest.fn();

    render(
      <AiPropertySuggestionsDialog
        open
        onClose={onClose}
        tenantId={null}
        projectId="p1"
        versionId={null}
        existingClasses={[]}
        existingProperties={[]}
        studioContext={EMPTY_CHAT_STUDIO_CONTEXT}
        onCreatePropertyFromSuggestion={jest.fn()}
        onAcceptAllPropertySuggestions={onAcceptAllPropertySuggestions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('ai-property-suggestions-model')).not.toBeDisabled();
    });

    await user.type(screen.getByTestId('ai-property-suggestions-prompt'), 'need a field');

    await user.click(screen.getByTestId('ai-property-suggestions-generate'));

    const addAll = await screen.findByTestId('ai-property-suggestions-add-all-suggested');
    expect(addAll).toHaveTextContent('Add all suggested');

    await user.click(addAll);

    expect(onAcceptAllPropertySuggestions).toHaveBeenCalledTimes(1);
    const seeds = onAcceptAllPropertySuggestions.mock.calls[0][0] as { name: string }[];
    expect(seeds).toHaveLength(1);
    expect(seeds[0].name).toBe('alpha');
    expect(onClose).toHaveBeenCalled();
  });
});
