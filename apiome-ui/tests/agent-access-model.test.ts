/**
 * The Agent access model — AGX-3.4 (#4540).
 *
 * Pure functions behind MCP → Agent access: payload parsing, the write-op confirmation rule,
 * key-form validation and the request body, allowlist helpers, quota meters and the shapes the
 * usage charts draw.
 */

import { describe, expect, test } from '@jest/globals';

import {
  agentKeyCreateBody,
  agentKeyIsMutable,
  allowableToolNames,
  allowlistChanged,
  dailyQuotaMeter,
  describeCaps,
  formatDay,
  formatLatency,
  formatRate,
  inactiveAllowlistEntries,
  parseAgentKey,
  parseAgentKeyList,
  parseAgentKeyUsage,
  parseAgentToolset,
  parseAgentToolsetList,
  parseAgentUsage,
  parseExpiryDays,
  parsePublishedVersionOptions,
  toggleName,
  toolToggleNeedsConfirmation,
  toolsetLabel,
  topBars,
  usageAgentLabel,
  usageDailySeries,
  usageIsEmpty,
  validateAgentKeyDraft,
  versionsWithoutToolset,
  withUpdatedTool,
  EMPTY_AGENT_KEY_DRAFT,
  USAGE_TOP_N,
  type AgentKeyUsage,
  type AgentTool,
  type AgentToolsetDetail,
} from '@/app/components/ade/agentAccess/agentAccessModel';

const tool = (over: Partial<AgentTool> = {}): AgentTool => ({
  id: 't1',
  operation: 'GET /pets',
  toolName: 'listPets',
  writeOp: false,
  enabled: true,
  writeConfirmedAt: null,
  writeConfirmedBy: null,
  ...over,
});

const toolset = (tools: AgentTool[]): AgentToolsetDetail => ({
  id: 'ts1',
  versionId: 'v1',
  projectId: 'p1',
  versionLabel: '1.0.0',
  enabled: true,
  target: 'prod',
  toolCount: tools.length,
  enabledToolCount: tools.filter((t) => t.enabled).length,
  enabledWriteOpCount: tools.filter((t) => t.enabled && t.writeOp).length,
  createdAt: null,
  tools,
});

const usageOf = (over: Partial<AgentKeyUsage> = {}): AgentKeyUsage => ({
  keyId: 'k1',
  licenseType: 'free',
  rpsCap: 2,
  dailyCap: 1000,
  used: 240,
  remaining: 760,
  resetsAt: '2026-10-07T00:00:00Z',
  ...over,
});

describe('parsing', () => {
  test('a toolset detail keeps its tools and defaults a bad target to prod', () => {
    const parsed = parseAgentToolset({
      id: 'ts1',
      versionId: 'v1',
      projectId: 'p1',
      versionLabel: '1.2.0',
      enabled: true,
      target: 'staging',
      toolCount: 2,
      enabledToolCount: 1,
      enabledWriteOpCount: 0,
      tools: [{ id: 't', operation: 'POST /pets', toolName: 'createPet', writeOp: true, enabled: false }],
    });
    expect(parsed.target).toBe('prod');
    expect(parsed.tools).toHaveLength(1);
    expect(parsed.tools[0]).toMatchObject({ toolName: 'createPet', writeOp: true, enabled: false });
  });

  test('a list entry has no tools, and garbage parses to an empty list', () => {
    expect(parseAgentToolsetList({ toolsets: [{ id: 'a', target: 'mock' }] })[0]).toMatchObject({
      id: 'a',
      target: 'mock',
      tools: [],
    });
    expect(parseAgentToolsetList(null)).toEqual([]);
    expect(parseAgentToolsetList({ toolsets: 'x' })).toEqual([]);
  });

  test('a key never carries its secret, and an unknown status reads as disabled', () => {
    const key = parseAgentKey({
      id: 'k',
      name: 'claude-desktop',
      keyPrefix: 'ak_abc...',
      toolsetId: 'ts1',
      toolAllowlist: ['listPets', 3],
      status: 'weird',
      secret: 'ak_SECRET',
    });
    expect(key.toolAllowlist).toEqual(['listPets']);
    expect(key.status).toBe('disabled');
    expect(JSON.stringify(key)).not.toContain('ak_SECRET');
    expect(parseAgentKeyList({ keys: [{ id: 'a', status: 'revoked' }] })[0].status).toBe('revoked');
  });

  test('key usage reads caps, null meaning unlimited', () => {
    const usage = parseAgentKeyUsage({
      keyId: 'k',
      licenseType: 'paid',
      rps: { cap: null },
      dailyCalls: { cap: 100000, used: 5, remaining: 99995, resetsAt: 'x' },
    });
    expect(usage).toMatchObject({ rpsCap: null, dailyCap: 100000, used: 5, remaining: 99995 });
  });

  test('usage rollups parse every slice', () => {
    const usage = parseAgentUsage({
      startDay: '2026-10-01',
      endDay: '2026-10-02',
      days: 2,
      totals: { calls: 3, errors: 1, errorRate: 1 / 3, quotaRejections: 1, latencyAvgMs: 120 },
      daily: [{ day: '2026-10-01', calls: 3 }, { day: '2026-10-02', calls: 0 }],
      tools: [{ toolName: 'listPets', calls: 3 }],
      agents: [{ keyId: 'k', name: null, keyPrefix: 'ak_x', revoked: true, calls: 3 }],
    });
    expect(usage.totals.quotaRejections).toBe(1);
    expect(usage.totals.latencyP95MaxMs).toBeNull();
    expect(usage.daily.map((d) => d.day)).toEqual(['2026-10-01', '2026-10-02']);
    expect(usage.agents[0]).toMatchObject({ revoked: true, name: null });
  });

  test('published versions become picker options, dropping rows without an id', () => {
    expect(
      parsePublishedVersionOptions({
        success: true,
        versions: [
          { id: 'v1', version_id: '1.0.0', project_id: 'p', project_name: 'Pets' },
          { version_id: 'orphan' },
        ],
      })
    ).toEqual([{ id: 'v1', label: '1.0.0', projectId: 'p', projectName: 'Pets' }]);
  });
});

