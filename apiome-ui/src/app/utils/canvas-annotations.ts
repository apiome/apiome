/**
 * Portable canvas annotations (#2394 DUX-2.1).
 *
 * Sticky notes and callouts authored on the schema canvas are serialized into
 * exported specs so they survive publish/export/import round-trips:
 *
 * - Notes attached to a class are emitted on that class's schema object under
 *   the `x-apiome-note` extension (an array — a class can carry several notes).
 *   Attachment is implicit from the location, which keeps the extension
 *   portable across systems where class IDs differ.
 * - Freeform (unattached) notes are emitted at the document level under the
 *   `x-apiome-canvas` extension.
 *
 * OpenAPI and JSON Schema support vendor extensions, so both carry these
 * losslessly. Formats without an extension mechanism (GraphQL SDL, SQL DDL,
 * protobuf, Avro, Thrift, and the diagram exports) skip annotations; the skip
 * is documented in docs/guide/export-fidelity.md.
 */

/** Document-level extension key carrying freeform canvas notes. */
export const X_APIOME_CANVAS_EXTENSION = 'x-apiome-canvas';

/** Schema-level extension key carrying notes attached to that class. */
export const X_APIOME_NOTE_EXTENSION = 'x-apiome-note';

/** Bump when the serialized note shape changes incompatibly. */
export const CANVAS_ANNOTATIONS_FORMAT_VERSION = 1 as const;

/** Visual style of a canvas annotation. */
export type CanvasNoteKind = 'sticky' | 'callout';

/**
 * One serialized canvas annotation.
 *
 * `attachedTo` is the class (schema) NAME, not a database ID, so the
 * attachment survives import into systems that assign new class IDs.
 */
export interface CanvasNoteAnnotation {
  /** Stable note identifier (regenerated on import when it collides). */
  id: string;
  kind: CanvasNoteKind;
  /** Note body text (plain text). */
  text: string;
  /** Color preset name (e.g. "amber") or a custom `#RRGGBB` hex value. */
  color: string;
  /** Canvas position in flow coordinates. */
  position: { x: number; y: number };
  /** Rendered size in canvas pixels (optional; renderer default when absent). */
  dimensions?: { width: number; height: number };
  /** Class (schema) name this note is attached to; null/absent = freeform. */
  attachedTo?: string | null;
}

/** Document-level `x-apiome-canvas` extension payload. */
export interface CanvasAnnotationsExtension {
  formatVersion: typeof CANVAS_ANNOTATIONS_FORMAT_VERSION;
  notes: CanvasNoteAnnotation[];
}

/**
 * Validates and normalizes one raw note value (from a parsed spec or a stored
 * layout payload). Returns null when the value cannot be a note.
 */
export function sanitizeCanvasNoteAnnotation(raw: unknown): CanvasNoteAnnotation | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;

  const id = typeof o.id === 'string' && o.id.trim() ? o.id.trim() : null;
  if (!id) return null;

  const kind: CanvasNoteKind = o.kind === 'callout' ? 'callout' : 'sticky';
  const text = typeof o.text === 'string' ? o.text : '';
  const color = typeof o.color === 'string' && o.color.trim() ? o.color.trim() : 'amber';

  const pos = o.position as { x?: unknown; y?: unknown } | undefined;
  const x = typeof pos?.x === 'number' && Number.isFinite(pos.x) ? pos.x : 0;
  const y = typeof pos?.y === 'number' && Number.isFinite(pos.y) ? pos.y : 0;

  const dims = o.dimensions as { width?: unknown; height?: unknown } | undefined;
  const width =
    typeof dims?.width === 'number' && Number.isFinite(dims.width) && dims.width > 0
      ? dims.width
      : undefined;
  const height =
    typeof dims?.height === 'number' && Number.isFinite(dims.height) && dims.height > 0
      ? dims.height
      : undefined;

  const attachedTo =
    typeof o.attachedTo === 'string' && o.attachedTo.trim() ? o.attachedTo.trim() : undefined;

  return {
    id,
    kind,
    text,
    color,
    position: { x, y },
    ...(width !== undefined && height !== undefined ? { dimensions: { width, height } } : {}),
    ...(attachedTo ? { attachedTo } : {}),
  };
}

