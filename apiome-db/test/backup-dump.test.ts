import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  applyUnifiedPatch,
  createDumpBackup,
  formatDate,
  listBackupEntries,
  parseBackupFilename,
  planReconstruction,
  reconstructContent,
  runUnifiedDiff,
  type BackupDumpDeps,
  type BackupEntry,
} from "../src/backup/dump.js";
import { CliError } from "../src/errors.js";

let dir: string;
beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "apiome-dump-"));
});
afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

/**
 * Fake diff/apply that model real semantics without shelling out: a "patch" is a JSON envelope
 * recording the exact from→to transition, and applying it asserts the base matches. This exercises
 * the chain-reconstruction ordering faithfully.
 */
function fakeDeps(dumps: string[]): BackupDumpDeps {
  let i = 0;
  return {
    dump: async () => {
      const d = dumps[i] ?? dumps[dumps.length - 1];
      i += 1;
      return d as string;
    },
    diff: async (oldText, newText) => JSON.stringify({ from: oldText, to: newText }),
    applyPatch: async (oldText, patchText) => {
      const { from, to } = JSON.parse(patchText) as { from: string; to: string };
      if (from !== oldText) {
        throw new Error("fake applyPatch: base mismatch (wrong reconstruction order)");
      }
      return to;
    },
  };
}

describe("formatDate", () => {
  it("formats a local YYYY-MM-DD", () => {
    expect(formatDate(new Date(2026, 5, 7))).toBe("2026-06-07");
    expect(formatDate(new Date(2026, 11, 23))).toBe("2026-12-23");
  });
});

describe("parseBackupFilename", () => {
  it("classifies full and patch files, ignores others", () => {
    expect(parseBackupFilename("backup-2026-06-23.sql")).toEqual({
      date: "2026-06-23",
      filename: "backup-2026-06-23.sql",
      kind: "full",
    });
    expect(parseBackupFilename("backup-2026-06-23.sql.patch")).toEqual({
      date: "2026-06-23",
      filename: "backup-2026-06-23.sql.patch",
      kind: "patch",
    });
    expect(parseBackupFilename("notes.txt")).toBeNull();
    expect(parseBackupFilename("backup-2026-6-3.sql")).toBeNull();
  });
});

describe("listBackupEntries", () => {
  it("returns [] for a missing directory", async () => {
    expect(await listBackupEntries(path.join(dir, "nope"))).toEqual([]);
  });
  it("lists and sorts backup files by date ascending", async () => {
    await writeFile(path.join(dir, "backup-2026-06-23.sql.patch"), "p");
    await writeFile(path.join(dir, "backup-2026-06-21.sql"), "f");
    await writeFile(path.join(dir, "unrelated.log"), "x");
    const entries = await listBackupEntries(dir);
    expect(entries.map((e) => e.date)).toEqual(["2026-06-21", "2026-06-23"]);
    expect(entries[0]?.kind).toBe("full");
  });
});

describe("planReconstruction", () => {
  const entries: BackupEntry[] = [
    { date: "2026-06-01", filename: "backup-2026-06-01.sql", kind: "full" },
    { date: "2026-06-02", filename: "backup-2026-06-02.sql.patch", kind: "patch" },
    { date: "2026-06-03", filename: "backup-2026-06-03.sql.patch", kind: "patch" },
    { date: "2026-06-04", filename: "backup-2026-06-04.sql", kind: "full" },
    { date: "2026-06-05", filename: "backup-2026-06-05.sql.patch", kind: "patch" },
  ];

  it("anchors at the latest full and replays patches up to the target", () => {
    expect(planReconstruction(entries, 2)).toEqual({ baseIndex: 0, patchIndices: [1, 2] });
    expect(planReconstruction(entries, 5 - 1)).toEqual({ baseIndex: 3, patchIndices: [4] });
    expect(planReconstruction(entries, 3)).toEqual({ baseIndex: 3, patchIndices: [] });
  });

  it("throws when no full precedes the target", () => {
    const orphan: BackupEntry[] = [
      { date: "2026-06-02", filename: "backup-2026-06-02.sql.patch", kind: "patch" },
    ];
    expect(() => planReconstruction(orphan, 0)).toThrow(CliError);
  });

  it("rejects out-of-range targets", () => {
    expect(() => planReconstruction(entries, 99)).toThrow(CliError);
  });
});

