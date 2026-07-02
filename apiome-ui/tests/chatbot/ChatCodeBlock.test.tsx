/**
 * Tests for the chatbot code block (#258).
 *
 * Covers:
 *   - Language label rendering and the `text` fallback
 *   - Copy-to-clipboard behaviour, including the temporary "Copied" state
 *   - Token highlighting for json / typescript / shell
 *   - Plain rendering for unknown languages
 */

import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  ChatCodeBlock,
  renderHighlighted,
} from '../../src/app/ade/studio/components/chatbot/ChatCodeBlock';

describe('ChatCodeBlock', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('renders the language label and the code body', () => {
    render(<ChatCodeBlock code={'print("hi")'} language="python" />);
    const block = screen.getByTestId('studio-ai-chat-code-block');
    expect(block).toHaveAttribute('data-language', 'python');
    // The uppercase label is a CSS transform on the source `python` text; we
    // assert against the underlying string to keep the test css-agnostic.
    expect(block.textContent).toContain('python');
    expect(block.textContent).toContain('print("hi")');
  });

  it('falls back to the "text" label when no language is provided', () => {
    render(<ChatCodeBlock code={'just text'} />);
    expect(screen.getByTestId('studio-ai-chat-code-block')).toHaveAttribute(
      'data-language',
      'text'
    );
  });

  it('copies code to the clipboard and shows a temporary "Copied" state', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    render(<ChatCodeBlock code={'hello world\n'} language="text" />);

    const copyButton = screen.getByTestId('studio-ai-chat-code-copy');
    expect(copyButton).toHaveAttribute('aria-label', 'Copy code to clipboard');

    await act(async () => {
      fireEvent.click(copyButton);
      // Resolve the writeText promise so the component flips to "copied".
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith('hello world');
    expect(copyButton).toHaveAttribute('aria-label', 'Code copied to clipboard');
    expect(copyButton.textContent).toContain('Copied');

    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(copyButton).toHaveAttribute('aria-label', 'Copy code to clipboard');
  });

  it('handles a denied clipboard without throwing', async () => {
    const writeText = jest.fn().mockRejectedValue(new Error('denied'));
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    render(<ChatCodeBlock code="x" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('studio-ai-chat-code-copy'));
      await Promise.resolve();
    });

    expect(screen.getByTestId('studio-ai-chat-code-copy').textContent).toContain('Copy');
  });
});

describe('renderHighlighted', () => {
  it('returns the raw string when the language has no rules', () => {
    expect(renderHighlighted('foo', 'unknown')).toBe('foo');
  });

  it('tokenises JSON keys, strings, numbers, and booleans', () => {
    const out = renderHighlighted('{ "name": "ada", "age": 36, "ok": true }', 'json');
    expect(Array.isArray(out)).toBe(true);

    const text = renderToString(out);
    expect(text).toBe('{ "name": "ada", "age": 36, "ok": true }');

    const classes = collectClasses(out);
    expect(classes.some((c) => c.includes('text-sky-300'))).toBe(true); // key
    expect(classes.some((c) => c.includes('text-emerald-300'))).toBe(true); // string
    expect(classes.some((c) => c.includes('text-amber-300'))).toBe(true); // number
    expect(classes.some((c) => c.includes('text-purple-300'))).toBe(true); // boolean
  });

  it('tokenises typescript keywords, strings, and numbers', () => {
    const out = renderHighlighted("const x: number = 42; // hi", 'typescript');
    const classes = collectClasses(out);
    expect(classes.some((c) => c.includes('text-purple-300'))).toBe(true); // const keyword
    expect(classes.some((c) => c.includes('text-amber-300'))).toBe(true); // 42
    expect(classes.some((c) => c.includes('italic'))).toBe(true); // comment
  });

  it('tokenises shell comments, variables, and flags', () => {
    const out = renderHighlighted('curl --silent $URL # fetch', 'sh');
    const classes = collectClasses(out);
    expect(classes.some((c) => c.includes('text-sky-300'))).toBe(true); // --silent
    expect(classes.some((c) => c.includes('text-amber-300'))).toBe(true); // $URL
    expect(classes.some((c) => c.includes('italic'))).toBe(true); // comment
  });
});

function renderToString(node: React.ReactNode): string {
  if (node == null || node === false) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(renderToString).join('');
  if (React.isValidElement(node)) {
    const children = (node.props as { children?: React.ReactNode }).children;
    return renderToString(children);
  }
  return '';
}

function collectClasses(node: React.ReactNode): string[] {
  const out: string[] = [];
  const visit = (n: React.ReactNode) => {
    if (Array.isArray(n)) {
      n.forEach(visit);
      return;
    }
    if (React.isValidElement(n)) {
      const props = n.props as { className?: string; children?: React.ReactNode };
      if (props.className) out.push(props.className);
      if (props.children) visit(props.children);
    }
  };
  visit(node);
  return out;
}
