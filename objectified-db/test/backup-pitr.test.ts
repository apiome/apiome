import { describe, expect, it } from "vitest";

import {
  diffSeconds,
  foldEventsAsOf,
  formatDuration,
  summarizeDrill,
  type DataEvent,
} from "../src/backup/pitr.js";

/** Convenience event builder. */
function ev(
  recordId: string,
  seq: number,
  action: DataEvent["action"],
  data: Record<string, unknown> | null,
  createdAt: string,
): DataEvent {
  return { recordId, recordSequence: seq, action, data, createdAt };
}

describe("foldEventsAsOf — replay semantics", () => {
  it("applies created then merges updated deltas", () => {
    const events = [
      ev("r1", 1, "created", { name: "Ada", role: "eng" }, "2026-06-01T00:00:00Z"),
      ev("r1", 2, "updated", { role: "lead" }, "2026-06-02T00:00:00Z"),
    ];
    const result = foldEventsAsOf(events, null);
    expect(result.records).toHaveLength(1);
    expect(result.records[0]?.data).toEqual({ name: "Ada", role: "lead" });
    expect(result.records[0]?.lastSequence).toBe(2);
    expect(result.eventsApplied).toBe(2);
  });

  it("excludes deleted records from the live set and counts them", () => {
    const events = [
      ev("r1", 1, "created", { v: 1 }, "2026-06-01T00:00:00Z"),
      ev("r1", 2, "deleted", null, "2026-06-03T00:00:00Z"),
    ];
    const result = foldEventsAsOf(events, null);
    expect(result.records).toHaveLength(0);
    expect(result.deletedCount).toBe(1);
  });

  it("restores a deleted record (optionally replacing state)", () => {
    const events = [
      ev("r1", 1, "created", { v: 1 }, "2026-06-01T00:00:00Z"),
      ev("r1", 2, "deleted", null, "2026-06-02T00:00:00Z"),
      ev("r1", 3, "restored", { v: 2 }, "2026-06-03T00:00:00Z"),
    ];
    const result = foldEventsAsOf(events, null);
    expect(result.records).toHaveLength(1);
    expect(result.records[0]?.data).toEqual({ v: 2 });
    expect(result.deletedCount).toBe(0);
  });
});

describe("foldEventsAsOf — point-in-time cutoff", () => {
  const events = [
    ev("r1", 1, "created", { state: "new" }, "2026-06-01T00:00:00Z"),
    ev("r1", 2, "updated", { state: "active" }, "2026-06-05T00:00:00Z"),
    ev("r1", 3, "deleted", null, "2026-06-10T00:00:00Z"),
  ];

  it("recovers the state as of an intermediate instant (inclusive)", () => {
    const result = foldEventsAsOf(events, new Date("2026-06-05T00:00:00Z"));
    expect(result.records[0]?.data).toEqual({ state: "active" });
    expect(result.eventsApplied).toBe(2);
    expect(result.lastEventAt).toBe("2026-06-05T00:00:00.000Z");
  });

  it("recovers the pre-update state just before the second event", () => {
    const result = foldEventsAsOf(events, new Date("2026-06-02T00:00:00Z"));
    expect(result.records[0]?.data).toEqual({ state: "new" });
    expect(result.eventsApplied).toBe(1);
  });

  it("a point before deletion still shows the record as live", () => {
    const result = foldEventsAsOf(events, new Date("2026-06-09T00:00:00Z"));
    expect(result.records).toHaveLength(1);
    expect(result.deletedCount).toBe(0);
  });

  it("a point at/after deletion drops the record", () => {
    const result = foldEventsAsOf(events, new Date("2026-06-10T00:00:00Z"));
    expect(result.records).toHaveLength(0);
    expect(result.deletedCount).toBe(1);
  });
});

describe("foldEventsAsOf — ordering + isolation", () => {
  it("applies events in record_sequence order regardless of input order", () => {
    const events = [
      ev("r1", 2, "updated", { b: 2 }, "2026-06-02T00:00:00Z"),
      ev("r1", 1, "created", { a: 1 }, "2026-06-01T00:00:00Z"),
    ];
    const result = foldEventsAsOf(events, null);
    expect(result.records[0]?.data).toEqual({ a: 1, b: 2 });
  });

  it("keeps records independent and returns them sorted by id", () => {
    const events = [
      ev("r2", 1, "created", { x: 2 }, "2026-06-01T00:00:00Z"),
      ev("r1", 1, "created", { x: 1 }, "2026-06-01T00:00:00Z"),
    ];
    const result = foldEventsAsOf(events, null);
    expect(result.records.map((r) => r.recordId)).toEqual(["r1", "r2"]);
  });

  it("ignores updates to records that do not yet exist at the cutoff", () => {
    const events = [ev("r1", 1, "updated", { orphan: true }, "2026-06-01T00:00:00Z")];
    const result = foldEventsAsOf(events, null);
    expect(result.records).toHaveLength(0);
    expect(result.deletedCount).toBe(0);
  });

  it("returns an empty result for no events", () => {
    expect(foldEventsAsOf([], null)).toEqual({
      records: [],
      deletedCount: 0,
      eventsApplied: 0,
      lastEventAt: null,
    });
  });
});

describe("formatDuration", () => {
  it("formats compact human durations", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(40)).toBe("40s");
    expect(formatDuration(400)).toBe("6m 40s");
    expect(formatDuration(660)).toBe("11m");
    expect(formatDuration(3669)).toBe("1h 1m 9s");
  });
});

describe("diffSeconds", () => {
  it("computes non-negative whole-second gaps", () => {
    expect(diffSeconds("2026-06-23T00:00:00Z", "2026-06-23T00:06:40Z")).toBe(400);
    expect(diffSeconds("2026-06-23T00:06:40Z", "2026-06-23T00:00:00Z")).toBe(0);
  });
});

describe("summarizeDrill", () => {
  it("grades a clean, in-target drill as pass", () => {
    const s = summarizeDrill({
      startedAt: "2026-06-23T00:00:00Z",
      finishedAt: "2026-06-23T00:06:40Z",
      rpoMarker: "2026-06-22T23:48:00Z",
      recordsRestored: 10,
      verified: true,
      rtoTargetSeconds: 1800,
      rpoTargetSeconds: 3600,
    });
    expect(s.rtoLabel).toBe("6m 40s");
    expect(s.rpoLabel).toBe("18m 40s");
    expect(s.result).toBe("pass");
  });

  it("warns when a target is exceeded but the restore verified", () => {
    const s = summarizeDrill({
      startedAt: "2026-06-23T00:00:00Z",
      finishedAt: "2026-06-23T00:40:00Z",
      rpoMarker: null,
      recordsRestored: 1,
      verified: true,
      rtoTargetSeconds: 1800,
    });
    expect(s.rpoSeconds).toBeNull();
    expect(s.result).toBe("warn");
  });

  it("fails when the restore did not verify, regardless of timing", () => {
    const s = summarizeDrill({
      startedAt: "2026-06-23T00:00:00Z",
      finishedAt: "2026-06-23T00:01:00Z",
      recordsRestored: 0,
      verified: false,
    });
    expect(s.result).toBe("fail");
  });
});
