'use client';

/**
 * **New overlay** / **Edit overlay** — the overlay manager's editor, COA-2.7 (#7050).
 *
 * Opened from the Versions screen's **Overlays** tab on a draft revision. The overlay is a name, an
 * Overlay version, a title and a list of actions; each action selects values with a JSONPath
 * **Target** and then **Update**s them (a JSON value merged in), **Remove**s them, **Copy**s one
 * other value onto them (Overlay 1.1) or runs a **Reusable** action the overlay declares in
 * `components.actions` (Overlay 1.2). The **JSON** view edits the whole document, for anything the
 * form does not cover.
 *
 * **Preview** renders the revision with the stored chain and this unsaved overlay — in the edited
 * overlay's place, or after the chain for a new one — and shows how many nodes each action's target
 * matched and every value it changes, before and after. Nothing is stored until **Save overlay**.
 */

import * as React from 'react';
import { ArrowDown, ArrowUp, Eye, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Textarea } from '@/app/components/ui/Textarea';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';

import {
  ACTION_KIND_LABEL,
  OVERLAY_REVISIONS,
  blankAction,
  documentToDraft,
  draftToDocument,
  newOverlayDraft,
  outcomesFor,
  parseDraftJson,
  reusableActionNames,
  type OverlayActionDraft,
  type OverlayActionKind,
  type OverlayDraft,
  type OverlayDraftProblem,
} from './overlayDraftModel';
import { MatchBadge, OverlayDiffTable } from './OverlayPreviewTables';
import {
  addVersionOverlay,
  previewVersionOverlayDraft,
  replaceVersionOverlay,
  type StoredVersionOverlay,
  type VersionOverlayPreview,
} from './versionOverlaysApi';

/** Props for {@link OverlayEditorDialog}. */
export interface OverlayEditorDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per open so it starts over. */
  open: boolean;
  /** Called with the open state. */
  onOpenChange: (open: boolean) => void;
  /** The revision's project. */
  projectId: string;
  /** The draft revision whose chain the overlay belongs to. */
  revisionId: string;
  /** The stored overlay to edit; omitted for a new overlay. */
  overlay?: StoredVersionOverlay | null;
  /** Called after the overlay was saved. */
  onSaved?: (overlay: StoredVersionOverlay) => void;
}

/** The kinds a row can switch between, in menu order. */
const KINDS: OverlayActionKind[] = ['update', 'remove', 'copy', 'ref'];

/**
 * The first problem for a field, if any.
 *
 * @param problems Every problem.
 * @param index The action (or -1).
 * @param field The field.
 */
function problemFor(
  problems: readonly OverlayDraftProblem[],
  index: number,
  field: OverlayDraftProblem['field']
): string | undefined {
  return problems.find((p) => p.index === index && p.field === field)?.message;
}

/**
 * Render the editor. See {@link OverlayEditorDialogProps}.
 *
 * @returns The dialog.
 */
