import type {
  ProjectSchema,
  VersionSchema,
  VersionTagSchema,
  WorkflowAuditEntryOut,
} from "../client.js";

import {
  domainDisplay,
  ellipsizeMiddle,
  formatRelativeAgo,
  latestPublishedIso,
  versionsCountDisplay,
} from "./format.js";

function kv(label: string, value: string): string {
  const lc = `${label}:`;
  return `  ${lc.padEnd(14)} ${value}`;
}

function isoDateOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = Date.parse(iso);
  if (Number.isNaN(d)) return "—";
  return iso.slice(0, 10);
}

export type VersionLifecycleSummary = {
  total: number;
  published: number;
  draft: number;
  archived: number;
  latestPublished?: { versionLabel: string; publishedAt: string };
};

export function summarizeVersionLifecycle(versions: VersionSchema[]): VersionLifecycleSummary {
  let published = 0;
  let draft = 0;
  let archived = 0;
  let latestPublished: { versionLabel: string; publishedAt: string } | undefined;

  for (const v of versions) {
    const isArchived = v.lifecycle === "archived" || v.enabled === false;
    if (isArchived) {
      archived++;
      continue;
    }
    if (v.published === true) {
      published++;
      const at = v.published_at ?? "";
      if (at !== "" && (!latestPublished || at > latestPublished.publishedAt)) {
        const raw = v.version_id.trim();
        const versionLabel = raw.startsWith("v") ? raw : `v${raw}`;
        latestPublished = { versionLabel, publishedAt: at };
      }
    } else {
      draft++;
    }
  }

  return {
    total: versions.length,
    published,
    draft,
    archived,
    latestPublished,
  };
}

export function revisionToVersionDisplayMap(versions: VersionSchema[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const v of versions) {
    const raw = v.version_id.trim();
    const label = raw.startsWith("v") ? raw : `v${raw}`;
    m.set(v.id, label);
  }
  return m;
}

function formatTagArrow(
  tag: VersionTagSchema,
  revisionToLabel: Map<string, string>,
): string {
  const target =
    (tag.target_version_string !== undefined &&
      tag.target_version_string !== null &&
      tag.target_version_string !== "" &&
      tag.target_version_string) ||
    revisionToLabel.get(tag.version_id) ||
    tag.version_id.slice(0, 8);
  return `${tag.name} → ${target}`;
}

function readDetailString(detail: WorkflowAuditEntryOut["detail"], key: string): string | undefined {
  if (!detail || typeof detail !== "object") return undefined;
  const v = (detail as Record<string, unknown>)[key];
  return typeof v === "string" && v !== "" ? v : undefined;
}

function actorDisplay(entry: WorkflowAuditEntryOut): string {
  const detail = entry.detail;
  const email =
    readDetailString(detail, "actorEmail") ??
    readDetailString(detail, "actor_email") ??
    readDetailString(detail, "email");
  if (email !== undefined) {
    return email.includes("@") ? ellipsizeMiddle(email, 22) : email;
  }
  if (entry.actorId !== undefined && entry.actorId !== null && entry.actorId !== "") {
    return ellipsizeMiddle(entry.actorId, 22);
  }
  return "—";
}

function actionDisplay(action: string): string {
  const parts = action.split(".").filter((p) => p !== "");
  if (parts.length === 0) return action;
  const [head, verb, ...rest] = parts;
  const topic =
    head === "version"
      ? "versions"
      : head === "schema"
        ? "schema"
        : head === "repository"
          ? "repository"
          : head ?? action;
  const tail = rest.length > 0 ? ` ${rest.join(" ")}` : "";
  return verb !== undefined ? `${topic} ${verb}${tail}` : `${topic}${tail}`;
}

function versionTokenForAudit(
  entry: WorkflowAuditEntryOut,
  revisionToLabel: Map<string, string>,
): string {
  const fromDetail =
    readDetailString(entry.detail, "versionLine") ??
    readDetailString(entry.detail, "version_id") ??
    readDetailString(entry.detail, "versionId");
  if (fromDetail !== undefined) {
    const t = fromDetail.trim();
    return t.startsWith("v") || !/\d+\.\d+/.test(t) ? t : `v${t}`;
  }
  if (entry.versionId !== undefined && entry.versionId !== null && entry.versionId !== "") {
    return revisionToLabel.get(entry.versionId) ?? ellipsizeMiddle(entry.versionId, 14);
  }
  return "";
}

