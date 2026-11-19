'use client';

/**
 * The review page's Suggestions tab — COL-4.2 (#4526).
 *
 * Reviewers **suggest a change**: pick a class or property of the version under review, pick a
 * field, type its new value. The author (the review's requester, or a project editor) sees each
 * suggestion as a diff of the element and **applies** or **rejects** it in one click. apiome-rest
 * merges an applied suggestion onto the element as it is now; when the element changed since in a
 * way that overlaps it, the suggestion is shown **Stale** with what changed, and Apply is off.
 */

import * as React from 'react';
import { Lightbulb } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { CONTROL_FIELD_CLASS, Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Textarea } from '@/app/components/ui/Textarea';
import { JsonDiffViewer } from '@/app/components/ui/code/JsonDiffViewer';
import {
  SUGGESTABLE_FIELDS,
  buildFieldPatch,
  currentFieldValue,
  fieldInputText,
  prettyJson,
  suggestionActions,
  suggestionOutcome,
  suggestionStatusLabel,
  type ReviewSuggestion,
  type SuggestionTarget,
  type SuggestionsPayload,
} from '@lib/review-suggestions';

/** Props of {@link ReviewSuggestionsPanel}. */
export interface ReviewSuggestionsPanelProps {
  /** The review. */
  reviewId: string;
  /** The signed-in user, or null. */
  viewerId: string | null;
  /** Whether the review is open on a draft version (suggestions can be made and decided). */
  writable: boolean;
}

type Loaded = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: SuggestionsPayload };

type Envelope = { success?: boolean; error?: string; code?: string; conflictPaths?: string[] } & Partial<SuggestionsPayload>;

async function readEnvelope(response: Response): Promise<Envelope> {
  try {
    return (await response.json()) as Envelope;
  } catch {
    return { success: false, error: `The server answered ${response.status}.` };
  }
}

/**
 * The Suggestions tab.
 *
 * @param props - See {@link ReviewSuggestionsPanelProps}.
 * @returns The panel.
 */
