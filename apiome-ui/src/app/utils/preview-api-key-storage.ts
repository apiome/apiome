/**
 * Persists a tenant-scoped API key on the device so the Published Versions dashboard
 * can open private schema / Swagger / Arazzo / JSON URLs without prompting every time.
 * Values live only in localStorage (never sent except as auth on REST requests the user opens).
 */

const STORAGE_PREFIX = 'apiome.previewApiKey.v1:';

export function previewApiKeyStorageKey(tenantId: string): string {
  return `${STORAGE_PREFIX}${tenantId}`;
}

export function getStoredPreviewApiKey(tenantId: string | null | undefined): string | null {
  if (!tenantId || typeof window === 'undefined') return null;
  try {
    const v = localStorage.getItem(previewApiKeyStorageKey(tenantId));
    const t = v?.trim();
    return t ? t : null;
  } catch {
    return null;
  }
}

export function setStoredPreviewApiKey(tenantId: string, apiKey: string): void {
  if (typeof window === 'undefined') return;
  const t = apiKey.trim();
  if (!t) {
    clearStoredPreviewApiKey(tenantId);
    return;
  }
  try {
    localStorage.setItem(previewApiKeyStorageKey(tenantId), t);
  } catch {
    /* quota / private mode */
  }
}

export function clearStoredPreviewApiKey(tenantId: string | null | undefined): void {
  if (!tenantId || typeof window === 'undefined') return;
  try {
    localStorage.removeItem(previewApiKeyStorageKey(tenantId));
  } catch {
    /* ignore */
  }
}
