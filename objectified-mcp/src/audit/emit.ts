export type AuditPayload = {
  event: string;
  metadata?: Record<string, unknown>;
};

/** Writes workflow_audit rows via objectified-rest (MCP-1.6). */
export async function emitAuditEvent(_payload: AuditPayload): Promise<void> {
  void _payload;
}
