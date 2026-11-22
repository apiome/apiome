/**
 * The **Import to catalog → Projects** hand-off (COA-4.3b, #7127).
 *
 * **Import to catalog** detects an OpenAPI or Swagger source and routes it to **Projects**, but
 * the catalog dialog only stores catalog items. Rather than make the user paste or upload the
 * source a second time, the catalog dialog hands what it already read to the Projects importer
 * (`ImportDialog`), which opens straight on its Analyze step with the source loaded.
 *
 * This module holds the payload and the two pure rules both dialogs share, so the catalog side
 * (which payload it may offer) and the Projects side (which intake buffer it fills) cannot drift.
 */

/** The catalog dialog's intake methods that carry one text document the Projects importer can read. */
export type ProjectsHandoffMethod = 'paste' | 'file' | 'url';

/** What the catalog dialog hands to the Projects importer. */
export interface ProjectsImportHandoff {
  /** The source text exactly as the catalog dialog read it. */
  text: string;
  /**
   * The name the Projects analyzer reads the source under — the uploaded file's name, a name
   * derived from the URL's path, or `openapi-spec.yaml` / `.json` for a paste. Its extension is
   * only a hint; the analyzer sniffs the content.
   */
  filename: string;
  /** How the source reached the catalog dialog; picks the Projects intake it lands in. */
  method: ProjectsHandoffMethod;
  /** The URL the source was fetched from (`method: 'url'` only), else `null`. */
  url: string | null;
  /** The format the catalog dialog detected (e.g. `openapi-3.1`), or `null` when unknown. */
  format: string | null;
}

/** What the catalog dialog knows when it asks {@link projectsHandoffFor} for a payload. */
export interface ProjectsHandoffInput {
  /** The routing decision's destination; only `project` hands off. */
  destination: string;
  /** The intake method the source came in through (`paste`, `file`, `url`, `git`, …). */
  method: string;
  /** The source text; empty for an archive or a repository selection. */
  text: string;
  /** The catalog dialog's label for the source — the file name, the URL, or `Pasted source`. */
  label: string;
  /** The detected (or overridden) format, when known. */
  format: string | null;
}

const HANDOFF_METHODS: ReadonlySet<string> = new Set<ProjectsHandoffMethod>(['paste', 'file', 'url']);

/**
 * A name for a pasted source whose extension matches its syntax, so the analyzer's hint agrees
 * with the content: `.json` when it opens with `{`, else `.yaml`.
 *
 * @param text The pasted source.
 * @returns `openapi-spec.json` or `openapi-spec.yaml`.
 */
function pastedFilename(text: string): string {
  return text.trimStart().startsWith('{') ? 'openapi-spec.json' : 'openapi-spec.yaml';
}

/**
 * The last path segment of a URL (`https://x/specs/petstore.yaml` → `petstore.yaml`), falling back
 * to a paste-style name when the path has none (`https://x/` or a query-only route).
 *
 * @param url The URL the source was fetched from.
 * @param text The fetched source, used only for the fallback's extension.
 * @returns A file name for the analyzer.
 */
function urlFilename(url: string, text: string): string {
  try {
    const segment = new URL(url).pathname.split('/').filter(Boolean).pop();
    if (segment) return decodeURIComponent(segment);
  } catch {
    // Not a parseable URL — fall through to the paste-style name.
  }
  return pastedFilename(text);
}

/**
 * The hand-off payload for a catalog import, or `null` when this source cannot be handed off.
 *
 * Only a source routed to **Projects** that arrived as one text document — pasted, uploaded or
 * fetched from a URL — can be: an archive or a repository selection carries no single document,
 * so the catalog dialog keeps its **Open Projects** link for those.
 *
 * @param input The routing decision and the source the catalog dialog holds.
 * @returns The payload for the Projects importer, or `null`.
 */
export function projectsHandoffFor(input: ProjectsHandoffInput): ProjectsImportHandoff | null {
  if (input.destination !== 'project') return null;
  if (!HANDOFF_METHODS.has(input.method)) return null;
  if (!input.text.trim()) return null;
  const method = input.method as ProjectsHandoffMethod;
  const label = input.label.trim();
  const filename =
    method === 'url'
      ? urlFilename(label, input.text)
      : method === 'file' && label
        ? label
        : pastedFilename(input.text);
  return {
    text: input.text,
    filename,
    method,
    url: method === 'url' && label ? label : null,
    format: input.format,
  };
}

/**
 * The Projects importer's intake source for a hand-off: a paste lands in **Clipboard**, a file
 * in **File**, a URL in **URL** — so **Back** from Analyze opens the intake the user actually used.
 *
 * @param method The hand-off's method.
 * @returns The `ImportDialog` source key.
 */
export function projectsIntakeSourceFor(method: ProjectsHandoffMethod): 'clipboard' | 'file' | 'url' {
  return method === 'paste' ? 'clipboard' : method;
}
