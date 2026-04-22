/**
 * Tests for the chat conversation orchestrator (#258).
 *
 * Covers the end-to-end flow exercised by the StudioAiChatbot panel:
 *   - Empty-state suggestions seed the conversation
 *   - Sending a prompt creates user + pending-assistant bubbles
 *   - Assistant reply replaces the pending bubble and reveals actions
 *   - Regenerate re-uses the last user prompt and replaces the prior reply
 *   - Thumbs up/down feedback toggles
 *   - Composer is disabled while the assistant is working
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ChatConversation } from '../../src/app/ade/studio/components/chatbot/ChatConversation';
import type { ChatSendFn } from '../../src/app/ade/studio/components/chatbot/types';

function createDeferredResponder(): {
  responder: ChatSendFn;
  resolveWith: (text: string) => void;
  calls: Array<{ prompt: string; isRegenerate: boolean }>;
} {
  const calls: Array<{ prompt: string; isRegenerate: boolean }> = [];
  let pendingResolve: ((text: string) => void) | null = null;
  const responder: ChatSendFn = ({ prompt, isRegenerate }) => {
    calls.push({ prompt, isRegenerate });
    return new Promise<string>((resolve) => {
      pendingResolve = resolve;
    });
  };
  return {
    responder,
    calls,
    resolveWith(text: string) {
      const fn = pendingResolve;
      pendingResolve = null;
      if (fn) fn(text);
    },
  };
}

beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
});

describe('ChatConversation', () => {
  it('renders the empty state with prompt suggestions', () => {
    render(<ChatConversation />);
    const suggestions = screen.getAllByTestId('studio-ai-chat-suggestion');
    expect(suggestions.length).toBeGreaterThanOrEqual(3);
  });

  it('clicking a suggestion seeds the conversation as a user message', async () => {
    const { responder, calls, resolveWith } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} />);

    const suggestions = screen.getAllByTestId('studio-ai-chat-suggestion');
    const text = suggestions[0].textContent ?? '';
    fireEvent.click(suggestions[0]);

    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(calls[0].prompt).toBe(text);

    const bubbles = screen.getAllByTestId('studio-ai-chat-bubble');
    expect(bubbles[0]).toHaveAttribute('data-role', 'user');
    expect(bubbles[1]).toHaveAttribute('data-role', 'assistant');
    expect(within(bubbles[1]).getByTestId('studio-ai-chat-typing')).toBeInTheDocument();

    await act(async () => {
      resolveWith('All set.');
    });
    expect(within(screen.getAllByTestId('studio-ai-chat-bubble')[1]).queryByTestId('studio-ai-chat-typing')).not.toBeInTheDocument();
  });

  it('disables the composer while the assistant is responding and re-enables it after', async () => {
    const { responder, resolveWith } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} />);

    const input = screen.getByTestId('studio-ai-chat-input');
    fireEvent.change(input, { target: { value: 'hello' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    await waitFor(() => {
      expect(screen.getByTestId('studio-ai-chat-input')).toBeDisabled();
    });

    await act(async () => {
      resolveWith('hi back');
    });

    expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
  });

  it('Regenerate re-uses the last user prompt, drops the prior reply, and flags isRegenerate', async () => {
    const { responder, calls, resolveWith } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'first ask' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    await waitFor(() => expect(calls).toHaveLength(1));
    await act(async () => {
      resolveWith('first reply');
    });

    fireEvent.click(screen.getByTestId('studio-ai-chat-regenerate'));
    await waitFor(() => expect(calls).toHaveLength(2));

    expect(calls[1]).toEqual({ prompt: 'first ask', isRegenerate: true });

    // While regenerating, the visible assistant bubble shows the typing indicator
    // and the previous "first reply" content has been removed from the transcript.
    expect(screen.queryByText('first reply')).not.toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chat-typing')).toBeInTheDocument();

    await act(async () => {
      resolveWith('second reply');
    });
    expect(screen.getByText('second reply')).toBeInTheDocument();
  });

  it('toggles thumbs up/down feedback on assistant messages', async () => {
    const { responder, resolveWith } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'q' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    await waitFor(() => expect(screen.getByTestId('studio-ai-chat-typing')).toBeInTheDocument());
    await act(async () => {
      resolveWith('answer');
    });

    const up = screen.getByTestId('studio-ai-chat-thumbs-up');
    expect(up).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(up);
    expect(screen.getByTestId('studio-ai-chat-thumbs-up')).toHaveAttribute('aria-pressed', 'true');
    // Clicking the same button again clears the feedback.
    fireEvent.click(screen.getByTestId('studio-ai-chat-thumbs-up'));
    expect(screen.getByTestId('studio-ai-chat-thumbs-up')).toHaveAttribute('aria-pressed', 'false');
  });

  it('falls back to a friendly error reply when the responder throws', async () => {
    const responder: ChatSendFn = () => Promise.reject(new Error('network down'));
    render(<ChatConversation onSendMessage={responder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'q' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    await waitFor(() => {
      expect(screen.getByText(/the assistant could not respond/i)).toBeInTheDocument();
    });
    expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
  });

  it('forwards the import callback when the assistant returns an OpenAPI spec', async () => {
    const onImportSpec = jest.fn();
    const responder: ChatSendFn = () =>
      Promise.resolve(
        [
          'Spec ready:',
          '',
          '```json',
          JSON.stringify({
            openapi: '3.1.0',
            info: { title: 'Sample', version: '0.1.0' },
            components: { schemas: {} },
          }),
          '```',
        ].join('\n')
      );

    render(<ChatConversation onSendMessage={responder} onImportSpec={onImportSpec} />);
    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'spec' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    const importButton = await screen.findByTestId('studio-ai-chat-import-spec-0');
    fireEvent.click(importButton);
    expect(onImportSpec).toHaveBeenCalledTimes(1);
    expect(onImportSpec.mock.calls[0][0].version).toBe('3.1.0');
  });
});