describe('toolsets', () => {
  test('only enabling a write op needs the confirmation', () => {
    expect(toolToggleNeedsConfirmation(tool({ writeOp: true, enabled: false }), true)).toBe(true);
    expect(toolToggleNeedsConfirmation(tool({ writeOp: true, enabled: true }), false)).toBe(false);
    expect(toolToggleNeedsConfirmation(tool({ writeOp: false, enabled: false }), true)).toBe(false);
    // Already on: re-asserting it is not a new exposure.
    expect(toolToggleNeedsConfirmation(tool({ writeOp: true, enabled: true }), true)).toBe(false);
  });

  test('versions that already have a toolset are not offered again', () => {
    const versions = [
      { id: 'v1', label: '1', projectId: 'p', projectName: 'P' },
      { id: 'v2', label: '2', projectId: 'p', projectName: 'P' },
    ];
    expect(versionsWithoutToolset(versions, [toolset([])]).map((v) => v.id)).toEqual(['v2']);
  });

  test('a toolset is named by project and version, falling back to the label', () => {
    const versions = [{ id: 'v1', label: '1.0.0', projectId: 'p', projectName: 'Pet Store' }];
    expect(toolsetLabel({ versionId: 'v1', versionLabel: '1.0.0' }, versions)).toBe('Pet Store · 1.0.0');
    expect(toolsetLabel({ versionId: 'zz', versionLabel: '2.0' }, versions)).toBe('2.0');
    expect(toolsetLabel({ versionId: 'zz', versionLabel: null }, [])).toBe('Unknown version');
  });

  test('a tool update recounts enabled tools and writes', () => {
    const before = toolset([tool(), tool({ id: 't2', toolName: 'createPet', writeOp: true, enabled: false })]);
    const after = withUpdatedTool(before, tool({ id: 't2', toolName: 'createPet', writeOp: true, enabled: true }));
    expect(after.enabledToolCount).toBe(2);
    expect(after.enabledWriteOpCount).toBe(1);
    expect(before.enabledWriteOpCount).toBe(0);
  });
});

