import {
  collectStudioAiBestPracticeLinesFromStudio,
  collectStudioAiBestPracticeTipLines,
} from '../../src/app/utils/studio-ai-best-practice-tips';

describe('collectStudioAiBestPracticeTipLines (#615, #616)', () => {
  it('maps ecommerce domain to inventory guidance', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'ecommerce',
      classNames: [],
    });
    expect(lines.some((l) => l.toLowerCase().includes('inventory'))).toBe(true);
  });

  it('emits several industry-specific patterns per domain (#616)', () => {
    const ecommerce = collectStudioAiBestPracticeTipLines({
      domainCategory: 'ecommerce',
      classNames: [],
    });
    expect(ecommerce.length).toBeGreaterThanOrEqual(3);
    expect(ecommerce.some((l) => l.toLowerCase().includes('idempotency'))).toBe(true);

    const healthcare = collectStudioAiBestPracticeTipLines({
      domainCategory: 'healthcare',
      classNames: [],
    });
    expect(healthcare.length).toBeGreaterThanOrEqual(3);
    expect(healthcare.some((l) => l.toLowerCase().includes('fhir'))).toBe(true);
  });

  it('maps saas domain to tenant isolation guidance', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'saas',
      classNames: [],
    });
    expect(lines.some((l) => l.toLowerCase().includes('tenant isolation'))).toBe(true);
  });

  it('detects auth-heavy class names for refresh-token guidance', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['User', 'RefreshToken'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('refresh token'))).toBe(true);
  });

  it('detects auth hint from CamelCase compound OAuthSession', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['OAuthSession'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('refresh token'))).toBe(true);
  });

  it('detects tenant hint from CamelCase compound OrganizationMember', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'social',
      classNames: ['OrganizationMember'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('tenant isolation'))).toBe(true);
  });

  it('detects tenant-like class names when domain is not saas', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'social',
      classNames: ['Organization', 'Post'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('tenant isolation'))).toBe(true);
  });

  it('does not duplicate tenant isolation when domain is already saas', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'saas',
      classNames: ['Organization'],
    });
    expect(lines.filter((l) => l.toLowerCase().includes('tenant isolation')).length).toBe(1);
  });

  it('ignores none domain sentinel', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'none',
      classNames: [],
    });
    expect(lines).toHaveLength(0);
  });

  it('adds payment security guidance for ecommerce and finance domains (#617)', () => {
    const ec = collectStudioAiBestPracticeTipLines({
      domainCategory: 'ecommerce',
      classNames: [],
    });
    expect(ec.some((l) => l.toLowerCase().includes('cvv'))).toBe(true);
    expect(ec.some((l) => l.toLowerCase().includes('processor tokens'))).toBe(true);

    const fin = collectStudioAiBestPracticeTipLines({
      domainCategory: 'finance',
      classNames: [],
    });
    expect(fin.some((l) => l.toLowerCase().includes('cvv'))).toBe(true);
  });

  it('adds PHI encryption guidance for healthcare domain (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: 'healthcare',
      classNames: [],
    });
    expect(lines.some((l) => l.toLowerCase().includes('encrypt phi'))).toBe(true);
  });

  it('detects secret-bearing reusable properties for vault and logging guidance (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['api_key'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('vault'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('logs'))).toBe(true);
  });

  it('adds password hashing guidance when password fields are present (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['password_hash'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('cleartext passwords'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('vault'))).toBe(false);
  });

  it('keeps vault guidance scoped to config secrets, not PAN/CVV/SSN fields (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['card_pan', 'cvv', 'ssn'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('vault'))).toBe(false);
    expect(lines.some((l) => l.toLowerCase().includes('logs'))).toBe(true);
  });

  it('adds auth endpoint rate-limit guidance when auth class names match (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['LoginAttempt'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('rate limits'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('refresh token'))).toBe(true);
  });

  it('adds webhook signature verification when webhook classes are present (#617)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['StripeWebhookEndpoint'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('webhook signatures'))).toBe(true);
  });
});

describe('collectStudioAiBestPracticeTipLines performance hints (#618)', () => {
  it('adds cache guidance when cache- or Redis-like names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['ProductCatalogCache'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('namespace cache'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('ttl'))).toBe(true);
  });

  it('adds cache guidance for tokenized ETag CamelCase compounds', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['OrderETag'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('namespace cache'))).toBe(true);
  });

  it('adds cache guidance for tokenized snake_case ETag properties', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['etag', 'e_tag'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('namespace cache'))).toBe(true);
  });

  it('adds queue and job guidance when worker-style names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['EmailOutbox'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('idempotent'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('retry'))).toBe(true);
  });

  it('adds queue guidance for tokenized CamelCase worker compounds', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['UserBackgroundTask'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('idempotent'))).toBe(true);
  });

  it('adds queue guidance for tokenized snake_case worker properties', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['background_task'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('idempotent'))).toBe(true);
  });

  it('adds pagination guidance when paging primitives appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['CursorToken'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('cursor'))).toBe(true);
    expect(lines.some((l) => l.toLowerCase().includes('offset'))).toBe(true);
  });

  it('adds search-index guidance when search projection names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['ListingSearchIndex'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('search documents'))).toBe(true);
  });

  it('adds bulk I/O guidance when export or migration names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['CsvExportJob'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('chunk'))).toBe(true);
  });

  it('adds media payload guidance when blob or attachment names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['InvoicePdfAttachment'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('binary'))).toBe(true);
  });

  it('adds media guidance for tokenized CamelCase payload compounds', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['OrderBinaryPayload'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('binary'))).toBe(true);
  });

  it('adds media guidance for tokenized snake_case payload properties', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['binary_payload'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('binary'))).toBe(true);
  });

  it('adds feed and timeline guidance when hot-read path names appear', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: ['HomeTimeline'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('fan-out'))).toBe(true);
  });

  it('detects performance signals on reusable property names (#618)', () => {
    const lines = collectStudioAiBestPracticeTipLines({
      domainCategory: '',
      classNames: [],
      propertyNames: ['redis_cache_key'],
    });
    expect(lines.some((l) => l.toLowerCase().includes('namespace cache'))).toBe(true);
  });
});

describe('collectStudioAiBestPracticeLinesFromStudio (#615)', () => {
  it('reads domain from project metadata shape', () => {
    const lines = collectStudioAiBestPracticeLinesFromStudio({
      project: { domainCategory: 'ecommerce' },
      classes: [],
    });
    expect(lines.length).toBeGreaterThan(0);
  });

  it('passes property names for security heuristics (#617)', () => {
    const lines = collectStudioAiBestPracticeLinesFromStudio({
      project: null,
      classes: [],
      properties: [{ name: 'client_secret' }],
    });
    expect(lines.some((l) => l.toLowerCase().includes('vault'))).toBe(true);
  });

  it('passes property names for performance heuristics (#618)', () => {
    const lines = collectStudioAiBestPracticeLinesFromStudio({
      project: null,
      classes: [{ name: 'ReportRow' }],
      properties: [{ name: 'next_page_token' }],
    });
    expect(lines.some((l) => l.toLowerCase().includes('cursor'))).toBe(true);
  });
});
