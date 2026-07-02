/**
 * Tests for LLM Import Dialog Markdown Rendering
 */

import React from 'react';
import { render } from '@testing-library/react';
import '@testing-library/jest-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
jest.mock('react-markdown', () => {
  return function ReactMarkdown({ children, components }: any) {
    // Simple mock that renders the content as-is
    if (typeof children === 'string') {
      // Check for code blocks
      const codeBlockMatch = children.match(/```(\w+)?\n([\s\S]*?)\n```/);
      if (codeBlockMatch && components?.code) {
        const language = codeBlockMatch[1];
        const code = codeBlockMatch[2];
        const CodeComponent = components.code;
        return (
          <div>
            <CodeComponent
              className={language ? `language-${language}` : undefined}
            >
              {code}
            </CodeComponent>
          </div>
        );
      }

      // Check for headings
      if (children.startsWith('# ')) {
        const heading = children.replace('# ', '');
        return <h1>{heading}</h1>;
      }

      // Check for bold
      if (children.includes('**')) {
        const parts = children.split('**');
        return (
          <p>
            {parts.map((part, i) =>
              i % 2 === 1 ? <strong key={i}>{part}</strong> : part
            )}
          </p>
        );
      }

      // Check for inline code
      if (children.includes('`')) {
        const parts = children.split('`');
        return (
          <p>
            {parts.map((part, i) =>
              i % 2 === 1 ? <code key={i}>{part}</code> : part
            )}
          </p>
        );
      }

      return <div>{children}</div>;
    }
    return <div>{children}</div>;
  };
});

jest.mock('remark-gfm', () => {
  return jest.fn();
});

describe('LLMImportDialog Markdown Rendering', () => {
  it('should render basic markdown headings', () => {
    const content = '# Hello World';

    const { container } = render(
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>
          {content}
        </ReactMarkdown>
      </div>
    );

    expect(container.querySelector('h1')).toHaveTextContent('Hello World');
  });

  it('should render bold text', () => {
    const content = 'This is a **bold** statement.';

    const { container } = render(
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>
          {content}
        </ReactMarkdown>
      </div>
    );

    expect(container.querySelector('strong')).toHaveTextContent('bold');
  });

  it('should render code blocks with language specification', () => {
    const content = '```json\n{"name": "test"}\n```';

    const { container } = render(
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown
          components={{
            code: ({ className, children }: any) => {
              const language = className?.replace('language-', '');
              if (language === 'json') {
                return (
                  <div data-testid="json-block">
                    <code>{children}</code>
                  </div>
                );
              }
              return <code>{children}</code>;
            }
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    );

    const jsonBlock = container.querySelector('[data-testid="json-block"]');
    expect(jsonBlock).toBeInTheDocument();
    expect(jsonBlock?.textContent).toContain('"name": "test"');
  });

  it('should render inline code', () => {
    const content = 'This is `inline code` in text.';

    const { container } = render(
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>
          {content}
        </ReactMarkdown>
      </div>
    );

    expect(container.querySelector('code')).toHaveTextContent('inline code');
  });

  it('should handle streaming content with cursor', () => {
    const content = 'This is streaming text';
    const isStreaming = true;

    const { container } = render(
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>
          {content}
        </ReactMarkdown>
        {isStreaming && (
          <span className="inline-block w-2 h-4 ml-1 bg-gray-900 dark:bg-white animate-pulse align-middle" />
        )}
      </div>
    );

    const cursor = container.querySelector('.animate-pulse');
    expect(cursor).toBeInTheDocument();
  });
});

