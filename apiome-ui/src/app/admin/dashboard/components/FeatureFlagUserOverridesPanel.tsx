'use client';

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Flag, Search, Plus, Minus, Package, Loader2 } from 'lucide-react';
import {
  getAllFeatureFlags,
  getAllFeatureFlagGroups,
  getUserLicense,
  setUserFeatureFlag,
  removeUserFeatureFlag,
} from '../../../../../lib/db/admin-actions';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';

export interface FeatureFlagRow {
  id: string;
  name: string;
  label: string;
  description: string | null;
  is_preview: boolean;
  enabled: boolean;
}

interface GroupMember {
  id: string;
  name: string;
  label: string;
  is_preview: boolean;
}

interface FeatureFlagGroupRow {
  id: string;
  name: string;
  label: string;
  description: string | null;
  feature_flags: GroupMember[];
}

function PreviewBadge() {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded-xs text-2xs font-semibold uppercase bg-warn/40 text-warn-fg border border-warn/40">
      Preview
    </span>
  );
}

type Notify = (type: 'success' | 'error', text: string) => void;

function flagMatchesQuery(flag: FeatureFlagRow, q: string) {
  if (!q) return true;
  return flag.label.toLowerCase().includes(q) || flag.name.toLowerCase().includes(q);
}

export function FeatureFlagUserOverridesPanel({
  userId,
  userName,
  userEmail,
  onNotify,
  className = '',
}: {
  userId: string;
  userName: string;
  userEmail: string;
  onNotify?: Notify;
  /** e.g. `h-full min-h-0` so the panel fills a flex parent and inner lists scroll */
  className?: string;
}) {
  const notifyRef = useRef(onNotify);
  notifyRef.current = onNotify;

  const [loading, setLoading] = useState(true);
  const [allFlags, setAllFlags] = useState<FeatureFlagRow[]>([]);
  const [groups, setGroups] = useState<FeatureFlagGroupRow[]>([]);
  const [licenseFlags, setLicenseFlags] = useState<Set<string>>(new Set());
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [flagSearch, setFlagSearch] = useState('');
  const [savingFlagIds, setSavingFlagIds] = useState<Set<string>>(new Set());
  const [savingGroupId, setSavingGroupId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [flagsRes, licRes, groupsRes] = await Promise.all([
      getAllFeatureFlags(),
      getUserLicense(userId),
      getAllFeatureFlagGroups(),
    ]);
    const flagsData = JSON.parse(flagsRes);
    const licData = JSON.parse(licRes);
    const groupsData = JSON.parse(groupsRes);

    if (flagsData.success) setAllFlags(flagsData.featureFlags);
    setGroups(groupsData.success ? (groupsData.groups ?? []) : []);

    if (licData.success && licData.license) {
      const lic = licData.license;
      setLicenseFlags(new Set((lic.license_feature_flags ?? []).map((f: { id: string }) => f.id)));
      const next: Record<string, boolean> = {};
      for (const o of lic.user_overrides ?? []) next[o.id] = o.enabled;
      setOverrides(next);
    } else {
      setLicenseFlags(new Set());
      setOverrides({});
    }
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await reload();
      } catch {
        if (!cancelled) notifyRef.current?.('error', 'Failed to load feature flags');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const withSaving = async (flagId: string, fn: () => Promise<void>) => {
    setSavingFlagIds(prev => new Set(prev).add(flagId));
    try {
      await fn();
    } finally {
      setSavingFlagIds(prev => {
        const n = new Set(prev);
        n.delete(flagId);
        return n;
      });
    }
  };

  const addGrantedFlag = async (flagId: string) => {
    await withSaving(flagId, async () => {
      const res = JSON.parse(await setUserFeatureFlag(userId, flagId, true));
      if (res.success) {
        setOverrides(prev => ({ ...prev, [flagId]: true }));
        notifyRef.current?.('success', 'Flag added for this user');
      } else {
        notifyRef.current?.('error', res.error || 'Could not add flag');
      }
    });
  };

  const removeGrantedFlag = async (flagId: string) => {
    await withSaving(flagId, async () => {
      const res = JSON.parse(await removeUserFeatureFlag(userId, flagId));
      if (res.success) {
        setOverrides(prev => {
          const n = { ...prev };
          delete n[flagId];
          return n;
        });
        notifyRef.current?.('success', 'Flag removed from this user');
      } else {
        notifyRef.current?.('error', res.error || 'Could not remove flag');
      }
    });
  };

  const addPackage = async (g: FeatureFlagGroupRow) => {
    const ids = (g.feature_flags ?? []).map(f => f.id);
    if (ids.length === 0) {
      notifyRef.current?.('error', 'This package has no flags yet');
      return;
    }
    setSavingGroupId(g.id);
    try {
      for (const flagId of ids) {
        const res = JSON.parse(await setUserFeatureFlag(userId, flagId, true));
        if (!res.success) {
          notifyRef.current?.('error', res.error || `Failed on flag ${flagId}`);
          await reload();
          return;
        }
      }
      setOverrides(prev => {
        const n = { ...prev };
        for (const flagId of ids) n[flagId] = true;
        return n;
      });
      notifyRef.current?.('success', `Package "${g.label}" added`);
    } catch {
      notifyRef.current?.('error', 'Failed to add package');
      await reload();
    } finally {
      setSavingGroupId(null);
    }
  };

  const removePackage = async (g: FeatureFlagGroupRow) => {
    const ids = (g.feature_flags ?? []).map(f => f.id);
    if (ids.length === 0) return;
    setSavingGroupId(g.id);
    try {
      for (const flagId of ids) {
        const res = JSON.parse(await removeUserFeatureFlag(userId, flagId));
        if (!res.success) {
          notifyRef.current?.('error', res.error || 'Failed to remove part of package');
          await reload();
          return;
        }
      }
      setOverrides(prev => {
        const n = { ...prev };
        for (const flagId of ids) delete n[flagId];
        return n;
      });
      notifyRef.current?.('success', `Package "${g.label}" removed`);
    } catch {
      notifyRef.current?.('error', 'Failed to remove package');
      await reload();
    } finally {
      setSavingGroupId(null);
    }
  };

  const searchLower = flagSearch.trim().toLowerCase();

  const sortedFlags = useMemo(
    () => [...allFlags].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' })),
    [allFlags]
  );

  const grantedList = useMemo(
    () => sortedFlags.filter(f => overrides[f.id] === true && flagMatchesQuery(f, searchLower)),
    [sortedFlags, overrides, searchLower]
  );

  const notGrantedList = useMemo(
    () => sortedFlags.filter(f => overrides[f.id] !== true && flagMatchesQuery(f, searchLower)),
    [sortedFlags, overrides, searchLower]
  );

  if (loading) {
    return (
      <div
        className={`flex flex-col items-center justify-center py-16 text-fg-muted gap-3 ${className}`}
      >
        <Loader2 className="w-8 h-8 animate-spin text-ok-fg" />
        <p className="text-sm">
          Loading flags for {userName}
          {userEmail ? ` (${userEmail})` : ''}…
        </p>
      </div>
    );
  }

  const renderFlagRow = (flag: FeatureFlagRow, mode: 'add' | 'remove') => {
    const inLicense = licenseFlags.has(flag.id);
    const busy = savingFlagIds.has(flag.id);
    return (
      <li
        key={`${mode}-${flag.id}`}
        className="flex items-center gap-2 border-b border-border px-3 py-2 last:border-b-0"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-fg">{flag.label}</span>
            <code className="text-2xs text-fg-muted truncate">{flag.name}</code>
            {inLicense && (
              <span className="px-1.5 py-0.5 bg-ok/30 text-ok-fg text-2xs rounded-xs shrink-0">
                license
              </span>
            )}
            {flag.is_preview && <PreviewBadge />}
          </div>
        </div>
        {mode === 'add' ? (
          <button
            type="button"
            title="Add to this user's granted flags"
            disabled={busy}
            onClick={() => addGrantedFlag(flag.id)}
            className="shrink-0 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-fg-on-accent hover:bg-accent-hover disabled:opacity-40 transition-colors"
          >
            <Plus className="w-5 h-5" />
          </button>
        ) : (
          <button
            type="button"
            title="Remove from this user’s granted flags"
            disabled={busy}
            onClick={() => removeGrantedFlag(flag.id)}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border-strong text-fg-muted transition-colors hover:border-danger hover:bg-danger/40 hover:text-danger-fg disabled:opacity-40"
          >
            <Minus className="w-5 h-5" />
          </button>
        )}
      </li>
    );
  };

  return (
    <div className={`flex h-full min-h-0 flex-col gap-3 ${className}`}>
      <div className="flex shrink-0 flex-wrap gap-3 text-xs text-fg-muted">
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-ok" /> Also on license
        </span>
        <span className="flex items-center gap-1.5">
          <Plus className="w-3 h-3 text-accent-fg" /> Add explicit grant
        </span>
        <span className="flex items-center gap-1.5">
          <Minus className="w-3 h-3 text-fg-subtle" /> Remove explicit grant
        </span>
      </div>

      <section className="shrink-0">
        <h4 className="text-sm font-semibold text-fg flex items-center gap-2 mb-1.5">
          <Package className="w-4 h-4 text-accent-fg" />
          Feature packages
        </h4>
        <p className="mb-2 text-xs text-fg-muted">
          Bulk add or remove the same flags together (defined under Licenses → Flag packages).
        </p>
        {groups.length === 0 ? (
          <p className="rounded-lg border border-border bg-subtle px-3 py-2 text-xs italic text-fg-muted">
            No packages defined yet.
          </p>
        ) : (
          <ul className="max-h-28 overflow-y-auto space-y-1.5 pr-1">
            {groups.map(g => {
              const members = g.feature_flags ?? [];
              const busy = savingGroupId === g.id;
              return (
                <li
                  key={g.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-subtle px-2.5 py-2"
                >
                  <span className="text-sm text-fg font-medium truncate flex-1 min-w-[8rem]">
                    {g.label}
                  </span>
                  <Button
                    type="button"
                    disabled={busy || members.length === 0}
                    onClick={() => addPackage(g)}
                    variant="accent" size="sm" className="text-xs"
                  >
                    Add all
                  </Button>
                  <Button
                    type="button"
                    disabled={busy || members.length === 0}
                    onClick={() => removePackage(g)}
                    variant="outline" size="sm" className="text-xs"
                  >
                    Remove all
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="relative shrink-0">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-muted pointer-events-none" />
        <Input
          type="search"
          value={flagSearch}
          onChange={e => setFlagSearch(e.target.value)}
          placeholder="Search flags by label or name…"
          className="pl-10 pr-3"
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Flag className="h-4 w-4 shrink-0 text-accent-fg" />
            <h4 className="text-sm font-semibold text-fg">Granted for this user</h4>
            <span className="ml-auto text-xs tabular-nums text-fg-muted">{grantedList.length}</span>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {grantedList.length === 0 ? (
              <li className="px-3 py-8 text-center text-xs text-fg-muted italic">No explicit grants{searchLower ? ' match this search' : ''}.</li>
            ) : (
              grantedList.map(f => renderFlagRow(f, 'remove'))
            )}
          </ul>
        </section>

        <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-4 w-4 shrink-0 text-fg-subtle" />
            <h4 className="text-sm font-semibold text-fg">All flags — add</h4>
            <span className="ml-auto text-xs tabular-nums text-fg-muted">{notGrantedList.length}</span>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {notGrantedList.length === 0 ? (
              <li className="px-3 py-8 text-center text-xs text-fg-muted italic">
                {sortedFlags.length === 0
                  ? 'No feature flags defined.'
                  : searchLower
                    ? 'No flags match this search.'
                    : 'Every flag is already explicitly granted for this user.'}
              </li>
            ) : (
              notGrantedList.map(f => renderFlagRow(f, 'add'))
            )}
          </ul>
        </section>
      </div>
    </div>
  );
}
