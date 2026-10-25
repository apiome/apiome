/**
 * The catalog search query language (BDX-0, browse retail search).
 *
 * The public directory is searched with one box, but one box has to carry more than words: a
 * visitor who knows what they want types `method:POST path:/orders`, a visitor who does not types
 * `orders`. This module parses that language into a structure the SQL builder (`./sql.ts`) and the
 * UI (operator chips, the "searching for" summary) both read, so a token means the same thing
 * everywhere.
 *
 * ### Grammar
 *
 * ```text
 * query    := token*
 * token    := negated | filter | phrase | word
 * negated  := '-' (phrase | word)              — must NOT match
 * filter   := key ':' (phrase | bare)          — key is one of FILTER_KEYS
 * phrase   := '"' [^"]* '"'                    — matched as one string, spaces included
 * word     := [^\s"]+                          — matched as a substring, case-insensitive
 * ```
 *
 * Filters are case-insensitive on the key. An unknown key (`foo:bar`) is not a filter — it stays
 * a plain word, because `a:b` is a perfectly good thing to search a schema for. Repeating a filter
 * ORs its values (`method:GET method:POST`), except `after:`/`before:` where the last one wins.
 *
 * Pure: no React, no pg. Unit-tested in `lib/search/__tests__/query.test.ts`.
 */

/** The filter keys the query language understands, in the order the syntax help lists them. */
export const FILTER_KEYS = [
  'type',
  'method',
  'path',
  'org',
  'project',
  'version',
  'format',
  'paradigm',
  'tag',
  'after',
  'before',
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];

/** Aliases a visitor may type instead of the canonical key. */
const FILTER_ALIASES: Readonly<Record<string, FilterKey>> = {
  kind: 'type',
  in: 'type',
  verb: 'method',
  op: 'method',
  route: 'path',
  tenant: 'org',
  organization: 'org',
  organisation: 'org',
  owner: 'org',
  api: 'project',
  v: 'version',
  fmt: 'format',
  protocol: 'paradigm',
  since: 'after',
  until: 'before',
};

/** The parsed form of a query string. */
export interface ParsedQuery {
  /** Plain words, in order; every one must match (AND). */
  terms: string[];
  /** Quoted phrases, in order; every one must match (AND). */
  phrases: string[];
  /** Words/phrases prefixed with `-`; none may match. */
  negated: string[];
  /** Filter values by key; a missing key means "any". Values are lower-cased and de-duplicated. */
  filters: Partial<Record<FilterKey, string[]>>;
}

/** The empty parse — what `parseQuery('')` returns. */
export const EMPTY_QUERY: ParsedQuery = Object.freeze({
  terms: [],
  phrases: [],
  negated: [],
  filters: {},
}) as ParsedQuery;

/** A token as the tokenizer sees it, before classification. */
interface RawToken {
  text: string;
  quoted: boolean;
  negated: boolean;
  /** A filter key when the token was `key:value`. */
  key?: FilterKey;
}

/**
 * Resolve a candidate key (the text before `:`) to a canonical filter key, or null when the text
 * is not a key the language knows — in which case the whole token is a word.
 */
export function resolveFilterKey(candidate: string): FilterKey | null {
  const key = candidate.trim().toLowerCase();
  if ((FILTER_KEYS as readonly string[]).includes(key)) return key as FilterKey;
  return FILTER_ALIASES[key] ?? null;
}

/**
 * Split a query string into raw tokens, honouring quotes, `-` negation and `key:` prefixes.
 *
 * A `-` only negates at the start of a token (`-draft`, `-"beta channel"`); a `-` inside a word
 * (`read-only`) is literal. A `key:` prefix only counts when the key is known and something
 * follows the colon.
 */
