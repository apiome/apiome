/**
 * Verify-finding → Monaco problem-marker model (MFX-43.3, #4363).
 *
 * The Verify lenses list validation failures (MFX-42.2) and lint findings (MFX-42.3); enterprise
 * users expect IDE behaviour on top of that list — squiggles at the offending line, a coloured
 * gutter bar, and click-through both ways. This module is the pure backbone of that behaviour:
 *
 * - {@link collectLocatedProblems} folds both lenses' findings into one **located problem** list —
 *   only findings that carry a real 1-based line number qualify; location-less findings stay
 *   list-only in the lenses and never get a fabricated position (MFX-43.3 acceptance);
 * - {@link problemsForFile} picks the problems belonging to one bundle file (with an opt-in for
 *   unfiled findings, which are attributable only when the artifact is a single document);
 * - {@link markersForProblems} turns problems into Monaco `IMarkerData` squiggles, clamped to the
 *   document so a tool's slightly-off location (e.g. EOF+1) never produces an invalid range;
 * - {@link decorationsForProblems} builds the matching gutter bars (worst severity per line) plus
 *   the selected problem's whole-line highlight;
 * - {@link problemAtLine} resolves a clicked editor line back to its problem (worst severity
 *   first), completing the marker → finding direction.
 *
 * Everything here is pure (no React, no Monaco import at runtime) so it unit-tests without a DOM —
 * mirroring `./exportBundle.ts` and the `paths-code-markers.ts` precedent: `monaco-editor` is a
 * **type-only** import and the `MarkerSeverity` numerics are hardcoded (Error=8, Warning=4,
 * Info=2), because importing Monaco at runtime breaks Jest.
 */

import type { editor } from 'monaco-editor';
import type { LintSeverity } from '../../../../utils/version-lint-report';
import type { EmittedLintFinding, EmittedValidationFinding } from './exportVerify';
import { normalizeBundlePath } from './exportBundle';

/** Which Verify lens a located problem came from. */
export type ProblemSource = 'validation' | 'lint';

/**
 * One Verify finding that carries a usable in-document location (a 1-based line), unified across
 * the validation and lint lenses so the marker/gutter/navigation layers handle both identically.
 */
export interface LocatedProblem {
  /** Stable id derived from the finding's lens and index (e.g. `lint-2`); keys UI rows. */
  id: string;
  /** Which lens produced the finding. */
  source: ProblemSource;
  /** Marker severity: validation failures are always errors; lint keeps its own severity. */
  severity: LintSeverity;
  /** The finding's human-readable message. */
  message: string;
  /** The rule that fired — a validator `keyword` or a lint `rule` — when known. */
  rule: string | null;
  /** The normalized bundle path the finding names, or null when it names no file. */
  file: string | null;
  /** The 1-based line the tool reported (what makes the finding *located*). */
  line: number;
  /** The 1-based column the tool reported, or null when it reported only a line. */
  column: number | null;
  /** The original lens finding, so UI layers can match a lens row to its problem by identity. */
  finding: EmittedValidationFinding | EmittedLintFinding;
}

/** A one-shot "open this problem in the editor" request; `nonce` distinguishes repeat clicks. */
export interface ProblemRevealRequest {
  /** The problem to open (its file, when named, and its line/column). */
  problem: LocatedProblem;
  /** Monotonic request id so revealing the same problem twice still re-triggers. */
  nonce: number;
}

/**
 * Monaco `MarkerSeverity` numerics — hardcoded so this module never imports `monaco-editor` at
 * runtime (no DOM in Jest); the `paths-code-markers.ts` convention. Hint=1 is unused here.
 */
const MARKER_SEVERITY: Record<LintSeverity, number> = { error: 8, warning: 4, info: 2 };

/** Severity rank for "worst first" ordering: error before warning before info. */
const SEVERITY_RANK: Record<LintSeverity, number> = { error: 0, warning: 1, info: 2 };

/** The marker owner namespace passed to `setModelMarkers` for Verify problems. */
export const PROBLEM_MARKER_OWNER = 'apiome-verify';

