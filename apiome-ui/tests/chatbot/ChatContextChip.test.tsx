/**
 * Tests for the chat context chip (#259).
 *
 * The chip is the user-visible affordance that surfaces what the assistant
 * can see in the current conversation. These tests pin:
 *   - Empty contexts render nothing (no chip on a fresh workspace)
 *   - The chip summary mentions project / version / counts
 *   - Opening the popover reveals selection, classes, and properties
 *   - Caps render an overflow marker so big workspaces stay tidy
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

// Radix Popover uses ResizeObserver internally; provide a no-op stub for jsdom.
(global as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

import { ChatContextChip } from '../../src/app/ade/studio/components/chatbot/ChatContextChip';
import {
  CHAT_CONTEXT_CLASS_CAP,
  CHAT_CONTEXT_PROPERTY_CAP,
  EMPTY_CHAT_STUDIO_CONTEXT,
  type ChatStudioContext,
} from '../../src/app/ade/studio/components/chatbot/chat-context';

const baseContext: ChatStudioContext = {
  project: { id: 'proj-1', name: 'Acme Catalog' },
  version: { id: 'ver-1', label: 'v1.4.0' },
  classes: [
    { id: 'cls-user', name: 'User', schema: {} },
    { id: 'cls-product', name: 'Product', schema: {} },
  ],
  properties: [
    { id: 'prop-email', name: 'email', type: 'string' },
    { id: 'prop-id', name: 'id', type: 'string' },
  ],
  selectedClassIds: ['cls-user'],
};

describe('ChatContextChip', () => {
  it('renders nothing when the context is empty', () => {
    const { container } = render(<ChatContextChip studioContext={EMPTY_CHAT_STUDIO_CONTEXT} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('summarises project, version, and counts in the chip label', () => {
    render(<ChatContextChip studioContext={baseContext} />);
    const chip = screen.getByTestId('studio-ai-chat-context-chip');
    expect(chip).toHaveTextContent('Acme Catalog');
    expect(chip).toHaveTextContent('v1.4.0');
    expect(chip).toHaveTextContent('2 classes');
    expect(chip).toHaveTextContent('2 properties');
    expect(chip).toHaveTextContent('1 selected');
  });

  it('shows project domain in the popover when domainCategory is set (#615)', () => {
    render(
      <ChatContextChip
        studioContext={{ ...baseContext, project: { ...baseContext.project!, domainCategory: 'ecommerce' } }}
      />,
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-context-chip'));
    const popover = screen.getByTestId('studio-ai-chat-context-popover');
    expect(within(popover).getByText('Project domain')).toBeInTheDocument();
    expect(within(popover).getByText(/E-commerce/i)).toBeInTheDocument();
  });

  it('opens the popover and surfaces selection, classes, and properties', () => {
    render(<ChatContextChip studioContext={baseContext} />);
    fireEvent.click(screen.getByTestId('studio-ai-chat-context-chip'));

    const popover = screen.getByTestId('studio-ai-chat-context-popover');
    expect(within(popover).getByText('Acme Catalog')).toBeInTheDocument();
    expect(within(popover).getByText('v1.4.0')).toBeInTheDocument();

    const selection = within(popover).getByTestId('studio-ai-chat-context-selection');
    expect(selection).toHaveTextContent('User');

    const classes = within(popover).getByTestId('studio-ai-chat-context-classes');
    expect(classes).toHaveTextContent('User');
    expect(classes).toHaveTextContent('Product');

    const properties = within(popover).getByTestId('studio-ai-chat-context-properties');
    expect(properties).toHaveTextContent('email (string)');
    expect(properties).toHaveTextContent('id (string)');
  });

  it('renders an overflow marker for very large class lists', () => {
    const classes = Array.from({ length: CHAT_CONTEXT_CLASS_CAP + 5 }, (_, i) => ({
      id: `c${i}`,
      name: `C${i}`,
    }));
    render(
      <ChatContextChip
        studioContext={{ ...baseContext, classes, selectedClassIds: [] }}
      />
    );
    fireEvent.click(screen.getByTestId('studio-ai-chat-context-chip'));
    const classesSection = screen.getByTestId('studio-ai-chat-context-classes');
    expect(classesSection).toHaveTextContent('+5 more');
  });

  it('renders an overflow marker for very large property lists', () => {
    const properties = Array.from({ length: CHAT_CONTEXT_PROPERTY_CAP + 3 }, (_, i) => ({
      id: `p${i}`,
      name: `p${i}`,
      type: 'string',
    }));
    render(<ChatContextChip studioContext={{ ...baseContext, properties }} />);
    fireEvent.click(screen.getByTestId('studio-ai-chat-context-chip'));
    const propertiesSection = screen.getByTestId('studio-ai-chat-context-properties');
    expect(propertiesSection).toHaveTextContent('+3 more');
  });
});
