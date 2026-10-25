/**
 * Parse-free markers for client-side format detection.
 *
 * The project Import wizard (`openapi-analyzer.ts`), URL import (`url-import.ts`) and the spec
 * parser (`openapi-import.ts`) decide a document's format in the browser with keyword checks —
 * `isThrift`, `isProtobuf`, `isGraphQL`. Those read raw text, so a word in a YAML description
 * ("namespace to its primitives", "struct Order {", "type Query") made an OpenAPI spec look like
 * Thrift, Protobuf or GraphQL. `apiome-rest/openapi.yaml` was imported as Thrift this way.
 *
 * {@link looksLikeStructuredDocument} answers the question those checks skipped — *is this a JSON
 * or YAML document at all?* — and every IDL check returns `false` when it is. It is the client
 * twin of `apiome-rest/src/app/document_markers.py`; keep the two rules the same.
 */

/** How much of the text to look through for the first meaningful line. */
const HEAD_CHARS = 16_384;

/**
 * A top-level YAML key: at column 0, a single plain or quoted token, then `:` and a space or the
 * end of the line. A single token rules out IDL lines that merely contain a colon (Thrift
 * `const map<string,string> M = {"a": "b"}`, WIT `package ns:name;`).
 */
const YAML_KEY_LINE = /^(?:"[^"\n]+"|'[^'\n]+'|[A-Za-z_$][\w$.-]*)\s*:(?:[ \t]|$)/;

/** A genuine JSON opening: `{` then a key or `}`, `[` then a value or `]`. */
const JSON_START = /^(?:\{\s*(?:"|\})|\[\s*(?:[[{"\]\-0-9]|true|false|null))/;

/** The first line that is not blank, a `#` comment, a YAML directive or a `---` marker. */
function firstMeaningfulLine(text: string): string | null {
  for (const line of text.slice(0, HEAD_CHARS).replace(/^﻿/, '').split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith('#') || stripped.startsWith('%')) continue;
    if (stripped === '---' || stripped === '...') continue;
    return line;
  }
  return null;
}

/**
 * Whether `text` is a JSON or YAML document rather than an IDL source.
 *
 * True when the text opens like JSON (`{"…`, `[…`), or its first meaningful line is a top-level
 * YAML mapping key (`openapi: 3.1.0`). No Thrift, Protobuf, GraphQL or WIT file begins that way.
 * SWIFT MT blocks (`{1:F01…}`) are brace-framed but not JSON, and do not count.
 *
 * @param text The raw document text.
 * @returns `true` for a JSON or YAML document; `false` otherwise, including for empty text.
 */
export function looksLikeStructuredDocument(text: string | null | undefined): boolean {
  if (!text) return false;
  const line = firstMeaningfulLine(text);
  if (line === null) return false;
  const stripped = line.trimStart();
  if (stripped.startsWith('{') || stripped.startsWith('[')) {
    const head = text.slice(0, HEAD_CHARS).replace(/^[﻿\s]+/, '');
    return JSON_START.test(head);
  }
  // Only a column-0 key is a *top-level* mapping key; an indented one is a nested value.
  return line === stripped && YAML_KEY_LINE.test(line);
}
