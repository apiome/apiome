/**
 * capabilityRegistry — destination capability & documentation registry contract (EFP-1.2, #4811).
 *
 * Covers the UI-side contract guards: the canonical reason-code set, the documentation-URL
 * host allowlist, the safe-fallback sanitiser, and the whole-snapshot validator — the checks
 * that let the export UI reject an unknown reason code or an unsafe link before rendering.
 */

import {
  ALLOWED_DOCUMENTATION_HOSTS,
  assertKnownReasonCode,
  assertSafeDocumentationUrl,
  isKnownReasonCode,
  isSafeDocumentationUrl,
  REASON_CODES,
  sanitizeDocumentationEvidence,
  validateRegistrySnapshot,
  type CapabilityRegistrySnapshot,
  type DestinationCapability,
  type DocumentationEvidence,
  type ReasonExplanation,
} from '../src/app/components/ade/dashboard/export/capabilityRegistry';

describe('REASON_CODES', () => {
  it('is exactly the eight-member canonical taxonomy', () => {
    expect([...REASON_CODES].sort()).toEqual(
      [
        'destination_unsupported',
        'emitter_unsupported',
        'not_applicable',
        'option_excluded',
        'security_redacted',
        'source_incomplete',
        'source_parse_limit',
        'target_tool_unavailable',
      ].sort(),
    );
  });
});

describe('isKnownReasonCode / assertKnownReasonCode', () => {
  it('accepts every canonical reason code', () => {
    for (const code of REASON_CODES) {
      expect(isKnownReasonCode(code)).toBe(true);
      expect(assertKnownReasonCode(code)).toBe(code);
    }
  });

  it('rejects an unknown reason code', () => {
    expect(isKnownReasonCode('destination_broken')).toBe(false);
    expect(isKnownReasonCode('')).toBe(false);
    expect(() => assertKnownReasonCode('lost')).toThrow(/unknown projection reason code/);
  });
});

describe('isSafeDocumentationUrl', () => {
  it('accepts an https link to an allowlisted host', () => {
    expect(isSafeDocumentationUrl('https://spec.openapis.org/oas/v3.1.0.html')).toBe(true);
    expect(isSafeDocumentationUrl('https://protobuf.dev/programming-guides/proto3/')).toBe(true);
  });

  it('rejects a non-https scheme, including javascript: and data:', () => {
    expect(isSafeDocumentationUrl('http://spec.openapis.org/oas/v3.1.0.html')).toBe(false);
    expect(isSafeDocumentationUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeDocumentationUrl('data:text/html,<script>alert(1)</script>')).toBe(false);
  });

  it('rejects an off-allowlist host and a look-alike host', () => {
    expect(isSafeDocumentationUrl('https://evil.test/oas')).toBe(false);
    expect(isSafeDocumentationUrl('https://spec.openapis.org.evil.test/oas')).toBe(false);
  });

  it('rejects embedded credentials and an explicit port', () => {
    expect(isSafeDocumentationUrl('https://user:pass@spec.openapis.org/oas')).toBe(false);
    expect(isSafeDocumentationUrl('https://spec.openapis.org:8443/oas')).toBe(false);
  });

  it('rejects empty / nullish input', () => {
    expect(isSafeDocumentationUrl('')).toBe(false);
    expect(isSafeDocumentationUrl(null)).toBe(false);
    expect(isSafeDocumentationUrl(undefined)).toBe(false);
    expect(isSafeDocumentationUrl('not a url')).toBe(false);
  });

  it('assertSafeDocumentationUrl throws on an unsafe URL and returns a safe one', () => {
    expect(assertSafeDocumentationUrl('https://avro.apache.org/docs/1.11.1/specification/')).toContain(
      'avro.apache.org',
    );
    expect(() => assertSafeDocumentationUrl('http://evil.test')).toThrow(/unsafe documentation URL/);
  });

  it('allowlist has no obviously unsafe host', () => {
    for (const host of ALLOWED_DOCUMENTATION_HOSTS) {
      expect(host).toBe(host.toLowerCase());
      expect(host).not.toContain('/');
      expect(host).not.toContain('@');
    }
  });
});

