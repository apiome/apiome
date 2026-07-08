/**
 * Cataloger notes — types and pure helpers (V2-MCP-36.3 / MCAT-22.3, #4666).
 *
 * Human notes on MCP endpoints, kept separate from server-reported discovery data.
 */

/** One cataloger note returned by the REST API. */
export interface McpEndpointNote {
  id: string;
  endpointId: string;
  body: string;
  createdBy: string;
  createdByName: string | null;
  createdByEmail: string | null;
  updatedBy: string | null;
  updatedByName: string | null;
  updatedByEmail: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Build a display label for a note's author from joined user fields. */
export function mcpEndpointNoteAuthorLabel(note: McpEndpointNote): string {
  const name = note.updatedByName ?? note.createdByName;
  const email = note.updatedByEmail ?? note.createdByEmail;
  if (name && email) return `${name} (${email})`;
  if (name) return name;
  if (email) return email;
  return note.updatedBy ?? note.createdBy;
}

/** Parse one cataloger note from the REST payload. */
export function mcpEndpointNoteFromPayload(raw: unknown): McpEndpointNote | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const id = typeof obj.id === 'string' ? obj.id : '';
  const endpointId =
    typeof obj.endpointId === 'string'
      ? obj.endpointId
      : typeof obj.endpoint_id === 'string'
        ? obj.endpoint_id
        : '';
  const body = typeof obj.body === 'string' ? obj.body : '';
  const createdBy =
    typeof obj.createdBy === 'string'
      ? obj.createdBy
      : typeof obj.created_by === 'string'
        ? obj.created_by
        : '';
  if (!id || !endpointId || !body.trim() || !createdBy) return null;
  const strOrNull = (value: unknown): string | null =>
    typeof value === 'string' && value.trim() ? value : null;
  return {
    id,
    endpointId,
    body,
    createdBy,
    createdByName: strOrNull(obj.createdByName ?? obj.created_by_name),
    createdByEmail: strOrNull(obj.createdByEmail ?? obj.created_by_email),
    updatedBy: strOrNull(obj.updatedBy ?? obj.updated_by),
    updatedByName: strOrNull(obj.updatedByName ?? obj.updated_by_name),
    updatedByEmail: strOrNull(obj.updatedByEmail ?? obj.updated_by_email),
    createdAt:
      typeof obj.createdAt === 'string'
        ? obj.createdAt
        : typeof obj.created_at === 'string'
          ? obj.created_at
          : '',
    updatedAt:
      typeof obj.updatedAt === 'string'
        ? obj.updatedAt
        : typeof obj.updated_at === 'string'
          ? obj.updated_at
          : '',
  };
}

/** Parse a list response envelope. */
export function mcpEndpointNotesFromPayload(raw: unknown): McpEndpointNote[] {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
  const notes = (raw as { notes?: unknown }).notes;
  if (!Array.isArray(notes)) return [];
  return notes
    .map((item) => mcpEndpointNoteFromPayload(item))
    .filter((item): item is McpEndpointNote => item !== null);
}

/** Whether a note was edited after creation (updated_by set and timestamps differ). */
export function mcpEndpointNoteWasEdited(note: McpEndpointNote): boolean {
  return Boolean(note.updatedBy && note.updatedAt && note.updatedAt !== note.createdAt);
}
