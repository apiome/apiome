/**
 * Browser-local bookmarks for Git-based OpenAPI import (account + repo + ref + optional spec path).
 */

export type GitImportRefKind = 'branch' | 'tag';

export type GitImportSavedRepo = {
  id: string;
  accountId: string;
  provider: string;
  repoFullName: string;
  refKind: GitImportRefKind;
  refName: string;
  /** Normalized path without leading slashes; empty if none */
  specPath: string;
  savedAt: number;
};

const STORAGE_PREFIX = 'apiome:git-import-saved-repos:';
export const MAX_GIT_IMPORT_SAVED_REPOS = 50;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function gitImportSavedReposStorageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

export function normalizeGitImportSpecPath(raw: string): string {
  return raw.trim().replace(/^\/+/, '');
}

export function dedupeKeyGitImportSaved(
  e: Pick<GitImportSavedRepo, 'accountId' | 'provider' | 'repoFullName' | 'refKind' | 'refName' | 'specPath'>
): string {
  return `${e.accountId}|${e.provider.toLowerCase()}|${e.repoFullName.toLowerCase()}|${e.refKind}|${e.refName}|${e.specPath}`;
}

export function isGitImportSavedRepo(v: unknown): v is GitImportSavedRepo {
  if (!isPlainObject(v)) return false;
  if (
    typeof v.id !== 'string' ||
    v.id.length === 0 ||
    typeof v.accountId !== 'string' ||
    v.accountId.length === 0 ||
    typeof v.provider !== 'string' ||
    v.provider.length === 0 ||
    typeof v.repoFullName !== 'string' ||
    v.repoFullName.length === 0 ||
    (v.refKind !== 'branch' && v.refKind !== 'tag') ||
    typeof v.refName !== 'string' ||
    typeof v.specPath !== 'string' ||
    typeof v.savedAt !== 'number' ||
    !Number.isFinite(v.savedAt)
  ) {
    return false;
  }
  // A tag entry must have a non-empty refName
  if (v.refKind === 'tag' && (v.refName as string).length === 0) return false;
  return true;
}

export function loadGitImportSavedRepos(userId: string): GitImportSavedRepo[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(gitImportSavedReposStorageKey(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isGitImportSavedRepo)
      .sort((a, b) => b.savedAt - a.savedAt);
  } catch {
    return [];
  }
}

export function saveGitImportSavedRepos(userId: string, items: GitImportSavedRepo[]): boolean {
  if (typeof window === 'undefined') return false;
  try {
    localStorage.setItem(gitImportSavedReposStorageKey(userId), JSON.stringify(items));
    return true;
  } catch {
    // quota or private mode
    return false;
  }
}

function newSavedId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `git-import-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function addGitImportSavedRepo(
  userId: string,
  entry: Omit<GitImportSavedRepo, 'id' | 'savedAt'>
): { persisted: boolean; items: GitImportSavedRepo[] } {
  const existing = loadGitImportSavedRepos(userId);
  const key = dedupeKeyGitImportSaved(entry);
  const filtered = existing.filter((e) => dedupeKeyGitImportSaved(e) !== key);
  const newEntry: GitImportSavedRepo = {
    ...entry,
    id: newSavedId(),
    savedAt: Date.now(),
  };
  const next = [newEntry, ...filtered].slice(0, MAX_GIT_IMPORT_SAVED_REPOS);
  const persisted = saveGitImportSavedRepos(userId, next);
  return { persisted, items: next };
}

export function removeGitImportSavedRepo(
  userId: string,
  id: string
): { persisted: boolean; items: GitImportSavedRepo[] } {
  const existing = loadGitImportSavedRepos(userId);
  const next = existing.filter((e) => e.id !== id);
  const persisted = saveGitImportSavedRepos(userId, next);
  return { persisted, items: next };
}