function tokenize(input: string): RawToken[] {
  const tokens: RawToken[] = [];
  let i = 0;
  const n = input.length;

  const readPhrase = (): string => {
    // Precondition: input[i] === '"'
    let j = i + 1;
    while (j < n && input[j] !== '"') j++;
    const text = input.slice(i + 1, j);
    i = j < n ? j + 1 : n;
    return text;
  };

  const readBare = (): string => {
    let j = i;
    while (j < n && !/\s/.test(input[j]) && input[j] !== '"') j++;
    const text = input.slice(i, j);
    i = j;
    return text;
  };

  while (i < n) {
    if (/\s/.test(input[i])) {
      i++;
      continue;
    }

    let negated = false;
    if (input[i] === '-' && i + 1 < n && !/\s/.test(input[i + 1])) {
      negated = true;
      i++;
    }

    if (input[i] === '"') {
      const text = readPhrase();
      if (text.trim()) tokens.push({ text, quoted: true, negated });
      continue;
    }

    // A filter: key ':' then either a phrase or bare text. The key must be known.
    const colon = input.indexOf(':', i);
    if (colon > i) {
      const candidate = input.slice(i, colon);
      const key = /^[A-Za-z]+$/.test(candidate) ? resolveFilterKey(candidate) : null;
      if (key && colon + 1 < n && !/\s/.test(input[colon + 1])) {
        i = colon + 1;
        if (input[i] === '"') {
          const text = readPhrase();
          if (text.trim()) tokens.push({ text, quoted: true, negated, key });
        } else {
          const text = readBare();
          if (text) tokens.push({ text, quoted: false, negated, key });
        }
        continue;
      }
    }

    const text = readBare();
    if (text) tokens.push({ text, quoted: false, negated });
  }

  return tokens;
}

/**
 * Normalize one filter value for a key: lower-cased, trimmed, and for `method` upper-cased so the
 * SQL side compares against the stored verb; a leading slash is kept on `path`.
 */
function normalizeFilterValue(key: FilterKey, raw: string): string {
  const value = raw.trim();
  if (!value) return '';
  if (key === 'method') return value.toUpperCase();
  if (key === 'path') return value;
  return value.toLowerCase();
}

/**
 * Parse a query string into {@link ParsedQuery}.
 *
 * @param input The raw text from the search box or the `q` URL parameter.
 * @returns The parsed query. Never throws; garbage in produces words out.
 */
export function parseQuery(input: string | null | undefined): ParsedQuery {
  const text = (input ?? '').trim();
  if (!text) return { terms: [], phrases: [], negated: [], filters: {} };

  const terms: string[] = [];
  const phrases: string[] = [];
  const negated: string[] = [];
  const filters: Partial<Record<FilterKey, string[]>> = {};

  for (const token of tokenize(text)) {
    if (token.key) {
      const value = normalizeFilterValue(token.key, token.text);
      if (!value) continue;
      // A negated filter is rare and has no SQL meaning yet; treat it as a negated word so the
      // visitor still gets the "not this" they asked for.
      if (token.negated) {
        negated.push(token.text.trim());
        continue;
      }
      const existing = filters[token.key] ?? [];
      if (!existing.includes(value)) existing.push(value);
      filters[token.key] = existing;
      continue;
    }
    const value = token.text.trim();
    if (!value) continue;
    if (token.negated) negated.push(value);
    else if (token.quoted) phrases.push(value);
    else terms.push(value);
  }

  return { terms, phrases, negated, filters };
}

/**
 * Whether the parse has anything at all to search for — a word, a phrase, or a filter.
 *
 * A filter-only query (`method:DELETE`) is a legitimate browse ("every DELETE operation"), so it
 * counts; a query of only negations does not, because "everything except X" over the whole
 * catalog is not a useful result set.
 */
export function hasSearchableContent(parsed: ParsedQuery): boolean {
  return (
    parsed.terms.length > 0 ||
    parsed.phrases.length > 0 ||
    Object.values(parsed.filters).some((values) => values && values.length > 0)
  );
}

/** The free-text part of a query (words and phrases) with filters removed, for highlighting. */
export function textNeedles(parsed: ParsedQuery): string[] {
  const needles = [...parsed.phrases, ...parsed.terms].map((s) => s.trim()).filter(Boolean);
  // Longest first so a phrase wins over a word it contains when both are highlighted.
  return [...new Set(needles)].sort((a, b) => b.length - a.length);
}

/**
 * Quote a value for the query language when it needs quoting (contains whitespace or a quote).
 */
