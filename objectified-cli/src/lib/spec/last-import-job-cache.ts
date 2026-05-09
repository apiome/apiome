import fs from "node:fs";
import os from "node:os";
import path from "node:path";

function tenantCacheSegment(tenantSlug: string): string {
  return tenantSlug.replace(/[^a-zA-Z0-9._-]+/g, "_");
}

/** Per-tenant file: latest import job id from a successful `spec import` POST (#3311). */
export function lastImportJobCacheFilePath(tenantSlug: string): string {
  return path.join(
    os.homedir(),
    ".cache",
    "objectified",
    `last-import-job-${tenantCacheSegment(tenantSlug)}.txt`,
  );
}

export function writeLastImportJobId(tenantSlug: string, jobId: string): void {
  const id = jobId.trim();
  if (id === "") return;
  const filePath = lastImportJobCacheFilePath(tenantSlug);
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, `${id}\n`, "utf8");
  } catch {
    // Cache is a convenience; ignore write failures so they don't fail CLI commands.
  }
}

export function readLastImportJobId(tenantSlug: string): string | undefined {
  const filePath = lastImportJobCacheFilePath(tenantSlug);
  try {
    const raw = fs.readFileSync(filePath, "utf8").trim();
    return raw === "" ? undefined : raw;
  } catch {
    // Cache is a convenience; treat any read error (including ENOENT) as a cache miss.
    return undefined;
  }
}
