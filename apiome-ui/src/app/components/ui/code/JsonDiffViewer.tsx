'use client';

import * as React from 'react';
import dynamic from 'next/dynamic';
import { cn } from '../../../../../lib/utils';
import {
  CODE_BLOCK_FONT_SIZE,
  CODE_BLOCK_LINE_HEIGHT,
  CODE_BLOCK_PADDING,
} from './editorTypography';

const MonacoDiffEditor = dynamic(
  () => import('@monaco-editor/react').then((mod) => mod.DiffEditor),
  { ssr: false },
);

/**
 * `vs-dark` with fainter diff tints: its stock green and red stack to a background that drops
 * syntax colours under 3:1 (WCAG 1.4.3). The light theme's tints already pass.
 */
const DIFF_DARK_THEME_ID = 'apiome-diff-dark';
const DIFF_DARK_THEME = {
  base: 'vs-dark' as const,
  inherit: true,
  rules: [],
  colors: {
    'diffEditor.insertedTextBackground': '#9ccc2c1a',
    'diffEditor.insertedLineBackground': '#9bb9550f',
    'diffEditor.removedTextBackground': '#ff00001a',
    'diffEditor.removedLineBackground': '#ff00000f',
  },
};

/** How the two sides are laid out: `split` (side-by-side) or `unified` (inline). */
export type DiffMode = 'split' | 'unified';

export interface JsonDiffViewerProps {
  /** Pretty-printed source for the base (left / "before") side. */
  original: string;
  /** Pretty-printed source for the target (right / "after") side. */
  modified: string;
  mode?: DiffMode;
  /**
   * Monaco language id used for syntax highlighting on both sides. Defaults to `json` (its original
   * use) but the viewer is format-neutral (MFI-28.7) — pass any monaco-supported language.
   */
  language?: string;
  /** Never auto-size below this many visible lines, so short diffs keep a workable viewport. */
  minLines?: number;
  /** Clamp the auto-sized editor to this many visible lines (content beyond it scrolls). */
  maxLines?: number;
  /**
   * Fold long unchanged regions (Monaco's `hideUnchangedRegions`) so only the changes and a little
   * surrounding context show. Defaults to `true` — pass `false` to reveal the whole document (this is
   * how the catalog Versions pane's "expand all" control works, MFI-28.1 #4117).
   */
  hideUnchangedRegions?: boolean;
  /** Accessible names of the two read-only editors (each side is an ARIA input field). */
  originalAriaLabel?: string;
  modifiedAriaLabel?: string;
  className?: string;
}

/**
 * `<JsonDiffViewer>` — a read-only diff backed by monaco's DiffEditor. Renders side-by-side (`split`)
 * or inline (`unified`) per `mode`, auto-sizes to the content (clamped to `maxLines`), collapses long
 * unchanged regions, and follows the app's light/dark theme.
 *
 * Format-neutral: it defaults to JSON but takes a `language` prop for any monaco-supported source.
 * Promoted from `ui/mcp/McpJsonDiffViewer` to `ui/code` in MFI-28.7 (#4123); `ui/mcp` keeps a
 * back-compat re-export.
 */
export function JsonDiffViewer({
  original,
  modified,
  mode = 'split',
  language = 'json',
  minLines = 8,
  maxLines = 30,
  hideUnchangedRegions = true,
  originalAriaLabel = 'Before',
  modifiedAriaLabel = 'After',
  className,
}: JsonDiffViewerProps) {
  const [isDark, setIsDark] = React.useState(false);

  // Follow the app theme switch (the `.dark` class on <html>) so Monaco re-themes live.
  React.useEffect(() => {
    const sync = () => setIsDark(document.documentElement.classList.contains('dark'));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const lineCount = Math.max(
    original ? original.split('\n').length : 1,
    modified ? modified.split('\n').length : 1,
  );
  const height =
    Math.min(Math.max(lineCount, minLines), maxLines) * CODE_BLOCK_LINE_HEIGHT + CODE_BLOCK_PADDING;

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-[#1e1e1e]',
        className,
      )}
    >
      <MonacoDiffEditor
        height={height}
        language={language}
        theme={isDark ? DIFF_DARK_THEME_ID : 'light'}
        beforeMount={(monaco) => monaco.editor.defineTheme(DIFF_DARK_THEME_ID, DIFF_DARK_THEME)}
        original={original}
        modified={modified}
        // Each side is an ARIA input field; the diff-level label options do not reach them.
        onMount={(editor) => {
          editor.getOriginalEditor().updateOptions({ ariaLabel: originalAriaLabel });
          editor.getModifiedEditor().updateOptions({ ariaLabel: modifiedAriaLabel });
        }}
        options={{
          readOnly: true,
          domReadOnly: true,
          renderSideBySide: mode === 'split',
          minimap: { enabled: false },
          lineNumbers: 'on',
          lineNumbersMinChars: 3,
          folding: false,
          fontSize: CODE_BLOCK_FONT_SIZE,
          lineHeight: CODE_BLOCK_LINE_HEIGHT,
          padding: { top: 8, bottom: 8 },
          scrollBeyondLastLine: false,
          diffWordWrap: 'on',
          wordWrap: 'on',
          renderLineHighlight: 'none',
          renderOverviewRuler: false,
          hideCursorInOverviewRuler: true,
          enableSplitViewResizing: false,
          hideUnchangedRegions: { enabled: hideUnchangedRegions },
          scrollbar: {
            verticalScrollbarSize: 8,
            horizontalScrollbarSize: 8,
            alwaysConsumeMouseWheel: false,
          },
          contextmenu: false,
          links: false,
          automaticLayout: true,
        }}
      />
    </div>
  );
}
