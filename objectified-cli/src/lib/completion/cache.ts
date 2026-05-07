import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

import { COMPLETION_CACHE_SEGMENT, COMPLETION_CACHE_TTL_MS } from "./constants.js";

export function completionCacheDir(): string {
  return join(homedir(), ".cache", "objectified", COMPLETION_CACHE_SEGMENT);
}

function cacheFile(profileKey: string, parts: string[]): string {
  const id = createHash("sha256").update(`${profileKey}\0${parts.join("\0")}`).digest("hex").slice(0, 40);
  return join(completionCacheDir(), `${id}.json`);
}

type CacheRow = { expiresAt: number; values: string[] };

export async function readCompletionCache(
  profileKey: string,
  parts: string[],
): Promise<string[] | undefined> {
  try {
    const raw = await readFile(cacheFile(profileKey, parts), "utf8");
    const row = JSON.parse(raw) as CacheRow;
    if (!Array.isArray(row.values) || typeof row.expiresAt !== "number") return undefined;
    if (Date.now() > row.expiresAt) return undefined;
    return row.values;
  } catch {
    return undefined;
  }
}

export async function writeCompletionCache(
  profileKey: string,
  parts: string[],
  values: string[],
): Promise<void> {
  const dir = completionCacheDir();
  await mkdir(dir, { recursive: true });
  const row: CacheRow = { expiresAt: Date.now() + COMPLETION_CACHE_TTL_MS, values };
  await writeFile(cacheFile(profileKey, parts), `${JSON.stringify(row)}\n`, "utf8");
}

/** Returns cached values, or runs fetcher (network). On failure returns []. */
export async function withCompletionCache(
  profileKey: string,
  parts: string[],
  fetcher: () => Promise<string[]>,
): Promise<string[]> {
  const hit = await readCompletionCache(profileKey, parts);
  if (hit !== undefined) return hit;
  try {
    const values = await fetcher();
    await writeCompletionCache(profileKey, parts, values);
    return values;
  } catch {
    return [];
  }
}