function quoteIfNeeded(value: string): string {
  if (/[\s"]/.test(value)) return `"${value.replace(/"/g, '')}"`;
  return value;
}

/**
 * Serialize a parse back into query text — the inverse of {@link parseQuery} up to whitespace and
 * token order (filters come last, in {@link FILTER_KEYS} order).
 *
 * Used when a chip in the UI adds or removes a filter: the box is rewritten from the structure, so
 * the text and the structure can never disagree.
 */
export function stringifyQuery(parsed: ParsedQuery): string {
  const parts: string[] = [];
  for (const term of parsed.terms) parts.push(quoteIfNeeded(term));
  for (const phrase of parsed.phrases) parts.push(`"${phrase.replace(/"/g, '')}"`);
  for (const neg of parsed.negated) parts.push(`-${quoteIfNeeded(neg)}`);
  for (const key of FILTER_KEYS) {
    for (const value of parsed.filters[key] ?? []) parts.push(`${key}:${quoteIfNeeded(value)}`);
  }
  return parts.join(' ');
}

/**
 * Return a copy of the parse with one filter value added, removed or toggled.
 *
 * @param parsed The current parse.
 * @param key The filter key.
 * @param value The value to toggle.
 * @param mode `add`, `remove`, or `toggle` (default).
 */
export function withFilter(
  parsed: ParsedQuery,
  key: FilterKey,
  value: string,
  mode: 'add' | 'remove' | 'toggle' = 'toggle'
): ParsedQuery {
  const normalized = normalizeFilterValue(key, value);
  const current = parsed.filters[key] ?? [];
  const has = current.includes(normalized);
  let next: string[];
  if (mode === 'add' || (mode === 'toggle' && !has)) {
    next = has ? current : [...current, normalized];
  } else {
    next = current.filter((v) => v !== normalized);
  }
  const filters = { ...parsed.filters };
  if (next.length > 0) filters[key] = next;
  else delete filters[key];
  return { ...parsed, filters };
}

/**
 * Human labels for the filter keys, for chips and the syntax help.
 */
export const FILTER_KEY_LABELS: Readonly<Record<FilterKey, string>> = {
  type: 'Kind',
  method: 'Method',
  path: 'Path',
  org: 'Organization',
  project: 'Project',
  version: 'Version',
  format: 'Format',
  paradigm: 'Paradigm',
  tag: 'Tag',
  after: 'Published after',
  before: 'Published before',
};

/** One row of the syntax help card: the operator, what it does, and an example. */
export interface SyntaxHelpRow {
  operator: string;
  meaning: string;
  example: string;
}

/** The syntax help, in the order the card shows it. */
export const SYNTAX_HELP: readonly SyntaxHelpRow[] = [
  { operator: 'words', meaning: 'Every word must appear somewhere in the item.', example: 'create order' },
  { operator: '"phrase"', meaning: 'Match the words together, in this order.', example: '"payment intent"' },
  { operator: '-word', meaning: 'Leave out items that mention the word.', example: 'orders -deprecated' },
  { operator: 'type:', meaning: 'Only this kind of item.', example: 'type:operation' },
  { operator: 'method:', meaning: 'Operations with this HTTP method.', example: 'method:POST' },
  { operator: 'path:', meaning: 'Operations whose path contains this.', example: 'path:/orders' },
  { operator: 'org:', meaning: 'Published by this organization (slug or name).', example: 'org:acme' },
  { operator: 'project:', meaning: 'In this project (slug or name).', example: 'project:payments' },
  { operator: 'version:', meaning: 'In this version label.', example: 'version:2.1' },
  { operator: 'format:', meaning: 'Imported from this format.', example: 'format:openapi' },
  { operator: 'paradigm:', meaning: 'REST, RPC, event-driven, graph, data schema or agent.', example: 'paradigm:rest' },
  { operator: 'tag:', meaning: 'Versions carrying this tag.', example: 'tag:stable' },
  { operator: 'after:', meaning: 'Published on or after a date.', example: 'after:2026-01-01' },
  { operator: 'before:', meaning: 'Published before a date.', example: 'before:2026-06' },
];