describe('sanitizeDocumentationEvidence', () => {
  const evidence = (overrides: Partial<DocumentationEvidence>): DocumentationEvidence => ({
    specification: 'OpenAPI Specification',
    version: '3.1.0',
    url: 'https://spec.openapis.org/oas/v3.1.0.html',
    anchor: null,
    documentation_unavailable: false,
    note: null,
    ...overrides,
  });

  it('returns safe-URL evidence unchanged', () => {
    const safe = evidence({});
    expect(sanitizeDocumentationEvidence(safe)).toBe(safe);
  });

  it('returns url-less evidence unchanged', () => {
    const none = evidence({ url: null, documentation_unavailable: true });
    expect(sanitizeDocumentationEvidence(none)).toBe(none);
  });

  it('strips an unsafe URL to the documentation-unavailable fallback', () => {
    const unsafe = evidence({ url: 'http://evil.test/oas' });
    const cleaned = sanitizeDocumentationEvidence(unsafe);
    expect(cleaned.url).toBeNull();
    expect(cleaned.anchor).toBeNull();
    expect(cleaned.documentation_unavailable).toBe(true);
    expect(cleaned.note).toMatch(/allowlist/);
  });
});

describe('validateRegistrySnapshot', () => {
  const reason = (overrides: Partial<ReasonExplanation>): ReasonExplanation => ({
    reason: 'destination_unsupported',
    category_label: 'Destination limit',
    summary_template: 'The destination cannot represent {construct}.',
    remediation: 'Choose another format.',
    destination_documentation_applies: true,
    ...overrides,
  });

  const destination = (overrides: Partial<DestinationCapability>): DestinationCapability => ({
    key: 'openapi',
    format: 'openapi-3.1',
    label: 'OpenAPI',
    availability: 'available',
    documentation: {
      specification: 'OpenAPI Specification',
      version: '3.1.0',
      url: 'https://spec.openapis.org/oas/v3.1.0.html',
      anchor: null,
      documentation_unavailable: false,
      note: null,
    },
    emitter_version: '1',
    registry_version: '1',
    review_date: '2026-07-15',
    ...overrides,
  });

  const snapshot = (overrides: Partial<CapabilityRegistrySnapshot>): CapabilityRegistrySnapshot => ({
    version: '1',
    review_date: '2026-07-15',
    reason_codes: [...REASON_CODES],
    reasons: [reason({})],
    destinations: [destination({})],
    ...overrides,
  });

  it('reports no issues for a clean snapshot', () => {
    expect(validateRegistrySnapshot(snapshot({}))).toEqual([]);
  });

  it('rejects an unknown reason code in reason_codes', () => {
    const issues = validateRegistrySnapshot(snapshot({ reason_codes: ['destination_unsupported', 'bogus'] }));
    expect(issues).toHaveLength(1);
    expect(issues[0].path).toBe('reason_codes[1]');
  });

  it('rejects an unknown reason code in reasons[]', () => {
    const issues = validateRegistrySnapshot(
      snapshot({ reasons: [reason({ reason: 'made_up' as never })] }),
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].path).toBe('reasons[0].reason');
  });

  it('rejects an unsafe documentation URL on a destination', () => {
    const issues = validateRegistrySnapshot(
      snapshot({
        destinations: [
          destination({
            key: 'evil',
            documentation: {
              url: 'http://evil.test/spec',
              documentation_unavailable: false,
            },
          }),
        ],
      }),
    );
    expect(issues).toHaveLength(1);
    expect(issues[0].path).toBe('destinations.evil.documentation.url');
    expect(issues[0].message).toMatch(/unsafe documentation URL/);
  });

  it('accepts a destination with a documentation-unavailable fallback (no url)', () => {
    const issues = validateRegistrySnapshot(
      snapshot({
        destinations: [
          destination({
            key: 'edix12',
            documentation: { url: null, documentation_unavailable: true, note: 'members only' },
          }),
        ],
      }),
    );
    expect(issues).toEqual([]);
  });
});
