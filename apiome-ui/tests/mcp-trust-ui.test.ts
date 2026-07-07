/**
 * Unit tests for the pure composite-trust-profile client helpers (V2-MCP-31.4 / MCAT-17.4).
 *
 * Exercises `mcpTrustUi` in isolation (no React): the defensive parser (including the re-derivation
 * of the overall composite / available count from the axes, and the gap-not-zero contract), the
 * score bands, the value formatter, and the radar projection.
 */
import {
  MCP_TRUST_AXIS_MAX,
  MCP_TRUST_BAND_TONE,
  mcpTrustBand,
  mcpTrustFormatValue,
  mcpTrustProfileFromPayload,
  mcpTrustRadarAxes,
} from '../src/app/components/ade/dashboard/mcp/mcpTrustUi';

function axis(
  key: string,
  label: string,
  value: number | null,
  available: boolean,
  detail = 'basis',
  methodology = 'how',
) {
  return { key, label, value, available, detail, methodology };
}

function payload(axes: unknown[], extra: Record<string, unknown> = {}) {
  return {
    success: true,
    endpoint_id: 'ep',
    version_id: 'v1',
    auth_type: 'none',
    profile: { axes, overall: 999, available_count: 999, axis_count: axes.length, ...extra },
    ...extra,
  };
}

describe('mcpTrustProfileFromPayload', () => {
  it('parses the five axes and re-derives the overall from the available ones', () => {
    const p = mcpTrustProfileFromPayload(
      payload([
        axis('quality', 'Quality', 90, true),
        axis('safety', 'Safety', 70, true),
        axis('documentation', 'Documentation', 50, true),
        axis('stability', 'Stability', null, false),
        axis('responsiveness', 'Responsiveness', null, false),
      ]),
    );
    expect(p).not.toBeNull();
    expect(p!.axes.map((a) => a.key)).toEqual([
      'quality',
      'safety',
      'documentation',
      'stability',
      'responsiveness',
    ]);
    expect(p!.availableCount).toBe(3);
    expect(p!.axisCount).toBe(5);
    // overall is the mean of the three available axes (90 + 70 + 50) / 3 = 70, not the wire's 999.
    expect(p!.overall).toBe(70);
    expect(p!.versionId).toBe('v1');
    expect(p!.authType).toBe('none');
  });

  it('renders a missing axis as an explicit gap (null value), never a zero', () => {
    const p = mcpTrustProfileFromPayload(
      payload([
        axis('quality', 'Quality', 80, true),
        axis('responsiveness', 'Responsiveness', null, false, 'Never tested'),
      ]),
    );
    const gap = p!.axes.find((a) => a.key === 'responsiveness')!;
    expect(gap.available).toBe(false);
    expect(gap.value).toBeNull();
    expect(gap.detail).toBe('Never tested');
  });

  it('treats an axis flagged available but carrying no finite value as a gap', () => {
    const p = mcpTrustProfileFromPayload(
      payload([
        axis('quality', 'Quality', null, true), // contradictory wire: available but no value
        axis('safety', 'Safety', 60, true),
      ]),
    );
    const quality = p!.axes.find((a) => a.key === 'quality')!;
    expect(quality.available).toBe(false);
    expect(quality.value).toBeNull();
    // Only the genuinely-available axis feeds the composite.
    expect(p!.availableCount).toBe(1);
    expect(p!.overall).toBe(60);
  });

  it('returns null overall when every axis is a gap', () => {
    const p = mcpTrustProfileFromPayload(
      payload([
        axis('quality', 'Quality', null, false),
        axis('safety', 'Safety', null, false),
      ]),
    );
    expect(p!.availableCount).toBe(0);
    expect(p!.overall).toBeNull();
  });

  it('returns null for an absent or malformed profile', () => {
    expect(mcpTrustProfileFromPayload(null)).toBeNull();
    expect(mcpTrustProfileFromPayload({})).toBeNull();
    expect(mcpTrustProfileFromPayload({ profile: 'nope' })).toBeNull();
  });

  it('drops axes with no resolvable key', () => {
    const p = mcpTrustProfileFromPayload(
      payload([axis('quality', 'Quality', 90, true), { label: 'orphan', value: 10, available: true }]),
    );
    expect(p!.axes).toHaveLength(1);
    expect(p!.axes[0].key).toBe('quality');
  });
});

describe('mcpTrustBand', () => {
  it('bands values into strong / fair / weak, and null into gap', () => {
    expect(mcpTrustBand(90)).toBe('strong');
    expect(mcpTrustBand(80)).toBe('strong');
    expect(mcpTrustBand(79.9)).toBe('fair');
    expect(mcpTrustBand(50)).toBe('fair');
    expect(mcpTrustBand(49.9)).toBe('weak');
    expect(mcpTrustBand(0)).toBe('weak');
    expect(mcpTrustBand(null)).toBe('gap');
  });

  it('maps every band to a chart tone', () => {
    for (const band of ['strong', 'fair', 'weak', 'gap'] as const) {
      expect(MCP_TRUST_BAND_TONE[band]).toBeTruthy();
    }
  });
});

describe('mcpTrustFormatValue', () => {
  it('rounds to a whole number, and renders a gap as an em dash', () => {
    expect(mcpTrustFormatValue(72.4)).toBe('72');
    expect(mcpTrustFormatValue(72.6)).toBe('73');
    expect(mcpTrustFormatValue(null)).toBe('—');
  });
});

describe('mcpTrustRadarAxes', () => {
  it('projects axes to the radar with gaps drawn at the centre (0), on a fixed 0-100 domain', () => {
    const p = mcpTrustProfileFromPayload(
      payload([
        axis('quality', 'Quality', 90, true),
        axis('stability', 'Stability', null, false),
      ]),
    );
    const radar = mcpTrustRadarAxes(p!);
    expect(radar).toEqual([
      { label: 'Quality', value: 90 },
      { label: 'Stability', value: 0 },
    ]);
    expect(MCP_TRUST_AXIS_MAX).toBe(100);
  });
});
