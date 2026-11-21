/**
 * Apply fix from the Lint posture workspace — GVM-3.6 (#5874).
 *
 * `applyPostureFixes` with injected requests: MCP findings are skipped with the reason, a
 * published revision is read-only, breaking / conflict entries are never applied, and a
 * finding is moved to `fixed` only when the new revision's re-lint no longer reports it.
 */

import {
  applyPostureFixes,
  groupFindingsByRevision,
  partitionFixableFindings,
  postureFixToast,
  type PostureFixDeps,
} from '../src/app/components/ade/lintFix/postureFixes';
import {
  MCP_NO_DOCUMENT_REASON,
  NO_FIX_REASON,
  PUBLISHED_REASON,
  type LintFixPlan,
} from '../src/app/utils/lint-fix';
import type { VersionLintReport } from '../src/app/utils/version-lint-report';
import { finding } from './helpers/lint-workspace-fixtures';

/** A plan for revision ver_2f0a91 with one entry per status. */
function plan(overrides: Partial<LintFixPlan> = {}): LintFixPlan {
  const entry = (fixId: string, findingId: string, status: 'ready' | 'breaking' | 'conflict') => ({
    fixId,
    ruleId: `rule-${findingId}`,
    fixClass: 'fill-in',
    wireVisible: false,
    path: `path.${findingId}`,
    pointer: '/x',
    findingId,
    message: '',
    status,
    reason: null,
    conflictsWith: status === 'conflict' ? 'fix-f1' : null,
    changes: [],
  });
  return {
    projectId: 'p1',
    versionRecordId: 'ver_2f0a91',
    counts: {},
    entries: [
      entry('fix-f1', 'f1', 'ready'),
      entry('fix-f2', 'f2', 'ready'),
      entry('fix-f3', 'f3', 'breaking'),
      entry('fix-f4', 'f4', 'conflict'),
    ],
    reportCurrent: true,
    published: false,
    ...overrides,
  };
}

/** A report that still lists the given finding ids. */
function report(ids: string[]): VersionLintReport {
  return {
    findings: ids.map((id) => ({
      id,
      path: `path.${id}`,
      category: 'c',
      rule: `rule-${id}`,
      severity: 'warning' as const,
      message: '',
    })),
  } as VersionLintReport;
}

/** Deps with a ready apply, a re-lint that still reports `stillReported`, and a clean bulk write. */
function deps(
  overrides: Partial<PostureFixDeps> = {},
  stillReported: string[] = [],
): jest.Mocked<PostureFixDeps> {
  return {
    fetchPlan: jest.fn().mockResolvedValue(plan()),
    apply: jest.fn().mockResolvedValue({
      projectId: 'p1',
      sourceVersionRecordId: 'ver_2f0a91',
      versionRecordId: 'ver_new',
      versionLabel: '2.4.1',
      appliedFixIds: ['fix-f1'],
      skipped: [],
      score: 95,
      grade: 'A',
    }),
    fetchReport: jest.fn().mockResolvedValue(report(stillReported)),
    markFixed: jest.fn().mockImplementation(async (findings) => ({
      results: findings.map((f: { sourceFingerprint: string }) => ({
        sourceFingerprint: f.sourceFingerprint,
        projectId: 'p1',
        decisionId: 'd',
        beforeState: 'open',
        afterState: 'fixed',
        ok: true,
        error: null,
      })),
      appliedCount: findings.length,
      failedCount: 0,
    })),
    ...overrides,
  } as jest.Mocked<PostureFixDeps>;
}

describe('partitionFixableFindings / groupFindingsByRevision', () => {
  it('skips MCP endpoint findings with the reason and groups the rest by revision', () => {
    const mcp = finding({
      sourceFingerprint: 'm1',
      subjectType: 'mcp_endpoint_version',
      versionRecordId: null,
    });
    const a = finding({ sourceFingerprint: 'f1' });
    const b = finding({ sourceFingerprint: 'f2', versionRecordId: 'ver_other' });
    const { supported, skipped } = partitionFixableFindings([mcp, a, b]);
    expect(supported).toEqual([a, b]);
    expect(skipped).toEqual([{ finding: mcp, reason: MCP_NO_DOCUMENT_REASON }]);
    expect([...groupFindingsByRevision(supported).keys()]).toEqual([
      'p1|ver_2f0a91',
      'p1|ver_other',
    ]);
  });
});

