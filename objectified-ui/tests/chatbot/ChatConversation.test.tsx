/**
 * Tests for the chat conversation orchestrator (#258, #259, #260, #261).
 *
 * Covers the end-to-end flow exercised by the StudioAiChatbot panel:
 *   - Empty-state suggestions seed the conversation
 *   - Sending a prompt creates user + pending-assistant bubbles
 *   - Assistant reply replaces the pending bubble and reveals actions
 *   - Regenerate re-uses the last user prompt and replaces the prior reply
 *   - Thumbs up/down feedback toggles
 *   - Composer is disabled while the assistant is working
 *   - The studio context snapshot rides on every send (#259)
 *   - Multi-turn follow-ups carry the full transcript and refine prior
 *     specs through the chat surface (#260)
 *   - Conversation history actions: persist per scope, browse, search,
 *     export markdown, clear current, clear all (#261)
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ChatConversation } from '../../src/app/ade/studio/components/chatbot/ChatConversation';
import type { ChatStudioContext } from '../../src/app/ade/studio/components/chatbot/chat-context';
import {
  createConversationStore,
  createMemoryConversationStorage,
  type ConversationStore,
  type StoredConversation,
} from '../../src/app/ade/studio/components/chatbot/conversation-store';
import type { ChatMessage, ChatSendFn } from '../../src/app/ade/studio/components/chatbot/types';

function makeMemoryStore(initial: StoredConversation[] = []): ConversationStore {
  return createConversationStore(createMemoryConversationStorage(initial));
}

function neverConfirm(): boolean {
  return false;
}
function alwaysConfirm(): boolean {
  return true;
}

type ResponderCall = {
  prompt: string;
  isRegenerate: boolean;
  studioContext?: ChatStudioContext;
};

function createDeferredResponder(): {
  responder: ChatSendFn;
  resolveWith: (text: string) => void;
  calls: ResponderCall[];
} {
  const calls: ResponderCall[] = [];
  let pendingResolve: ((text: string) => void) | null = null;
  const responder: ChatSendFn = ({ prompt, isRegenerate, studioContext }) => {
    calls.push({ prompt, isRegenerate, studioContext });
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
  // Conversations auto-persist to localStorage in production; reset between
  // tests so each run starts from a clean slate without restoring stale
  // history into the chat surface.
  if (typeof window !== 'undefined' && window.localStorage) {
    window.localStorage.clear();
  }
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

  it('does not render the context chip when no studio context is supplied', () => {
    render(<ChatConversation />);
    expect(screen.queryByTestId('studio-ai-chat-context-chip')).not.toBeInTheDocument();
  });

  it('renders the context chip when a non-empty studio context is supplied', () => {
    const studioContext: ChatStudioContext = {
      project: { id: 'p', name: 'Acme' },
      version: { id: 'v', label: 'v1.0' },
      classes: [{ id: 'c', name: 'User' }],
      properties: [],
      selectedClassIds: [],
    };
    render(<ChatConversation studioContext={studioContext} />);
    expect(screen.getByTestId('studio-ai-chat-context-chip')).toBeInTheDocument();
  });

  it('forwards the studio context snapshot to the responder on each send', async () => {
    const studioContext: ChatStudioContext = {
      project: { id: 'p', name: 'Acme' },
      version: { id: 'v', label: 'v1.0' },
      classes: [{ id: 'c', name: 'User' }],
      properties: [],
      selectedClassIds: ['c'],
    };
    const { responder, calls, resolveWith } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} studioContext={studioContext} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'hi' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].studioContext).toEqual(studioContext);

    await act(async () => {
      resolveWith('ok');
    });
  });

  it('captures the latest studio context snapshot at send time, not at mount time', async () => {
    const initial: ChatStudioContext = {
      project: { id: 'p', name: 'Acme' },
      version: null,
      classes: [],
      properties: [],
      selectedClassIds: [],
    };
    const updated: ChatStudioContext = {
      ...initial,
      version: { id: 'v', label: 'v2.0' },
      selectedClassIds: ['c'],
    };
    const { responder, calls, resolveWith } = createDeferredResponder();
    const { rerender } = render(
      <ChatConversation onSendMessage={responder} studioContext={initial} />
    );

    rerender(<ChatConversation onSendMessage={responder} studioContext={updated} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'hi' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].studioContext).toEqual(updated);

    await act(async () => {
      resolveWith('ok');
    });
  });

  it('passes the full prior transcript to the responder on follow-up turns (#260)', async () => {
    const calls: ResponderCall[] = [];
    const transcripts: ChatMessage[][] = [];
    const responder: ChatSendFn = ({ messages, prompt, isRegenerate, studioContext }) => {
      calls.push({ prompt, isRegenerate, studioContext });
      transcripts.push(messages);
      return Promise.resolve(`echo: ${prompt}`);
    };
    render(<ChatConversation onSendMessage={responder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'first ask' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    await waitFor(() => expect(calls).toHaveLength(1));

    await waitFor(() => {
      expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
    });

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'follow up' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    await waitFor(() => expect(calls).toHaveLength(2));

    // First call only sees the just-sent user turn.
    expect(transcripts[0]).toHaveLength(1);
    expect(transcripts[0][0]).toMatchObject({ role: 'user', content: 'first ask' });

    // Second call sees the full prior transcript: user + assistant + new user.
    expect(transcripts[1]).toHaveLength(3);
    expect(transcripts[1].map((m) => m.role)).toEqual(['user', 'assistant', 'user']);
    expect(transcripts[1][1].content).toBe('echo: first ask');
    expect(transcripts[1][2].content).toBe('follow up');
  });

  it('lets the user iteratively refine a previously imported spec (#260)', async () => {
    // Drives the actual demo responder through the chat shell so the
    // multi-turn refinement path is exercised end-to-end.
    const { createDemoChatResponder } = await import('../../src/app/ade/studio/components/chatbot/demo-responder');
    const responder = createDemoChatResponder();
    const onImportSpec = jest.fn();
    render(<ChatConversation onSendMessage={responder} onImportSpec={onImportSpec} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'sketch a schema' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    await waitFor(() => expect(screen.getByTestId('studio-ai-chat-import-spec-0')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled());

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'add a phone field' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    // The refinement reply re-ships an importable spec — wait on the second
    // import button so we know both turns made it through the responder.
    await waitFor(() => expect(screen.getAllByTestId(/studio-ai-chat-import-spec-/)).toHaveLength(1));
    const bubbles = screen.getAllByTestId('studio-ai-chat-bubble');
    const assistantBubbles = bubbles.filter((b) => b.getAttribute('data-role') === 'assistant');
    expect(assistantBubbles).toHaveLength(2);
    // The second assistant reply is the refinement: it must include the
    // refined spec containing a `phone` property as JSON text.
    expect(assistantBubbles[1].textContent ?? '').toMatch(/"phone"/);
  });

  describe('conversation history actions (#261)', () => {
    it('renders the toolbar with new / history / export / clear actions', () => {
      render(
        <ChatConversation
          conversationStore={makeMemoryStore()}
          restoreLastConversation={false}
        />,
      );
      expect(screen.getByTestId('studio-ai-chat-toolbar')).toBeInTheDocument();
      expect(screen.getByTestId('studio-ai-chat-new')).toBeInTheDocument();
      expect(screen.getByTestId('studio-ai-chat-history')).toBeInTheDocument();
      expect(screen.getByTestId('studio-ai-chat-export')).toBeDisabled();
      expect(screen.getByTestId('studio-ai-chat-clear')).toBeDisabled();
    });

    it('persists each conversation under the current scope as turns settle', async () => {
      const store = makeMemoryStore();
      const studioContext: ChatStudioContext = {
        project: { id: 'proj-1', name: 'Acme' },
        version: { id: 'ver-1', label: 'v1' },
        classes: [],
        properties: [],
        selectedClassIds: [],
      };
      const responder: ChatSendFn = ({ prompt }) => Promise.resolve(`reply: ${prompt}`);
      render(
        <ChatConversation
          onSendMessage={responder}
          studioContext={studioContext}
          conversationStore={store}
          restoreLastConversation={false}
        />,
      );

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'design a cart' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

      await waitFor(() => expect(store.list()).toHaveLength(1));
      const stored = store.list()[0];
      expect(stored.projectId).toBe('proj-1');
      expect(stored.versionId).toBe('ver-1');
      expect(stored.title).toBe('design a cart');
      expect(stored.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
    });

    it('restores the most recent persisted conversation in the active scope on mount', async () => {
      const studioContext: ChatStudioContext = {
        project: { id: 'proj-1', name: 'Acme' },
        version: null,
        classes: [],
        properties: [],
        selectedClassIds: [],
      };
      const store = makeMemoryStore([
        {
          id: 'conv-keep',
          projectId: 'proj-1',
          versionId: null,
          title: 'Keep me',
          createdAt: 100,
          updatedAt: 200,
          messages: [
            { id: 'u1', role: 'user', content: 'remembered prompt' },
            { id: 'a1', role: 'assistant', content: 'remembered reply' },
          ],
        },
      ]);
      render(
        <ChatConversation
          studioContext={studioContext}
          conversationStore={store}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('remembered prompt')).toBeInTheDocument();
      });
      expect(screen.getByText('remembered reply')).toBeInTheDocument();
    });

    it('opens the history surface, lists prior conversations, and switches active when one is opened', async () => {
      const store = makeMemoryStore([
        {
          id: 'conv-old',
          projectId: null,
          versionId: null,
          title: 'older convo',
          createdAt: 100,
          updatedAt: 100,
          messages: [
            { id: 'u', role: 'user', content: 'older prompt' },
            { id: 'a', role: 'assistant', content: 'older reply' },
          ],
        },
        {
          id: 'conv-new',
          projectId: null,
          versionId: null,
          title: 'newer convo',
          createdAt: 200,
          updatedAt: 200,
          messages: [
            { id: 'u', role: 'user', content: 'newer prompt' },
            { id: 'a', role: 'assistant', content: 'newer reply' },
          ],
        },
      ]);
      render(
        <ChatConversation
          conversationStore={store}
          restoreLastConversation={false}
        />,
      );

      fireEvent.click(screen.getByTestId('studio-ai-chat-history'));
      const rows = screen.getAllByTestId('studio-ai-chat-history-row');
      expect(rows).toHaveLength(2);
      expect(within(rows[0]).getByText('newer convo')).toBeInTheDocument();
      expect(within(rows[1]).getByText('older convo')).toBeInTheDocument();

      fireEvent.click(within(rows[1]).getByTestId('studio-ai-chat-history-open'));

      await waitFor(() => {
        expect(screen.getByText('older prompt')).toBeInTheDocument();
      });
      expect(screen.getByText('older reply')).toBeInTheDocument();
    });

    it('filters the history list with the search box', () => {
      const store = makeMemoryStore([
        {
          id: 'a',
          projectId: null,
          versionId: null,
          title: 'Cart schema',
          createdAt: 1,
          updatedAt: 2,
          messages: [{ id: 'u', role: 'user', content: 'design cart' }],
        },
        {
          id: 'b',
          projectId: null,
          versionId: null,
          title: 'Auth design',
          createdAt: 1,
          updatedAt: 3,
          messages: [{ id: 'u', role: 'user', content: 'login flow' }],
        },
      ]);
      render(
        <ChatConversation
          conversationStore={store}
          restoreLastConversation={false}
        />,
      );

      fireEvent.click(screen.getByTestId('studio-ai-chat-history'));
      fireEvent.change(screen.getByTestId('studio-ai-chat-history-search'), {
        target: { value: 'cart' },
      });
      const rows = screen.getAllByTestId('studio-ai-chat-history-row');
      expect(rows).toHaveLength(1);
      expect(within(rows[0]).getByText('Cart schema')).toBeInTheDocument();
    });

    it('exports the active conversation as markdown via the supplied handler', async () => {
      const responder: ChatSendFn = ({ prompt }) => Promise.resolve(`reply: ${prompt}`);
      const store = makeMemoryStore();
      const onExportConversation = jest.fn();
      render(
        <ChatConversation
          onSendMessage={responder}
          conversationStore={store}
          restoreLastConversation={false}
          onExportConversation={onExportConversation}
        />,
      );

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'design a cart' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
      await waitFor(() => expect(screen.getByTestId('studio-ai-chat-export')).not.toBeDisabled());

      fireEvent.click(screen.getByTestId('studio-ai-chat-export'));
      expect(onExportConversation).toHaveBeenCalledTimes(1);
      const arg = onExportConversation.mock.calls[0][0] as { filename: string; markdown: string };
      expect(arg.filename).toMatch(/^studio-ai-design-a-cart-\d{4}-\d{2}-\d{2}\.md$/);
      expect(arg.markdown).toMatch(/^# design a cart/);
      expect(arg.markdown).toMatch(/## User/);
      expect(arg.markdown).toMatch(/design a cart/);
      expect(arg.markdown).toMatch(/reply: design a cart/);
    });

    it('clears the active conversation, removes it from history, and resets the view', async () => {
      const responder: ChatSendFn = ({ prompt }) => Promise.resolve(`reply: ${prompt}`);
      const store = makeMemoryStore();
      render(
        <ChatConversation
          onSendMessage={responder}
          conversationStore={store}
          restoreLastConversation={false}
          confirmAction={alwaysConfirm}
        />,
      );

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'something to clear' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
      await waitFor(() => expect(store.list()).toHaveLength(1));

      fireEvent.click(screen.getByTestId('studio-ai-chat-clear'));

      expect(store.list()).toHaveLength(0);
      expect(screen.queryByText('something to clear')).not.toBeInTheDocument();
      expect(screen.getAllByTestId('studio-ai-chat-suggestion').length).toBeGreaterThan(0);
    });

    it('does not clear when the confirmation is declined', async () => {
      const responder: ChatSendFn = ({ prompt }) => Promise.resolve(`reply: ${prompt}`);
      const store = makeMemoryStore();
      render(
        <ChatConversation
          onSendMessage={responder}
          conversationStore={store}
          restoreLastConversation={false}
          confirmAction={neverConfirm}
        />,
      );

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'keep me' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
      await waitFor(() => expect(store.list()).toHaveLength(1));

      fireEvent.click(screen.getByTestId('studio-ai-chat-clear'));

      expect(store.list()).toHaveLength(1);
      expect(screen.getByText('keep me')).toBeInTheDocument();
    });

    it('clear-all from the history surface wipes every conversation in scope', async () => {
      const studioContext: ChatStudioContext = {
        project: { id: 'proj-1', name: 'Acme' },
        version: null,
        classes: [],
        properties: [],
        selectedClassIds: [],
      };
      const store = makeMemoryStore([
        {
          id: 'in-scope',
          projectId: 'proj-1',
          versionId: null,
          title: 'in scope',
          createdAt: 1,
          updatedAt: 1,
          messages: [{ id: 'u', role: 'user', content: 'in scope prompt' }],
        },
        {
          id: 'other-scope',
          projectId: 'proj-2',
          versionId: null,
          title: 'other scope',
          createdAt: 1,
          updatedAt: 1,
          messages: [{ id: 'u', role: 'user', content: 'other scope prompt' }],
        },
      ]);
      render(
        <ChatConversation
          studioContext={studioContext}
          conversationStore={store}
          confirmAction={alwaysConfirm}
        />,
      );

      fireEvent.click(screen.getByTestId('studio-ai-chat-history'));
      fireEvent.click(screen.getByTestId('studio-ai-chat-history-clear-all'));

      expect(store.list({ projectId: 'proj-1', versionId: null })).toHaveLength(0);
      expect(store.list({ projectId: 'proj-2', versionId: null })).toHaveLength(1);
    });

    it('starting a New conversation hides previous bubbles but keeps the prior entry in history', async () => {
      const responder: ChatSendFn = ({ prompt }) => Promise.resolve(`reply: ${prompt}`);
      const store = makeMemoryStore();
      render(
        <ChatConversation
          onSendMessage={responder}
          conversationStore={store}
          restoreLastConversation={false}
        />,
      );

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'first thread' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
      await waitFor(() => expect(store.list()).toHaveLength(1));

      fireEvent.click(screen.getByTestId('studio-ai-chat-new'));

      expect(screen.queryByText('first thread')).not.toBeInTheDocument();
      expect(screen.getAllByTestId('studio-ai-chat-suggestion').length).toBeGreaterThan(0);
      expect(store.list()).toHaveLength(1);
    });

    it('deleting a conversation from history removes it and wipes the active view if it was open', async () => {
      const store = makeMemoryStore([
        {
          id: 'conv-1',
          projectId: null,
          versionId: null,
          title: 'doomed',
          createdAt: 1,
          updatedAt: 1,
          messages: [{ id: 'u', role: 'user', content: 'doomed prompt' }],
        },
      ]);
      render(<ChatConversation conversationStore={store} confirmAction={alwaysConfirm} />);

      await waitFor(() => {
        expect(screen.getByText('doomed prompt')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('studio-ai-chat-history'));
      fireEvent.click(screen.getByTestId('studio-ai-chat-history-delete'));

      expect(store.list()).toHaveLength(0);
      // After deletion the history surface shows the empty state and the
      // chat returns to the empty-conversation state.
      expect(screen.getByTestId('studio-ai-chat-history-empty')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('studio-ai-chat-history-back'));
      expect(screen.getAllByTestId('studio-ai-chat-suggestion').length).toBeGreaterThan(0);
    });
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
