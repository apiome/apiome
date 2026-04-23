/**
 * Tests for the conversation history browse / search surface (#261).
 *
 * Pins the row rendering, scope-agnostic substring search, and the wiring
 * for the open / delete / clear-all callbacks the chat shell hands in.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ConversationHistoryPanel } from '../../src/app/ade/studio/components/chatbot/ConversationHistoryPanel';
import type { StoredConversation } from '../../src/app/ade/studio/components/chatbot/conversation-store';
import type { ChatMessage } from '../../src/app/ade/studio/components/chatbot/types';

function user(content: string, id = `u-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'user', content };
}

function assistant(content: string, id = `a-${content.slice(0, 8)}`): ChatMessage {
  return { id, role: 'assistant', content };
}

function makeConversation(overrides: Partial<StoredConversation> = {}): StoredConversation {
  return {
    id: overrides.id ?? 'c-1',
    projectId: overrides.projectId ?? null,
    versionId: overrides.versionId ?? null,
    title: overrides.title ?? 'Sample',
    createdAt: overrides.createdAt ?? Date.now(),
    updatedAt: overrides.updatedAt ?? Date.now(),
    messages: overrides.messages ?? [user('hi'), assistant('hello')],
  };
}

describe('ConversationHistoryPanel', () => {
  it('renders the empty state when no conversations are persisted', () => {
    render(
      <ConversationHistoryPanel
        conversations={[]}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByTestId('studio-ai-chat-history-empty')).toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chat-history-clear-all')).toBeDisabled();
  });

  it('lists each conversation with its title and message count', () => {
    const conversations = [
      makeConversation({ id: 'a', title: 'Cart schema', messages: [user('hi'), assistant('there')] }),
      makeConversation({ id: 'b', title: 'Auth design', messages: [user('login'), assistant('ok'), user('next')] }),
    ];
    render(
      <ConversationHistoryPanel
        conversations={conversations}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    const rows = screen.getAllByTestId('studio-ai-chat-history-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Cart schema')).toBeInTheDocument();
    expect(within(rows[0]).getByText(/2 messages/)).toBeInTheDocument();
    expect(within(rows[1]).getByText('Auth design')).toBeInTheDocument();
    expect(within(rows[1]).getByText(/3 messages/)).toBeInTheDocument();
  });

  it('marks the active conversation visually', () => {
    const conversations = [
      makeConversation({ id: 'a', title: 'first' }),
      makeConversation({ id: 'b', title: 'second' }),
    ];
    render(
      <ConversationHistoryPanel
        conversations={conversations}
        activeId="b"
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    const rows = screen.getAllByTestId('studio-ai-chat-history-row');
    expect(rows[0]).toHaveAttribute('data-active', 'false');
    expect(rows[1]).toHaveAttribute('data-active', 'true');
  });

  it('filters conversations by title and message content as the user types', () => {
    const conversations = [
      makeConversation({
        id: 'a',
        title: 'Cart schema',
        messages: [user('design cart'), assistant('done')],
      }),
      makeConversation({
        id: 'b',
        title: 'Auth design',
        messages: [user('login flow'), assistant('use OAuth')],
      }),
      makeConversation({
        id: 'c',
        title: 'Catalog',
        messages: [user('list products'), assistant('SKU map')],
      }),
    ];
    render(
      <ConversationHistoryPanel
        conversations={conversations}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );

    const search = screen.getByTestId('studio-ai-chat-history-search');
    fireEvent.change(search, { target: { value: 'oauth' } });
    const rows = screen.getAllByTestId('studio-ai-chat-history-row');
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText('Auth design')).toBeInTheDocument();
  });

  it('shows a no-match state when the search term has no hits', () => {
    render(
      <ConversationHistoryPanel
        conversations={[makeConversation({ id: 'a', title: 'Cart' })]}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    fireEvent.change(screen.getByTestId('studio-ai-chat-history-search'), {
      target: { value: 'zzz' },
    });
    expect(screen.getByTestId('studio-ai-chat-history-no-matches')).toBeInTheDocument();
  });

  it('invokes onOpen with the conversation id when a row is clicked', () => {
    const onOpen = jest.fn();
    const conversations = [makeConversation({ id: 'pick-me', title: 'pick me' })];
    render(
      <ConversationHistoryPanel
        conversations={conversations}
        onOpen={onOpen}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-history-open'));
    expect(onOpen).toHaveBeenCalledWith('pick-me');
  });

  it('invokes onDelete with the conversation id when the row delete button is clicked', () => {
    const onDelete = jest.fn();
    const conversations = [makeConversation({ id: 'doomed', title: 'doomed' })];
    render(
      <ConversationHistoryPanel
        conversations={conversations}
        onOpen={jest.fn()}
        onDelete={onDelete}
        onClearAll={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-history-delete'));
    expect(onDelete).toHaveBeenCalledWith('doomed');
  });

  it('invokes onClearAll when the clear-all button is pressed', () => {
    const onClearAll = jest.fn();
    render(
      <ConversationHistoryPanel
        conversations={[makeConversation({ id: 'x' })]}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={onClearAll}
        onClose={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-history-clear-all'));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it('invokes onClose when the back button is pressed', () => {
    const onClose = jest.fn();
    render(
      <ConversationHistoryPanel
        conversations={[]}
        onOpen={jest.fn()}
        onDelete={jest.fn()}
        onClearAll={jest.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-history-back'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
