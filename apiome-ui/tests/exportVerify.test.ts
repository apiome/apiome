/**
 * exportVerify — verdict derivation, banner copy, lens badge counts, and the Generate gate
 * (MFX-42.1, #4354). Pure logic, tested directly (no React, no fetch), mirroring
 * `exportFidelityPreview.test.ts` / `exportTargetCatalog.test.ts`.
 */

import {
  deriveVerifyVerdict,
  lensBadgeCount,
  lintSeverityCounts,
  verifyGatePasses,
  verifyVerdictBanner,
  verifyVerdictBannerClass,
  type EmittedArtifactLintReport,
  type EmittedValidationReport,
  type ExportVerifyResponse,
} from '../src/app/components/ade/dashboard/export/exportVerify';
import type {
  ExportFidelityEnvelope,
  ExportFidelityTier,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

/** A minimal fidelity envelope with the given tier and kind counts. */
function fidelity(
  tier: ExportFidelityTier,
  kindCounts: Partial<Record<string, number>> = {},
): ExportFidelityEnvelope {
  return {
    target: {
      key: 'proto',
      format: 'proto-3',
      label: 'gRPC / Protobuf',
      description: 'Export services as a .proto file.',
      icon: 'binary',
      paradigm: 'rpc',
      multi_file: false,
      needs_toolchain: false,
      available: true,
      unavailable_reason: null,
    },
    summary: {
      tier,
      preserved_percent: tier === 'lossless' ? 100 : 64,
      total: 10,
      preserved: 6,
      dropped: kindCounts.drop ?? 0,
      approximated: kindCounts.approx ?? 0,
      synthesized: kindCounts.synth ?? 0,
    },
    report: {
      items: [],
      kind_counts: { drop: 0, approx: 0, synth: 0, ok: 0, ...kindCounts },
      severity_counts: { info: 0, warn: 0, critical: 0 },
    },
    advisory: {
      show: tier !== 'lossless',
      severity: tier === 'lossless' ? null : 'warn',
      requires_ack: tier !== 'lossless',
      target_format: 'gRPC / Protobuf',
      dropped: kindCounts.drop ?? 0,
      approximated: kindCounts.approx ?? 0,
      synthesized: kindCounts.synth ?? 0,
      affected: 0,
      headline: 'x',
      message: 'x',
    },
  };
}

/** A validation report with the given verdict; findings default to empty. */
function validation(
  verdict: EmittedValidationReport['verdict'],
  overrides: Partial<EmittedValidationReport> = {},
): EmittedValidationReport {
  return {
    verdict,
    target: 'openapi-3.1',
    blocks_delivery: verdict === 'invalid',
    warns: verdict === 'skipped',
    valid: verdict === 'valid',
    findings: [],
    detail: verdict === 'skipped' ? 'Validator not installed on server.' : null,
    headline: verdict === 'invalid' ? 'Invalid — export blocked' : 'Valid',
    message: 'x',
    ...overrides,
  };
}

/** Assemble a verify result from its lens parts. */
function result(
  fid: ExportFidelityEnvelope,
  val: EmittedValidationReport,
  lint: EmittedArtifactLintReport | null = null,
  verdict?: ExportVerifyResponse['verdict'],
): ExportVerifyResponse {
  return {
    artifact: 'proj-1',
    version: null,
    version_record_id: 'rev-1',
    version_label: '1.0.0',
    fidelity: fid,
    validation: val,
    lint,
    verdict: verdict ?? null,
  };
}

describe('deriveVerifyVerdict', () => {
  it('is invalid when validation blocks delivery — regardless of fidelity tier', () => {
    expect(deriveVerifyVerdict(result(fidelity('lossless'), validation('invalid')))).toBe('invalid');
  });

  it('is lossy when the conversion is not lossless and validation passes', () => {
    expect(deriveVerifyVerdict(result(fidelity('lossy', { drop: 2 }), validation('valid')))).toBe(
      'lossy',
    );
    // types-only is also a non-lossless (acknowledgement-requiring) band.
    expect(deriveVerifyVerdict(result(fidelity('types-only'), validation('valid')))).toBe('lossy');
  });

  it('is clean for a lossless, valid conversion', () => {
    expect(deriveVerifyVerdict(result(fidelity('lossless'), validation('valid')))).toBe('clean');
  });

  it('treats a skipped (toolchain-unavailable) validation as non-blocking', () => {
    // Skipped warns but does not demote a lossless conversion below clean.
    expect(deriveVerifyVerdict(result(fidelity('lossless'), validation('skipped')))).toBe('clean');
  });

  it('prefers a server-supplied verdict over the derived one', () => {
    // Server says invalid even though the lenses would derive clean.
    const r = result(fidelity('lossless'), validation('valid'), null, 'invalid');
    expect(deriveVerifyVerdict(r)).toBe('invalid');
  });
});

describe('verifyVerdictBanner', () => {
  it('uses the roadmap label strings verbatim', () => {
    expect(verifyVerdictBanner('clean').label).toBe('Clean');
    expect(verifyVerdictBanner('lossy').label).toBe('Lossy — acknowledge to continue');
    expect(verifyVerdictBanner('invalid').label).toBe('Invalid — export blocked');
  });

  it('maps each verdict to its tone', () => {
    expect(verifyVerdictBanner('clean').tone).toBe('clean');
    expect(verifyVerdictBanner('lossy').tone).toBe('lossy');
    expect(verifyVerdictBanner('invalid').tone).toBe('invalid');
  });

  it('gives a distinct banner class per tone', () => {
    const classes = new Set([
      verifyVerdictBannerClass('clean'),
      verifyVerdictBannerClass('lossy'),
      verifyVerdictBannerClass('invalid'),
    ]);
    expect(classes.size).toBe(3);
  });
});

describe('lensBadgeCount', () => {
  const r = result(
    fidelity('lossy', { drop: 2, approx: 1, synth: 3, ok: 5 }),
    validation('invalid', {
      findings: [
        { message: 'a' },
        { message: 'b' },
      ],
    }),
    { applicable: true, findings: [{ severity: 'warning', rule: 'r1', message: 'm' }] },
  );

  it('counts non-faithful constructs (drop + approx + synth, not ok) for fidelity', () => {
    expect(lensBadgeCount('fidelity', r)).toBe(6);
  });

  it('counts validation findings', () => {
    expect(lensBadgeCount('validation', r)).toBe(2);
  });

  it('counts lint findings, 0 when there is no lint report', () => {
    expect(lensBadgeCount('lint', r)).toBe(1);
    expect(lensBadgeCount('lint', result(fidelity('lossless'), validation('valid'), null))).toBe(0);
  });

  it('is 0 for every lens before a result exists', () => {
    expect(lensBadgeCount('fidelity', null)).toBe(0);
    expect(lensBadgeCount('validation', null)).toBe(0);
    expect(lensBadgeCount('lint', null)).toBe(0);
  });
});

describe('lintSeverityCounts', () => {
  it('tallies per severity, zero-filled', () => {
    expect(
      lintSeverityCounts([
        { severity: 'error', rule: 'a', message: 'm' },
        { severity: 'error', rule: 'b', message: 'm' },
        { severity: 'warning', rule: 'c', message: 'm' },
      ]),
    ).toEqual({ error: 2, warning: 1, info: 0 });
  });

  it('is all-zero for no findings', () => {
    expect(lintSeverityCounts([])).toEqual({ error: 0, warning: 0, info: 0 });
  });
});

describe('verifyGatePasses', () => {
  it('never passes before a verdict exists', () => {
    expect(verifyGatePasses(null, false)).toBe(false);
    expect(verifyGatePasses(null, true)).toBe(false);
  });

  it('blocks invalid regardless of acknowledgement', () => {
    expect(verifyGatePasses('invalid', false)).toBe(false);
    expect(verifyGatePasses('invalid', true)).toBe(false);
  });

  it('passes lossy only once acknowledged', () => {
    expect(verifyGatePasses('lossy', false)).toBe(false);
    expect(verifyGatePasses('lossy', true)).toBe(true);
  });

  it('always passes clean', () => {
    expect(verifyGatePasses('clean', false)).toBe(true);
  });
});
