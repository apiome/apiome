/**
 * Tests for export advisory presentation helpers — MFX-7.2 (#3861).
 */

import { describe, expect, it } from 'vitest';
import {
  advisoryBannerClass,
  advisoryChips,
  advisoryPresentation,
  advisorySeverityPillClass,
  type ExportAdvisory,
} from '../export-advisory';

const SERVER_LOSSY_ADVISORY: ExportAdvisory = {
  show: true,
  severity: 'critical',
  requires_ack: true,
  target_format: 'Protobuf',
  dropped: 1,
  approximated: 2,
  synthesized: 1,
  affected: 4,
  headline: 'Fidelity notice — exporting to Protobuf may lose detail.',
  message:
    "Exporting to Protobuf may lose some fidelity. The destination format can't " +
    'represent everything in this API, so 4 constructs will be dropped or ' +
    'approximated — review the fidelity report before downloading.',
};

const SERVER_LOSSLESS_ADVISORY: ExportAdvisory = {
  show: false,
  severity: null,
  requires_ack: false,
  target_format: 'OpenAPI 3.1',
  dropped: 0,
  approximated: 0,
  synthesized: 0,
  affected: 0,
  headline: 'No fidelity loss exporting to OpenAPI 3.1.',
  message:
    'Exporting to OpenAPI 3.1 preserves full fidelity — every construct in this ' +
    'API maps cleanly onto the target format.',
};

describe('advisoryPresentation', () => {
  it('maps critical to critical strength and ack gate', () => {
    const p = advisoryPresentation(SERVER_LOSSY_ADVISORY);
    expect(p.strength).toBe('critical');
    expect(p.requiresAck).toBe(true);
  });

  it('maps warn to warning without ack gate', () => {
    const p = advisoryPresentation({ ...SERVER_LOSSY_ADVISORY, severity: 'warn', requires_ack: false });
    expect(p.strength).toBe('warning');
    expect(p.requiresAck).toBe(false);
  });

  it('presents suppressed advisory as info', () => {
    const p = advisoryPresentation(SERVER_LOSSLESS_ADVISORY);
    expect(p.strength).toBe('info');
    expect(p.requiresAck).toBe(false);
  });
});

describe('advisoryChips', () => {
  it('emits chips for non-zero buckets worst-first', () => {
    const chips = advisoryChips(SERVER_LOSSY_ADVISORY);
    expect(chips.map((c) => c.key)).toEqual(['dropped', 'approximated', 'synthesized']);
    expect(chips.map((c) => c.count)).toEqual([1, 2, 1]);
  });

  it('returns empty when all counts are zero', () => {
    expect(advisoryChips(SERVER_LOSSLESS_ADVISORY)).toEqual([]);
  });
});

describe('advisoryBannerClass', () => {
  it('maps strengths to distinct palettes', () => {
    expect(advisoryBannerClass('critical')).toContain('rose');
    expect(advisoryBannerClass('warning')).toContain('amber');
    expect(advisoryBannerClass('info')).toContain('sky');
  });
});

describe('advisorySeverityPillClass', () => {
  it('maps severities to distinct palettes', () => {
    expect(advisorySeverityPillClass('critical')).toContain('rose');
    expect(advisorySeverityPillClass('warn')).toContain('amber');
    expect(advisorySeverityPillClass('info')).toContain('sky');
    expect(advisorySeverityPillClass(null)).toContain('sky');
  });
});
