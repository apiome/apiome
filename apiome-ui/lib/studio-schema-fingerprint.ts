import type { ChatStudioContext } from '@/app/ade/studio/components/chatbot/chat-context';
import { stableStringify } from './stable-json';

/**
 * Canonical snapshot of schema-bearing studio state for Ollama cache keys (#526).
 * Selection is intentionally omitted: it only affects prompt wording, not the
 * underlying spec the assistant must stay aligned with.
 */
export function canonicalStudioSchemaState(ctx: ChatStudioContext): unknown {
  const classes = [...ctx.classes]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((c) => ({ id: c.id, name: c.name, schema: c.schema ?? null }));
  const properties = [...ctx.properties]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((p) => ({
      id: p.id,
      name: p.name,
      description: p.description ?? null,
      type: p.type ?? null,
      format: p.format ?? null,
      required: p.required ?? null,
    }));
  return {
    versionId: ctx.version?.id ?? null,
    projectId: ctx.project?.id ?? null,
    classes,
    properties,
  };
}

async function sha256HexUtf8(text: string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error('Web Crypto is required for studio schema fingerprint');
  }
  const bytes = new TextEncoder().encode(text);
  const digest = await subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/** Memoises fingerprints so repeated sends with an unchanged schema skip re-hashing. */
const FINGERPRINT_CACHE_MAX = 16;
const fingerprintCache = new Map<string, string>();

/** SHA-256 hex of canonical schema state — send as `schemaContextFingerprint` on `/api/ollama/chat`. */
export async function computeStudioSchemaFingerprint(ctx: ChatStudioContext): Promise<string> {
  const key = stableStringify(canonicalStudioSchemaState(ctx));
  const cached = fingerprintCache.get(key);
  if (cached !== undefined) return cached;
  const hash = await sha256HexUtf8(key);
  if (fingerprintCache.size >= FINGERPRINT_CACHE_MAX) {
    const oldest = fingerprintCache.keys().next().value;
    if (oldest !== undefined) fingerprintCache.delete(oldest);
  }
  fingerprintCache.set(key, hash);
  return hash;
}
