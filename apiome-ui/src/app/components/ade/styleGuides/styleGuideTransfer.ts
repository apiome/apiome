/**
 * Style-guide import/export — the pure half (#1747).
 *
 * A guide's rule configuration travels as one `apiome.style-guide` JSON document:
 * `GET /api/style-guides/{id}/export` writes it and `POST /api/style-guides/import` creates a
 * new custom guide from one, pasted from an uploaded file or fetched from a URL. This module
 * holds what the list screen and the import dialog derive from that contract — the download
 * filename, the request body, the error sentence — so it is unit-testable without a DOM.
 */

/** The `format` discriminator every export carries. */
export const STYLE_GUIDE_FORMAT_ID = 'apiome.style-guide';

/** The largest document the REST layer accepts (1 MiB), checked before upload. */
export const MAX_STYLE_GUIDE_DOCUMENT_BYTES = 1_048_576;

/** Where the import dialog reads the document from. */
export type StyleGuideImportSource = 'file' | 'url';

/** The import dialog's state — what an import POST is built from. */
export interface StyleGuideImportDraft {
  /** Which source is selected. */
  source: StyleGuideImportSource;
  /** The chosen file's text, or `''` before one is picked. */
  fileContent: string;
  /** The chosen file's name, sent as the source label. */
  fileName: string;
  /** The URL to fetch, for the URL source. */
  url: string;
  /** A name for the new guide; `''` keeps the document's own. */
  name: string;
}

/** The JSON body of `POST /api/style-guides/import`. */
export interface StyleGuideImportRequest {
  content?: string;
  url?: string;
  name?: string;
  sourceLabel?: string;
}

/** One entry the import reported instead of storing. */
export interface StyleGuideImportSkippedRule {
  ruleId: string;
  /** Machine-readable code — `unknown_rule`. */
  reason: string;
  detail: string;
}

/** The import response: the new guide, what it stored, what it skipped. */
export interface StyleGuideImportResult {
  guide: { id: string; name: string };
  sourceLabel: string | null;
  builtinRuleCount: number;
  customRuleCount: number;
  skipped: StyleGuideImportSkippedRule[];
}

/** An empty draft — the dialog's state each time it opens. */
export const EMPTY_STYLE_GUIDE_IMPORT_DRAFT: StyleGuideImportDraft = {
  source: 'file',
  fileContent: '',
  fileName: '',
  url: '',
  name: '',
};

/**
 * The download filename for a guide's export — mirrors the REST `Content-Disposition`.
 *
 * The proxy answers with the JSON body only, so the browser cannot read the server's
 * filename; deriving it the same way keeps the two identical.
 *
 * @param guideName The guide's display name.
 * @returns e.g. `payments-guide.style-guide.json`; `style-guide.json` for a name with no
 *   letters or digits.
 */
export function styleGuideExportFilename(guideName: string): string {
  const slug = guideName
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/g, '');
  return slug ? `${slug}.style-guide.json` : 'style-guide.json';
}

/**
 * Validate the draft and build the import request body.
 *
 * Checks only what the dialog can know without the server — a source is chosen and the URL
 * is http(s). The document itself is validated by the REST layer, which points at the
 * offending node.
 *
 * @param draft The dialog's state.
 * @returns `{request}` to send, or `{error}` — the sentence to show inline.
 */
export function buildStyleGuideImportRequest(
  draft: StyleGuideImportDraft
): { request: StyleGuideImportRequest } | { error: string } {
  const name = draft.name.trim();
  const named = name ? { name } : {};
  if (draft.source === 'file') {
    if (!draft.fileContent.trim()) return { error: 'Choose a style-guide JSON file to import.' };
    return {
      request: {
        content: draft.fileContent,
        ...named,
        ...(draft.fileName ? { sourceLabel: draft.fileName } : {}),
      },
    };
  }
  const url = draft.url.trim();
  if (!url) return { error: 'Enter the URL of a style-guide JSON document.' };
  if (!/^https?:\/\/\S+$/i.test(url)) return { error: 'The URL must start with http:// or https://.' };
  return { request: { url, ...named } };
}

/**
 * Turn a refused import into the sentence to show.
 *
 * A malformed document comes back as a 422 whose `detail` is `{message, pointer}`; the
 * pointer names the node (`builtinRules[3].severity`) so the reader can find it in the file.
 *
 * @param error What the API call threw.
 * @returns The sentence.
 */
export function describeStyleGuideImportFailure(error: unknown): string {
  const detail = (error as { detail?: { message?: string; pointer?: string } } | null)?.detail;
  if (detail && typeof detail === 'object' && detail.message) {
    return detail.pointer ? `${detail.message} (at ${detail.pointer})` : detail.message;
  }
  return error instanceof Error && error.message ? error.message : 'Failed to import the style guide';
}

/**
 * Summarize what an import stored, for the dialog's result view.
 *
 * @param result The import response.
 * @returns e.g. `Imported 12 built-in rule settings and 3 custom rules.`
 */
export function styleGuideImportSummary(result: StyleGuideImportResult): string {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return `Imported ${plural(result.builtinRuleCount, 'built-in rule setting', 'built-in rule settings')} and ${plural(result.customRuleCount, 'custom rule', 'custom rules')}.`;
}
