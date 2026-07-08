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
 *   - Indeterminate progress bar while the assistant is generating (#523)
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
import {
  EMPTY_CHAT_STUDIO_CONTEXT,
  type ChatStudioContext,
} from '../../src/app/ade/studio/components/chatbot/chat-context';
import {
  createConversationStore,
  createMemoryConversationStorage,
  type ConversationStore,
  type StoredConversation,
} from '../../src/app/ade/studio/components/chatbot/conversation-store';
import { CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY } from '../../src/app/ade/studio/components/chatbot/ollama-model-defaults';
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
  let abortCleanup: (() => void) | null = null;

  const responder: ChatSendFn = ({ prompt, isRegenerate, studioContext, signal }) => {
    calls.push({ prompt, isRegenerate, studioContext });
    abortCleanup?.();
    abortCleanup = null;

    return new Promise<string>((resolve, reject) => {
      const onAbort = () => {
        pendingResolve = null;
        abortCleanup?.();
        abortCleanup = null;
        reject(new DOMException('The operation was aborted.', 'AbortError'));
      };

      if (signal) {
        if (signal.aborted) {
          queueMicrotask(onAbort);
          return;
        }
        signal.addEventListener('abort', onAbort, { once: true });
        const s = signal;
        abortCleanup = () => s.removeEventListener('abort', onAbort);
      }

      pendingResolve = (text: string) => {
        abortCleanup?.();
        abortCleanup = null;
        resolve(text);
      };
    });
  };
  return {
    responder,
    calls,
    resolveWith(text: string) {
      abortCleanup?.();
      abortCleanup = null;
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

  it('shows the four NL→schema example prompts on the empty state (#268)', () => {
    render(<ChatConversation />);
    const labels = screen.getAllByTestId('studio-ai-chat-suggestion').map((el) => el.textContent?.trim() ?? '');
    expect(labels).toEqual([
      'Create a User class with email, password hash, created date, and roles array',
      'I need an e-commerce order with line items, shipping address, and payment info',
      'Generate a blog post schema with author reference, tags, and comments',
      'Create a REST API for managing a todo list application',
    ]);
  });

  it('shows workspace best-practice tips when project domainCategory signals e-commerce (#615)', () => {
    const studioContext: ChatStudioContext = {
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      project: { id: 'p1', name: 'Shop', domainCategory: 'ecommerce' },
      version: { id: 'v1', label: 'v1' },
      classes: [],
      properties: [],
      selectedClassIds: [],
    };
    render(<ChatConversation restoreLastConversation={false} studioContext={studioContext} />);
    expect(screen.getByTestId('studio-ai-chat-best-practice-tips')).toHaveTextContent('inventory tracking');
    expect(screen.getByTestId('studio-ai-chat-best-practice-tips')).toHaveTextContent('processor tokens');
  });

  it('shows auth-oriented tips when class names suggest tokens or sessions (#615)', () => {
    const studioContext: ChatStudioContext = {
      ...EMPTY_CHAT_STUDIO_CONTEXT,
      project: { id: 'p1', name: 'Auth svc' },
      version: { id: 'v1', label: 'v1' },
      classes: [{ id: 'c1', name: 'RefreshToken' }],
      properties: [],
      selectedClassIds: [],
    };
    render(<ChatConversation restoreLastConversation={false} studioContext={studioContext} />);
    expect(screen.getByTestId('studio-ai-chat-best-practice-tips')).toHaveTextContent('refresh token');
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
      expect(screen.getByTestId('studio-ai-chat-generation-progress')).toBeInTheDocument();
    });

    await act(async () => {
      resolveWith('hi back');
    });

    expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
    expect(screen.queryByTestId('studio-ai-chat-generation-progress')).not.toBeInTheDocument();
  });

  it('Stop aborts an in-flight responder turn and leaves a stopped message (#522)', async () => {
    const { responder } = createDeferredResponder();
    render(<ChatConversation onSendMessage={responder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'hello' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    await waitFor(() => {
      expect(screen.getByTestId('studio-ai-chat-stop')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('studio-ai-chat-stop'));

    await waitFor(() => {
      expect(screen.getByText('Generation stopped.')).toBeInTheDocument();
    });
    expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
    expect(screen.queryByTestId('studio-ai-chat-stop')).not.toBeInTheDocument();
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
    const responder: ChatSendFn = async () => {
      throw new Error('network down');
    };
    render(
      <ChatConversation
        onSendMessage={responder}
        restoreLastConversation={false}
        conversationStore={makeMemoryStore()}
      />,
    );

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'q' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));
    });

    expect(
      await screen.findByText(/the assistant could not respond/i, {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('studio-ai-chat-input')).not.toBeDisabled();
    });
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
    expect(screen.getByTestId('studio-ai-chat-import-preview-dialog')).toBeInTheDocument();
    expect(onImportSpec).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('studio-ai-chat-import-preview-apply'));
    expect(onImportSpec).toHaveBeenCalledTimes(1);
    expect(onImportSpec.mock.calls[0][0].version).toBe('3.1.0');
  });

  it('closes the OpenAPI import preview without applying when Cancel is used (#519)', async () => {
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
    fireEvent.click(screen.getByTestId('studio-ai-chat-import-preview-cancel'));

    expect(onImportSpec).not.toHaveBeenCalled();
    expect(screen.queryByTestId('studio-ai-chat-import-preview-dialog')).not.toBeInTheDocument();
  });

  it('opens class create preview before the workspace action (#528)', async () => {
    const onChatWorkspaceAction = jest.fn();
    const responder: ChatSendFn = () =>
      Promise.resolve(
        [
          'Draft ready.',
          '',
          '**Create this class**',
          '',
          '```json',
          JSON.stringify({
            name: 'Widget',
            description: 'A widget',
            schema: { type: 'object', properties: { id: { type: 'string' } } },
          }),
          '```',
        ].join('\n')
      );

    render(<ChatConversation onSendMessage={responder} onChatWorkspaceAction={onChatWorkspaceAction} />);
    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'make class' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    const createBtn = await screen.findByTestId('studio-ai-chat-quick-create-class');
    fireEvent.click(createBtn);

    expect(screen.getByTestId('studio-ai-chat-class-create-preview-dialog')).toBeInTheDocument();
    expect(onChatWorkspaceAction).not.toHaveBeenCalled();

    const previewSchema = screen.getByTestId('studio-ai-chat-class-create-preview-json');
    expect(previewSchema.textContent).toContain('"type": "object"');
    expect(previewSchema.textContent).toContain('"id"');
    expect(previewSchema.textContent).not.toMatch(/"name"\s*:\s*"Widget"/);

    fireEvent.click(screen.getByTestId('studio-ai-chat-class-create-preview-confirm'));
    expect(onChatWorkspaceAction).toHaveBeenCalledTimes(1);
    expect(onChatWorkspaceAction.mock.calls[0][0]).toMatchObject({
      kind: 'create_class',
      assistantMarkdown: expect.stringContaining('Widget'),
    });
  });

  it('refreshes the class create preview after Ask assistant to refine (#532)', async () => {
    const onChatWorkspaceAction = jest.fn();
    let sendCount = 0;
    const responder: ChatSendFn = async (ctx) => {
      sendCount += 1;
      if (sendCount === 1) {
        return [
          'Draft ready.',
          '',
          '**Create this class**',
          '',
          '```json',
          JSON.stringify({
            name: 'Widget',
            description: 'A widget',
            schema: { type: 'object', properties: { id: { type: 'string' } } },
          }),
          '```',
        ].join('\n');
      }
      expect(ctx.ollamaTask).toBe('class_skeleton');
      if (ctx.prompt.includes('**Refine class draft**')) {
        return [
          'Updated.',
          '',
          '```json',
          JSON.stringify({
            name: 'Widget',
            description: 'A widget',
            schema: {
              type: 'object',
              properties: {
                id: { type: 'string' },
                phoneNumber: { type: 'string' },
              },
            },
          }),
          '```',
        ].join('\n');
      }
      return 'unexpected';
    };

    render(<ChatConversation onSendMessage={responder} onChatWorkspaceAction={onChatWorkspaceAction} />);
    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'make class' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    const createBtn = await screen.findByTestId('studio-ai-chat-quick-create-class');
    fireEvent.click(createBtn);

    const refineInput = screen.getByTestId('studio-ai-chat-class-create-preview-refine-input');
    fireEvent.change(refineInput, { target: { value: 'Add a phone number field' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-class-create-preview-refine-submit'));

    await waitFor(() => {
      const previewSchema = screen.getByTestId('studio-ai-chat-class-create-preview-json');
      expect(previewSchema.textContent).toContain('phoneNumber');
    });

    expect(sendCount).toBe(2);
    expect(onChatWorkspaceAction).not.toHaveBeenCalled();
  });

  it('updates the pending bubble incrementally via onStreamAccumulated and commits the final reply (#520)', async () => {
    let capturedStreamAccumulated: ((text: string) => void) | undefined;
    let pendingResolve: ((text: string) => void) | null = null;

    const streamingResponder: ChatSendFn = ({ onStreamAccumulated }) => {
      capturedStreamAccumulated = onStreamAccumulated;
      return new Promise<string>((resolve) => {
        pendingResolve = resolve;
      });
    };

    render(<ChatConversation onSendMessage={streamingResponder} />);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'stream me' } });
    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    // Pending bubble appears with the typing indicator (empty content)
    await waitFor(() => {
      expect(screen.getByTestId('studio-ai-chat-typing')).toBeInTheDocument();
    });

    // First streamed chunk — typing indicator gives way to partial content
    await act(async () => {
      capturedStreamAccumulated?.('Hello');
    });
    expect(screen.queryByTestId('studio-ai-chat-typing')).not.toBeInTheDocument();
    const bubbleAfterFirstChunk = screen
      .getAllByTestId('studio-ai-chat-bubble')
      .find((b) => b.getAttribute('data-role') === 'assistant')!;
    expect(bubbleAfterFirstChunk).toHaveTextContent('Hello');

    // Second chunk replaces the accumulated text (not double-appended)
    await act(async () => {
      capturedStreamAccumulated?.('Hello world');
    });
    const bubbleAfterSecondChunk = screen
      .getAllByTestId('studio-ai-chat-bubble')
      .find((b) => b.getAttribute('data-role') === 'assistant')!;
    expect(bubbleAfterSecondChunk).toHaveTextContent('Hello world');
    expect(bubbleAfterSecondChunk).not.toHaveTextContent('Hello Hello world');

    // Responder resolves — pending state clears and assistant actions appear
    await act(async () => {
      pendingResolve?.('Hello world!');
    });
    await waitFor(() => {
      expect(screen.queryByTestId('studio-ai-chat-typing')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Hello world!')).toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chat-regenerate')).toBeInTheDocument();
  });

  describe('Ollama transport (#265)', () => {
    const originalFetch = global.fetch;

    afterEach(() => {
      global.fetch = originalFetch;
    });

    function mockSseBody(lines: string[]) {
      const enc = new TextEncoder();
      const payload = enc.encode(lines.join(''));
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

    it('shows error message and Retry button when models endpoint returns non-OK HTTP', async () => {
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: false,
            status: 500,
            json: async () => ({ success: false, error: 'internal server error' }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });
      global.fetch = fetchMock;

      render(<ChatConversation ollamaTransport restoreLastConversation={false} />);

      await waitFor(() => {
        expect(screen.getByText('Could not reach Ollama. Using the offline assistant.')).toBeInTheDocument();
      });

      expect(screen.getByTestId('studio-ai-chat-ollama-retry-models')).toBeInTheDocument();
      expect(screen.queryByTestId('studio-ai-chat-ollama-model-select')).not.toBeInTheDocument();

      // Sending a message must use the demo responder, not the Ollama chat route.
      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'Hello' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

      // Wait for the user bubble to appear (state update is synchronous after send).
      await waitFor(() => {
        expect(screen.getAllByTestId('studio-ai-chat-bubble').length).toBeGreaterThan(0);
      });

      const chatCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/ollama/chat'));
      expect(chatCalls.length).toBe(0);
    });

    it('shows error message and Retry button when models endpoint returns {success:false}', async () => {
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ success: false, error: 'ollama unavailable' }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });
      global.fetch = fetchMock;

      render(<ChatConversation ollamaTransport restoreLastConversation={false} />);

      await waitFor(() => {
        expect(screen.getByText('Could not reach Ollama. Using the offline assistant.')).toBeInTheDocument();
      });

      expect(screen.getByTestId('studio-ai-chat-ollama-retry-models')).toBeInTheDocument();
      expect(screen.queryByTestId('studio-ai-chat-ollama-model-select')).not.toBeInTheDocument();

      // Sending a message must use the demo responder, not the Ollama chat route.
      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'Hello' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

      // Wait for the user bubble to appear (state update is synchronous after send).
      await waitFor(() => {
        expect(screen.getAllByTestId('studio-ai-chat-bubble').length).toBeGreaterThan(0);
      });

      const chatCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/ollama/chat'));
      expect(chatCalls.length).toBe(0);
    });

    it('loads models and shows the selector', async () => {
      global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ success: true, models: [{ name: 'studio-test:latest' }] }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });

      render(<ChatConversation ollamaTransport restoreLastConversation={false} />);

      await waitFor(() => {
        expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument();
      });

      const select = screen.getByTestId('studio-ai-chat-ollama-model-select') as HTMLSelectElement;
      expect(select.value).toBe('studio-test:latest');
    });

    it('selects persisted project default over the first listed model (#266)', async () => {
      window.localStorage.setItem(
        CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY,
        JSON.stringify({
          v: 1,
          byTenant: {},
          byProject: { 'tenant-a::project-b': 'saved:latest' },
        }),
      );

      global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              success: true,
              models: [{ name: 'first:latest' }, { name: 'saved:latest' }],
            }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });

      render(
        <ChatConversation
          ollamaTransport
          restoreLastConversation={false}
          tenantId="tenant-a"
          studioContext={{
            ...EMPTY_CHAT_STUDIO_CONTEXT,
            project: { id: 'project-b', name: 'PB' },
          }}
        />,
      );

      await waitFor(() => {
        expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument();
      });

      const select = screen.getByTestId('studio-ai-chat-ollama-model-select') as HTMLSelectElement;
      expect(select.value).toBe('saved:latest');
    });

    it('writes project default to localStorage when the user changes the model (#266)', async () => {
      window.localStorage.removeItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);

      global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              success: true,
              models: [{ name: 'a:latest' }, { name: 'b:latest' }],
            }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });

      render(
        <ChatConversation
          ollamaTransport
          restoreLastConversation={false}
          tenantId="tenant-x"
          studioContext={{
            ...EMPTY_CHAT_STUDIO_CONTEXT,
            project: { id: 'project-y', name: 'PY' },
          }}
        />,
      );

      await waitFor(() => {
        expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument();
      });

      const select = screen.getByTestId('studio-ai-chat-ollama-model-select') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: 'b:latest' } });

      const raw = window.localStorage.getItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);
      expect(raw).toBeTruthy();
      const parsed = JSON.parse(raw!) as { byProject: Record<string, string> };
      expect(parsed.byProject['tenant-x::project-y']).toBe('b:latest');
    });

    it('Tenant default button saves the tenant-wide preference (#266)', async () => {
      window.localStorage.removeItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);

      global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              success: true,
              models: [{ name: 'a:latest' }, { name: 'b:latest' }],
            }),
          } as Response);
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });

      render(
        <ChatConversation
          ollamaTransport
          restoreLastConversation={false}
          tenantId="tenant-x"
          studioContext={{
            ...EMPTY_CHAT_STUDIO_CONTEXT,
            project: { id: 'project-y', name: 'PY' },
          }}
        />,
      );

      await waitFor(() => {
        expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument();
      });

      const select = screen.getByTestId('studio-ai-chat-ollama-model-select') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: 'b:latest' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-ollama-tenant-default'));

      const raw = window.localStorage.getItem(CHAT_OLLAMA_MODEL_DEFAULTS_STORAGE_KEY);
      expect(raw).toBeTruthy();
      const parsed = JSON.parse(raw!) as { byTenant: Record<string, string> };
      expect(parsed.byTenant['tenant-x']).toBe('b:latest');
    });

    it('sends messages through the Ollama chat route when models are ready', async () => {
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ success: true, models: [{ name: 'studio-test:latest' }] }),
          } as Response);
        }
        if (url.includes('/api/ollama/chat')) {
          return Promise.resolve(mockSseBody(['data: {"content":"Model reply","done":true}\n\n', 'data: [DONE]\n\n']));
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });
      global.fetch = fetchMock;

      render(<ChatConversation ollamaTransport restoreLastConversation={false} />);

      await waitFor(() => expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument());

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'Hello Ollama' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

      await waitFor(() => {
        expect(screen.getByText('Model reply')).toBeInTheDocument();
      });

      const chatCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/ollama/chat'));
      expect(chatCalls.length).toBe(1);
      const body = JSON.parse((chatCalls[0][1] as RequestInit).body as string) as {
        model: string;
        messages: unknown[];
      };
      expect(body.model).toBe('studio-test:latest');
      expect(Array.isArray(body.messages)).toBe(true);
    });

    it('shows token usage while using Ollama transport (#521)', async () => {
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
        if (url.includes('/api/ollama/models')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ success: true, models: [{ name: 'studio-test:latest' }] }),
          } as Response);
        }
        if (url.includes('/api/ollama/chat')) {
          return Promise.resolve(
            mockSseBody([
              'data: {"content":"Hi","done":false}\n\n',
              'data: {"content":" there","done":true,"usage":{"promptTokens":50,"completionTokens":3}}\n\n',
              'data: [DONE]\n\n',
            ]),
          );
        }
        return Promise.reject(new Error(`unexpected fetch ${url}`));
      });
      global.fetch = fetchMock;

      render(<ChatConversation ollamaTransport restoreLastConversation={false} />);

      await waitFor(() => expect(screen.getByTestId('studio-ai-chat-ollama-model-select')).toBeInTheDocument());

      fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'Hello' } });
      fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

      await waitFor(() => {
        expect(screen.getByText('Hi there')).toBeInTheDocument();
      });

      const usage = screen.getByTestId('studio-ai-chat-token-usage');
      expect(usage).toHaveTextContent('50');
      expect(usage).toHaveTextContent('3');
      expect(usage.textContent).not.toMatch(/estimated/i);
    });
  });
});
