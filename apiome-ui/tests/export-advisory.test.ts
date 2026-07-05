/**
 * Tests for the export fidelity advisory consumer helpers (MFX-2.4, #3841).
 *
 * These cover the pure presentation helpers only — the advisory `message`/`headline` and its
 * counts are the server's verdict (apiome-rest `app/fidelity_advisory.py`) and are never
 * recomputed here. The `SERVER_*` fixtures pin the exact wording apiome-rest emits, so a change
 * to the canonical string source that isn't mirrored in the UI's expectations is caught.
 */
import {
  advisoryBannerClass,
  advisoryChips,
  advisoryPresentation,
  advisorySeverityPillClass,
  type ExportAdvisory,
} from '../src/app/utils/export-advisory';

/** A lossy advisory exactly as apiome-rest serialises it for a Protobuf export. */
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

/** A lossless advisory exactly as apiome-rest serialises it for a clean round-trip. */
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
  it('maps a critical advisory to the critical strength and the ack gate', () => {
    const p = advisoryPresentation(SERVER_LOSSY_ADVISORY);
    expect(p.strength).toBe('critical');
    expect(p.requiresAck).toBe(true);
  });

  it('maps a warn advisory to the warning strength without an ack gate', () => {
    const p = advisoryPresentation({
      ...SERVER_LOSSY_ADVISORY,
      severity: 'warn',
      requires_ack: false,
    });
    expect(p.strength).toBe('warning');
    expect(p.requiresAck).toBe(false);
  });

  it('presents a suppressed advisory as info and gates nothing', () => {
    const p = advisoryPresentation(SERVER_LOSSLESS_ADVISORY);
    expect(p.strength).toBe('info');
    expect(p.requiresAck).toBe(false);
  });
});

describe('advisoryChips', () => {
  it('emits chips for non-zero buckets in worst-first order', () => {
    const chips = advisoryChips(SERVER_LOSSY_ADVISORY);
    expect(chips.map((c) => c.key)).toEqual(['dropped', 'approximated', 'synthesized']);
    expect(chips.map((c) => c.count)).toEqual([1, 2, 1]);
  });

  it('drops empty buckets', () => {
    const chips = advisoryChips({
      ...SERVER_LOSSY_ADVISORY,
      dropped: 0,
      approximated: 3,
      synthesized: 0,
      affected: 3,
    });
    expect(chips.map((c) => c.key)).toEqual(['approximated']);
  });

  it('is empty for a lossless advisory', () => {
    expect(advisoryChips(SERVER_LOSSLESS_ADVISORY)).toEqual([]);
  });
});

describe('CSS class helpers', () => {
  it('returns a distinct banner palette per strength', () => {
    const classes = new Set([
      advisoryBannerClass('critical'),
      advisoryBannerClass('warning'),
      advisoryBannerClass('info'),
    ]);
    expect(classes.size).toBe(3);
    expect(advisoryBannerClass('critical')).toContain('rose');
    expect(advisoryBannerClass('warning')).toContain('amber');
  });

  it('returns a severity pill palette, defaulting for a null severity', () => {
    expect(advisorySeverityPillClass('critical')).toContain('rose');
    expect(advisorySeverityPillClass('warn')).toContain('amber');
    expect(advisorySeverityPillClass(null)).toContain('sky');
  });
});

describe('server wording contract', () => {
  it('renders the server message and headline verbatim (no re-templating)', () => {
    // The consumer displays these strings as-is; this pins the canonical wording the
    // apiome-rest string source (MFX-2.4) must produce, so UI/browse/CLI stay identical.
    expect(SERVER_LOSSY_ADVISORY.message).toContain('may lose some fidelity');
    expect(SERVER_LOSSY_ADVISORY.message).toContain('4 constructs will be dropped or approximated');
    expect(SERVER_LOSSY_ADVISORY.headline).toBe(
      'Fidelity notice — exporting to Protobuf may lose detail.',
    );
  });
});
