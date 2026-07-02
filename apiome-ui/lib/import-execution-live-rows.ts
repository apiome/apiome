/**
 * Derives per-schema checklist rows for the Import Execution panel (#296).
 */

import type { ImportEventLike } from './import-execution-error-indicators';

export type LiveChecklistStatus = 'pending' | 'importing' | 'success' | 'warning' | 'error';

export interface LiveChecklistRow {
  id: string;
  label: string;
  status: LiveChecklistStatus;
  detail?: string;
}

export interface ProgressLike {
  phase?: string;
  total?: number;
  completed?: number;
  currentItem?: string;
}

const CLASS_CREATED_RE = /^(?:Imported class:|Would import class:)\s*(.+)$/i;
const CLASS_FAILED_RE = /^Failed to create class\s+([^:]+)/i;

function extractCreatedClassName(message: string): string | null {
  const m = message.match(CLASS_CREATED_RE);
  return m ? m[1].trim() : null;
}

function extractFailedClassName(message: string): string | null {
  const m = message.match(CLASS_FAILED_RE);
  return m ? m[1].trim() : null;
}

function namesMatch(a: string, b: string): boolean {
  if (a === b) return true;
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** Preserve schema order from CLASS_CREATED / CLASS_FAILED sequence when Preview list is unavailable. */
function inferOrderFromEvents(
  events: ImportEventLike[],
  created: Set<string>,
  failed: Set<string>
): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const ev of events) {
    if (ev.code === 'CLASS_CREATED') {
      const n = extractCreatedClassName(ev.message);
      if (n && !seen.has(n)) {
        seen.add(n);
        order.push(n);
      }
    }
    if (ev.code === 'CLASS_FAILED') {
      const n = extractFailedClassName(ev.message);
      if (n && !seen.has(n)) {
        seen.add(n);
        order.push(n);
      }
    }
  }
  for (const name of failed) {
    if (!seen.has(name)) order.push(name);
  }
  for (const name of created) {
    if (!seen.has(name)) order.push(name);
  }
  return order;
}

/** Warning lines associated with a class from import events. */
function warningDetailForClass(events: ImportEventLike[], className: string): string | undefined {
  const parts: string[] = [];
  for (const ev of events) {
    if (ev.level !== 'warn') continue;
    const ctx = ev.context as { className?: string; propertyName?: string } | undefined;
    if (ctx?.className && namesMatch(ctx.className, className)) {
      parts.push(ev.message);
      continue;
    }
    if (ev.message.includes(`class "${className}"`) || ev.message.includes(`class '${className}'`)) {
      parts.push(ev.message);
    }
  }
  if (parts.length === 0) return undefined;
  return parts[0];
}

/**
 * Builds one row per selected schema with pending / importing / success / warning / error.
 * When `selectedSchemas` is empty, returns rows inferred from CLASS_CREATED / CLASS_FAILED events (order preserved by first appearance).
 */
export function buildImportLiveChecklist(
  selectedSchemas: string[],
  events: ImportEventLike[],
  progress: ProgressLike | undefined,
  jobState: string
): LiveChecklistRow[] {
  const created = new Set<string>();
  const failed = new Set<string>();

  for (const ev of events) {
    if (ev.code === 'CLASS_CREATED') {
      const n = extractCreatedClassName(ev.message);
      if (n) created.add(n);
    }
    if (ev.code === 'CLASS_FAILED') {
      const n = extractFailedClassName(ev.message);
      if (n) failed.add(n);
    }
  }

  const runningLike = ['queued', 'running', 'committing'].includes(jobState);

  const order: string[] =
    selectedSchemas.length > 0
      ? [...selectedSchemas]
      : inferOrderFromEvents(events, created, failed);

  if (order.length === 0) {
    return [];
  }

  const createdLower = new Set<string>([...created].map((n) => n.trim().toLowerCase()));
  const failedLower = new Set<string>([...failed].map((n) => n.trim().toLowerCase()));

  const rows: LiveChecklistRow[] = order.map((label, i) => {
    const id = `schema-${i}-${label}`;
    const labelLower = label.trim().toLowerCase();
    const isFailed = failedLower.has(labelLower);
    if (isFailed) {
      return { id, label, status: 'error' as const };
    }

    const isCreated = createdLower.has(labelLower);

    if (isCreated) {
      const warnDetail = warningDetailForClass(events, label);
      if (warnDetail) {
        return { id, label, status: 'warning' as const, detail: warnDetail };
      }
      return { id, label, status: 'success' as const };
    }

    const importing =
      runningLike &&
      progress?.phase === 'creating-classes' &&
      progress.currentItem &&
      namesMatch(progress.currentItem, label);

    if (importing) {
      return { id, label, status: 'importing' as const };
    }

    return { id, label, status: 'pending' as const };
  });

  return rows;
}

export function formatProgressPrimaryLine(
  progress: ProgressLike | undefined,
  jobState: string
): string {
  if (!progress) {
    return jobState === 'queued' ? 'Waiting to start…' : 'Preparing…';
  }

  const { phase, total = 0, completed = 0, currentItem } = progress;

  if (phase === 'creating-classes' && total >= 2) {
    const n = total - 2;
    if (n > 0) {
      const idx = Math.min(Math.max(completed - 1, 1), n);
      const name = currentItem && currentItem !== 'Verifying import...' ? currentItem : '';
      return name
        ? `Importing schema ${idx} of ${n}: ${name}`
        : `Importing schema ${idx} of ${n}`;
    }
  }

  const labels: Record<string, string> = {
    initializing: 'Initializing import…',
    'creating-project': currentItem ? `Creating project: ${currentItem}` : 'Creating project…',
    'creating-version': currentItem ? `Creating version: ${currentItem}` : 'Creating version…',
    'creating-properties': 'Creating shared properties in library…',
    'creating-classes': currentItem ? `Working on: ${currentItem}` : 'Creating classes…',
    verifying: 'Verifying imported data…',
    finalizing: 'Finalizing…',
  };

  return labels[phase ?? ''] ?? (phase ? phase.replace(/-/g, ' ') : 'In progress…');
}

export function estimateSecondsRemaining(
  percent: number,
  elapsedMs: number
): number | null {
  if (percent <= 0 || percent >= 100) return null;
  const p = Math.max(1, Math.min(99, percent));
  const totalEstimated = (elapsedMs / p) * 100;
  const remaining = totalEstimated - elapsedMs;
  if (!Number.isFinite(remaining) || remaining < 0) return null;
  return Math.max(1, Math.round(remaining / 1000));
}
