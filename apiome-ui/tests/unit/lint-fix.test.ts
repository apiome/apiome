/**
 * The lint-fix client contract — GVM-3.6 (#5874).
 *
 * Parsers, the refusal error, the requests' wire shape, and the pure helpers both Apply fix
 * surfaces share (entry matching, the reason a non-ready fix renders, posture subject support,
 * and the observed-not-assumed re-lint check).
 */

import {
  LintFixError,
  MCP_NO_DOCUMENT_REASON,
  applyLintFixes,
  defaultFixReason,
  fetchLintFixPlan,
  fixEntriesByFinding,
  fixEntryForFinding,
  fixEntryReason,
  fixSubjectSupport,
  lintFixApplyResultFromPayload,
  lintFixErrorFromPayload,
  lintFixPlanFromPayload,
  observeFixedFindings,
  readyFixIds,
  revisionHref,
  type LintFixEntry,
} from '../../src/app/utils/lint-fix';

/** A raw plan payload as the BFF returns it. */
function planPayload(overrides: Record<string, unknown> = {}) {
  return {
    success: true,
    projectId: 'p1',
    versionRecordId: 'v1',
    counts: { ready: 1, breaking: 1, conflict: 1, excluded: 1 },
    reportCurrent: true,
    published: false,
    entries: [
      {
        fixId: 'fix-a',
        ruleId: 'operation-id-required',
        fixClass: 'fill-in',
        wireVisible: true,
        path: 'paths./pets.get',
        pointer: '/paths/~1pets/get',
        findingId: 'lint-a',
        message: 'Operation has no operationId.',
        ops: [{ op: 'add', path: '/paths/~1pets/get/operationId', value: 'getPets' }],
        status: 'ready',
        reason: null,
        conflictsWith: null,
        classification: { maxSeverity: 'non-breaking', counts: {}, changes: [] },
      },
      {
        fixId: 'fix-b',
        ruleId: 'enum-casing',
        fixClass: 'rename',
        wireVisible: true,
        path: 'components.schemas.Pet.properties.kind',
        pointer: '/components/schemas/Pet/properties/kind',
        findingId: 'lint-b',
        message: 'Enum values are not UPPER_CASE.',
        ops: [],
        status: 'breaking',
        classification: {
          maxSeverity: 'breaking',
          changes: [{ ruleId: 'enum-value-removed', severity: 'breaking', pointer: '/x' }],
        },
      },
      {
        fixId: 'fix-c',
        ruleId: 'description-required',
        fixClass: 'fill-in',
        wireVisible: false,
        path: 'paths./pets',
        pointer: '/paths/~1pets',
        findingId: 'lint-c',
        message: 'No description.',
        ops: [],
        status: 'conflict',
        conflictsWith: 'fix-a',
      },
      {
        fixId: 'fix-d',
        ruleId: 'schema-pascal-case',
        fixClass: 'rename',
        wireVisible: true,
        path: 'components.schemas.pet',
        pointer: '/components/schemas/pet',
        findingId: 'lint-d',
        message: 'Not PascalCase.',
        ops: [],
        status: 'excluded',
        reason: 'renames-not-included',
      },
      { ruleId: 'no-fix-id' },
    ],
    ...overrides,
  };
}

describe('lintFixPlanFromPayload', () => {
  it('reads entries, counts and the BFF published flag, dropping entries without a fix id', () => {
    const plan = lintFixPlanFromPayload(planPayload());
    expect(plan.entries.map((e) => e.fixId)).toEqual(['fix-a', 'fix-b', 'fix-c', 'fix-d']);
    expect(plan.counts).toEqual({ ready: 1, breaking: 1, conflict: 1, excluded: 1 });
    expect(plan.published).toBe(false);
    expect(plan.reportCurrent).toBe(true);
    expect(plan.entries[1].changes).toEqual([
      { ruleId: 'enum-value-removed', severity: 'breaking', pointer: '/x' },
    ]);
    expect(plan.entries[2].conflictsWith).toBe('fix-a');
  });

  it('tolerates junk and an unknown status', () => {
    expect(lintFixPlanFromPayload(null)).toEqual({
      projectId: null,
      versionRecordId: null,
      counts: {},
      entries: [],
      reportCurrent: null,
      published: false,
    });
    const plan = lintFixPlanFromPayload({ entries: [{ fixId: 'x', status: 'weird' }] });
    expect(plan.entries[0].status).toBe('excluded');
  });
});

