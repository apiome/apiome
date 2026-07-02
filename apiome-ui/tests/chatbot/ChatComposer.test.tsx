/**
 * Tests for the chat composer (#258).
 *
 * Covers submission via button + Enter, newline insertion via Shift+Enter,
 * busy-state disabling, and the trim/empty-guard rules.
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ChatComposer } from '../../src/app/ade/studio/components/chatbot/ChatComposer';

describe('ChatComposer', () => {
  it('submits the trimmed value on Send click and clears the input', () => {
    const onSend = jest.fn();
    render(<ChatComposer onSend={onSend} />);
    const input = screen.getByTestId('studio-ai-chat-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '   hello   ' } });

    fireEvent.click(screen.getByTestId('studio-ai-chat-send'));

    expect(onSend).toHaveBeenCalledWith('hello');
    expect(input.value).toBe('');
  });

  it('submits on Enter and skips when Shift+Enter is held', () => {
    const onSend = jest.fn();
    render(<ChatComposer onSend={onSend} />);
    const input = screen.getByTestId('studio-ai-chat-input');

    fireEvent.change(input, { target: { value: 'first' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('first');

    fireEvent.change(input, { target: { value: 'second' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('does not submit when the field is empty or whitespace-only', () => {
    const onSend = jest.fn();
    render(<ChatComposer onSend={onSend} />);
    const sendButton = screen.getByTestId('studio-ai-chat-send');

    expect(sendButton).toBeDisabled();
    fireEvent.click(sendButton);

    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: '   ' } });
    fireEvent.click(sendButton);

    expect(onSend).not.toHaveBeenCalled();
  });

  it('disables both input and send while busy', () => {
    const onSend = jest.fn();
    render(<ChatComposer onSend={onSend} isBusy />);
    expect(screen.getByTestId('studio-ai-chat-input')).toBeDisabled();
    expect(screen.getByTestId('studio-ai-chat-send')).toBeDisabled();
  });

  it('does not submit while busy even if Enter is pressed', () => {
    const onSend = jest.fn();
    const { rerender } = render(<ChatComposer onSend={onSend} />);
    fireEvent.change(screen.getByTestId('studio-ai-chat-input'), { target: { value: 'queued' } });
    rerender(<ChatComposer onSend={onSend} isBusy />);
    fireEvent.keyDown(screen.getByTestId('studio-ai-chat-input'), { key: 'Enter' });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('shows Stop and invokes onStop while busy when onStop is set (#522)', () => {
    const onSend = jest.fn();
    const onStop = jest.fn();
    render(<ChatComposer onSend={onSend} isBusy onStop={onStop} />);
    expect(screen.getByTestId('studio-ai-chat-stop')).toBeInTheDocument();
    expect(screen.queryByTestId('studio-ai-chat-send')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('studio-ai-chat-stop'));
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
