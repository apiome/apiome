'use client';

import * as React from 'react';
import { Loader2, MessageSquarePlus, Pencil, StickyNote, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '../../../ui/Button';
import { Textarea } from '../../../ui/Textarea';
import { dashboardPanelPaddedClass } from '../dashboardScreenClasses';
import {
  mcpEndpointNoteAuthorLabel,
  mcpEndpointNoteWasEdited,
  mcpEndpointNotesFromPayload,
  type McpEndpointNote,
} from './mcpEndpointNotesUi';

export interface McpEndpointNotesPanelProps {
  endpointId: string;
}

function notesUrl(endpointId: string, noteId?: string): string {
  const base = `/api/mcp/endpoints/${encodeURIComponent(endpointId)}/notes`;
  return noteId ? `${base}/${encodeURIComponent(noteId)}` : base;
}

async function fetchNotes(endpointId: string): Promise<McpEndpointNote[]> {
  const res = await fetch(notesUrl(endpointId), { credentials: 'include', cache: 'no-store' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
  }
  return mcpEndpointNotesFromPayload(data);
}

function formatTimestamp(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

/**
 * Cataloger notes on an endpoint — human commentary kept visually distinct from discovered data.
 */
export function McpEndpointNotesPanel({
  endpointId,
}: McpEndpointNotesPanelProps): React.ReactElement {
  const [notes, setNotes] = React.useState<McpEndpointNote[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editDraft, setEditDraft] = React.useState('');

  const reload = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setNotes(await fetchNotes(endpointId));
    } catch (e) {
      setNotes([]);
      setError(e instanceof Error ? e.message : 'Could not load cataloger notes');
    } finally {
      setLoading(false);
    }
  }, [endpointId]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const handleCreate = async () => {
    const body = draft.trim();
    if (!body) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(notesUrl(endpointId), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      setDraft('');
      toast.success('Cataloger note added');
      await reload();
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not save note';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (note: McpEndpointNote) => {
    setEditingId(note.id);
    setEditDraft(note.body);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft('');
  };

  const handleUpdate = async (noteId: string) => {
    const body = editDraft.trim();
    if (!body) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(notesUrl(endpointId, noteId), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      cancelEdit();
      toast.success('Cataloger note updated');
      await reload();
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not update note';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (noteId: string) => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(notesUrl(endpointId, noteId), {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      toast.success('Cataloger note deleted');
      await reload();
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not delete note';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      aria-label="Cataloger commentary"
      className="rounded-lg border border-amber-200 bg-amber-50/80 dark:border-amber-900/60 dark:bg-amber-950/30"
    >
      <div className="border-b border-amber-200/80 px-4 py-3 dark:border-amber-900/50">
        <div className="flex items-start gap-2">
          <StickyNote className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
          <div>
            <h3 className="text-sm font-semibold text-amber-950 dark:text-amber-100">
              Cataloger commentary
            </h3>
            <p className="mt-0.5 text-xs text-amber-800/90 dark:text-amber-200/80">
              Human notes from your team — not reported by the MCP server.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-4">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-amber-900/80 dark:text-amber-100/80">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading notes…
          </div>
        ) : null}

        {error ? (
          <p className="text-sm text-red-600 dark:text-red-400" role="alert">
            {error}
          </p>
        ) : null}

        {!loading && notes.length === 0 ? (
          <p className="text-sm text-amber-900/70 dark:text-amber-100/70">
            No cataloger notes yet. Add context, caveats, or recommendations for your team.
          </p>
        ) : null}

        {notes.map((note) => (
          <article
            key={note.id}
            className={`${dashboardPanelPaddedClass} border border-amber-100 bg-white/90 dark:border-amber-900/40 dark:bg-gray-900/40`}
          >
            {editingId === note.id ? (
              <div className="space-y-3">
                <Textarea
                  value={editDraft}
                  onChange={(e) => setEditDraft(e.target.value)}
                  rows={4}
                  aria-label="Edit cataloger note"
                  className="bg-white dark:bg-gray-900"
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={saving || !editDraft.trim()}
                    onClick={() => void handleUpdate(note.id)}
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                    Save
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={cancelEdit}>
                    <X className="h-4 w-4" aria-hidden />
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <p className="whitespace-pre-wrap text-sm text-gray-800 dark:text-gray-200">
                  {note.body}
                </p>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-amber-100 pt-3 text-xs text-gray-500 dark:border-amber-900/40 dark:text-gray-400">
                  <div>
                    <span className="font-medium text-gray-700 dark:text-gray-300">
                      {mcpEndpointNoteAuthorLabel(note)}
                    </span>
                    <span className="mx-1">·</span>
                    <time dateTime={note.createdAt}>{formatTimestamp(note.createdAt)}</time>
                    {mcpEndpointNoteWasEdited(note) ? (
                      <span className="ml-1 text-gray-400">(edited)</span>
                    ) : null}
                  </div>
                  <div className="flex gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={saving}
                      onClick={() => startEdit(note)}
                      title="Edit note"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                      <span className="sr-only">Edit</span>
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={saving}
                      onClick={() => void handleDelete(note.id)}
                      title="Delete note"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-500" aria-hidden />
                      <span className="sr-only">Delete</span>
                    </Button>
                  </div>
                </div>
              </>
            )}
          </article>
        ))}

        <div className="space-y-2 border-t border-amber-200/80 pt-4 dark:border-amber-900/50">
          <label
            htmlFor={`cataloger-note-draft-${endpointId}`}
            className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-amber-900/80 dark:text-amber-200/80"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" aria-hidden />
            Add a note
          </label>
          <Textarea
            id={`cataloger-note-draft-${endpointId}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder="e.g. Prefer the staging endpoint for QA — production is read-only."
            className="bg-white dark:bg-gray-900"
          />
          <Button
            type="button"
            size="sm"
            disabled={saving || !draft.trim()}
            onClick={() => void handleCreate()}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Save note
          </Button>
        </div>
      </div>
    </section>
  );
}
