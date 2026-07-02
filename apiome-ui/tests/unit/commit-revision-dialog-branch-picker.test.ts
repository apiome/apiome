import { describe, test, expect } from '@jest/globals';
import { commitRevisionDialogShowsBranchPicker } from '@/app/components/ade/version-dialogs/CommitRevisionDialog';

describe('commitRevisionDialogShowsBranchPicker', () => {
  const branches = [{ id: 'a' }, { id: 'b' }];

  test('hides picker for 0 or 1 branch', () => {
    expect(commitRevisionDialogShowsBranchPicker(null, [])).toBe(false);
    expect(commitRevisionDialogShowsBranchPicker(null, [{ id: 'a' }])).toBe(false);
  });

  test('shows picker for multi-branch without lock', () => {
    expect(commitRevisionDialogShowsBranchPicker(null, branches)).toBe(true);
    expect(commitRevisionDialogShowsBranchPicker('  ', branches)).toBe(true);
  });

  test('hides picker when lock matches a branch', () => {
    expect(commitRevisionDialogShowsBranchPicker('a', branches)).toBe(false);
  });

  test('shows picker when lock does not match any branch', () => {
    expect(commitRevisionDialogShowsBranchPicker('missing', branches)).toBe(true);
  });
});