describe('lintFixApplyResultFromPayload', () => {
  it('reads the created revision', () => {
    const result = lintFixApplyResultFromPayload({
      projectId: 'p1',
      sourceVersionRecordId: 'v1',
      versionRecordId: 'v2',
      versionLabel: '1.0.1',
      appliedFixIds: ['fix-a', 3],
      skipped: [{ fixId: 'fix-b', ruleId: 'enum-casing', status: 'breaking' }],
      score: 92,
      grade: 'A',
    });
    expect(result).toEqual({
      projectId: 'p1',
      sourceVersionRecordId: 'v1',
      versionRecordId: 'v2',
      versionLabel: '1.0.1',
      appliedFixIds: ['fix-a'],
      skipped: [{ fixId: 'fix-b', ruleId: 'enum-casing', status: 'breaking' }],
      score: 92,
      grade: 'A',
    });
  });
});

describe('lintFixErrorFromPayload', () => {
  it('keeps the structured refusal code and message', () => {
    const error = lintFixErrorFromPayload(
      { success: false, detail: { code: 'lint-fix-version-published', message: 'Published.' } },
      409,
      'fallback',
    );
    expect(error).toBeInstanceOf(LintFixError);
    expect(error.code).toBe('lint-fix-version-published');
    expect(error.message).toBe('Published.');
    expect(error.status).toBe(409);
  });

  it('reads FastAPI validation errors, string details and the fallback', () => {
    expect(lintFixErrorFromPayload({ detail: [{ msg: 'bad body' }] }, 422, 'f').message).toBe(
      'bad body',
    );
    expect(lintFixErrorFromPayload({ detail: 'Revision not found' }, 404, 'f').message).toBe(
      'Revision not found',
    );
    expect(lintFixErrorFromPayload(null, 500, 'fallback').message).toBe('fallback');
  });
});

describe('requests', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('reads the plan from the BFF route', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => planPayload() });
    global.fetch = fetchMock as unknown as typeof fetch;
    const plan = await fetchLintFixPlan('p 1', 'v/1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p%201/versions/v%2F1/lint/fixes');
    expect(plan.entries).toHaveLength(4);
  });

  it('raises the refusal when the plan cannot be read', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        success: false,
        detail: { code: 'lint-fix-not-openapi', message: 'OpenAPI 3.x only.' },
      }),
    }) as unknown as typeof fetch;
    await expect(fetchLintFixPlan('p1', 'v1')).rejects.toMatchObject({
      code: 'lint-fix-not-openapi',
      message: 'OpenAPI 3.x only.',
    });
  });

  it('posts fixIds and the trimmed reason', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, versionRecordId: 'v2', versionLabel: '1.0.1' }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    const result = await applyLintFixes('p1', 'v1', ['fix-a'], '  tidy up  ');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1/versions/v1/lint/fixes/apply');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      fixIds: ['fix-a'],
      reason: 'tidy up',
    });
    expect(result.versionLabel).toBe('1.0.1');
  });

  it('refuses a blank reason or no fixes without a request', async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    await expect(applyLintFixes('p1', 'v1', ['fix-a'], '   ')).rejects.toThrow(/reason/);
    await expect(applyLintFixes('p1', 'v1', [], 'why')).rejects.toThrow(/no fixes/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('surfaces a published refusal', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        success: false,
        detail: { code: 'lint-fix-version-published', message: 'This revision is published.' },
      }),
    }) as unknown as typeof fetch;
    await expect(applyLintFixes('p1', 'v1', ['fix-a'], 'why')).rejects.toMatchObject({
      code: 'lint-fix-version-published',
      status: 409,
    });
  });
});

