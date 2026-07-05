/**
 * recentExports — the browser-local per-version recent-exports store (MFX-6.5, #3859).
 *
 * Covers: per-artifact-per-version storage keys, record → load round-trips (newest first),
 * the list cap, resilience to corrupted / foreign storage payloads, and the fidelity badge
 * label (`lossless` vs `N% fidelity`, per the mockup).
 */

import { jest } from '@jest/globals';
import {
  MAX_RECENT_EXPORTS,
  fidelityBadgeLabel,
  isRecentExport,
  loadRecentExports,
  recentExportsStorageKey,
  recordRecentExport,
  type RecentExportInput,
} from '../src/app/components/ade/dashboard/export/recentExports';

const ARTIFACT = 'proj-petstore';
const VERSION = 'rev-1';

function makeInput(overrides: Partial<RecentExportInput> = {}): RecentExportInput {
  return {
    targetKey: 'proto',
    targetLabel: 'gRPC / Protobuf',
    tier: 'lossy',
    preservedPercent: 64,
    filename: 'petstore.proto',
    ...overrides,
  };
}

describe('recentExports — storage keys', () => {
  it('scopes the key to the artifact and version', () => {
    expect(recentExportsStorageKey(ARTIFACT, VERSION)).toBe(
      'apiome:recent-exports:proj-petstore:rev-1',
    );
  });

  it('buckets a missing version selector as latest', () => {
    expect(recentExportsStorageKey(ARTIFACT, null)).toBe(
      'apiome:recent-exports:proj-petstore:latest',
    );
    expect(recentExportsStorageKey(ARTIFACT, undefined)).toBe(
      'apiome:recent-exports:proj-petstore:latest',
    );
  });
});

describe('recentExports — record and load', () => {
  beforeEach(() => {
    localStorage.clear();
    jest.restoreAllMocks();
  });

  it('round-trips a recorded export, newest first', () => {
    jest.spyOn(Date, 'now').mockReturnValueOnce(1_000).mockReturnValueOnce(2_000);
    recordRecentExport(ARTIFACT, VERSION, makeInput({ targetKey: 'openapi', targetLabel: 'OpenAPI 3.1', tier: 'lossless', preservedPercent: 100, filename: 'petstore.json' }));
    const { persisted, items } = recordRecentExport(ARTIFACT, VERSION, makeInput());

    expect(persisted).toBe(true);
    expect(items.map((e) => e.targetKey)).toEqual(['proto', 'openapi']);
    expect(loadRecentExports(ARTIFACT, VERSION)).toEqual(items);
    expect(items[0].exportedAt).toBe(2_000);
  });

  it('keeps every export as its own event (no dedupe by target)', () => {
    recordRecentExport(ARTIFACT, VERSION, makeInput({ preservedPercent: 64 }));
    recordRecentExport(ARTIFACT, VERSION, makeInput({ preservedPercent: 71 }));

    const items = loadRecentExports(ARTIFACT, VERSION);
    expect(items).toHaveLength(2);
    expect(items.map((e) => e.preservedPercent)).toEqual([71, 64]);
  });

  it('caps the list at MAX_RECENT_EXPORTS, dropping the oldest', () => {
    for (let i = 0; i < MAX_RECENT_EXPORTS + 3; i++) {
      recordRecentExport(ARTIFACT, VERSION, makeInput({ filename: `run-${i}.proto` }));
    }
    const items = loadRecentExports(ARTIFACT, VERSION);
    expect(items).toHaveLength(MAX_RECENT_EXPORTS);
    expect(items.some((e) => e.filename === 'run-0.proto')).toBe(false);
    expect(items[0].filename).toBe(`run-${MAX_RECENT_EXPORTS + 2}.proto`);
  });

  it('isolates versions of the same artifact from each other', () => {
    recordRecentExport(ARTIFACT, 'rev-1', makeInput({ targetKey: 'proto' }));
    recordRecentExport(ARTIFACT, 'rev-2', makeInput({ targetKey: 'openapi' }));

    expect(loadRecentExports(ARTIFACT, 'rev-1').map((e) => e.targetKey)).toEqual(['proto']);
    expect(loadRecentExports(ARTIFACT, 'rev-2').map((e) => e.targetKey)).toEqual(['openapi']);
  });

  it('returns [] for corrupted JSON and for non-array payloads', () => {
    localStorage.setItem(recentExportsStorageKey(ARTIFACT, VERSION), '{not json');
    expect(loadRecentExports(ARTIFACT, VERSION)).toEqual([]);

    localStorage.setItem(recentExportsStorageKey(ARTIFACT, VERSION), '{"a":1}');
    expect(loadRecentExports(ARTIFACT, VERSION)).toEqual([]);
  });

  it('drops malformed entries but keeps well-formed ones', () => {
    const good = { ...makeInput(), exportedAt: 5 };
    localStorage.setItem(
      recentExportsStorageKey(ARTIFACT, VERSION),
      JSON.stringify([good, { targetKey: '' }, null, 42, { ...good, tier: 'weird' }]),
    );
    expect(loadRecentExports(ARTIFACT, VERSION)).toEqual([good]);
  });
});

describe('recentExports — shape guard and badge label', () => {
  it('accepts every fidelity tier and rejects unknown ones', () => {
    const base = { ...makeInput(), exportedAt: 1 };
    expect(isRecentExport({ ...base, tier: 'lossless' })).toBe(true);
    expect(isRecentExport({ ...base, tier: 'lossy' })).toBe(true);
    expect(isRecentExport({ ...base, tier: 'types-only' })).toBe(true);
    expect(isRecentExport({ ...base, tier: 'pristine' })).toBe(false);
    expect(isRecentExport({ ...base, exportedAt: Number.NaN })).toBe(false);
  });

  it('labels lossless exports as lossless and lossy ones with their preserved-%', () => {
    expect(fidelityBadgeLabel({ tier: 'lossless', preservedPercent: 100 })).toBe('lossless');
    expect(fidelityBadgeLabel({ tier: 'lossy', preservedPercent: 82 })).toBe('82% fidelity');
    expect(fidelityBadgeLabel({ tier: 'types-only', preservedPercent: 31 })).toBe('31% fidelity');
  });
});
