/**
 * Emitted-artifact preview helpers (MFX-6.3, #3857) — pure unit tests.
 *
 * Covers the ticket's preview semantics:
 *  1. Syntax detection from media type (preferred) and filename extension (fallback).
 *  2. Client-side well-formedness validation for JSON and YAML; honest "unchecked" for
 *     formats without a client-side parser.
 *  3. Status-badge derivation — the "valid · round-trip OK" chip and its lossy/invalid/
 *     neutral variants, with hints stating the basis of every claim.
 *  4. The size and zip-filename helpers used by the preview card and download buttons.
 */

import {
  buildArtifactBadge,
  detectArtifactSyntax,
  formatByteSize,
  reportPredictsCleanRoundTrip,
  utf8ByteLength,
  validateEmittedArtifact,
  zipFilenameFor,
  type EmittedArtifact,
} from '../src/app/components/ade/dashboard/export/exportArtifactPreview';
import type { LossinessReport } from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

/** Build an artifact fixture with sensible defaults. */
function artifact(overrides: Partial<EmittedArtifact>): EmittedArtifact {
  return { filename: 'petstore.json', mediaType: 'application/json', text: '{}', ...overrides };
}

/** Build a loss report with the given kind counts (items are irrelevant to the badge). */
function report(counts: Partial<Record<string, number>>): LossinessReport {
  return {
    items: [],
    kind_counts: { drop: 0, approx: 0, synth: 0, ok: 0, ...counts },
    severity_counts: { info: 0, warn: 0, critical: 0 },
  };
}

describe('detectArtifactSyntax', () => {
  it('prefers the media type over the filename', () => {
    expect(detectArtifactSyntax('petstore.txt', 'application/json')).toBe('json');
    expect(detectArtifactSyntax('petstore.json', 'application/x-yaml')).toBe('yaml');
  });

  it('falls back to the filename extension when the media type is generic', () => {
    expect(detectArtifactSyntax('petstore.json', 'text/plain')).toBe('json');
    expect(detectArtifactSyntax('petstore.yaml', '')).toBe('yaml');
    expect(detectArtifactSyntax('petstore.yml', '')).toBe('yaml');
  });

  it('treats Avro .avsc files as JSON', () => {
    expect(detectArtifactSyntax('User.avsc', 'text/plain')).toBe('json');
  });

  it('reports no client-side parser for proto/GraphQL artifacts', () => {
    expect(detectArtifactSyntax('petstore.proto', 'text/plain')).toBe('none');
    expect(detectArtifactSyntax('schema.graphql', '')).toBe('none');
  });
});

describe('validateEmittedArtifact', () => {
  it('accepts well-formed JSON', () => {
    const result = validateEmittedArtifact(artifact({ text: '{"openapi":"3.1.0"}' }));
    expect(result).toMatchObject({ syntax: 'json', checked: true, valid: true, error: null });
  });

  it('rejects malformed JSON with the parse error', () => {
    const result = validateEmittedArtifact(artifact({ text: '{"openapi": ' }));
    expect(result.checked).toBe(true);
    expect(result.valid).toBe(false);
    expect(result.error).toBeTruthy();
  });

  it('accepts well-formed YAML', () => {
    const result = validateEmittedArtifact(
      artifact({ filename: 'petstore.yaml', mediaType: 'application/x-yaml', text: 'openapi: 3.1.0\n' }),
    );
    expect(result).toMatchObject({ syntax: 'yaml', checked: true, valid: true });
  });

  it('rejects malformed YAML', () => {
    const result = validateEmittedArtifact(
      artifact({ filename: 'petstore.yaml', mediaType: 'text/yaml', text: 'a: [unclosed' }),
    );
    expect(result.valid).toBe(false);
    expect(result.error).toBeTruthy();
  });

  it('skips (never fakes) validation for formats without a client-side parser', () => {
    const result = validateEmittedArtifact(
      artifact({ filename: 'petstore.proto', mediaType: 'text/plain', text: 'syntax = "proto3";' }),
    );
    expect(result).toMatchObject({ syntax: 'none', checked: false, valid: false, error: null });
  });
});

