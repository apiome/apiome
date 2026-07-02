import {
  getBranchDivergenceChipPresentation,
  branchDivergenceChipToneClasses,
} from '@/app/ade/studio/lib/branch-divergence-chip-copy';

describe('getBranchDivergenceChipPresentation', () => {
  test('in sync when both zero', () => {
    expect(getBranchDivergenceChipPresentation(0, 0, 'main')).toEqual({
      label: 'in sync with main',
      tone: 'muted',
    });
  });

  test('ahead only', () => {
    expect(getBranchDivergenceChipPresentation(3, 0, 'main')).toEqual({
      label: '↑3 ahead of main',
      tone: 'ahead',
    });
  });

  test('behind only', () => {
    expect(getBranchDivergenceChipPresentation(0, 2, 'production')).toEqual({
      label: '↓2 behind production',
      tone: 'behind',
    });
  });

  test('diverged', () => {
    expect(getBranchDivergenceChipPresentation(2, 1, 'main')).toEqual({
      label: '↑2 ↓1 diverged from main',
      tone: 'diverged',
    });
  });

  test('falls back when against name empty', () => {
    expect(getBranchDivergenceChipPresentation(0, 0, '   ').label).toBe('in sync with default branch');
  });
});

describe('branchDivergenceChipToneClasses', () => {
  test('returns distinct strings per tone', () => {
    const a = branchDivergenceChipToneClasses('muted');
    const b = branchDivergenceChipToneClasses('ahead');
    expect(a).not.toEqual(b);
    expect(a).toContain('border-gray-200/55');
    expect(b).toContain('emerald');
  });
});
