import fs from "node:fs";

import { COMPLETION_BEGIN, COMPLETION_END } from "./constants.js";

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const BLOCK_RE = new RegExp(
  `${escapeRegExp(COMPLETION_BEGIN)}\\s*\\n([\\s\\S]*?)\\n${escapeRegExp(COMPLETION_END)}\\s*\\n?`,
  "m",
);

export function upsertMarkedCompletionBlock(existing: string, innerBody: string): string {
  const wrapped = `${COMPLETION_BEGIN}\n${innerBody.trimEnd()}\n${COMPLETION_END}\n`;
  const trimmed = existing.replace(/\s+$/, "");
  if (!trimmed.includes(COMPLETION_BEGIN)) {
    return trimmed === "" ? wrapped : `${trimmed}\n\n${wrapped}`;
  }
  return trimmed.replace(BLOCK_RE, wrapped);
}

export function stripMarkedCompletionBlock(existing: string): string {
  const stripped = existing.replace(BLOCK_RE, "");
  return stripped.replace(/\n{3,}/g, "\n\n").trimEnd();
}

export function readRcSafe(path: string): string {
  try {
    return fs.readFileSync(path, "utf8");
  } catch (e: unknown) {
    const code = typeof e === "object" && e && "code" in e ? (e as NodeJS.ErrnoException).code : undefined;
    if (code === "ENOENT") return "";
    throw e;
  }
}