describe('applyPostureFixes', () => {
  it('applies the ready fix, observes it gone after the re-lint and marks it fixed', async () => {
    const d = deps();
    const target = finding({ sourceFingerprint: 'f1' });
    const outcome = await applyPostureFixes([target], 'tidy', d);
    expect(d.apply).toHaveBeenCalledWith('p1', 'ver_2f0a91', ['fix-f1'], 'tidy');
    expect(d.fetchReport).toHaveBeenCalledWith('p1', 'ver_new');
    expect(d.markFixed).toHaveBeenCalledWith([target], 'Fixed by lint-fix revision v2.4.1: tidy');
    expect(outcome.fixed).toEqual([target]);
    expect(outcome.states).toEqual({ f1: 'fixed' });
    expect(outcome.revisions[0].result?.versionLabel).toBe('2.4.1');
    expect(postureFixToast(outcome)).toEqual({
      tone: 'success',
      title: 'Fixed 1 finding',
      description: 'New revision: v2.4.1.',
    });
  });

  it('does not mark a finding the re-lint still reports', async () => {
    const d = deps({}, ['f1']);
    const outcome = await applyPostureFixes([finding({ sourceFingerprint: 'f1' })], 'tidy', d);
    expect(d.markFixed).not.toHaveBeenCalled();
    expect(outcome.fixed).toEqual([]);
    expect(outcome.remaining.map((f) => f.sourceFingerprint)).toEqual(['f1']);
    expect(postureFixToast(outcome).tone).toBe('warning');
  });

  it('never applies breaking or conflicting fixes, and says why', async () => {
    const d = deps();
    const outcome = await applyPostureFixes(
      [finding({ sourceFingerprint: 'f3' }), finding({ sourceFingerprint: 'f4' })],
      'tidy',
      d,
    );
    expect(d.apply).not.toHaveBeenCalled();
    expect(outcome.skipped.map((s) => s.reason)).toEqual([
      expect.stringMatching(/breaking change/),
      expect.stringMatching(/same part of the document as fix-f1/),
    ]);
    expect(postureFixToast(outcome).tone).toBe('error');
  });

  it('treats a published revision as read-only', async () => {
    const d = deps({ fetchPlan: jest.fn().mockResolvedValue(plan({ published: true })) });
    const outcome = await applyPostureFixes([finding({ sourceFingerprint: 'f1' })], 'tidy', d);
    expect(d.apply).not.toHaveBeenCalled();
    expect(outcome.skipped[0].reason).toBe(PUBLISHED_REASON);
  });

  it('skips a finding with no plan entry, and one whose apply was refused', async () => {
    const d = deps({ apply: jest.fn().mockRejectedValue(new Error('Quality policy blocked it.')) });
    const outcome = await applyPostureFixes(
      [finding({ sourceFingerprint: 'zz', ruleId: 'other' }), finding({ sourceFingerprint: 'f2' })],
      'tidy',
      d,
    );
    expect(outcome.skipped.map((s) => s.reason)).toEqual([
      NO_FIX_REASON,
      'Quality policy blocked it.',
    ]);
    expect(d.markFixed).not.toHaveBeenCalled();
  });

  it('applies the ready fixes of one revision in one request, and skips MCP findings', async () => {
    const d = deps();
    const outcome = await applyPostureFixes(
      [
        finding({ sourceFingerprint: 'f1' }),
        finding({ sourceFingerprint: 'f2' }),
        finding({
          sourceFingerprint: 'm',
          subjectType: 'mcp_endpoint_version',
          versionRecordId: null,
        }),
      ],
      'tidy',
      d,
    );
    expect(d.apply).toHaveBeenCalledTimes(1);
    expect(d.apply.mock.calls[0][2]).toEqual(['fix-f1', 'fix-f2']);
    expect(outcome.fixed).toHaveLength(2);
    expect(outcome.skipped).toEqual([expect.objectContaining({ reason: MCP_NO_DOCUMENT_REASON })]);
  });

  it('records a refused decision write without claiming the finding fixed', async () => {
    const d = deps({
      markFixed: jest.fn().mockResolvedValue({
        results: [
          {
            sourceFingerprint: 'f1',
            projectId: 'p1',
            decisionId: null,
            beforeState: 'open',
            afterState: null,
            ok: false,
            error: 'Permission denied',
          },
        ],
        appliedCount: 0,
        failedCount: 1,
      }),
    });
    const outcome = await applyPostureFixes([finding({ sourceFingerprint: 'f1' })], 'tidy', d);
    expect(outcome.fixed).toEqual([]);
    expect(outcome.markError).toBe('Permission denied');
  });
});
