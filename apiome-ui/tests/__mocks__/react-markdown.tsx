/**
 * Mock for react-markdown library
 */

import React from 'react';

interface ReactMarkdownProps {
  children: string;
  components?: any;
  remarkPlugins?: any[];
}

export default function ReactMarkdown({ children, components }: ReactMarkdownProps) {
  // Simple mock that renders basic markdown features
  if (typeof children === 'string') {
    // Handle code blocks
    const codeBlockMatch = children.match(/```(\w+)?\n([\s\S]*?)\n```/);
    if (codeBlockMatch && components?.code) {
      const language = codeBlockMatch[1];
      const code = codeBlockMatch[2];
      const CodeComponent = components.code;
      return (
        <div>
          {React.createElement(CodeComponent, {
            className: language ? `language-${language}` : undefined,
            children: code,
          })}
        </div>
      );
    }

    // Handle headings
    if (children.startsWith('# ')) {
      const heading = children.replace('# ', '').trim();
      return <h1>{heading}</h1>;
    }

    // Handle bold text
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

    // Handle inline code
    if (children.includes('`') && !children.includes('```')) {
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
}