describe('helpers', () => {
  const plan = lintFixPlanFromPayload(planPayload());
  const entry = (id: string) => plan.entries.find((e) => e.fixId === id) as LintFixEntry;

  it('indexes entries by finding and matches by id, then by rule + path', () => {
    expect(fixEntriesByFinding(plan).get('lint-a')?.fixId).toBe('fix-a');
    expect(fixEntryForFinding(plan, { id: 'lint-c' })?.fixId).toBe('fix-c');
    expect(
      fixEntryForFinding(plan, {
        id: 'other',
        rule: 'operation-id-required',
        path: 'paths./pets.get',
      })?.fixId,
    ).toBe('fix-a');
    expect(fixEntryForFinding(plan, { id: 'other', rule: 'nope', path: 'x' })).toBeNull();
    expect(fixEntryForFinding(null, { id: 'lint-a' })).toBeNull();
  });

  it('applies only ready fixes', () => {
    expect(readyFixIds(plan)).toEqual(['fix-a']);
    expect(readyFixIds(null)).toEqual([]);
  });

  it('says why a breaking, conflicting or excluded fix is not applied', () => {
    expect(fixEntryReason(entry('fix-a'))).toBeNull();
    expect(fixEntryReason(entry('fix-b'))).toMatch(/breaking change \(enum-value-removed\)/);
    expect(fixEntryReason(entry('fix-c'))).toMatch(/same part of the document as fix-a/);
    expect(fixEntryReason(entry('fix-d'))).toMatch(/rename fix/);
  });

  it('supports catalog revisions only and says why an MCP finding cannot be fixed', () => {
    const base = {
      subjectType: 'catalog_revision',
      projectId: 'p1',
      versionRecordId: 'v1',
      sourceFingerprint: 'lint-a',
    };
    expect(fixSubjectSupport(base)).toEqual({ supported: true, reason: null });
    expect(fixSubjectSupport({ ...base, subjectType: 'mcp_endpoint_version' })).toEqual({
      supported: false,
      reason: MCP_NO_DOCUMENT_REASON,
    });
    expect(fixSubjectSupport({ ...base, versionRecordId: null }).supported).toBe(false);
    expect(fixSubjectSupport({ ...base, sourceFingerprint: null }).supported).toBe(false);
  });

  it('observes which findings the new revision no longer reports', () => {
    const report = {
      findings: [
        {
          id: 'lint-b',
          path: 'p.b',
          category: 'c',
          rule: 'r-b',
          severity: 'warning' as const,
          message: '',
        },
        {
          id: 'renumbered',
          path: 'p.c',
          category: 'c',
          rule: 'r-c',
          severity: 'info' as const,
          message: '',
        },
      ],
    };
    expect(
      observeFixedFindings(report, [
        { id: 'lint-a', rule: 'r-a', path: 'p.a' },
        { id: 'lint-b', rule: 'r-b', path: 'p.b' },
        { id: 'lint-c', rule: 'r-c', path: 'p.c' },
      ]),
    ).toEqual({ fixed: ['lint-a'], remaining: ['lint-b', 'lint-c'] });
  });

  it('builds the revision link and the default reason', () => {
    expect(revisionHref('p 1')).toBe('/ade/dashboard/versions?projectId=p%201');
    expect(defaultFixReason(1, 'operation-id-required')).toBe(
      'Apply the deterministic operation-id-required fix.',
    );
    expect(defaultFixReason(3)).toBe('Apply 3 deterministic lint fixes.');
    expect(defaultFixReason(1)).toBe('Apply 1 deterministic lint fix.');
  });
});
