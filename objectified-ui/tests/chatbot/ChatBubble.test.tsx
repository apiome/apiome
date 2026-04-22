/**
 * Tests for the chat bubble (#258).
 *
 * Covers:
 *   - Role-based styling and alignment (user vs assistant)
 *   - Typing indicator while a message is pending
 *   - Regenerate button (only on the latest assistant message)
 *   - Thumbs up / down feedback toggling
 *   - OpenAPI import affordance for ```json``` specs
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ChatBubble } from '../../src/app/ade/studio/components/chatbot/ChatBubble';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

const userMessage: ChatMessage = { id: 'u1', role: 'user', content: 'Design a User class please' };
const assistantMessage: ChatMessage = {
  id: 'a1',
  role: 'assistant',
  content: 'Sure, here is a sketch.',
};
const pendingAssistant: ChatMessage = {
  id: 'a-pending',
  role: 'assistant',
  content: '',
  pending: true,
};
const specMessage: ChatMessage = {
  id: 'a-spec',
  role: 'assistant',
  content: [
    'Here you go:',
    '',
    '```json',
    JSON.stringify({ openapi: '3.1.0', info: { title: 'X', version: '1' }, components: { schemas: {} } }),
    '```',
  ].join('\n'),
};

describe('ChatBubble', () => {
  it('renders user content with the user role and right alignment', () => {
    render(<ChatBubble message={userMessage} />);
    const bubble = screen.getByTestId('studio-ai-chat-bubble');
    expect(bubble).toHaveAttribute('data-role', 'user');
    expect(bubble.className).toContain('justify-end');
    expect(bubble.textContent).toContain('Design a User class please');
  });

  it('renders assistant content with the assistant role and left alignment', () => {
    render(<ChatBubble message={assistantMessage} />);
    const bubble = screen.getByTestId('studio-ai-chat-bubble');
    expect(bubble).toHaveAttribute('data-role', 'assistant');
    expect(bubble.className).toContain('justify-start');
    expect(bubble.textContent).toContain('Sure, here is a sketch.');
  });

  it('shows the typing indicator while an assistant message is pending', () => {
    render(<ChatBubble message={pendingAssistant} />);
    expect(screen.getByTestId('studio-ai-chat-typing')).toBeInTheDocument();
    // Pending bubbles should not expose actions.
    expect(screen.queryByTestId('studio-ai-chat-regenerate')).not.toBeInTheDocument();
  });

  it('only renders Regenerate on the latest assistant message', () => {
    const onRegenerate = jest.fn();
    const { rerender } = render(
      <ChatBubble message={assistantMessage} isLatestAssistant onRegenerate={onRegenerate} />
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-regenerate'));
    expect(onRegenerate).toHaveBeenCalledTimes(1);

    rerender(
      <ChatBubble message={assistantMessage} isLatestAssistant={false} onRegenerate={onRegenerate} />
    );
    expect(screen.queryByTestId('studio-ai-chat-regenerate')).not.toBeInTheDocument();
  });

  it('emits feedback events when thumbs up / down are clicked', () => {
    const onFeedback = jest.fn();
    render(<ChatBubble message={assistantMessage} onFeedback={onFeedback} />);
    fireEvent.click(screen.getByTestId('studio-ai-chat-thumbs-up'));
    fireEvent.click(screen.getByTestId('studio-ai-chat-thumbs-down'));
    expect(onFeedback).toHaveBeenNthCalledWith(1, 'up');
    expect(onFeedback).toHaveBeenNthCalledWith(2, 'down');
  });

  it('marks the active feedback button via aria-pressed', () => {
    render(
      <ChatBubble
        message={{ ...assistantMessage, feedback: 'up' }}
        onFeedback={() => undefined}
      />
    );
    expect(screen.getByTestId('studio-ai-chat-thumbs-up')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('studio-ai-chat-thumbs-down')).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders an Import button when the message contains an OpenAPI spec', () => {
    const onImportSpec = jest.fn();
    render(<ChatBubble message={specMessage} onImportSpec={onImportSpec} />);
    const importButton = screen.getByTestId('studio-ai-chat-import-spec-0');
    expect(importButton).toHaveTextContent(/Import OpenAPI spec/i);
    fireEvent.click(importButton);
    expect(onImportSpec).toHaveBeenCalledTimes(1);
    expect(onImportSpec.mock.calls[0][0].version).toBe('3.1.0');
  });

  it('does not render an Import button when onImportSpec is not provided', () => {
    render(<ChatBubble message={specMessage} />);
    expect(screen.queryByTestId('studio-ai-chat-import-spec-0')).not.toBeInTheDocument();
  });

  it('does not render an Import button on user messages or assistant text without a spec', () => {
    const { rerender } = render(<ChatBubble message={userMessage} onImportSpec={() => undefined} />);
    expect(screen.queryByTestId('studio-ai-chat-import-spec-0')).not.toBeInTheDocument();

    rerender(<ChatBubble message={assistantMessage} onImportSpec={() => undefined} />);
    expect(screen.queryByTestId('studio-ai-chat-import-spec-0')).not.toBeInTheDocument();
  });
});
