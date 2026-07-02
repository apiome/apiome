'use client';

import * as React from 'react';
import { Check, Copy } from 'lucide-react';

/**
 * Chat code block (#258).
 *
 * Renders fenced code from the assistant with:
 *   - language label header
 *   - copy-to-clipboard button (shows a check icon for ~1.5s after copy)
 *   - lightweight token highlighting for `json`, `javascript`/`typescript`,
 *     and `bash`/`shell`. Other languages render as plain monospace.
 *
 * The highlighter is intentionally tiny and dependency-free so the chat
 * surface stays cheap to load. It is *not* a full lexer — it covers the
 * common cases the chatbot emits (OpenAPI JSON, snippets, shell commands).
 */
export interface ChatCodeBlockProps {
  /** Source code to render — already stripped of fence markers. */
  code: string;
  /** Lowercase language tag from the markdown fence (`json`, `ts`, etc.). */
  language?: string;
  className?: string;
}

const COPIED_RESET_MS = 1500;

export function ChatCodeBlock({ code, language, className }: ChatCodeBlockProps) {
  const [copied, setCopied] = React.useState(false);
  const trimmed = React.useMemo(() => code.replace(/\n+$/, ''), [code]);
  const lang = (language || '').toLowerCase();
  const displayLang = lang || 'text';

  const handleCopy = React.useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(trimmed);
      setCopied(true);
    } catch {
      // Clipboard may be denied (e.g. test envs) — silently ignore so the
      // chat surface keeps working.
    }
  }, [trimmed]);

  React.useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
    return () => window.clearTimeout(id);
  }, [copied]);

  return (
    <div
      data-testid="studio-ai-chat-code-block"
      data-language={displayLang}
      className={`my-2 overflow-hidden rounded-lg border border-gray-700 bg-gray-900 text-gray-100 shadow-sm ${className ?? ''}`}
    >
      <div className="flex items-center justify-between border-b border-gray-700 bg-gray-800/80 px-3 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wider text-gray-300">
          {displayLang}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? 'Code copied to clipboard' : 'Copy code to clipboard'}
          data-testid="studio-ai-chat-code-copy"
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-gray-300 transition-colors hover:bg-gray-700 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3" /> Copied
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" /> Copy
            </>
          )}
        </button>
      </div>
      <pre className="m-0 overflow-x-auto p-4 text-[13px] leading-relaxed">
        <code className="font-mono text-gray-100">{renderHighlighted(trimmed, lang)}</code>
      </pre>
    </div>
  );
}

/**
 * Render `code` as React nodes with simple token coloring for the languages
 * the chatbot most commonly emits. Returns the raw string when no highlighter
 * applies, which keeps the markup minimal for unknown languages.
 */
export function renderHighlighted(code: string, language: string): React.ReactNode {
  switch (language) {
    case 'json':
    case 'jsonc':
      return tokenize(code, JSON_RULES);
    case 'js':
    case 'javascript':
    case 'ts':
    case 'tsx':
    case 'typescript':
      return tokenize(code, JS_RULES);
    case 'bash':
    case 'sh':
    case 'shell':
    case 'zsh':
      return tokenize(code, SHELL_RULES);
    default:
      return code;
  }
}

interface HighlightRule {
  /** Anchored regex describing the token at the cursor position. */
  pattern: RegExp;
  /** Tailwind class applied to the matched span. */
  className: string;
}

/** Greedy left-to-right tokenizer. Each rule's regex must be anchored (^). */
function tokenize(input: string, rules: HighlightRule[]): React.ReactNode {
  const out: React.ReactNode[] = [];
  let cursor = 0;
  let plain = '';
  let key = 0;

  const flushPlain = () => {
    if (plain) {
      out.push(plain);
      plain = '';
    }
  };

  while (cursor < input.length) {
    const slice = input.slice(cursor);
    let matched = false;
    for (const rule of rules) {
      const m = rule.pattern.exec(slice);
      if (m && m.index === 0 && m[0].length > 0) {
        flushPlain();
        out.push(
          <span key={`tok-${key++}`} className={rule.className}>
            {m[0]}
          </span>
        );
        cursor += m[0].length;
        matched = true;
        break;
      }
    }
    if (!matched) {
      plain += input[cursor];
      cursor += 1;
    }
  }
  flushPlain();
  return out;
}

const JSON_RULES: HighlightRule[] = [
  { pattern: /^"(?:\\.|[^"\\])*"(?=\s*:)/, className: 'text-sky-300' },
  { pattern: /^"(?:\\.|[^"\\])*"/, className: 'text-emerald-300' },
  { pattern: /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/, className: 'text-amber-300' },
  { pattern: /^(?:true|false|null)\b/, className: 'text-purple-300' },
  { pattern: /^[{}\[\],:]/, className: 'text-gray-400' },
];

const JS_KEYWORDS =
  'async|await|break|case|catch|class|const|continue|debugger|default|delete|do|else|enum|export|extends|false|finally|for|from|function|if|implements|import|in|instanceof|interface|let|new|null|of|return|static|super|switch|this|throw|true|try|type|typeof|undefined|var|void|while|yield';

const JS_RULES: HighlightRule[] = [
  { pattern: /^\/\/[^\n]*/, className: 'text-gray-500 italic' },
  { pattern: /^\/\*[\s\S]*?\*\//, className: 'text-gray-500 italic' },
  { pattern: /^`(?:\\.|[^`\\])*`/, className: 'text-emerald-300' },
  { pattern: /^'(?:\\.|[^'\\])*'/, className: 'text-emerald-300' },
  { pattern: /^"(?:\\.|[^"\\])*"/, className: 'text-emerald-300' },
  { pattern: new RegExp(`^(?:${JS_KEYWORDS})\\b`), className: 'text-purple-300' },
  { pattern: /^-?\d+(?:\.\d+)?/, className: 'text-amber-300' },
];

const SHELL_RULES: HighlightRule[] = [
  { pattern: /^#[^\n]*/, className: 'text-gray-500 italic' },
  { pattern: /^"(?:\\.|[^"\\])*"/, className: 'text-emerald-300' },
  { pattern: /^'(?:\\.|[^'\\])*'/, className: 'text-emerald-300' },
  { pattern: /^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/, className: 'text-amber-300' },
  { pattern: /^--?[A-Za-z][A-Za-z0-9-]*/, className: 'text-sky-300' },
];
