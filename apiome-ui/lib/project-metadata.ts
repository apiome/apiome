/** Projects.metadata may arrive as an object or a JSON string (proxies / legacy). */
export function coerceProjectMetadataRecord(raw: unknown): Record<string, unknown> | undefined {
  if (raw == null) return undefined;
  if (typeof raw === 'string') {
    try {
      const p = JSON.parse(raw) as unknown;
      if (p !== null && typeof p === 'object' && !Array.isArray(p)) return p as Record<string, unknown>;
    } catch {
      /* ignore */
    }
    return undefined;
  }
  if (typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>;
  return undefined;
}

/** Studio `Project` rows often omit `description` in TS even when the API returns it. */
export function projectDescriptionForOpenApiPreview(project: unknown): string | undefined {
  if (project == null || typeof project !== 'object') return undefined;
  const d = (project as { description?: unknown }).description;
  if (typeof d !== 'string') return undefined;
  const t = d.trim();
  return t || undefined;
}
