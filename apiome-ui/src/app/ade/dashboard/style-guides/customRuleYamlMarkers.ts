/**
 * Map GOV-1.3 validation pointers onto Monaco marker ranges in a YAML document.
 *
 * Server 422 responses carry `detail.pointer` values such as
 * `rules.my-rule.then.functionOptions.match`; this module resolves them to line/column
 * spans for inline squiggles in the custom-rules editor.
 */

export interface YamlPointerRange {
  startLine: number;
  startColumn: number;
  endLine: number;
  endColumn: number;
}

/** Escape a string for use inside a RegExp character class alternative. */
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Resolve a dotted validation pointer to a single-line range in `yaml`.
 *
 * Walks pointer segments from the end until a `key:` line is found.
 */
export function pointerToYamlRange(pointer: string, yaml: string): YamlPointerRange {
  const lines = yaml.split('\n');
  const parts = pointer.split('.').filter(Boolean);
  if (parts.length === 0) {
    return { startLine: 1, startColumn: 1, endLine: 1, endColumn: Math.max(1, lines[0]?.length ?? 1) };
  }

  for (let pi = parts.length - 1; pi >= 0; pi--) {
    const key = parts[pi];
    const re = new RegExp(`^(\\s*)${escapeRegExp(key)}\\s*:`);
    for (let i = 0; i < lines.length; i++) {
      const match = lines[i].match(re);
      if (match) {
        const startColumn = (match[1]?.length ?? 0) + 1;
        const endColumn = Math.max(startColumn + 1, lines[i].length + 1);
        return { startLine: i + 1, startColumn, endLine: i + 1, endColumn };
      }
    }
  }

  const fallbackEnd = Math.max(1, (lines[0]?.length ?? 0) + 1);
  return { startLine: 1, startColumn: 1, endLine: 1, endColumn: fallbackEnd };
}

/** Monaco `MarkerSeverity` numerics — avoid importing `monaco-editor` in shared helpers. */
export const YAML_ERROR_MARKER_SEVERITY = 8;

export interface ServerValidationDetail {
  message?: string;
  pointer?: string;
}

/** Normalize a style-guides proxy error into pointer + message when present. */
export function parseValidationDetail(error: unknown): ServerValidationDetail | null {
  if (!error || typeof error !== 'object') return null;
  const obj = error as Record<string, unknown>;
  const detail = obj.detail ?? obj.error ?? obj;
  if (!detail || typeof detail !== 'object') return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.message === 'string') {
    return { message: d.message, pointer: typeof d.pointer === 'string' ? d.pointer : '' };
  }
  return null;
}
