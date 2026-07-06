/**
 * Unit tests for the Verify problem-marker model (MFX-43.3, #4363).
 *
 * Covers the ticket's acceptance surface at the model level:
 *  1. Only findings with a real line number become located problems — no fake positions for
 *     location-less findings, ever.
 *  2. Severities map distinctly onto Monaco marker severities (validation always error; lint
 *     keeps error/warning/info).
 *  3. Markers/decorations are clamped into the document, and per-file filtering respects the
 *     "unfiled findings belong only to a single document" rule.
 *  4. A clicked line resolves back to its (worst-severity) problem.
 */

import {
  collectLocatedProblems,
  decorationsForProblems,
  gutterClassForSeverity,
  markersForProblems,
  problemAtLine,
  problemsForFile,
} from '../src/app/components/ade/dashboard/export/exportProblemMarkers';
import type {
  EmittedLintFinding,
  EmittedValidationFinding,
} from '../src/app/components/ade/dashboard/export/exportVerify';

const validationFindings: EmittedValidationFinding[] = [
  { message: 'Field number 0 is not allowed.', file: 'petstore.proto', line: 12, column: 3, keyword: 'buf.field-number' },
  { message: 'No location at all.', keyword: 'schema' },
  { message: 'Line but no file or column.', line: 4 },
];

const lintFindings: EmittedLintFinding[] = [
  { severity: 'warning', rule: 'proto-style', message: 'Prefer explicit package.', file: './petstore.proto', line: 1, column: 8 },
  { severity: 'info', rule: 'naming', message: 'Consider a suffix.', file: 'google/protobuf/timestamp.proto', line: 2 },
  { severity: 'error', rule: 'oas3-schema', message: 'Location-less lint.', file: 'petstore.proto' },
];

describe('collectLocatedProblems (MFX-43.3)', () => {
  it('keeps only findings with a real line number — no fake positions', () => {
    const problems = collectLocatedProblems(validationFindings, lintFindings);
    expect(problems.map((p) => p.id)).toEqual(['validation-0', 'validation-2', 'lint-0', 'lint-1']);
    // Every excluded finding is exactly the ones without a line.
    expect(problems.some((p) => p.message === 'No location at all.')).toBe(false);
    expect(problems.some((p) => p.message === 'Location-less lint.')).toBe(false);
  });

  it('maps severities: validation is always error, lint keeps its own', () => {
    const problems = collectLocatedProblems(validationFindings, lintFindings);
    expect(problems.find((p) => p.id === 'validation-0')?.severity).toBe('error');
    expect(problems.find((p) => p.id === 'lint-0')?.severity).toBe('warning');
    expect(problems.find((p) => p.id === 'lint-1')?.severity).toBe('info');
  });

  it('normalizes file paths and keeps null for unfiled findings', () => {
    const problems = collectLocatedProblems(validationFindings, lintFindings);
    // `./petstore.proto` normalizes to the manifest's `petstore.proto`.
    expect(problems.find((p) => p.id === 'lint-0')?.file).toBe('petstore.proto');
    expect(problems.find((p) => p.id === 'validation-2')?.file).toBeNull();
  });

  it('carries the rule (validation keyword / lint rule) and the original finding by identity', () => {
    const problems = collectLocatedProblems(validationFindings, lintFindings);
    expect(problems.find((p) => p.id === 'validation-0')?.rule).toBe('buf.field-number');
    expect(problems.find((p) => p.id === 'lint-0')?.rule).toBe('proto-style');
    expect(problems.find((p) => p.id === 'lint-0')?.finding).toBe(lintFindings[0]);
  });
});

describe('problemsForFile (MFX-43.3)', () => {
  const problems = collectLocatedProblems(validationFindings, lintFindings);

  it('matches by normalized path and orders by line, column, severity', () => {
    const forFile = problemsForFile(problems, 'petstore.proto');
    expect(forFile.map((p) => p.id)).toEqual(['lint-0', 'validation-0']);
  });

  it('excludes unfiled problems by default (multi-file bundles must not guess)', () => {
    const forFile = problemsForFile(problems, 'petstore.proto');
    expect(forFile.some((p) => p.file === null)).toBe(false);
  });

  it('admits unfiled problems only when the caller opts in (single-document artifacts)', () => {
    const forFile = problemsForFile(problems, 'petstore.proto', { includeUnfiled: true });
    expect(forFile.map((p) => p.id)).toEqual(['lint-0', 'validation-2', 'validation-0']);
  });
});