export function OverlayEditorDialog({
  open,
  onOpenChange,
  projectId,
  revisionId,
  overlay,
  onSaved,
}: OverlayEditorDialogProps) {
  const [draft, setDraft] = React.useState<OverlayDraft>(() =>
    overlay ? documentToDraft(overlay.name, overlay.document) : newOverlayDraft()
  );
  const [mode, setMode] = React.useState<'form' | 'json'>('form');
  const [jsonText, setJsonText] = React.useState('');
  const [problems, setProblems] = React.useState<OverlayDraftProblem[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<VersionOverlayPreview | null>(null);
  const [previewedFor, setPreviewedFor] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<'preview' | 'save' | null>(null);
  const returnFocus = useReturnFocus(open);

  const reusable = reusableActionNames(draft);
  const outcomes = outcomesFor(preview, preview?.draft);

  /** Replace one action of the draft. */
  const updateAction = (index: number, patch: Partial<OverlayActionDraft>) =>
    setDraft((current) => ({
      ...current,
      actions: current.actions.map((action, i) => (i === index ? { ...action, ...patch } : action)),
    }));

  /** Move an action one place up (-1) or down (+1). */
  const moveAction = (index: number, step: -1 | 1) =>
    setDraft((current) => {
      const actions = [...current.actions];
      const [moved] = actions.splice(index, 1);
      actions.splice(index + step, 0, moved);
      return { ...current, actions };
    });

  /**
   * The document the dialog currently describes — from the form or from the JSON view.
   *
   * @returns The document and its name, or null after recording why it cannot be built.
   */
  const currentDocument = (): {
    name: string;
    document: Record<string, unknown>;
  } | null => {
    let source = draft;
    if (mode === 'json') {
      const parsed = parseDraftJson(draft.name, jsonText);
      if (!parsed.ok) {
        setError(parsed.error);
        return null;
      }
      source = { ...parsed.draft, name: draft.name };
    }
    const built = draftToDocument(source);
    if (!built.ok) {
      setProblems(built.problems);
      setError(mode === 'json' ? built.problems.map((p) => p.message).join(' ') : 'Fix the fields marked below.');
      return null;
    }
    setProblems([]);
    setError(null);
    return { name: source.name.trim(), document: built.document };
  };

  const switchMode = (next: 'form' | 'json') => {
    if (next === mode) return;
    if (next === 'json') {
      const built = draftToDocument({
        ...draft,
        name: draft.name || 'overlay',
      });
      if (!built.ok) {
        setProblems(built.problems);
        setError('Fix the fields marked below before switching to JSON.');
        return;
      }
      setJsonText(JSON.stringify(built.document, null, 2));
      setError(null);
      setMode('json');
      return;
    }
    const parsed = parseDraftJson(draft.name, jsonText);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setDraft({ ...parsed.draft, name: draft.name });
    setError(null);
    setMode('form');
  };

  const handlePreview = async () => {
    const current = currentDocument();
    if (!current) return;
    setBusy('preview');
    try {
      const next = await previewVersionOverlayDraft(
        projectId,
        revisionId,
        { name: current.name || 'draft', document: current.document },
        overlay?.id
      );
      setPreview(next);
      setPreviewedFor(JSON.stringify(current));
    } catch (caught) {
      setPreview(null);
      setError(caught instanceof Error ? caught.message : 'The preview could not be rendered.');
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    const current = currentDocument();
    if (!current) return;
    setBusy('save');
    try {
      const body = {
        name: current.name,
        source: overlay?.source ?? 'manual',
        document: current.document,
      } as const;
      const saved = overlay
        ? await replaceVersionOverlay(projectId, revisionId, overlay.id, body)
        : await addVersionOverlay(projectId, revisionId, body);
      onSaved?.(saved);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The overlay could not be saved.');
    } finally {
      setBusy(null);
    }
  };

  /**
   * A comparable snapshot of what the dialog describes now, without recording problems.
   *
   * @returns `{name, document}` as JSON, or null when the form or the JSON is not valid.
   */
  const snapshot = (): string | null => {
    const parsed = mode === 'json' ? parseDraftJson(draft.name, jsonText) : ({ ok: true, draft } as const);
    if (!parsed.ok) return null;
    const built = draftToDocument({ ...parsed.draft, name: draft.name });
    return built.ok ? JSON.stringify({ name: draft.name.trim(), document: built.document }) : null;
  };
  const stale = preview !== null && snapshot() !== previewedFor;

  const draftFindings = preview?.report?.findings.filter((f) => f.overlay === preview.draft) ?? [];

  return (
    <Dialog open={open} onOpenChange={(next) => (busy ? undefined : onOpenChange(next))}>
      <DialogContent size="xl" onCloseAutoFocus={returnFocus} data-testid="overlay-editor">
        <DialogHeader>
          <DialogTitle>{overlay ? `Edit overlay — ${overlay.name}` : 'New overlay'}</DialogTitle>
          <DialogDescription>
            Each action selects values with a JSONPath target and updates, removes or copies them. Preview shows how
            many values each target matches and every change, before you save.
          </DialogDescription>
        </DialogHeader>

        <div className="vovl-editor">
          <div className="vovl-editor__meta">
            <FormField label="Name" htmlFor="overlay-editor-name" error={problemFor(problems, -1, 'name')} required>
              <Input
                id="overlay-editor-name"
                value={draft.name}
                placeholder="partner-edition"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                data-testid="overlay-editor-name"
              />
            </FormField>
            {mode === 'form' ? (
              <>
                <FormField
                  label="Title"
                  htmlFor="overlay-editor-title"
                  error={problemFor(problems, -1, 'title')}
                  required
                >
                  <Input
                    id="overlay-editor-title"
                    value={draft.title}
                    placeholder="Partner edition"
                    onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                    data-testid="overlay-editor-title"
                  />
                </FormField>
                <FormField
                  label="Overlay version"
                  htmlFor="overlay-editor-version"
                  error={problemFor(problems, -1, 'version')}
                >
                  <select
                    id="overlay-editor-version"
                    className="hive-control vovl-select"
                    value={draft.version}
                    onChange={(event) => setDraft({ ...draft, version: event.target.value })}
                    data-testid="overlay-editor-version"
                  >
                    {(OVERLAY_REVISIONS as readonly string[]).includes(draft.version) ? null : (
                      <option value={draft.version}>{draft.version}</option>
                    )}
                    {OVERLAY_REVISIONS.map((revision) => (
                      <option key={revision} value={revision}>
                        {revision}
                      </option>
                    ))}
                  </select>
                </FormField>
              </>
            ) : null}
          </div>

          <div className="vovl-editor__mode">
            <span className="vovl-editor__mode-label" id="overlay-editor-mode-label">
              Edit as
            </span>
            <Segmented
              value={mode}
              onValueChange={(value) => switchMode(value as 'form' | 'json')}
              aria-labelledby="overlay-editor-mode-label"
              size="sm"
              data-testid="overlay-editor-mode"
            >
              <SegmentedItem value="form">Actions</SegmentedItem>
              <SegmentedItem value="json">JSON</SegmentedItem>
            </Segmented>
          </div>

          {mode === 'json' ? (
            <FormField
              label="Overlay document"
              htmlFor="overlay-editor-json"
              helperText="The whole Overlay document as JSON, including components and extends."
            >
              <Textarea
                id="overlay-editor-json"
                className="vovl-editor__json xstd-mono"
                rows={18}
                value={jsonText}
                onChange={(event) => setJsonText(event.target.value)}
                data-testid="overlay-editor-json"
              />
            </FormField>
          ) : (
            <ol className="vovl-editor__actions" aria-label="Actions, in the order they apply">
              {draft.actions.map((action, index) => {
                const outcome = outcomes.get(index);
                const id = `overlay-action-${index}`;
                return (
                  <li key={action.key} className="vovl-action" data-testid={`overlay-editor-action-${index}`}>
                    <div className="vovl-action__head">
                      <span className="xstd-overlay__order" aria-hidden>
                        {index + 1}
                      </span>
                      <label className="sr-only" htmlFor={`${id}-kind`}>
                        Action {index + 1} kind
                      </label>
                      <select
                        id={`${id}-kind`}
                        className="hive-control vovl-select"
                        value={action.kind}
                        onChange={(event) =>
                          updateAction(index, {
                            kind: event.target.value as OverlayActionKind,
                          })
                        }
                        data-testid={`overlay-editor-kind-${index}`}
                      >
                        {KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {ACTION_KIND_LABEL[kind]}
                          </option>
                        ))}
                      </select>
                      <span className="vovl-action__grow">
                        {outcome && !stale ? <MatchBadge outcome={outcome} /> : null}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Move action ${index + 1} up`}
                        title={index === 0 ? 'Already first' : `Move action ${index + 1} up`}
                        disabled={index === 0}
                        onClick={() => moveAction(index, -1)}
                      >
                        <ArrowUp aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Move action ${index + 1} down`}
                        title={index === draft.actions.length - 1 ? 'Already last' : `Move action ${index + 1} down`}
                        disabled={index === draft.actions.length - 1}
                        onClick={() => moveAction(index, 1)}
                      >
                        <ArrowDown aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete action ${index + 1}`}
                        title={`Delete action ${index + 1}`}
                        onClick={() =>
                          setDraft({
                            ...draft,
                            actions: draft.actions.filter((_, i) => i !== index),
                          })
                        }
                        data-testid={`overlay-editor-delete-${index}`}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>

                    <FormField label="Target" htmlFor={`${id}-target`} error={problemFor(problems, index, 'target')}>
                      <Input
                        id={`${id}-target`}
                        className="xstd-mono"
                        value={action.target}
                        placeholder="$.paths['/pets'].get"
                        onChange={(event) => updateAction(index, { target: event.target.value })}
                        data-testid={`overlay-editor-target-${index}`}
                      />
                    </FormField>

                    {action.kind === 'update' ? (
                      <FormField
                        label="Value (JSON)"
                        htmlFor={`${id}-update`}
                        helperText="Merged into each match: objects merge, anything else replaces."
                        error={problemFor(problems, index, 'update')}
                      >
                        <Textarea
                          id={`${id}-update`}
                          className="xstd-mono"
                          rows={3}
                          value={action.update}
                          onChange={(event) => updateAction(index, { update: event.target.value })}
                          data-testid={`overlay-editor-update-${index}`}
                        />
                      </FormField>
                    ) : null}

                    {action.kind === 'copy' ? (
                      <FormField
                        label="Copy from"
                        htmlFor={`${id}-copy`}
                        helperText="The JSONPath of exactly one value; it is merged into each match."
                        error={problemFor(problems, index, 'copy')}
                      >
                        <Input
                          id={`${id}-copy`}
                          className="xstd-mono"
                          value={action.copy}
                          placeholder="$.components.schemas.Pet.description"
                          onChange={(event) => updateAction(index, { copy: event.target.value })}
                          data-testid={`overlay-editor-copy-${index}`}
                        />
                      </FormField>
                    ) : null}

                    {action.kind === 'ref' ? (
                      <FormField
                        label="Reusable action"
                        htmlFor={`${id}-ref`}
                        helperText={
                          reusable.length === 0
                            ? 'Declare reusable actions under components.actions in the JSON view.'
                            : 'One of the actions this overlay declares under components.actions.'
                        }
                        error={problemFor(problems, index, 'ref')}
                      >
                        <select
                          id={`${id}-ref`}
                          className="hive-control vovl-select"
                          value={action.ref}
                          onChange={(event) => updateAction(index, { ref: event.target.value })}
                          data-testid={`overlay-editor-ref-${index}`}
                        >
                          <option value="">Choose…</option>
                          {action.ref && !reusable.includes(action.ref) ? (
                            <option value={action.ref}>{action.ref}</option>
                          ) : null}
                          {reusable.map((name) => (
                            <option key={name} value={name}>
                              {name}
                            </option>
                          ))}
                        </select>
                      </FormField>
                    ) : null}

                    {action.kind === 'remove' ? (
                      <p className="hive-quiet">Every value the target matches is removed.</p>
                    ) : null}

                    <FormField label="Description" htmlFor={`${id}-description`}>
                      <Input
                        id={`${id}-description`}
                        value={action.description}
                        placeholder="Optional: why this action exists"
                        onChange={(event) =>
                          updateAction(index, {
                            description: event.target.value,
                          })
                        }
                      />
                    </FormField>
                  </li>
                );
              })}
            </ol>
          )}

          {mode === 'form' ? (
            <div className="vovl-actions">
              <Button
                variant="outline"
                onClick={() =>
                  setDraft({
                    ...draft,
                    actions: [...draft.actions, blankAction('update')],
                  })
                }
                data-testid="overlay-editor-add-action"
              >
                <Plus className="h-4 w-4" aria-hidden />
                Add action
              </Button>
              {problemFor(problems, -1, 'actions') ? (
                <span className="vovl-error">{problemFor(problems, -1, 'actions')}</span>
              ) : null}
            </div>
          ) : null}

          {error ? (
            <p className="xstd-notice" data-tone="warn" role="alert" data-testid="overlay-editor-error">
              {error}
            </p>
          ) : null}

          {preview ? (
            <section className="xstd-stack" aria-label="Preview" data-testid="overlay-editor-preview">
              <div className="xstd-caps">
                <Eye aria-hidden />
                Preview
              </div>
              {stale ? (
                <p className="hive-quiet" data-testid="overlay-editor-preview-stale">
                  Edited since this preview — preview again to see the current changes.
                </p>
              ) : null}
              {draftFindings.length > 0 ? (
                <ul className="xstd-overlay__list" data-testid="overlay-editor-findings">
                  {draftFindings.map((finding) => (
                    <li
                      key={`${finding.action_index}-${finding.rule}-${finding.message}`}
                      className="xstd-notice"
                      data-tone={finding.severity === 'error' ? 'danger' : 'warn'}
                    >
                      {finding.action_index >= 0 ? `Action ${finding.action_index + 1}: ` : ''}
                      {finding.message}
                    </li>
                  ))}
                </ul>
              ) : null}
              <OverlayDiffTable rows={preview.diff ?? []} />
            </section>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={busy !== null}
            title={busy ? 'Wait for the request to finish' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="outline"
            disabled={busy !== null}
            title={busy ? 'Wait for the request to finish' : undefined}
            onClick={() => void handlePreview()}
            data-testid="overlay-editor-preview-button"
          >
            <Eye className="h-4 w-4" aria-hidden />
            {busy === 'preview' ? 'Previewing…' : 'Preview'}
          </Button>
          <Button
            variant="primary"
            disabled={busy !== null}
            title={busy ? 'Wait for the request to finish' : undefined}
            onClick={() => void handleSave()}
            data-testid="overlay-editor-save"
          >
            {busy === 'save' ? 'Saving…' : 'Save overlay'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
