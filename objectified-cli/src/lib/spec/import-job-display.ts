import type { ImportJobResponse } from "../client.js";
import { ObjectifiedCliError } from "../errors.js";
import { EXIT_CODES } from "../exit-codes.js";

function pickStr(o: Record<string, unknown>, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === "string") {
      const t = v.trim();
      if (t !== "") return t;
    }
  }
  return undefined;
}

export function formatShortJobId(jobId: string): string {
  const t = jobId.trim();
  if (t.length <= 12) return t;
  return `${t.slice(0, 4)}…${t.slice(-4)}`;
}

export function progressSpinnerText(job: ImportJobResponse): string {
  const p = job.progress;
  if (p === undefined || p === null) {
    return `Importing… (${job.state})`;
  }
  const phase = p.phase.trim() !== "" ? p.phase : "working";
  const total = p.total;
  const done = p.completed;
  const item =
    typeof p.currentItem === "string" && p.currentItem.trim() !== ""
      ? ` ${p.currentItem.trim()}`
      : "";
  if (typeof total === "number" && typeof done === "number" && total > 0) {
    return `[${phase} ${String(done)}/${String(total)}]${item}`;
  }
  return `[${phase}]${item}`;
}

function formatRelativeEnglish(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "unknown time ago";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return `${String(sec)}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${String(min)}m ago`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${String(h)}h ago`;
  const d = Math.floor(h / 24);
  return `${String(d)}d ago`;
}

export function formatImportJobStatusHumanLines(
  job: ImportJobResponse,
  tenantSlug: string,
): string[] {
  const jid = formatShortJobId(job.jobId);
  const summary =
    job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
      ? (job.summary as Record<string, unknown>)
      : undefined;
  const project =
    pickStr(summary ?? {}, ["projectSlug", "project_slug", "project"]) ??
    (job.projectId !== undefined && job.projectId !== null && job.projectId.trim() !== ""
      ? `${job.projectId.slice(0, 8)}…`
      : "?");

  const lines: string[] = [];
  lines.push(`Job ${jid} (tenant=${tenantSlug}, project=${project})`);
  lines.push(`State: ${job.state}`);

  const p = job.progress;
  if (p !== undefined && p !== null) {
    const phase = p.phase.trim() !== "" ? p.phase : "working";
    const total = p.total;
    const done = p.completed;
    if (typeof total === "number" && typeof done === "number" && total > 0) {
      lines.push(`Phase: ${phase}  (${String(done)}/${String(total)})`);
    } else {
      lines.push(`Phase: ${phase}`);
    }
  }

  const ev = job.events;
  lines.push(`Events: ${String(Array.isArray(ev) ? ev.length : 0)}`);
  lines.push(`Started ${formatRelativeEnglish(job.createdAt)}.`);

  if (job.state === "pending-approval") {
    lines.push("");
    lines.push(`Run \`objectified spec import commit ${job.jobId}\` to commit, or`);
    lines.push(`    \`objectified spec import cancel ${job.jobId}\` to abort.`);
  }

  return lines;
}

/** Same terminal exit semantics as `spec import` polling (#3310 / T9). */
export function throwIfImportJobWatchTerminalFailure(
  job: ImportJobResponse,
  ctx: { lastRequestId?: string; lastRetriesAttempted?: number },
): void {
  if (job.state === "completed" || job.state === "pending-approval") return;

  if (job.state === "canceled") {
    throw new ObjectifiedCliError({
      message: "Import job was canceled.",
      exitCode: EXIT_CODES.GENERIC,
      title: "Canceled",
      hint: "Re-queue an import or inspect tenant logs if this was unexpected.",
      requestId: ctx.lastRequestId,
      retriesAttempted: ctx.lastRetriesAttempted,
    });
  }

  if (job.state === "failed" || job.state === "rolled-back") {
    const msg =
      job.error !== undefined && job.error !== null && typeof job.error.message === "string"
        ? job.error.message
        : `Import ${job.state}.`;
    throw new ObjectifiedCliError({
      message: msg,
      exitCode: EXIT_CODES.SERVER_ERROR,
      title: "Import failed",
      hint:
        ctx.lastRequestId !== undefined && ctx.lastRequestId !== ""
          ? `Request ID: ${ctx.lastRequestId}`
          : "Retry later or inspect API logs.",
      requestId: ctx.lastRequestId,
      retriesAttempted: ctx.lastRetriesAttempted,
    });
  }

  throw new ObjectifiedCliError({
    message: `Import ended in unexpected state ${JSON.stringify(job.state)}.`,
    exitCode: EXIT_CODES.GENERIC,
    title: "Import failed",
    requestId: ctx.lastRequestId,
    retriesAttempted: ctx.lastRetriesAttempted,
  });
}

export function pickImportJobProjectSlug(job: ImportJobResponse): string | undefined {
  const summary =
    job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
      ? (job.summary as Record<string, unknown>)
      : undefined;
  return pickStr(summary ?? {}, ["projectSlug", "project_slug", "project"]);
}

export function pickImportJobVersionLabel(job: ImportJobResponse): string | undefined {
  const fromResult = job.result?.versionId?.trim();
  if (fromResult !== undefined && fromResult !== "") return fromResult;
  const summary =
    job.summary !== undefined && job.summary !== null && typeof job.summary === "object"
      ? (job.summary as Record<string, unknown>)
      : undefined;
  return pickStr(summary ?? {}, ["versionId", "version_id"]);
}