describe('agent keys', () => {
  const valid = { ...EMPTY_AGENT_KEY_DRAFT, name: 'claude', toolsetId: 'ts1', toolAllowlist: ['listPets'] };

  test('expiry is whole days within range, or empty', () => {
    expect(parseExpiryDays('')).toBeNull();
    expect(parseExpiryDays(' 30 ')).toBe(30);
    expect(parseExpiryDays('0')).toBeNaN();
    expect(parseExpiryDays('1.5')).toBeNaN();
    expect(parseExpiryDays('-3')).toBeNaN();
    expect(parseExpiryDays('99999')).toBeNaN();
  });

  test('validation names the first problem', () => {
    expect(validateAgentKeyDraft(valid)).toBeNull();
    expect(validateAgentKeyDraft({ ...valid, name: '  ' })).toMatch(/Name is required/);
    expect(validateAgentKeyDraft({ ...valid, name: 'x'.repeat(256) })).toMatch(/at most 255/);
    expect(validateAgentKeyDraft({ ...valid, toolsetId: '' })).toMatch(/toolset/);
    expect(validateAgentKeyDraft({ ...valid, toolAllowlist: [] })).toMatch(/at least one tool/);
    expect(validateAgentKeyDraft({ ...valid, toolAllowlist: ['bad name'] })).toMatch(/not an MCP tool name/);
    expect(validateAgentKeyDraft({ ...valid, expiresInDays: 'soon' })).toMatch(/Expiry/);
  });

  test('the create body trims, dedupes and computes expiry from now', () => {
    const now = new Date('2026-10-06T00:00:00.000Z');
    const body = agentKeyCreateBody(
      { ...valid, name: ' claude ', description: '  ', toolAllowlist: ['b', 'a', 'b'], expiresInDays: '2' },
      now
    );
    expect(body).toEqual({
      name: 'claude',
      toolsetId: 'ts1',
      toolAllowlist: ['a', 'b'],
      expiresAt: '2026-10-08T00:00:00.000Z',
    });
    expect(agentKeyCreateBody({ ...valid, description: 'desk' }, now)).toMatchObject({
      description: 'desk',
    });
    expect(agentKeyCreateBody(valid, now)).not.toHaveProperty('expiresAt');
  });

  test('allowable tools are the enabled ones; stale allowlist entries are reported', () => {
    const ts = toolset([tool(), tool({ id: 't2', toolName: 'createPet', enabled: false })]);
    expect(allowableToolNames(ts)).toEqual(['listPets']);
    expect(inactiveAllowlistEntries(['createPet', 'listPets', 'gone'], ts)).toEqual(['createPet', 'gone']);
  });

  test('allowlist comparison ignores order and duplicates', () => {
    expect(allowlistChanged(['a', 'b'], ['b', 'a'])).toBe(false);
    expect(allowlistChanged(['a', 'a'], ['a'])).toBe(false);
    expect(allowlistChanged(['a'], ['a', 'b'])).toBe(true);
    expect(allowlistChanged(['a'], ['b'])).toBe(true);
  });

  test('toggling a name keeps the selection sorted and unique', () => {
    expect(toggleName(['b'], 'a', true)).toEqual(['a', 'b']);
    expect(toggleName(['a', 'b'], 'a', false)).toEqual(['b']);
    expect(toggleName(['a'], 'a', true)).toEqual(['a']);
  });

  test('a revoked key is frozen', () => {
    expect(agentKeyIsMutable({ status: 'revoked' })).toBe(false);
    expect(agentKeyIsMutable({ status: 'expired' })).toBe(true);
  });

  test('the daily meter is capped at the quota and absent when unlimited', () => {
    expect(dailyQuotaMeter(usageOf())).toEqual({
      value: 240,
      max: 1000,
      valueText: '240 of 1,000 calls today',
    });
    expect(dailyQuotaMeter(usageOf({ used: 1500 }))?.value).toBe(1000);
    expect(dailyQuotaMeter(usageOf({ dailyCap: null }))).toBeNull();
  });

  test('caps are described in one line', () => {
    expect(describeCaps(usageOf())).toBe('2 calls/s · 1,000 calls/day');
    expect(describeCaps(usageOf({ rpsCap: null, dailyCap: null }))).toBe('Unlimited');
    expect(describeCaps(usageOf({ rpsCap: null }))).toBe('no rate limit · 1,000 calls/day');
  });
});

describe('usage', () => {
  const day = (d: string, calls: number, errorRate = 0, latency: number | null = null) => ({
    day: d,
    calls,
    errors: Math.round(calls * errorRate),
    errorRate,
    latencyAvgMs: latency,
    latencyP95MaxMs: null,
  });

  test('quiet days are gaps in rate and latency, zeros in calls', () => {
    const series = usageDailySeries({
      daily: [day('2026-10-01', 4, 0.25, 101.6), day('2026-10-02', 0)],
    });
    expect(series.calls).toEqual([4, 0]);
    expect(series.errors).toEqual([1, 0]);
    expect(series.errorRatePct).toEqual([25, null]);
    expect(series.latencyAvgMs).toEqual([102, null]);
  });

  test('emptiness is "no calls at all"', () => {
    const totals = { ...day('x', 0), successCalls: 0, upstreamErrors: 0, validationFailures: 0, quotaRejections: 0, internalErrors: 0 };
    expect(usageIsEmpty({ totals })).toBe(true);
    expect(usageIsEmpty({ totals: { ...totals, calls: 1 } })).toBe(false);
  });

  test('top bars take the first N entries', () => {
    const entries = Array.from({ length: USAGE_TOP_N + 3 }, (_, i) => ({ ...day('x', 100 - i), toolName: `t${i}` }));
    const bars = topBars(entries, (e) => e.toolName);
    expect(bars).toHaveLength(USAGE_TOP_N);
    expect(bars[0]).toEqual({ label: 't0', value: 100 });
  });

  test('an agent is labelled by name, prefix or id, and marked when revoked', () => {
    expect(usageAgentLabel({ name: 'claude', keyPrefix: 'ak_', keyId: 'k', revoked: false })).toBe('claude');
    expect(usageAgentLabel({ name: null, keyPrefix: 'ak_abc', keyId: 'k', revoked: true })).toBe('ak_abc (revoked)');
    expect(usageAgentLabel({ name: null, keyPrefix: null, keyId: 'abcdef123456', revoked: false })).toBe('key abcdef12');
  });

  test('formatting', () => {
    expect(formatRate(0)).toBe('0%');
    expect(formatRate(0.0423)).toBe('4.2%');
    expect(formatRate(0.5)).toBe('50%');
    expect(formatLatency(null)).toBe('—');
    expect(formatLatency(182.4)).toBe('182 ms');
    expect(formatLatency(1440)).toBe('1.4 s');
    expect(formatDay('2026-10-06')).toBe('Oct 6');
    expect(formatDay('nope')).toBe('nope');
  });
});
