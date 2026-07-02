'use client';

/**
 * Single ref-counted draft-lock poll per project+revision (#2585, #2726 GLI-07).
 * Avoids duplicate GET /draft-lock when header chip and branch status popover both mount.
 */

export type DraftLockStatusPayload = {
  active: boolean;
  ownerUserId?: string;
  expiresAt?: string;
};

export type DraftLockSharedSnapshot = {
  payload: DraftLockStatusPayload | null;
  /** Monotonic tick for countdown labels (ms since epoch). */
  nowMs: number;
};

type Subscriber = () => void;

const POLL_MS = 10_000;
const TICK_MS = 1_000;

const refCounts = new Map<string, number>();
let pollTimer: number | null = null;
let tickTimer: number | null = null;
let activeKey = '';
let payload: DraftLockStatusPayload | null = null;
let nowMs = Date.now();
const listeners = new Set<Subscriber>();

/** Cached snapshot for `useSyncExternalStore` — must keep referential stability when values are unchanged. */
let snapshotCache: DraftLockSharedSnapshot = { payload: null, nowMs };

function syncSnapshotCache() {
  if (snapshotCache.payload === payload && snapshotCache.nowMs === nowMs) return;
  snapshotCache = { payload, nowMs };
}

function emit() {
  syncSnapshotCache();
  listeners.forEach((l) => l());
}

function stopTimers() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (tickTimer !== null) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

async function fetchOnce(projectId: string, versionId: string) {
  try {
    const qs = new URLSearchParams({ projectId });
    const res = await fetch(`/api/versions/${encodeURIComponent(versionId)}/draft-lock?${qs.toString()}`);
    const json = (await res.json()) as {
      success?: boolean;
      status?: { active?: boolean; ownerUserId?: string; expiresAt?: string };
      error?: string;
    };
    if (!res.ok || !json.success || !json.status) {
      payload = null;
      stopTickIfIdle();
      emit();
      return;
    }
    const st = json.status;
    payload = {
      active: Boolean(st.active),
      ownerUserId: typeof st.ownerUserId === 'string' ? st.ownerUserId : undefined,
      expiresAt: typeof st.expiresAt === 'string' ? st.expiresAt : undefined,
    };
    if (payload.active && payload.expiresAt) ensureTick();
    else stopTickIfIdle();
    emit();
  } catch {
    payload = null;
    stopTickIfIdle();
    emit();
  }
}

function ensurePolling(projectId: string, versionId: string) {
  const key = `${projectId}:${versionId}`;
  if (activeKey === key && pollTimer !== null) return;
  const keyChanged = activeKey !== key;
  stopTimers();
  activeKey = key;
  nowMs = Date.now();
  if (keyChanged) {
    payload = null;
    emit();
  }
  void fetchOnce(projectId, versionId);
  pollTimer = window.setInterval(() => {
    void fetchOnce(projectId, versionId);
  }, POLL_MS);
}

function ensureTick() {
  if (tickTimer !== null) return;
  tickTimer = window.setInterval(() => {
    nowMs = Date.now();
    if (payload?.active && payload.expiresAt) emit();
  }, TICK_MS);
}

function stopTickIfIdle() {
  if (!payload?.active || !payload.expiresAt) {
    if (tickTimer !== null) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
  }
}

export function subscribeDraftLockShared(cb: Subscriber) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function getDraftLockSharedSnapshot(): DraftLockSharedSnapshot {
  syncSnapshotCache();
  return snapshotCache;
}

export function acquireDraftLockShared(projectId: string, versionId: string, published: boolean) {
  if (published || !projectId || !versionId) {
    return;
  }
  const key = `${projectId}:${versionId}`;
  refCounts.set(key, (refCounts.get(key) ?? 0) + 1);
  ensurePolling(projectId, versionId);
  if (payload?.active && payload.expiresAt) ensureTick();
}

export function releaseDraftLockShared(projectId: string, versionId: string, published: boolean) {
  if (published || !projectId || !versionId) {
    return;
  }
  const key = `${projectId}:${versionId}`;
  const next = (refCounts.get(key) ?? 1) - 1;
  if (next <= 0) {
    refCounts.delete(key);
    if (activeKey === key) {
      stopTimers();
      activeKey = '';
      payload = null;
      emit();
    }
  } else {
    refCounts.set(key, next);
  }
  stopTickIfIdle();
}
