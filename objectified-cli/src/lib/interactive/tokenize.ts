/**
 * Shell-like tokenizer for the interactive REPL.
 *
 * Splits a typed line into argv tokens honoring single quotes, double quotes
 * (with backslash escapes) and bare backslash escapes — enough to pass quoted
 * values (e.g. descriptions) through to oclif commands the same way a shell would.
 */

export type QuoteChar = '"' | "'";

export type TokenizeResult = {
  /** Parsed argv tokens (quotes/escapes resolved). */
  tokens: string[];
  /** Set when the line ends inside an unterminated quote. */
  openQuote: QuoteChar | null;
  /** True when the line ends with unquoted whitespace (cursor starts a new word). */
  trailingSpace: boolean;
};

export function tokenizeLineDetailed(line: string): TokenizeResult {
  const tokens: string[] = [];
  let current = "";
  let hasCurrent = false;
  let quote: QuoteChar | null = null;
  let trailingSpace = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i] as string;

    if (quote === "'") {
      if (ch === "'") quote = null;
      else current += ch;
      continue;
    }

    if (quote === '"') {
      if (ch === "\\") {
        const next = line[i + 1];
        if (next === '"' || next === "\\") {
          current += next;
          i++;
        } else {
          current += ch;
        }
      } else if (ch === '"') {
        quote = null;
      } else {
        current += ch;
      }
      continue;
    }

    // Unquoted.
    if (ch === "'" || ch === '"') {
      quote = ch;
      hasCurrent = true;
      trailingSpace = false;
      continue;
    }
    if (ch === "\\") {
      const next = line[i + 1];
      if (next !== undefined) {
        current += next;
        hasCurrent = true;
        i++;
      }
      trailingSpace = false;
      continue;
    }
    if (ch === " " || ch === "\t") {
      if (hasCurrent) {
        tokens.push(current);
        current = "";
        hasCurrent = false;
      }
      trailingSpace = true;
      continue;
    }
    current += ch;
    hasCurrent = true;
    trailingSpace = false;
  }

  if (hasCurrent || quote !== null) {
    tokens.push(current);
  }

  return { tokens, openQuote: quote, trailingSpace };
}

/** Parse a line into argv tokens for execution (quotes/escapes resolved). */
export function tokenizeLine(line: string): string[] {
  return tokenizeLineDetailed(line).tokens;
}

export type CompletionLine = {
  /** Words with `binName` prepended at index 0 (the shape `computeCompletionCandidates` expects). */
  words: string[];
  /** Index of the word being completed. */
  cword: number;
  /** The partial token under the cursor (readline replaces this suffix). */
  current: string;
  /** True when the cursor sits inside an unterminated quote (completion is skipped). */
  insideQuote: boolean;
};

/**
 * Map a partial line (text before the cursor) onto the (words, cword) model used by
 * the shared completion engine. `binName` becomes `words[0]` because that engine
 * indexes command tokens from position 1 (mirroring shell `COMP_WORDS`).
 */
export function parseCompletionLine(line: string, binName: string): CompletionLine {
  const { tokens, openQuote, trailingSpace } = tokenizeLineDetailed(line);

  if (trailingSpace || tokens.length === 0) {
    const words = [binName, ...tokens, ""];
    return { words, cword: words.length - 1, current: "", insideQuote: openQuote !== null };
  }

  const words = [binName, ...tokens];
  return {
    words,
    cword: words.length - 1,
    current: tokens[tokens.length - 1] ?? "",
    insideQuote: openQuote !== null,
  };
}
