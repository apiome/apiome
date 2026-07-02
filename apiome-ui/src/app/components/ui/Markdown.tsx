'use client';

import React, { type ReactNode } from 'react';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { cn } from '@lib/utils';

const VARIANT_CLASSES = {
  /** Change reports, previews, path operation description — scroll-margin on headings */
  default: 'prose prose-sm dark:prose-invert max-w-none prose-headings:scroll-mt-4',
  compact: 'prose prose-sm dark:prose-invert max-w-none',
  article:
    'prose prose-gray dark:prose-invert prose-base max-w-none prose-headings:font-semibold prose-a:font-medium',
  /** No prose wrapper — parent supplies layout (rare) */
  bare: '',
} as const;

export type MarkdownVariant = keyof typeof VARIANT_CLASSES;

export type MarkdownProps = {
  children: string;
  className?: string;
  variant?: MarkdownVariant;
  /**
   * Allow raw HTML in markdown (e.g. static bundled docs). Do not enable for untrusted user input.
   */
  allowHtml?: boolean;
  components?: Components;
  /** Rendered when `children` is empty or whitespace-only */
  fallback?: ReactNode;
};

/**
 * Renders markdown with `react-markdown`, `remark-gfm`, and shared typography (Tailwind prose).
 * Use everywhere user-facing markdown is shown (change reports, What’s New, path descriptions, etc.).
 */
export function Markdown({
  children,
  className,
  variant = 'default',
  allowHtml = false,
  components,
  fallback = null,
}: MarkdownProps) {
  const raw = children ?? '';
  if (!raw.trim()) {
    return <>{fallback}</>;
  }

  return (
    <div className={cn(VARIANT_CLASSES[variant], className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={allowHtml ? [rehypeRaw] : undefined}
        components={components}
      >
        {raw}
      </ReactMarkdown>
    </div>
  );
}

/** Default empty-state line for change report sections */
export const MARKDOWN_EMPTY_EM_DASH = (
  <p className="text-sm text-gray-500 dark:text-gray-400">—</p>
);
