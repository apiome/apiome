import YAML from 'yaml';
import type { editor } from 'monaco-editor';

export type PathsCodeFormat = 'json' | 'yaml';

/** Monaco `MarkerSeverity.Error` — avoid importing `monaco-editor` in Jest (no DOM). */
const MARKER_ERROR = 8;

/** Debounced parse for Paths Code view — returns Monaco markers for invalid YAML/JSON. */
export function markersForParsedText(text: string, fmt: PathsCodeFormat): editor.IMarkerData[] {
  try {
    if (fmt === 'json') {
      JSON.parse(text);
    } else {
      YAML.parse(text);
    }
    return [];
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Parse error';
    const firstLineLen = text.split('\n')[0]?.length ?? 1;
    return [
      {
        severity: MARKER_ERROR,
        message: msg,
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: 1,
        endColumn: Math.min(200, firstLineLen + 1),
      },
    ];
  }
}