export function ReviewSuggestionsPanel({ reviewId, viewerId, writable }: ReviewSuggestionsPanelProps) {
  const base = `/api/reviews/${encodeURIComponent(reviewId)}/suggestions`;
  const [loaded, setLoaded] = React.useState<Loaded>({ status: 'loading' });
  const [busy, setBusy] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    try {
      const json = await readEnvelope(await fetch(base));
      if (!json.success) {
        setLoaded({ status: 'error', message: json.error ?? 'Could not load the suggestions.' });
        return;
      }
      setLoaded({
        status: 'ready',
        data: { suggestions: json.suggestions ?? [], canDecide: Boolean(json.canDecide), targets: json.targets ?? [] },
      });
    } catch {
      setLoaded({ status: 'error', message: 'Could not load the suggestions.' });
    }
  }, [base]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const decide = async (s: ReviewSuggestion, action: 'apply' | 'reject') => {
    setBusy(s.id);
    setNotice(null);
    try {
      const res = await fetch(`${base}/${encodeURIComponent(s.id)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const json = await readEnvelope(res);
      if (!json.success) setNotice(json.error ?? 'The request failed.');
      else if (action === 'apply') setNotice(`Applied to ${s.target_label}.`);
      await reload();
    } finally {
      setBusy(null);
    }
  };

  if (loaded.status === 'loading') return <LoadingState message="Loading suggestions…" />;
  if (loaded.status === 'error') return <Alert variant="danger">{loaded.message}</Alert>;
  const { suggestions, canDecide, targets } = loaded.data;

  return (
    <div className="sugg" data-testid="review-suggestions">
      {notice ? (
        <Alert variant="info" role="status">
          {notice}
        </Alert>
      ) : null}
      {writable && targets.length > 0 ? <SuggestForm targets={targets} endpoint={base} onCreated={reload} /> : null}
      {suggestions.length === 0 ? (
        <EmptyState
          icon={<Lightbulb aria-hidden="true" />}
          title="No suggestions yet"
          description="Reviewers suggest a change to a class or property; the author applies it."
        />
      ) : (
        <ol className="sugg-list">
          {suggestions.map((s) => {
            const actions = writable ? suggestionActions(s, viewerId, canDecide) : null;
            const outcome = suggestionOutcome(s);
            const stale = s.status === 'stale' || s.stale;
            return (
              <li key={s.id} className="sugg-item" data-testid={`suggestion-${s.id}`}>
                <div className="sugg-item__head">
                  <span className="sugg-item__target">{s.target_label}</span>
                  <Badge variant={stale ? 'warning' : s.status === 'applied' ? 'success' : 'secondary'}>
                    {suggestionStatusLabel(s)}
                  </Badge>
                  <span className="sugg-item__meta">by {s.author_name ?? 'a former member'}</span>
                </div>
                {s.note ? <p className="sugg-item__note">{s.note}</p> : null}
                <JsonDiffViewer original={prettyJson(s.base)} modified={prettyJson(s.proposed)} hideUnchangedRegions />
                {outcome ? (
                  <p className={stale ? 'sugg-item__outcome sugg-item__outcome--stale' : 'sugg-item__outcome'}>{outcome}</p>
                ) : null}
                {actions && (actions.apply || actions.reject) ? (
                  <div className="sugg-item__actions">
                    {actions.apply ? (
                      <Button
                        size="sm"
                        disabled={!actions.applyEnabled || busy === s.id} title={busy === s.id ? 'Saving your decision…' : !actions.applyEnabled ? 'This suggestion cannot be applied to the current revision' : undefined}
                        onClick={() => void decide(s, 'apply')}
                      >
                        Apply
                      </Button>
                    ) : null}
                    {actions.reject ? (
                      <Button size="sm" variant="ghost" disabled={busy === s.id} title={busy === s.id ? 'Saving your decision…' : undefined} onClick={() => void decide(s, 'reject')}>
                        {actions.rejectLabel}
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Props of {@link SuggestForm}. */
interface SuggestFormProps {
  targets: SuggestionTarget[];
  endpoint: string;
  onCreated: () => Promise<void>;
}

/**
 * The **Suggest a change** form: element, field, new value, optional note.
 *
 * @param props - See {@link SuggestFormProps}.
 * @returns The form.
 */
function SuggestForm({ targets, endpoint, onCreated }: SuggestFormProps) {
  const [targetKey, setTargetKey] = React.useState(`${targets[0].type}:${targets[0].id}`);
  const target = targets.find((t) => `${t.type}:${t.id}` === targetKey) ?? targets[0];
  const fields = SUGGESTABLE_FIELDS[target.type];
  const [field, setField] = React.useState<string>(fields[0]);
  const effectiveField = fields.includes(field) ? field : fields[0];
  const [value, setValue] = React.useState(() => fieldInputText(currentFieldValue(target, effectiveField)));
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const pick = (nextTarget: SuggestionTarget, nextField: string) => {
    setValue(fieldInputText(currentFieldValue(nextTarget, nextField)));
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const patch = buildFieldPatch(target, effectiveField, value);
    if (!patch) {
      setError('That is the current value — change it to suggest something.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_type: target.type, target_id: target.id, patch, note }),
      });
      const json = await readEnvelope(res);
      if (!json.success) {
        setError(json.error ?? 'Could not save the suggestion.');
        return;
      }
      setNote('');
      await onCreated();
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="sugg-form" onSubmit={submit} aria-label="Suggest a change">
      <h3 className="sugg-form__title">Suggest a change</h3>
      <div className="sugg-form__row">
        <div className="sugg-form__field">
          <Label htmlFor="sugg-target">Element</Label>
          <select
            id="sugg-target"
            className={CONTROL_FIELD_CLASS}
            value={targetKey}
            onChange={(e) => {
              setTargetKey(e.target.value);
              const next = targets.find((t) => `${t.type}:${t.id}` === e.target.value) ?? targets[0];
              const nextField = SUGGESTABLE_FIELDS[next.type].includes(field) ? field : SUGGESTABLE_FIELDS[next.type][0];
              setField(nextField);
              pick(next, nextField);
            }}
          >
            {targets.map((t) => (
              <option key={`${t.type}:${t.id}`} value={`${t.type}:${t.id}`}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="sugg-form__field">
          <Label htmlFor="sugg-field">Field</Label>
          <select
            id="sugg-field"
            className={CONTROL_FIELD_CLASS}
            value={effectiveField}
            onChange={(e) => {
              setField(e.target.value);
              pick(target, e.target.value);
            }}
          >
            {fields.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
        <div className="sugg-form__field sugg-form__field--grow">
          <Label htmlFor="sugg-value">New value</Label>
          <Input
            id="sugg-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Leave empty to remove the field"
          />
        </div>
      </div>
      <p className="sugg-form__hint">
        Numbers, true/false, lists such as [&quot;a&quot;, &quot;b&quot;] and objects are read as JSON; anything else as text.
      </p>
      <Label htmlFor="sugg-note">Why (optional)</Label>
      <Textarea id="sugg-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={5000} />
      {error ? <Alert variant="danger">{error}</Alert> : null}
      <div className="sugg-form__actions">
        <Button type="submit" size="sm" disabled={saving} title={saving ? 'Saving the suggestion…' : undefined}>
          Suggest
        </Button>
      </div>
    </form>
  );
}