/** Whether a lens finding carries a usable location (a positive, finite 1-based line). */
function hasUsableLine(line: number | null | undefined): line is number {
  return typeof line === 'number' && Number.isFinite(line) && line >= 1;
}

/**
 * Fold the two Verify lenses' findings into the unified located-problem list. Only findings with a
 * real line number qualify — a finding without one has no position to mark, and inventing one is
 * exactly what MFX-43.3 forbids ("no fake positions"). Validation failures are error-severity by
 * definition (they block delivery); lint findings keep their own severity. File names are
 * normalized with {@link normalizeBundlePath} so they correlate to bundle manifest paths the same
 * way `countFindingsByFile` does.
 *
 * @param validationFindings The validation lens's findings (MFX-42.2), in server order.
 * @param lintFindings The lint lens's findings (MFX-42.3), in server order.
 * @returns The located problems, validation first then lint, each in server order.
 */
export function collectLocatedProblems(
  validationFindings: EmittedValidationFinding[],
  lintFindings: EmittedLintFinding[],
): LocatedProblem[] {
  const problems: LocatedProblem[] = [];
  validationFindings.forEach((finding, index) => {
    if (!hasUsableLine(finding.line)) return;
    problems.push({
      id: `validation-${index}`,
      source: 'validation',
      severity: 'error',
      message: finding.message,
      rule: finding.keyword ?? null,
      file: finding.file ? normalizeBundlePath(finding.file) || null : null,
      line: Math.floor(finding.line),
      column: hasUsableLine(finding.column) ? Math.floor(finding.column) : null,
      finding,
    });
  });
  lintFindings.forEach((finding, index) => {
    if (!hasUsableLine(finding.line)) return;
    problems.push({
      id: `lint-${index}`,
      source: 'lint',
      severity: finding.severity,
      message: finding.message,
      rule: finding.rule ?? null,
      file: finding.file ? normalizeBundlePath(finding.file) || null : null,
      line: Math.floor(finding.line),
      column: hasUsableLine(finding.column) ? Math.floor(finding.column) : null,
      finding,
    });
  });
  return problems;
}

/**
 * The problems belonging to one file, ordered for a problems list (line, then column, then worst
 * severity). A problem matches when it names the same normalized path. Problems that name **no**
 * file are attributable only when the whole artifact is a single document — pass
 * `includeUnfiled: true` there (single-file preview); a multi-file bundle must leave them
 * list-only, because guessing their file would fabricate a location.
 *
 * @param problems The located problems (from {@link collectLocatedProblems}).
 * @param path The bundle path to filter to (normalized internally).
 * @param opts `includeUnfiled` admits problems with no file name (single-document artifacts only).
 * @returns The file's problems in display order.
 */
export function problemsForFile(
  problems: LocatedProblem[],
  path: string,
  opts: { includeUnfiled?: boolean } = {},
): LocatedProblem[] {
  const target = normalizeBundlePath(path);
  return problems
    .filter((p) => (p.file ? p.file === target : Boolean(opts.includeUnfiled)))
    .sort(
      (a, b) =>
        a.line - b.line ||
        (a.column ?? 1) - (b.column ?? 1) ||
        SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
    );
}

/** Clamp a 1-based value into `[1, max]`. */
function clamp(value: number, max: number): number {
  return Math.min(Math.max(1, value), Math.max(1, max));
}

/** Split a document into lines, tolerating `\r\n` (the `\r` never counts toward line length). */
function documentLines(text: string): string[] {
  return text.split('\n').map((line) => (line.endsWith('\r') ? line.slice(0, -1) : line));
}

/**
 * Build the Monaco squiggle markers for one file's problems. Each marker runs from the reported
 * column (or the line start) to the end of that line, so a column-less finding still shows a
 * visible squiggle without pretending to know a span the tool never reported. Lines/columns are
 * clamped into the document (validators occasionally report EOF+1) so Monaco never receives an
 * out-of-range marker.
 *
 * @param problems The file's problems (from {@link problemsForFile}).
 * @param text The file's text, used to clamp lines/columns to real positions.
 * @returns Marker data for `setModelMarkers`, one marker per problem.
 */
