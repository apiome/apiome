/** Split CLI words (from the shell driver) into profile override and command tokens. */

export function extractProfileFromWords(words: string[], uptoInclusive: number): string | undefined {
  const hi = Math.min(uptoInclusive, words.length - 1);
  for (let i = 1; i <= hi; i++) {
    const w = words[i];
    if (w === undefined) continue;
    if (w === "--profile") {
      const next = words[i + 1];
      if (next !== undefined && i + 1 <= hi) return next;
      continue;
    }
    if (w.startsWith("--profile=")) {
      const v = w.slice("--profile=".length);
      if (v !== "") return v;
    }
  }
  return undefined;
}

export type SplitWordsResult = {
  /** Non-flag command tokens before the cursor word (subcommands only). */
  cmdParts: string[];
  /** Word being completed (`COMP_WORDS[cword]`). */
  current: string;
};

/**
 * Parse completion words: `words[0]` is the CLI binary, `cword` indexes the active token.
 * Returns command tokens (no globals) strictly before `cword`, and the current token.
 */
export function splitCommandTokens(words: string[], cword: number): SplitWordsResult {
  const current = words[cword] ?? "";
  const cmdParts: string[] = [];
  let i = 1;
  while (i < cword && i < words.length) {
    const w = words[i];
    if (w === undefined) break;
    if (w === "--") break;
    if (w.startsWith("-")) {
      if (w === "--profile" || w.startsWith("--profile=")) {
        if (w === "--profile") i += 2;
        else i += 1;
        continue;
      }
      if (w === "--api-key" || w.startsWith("--api-key=")) {
        if (w === "--api-key") i += 2;
        else i += 1;
        continue;
      }
      if (w === "--base-url" || w.startsWith("--base-url=")) {
        if (w === "--base-url") i += 2;
        else i += 1;
        continue;
      }
      if (w === "--config" || w.startsWith("--config=")) {
        if (w === "--config") i += 2;
        else i += 1;
        continue;
      }
      i += 1;
      continue;
    }
    cmdParts.push(w);
    i += 1;
  }
  return { cmdParts, current };
}

export function matchesPrefix(candidate: string, partial: string): boolean {
  return partial === "" || candidate.startsWith(partial);
}
