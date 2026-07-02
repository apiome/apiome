/**
 * Browser-local recent OpenAPI spec opens from Git SSO import (per user).
 * Shown under Repositories → History, optionally filtered to the selected repo.
 */

import type { GitImportRefKind } from './git-import-saved-repos';
import { dedupeKeyGitImportSaved, normalizeGitImportSpecPath } from './git-import-saved-repos';

export type GitImportRecentSpec = {
  id: string;
  accountId: string;
  provider: string;
  repoFullName: string;
  refKind: GitImportRefKind;
  refName: string;
  /** Normalized path without leading slashes */
  specPath: string;
  openedAt: number;
};

const STORAGE_PREFIX = 'apiome:git-import-recent-specs:';
export const MAX_GIT_IMPORT_RECENT_SPECS = 80;

export function gitImportRecentSpecsStorageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function isGitImportRecentSpec(v: unknown): v is GitImportRecentSpec {
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
    v.specPath.length === 0 ||
    typeof v.openedAt !== 'number' ||
    !Number.isFinite(v.openedAt)
  ) {
    return false;
  }
  if (v.refKind === 'tag' && (v.refName as string).length === 0) return false;
  return true;
}

export function loadGitImportRecentSpecs(userId: string): GitImportRecentSpec[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(gitImportRecentSpecsStorageKey(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isGitImportRecentSpec)
      .sort((a, b) => b.openedAt - a.openedAt);
  } catch {
    return [];
  }
}

export function saveGitImportRecentSpecs(userId: string, items: GitImportRecentSpec[]): boolean {
  if (typeof window === 'undefined') return false;
  try {
    localStorage.setItem(gitImportRecentSpecsStorageKey(userId), JSON.stringify(items));
    return true;
  } catch {
    return false;
  }
}

function newRecentId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `git-import-recent-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export type GitImportRecentSpecInput = Omit<GitImportRecentSpec, 'id' | 'openedAt'>;

/** Dedupe key matches bookmarks so the same logical import is one row, bumped to most recent. */
export function dedupeKeyGitImportRecent(
  e: Pick<GitImportRecentSpec, 'accountId' | 'provider' | 'repoFullName' | 'refKind' | 'refName' | 'specPath'>
): string {
  return dedupeKeyGitImportSaved(e);
}

export function recordGitImportRecentSpec(
  userId: string,
  entry: GitImportRecentSpecInput
): { persisted: boolean; items: GitImportRecentSpec[] } {
  const specPath = normalizeGitImportSpecPath(entry.specPath);
  if (!specPath) {
    return { persisted: true, items: loadGitImportRecentSpecs(userId) };
  }

  const normalized: GitImportRecentSpecInput = {
    ...entry,
    specPath,
    repoFullName: entry.repoFullName.trim(),
    provider: entry.provider.trim(),
    refName: entry.refName.trim(),
  };

  const existing = loadGitImportRecentSpecs(userId);
  const key = dedupeKeyGitImportRecent(normalized);
  const filtered = existing.filter((e) => dedupeKeyGitImportRecent(e) !== key);
  const newEntry: GitImportRecentSpec = {
    ...normalized,
    id: newRecentId(),
    openedAt: Date.now(),
  };
  const next = [newEntry, ...filtered].slice(0, MAX_GIT_IMPORT_RECENT_SPECS);
  const persisted = saveGitImportRecentSpecs(userId, next);
  return { persisted, items: next };
}

export function recentSpecsForAccountAndOptionalRepo(
  items: GitImportRecentSpec[],
  accountId: string,
  repoFullName: string | null
): GitImportRecentSpec[] {
  const byAccount = items.filter((e) => e.accountId === accountId);
  if (!repoFullName) return byAccount;
  const r = repoFullName.toLowerCase();
  return byAccount.filter((e) => e.repoFullName.toLowerCase() === r);
}