describe("reconstructContent (chain replay)", () => {
  it("replays the patch chain back to the exact prior state", async () => {
    // base full = "v1"; patch1: v1→v2; patch2: v2→v3.
    await writeFile(path.join(dir, "backup-2026-06-01.sql"), "v1");
    await writeFile(
      path.join(dir, "backup-2026-06-02.sql.patch"),
      JSON.stringify({ from: "v1", to: "v2" }),
    );
    await writeFile(
      path.join(dir, "backup-2026-06-03.sql.patch"),
      JSON.stringify({ from: "v2", to: "v3" }),
    );
    const entries = await listBackupEntries(dir);
    const deps = fakeDeps([]);
    expect(await reconstructContent(dir, entries, 2, deps)).toBe("v3");
    expect(await reconstructContent(dir, entries, 1, deps)).toBe("v2");
    expect(await reconstructContent(dir, entries, 0, deps)).toBe("v1");
  });
});

describe("createDumpBackup", () => {
  it("writes a full dump when the directory is empty", async () => {
    const res = await createDumpBackup(dir, fakeDeps(["DUMP-A"]), { now: new Date(2026, 5, 1) });
    expect(res.kind).toBe("full");
    expect(res.priorDate).toBeNull();
    expect(await readFile(path.join(dir, "backup-2026-06-01.sql"), "utf8")).toBe("DUMP-A");
  });

  it("writes a diff against the prior day on a later run", async () => {
    await createDumpBackup(dir, fakeDeps(["DUMP-A"]), { now: new Date(2026, 5, 1) });
    const res = await createDumpBackup(dir, fakeDeps(["DUMP-B"]), { now: new Date(2026, 5, 2) });
    expect(res.kind).toBe("patch");
    expect(res.priorDate).toBe("2026-06-01");
    const patch = await readFile(path.join(dir, "backup-2026-06-02.sql.patch"), "utf8");
    expect(JSON.parse(patch)).toEqual({ from: "DUMP-A", to: "DUMP-B" });
  });

  it("diffs day 3 against the reconstructed day-2 state (chain)", async () => {
    await createDumpBackup(dir, fakeDeps(["A"]), { now: new Date(2026, 5, 1) });
    await createDumpBackup(dir, fakeDeps(["B"]), { now: new Date(2026, 5, 2) }); // patch A→B
    const res = await createDumpBackup(dir, fakeDeps(["C"]), { now: new Date(2026, 5, 3) }); // patch B→C
    expect(res.kind).toBe("patch");
    const patch = await readFile(path.join(dir, "backup-2026-06-03.sql.patch"), "utf8");
    // Prior content must be the reconstructed "B", not the raw base "A".
    expect(JSON.parse(patch)).toEqual({ from: "B", to: "C" });
  });

  it("--full forces a full dump even when a prior day exists", async () => {
    await createDumpBackup(dir, fakeDeps(["A"]), { now: new Date(2026, 5, 1) });
    const res = await createDumpBackup(dir, fakeDeps(["B"]), { now: new Date(2026, 5, 2), force: true });
    expect(res.kind).toBe("full");
    expect(await readFile(path.join(dir, "backup-2026-06-02.sql"), "utf8")).toBe("B");
  });

  it("re-running on the same day replaces that day's file", async () => {
    await createDumpBackup(dir, fakeDeps(["A"]), { now: new Date(2026, 5, 1) });
    await createDumpBackup(dir, fakeDeps(["A2"]), { now: new Date(2026, 5, 1) });
    const files = (await readdir(dir)).filter((f) => f.startsWith("backup-2026-06-01"));
    expect(files).toEqual(["backup-2026-06-01.sql"]);
    expect(await readFile(path.join(dir, "backup-2026-06-01.sql"), "utf8")).toBe("A2");
  });
});

// The real diff/patch helpers wrap the system tools; a direct round-trip proves the format the
// operator's `patch` will consume. Skipped automatically only if the host lacks the tools is NOT
// done here — GNU diff/patch are part of the project's POSIX baseline, so we assert the round-trip.
describe("runUnifiedDiff + applyUnifiedPatch (real tools)", () => {
  it("produces a patch that reconstructs the new text from the old", async () => {
    const oldText = "line1\nline2\nline3\n";
    const newText = "line1\nline2 changed\nline3\nline4\n";
    const patch = await runUnifiedDiff(oldText, newText);
    expect(patch).toContain("@@");
    expect(await applyUnifiedPatch(oldText, patch)).toBe(newText);
  });

  it("treats identical inputs as an empty patch (no-op apply)", async () => {
    const text = "same\ncontent\n";
    const patch = await runUnifiedDiff(text, text);
    expect(patch).toBe("");
    expect(await applyUnifiedPatch(text, patch)).toBe(text);
  });
});
