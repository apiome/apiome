import { describe, expect, it } from "vitest";

import {
  DEFAULT_RETENTION,
  describeRetention,
  parseCount,
  selectExpired,
  type Retainable,
} from "../src/backup/retention.js";
import { CliError } from "../src/errors.js";

const now = new Date("2026-06-23T00:00:00.000Z");

/** Build a backup id `d<n>` created `n` days before `now`. */
function dayOld(n: number): Retainable {
  return { id: `d${n}`, createdAt: new Date(now.getTime() - n * 86400_000).toISOString() };
}

describe("selectExpired", () => {
  it("prunes nothing when no guards are set", () => {
    expect(selectExpired([dayOld(100)], {}, now)).toEqual([]);
  });

  it("prunes by age beyond keepDays", () => {
    const backups = [dayOld(1), dayOld(10), dayOld(40), dayOld(90)];
    const expired = selectExpired(backups, { keepDays: 30 }, now).map((b) => b.id);
    expect(expired.sort()).toEqual(["d40", "d90"]);
  });

  it("never prunes the keepLast most-recent copies even when aged out", () => {
    const backups = [dayOld(40), dayOld(50), dayOld(60)]; // all older than 30d
    const expired = selectExpired(backups, { keepDays: 30, keepLast: 2 }, now).map((b) => b.id);
    expect(expired).toEqual(["d60"]); // d40 + d50 protected by keepLast=2
  });

  it("with only keepLast set, prunes nothing (count guard alone never deletes)", () => {
    const backups = [dayOld(1), dayOld(2), dayOld(3)];
    expect(selectExpired(backups, { keepLast: 1 }, now)).toEqual([]);
  });

  it("keeps a sole aged backup when keepLast protects it", () => {
    expect(selectExpired([dayOld(365)], { keepDays: 30, keepLast: 7 }, now)).toEqual([]);
  });

  it("never prunes entries with an unparseable timestamp", () => {
    const backups: Retainable[] = [{ id: "bad", createdAt: "not-a-date" }, dayOld(90)];
    const expired = selectExpired(backups, { keepDays: 30, keepLast: 0 }, now).map((b) => b.id);
    expect(expired).toEqual(["d90"]);
  });
});

describe("parseCount", () => {
  it("parses non-negative integers", () => {
    expect(parseCount("0", "--keep-last")).toBe(0);
    expect(parseCount("7", "--keep-last")).toBe(7);
    expect(parseCount(undefined, "--keep-last")).toBeUndefined();
  });
  it("rejects negatives and non-integers", () => {
    expect(() => parseCount("-1", "--keep-days")).toThrow(CliError);
    expect(() => parseCount("3.5", "--keep-days")).toThrow(CliError);
    expect(() => parseCount("x", "--keep-days")).toThrow(CliError);
  });
});

describe("describeRetention", () => {
  it("renders both guards and the forever default", () => {
    expect(describeRetention(DEFAULT_RETENTION)).toBe("keep 30d · keep last 7");
    expect(describeRetention({})).toBe("retain forever");
  });
});
