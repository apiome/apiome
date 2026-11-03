/**
 * Model for the workspace refresh defaults (RAR-6.5, #3542): the **Refresh defaults** page under
 * Repositories, and the "Workspace default / Custom" state of each repository's refresh settings.
 *
 * A workspace can set the cadence, conflict policy and auto-refresh switch a new repository starts
 * from. Each repository follows a default per setting until that one setting is changed on it; the
 * page can re-apply changed defaults to the settings repositories still follow.
 *
 * Pure helpers only, so they are unit-tested without rendering.
 */

import { formatCadence } from '@/app/components/ade/dashboard/repositories/repositoryBranchRefresh';

/** The three refresh settings a repository can follow the workspace default for. */
export type RefreshSetting = 'refresh_interval' | 'conflict_policy' | 'auto_refresh';

/** Every refresh setting, in the order the screens list them. */
export const REFRESH_SETTINGS: readonly RefreshSetting[] = ['refresh_interval', 'conflict_policy', 'auto_refresh'];

/** How each setting is named on screen. */
export const REFRESH_SETTING_LABELS: Record<RefreshSetting, string> = {
  refresh_interval: 'Cadence',
  conflict_policy: 'Refresh conflicts',
  auto_refresh: 'Auto-refresh',
};

/** Per-setting counts (how many repositories follow each default, or changed on a re-apply). */
export interface RefreshSettingCounts {
  refreshInterval: number;
  conflictPolicy: number;
  autoRefresh: number;
}

/** The page's data: the defaults, who may change them, and how many repositories follow them. */
export interface RefreshDefaultsData {
  /** False when the workspace has not set defaults and the built-in values apply. */
  configured: boolean;
  refreshIntervalSeconds: number;
  conflictPolicy: string;
  autoRefreshEnabled: boolean;
  minIntervalSeconds: number;
  availableConflictPolicies: string[];
  canEdit: boolean;
  updatedAt: string | null;
  /** Live repositories, and how many follow each default. */
  repositories: number;
  inheriting: RefreshSettingCounts;
  /** After a save with re-apply: how many repositories changed per setting. */
  applied: RefreshSettingCounts | null;
}

/** The form's values. */
export interface RefreshDefaultsDraft {
  refreshIntervalSeconds: number;
  conflictPolicy: string;
  autoRefreshEnabled: boolean;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function asCounts(value: unknown): RefreshSettingCounts {
  const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  return {
    refreshInterval: asNumber(raw.refreshInterval, 0),
    conflictPolicy: asNumber(raw.conflictPolicy, 0),
    autoRefresh: asNumber(raw.autoRefresh, 0),
  };
}

/**
 * Parse the proxy's flat refresh-defaults projection.
 *
 * @param body The JSON the `/api/repositories/refresh-defaults` route returned.
 * @returns The page data, with the built-in values for anything missing.
 */
export function parseRefreshDefaults(body: unknown): RefreshDefaultsData {
  const raw = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
  const inheriting = (raw.inheriting && typeof raw.inheriting === 'object' ? raw.inheriting : {}) as Record<
    string,
    unknown
  >;
  return {
    configured: raw.configured === true,
    refreshIntervalSeconds: asNumber(raw.refreshIntervalSeconds, 300),
    conflictPolicy: typeof raw.conflictPolicy === 'string' ? raw.conflictPolicy : 'hold-for-review',
    autoRefreshEnabled: raw.autoRefreshEnabled !== false,
    minIntervalSeconds: asNumber(raw.minIntervalSeconds, 60),
    availableConflictPolicies: Array.isArray(raw.availableConflictPolicies)
      ? raw.availableConflictPolicies.filter((p): p is string => typeof p === 'string')
      : ['hold-for-review', 'overwrite', 'new-branch'],
    canEdit: raw.canEdit === true,
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : null,
    repositories: asNumber(inheriting.repositories, 0),
    inheriting: asCounts(inheriting),
    applied: raw.applied && typeof raw.applied === 'object' ? asCounts(raw.applied) : null,
  };
}

/**
 * The form's starting values.
 *
 * @param data The stored defaults.
 * @returns A draft equal to them.
 */
export function draftFromDefaults(data: RefreshDefaultsData): RefreshDefaultsDraft {
  return {
    refreshIntervalSeconds: data.refreshIntervalSeconds,
    conflictPolicy: data.conflictPolicy,
    autoRefreshEnabled: data.autoRefreshEnabled,
  };
}

/**
 * Whether the form differs from what is stored, or the workspace has no defaults yet.
 *
 * @param draft The form's values.
 * @param data The stored defaults.
 * @returns True when saving would store something new.
 */
export function defaultsChanged(draft: RefreshDefaultsDraft, data: RefreshDefaultsData): boolean {
  return (
    !data.configured ||
    draft.refreshIntervalSeconds !== data.refreshIntervalSeconds ||
    draft.conflictPolicy !== data.conflictPolicy ||
    draft.autoRefreshEnabled !== data.autoRefreshEnabled
  );
}

const COUNT_KEY: Record<RefreshSetting, keyof RefreshSettingCounts> = {
  refresh_interval: 'refreshInterval',
  conflict_policy: 'conflictPolicy',
  auto_refresh: 'autoRefresh',
};

/**
 * How many repositories follow one default, in words.
 *
 * @param data The page data.
 * @param setting The setting.
 * @returns For example "4 of 5 repositories follow this default".
 */
export function inheritanceSentence(data: RefreshDefaultsData, setting: RefreshSetting): string {
  const following = data.inheriting[COUNT_KEY[setting]];
  if (data.repositories === 0) return 'No repositories yet';
  const noun = data.repositories === 1 ? 'repository' : 'repositories';
  return `${following} of ${data.repositories} ${noun} follow this default`;
}

/**
 * The toast after a save with re-apply.
 *
 * @param applied How many repositories changed per setting.
 * @returns For example "Defaults saved and applied: cadence on 4 repositories, refresh conflicts on 1 repository."
 */
export function appliedSentence(applied: RefreshSettingCounts): string {
  const parts = REFRESH_SETTINGS.map((setting) => {
    const count = applied[COUNT_KEY[setting]];
    return { setting, count };
  })
    .filter(({ count }) => count > 0)
    .map(
      ({ setting, count }) =>
        `${REFRESH_SETTING_LABELS[setting].toLowerCase()} on ${count} ${count === 1 ? 'repository' : 'repositories'}`
    );
  if (parts.length === 0) return 'Defaults saved. Every repository that follows them already matched.';
  return `Defaults saved and applied: ${parts.join(', ')}.`;
}

/**
 * A repository setting's value in words, for the "Workspace default / Custom" rows.
 *
 * @param setting The setting.
 * @param value The repository's value (seconds, policy token or switch).
 * @param policyLabel Turns a policy token into its label.
 * @returns For example "Every 15 min", "Hold for review", "On".
 */
export function settingValueText(
  setting: RefreshSetting,
  value: number | string | boolean | null | undefined,
  policyLabel: (policy: string) => string
): string {
  if (setting === 'refresh_interval') return typeof value === 'number' ? `Every ${formatCadence(value)}` : '—';
  if (setting === 'conflict_policy') return typeof value === 'string' ? policyLabel(value) : '—';
  return value === false ? 'Off' : 'On';
}