export function formatWorkflowAuditActivityLine(
  entry: WorkflowAuditEntryOut,
  revisionToLabel: Map<string, string>,
  nowMs: number,
): string {
  const rel = formatRelativeAgo(entry.createdAt, nowMs).padEnd(8);
  const verb = actionDisplay(entry.action);
  const ver = versionTokenForAudit(entry, revisionToLabel);
  const outcome = entry.outcome !== "success" ? ` (${entry.outcome})` : "";
  const middle = [verb, ver !== "" ? ver : undefined].filter(Boolean).join(" ");
  const actor = actorDisplay(entry);
  return `    ${rel} ${middle}${outcome}  ${actor}`;
}

export function formatProjectsShowHumanLines(opts: {
  project: ProjectSchema;
  tenantSlug: string;
  versions: VersionSchema[];
  tags: VersionTagSchema[];
  activity: WorkflowAuditEntryOut[];
  titleBold: (s: string) => string;
  separator: string;
  now?: Date;
}): string[] {
  const nowMs = (opts.now ?? new Date()).getTime();
  const p = opts.project;
  const summary = summarizeVersionLifecycle(opts.versions);
  const revisionToLabel = revisionToVersionDisplayMap(opts.versions);

  const versionsLine = versionsLineFromProjectOrVersions(p, summary);
  const latestLine = latestLineFromProjectOrVersions(p, summary);

  const tagsSorted = [...opts.tags].sort((a, b) => a.name.localeCompare(b.name));
  const tagsLine =
    tagsSorted.length === 0
      ? "—"
      : tagsSorted.map((t) => formatTagArrow(t, revisionToLabel)).join(", ");

  const createdEmail = p.creator_email ?? "";
  const createdIso = p.created_at ?? "";
  const created =
    createdIso !== ""
      ? `${isoDateOnly(createdIso)}${createdEmail !== "" ? ` by ${createdEmail}` : ""}`
      : "—";

  const desc = (p.description ?? "").trim();
  const descDisp = desc !== "" ? desc : "—";

  const lines: string[] = [
    "",
    `  ${opts.titleBold(`${p.name}  (${p.slug})`)}`,
    `  ${opts.separator}`,
    kv("ID", ellipsizeMiddle(p.id, 36)),
    kv("Tenant", opts.tenantSlug),
    kv("Domain", domainDisplay(p)),
    kv("Description", descDisp),
    kv("Created", created),
    kv("Updated", isoDateOnly(p.updated_at ?? null)),
    kv("Versions", versionsLine),
    kv("Latest", latestLine),
    kv("Tags (latest)", tagsLine),
    "",
    "  Recent activity:",
    ...opts.activity.map((e) => formatWorkflowAuditActivityLine(e, revisionToLabel, nowMs)),
  ];

  if (opts.activity.length === 0) {
    lines.push("    —");
  }

  lines.push("");
  return lines;
}

/** Uses aggregate counts from API/project payload when version list is empty (same helpers as list view). */
export function versionsLineFromProjectOrVersions(
  project: ProjectSchema,
  summary: VersionLifecycleSummary,
): string {
  const listed = summary.total;
  if (listed > 0) {
    return `${String(summary.total)}  (${String(summary.published)} published, ${String(summary.draft)} draft, ${String(summary.archived)} archived)`;
  }
  const vc = versionsCountDisplay(project);
  return vc === "—" ? "0" : vc;
}

export function latestLineFromProjectOrVersions(
  project: ProjectSchema,
  summary: VersionLifecycleSummary,
): string {
  if (summary.latestPublished !== undefined) {
    const pubDate = isoDateOnly(summary.latestPublished.publishedAt);
    return `${summary.latestPublished.versionLabel}   published ${pubDate}`;
  }
  const iso = latestPublishedIso(project);
  if (iso !== undefined) {
    const top = (project as Record<string, unknown>).latest_published_version;
    const raw = typeof top === "string" ? top.trim() : "";
    const ver = raw !== "" ? (raw.startsWith("v") ? raw : `v${raw}`) : undefined;
    const pubDate = isoDateOnly(iso);
    return ver !== undefined ? `${ver}   published ${pubDate}` : `published ${pubDate}`;
  }
  return "—";
}