describe('reportPredictsCleanRoundTrip', () => {
  it('is clean when only OK entries exist', () => {
    expect(reportPredictsCleanRoundTrip(report({ ok: 12 }))).toBe(true);
  });

  it('is lossy when anything drops, approximates, or synthesizes', () => {
    expect(reportPredictsCleanRoundTrip(report({ ok: 10, drop: 1 }))).toBe(false);
    expect(reportPredictsCleanRoundTrip(report({ approx: 2 }))).toBe(false);
    expect(reportPredictsCleanRoundTrip(report({ synth: 1 }))).toBe(false);
  });
});

describe('buildArtifactBadge', () => {
  const validJson = validateEmittedArtifact(artifact({ text: '{}' }));
  const invalidJson = validateEmittedArtifact(artifact({ text: '{' }));
  const unchecked = validateEmittedArtifact(
    artifact({ filename: 'petstore.proto', mediaType: 'text/plain', text: 'syntax = "proto3";' }),
  );

  it('shows the mockup badge — "valid · round-trip OK" — for a parsed doc with a clean report', () => {
    const badge = buildArtifactBadge(validJson, report({ ok: 5 }));
    expect(badge.tone).toBe('green');
    expect(badge.label).toBe('valid · round-trip OK');
    expect(badge.hint).toContain('well-formed JSON');
    expect(badge.hint).toContain('clean round-trip');
  });

  it('shows an amber lossy badge when the report predicts degradation', () => {
    const badge = buildArtifactBadge(validJson, report({ ok: 5, drop: 2 }));
    expect(badge.tone).toBe('amber');
    expect(badge.label).toBe('valid · lossy round-trip');
    expect(badge.hint).toContain('degrades');
  });

  it('flags a failed parse in red regardless of the report', () => {
    const badge = buildArtifactBadge(invalidJson, report({ ok: 5 }));
    expect(badge.tone).toBe('red');
    expect(badge.label).toBe('invalid JSON');
    expect(badge.hint).toContain('failed to parse');
  });

  it('claims only the round-trip half when no client-side parser applies', () => {
    expect(buildArtifactBadge(unchecked, report({ ok: 3 }))).toMatchObject({
      tone: 'green',
      label: 'round-trip OK',
    });
    expect(buildArtifactBadge(unchecked, report({ drop: 1 }))).toMatchObject({
      tone: 'amber',
      label: 'lossy round-trip',
    });
  });

  it('degrades honestly when the fidelity report is unavailable', () => {
    expect(buildArtifactBadge(validJson, null)).toMatchObject({ tone: 'green', label: 'valid' });
    const neutral = buildArtifactBadge(unchecked, null);
    expect(neutral.tone).toBe('neutral');
    expect(neutral.label).toBe('emitted');
    expect(neutral.hint).toContain('unavailable');
  });
});

describe('size + zip filename helpers', () => {
  it('measures UTF-8 byte length, not UTF-16 code units', () => {
    expect(utf8ByteLength('abc')).toBe(3);
    expect(utf8ByteLength('é')).toBe(2);
  });

  it('formats byte counts across magnitudes', () => {
    expect(formatByteSize(312)).toBe('312 B');
    expect(formatByteSize(4300)).toBe('4.2 KB');
    expect(formatByteSize(1_400_000)).toBe('1.3 MB');
  });

  it('derives the zip filename by swapping the extension', () => {
    expect(zipFilenameFor('petstore.proto')).toBe('petstore.zip');
    expect(zipFilenameFor('openapi.3.1.json')).toBe('openapi.3.1.zip');
    expect(zipFilenameFor('README')).toBe('README.zip');
    expect(zipFilenameFor('')).toBe('export.zip');
  });
});
