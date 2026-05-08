import type { VersionSchema, VersionTagSchema } from "../client.js";

import { ellipsizeEnd, ellipsizeMiddle } from "../projects/format.js";

import { versionIsArchived } from "./list-query.js";

const versionW = 14;
/** Fits `published [frozen]` (ASCII) or `published ❄` (glyph). */
const stateW = 18;
const tagsW = 14;
const publishedW = 10;
const authorW = 18;

export function formatVersionLabel(versionId: string): string {
  const raw = versionId.trim();
  return raw.startsWith("v") || raw.startsWith("V") ? raw : `v${raw}`;
}

/** Map revision id (`versions.id`) → distinct tag names pointing at that revision (API iteration order). */
export function buildTagsByRevisionId(tags: VersionTagSchema[]): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const t of tags) {
    const rev = t.version_id;
    const name = t.name.trim();
    if (rev === "" || name === "") continue;
    const cur = m.get(rev) ?? [];
    if (!cur.includes(name)) cur.push(name);
    m.set(rev, cur);
  }
  return m;
}

function primaryStateWord(v: VersionSchema): string {
  if (versionIsArchived(v)) return "archived";
  if (v.published === true) return "published";
  return "draft";
}

function publishedDateDisplay(v: VersionSchema): string {
  const iso = v.published_at;
  if (!iso || iso === "") return "—";
  return iso.slice(0, 10);
}

function authorDisplay(v: VersionSchema): string {
  const a = v.author?.trim();
  if (a !== undefined && a !== "") return a;
  const email = v.creator_email?.trim();
  if (email !== undefined && email !== "") return email;
  const name = v.creator_name?.trim();
  if (name !== undefined && name !== "") return name;
  return "—";
}

export type VersionsListFormatOpts = {
  versions: VersionSchema[];
  tagsByRevisionId: Map<string, string[]>;
  /** Project slug for footer messaging (human output). */
  projectLabel: string;
  truncated: boolean;
  totalAfterPipeline: number;
  /** When false, frozen revisions use `[frozen]` instead of a snowflake glyph. */
  useGlyphForFrozen: boolean;
  freezeGlyph: string;
  freezeBracket: string;
};

export function formatVersionsListHumanLines(opts: VersionsListFormatOpts): string[] {
  const headers = ["VERSION", "STATE", "TAGS", "PUBLISHED", "AUTHOR"];
  const widths = [versionW, stateW, tagsW, publishedW, authorW];
  const headerLine = `  ${headers
    .map((h, i) => {
      const w = widths[i] ?? 0;
      return ellipsizeEnd(h, w).padEnd(w);
    })
    .join(" ")}`;

  const lines: string[] = [headerLine];

  for (const v of opts.versions) {
    const verCell = ellipsizeMiddle(formatVersionLabel(v.version_id), versionW);
    const archived = versionIsArchived(v);
    const frozen = !archived && Boolean(v.published) && v.publishedImmutable === true;
    let stateText = primaryStateWord(v);
    if (frozen) {
      stateText =
        opts.useGlyphForFrozen && opts.freezeGlyph !== ""
          ? `${stateText} ❄`
          : `${stateText}${opts.freezeBracket}`;
    }
    const stateCell = ellipsizeEnd(stateText, stateW).padEnd(stateW);
    const tagNames = opts.tagsByRevisionId.get(v.id) ?? [];
    const tagsRaw = tagNames.join(", ");
    const tagsCell = ellipsizeEnd(tagsRaw, tagsW).padEnd(tagsW);
    const pubCell = ellipsizeEnd(publishedDateDisplay(v), publishedW).padEnd(publishedW);
    const authCell = ellipsizeEnd(authorDisplay(v), authorW).padEnd(authorW);
    let row = `  ${verCell.padEnd(versionW)} ${stateCell} ${tagsCell} ${pubCell} ${authCell}`;
    if (frozen && opts.useGlyphForFrozen && opts.freezeGlyph !== "") {
      row = row.replace("❄", opts.freezeGlyph);
    }
    lines.push(row);
  }

  lines.push("");
  const total = opts.totalAfterPipeline;
  const showing = opts.versions.length;
  const noun = total === 1 ? "version" : "versions";
  let summary = `${String(total)} ${noun} in '${opts.projectLabel}'`;
  if (opts.truncated && total > showing) {
    summary += ` (showing latest ${String(showing)} of ${String(total)}). Use --all to list all.`;
  } else {
    summary += ".";
  }
  lines.push(summary);

  return lines;
}
