/**
 * Point-in-time recovery (PITR) over the event/snapshot model.
 *
 * The data layer is event-sourced: `odb.data_record` holds one immutable row per change
 * (`created` / `updated` / `deleted` / `restored`) with a per-record monotonic `record_sequence`,
 * and `odb.data_snapshot` caches the current materialized state. To recover the state of the world
 * as of any past instant we do not need a continuous WAL archive — we replay the event log onto
 * nothing and stop at the chosen timestamp. `foldEventsAsOf` is that replay, kept pure so it is
 * exhaustively testable without a database.
 *
 * Event payload semantics (matching V059):
 *   - created:  `data` is the full document.
 *   - updated:  `data` is a shallow delta merged over the prior state.
 *   - deleted:  the record leaves the live set (`data` is optional/ignored).
 *   - restored: the record re-enters the live set; `data`, if present, replaces the state.
 */

/** One event-log row, narrowed to the fields PITR needs. */
export type DataEvent = {
  recordId: string;
  recordSequence: number;
  action: "created" | "updated" | "deleted" | "restored";
  data: Record<string, unknown> | null;
  /** Event time (ISO 8601 string or Date). */
  createdAt: string | Date;
};

/** A live record reconstructed at the recovery point. */
export type LiveRecord = {
  recordId: string;
  data: Record<string, unknown>;
  /** The sequence number of the last event applied to this record. */
  lastSequence: number;
  /** ISO 8601 timestamp of the last event applied. */
  lastEventAt: string;
};

export type FoldResult = {
  /** Live records at the recovery point (deleted records are excluded). */
  records: LiveRecord[];
  /** Count of records that existed but were deleted at/by the recovery point. */
  deletedCount: number;
  /** Number of events actually applied (those at or before the cutoff). */
  eventsApplied: number;
  /** ISO 8601 timestamp of the newest event applied, or null when none applied. */
  lastEventAt: string | null;
};

function toMs(when: string | Date): number {
  return when instanceof Date ? when.getTime() : Date.parse(when);
}

function toIso(when: string | Date): string {
  return when instanceof Date ? when.toISOString() : new Date(when).toISOString();
}

type WorkingRecord = {
  data: Record<string, unknown>;
  live: boolean;
  lastSequence: number;
  lastEventAt: string;
};

/**
 * Replay `events` and return the live state as of `asOf` (inclusive). Pass `null` to replay the
 * entire log (latest state). Events after the cutoff are ignored; within a record, events are
 * applied in `record_sequence` order regardless of input ordering.
 */
export function foldEventsAsOf(events: DataEvent[], asOf: Date | null): FoldResult {
  const cutoffMs = asOf === null ? Number.POSITIVE_INFINITY : asOf.getTime();

  // Deterministic application order: by record, then by sequence.
  const inWindow = events
    .filter((e) => toMs(e.createdAt) <= cutoffMs)
    .sort((a, b) =>
      a.recordId === b.recordId
        ? a.recordSequence - b.recordSequence
        : a.recordId.localeCompare(b.recordId),
    );

  const working = new Map<string, WorkingRecord>();
  for (const event of inWindow) {
    const eventIso = toIso(event.createdAt);
    const current = working.get(event.recordId);
    switch (event.action) {
      case "created":
        working.set(event.recordId, {
          data: { ...(event.data ?? {}) },
          live: true,
          lastSequence: event.recordSequence,
          lastEventAt: eventIso,
        });
        break;
      case "updated":
        if (current) {
          current.data = { ...current.data, ...(event.data ?? {}) };
          current.live = true;
          current.lastSequence = event.recordSequence;
          current.lastEventAt = eventIso;
        }
        break;
      case "deleted":
        if (current) {
          current.live = false;
          current.lastSequence = event.recordSequence;
          current.lastEventAt = eventIso;
        }
        break;
      case "restored":
        if (current) {
          if (event.data !== null) current.data = { ...event.data };
          current.live = true;
          current.lastSequence = event.recordSequence;
          current.lastEventAt = eventIso;
        }
        break;
    }
  }

  const records: LiveRecord[] = [];
  let deletedCount = 0;
  let lastEventAt: string | null = null;
  for (const [recordId, rec] of working) {
    if (lastEventAt === null || rec.lastEventAt > lastEventAt) lastEventAt = rec.lastEventAt;
    if (rec.live) {
      records.push({
        recordId,
        data: rec.data,
        lastSequence: rec.lastSequence,
        lastEventAt: rec.lastEventAt,
      });
    } else {
      deletedCount += 1;
    }
  }
  records.sort((a, b) => a.recordId.localeCompare(b.recordId));
  return { records, deletedCount, eventsApplied: inWindow.length, lastEventAt };
}

// ───────────────────────────── RPO / RTO ─────────────────────────────

/** Whole-second difference `to - from` (never negative). */
export function diffSeconds(from: string | Date, to: string | Date): number {
  const seconds = Math.round((toMs(to) - toMs(from)) / 1000);
  return seconds < 0 ? 0 : seconds;
}

/** Format a duration in seconds as a compact `1h 5m 9s` / `6m 40s` / `11s` label. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);
  return parts.join(" ");
}

export type DrillInput = {
  /** When the drill (restore) started. */
  startedAt: string | Date;
  /** When the drill finished (sandbox restored + verified). */
  finishedAt: string | Date;
  /** Newest event captured by the backup under test (its recovery point), if known. */
  rpoMarker?: string | null;
  /** Number of live records reconstructed into the sandbox. */
  recordsRestored: number;
  /** Whether the restored artifact passed integrity + row-count verification. */
  verified: boolean;
  /** Optional RTO target in seconds for pass/warn grading. */
  rtoTargetSeconds?: number;
  /** Optional RPO target in seconds for pass/warn grading. */
  rpoTargetSeconds?: number;
};

export type DrillSummary = {
  rtoSeconds: number;
  rtoLabel: string;
  /** Recovery-point age at drill time (now - rpoMarker), or null when unknown. */
  rpoSeconds: number | null;
  rpoLabel: string | null;
  recordsRestored: number;
  verified: boolean;
  /** `pass` (verified + within targets), `warn` (verified but over a target), `fail` (not verified). */
  result: "pass" | "warn" | "fail";
};

/**
 * Grade a DR drill: compute measured RTO (restore wall-clock) and the recovery-point age, then
 * classify against optional targets. Verification failure is always a `fail`; exceeding a target
 * while still verified is a `warn` (mirrors the drill-history mockup's pass/warn/fail states).
 */
export function summarizeDrill(input: DrillInput): DrillSummary {
  const rtoSeconds = diffSeconds(input.startedAt, input.finishedAt);
  const rpoSeconds =
    input.rpoMarker == null ? null : diffSeconds(input.rpoMarker, input.finishedAt);

  let result: DrillSummary["result"];
  if (!input.verified) {
    result = "fail";
  } else {
    const overRto =
      input.rtoTargetSeconds !== undefined && rtoSeconds > input.rtoTargetSeconds;
    const overRpo =
      input.rpoTargetSeconds !== undefined &&
      rpoSeconds !== null &&
      rpoSeconds > input.rpoTargetSeconds;
    result = overRto || overRpo ? "warn" : "pass";
  }

  return {
    rtoSeconds,
    rtoLabel: formatDuration(rtoSeconds),
    rpoSeconds,
    rpoLabel: rpoSeconds === null ? null : formatDuration(rpoSeconds),
    recordsRestored: input.recordsRestored,
    verified: input.verified,
    result,
  };
}
