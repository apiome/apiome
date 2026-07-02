import { describe, it, expect, beforeEach } from '@jest/globals';
import {
  addGitImportSavedRepo,
  dedupeKeyGitImportSaved,
  gitImportSavedReposStorageKey,
  loadGitImportSavedRepos,
  MAX_GIT_IMPORT_SAVED_REPOS,
  normalizeGitImportSpecPath,
  removeGitImportSavedRepo,
  saveGitImportSavedRepos,
} from '@/app/utils/git-import-saved-repos';

describe('git-import-saved-repos', () => {
  const userId = 'user-test-1';

  beforeEach(() => {
    localStorage.clear();
  });

  it('uses a stable storage key per user', () => {
    expect(gitImportSavedReposStorageKey(userId)).toBe(
      'apiome:git-import-saved-repos:user-test-1'
    );
  });

  it('normalizes spec paths', () => {
    expect(normalizeGitImportSpecPath('  /foo/bar.yaml  ')).toBe('foo/bar.yaml');
    expect(normalizeGitImportSpecPath('')).toBe('');
  });

  it('round-trips through localStorage', () => {
    const { items: list, persisted } = addGitImportSavedRepo(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/repo',
      refKind: 'branch',
      refName: 'main',
      specPath: 'spec/openapi.yaml',
    });
    expect(persisted).toBe(true);
    expect(list).toHaveLength(1);
    expect(loadGitImportSavedRepos(userId)).toEqual(list);
  });

  it('replaces duplicate bookmarks (same dedupe key)', () => {
    const { items: a } = addGitImportSavedRepo(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/repo',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    const idFirst = a[0].id;
    const { items: b } = addGitImportSavedRepo(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'org/repo',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    expect(b).toHaveLength(1);
    expect(b[0].id).not.toBe(idFirst);
    expect(loadGitImportSavedRepos(userId)).toHaveLength(1);
  });

  it('dedupe key is stable for casing on provider and repo', () => {
    const k1 = dedupeKeyGitImportSaved({
      accountId: 'a',
      provider: 'GitHub',
      repoFullName: 'Org/Repo',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    const k2 = dedupeKeyGitImportSaved({
      accountId: 'a',
      provider: 'github',
      repoFullName: 'org/repo',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    expect(k1).toBe(k2);
  });

  it('removeGitImportSavedRepo drops by id', () => {
    const { items: one } = addGitImportSavedRepo(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'a/a',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    const { items: two } = addGitImportSavedRepo(userId, {
      accountId: 'acc1',
      provider: 'github',
      repoFullName: 'b/b',
      refKind: 'branch',
      refName: 'main',
      specPath: '',
    });
    expect(one).toHaveLength(1);
    expect(two).toHaveLength(2);
    const olderId = two.find((e) => e.repoFullName === 'a/a')?.id;
    expect(olderId).toBeDefined();
    const { items: rest } = removeGitImportSavedRepo(userId, olderId!);
    expect(rest).toHaveLength(1);
    expect(rest[0].repoFullName).toBe('b/b');
  });

  it('caps list length', () => {
    for (let i = 0; i < MAX_GIT_IMPORT_SAVED_REPOS + 5; i += 1) {
      addGitImportSavedRepo(userId, {
        accountId: 'acc1',
        provider: 'github',
        repoFullName: `org/r${i}`,
        refKind: 'branch',
        refName: 'main',
        specPath: '',
      });
    }
    expect(loadGitImportSavedRepos(userId)).toHaveLength(MAX_GIT_IMPORT_SAVED_REPOS);
  });

  it('ignores corrupt JSON in localStorage', () => {
    localStorage.setItem(gitImportSavedReposStorageKey(userId), 'not-json');
    expect(loadGitImportSavedRepos(userId)).toEqual([]);
  });

  it('filters invalid array entries on load', () => {
    saveGitImportSavedRepos(userId, [
      {
        id: 'ok',
        accountId: 'a',
        provider: 'github',
        repoFullName: 'o/r',
        refKind: 'branch',
        refName: 'main',
        specPath: '',
        savedAt: 1,
      },
      { bad: true } as never,
    ]);
    expect(loadGitImportSavedRepos(userId)).toHaveLength(1);
  });

  it('rejects entries with empty required fields', () => {
    saveGitImportSavedRepos(userId, [
      // empty accountId
      { id: 'a', accountId: '', provider: 'github', repoFullName: 'o/r', refKind: 'branch', refName: 'main', specPath: '', savedAt: 1 } as never,
      // empty provider
      { id: 'b', accountId: 'acc', provider: '', repoFullName: 'o/r', refKind: 'branch', refName: 'main', specPath: '', savedAt: 1 } as never,
      // empty repoFullName
      { id: 'c', accountId: 'acc', provider: 'github', repoFullName: '', refKind: 'branch', refName: 'main', specPath: '', savedAt: 1 } as never,
      // tag with empty refName
      { id: 'd', accountId: 'acc', provider: 'github', repoFullName: 'o/r', refKind: 'tag', refName: '', specPath: '', savedAt: 1 } as never,
      // valid entry
      { id: 'e', accountId: 'acc', provider: 'github', repoFullName: 'o/r', refKind: 'branch', refName: 'main', specPath: '', savedAt: 1 },
    ]);
    const loaded = loadGitImportSavedRepos(userId);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe('e');
  });
});
