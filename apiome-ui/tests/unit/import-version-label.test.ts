/**
 * Resolution strategy "Create version" (#590): the sub-version label an import uses when its
 * version is taken.
 */
import { describe, expect, test } from '@jest/globals';
import {
  nextFreeVersionLabel,
  planImportVersion,
  subVersionStem,
  subVersionSuffix,
} from '../../src/app/utils/import-version-label';

describe('subVersionSuffix', () => {
  test('starts at b and runs to z', () => {
    expect([0, 1, 2, 24].map(subVersionSuffix)).toEqual(['b', 'c', 'd', 'z']);
  });

  test('grows a letter after z, never using a', () => {
    expect([25, 26, 49, 50].map(subVersionSuffix)).toEqual(['bb', 'bc', 'bz', 'cb']);
    const suffixes = Array.from({ length: 2000 }, (_, i) => subVersionSuffix(i));
    expect(new Set(suffixes).size).toBe(2000);
    expect(suffixes.some((s) => s.includes('a'))).toBe(false);
  });
});

describe('subVersionStem', () => {
  test.each([
    ['1.0.0b', '1.0.0'],
    ['1.0.0bb', '1.0.0'],
    ['1.0.0', '1.0.0'],
    ['v2-beta', 'v2-beta'],
    ['latest', 'latest'],
    ['2024.10', '2024.10'],
  ])('%s → %s', (label, stem) => {
    expect(subVersionStem(label)).toBe(stem);
  });
});

describe('nextFreeVersionLabel', () => {
  test('keeps a free label', () => {
    expect(nextFreeVersionLabel('1.1.0', ['1.0.0'])).toBe('1.1.0');
    expect(nextFreeVersionLabel(' 1.1.0 ', [])).toBe('1.1.0');
  });

  test('a taken label becomes the first free sub-version', () => {
    expect(nextFreeVersionLabel('1.0.0', ['1.0.0'])).toBe('1.0.0b');
    expect(nextFreeVersionLabel('1.0.0', ['1.0.0', '1.0.0b', '1.0.0c'])).toBe('1.0.0d');
    // Gaps are filled first.
    expect(nextFreeVersionLabel('1.0.0', ['1.0.0', '1.0.0c'])).toBe('1.0.0b');
  });

  test('re-importing a sub-version adds the next one, not a doubled suffix', () => {
    expect(nextFreeVersionLabel('1.0.0b', ['1.0.0', '1.0.0b'])).toBe('1.0.0c');
  });

  test('a label with no numeric stem gets a suffix too', () => {
    expect(nextFreeVersionLabel('latest', ['latest'])).toBe('latestb');
  });

  test('is exact: case and whitespace in stored labels are trimmed, not folded', () => {
    expect(nextFreeVersionLabel('1.0.0', [' 1.0.0 '])).toBe('1.0.0b');
    expect(nextFreeVersionLabel('V1', ['v1'])).toBe('V1');
  });
});

describe('planImportVersion', () => {
  test('says whether the requested label is taken and which one the import uses', () => {
    expect(planImportVersion('2.5.0', ['2.4.0', '2.5.0'])).toEqual({ requested: '2.5.0', label: '2.5.0b', taken: true });
    expect(planImportVersion('2.6.0', ['2.4.0', '2.5.0'])).toEqual({ requested: '2.6.0', label: '2.6.0', taken: false });
    // An older server sends no labels: nothing is known to be taken.
    expect(planImportVersion('2.5.0', undefined)).toEqual({ requested: '2.5.0', label: '2.5.0', taken: false });
  });
});
