/**
 * Runs a single specification import for objectified-rest (tsx subprocess).
 * Reads JSON stdin from the REST layer; prints newline-delimited JSON to stdout (logs on stderr only).
 * While the import is in progress, emits `{ partial: true, status }` lines; the final line omits `partial`.
 */

import { stdin as input } from "node:process";

import { parse as parseYaml } from "yaml";

import type { ImportJobInput } from "../lib/db/import-helper";
import { getImportStatus, startImport } from "../lib/db/import-helper";

type Payload = {
  tenant_id: string;
  user_id: string;
  rest_job_id: string;
  metadata: {
    source_kind: string;
    project: { name: string; slug: string; description?: string | null };
    version: { version_id: string; description?: string | null };
    existing_project_id?: string | null;
    options?: Record<string, unknown>;
  };
  document_base64: string;
  filename?: string | null;
  content_type?: string | null;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of input) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function mapSourceKind(kind: string): "openapi" | "arazzo" {
  const k = kind.trim().toLowerCase();
  if (k === "openapi-3" || k === "openapi3" || k === "swagger" || k === "openapi") {
    return "openapi";
  }
  if (k === "arazzo") {
    return "arazzo";
  }
  throw new Error(
    `Unsupported source_kind "${kind}" for REST import (supported: openapi-3, arazzo).`,
  );
}

function parseDocument(text: string): unknown {
  const t = text.trim();
  if (t.startsWith("{") || t.startsWith("[")) {
    return JSON.parse(text) as unknown;
  }
  return parseYaml(text) as unknown;
}

function optionsFromMeta(meta: Payload["metadata"]): ImportJobInput["options"] {
  const o = meta.options ?? {};
  const sel = (o.selected_schemas ?? o.selectedSchemas) as unknown;
  const selectedSchemas = Array.isArray(sel) ? (sel as string[]) : [];
  return {
    selectedSchemas,
    dryRun: Boolean(o.dry_run ?? o.dryRun),
    incrementalMode: true,
    autoLayout: Boolean(o.auto_layout ?? o.autoLayout),
    createRelationships: Boolean(o.create_relationships ?? o.createRelationships),
    applyNamingConvention: Boolean(o.apply_naming_convention ?? o.applyNamingConvention),
    classNamingConvention: (o.class_naming_convention ?? o.classNamingConvention) as
      | ImportJobInput["options"]["classNamingConvention"]
      | undefined,
    propertyNamingConvention: (o.property_naming_convention ?? o.propertyNamingConvention) as
      | ImportJobInput["options"]["propertyNamingConvention"]
      | undefined,
    classNameMap: (o.class_name_map ?? o.classNameMap) as Record<string, string> | undefined,
    classPrefix: (o.class_prefix ?? o.classPrefix) as string | undefined,
    classSuffix: (o.class_suffix ?? o.classSuffix) as string | undefined,
    typeMapping: (o.type_mapping ?? o.typeMapping) as Record<string, unknown> | undefined,
    defaultValues: (o.default_values ?? o.defaultValues) as Record<string, unknown> | undefined,
    requiredOverrides: (o.required_overrides ?? o.requiredOverrides) as
      | Record<string, Record<string, boolean>>
      | undefined,
    descriptionOverrides: (o.description_overrides ?? o.descriptionOverrides) as
      | Record<string, Record<string, string>>
      | undefined,
    generateExamples: Boolean(o.generate_examples ?? o.generateExamples),
  };
}

function progressToRest(st: Awaited<ReturnType<typeof getImportStatus>>): Record<string, unknown> | undefined {
  const p = st.progress;
  if (!p) {
    return undefined;
  }
  return {
    phase: p.phase,
    total: p.total,
    completed: p.completed,
    current_item: p.currentItem ?? null,
  };
}

function resultToRest(
  st: Awaited<ReturnType<typeof getImportStatus>>,
  meta: Payload["metadata"],
): Record<string, unknown> | undefined {
  const r = st.result;
  if (!r?.projectId || !r.versionId) {
    return undefined;
  }
  return {
    project_id: r.projectId,
    project_slug: meta.project.slug,
    version_id: meta.version.version_id,
    version_record_id: r.versionId,
  };
}

function buildRestStatus(
  st: Awaited<ReturnType<typeof getImportStatus>>,
  restJobId: string,
  meta: Payload["metadata"],
): Record<string, unknown> {
  return {
    job_id: restJobId,
    state: st.state,
    percent: st.percent,
    events: st.events.map((e) => ({
      id: e.id,
      ts: e.ts,
      level: e.level,
      code: e.code,
      message: e.message,
      context: e.context ?? null,
    })),
    progress: progressToRest(st),
    summary: st.summary ?? null,
    result: resultToRest(st, meta),
  };
}

/** One JSON object per line so objectified-rest can update poll status while the import runs. */
function writeWorkerStdoutLine(obj: unknown): void {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

async function runFromPayload(payload: Payload): Promise<void> {
  const sourceKind = mapSourceKind(payload.metadata.source_kind);
  let document: unknown;
  try {
    const bytes = Buffer.from(payload.document_base64, "base64");
    const text = bytes.toString("utf8");
    document = parseDocument(text);
  } catch (e: unknown) {
    throw new Error(`Could not parse specification document: ${(e as Error)?.message ?? e}`);
  }

  const existing = payload.metadata.existing_project_id?.trim();
  const inputPayload: ImportJobInput = {
    tenantId: payload.tenant_id,
    userId: payload.user_id,
    sourceKind,
    document,
    project: {
      name: payload.metadata.project.name,
      slug: payload.metadata.project.slug,
      description: payload.metadata.project.description ?? undefined,
    },
    version: {
      versionId: payload.metadata.version.version_id,
      description: payload.metadata.version.description ?? null,
    },
    options: optionsFromMeta(payload.metadata),
    existingProjectId: existing !== undefined && existing !== "" ? existing : undefined,
  };

  const { jobId } = await startImport(inputPayload);

  const pending = new Set(["queued", "running", "committing"]);

  for (;;) {
    const st = await getImportStatus(jobId);
    const restStatus = buildRestStatus(st, payload.rest_job_id, payload.metadata);
    if (!pending.has(st.state)) {
      writeWorkerStdoutLine({ ok: true, job_id: payload.rest_job_id, status: restStatus });
      return;
    }
    writeWorkerStdoutLine({
      ok: true,
      partial: true,
      job_id: payload.rest_job_id,
      status: restStatus,
    });
    await sleep(400);
  }
}

async function main(): Promise<void> {
  const raw = await readStdin();
  let payload: Payload;
  try {
    payload = JSON.parse(raw) as Payload;
  } catch (e: unknown) {
    throw new Error(`Invalid JSON stdin: ${(e as Error)?.message ?? e}`);
  }
  await runFromPayload(payload);
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  writeWorkerStdoutLine({ ok: false, error: message });
  process.exit(1);
});
