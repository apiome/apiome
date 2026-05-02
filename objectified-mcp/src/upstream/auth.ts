/**
 * API key used against objectified-rest (HTTP header or stdio env).
 * Full resolution ships in MCP-1.3 / MCP-1.4.
 */
export function resolveApiKeyFromEnv(): string | undefined {
  const key = process.env.OBJECTIFIED_MCP_KEY;
  return key?.trim() || undefined;
}

export function resolveRestBaseUrl(): string {
  const raw = process.env.OBJECTIFIED_REST_URL?.trim();
  if (raw) return raw.replace(/\/$/, '');
  return 'http://127.0.0.1:8000';
}
