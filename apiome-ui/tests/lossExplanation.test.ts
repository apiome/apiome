/**
 * lossExplanation — the evidence drawer's pure presentation helpers (EFP-2.3, #4815).
 *
 * Covers the ticket's acceptance criteria at the module level:
 *  1. Every canonical reason code maps to exactly one truthful cause category, and the five
 *     loss categories (format limit / emitter gap / source incomplete / option excluded /
 *     redacted) are mutually distinguishable by label and by distinction line.
 *  2. A destination limitation is never claimed for an apiome-side cause: emitter and
 *     toolchain gaps read as emitter gaps.
 *  3. Safe remediation actions only exist where an in-export change genuinely helps.
 *  4. Documentation links are host-allowlisted, version-disclosing, and accessibly named;
 *     an unsafe URL yields no link at all.
 *  5. Manifest provenance extraction guards every field of the untyped target block.
 *  6. Evidence prose sanitisation strips control/bidi characters and caps length.
 */

import {
  categoryForReason,
  documentationLink,
  manifestProvenance,
  MAX_EVIDENCE_PROSE_LENGTH,
  reasonCategoryPresentation,
  remediationActionsForReason,
  sanitizeEvidenceProse,
  type ReasonCategoryKey,
} from '../src/app/components/ade/dashboard/export/lossExplanation';
import { REASON_CODES } from '../src/app/components/ade/dashboard/export/capabilityRegistry';
import type { DocumentationEvidence } from '../src/app/components/ade/dashboard/export/capabilityRegistry';

describe('categoryForReason — the reason → cause-category mapping', () => {
  it.each([
    ['destination_unsupported', 'format-limit'],
    ['emitter_unsupported', 'emitter-gap'],
    ['target_tool_unavailable', 'emitter-gap'],
    ['source_incomplete', 'source-incomplete'],
    ['source_parse_limit', 'source-incomplete'],
    ['option_excluded', 'option-excluded'],
    ['security_redacted', 'redacted'],
    ['not_applicable', 'not-applicable'],
  ] as const)('maps %s to %s', (reason, category) => {
    expect(categoryForReason(reason)).toBe(category);
  });

  it('maps every canonical reason code to some category', () => {
    for (const code of REASON_CODES) {
      expect(categoryForReason(code)).not.toBeNull();
    }
  });

  it('yields no category for an unknown or absent reason (never guesses)', () => {
    expect(categoryForReason('made_up_reason')).toBeNull();
    expect(categoryForReason(null)).toBeNull();
    expect(categoryForReason(undefined)).toBeNull();
  });

  it('never claims a destination limitation for an apiome-side cause (EFP-2.3)', () => {
    // Only the genuine destination limit reads as a format limit; emitter and toolchain
    // gaps are apiome's, not the format's.
    expect(categoryForReason('emitter_unsupported')).not.toBe('format-limit');
    expect(categoryForReason('target_tool_unavailable')).not.toBe('format-limit');
    expect(categoryForReason('destination_unsupported')).toBe('format-limit');
  });
});

describe('reasonCategoryPresentation — the five distinguishable cause categories', () => {
  const LOSS_CATEGORIES: ReasonCategoryKey[] = [
    'format-limit',
    'emitter-gap',
    'source-incomplete',
    'option-excluded',
    'redacted',
  ];

  it('gives every category a unique label and a unique distinction line', () => {
    const all: ReasonCategoryKey[] = [...LOSS_CATEGORIES, 'not-applicable'];
    const labels = all.map((key) => reasonCategoryPresentation(key).label);
    const distinctions = all.map((key) => reasonCategoryPresentation(key).distinction);
    expect(new Set(labels).size).toBe(all.length);
    expect(new Set(distinctions).size).toBe(all.length);
  });

  it('phrases each loss distinction to identify its cause', () => {
    expect(reasonCategoryPresentation('format-limit').distinction).toMatch(/format cannot represent/i);
    expect(reasonCategoryPresentation('emitter-gap').distinction).toMatch(/apiome does not yet emit/i);
    expect(reasonCategoryPresentation('source-incomplete').distinction).toMatch(/source/i);
    expect(reasonCategoryPresentation('option-excluded').distinction).toMatch(/option/i);
    expect(reasonCategoryPresentation('redacted').distinction).toMatch(/security policy/i);
  });

  it('marks the emitter gap as possibly supported by the format itself', () => {
    expect(reasonCategoryPresentation('emitter-gap').distinction).toMatch(
      /format itself may support it/i,
    );
  });
});

describe('remediationActionsForReason — safe, navigation-only remediation', () => {
  it('offers a target change for a genuine format limit', () => {
    const actions = remediationActionsForReason('destination_unsupported');
    expect(actions).toHaveLength(1);
    expect(actions[0].kind).toBe('change-target');
    expect(actions[0].label).toMatch(/different target/i);
  });

  it('offers an options change for an option exclusion', () => {
    const actions = remediationActionsForReason('option_excluded');
    expect(actions).toHaveLength(1);
    expect(actions[0].kind).toBe('change-options');
  });

  it.each([
    'emitter_unsupported',
    'target_tool_unavailable',
    'source_incomplete',
    'source_parse_limit',
    'security_redacted',
    'not_applicable',
  ])('offers no in-export action for %s (fixed outside this export)', (reason) => {
    expect(remediationActionsForReason(reason)).toEqual([]);
  });

  it('offers nothing for an unknown or absent reason', () => {
    expect(remediationActionsForReason('made_up')).toEqual([]);
    expect(remediationActionsForReason(null)).toEqual([]);
  });
});

