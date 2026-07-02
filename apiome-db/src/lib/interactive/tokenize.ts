/**
 * Shell-like tokenizer for the interactive REPL.
 *
 * Splits a typed line into argv tokens honoring single quotes, double quotes
 * (with backslash escapes) and bare backslash escapes — so quoted values
 * (e.g. a multi-word --name or --description) reach the Commander program the
 * same way a real shell would pass them, without the shell-quoting footgun of
 * one-shot invocation.
 */

export type QuoteChar = '"' | "'";

export type TokenizeResult = {
  /** Parsed argv tokens (quotes/escapes resolved). */
  tokens: string[];
  /** Set when the line ends inside an unterminated quote. */
  openQuote: QuoteChar | null;
};

export function tokenizeLineDetailed(line: string): TokenizeResult {
  const tokens: string[] = [];
  let current = "";
  let hasCurrent = false;
  let quote: QuoteChar | null = null;

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
      continue;
    }
    if (ch === "\\") {
      const next = line[i + 1];
      if (next !== undefined) {
        current += next;
        hasCurrent = true;
        i++;
      }
      continue;
    }
    if (ch === " " || ch === "\t") {
      if (hasCurrent) {
        tokens.push(current);
        current = "";
        hasCurrent = false;
      }
      continue;
    }
    current += ch;
    hasCurrent = true;
  }

  if (hasCurrent || quote !== null) {
    tokens.push(current);
  }

  return { tokens, openQuote: quote };
}

/** Parse a line into argv tokens for execution (quotes/escapes resolved). */
export function tokenizeLine(line: string): string[] {
  return tokenizeLineDetailed(line).tokens;
}
