/**
 * Unit tests for the Type Registry Settings model (#3472).
 *
 * Covers defaults coercion, allowlist (de)serialization, depth clamping, list toggling, and the
 * change-diffing the Settings view relies on to send minimal PUT payloads.
 */

import {
  DEFAULT_SETTINGS,
  MAX_RESOLUTION_DEPTH,
  MIN_RESOLUTION_DEPTH,
  clampDepth,
  coerceSettings,
  diffSettings,
  formatAllowlist,
  hasChanges,
  parseAllowlist,
  toggleInList,
  type TypeRegistrySettings,
} from '../src/app/ade/dashboard/primitives/primitivesSettingsModel';

describe('coerceSettings', () => {
  it('returns a complete defaults object for null/empty input', () => {
    expect(coerceSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(coerceSettings(undefined)).toEqual(DEFAULT_SETTINGS);
    expect(coerceSettings({})).toEqual(DEFAULT_SETTINGS);
  });

  it('fills missing fields from defaults and keeps provided ones', () => {
    const result = coerceSettings({ default_draft: '2019-09', max_resolution_depth: 5 });
    expect(result.default_draft).toBe('2019-09');
    expect(result.max_resolution_depth).toBe(5);
    expect(result.ref_style).toBe(DEFAULT_SETTINGS.ref_style);
  });

  it('copies arrays so the returned object never shares the DEFAULT_SETTINGS references', () => {
    const result = coerceSettings({});
    expect(result.remote_host_allowlist).toEqual(DEFAULT_SETTINGS.remote_host_allowlist);
    expect(result.remote_host_allowlist).not.toBe(DEFAULT_SETTINGS.remote_host_allowlist);
    expect(result.accepted_formats).not.toBe(DEFAULT_SETTINGS.accepted_formats);
  });

  it('coerces non-array allowlist/formats to defaults', () => {
    const result = coerceSettings({
      remote_host_allowlist: undefined,
      accepted_formats: undefined,
    });
    expect(result.remote_host_allowlist).toEqual(DEFAULT_SETTINGS.remote_host_allowlist);
    expect(result.accepted_formats).toEqual(DEFAULT_SETTINGS.accepted_formats);
  });
});

describe('parseAllowlist / formatAllowlist', () => {
  it('splits on newlines and commas, trims, and de-duplicates', () => {
    expect(parseAllowlist('json-schema.org\n spec.openapis.org , json-schema.org\n\n')).toEqual([
      'json-schema.org',
      'spec.openapis.org',
    ]);
  });

  it('returns an empty list for blank text', () => {
    expect(parseAllowlist('   \n  ')).toEqual([]);
  });

  it('round-trips through format → parse', () => {
    const hosts = ['a.example', 'b.example'];
    expect(parseAllowlist(formatAllowlist(hosts))).toEqual(hosts);
  });
});

describe('clampDepth', () => {
  it('clamps to the inclusive bounds', () => {
    expect(clampDepth(0)).toBe(MIN_RESOLUTION_DEPTH);
    expect(clampDepth(999)).toBe(MAX_RESOLUTION_DEPTH);
    expect(clampDepth(12)).toBe(12);
  });

  it('truncates fractions and falls back to the default for NaN', () => {
    expect(clampDepth(8.9)).toBe(8);
    expect(clampDepth(Number.NaN)).toBe(DEFAULT_SETTINGS.max_resolution_depth);
  });
});

describe('toggleInList', () => {
  it('adds a missing value and removes a present one, preserving order', () => {
    expect(toggleInList(['a', 'b'], 'c')).toEqual(['a', 'b', 'c']);
    expect(toggleInList(['a', 'b', 'c'], 'b')).toEqual(['a', 'c']);
  });
});

describe('diffSettings / hasChanges', () => {
  it('returns an empty payload when nothing changed', () => {
    expect(diffSettings(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS })).toEqual({});
    expect(hasChanges(DEFAULT_SETTINGS, { ...DEFAULT_SETTINGS })).toBe(false);
  });

  it('includes only the changed scalar fields', () => {
    const current: TypeRegistrySettings = {
      ...DEFAULT_SETTINGS,
      default_draft: '2019-09',
      max_resolution_depth: 20,
    };
    expect(diffSettings(DEFAULT_SETTINGS, current)).toEqual({
      default_draft: '2019-09',
      max_resolution_depth: 20,
    });
    expect(hasChanges(DEFAULT_SETTINGS, current)).toBe(true);
  });

  it('treats list reordering as no change but membership changes as a change', () => {
    const reordered: TypeRegistrySettings = {
      ...DEFAULT_SETTINGS,
      remote_host_allowlist: [...DEFAULT_SETTINGS.remote_host_allowlist].reverse(),
    };
    expect(diffSettings(DEFAULT_SETTINGS, reordered)).toEqual({});

    const changed: TypeRegistrySettings = {
      ...DEFAULT_SETTINGS,
      accepted_formats: ['json-schema-2020-12'],
    };
    expect(diffSettings(DEFAULT_SETTINGS, changed)).toEqual({
      accepted_formats: ['json-schema-2020-12'],
    });
  });

  it('detects a null ↔ value change on default_target_namespace', () => {
    const current: TypeRegistrySettings = {
      ...DEFAULT_SETTINGS,
      default_target_namespace: 'tenant/acme/v1/types',
    };
    expect(diffSettings(DEFAULT_SETTINGS, current)).toEqual({
      default_target_namespace: 'tenant/acme/v1/types',
    });
  });
});