describe('markersForProblems (MFX-43.3)', () => {
  const text = 'syntax = "proto3";\n\npackage example;\nmessage Pet {}\n';

  it('builds one marker per problem with distinct Monaco severities', () => {
    const problems = collectLocatedProblems(
      [{ message: 'Bad field.', line: 4, column: 9 }],
      [
        { severity: 'warning', rule: 'w', message: 'Warn.', line: 3 },
        { severity: 'info', rule: 'i', message: 'Info.', line: 1 },
      ],
    );
    const markers = markersForProblems(problems, text);
    expect(markers.map((m) => m.severity)).toEqual([8, 4, 2]); // Error, Warning, Info
    expect(markers[0]).toMatchObject({
      message: 'Bad field.',
      startLineNumber: 4,
      startColumn: 9,
      endLineNumber: 4,
      endColumn: 'message Pet {}'.length + 1,
    });
    // A column-less problem squiggles the whole line.
    expect(markers[1]).toMatchObject({ startColumn: 1, endColumn: 'package example;'.length + 1 });
  });

  it('clamps out-of-range lines and columns into the document', () => {
    const problems = collectLocatedProblems([{ message: 'EOF+1.', line: 99, column: 500 }], []);
    const markers = markersForProblems(problems, 'one line only');
    expect(markers[0].startLineNumber).toBe(1);
    expect(markers[0].startColumn).toBeLessThanOrEqual('one line only'.length);
    expect(markers[0].endColumn).toBe('one line only'.length + 1);
  });

  it('keeps a visible one-character marker on an empty line', () => {
    const problems = collectLocatedProblems([{ message: 'Empty.', line: 2 }], []);
    const markers = markersForProblems(problems, 'a\n\nb');
    expect(markers[0]).toMatchObject({ startLineNumber: 2, startColumn: 1, endColumn: 2 });
  });
});

describe('decorationsForProblems (MFX-43.3)', () => {
  const text = 'a\nb\nc\n';

  it('dedupes gutter bars to one per line, keeping the worst severity', () => {
    const problems = collectLocatedProblems(
      [{ message: 'Error here.', line: 2 }],
      [{ severity: 'warning', rule: 'w', message: 'Warn same line.', line: 2 }],
    );
    const decorations = decorationsForProblems(problems, text);
    expect(decorations).toHaveLength(1);
    expect(decorations[0].options.linesDecorationsClassName).toBe(gutterClassForSeverity('error'));
    expect(decorations[0].options.isWholeLine).toBe(true);
  });

  it('adds a whole-line highlight for the selected problem', () => {
    const problems = collectLocatedProblems([{ message: 'Error.', line: 3 }], []);
    const decorations = decorationsForProblems(problems, text, 'validation-0');
    const highlight = decorations.find((d) => d.options.className === 'verify-problem-line--selected');
    expect(highlight).toBeDefined();
    expect(highlight?.range.startLineNumber).toBe(3);
  });

  it('adds no highlight when nothing is selected', () => {
    const problems = collectLocatedProblems([{ message: 'Error.', line: 3 }], []);
    const decorations = decorationsForProblems(problems, text, null);
    expect(decorations.some((d) => d.options.className === 'verify-problem-line--selected')).toBe(false);
  });
});

describe('problemAtLine (MFX-43.3)', () => {
  it('resolves a clicked line to its problem, worst severity first', () => {
    const problems = collectLocatedProblems(
      [{ message: 'Error.', line: 5 }],
      [{ severity: 'info', rule: 'i', message: 'Info same line.', line: 5, column: 1 }],
    );
    expect(problemAtLine(problems, 5)?.id).toBe('validation-0');
    expect(problemAtLine(problems, 6)).toBeNull();
  });
});
