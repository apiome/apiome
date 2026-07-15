/**
 * Unit tests for MCP trust-drift + shadowing helpers (CLX-3.4, #4858).
 *
 * The central assertions: a drift report parses every change with its classification and old→new
 * evidence preserved, the category/gate class helpers are deterministic and token-driven, and the
 * shadowing report parses group + endpoint shape.
 */

import {
  driftCategoryClass,
  driftCategoryLabel,
  driftGateClass,
  parseDriftReport,
  parseShadowReport,
} from '@/app/utils/mcp-trust-drift';

const DRIFT = {
  drift: {
    baseline_fingerprint: 'base-fp',
    current_fingerprint: 'cur-fp',
    unchanged: false,
    alert_severity: 'security_regression',
    has_regression: true,
    category_counts: {
      normal_change: 1,
      quality_regression: 0,
      security_regression: 1,
      coverage_loss: 0,
    },
    gate: {
      status: 'blocked',
      blocking_categories: ['security_regression'],
      reason: 'A configured risk delta was detected.',
      enforced: false,
    },
    changes: [
      {
        category: 'security_regression',
        component: 'capability',
        path: 'tool:search',
        summary: "tool 'search' no longer declares readOnlyHint",
        before: { annotations: { readOnlyHint: true } },
        after: { annotations: {} },
        evidence: {
          baseline: { version_tag: 'v1' },
          current: { version_tag: 'v2' },
        },
      },
    ],
  },
  notified: [],
};

describe('parseDriftReport', () => {
  it('parses the classified changes with old→new evidence preserved', () => {
    const report = parseDriftReport(DRIFT);
    expect(report).not.toBeNull();
    expect(report!.alertSeverity).toBe('security_regression');
    expect(report!.gate.status).toBe('blocked');
    expect(report!.gate.enforced).toBe(false);
    expect(report!.changes).toHaveLength(1);
    const change = report!.changes[0];
    expect(change.category).toBe('security_regression');
    expect(change.path).toBe('tool:search');
    expect(change.evidence.baseline.version_tag).toBe('v1');
    expect(change.evidence.current.version_tag).toBe('v2');
  });

  it('accepts a bare drift object (not only the {drift} envelope)', () => {
    const report = parseDriftReport(DRIFT.drift);
    expect(report!.currentFingerprint).toBe('cur-fp');
  });

  it('returns null for malformed input', () => {
    expect(parseDriftReport(null)).toBeNull();
    expect(parseDriftReport(42)).toBeNull();
  });
});

describe('drift class helpers', () => {
  it('maps each category to a distinct token-driven chip class', () => {
    const classes = new Set([
      driftCategoryClass('security_regression'),
      driftCategoryClass('coverage_loss'),
      driftCategoryClass('quality_regression'),
      driftCategoryClass('normal_change'),
    ]);
    expect(classes.size).toBe(4);
    // Security regression reads as the danger tone.
    expect(driftCategoryClass('security_regression')).toContain('rose');
  });

  it('labels categories in plain language', () => {
    expect(driftCategoryLabel('coverage_loss')).toBe('Coverage loss');
    expect(driftCategoryLabel('security_regression')).toBe('Security regression');
  });

  it('maps gate status to distinct classes', () => {
    expect(driftGateClass('blocked')).toContain('rose');
    expect(driftGateClass('warn')).toContain('amber');
    expect(driftGateClass('pass')).toContain('emerald');
  });
});

describe('parseShadowReport', () => {
  it('parses shadowing groups and their endpoints', () => {
    const report = parseShadowReport({
      advisory: true,
      group_count: 1,
      same_host_count: 1,
      cross_host_count: 0,
      groups: [
        {
          item_type: 'tool',
          name: 'search',
          host_scope: 'same_host',
          endpoint_count: 2,
          endpoints: [
            { id: 'ep1', name: 'A', slug: 'a', host: 'same.example' },
            { id: 'ep2', name: 'B', slug: 'b', host: 'same.example' },
          ],
        },
      ],
    });
    expect(report!.groupCount).toBe(1);
    expect(report!.groups[0].name).toBe('search');
    expect(report!.groups[0].hostScope).toBe('same_host');
    expect(report!.groups[0].endpoints.map((e) => e.id)).toEqual(['ep1', 'ep2']);
  });

  it('returns null for malformed input', () => {
    expect(parseShadowReport(undefined)).toBeNull();
  });
});
