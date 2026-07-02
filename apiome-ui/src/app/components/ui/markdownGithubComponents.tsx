'use client';

import type { ReactNode } from 'react';
import type { Components } from 'react-markdown';
import { ExternalLink } from 'lucide-react';

/**
 * Rich, GitHub-flavored component map for long-form markdown surfaces:
 *   - What’s New (`/WHATS_NEW.md`)
 *   - Version change reports (header / body / footnote)
 *   - Any other readable document rendered through `<Markdown />`
 *
 * Pair with `<Markdown allowHtml variant="article" components={githubMarkdownComponents} />`
 * for content that may contain inline HTML (e.g. template-rendered snapshots).
 */
export const githubMarkdownComponents: Components = {
  h1: ({ children }) => (
    <h1 className="text-2xl font-bold mt-0 mb-5 text-gray-900 dark:text-white border-b border-gray-200 dark:border-gray-600 pb-3">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-xl font-semibold mt-8 mb-3 text-gray-900 dark:text-white">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900 dark:text-white">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="mb-4 text-gray-700 dark:text-gray-300 leading-relaxed">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc pl-6 mb-4 space-y-2 text-gray-700 dark:text-gray-300">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal pl-6 mb-4 space-y-2 text-gray-700 dark:text-gray-300">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="leading-relaxed [&>p]:mb-0 [&>p]:inline">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-gray-900 dark:text-white">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-gray-800 dark:text-gray-200">{children}</em>,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 hover:underline underline-offset-2"
    >
      {children}
      <ExternalLink className="w-3.5 h-3.5 shrink-0" aria-hidden />
    </a>
  ),
  code: ({ className, children, ...props }: { className?: string; children?: ReactNode }) => {
    const inline = !className?.includes('language-');
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : '';

    if (inline) {
      return (
        <code
          className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-sm font-mono"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <div className="my-4 rounded-lg overflow-hidden border border-gray-200 dark:border-gray-600">
        {language && (
          <div className="bg-gray-100 dark:bg-gray-800 px-3 py-1.5 border-b border-gray-200 dark:border-gray-600">
            <span className="text-xs font-mono text-gray-500 dark:text-gray-400 uppercase tracking-wider">
              {language}
            </span>
          </div>
        )}
        <pre className="bg-gray-50 dark:bg-gray-900 p-4 overflow-x-auto m-0 text-sm">
          <code className="font-mono text-gray-800 dark:text-gray-200" {...props}>
            {children}
          </code>
        </pre>
      </div>
    );
  },
  pre: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-indigo-500 dark:border-indigo-400 pl-4 my-4 italic text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/50 py-2 rounded-r">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-6 border-0 border-t border-gray-200 dark:border-gray-600" />,
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-600">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-600">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-gray-50 dark:bg-gray-800">{children}</thead>,
  th: ({ children }) => (
    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
      {children}
    </th>
  ),
  tr: ({ children }) => (
    <tr className="border-b border-gray-200 dark:border-gray-600 last:border-0">{children}</tr>
  ),
  td: ({ children }) => (
    <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">{children}</td>
  ),
  tbody: ({ children }) => (
    <tbody className="divide-y divide-gray-200 dark:divide-gray-600 bg-white dark:bg-gray-800">
      {children}
    </tbody>
  ),
  img: ({ src, alt }) => (
    <img
      src={src}
      alt={alt || ''}
      className="max-w-full h-auto rounded-lg my-4 shadow-sm border border-gray-200 dark:border-gray-600"
    />
  ),
};