describe('documentationLink — safe, version-disclosing, accessibly named', () => {
  const SAFE_EVIDENCE: DocumentationEvidence = {
    specification: 'OpenAPI Specification',
    version: '3.1',
    url: 'https://spec.openapis.org/oas/v3.1.0',
    anchor: '#paths-object',
    documentation_unavailable: false,
    note: null,
  };

  it('builds the href from the URL plus its anchor', () => {
    expect(documentationLink(SAFE_EVIDENCE)?.href).toBe(
      'https://spec.openapis.org/oas/v3.1.0#paths-object',
    );
  });

  it('discloses the specification and version in the visible text', () => {
    expect(documentationLink(SAFE_EVIDENCE)?.text).toBe('OpenAPI Specification (3.1)');
  });

  it('discloses the host and new-tab behaviour in the accessible name', () => {
    const label = documentationLink(SAFE_EVIDENCE)?.ariaLabel ?? '';
    expect(label).toContain('OpenAPI Specification (3.1)');
    expect(label).toContain('spec.openapis.org');
    expect(label).toMatch(/opens in a new tab/i);
  });

  it('falls back to a generic name when the specification is unnamed, without inventing a version', () => {
    const link = documentationLink({ ...SAFE_EVIDENCE, specification: null, version: null });
    expect(link?.text).toBe('Destination documentation');
    expect(link?.text).not.toContain('(');
  });

  it('yields no link for an off-allowlist or non-https URL', () => {
    expect(documentationLink({ ...SAFE_EVIDENCE, url: 'https://evil.example.com/spec' })).toBeNull();
    expect(documentationLink({ ...SAFE_EVIDENCE, url: 'http://spec.openapis.org/oas' })).toBeNull();
    expect(documentationLink({ ...SAFE_EVIDENCE, url: 'javascript:alert(1)' })).toBeNull();
  });

  it('yields no link for absent evidence or an absent URL', () => {
    expect(documentationLink(null)).toBeNull();
    expect(documentationLink(undefined)).toBeNull();
    expect(
      documentationLink({ ...SAFE_EVIDENCE, url: null, documentation_unavailable: true }),
    ).toBeNull();
  });
});

describe('manifestProvenance — guarded extraction from the untyped target block', () => {
  it('extracts the emitter, registry, and apiome versions', () => {
    expect(
      manifestProvenance({
        emitter_version: '1.4.0',
        registry_version: '2025.07.01',
        apiome_version: '1.9.0',
      }),
    ).toEqual({ emitterVersion: '1.4.0', registryVersion: '2025.07.01', apiomeVersion: '1.9.0' });
  });

  it('reads a missing, empty, or non-string field as null', () => {
    expect(manifestProvenance({ emitter_version: 42, registry_version: '', label: 'x' })).toEqual({
      emitterVersion: null,
      registryVersion: null,
      apiomeVersion: null,
    });
  });

  it('reads an absent block as all-null', () => {
    expect(manifestProvenance(null)).toEqual({
      emitterVersion: null,
      registryVersion: null,
      apiomeVersion: null,
    });
    expect(manifestProvenance(undefined)).toEqual({
      emitterVersion: null,
      registryVersion: null,
      apiomeVersion: null,
    });
  });
});

describe('sanitizeEvidenceProse — defence-in-depth for longer evidence text', () => {
  it('passes ordinary prose through unchanged', () => {
    expect(sanitizeEvidenceProse('The uniqueness constraint becomes a description note.')).toBe(
      'The uniqueness constraint becomes a description note.',
    );
  });

  it('strips control and bidi-override characters and collapses whitespace', () => {
    expect(sanitizeEvidenceProse('a\u0007b\u202Ec\n\n  d\te')).toBe('abc d e');
  });

  it('keeps markup characters — prose only ever renders as text nodes', () => {
    expect(sanitizeEvidenceProse('<b>bold</b> & "quoted"')).toBe('<b>bold</b> & "quoted"');
  });

  it('returns null when nothing survives', () => {
    expect(sanitizeEvidenceProse(null)).toBeNull();
    expect(sanitizeEvidenceProse(undefined)).toBeNull();
    expect(sanitizeEvidenceProse('  ‪‫  ')).toBeNull();
  });

  it('caps runaway prose with an ellipsis', () => {
    const long = 'x'.repeat(MAX_EVIDENCE_PROSE_LENGTH * 3);
    const result = sanitizeEvidenceProse(long) as string;
    expect(result).toHaveLength(MAX_EVIDENCE_PROSE_LENGTH);
    expect(result.endsWith('…')).toBe(true);
  });
});
