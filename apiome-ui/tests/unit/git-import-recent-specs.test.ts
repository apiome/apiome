import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  gitImportRecentSpecsStorageKey,
  loadGitImportRecentSpecs,
  MAX_GIT_IMPORT_RECENT_SPECS,
  recordGitImportRecentSpec,
  recentSpecsForAccountAndOptionalRepo,
  saveGitImportRecentSpecs,
} from '@/app/utils/git-import-recent-specs';

describe('git-import-recent-specs', () => {
  const userId = 'user-recent-1';

  beforeEach(() => {
    localStorage.clear();
  });

  it('uses a stable storage key per user', () => {
    expect(gitImportRecentSpecsStorageKey(userId)).toBe(
      'apiome:git-import-recent-specs:user-recent-1'
    );
  });

  it('records and sorts by openedAt descending', () => {
    const { items: a } = recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/a',
      refKind: 'branch',
      refName: 'main',
      specPath: 'spec/a.yaml',
    });
    expect(a).toHaveLength(1);
    const { items: b } = recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/b',
      refKind: 'branch',
      refName: 'main',
      specPath: 'spec/b.yaml',
    });
    expect(b[0].repoFullName).toBe('org/b');
    expect(b[1].repoFullName).toBe('org/a');
  });

  it('dedupes the same account/repo/ref/path and bumps to top', () => {
    recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/r',
      refKind: 'branch',
      refName: 'main',
      specPath: 'openapi.yaml',
    });
    recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/r',
      refKind: 'branch',
      refName: 'main',
      specPath: 'other.yaml',
    });
    const { items } = recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/r',
      refKind: 'branch',
      refName: 'main',
      specPath: 'openapi.yaml',
    });
    expect(items).toHaveLength(2);
    expect(items[0].specPath).toBe('openapi.yaml');
    expect(items[1].specPath).toBe('other.yaml');
  });

  it('ignores empty spec path without writing', () => {
    const { items, persisted } = recordGitImportRecentSpec(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/r',
      refKind: 'branch',
      refName: 'main',
      specPath: '   ',
    });
    expect(persisted).toBe(true);
    expect(items).toHaveLength(0);
  });

  it('recentSpecsForAccountAndOptionalRepo filters by account and optional repo', () => {
    recordGitImportRecentSpec(userId, {
      accountId: 'a1',
      provider: 'github',
      repoFullName: 'o/one',
      refKind: 'branch',
      refName: 'main',
      specPath: 'x.yaml',
    });
    recordGitImportRecentSpec(userId, {
      accountId: 'a2',
      provider: 'github',
      repoFullName: 'o/two',
      refKind: 'branch',
      refName: 'main',
      specPath: 'y.yaml',
    });
    const all = loadGitImportRecentSpecs(userId);
    expect(recentSpecsForAccountAndOptionalRepo(all, 'a1', null)).toHaveLength(1);
    expect(recentSpecsForAccountAndOptionalRepo(all, 'a1', 'O/One')).toHaveLength(1);
    expect(recentSpecsForAccountAndOptionalRepo(all, 'a1', 'o/two')).toHaveLength(0);
  });

  it('caps list length', () => {
    for (let i = 0; i < MAX_GIT_IMPORT_RECENT_SPECS + 5; i += 1) {
      recordGitImportRecentSpec(userId, {
        accountId: 'acc1',
        provider: 'github',
        repoFullName: `org/r${i}`,
        refKind: 'branch',
        refName: 'main',
        specPath: `s${i}.yaml`,
      });
    }
    expect(loadGitImportRecentSpecs(userId)).toHaveLength(MAX_GIT_IMPORT_RECENT_SPECS);
  });

  it('filters corrupt JSON on load', () => {
    localStorage.setItem(gitImportRecentSpecsStorageKey(userId), 'not-json');
    expect(loadGitImportRecentSpecs(userId)).toEqual([]);
  });

  it('filters invalid entries on load', () => {
    saveGitImportRecentSpecs(userId, [
      {
        id: 'ok',
        accountId: 'a',
        provider: 'github',
        repoFullName: 'o/r',
        refKind: 'branch',
        refName: 'main',
        specPath: 'p.yaml',
        openedAt: 1,
      },
      { bad: true } as never,
    ]);
    expect(loadGitImportRecentSpecs(userId)).toHaveLength(1);
  });
});