export function markersForProblems(
  problems: LocatedProblem[],
  text: string,
): editor.IMarkerData[] {
  const lines = documentLines(text);
  return problems.map((problem) => {
    const lineNumber = clamp(problem.line, lines.length);
    const lineLength = lines[lineNumber - 1]?.length ?? 0;
    const startColumn = problem.column === null ? 1 : clamp(problem.column, Math.max(1, lineLength));
    // To the end of the line, but always at least one character wide (empty lines included).
    const endColumn = Math.max(lineLength + 1, startColumn + 1);
    return {
      severity: MARKER_SEVERITY[problem.severity],
      message: problem.message,
      code: problem.rule ?? undefined,
      source: problem.source === 'validation' ? 'verify · validation' : 'verify · lint',
      startLineNumber: lineNumber,
      startColumn,
      endLineNumber: lineNumber,
      endColumn,
    };
  });
}

/** The gutter-bar CSS class for a problem severity (defined in `globals.css`). */
export function gutterClassForSeverity(severity: LintSeverity): string {
  return `verify-problem-gutter verify-problem-gutter--${severity}`;
}

/**
 * Build the gutter-bar (and selected-line highlight) decorations for one file's problems. Gutter
 * bars are deduplicated to one per line, keeping the worst severity, so stacked findings never
 * paint over each other; the selected problem additionally highlights its whole line so a lens →
 * editor jump is visibly anchored.
 *
 * @param problems The file's problems (from {@link problemsForFile}).
 * @param text The file's text, used to clamp lines to real positions.
 * @param selectedId The currently highlighted problem's id, or null when none is selected.
 * @returns Delta decorations for `createDecorationsCollection`.
 */
export function decorationsForProblems(
  problems: LocatedProblem[],
  text: string,
  selectedId: string | null = null,
): editor.IModelDeltaDecoration[] {
  const lineCount = documentLines(text).length;
  const worstByLine = new Map<number, LintSeverity>();
  let selectedLine: number | null = null;
  for (const problem of problems) {
    const line = clamp(problem.line, lineCount);
    const current = worstByLine.get(line);
    if (current === undefined || SEVERITY_RANK[problem.severity] < SEVERITY_RANK[current]) {
      worstByLine.set(line, problem.severity);
    }
    if (problem.id === selectedId) selectedLine = line;
  }

  const decorations: editor.IModelDeltaDecoration[] = [];
  for (const [line, severity] of worstByLine) {
    decorations.push({
      range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 1 },
      options: { isWholeLine: true, linesDecorationsClassName: gutterClassForSeverity(severity) },
    });
  }
  if (selectedLine !== null) {
    decorations.push({
      range: {
        startLineNumber: selectedLine,
        startColumn: 1,
        endLineNumber: selectedLine,
        endColumn: 1,
      },
      options: { isWholeLine: true, className: 'verify-problem-line--selected' },
    });
  }
  return decorations;
}

/**
 * The problem to highlight for a clicked editor line — the marker → finding direction. When
 * several problems share the line the worst severity wins (then the earliest column), matching
 * which gutter bar the user sees.
 *
 * @param problems The file's problems (from {@link problemsForFile}).
 * @param line The clicked 1-based line.
 * @returns The line's problem, or null when the line has none.
 */
export function problemAtLine(problems: LocatedProblem[], line: number): LocatedProblem | null {
  const hits = problems.filter((p) => p.line === line);
  if (hits.length === 0) return null;
  const outranks = (a: LocatedProblem, b: LocatedProblem): boolean => {
    const bySeverity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
    if (bySeverity !== 0) return bySeverity < 0;
    return (a.column ?? 1) < (b.column ?? 1);
  };
  return hits.reduce((best, p) => (outranks(p, best) ? p : best));
}