/**
 * Splits notes into the document-level extension payload and per-schema
 * `x-apiome-note` arrays keyed by class name.
 *
 * @param notes - All canvas notes for the exported version.
 * @param schemaNames - Names of schemas present in the export; notes attached
 *   to a class that is not exported fall back to the document-level payload
 *   (with `attachedTo` preserved) so nothing is silently dropped.
 * @returns `documentExtension` (null when no freeform notes) and
 *   `notesBySchema` (empty object when no attached notes).
 */
export function splitCanvasAnnotationsForExport(
  notes: CanvasNoteAnnotation[],
  schemaNames: Set<string>
): {
  documentExtension: CanvasAnnotationsExtension | null;
  notesBySchema: Record<string, CanvasNoteAnnotation[]>;
} {
  const documentNotes: CanvasNoteAnnotation[] = [];
  const notesBySchema: Record<string, CanvasNoteAnnotation[]> = {};

  for (const raw of notes) {
    const note = sanitizeCanvasNoteAnnotation(raw);
    if (!note) continue;
    if (note.attachedTo && schemaNames.has(note.attachedTo)) {
      // Attachment is implicit from the schema location; drop the name.
      const { attachedTo: _attachedTo, ...schemaNote } = note;
      (notesBySchema[note.attachedTo] ??= []).push(schemaNote);
    } else {
      documentNotes.push(note);
    }
  }

  return {
    documentExtension:
      documentNotes.length > 0
        ? { formatVersion: CANVAS_ANNOTATIONS_FORMAT_VERSION, notes: documentNotes }
        : null,
    notesBySchema,
  };
}

/** Returns the schemas record of an OpenAPI or JSON Schema document. */
function getSchemasRecord(doc: Record<string, unknown>): Record<string, unknown> | null {
  const components = doc.components as { schemas?: unknown } | undefined;
  if (components?.schemas && typeof components.schemas === 'object') {
    return components.schemas as Record<string, unknown>;
  }
  if (doc.$defs && typeof doc.$defs === 'object') {
    return doc.$defs as Record<string, unknown>;
  }
  if (doc.definitions && typeof doc.definitions === 'object') {
    return doc.definitions as Record<string, unknown>;
  }
  return null;
}

/**
 * Reads all canvas annotations from a parsed OpenAPI or JSON Schema document:
 * the document-level `x-apiome-canvas` payload plus every schema-level
 * `x-apiome-note` array (attachment restored as the schema name).
 *
 * Tolerant of malformed input — invalid entries are skipped, never thrown on.
 */
export function extractCanvasAnnotationsFromSpec(doc: unknown): CanvasNoteAnnotation[] {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return [];
  const o = doc as Record<string, unknown>;
  const notes: CanvasNoteAnnotation[] = [];

  const canvasExt = o[X_APIOME_CANVAS_EXTENSION] as { notes?: unknown } | undefined;
  if (canvasExt && typeof canvasExt === 'object' && Array.isArray(canvasExt.notes)) {
    for (const raw of canvasExt.notes) {
      const note = sanitizeCanvasNoteAnnotation(raw);
      if (note) notes.push(note);
    }
  }

  const schemas = getSchemasRecord(o);
  if (schemas) {
    for (const [schemaName, schema] of Object.entries(schemas)) {
      if (!schema || typeof schema !== 'object') continue;
      const attachedRaw = (schema as Record<string, unknown>)[X_APIOME_NOTE_EXTENSION];
      if (!Array.isArray(attachedRaw)) continue;
      for (const raw of attachedRaw) {
        const note = sanitizeCanvasNoteAnnotation(raw);
        if (note) notes.push({ ...note, attachedTo: schemaName });
      }
    }
  }

  return notes;
}
