/**
 * Unit tests for the Studio AI chatbot placement chrome (#257) and the
 * mounted chat surface (#258).
 *
 * Covers:
 *   - Visibility gating against the current pathname (canvas surfaces only).
 *   - Launcher → slide-out panel transition on click.
 *   - Slide-out → fullscreen toggle and back.
 *   - Closing via the close button and via the Escape key.
 *   - ⌘+Shift+A / Ctrl+Shift+A keyboard toggle.
 *   - The opened panel renders the chat conversation surface and composer.
 */

import React from 'react';
import { render, screen, act, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  StudioAiChatbot,
  isStudioAiChatbotPath,
} from '../src/app/ade/studio/components/StudioAiChatbot';
import type { ChatStudioContext } from '../src/app/ade/studio/components/chatbot/chat-context';

(global as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const mockUsePathname = jest.fn<string | null, []>();
jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
}));

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

beforeEach(() => {
  mockUsePathname.mockReset();
  Element.prototype.scrollIntoView = jest.fn();
});

describe('isStudioAiChatbotPath', () => {
  it('matches studio canvas surfaces', () => {
    expect(isStudioAiChatbotPath('/ade/studio/editor')).toBe(true);
    expect(isStudioAiChatbotPath('/ade/studio/editor?foo=bar')).toBe(true);
    expect(isStudioAiChatbotPath('/ade/studio/paths')).toBe(true);
    expect(isStudioAiChatbotPath('/ade/studio/paths/123')).toBe(true);
  });

  it('does not match unrelated surfaces', () => {
    expect(isStudioAiChatbotPath('/ade/studio')).toBe(false);
    expect(isStudioAiChatbotPath('/ade/studio/code')).toBe(false);
    expect(isStudioAiChatbotPath('/ade/dashboard')).toBe(false);
    expect(isStudioAiChatbotPath('/admin/users')).toBe(false);
    expect(isStudioAiChatbotPath(null)).toBe(false);
    expect(isStudioAiChatbotPath(undefined)).toBe(false);
  });
});

describe('StudioAiChatbot', () => {
  it('renders nothing on non-canvas pathnames', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard');
    const { container } = render(<StudioAiChatbot />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders only the launcher when closed on a canvas page', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot />);

    expect(screen.getByTestId('studio-ai-chatbot-launcher')).toBeInTheDocument();
    expect(screen.queryByTestId('studio-ai-chatbot-panel')).not.toBeInTheDocument();
  });

  it('opens the slide-out panel when the launcher is clicked', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot />);

    fireEvent.click(screen.getByTestId('studio-ai-chatbot-launcher'));

    const panel = screen.getByTestId('studio-ai-chatbot-panel');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveAttribute('data-mode', 'slide');
    expect(screen.queryByTestId('studio-ai-chatbot-launcher')).not.toBeInTheDocument();
  });

  it('toggles between slide-out and fullscreen', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot initialMode="slide" />);

    const toggle = screen.getByTestId('studio-ai-chatbot-toggle-fullscreen');
    fireEvent.click(toggle);
    expect(screen.getByTestId('studio-ai-chatbot-panel')).toHaveAttribute('data-mode', 'fullscreen');

    fireEvent.click(screen.getByTestId('studio-ai-chatbot-toggle-fullscreen'));
    expect(screen.getByTestId('studio-ai-chatbot-panel')).toHaveAttribute('data-mode', 'slide');
  });

  it('closes via the close button', () => {
    mockUsePathname.mockReturnValue('/ade/studio/paths');
    render(<StudioAiChatbot initialMode="slide" />);

    fireEvent.click(screen.getByTestId('studio-ai-chatbot-close'));

    expect(screen.queryByTestId('studio-ai-chatbot-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chatbot-launcher')).toBeInTheDocument();
  });

  it('closes when Escape is pressed', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot initialMode="slide" />);

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });

    expect(screen.queryByTestId('studio-ai-chatbot-panel')).not.toBeInTheDocument();
  });

  it('toggles open/closed with Ctrl+Shift+A', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot />);

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, shiftKey: true })
      );
    });
    expect(screen.getByTestId('studio-ai-chatbot-panel')).toHaveAttribute('data-mode', 'slide');

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, shiftKey: true })
      );
    });
    expect(screen.queryByTestId('studio-ai-chatbot-panel')).not.toBeInTheDocument();
  });

  it('also responds to the ⌘+Shift+A combination', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot />);

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'a', metaKey: true, shiftKey: true })
      );
    });
    expect(screen.getByTestId('studio-ai-chatbot-panel')).toHaveAttribute('data-mode', 'slide');
  });

  it('ignores the keyboard shortcut on non-canvas pages', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard');
    render(<StudioAiChatbot />);

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, shiftKey: true })
      );
    });
    expect(screen.queryByTestId('studio-ai-chatbot-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('studio-ai-chatbot-launcher')).not.toBeInTheDocument();
  });

  it('respects forceVisible when the pathname would otherwise hide the chatbot', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard');
    render(<StudioAiChatbot forceVisible />);
    expect(screen.getByTestId('studio-ai-chatbot-launcher')).toBeInTheDocument();
  });

  it('mounts the chat conversation and composer when the panel is open', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot initialMode="slide" />);

    expect(screen.getByTestId('studio-ai-chat-conversation')).toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('studio-ai-chat-send')).toBeInTheDocument();
    // Empty-state suggestions surface the prompt patterns the panel ships with.
    expect(screen.getAllByTestId('studio-ai-chat-suggestion').length).toBeGreaterThan(0);
  });

  it('does not render the context chip when no studio context is provided', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    render(<StudioAiChatbot initialMode="slide" />);
    expect(screen.queryByTestId('studio-ai-chat-context-chip')).not.toBeInTheDocument();
  });

  it('does not render the context chip when the supplied context is empty (#259)', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    const emptyContext: ChatStudioContext = {
      project: null,
      version: null,
      classes: [],
      properties: [],
      selectedClassIds: [],
    };
    render(<StudioAiChatbot initialMode="slide" studioContext={emptyContext} />);
    expect(screen.queryByTestId('studio-ai-chat-context-chip')).not.toBeInTheDocument();
  });

  it('renders the context chip with project + class summary when context is supplied (#259)', () => {
    mockUsePathname.mockReturnValue('/ade/studio/editor');
    const populatedContext: ChatStudioContext = {
      project: { id: 'proj-1', name: 'Acme Catalog' },
      version: { id: 'ver-1', label: 'v1.0.0' },
      classes: [
        { id: 'cls-1', name: 'Product', description: 'Sellable item', schema: null },
        { id: 'cls-2', name: 'Customer', description: null, schema: null },
      ],
      properties: [
        { id: 'prop-1', name: 'sku', type: 'string', format: null, required: true },
      ],
      selectedClassIds: ['cls-1'],
    };
    render(<StudioAiChatbot initialMode="slide" studioContext={populatedContext} />);

    const chip = screen.getByTestId('studio-ai-chat-context-chip');
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent('Acme Catalog');
    expect(chip).toHaveTextContent('v1.0.0');
  });
});
