'use client';

/**
 * **Settings → Clean-up** — PFX-8.14 (#7311), built to `docs/mockups/contracts/settings.html`.
 *
 * * **What to keep** — the rules as sentences, each with how many versions it keeps now: every
 *   version deployed or released anywhere (always — it has no remove button and no rule set can turn
 *   it off), the latest N of each main branch, the latest N of every other branch (for D days), and
 *   anything with a listed tag. **Add a rule** brings back a removed one. **Run clean-up nightly**,
 *   the restore window, **Save rules** (the tab's one primary) and **Discard**.
 * * **If it ran now** — the form planned by REST exactly as the nightly run plans it, redrawn as the
 *   form changes; **See the list** shows the versions with their pacts and results. While clean-up
 *   is off it says "Nothing is removed while clean-up is off." first.
 * * **Recently deleted** — what was deleted (by hand or by the clean-up), newest first, with
 *   **Restore** until it is purged.
 * * **The same, from anywhere** — the form as `apiome pact retention set` and the REST `PUT`.
 *
 * Without the Contracts admin permission (`pacts:delete`, REST's `can_edit`) every control is
 * read-only and the tab says so once, in a callout.
 */

import * as React from 'react';
import { Plus, RefreshCw, X } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, CommandBlock, LoadingState } from '@/app/components/ui';
import { Switch } from '@/app/components/ui/Switch';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { formatWhen } from '@lib/pact-pacticipants';
import {
  KEEPS_IN_USE,
  MATCH_KEYS,
  OPTIONAL_RULES,
  RESTORE_WINDOW_CHOICES,
  RULE_LABELS,
  deletedDetail,
  deletedTitle,
  formOf,
  plural,
  previewHeadline,
  retentionCommandAction,
  rulesOf,
  sameRules,
  type CleanupForm,
  type DeletedItem,
  type DeletedPage,
  type OptionalRule,
  type RetentionPolicy,
  type RetentionPreview,
  type RetentionRules,
} from '@lib/pact-retention';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { restorePacticipant, restoreVersion } from '../pactPacticipants/pacticipantsApi';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { fetchDeleted, fetchPolicy, previewPolicy, savePolicy } from './retentionApi';

/** How long the preview waits after the last keystroke before asking REST. */
export const PREVIEW_DELAY_MS = 400;

/** The on-switch of each optional rule in the form. */
const RULE_SWITCH: Record<OptionalRule, 'mainOn' | 'otherOn' | 'tagsOn'> = {
  main: 'mainOn',
  other: 'otherOn',
  tags: 'tagsOn',
};

/** A section's read. */
type Read<T> = { data: T | null; error: string | null };

/**
 * How many versions a rule keeps now, from the preview.
 *
 * @param preview - The latest preview, or `null` while it loads.
 * @param key - The `matched_by` key.
 * @returns E.g. `55 versions`, or `''` before the first preview.
 */
function keptCount(preview: RetentionPreview | null, key: string): string {
  if (!preview) return '';
  return plural(preview.plan.matched_by[key] ?? 0, 'version');
}

/**
 * A number input inside a rule's sentence.
 *
 * @param props - Its label, value and what changing it does.
 * @returns The input.
 */
function InlineNumber({
  id,
  label,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  placeholder?: string;
}) {
  return (
    <input
      id={id}
      className="pmx-input pcx-inline-number"
      inputMode="numeric"
      aria-label={label}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
    />
  );
}

/**
 * One rule row: the sentence, how much it keeps, and its remove button (none for the rule that is
 * always on).
 *
 * @param props - The sentence, the count, and what removing it does.
 * @returns The row.
 */
function RuleRow({
  id,
  count,
  always,
  onRemove,
  removeLabel,
  disabled,
  children,
}: {
  id: string;
  count: string;
  always?: boolean;
  onRemove?: () => void;
  removeLabel?: string;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="pcx-rule" data-testid={`pcx-rule-${id}`}>
      <span className="pcx-rule__sentence">{children}</span>
      <span className="pcx-rule__aside">
        <span className="pcx-rule__count">{always ? (count ? `always · ${count}` : 'always') : count}</span>
        {onRemove ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onRemove}
            aria-label={removeLabel}
            disabled={disabled}
            data-testid={`pcx-remove-${id}`}
          >
            <X aria-hidden />
          </Button>
        ) : null}
      </span>
    </div>
  );
}

/**
 * **If it ran now**: the headline, and the list behind **See the list**.
 *
 * @param props - The latest preview (or its error) and how to ask again.
 * @returns The card.
 */
function PreviewCard({
  preview,
  error,
  loading,
  onRefresh,
}: {
  preview: RetentionPreview | null;
  error: string | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const headline = preview ? previewHeadline(preview) : null;
  return (
    <section className="ppx__panel pcx-preview" aria-labelledby="pcx-preview-title" data-testid="pcx-preview">
      <div className="ppx__panel-head">
        <h2 id="pcx-preview-title" className="pcx-caps">
          If it ran now
        </h2>
        <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading} data-testid="pcx-preview-refresh">
          <RefreshCw aria-hidden />
          Preview
        </Button>
      </div>
      {error ? (
        <p className="ppx__error" role="alert" data-testid="pcx-preview-error">
          {error}
        </p>
      ) : !preview || !headline ? (
        <LoadingState message="Planning the clean-up…" minHeightClassName="min-h-[4rem]" />
      ) : (
        <div className="pcx-preview__body" aria-live="polite" aria-busy={loading}>
          {!preview.nightly_enabled ? (
            <p className="pcx-preview__off" data-testid="pcx-preview-off">
              Nothing is removed while clean-up is off.
            </p>
          ) : null}
          <div className="pcx-preview__headline">
            <span className="pcx-preview__count" data-testid="pcx-preview-count">
              {preview.plan.deleted.toLocaleString('en-US')}
            </span>
            <div>
              <div className="pcx-preview__title">
                {preview.nightly_enabled ? headline.title : `Turned on, ${headline.title}`}
              </div>
              <div className="ppx__muted">{headline.detail}</div>
            </div>
          </div>
          {preview.draft ? <p className="ppx__muted">Previewing rules that are not saved yet.</p> : null}
          {preview.plan.deleted > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              aria-controls="pcx-preview-list"
              data-testid="pcx-preview-toggle"
            >
              {open ? 'Hide the list' : 'See the list'}
            </Button>
          ) : null}
          {open ? <PreviewList preview={preview} /> : null}
        </div>
      )}
    </section>
  );
}

/**
 * The versions a preview removes, per pacticipant.
 *
 * @param props - The preview.
 * @returns The table.
 */
function PreviewList({ preview }: { preview: RetentionPreview }) {
  return (
    <div className="ppx__table-wrap" id="pcx-preview-list">
      <table className="ppx__table" data-testid="pcx-preview-table">
        <caption className="sr-only">Versions the clean-up would remove</caption>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">With it</th>
          </tr>
        </thead>
        <tbody>
          {preview.plan.pacticipants
            .filter((row) => row.deleted > 0)
            .flatMap((row) => [
              ...row.deletions.map((deletion) => (
                <tr key={`${row.slug}:${deletion.number}`}>
                  <td>
                    <span className="pcx-table__primary">{row.name}</span>{' '}
                    <span className="pcx-mono">{deletion.number}</span>
                    {deletion.branches.length > 0 ? (
                      <div className="ppx__muted">{deletion.branches.join(', ')}</div>
                    ) : null}
                  </td>
                  <td className="ppx__muted">
                    {plural(deletion.pacts, 'pact')} · {plural(deletion.results, 'result')}
                  </td>
                </tr>
              )),
              ...(row.deleted > row.deletions.length
                ? [
                    <tr key={`${row.slug}:more`}>
                      <td colSpan={2} className="ppx__muted">
                        {row.name}: and {plural(row.deleted - row.deletions.length, 'more version')}
                      </td>
                    </tr>,
                  ]
                : []),
            ])}
        </tbody>
      </table>
    </div>
  );
}

/**
 * **Recently deleted**, with **Restore**.
 *
 * @param props - The list's read, whether restoring is allowed, and what restoring and paging do.
 * @returns The section.
 */
function RecentlyDeleted({
  page,
  error,
  onRetry,
  onRestore,
  onMore,
  restoring,
  restoreError,
}: {
  page: DeletedPage | null;
  error: string | null;
  onRetry: () => void;
  onRestore: (item: DeletedItem) => void;
  onMore: () => void;
  restoring: string | null;
  restoreError: string | null;
}) {
  return (
    <Panel
      id="pcx-deleted"
      title="Recently deleted"
      aside={
        page ? (
          <span className="ppx__muted">Gone for good after {plural(page.restore_window_days, 'day')}</span>
        ) : undefined
      }
    >
      {error ? (
        <SectionError title="What was deleted could not be read" error={error} onRetry={onRetry} />
      ) : page === null ? (
        <LoadingState message="Reading what was deleted…" minHeightClassName="min-h-[4rem]" />
      ) : page.items.length === 0 ? (
        <p className="ppx__statement" data-testid="pcx-deleted-empty">
          Nothing is waiting to be purged: nothing was deleted in the last {plural(page.restore_window_days, 'day')}.
        </p>
      ) : (
        <>
          <div className="ppx__table-wrap">
            <table className="ppx__table" data-testid="pcx-deleted-table">
              <caption className="sr-only">Recently deleted pacticipants and versions</caption>
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Deleted</th>
                  <th scope="col">By</th>
                  {page.can_restore ? (
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={`${item.kind}:${item.id}`} data-testid={`pcx-deleted-${item.id}`}>
                    <td>
                      <span className="pcx-table__primary">{deletedTitle(item)}</span>{' '}
                      {item.kind === 'pacticipant' ? <Badge variant="outline">pacticipant</Badge> : null}
                      <div className="ppx__muted">{deletedDetail(item)}</div>
                    </td>
                    <td className="ppx__muted">
                      {formatWhen(item.deleted_at)}
                      <div>Purged {formatWhen(item.purge_after)}</div>
                    </td>
                    <td>{item.deleted_by ?? '—'}</td>
                    {page.can_restore ? (
                      <td className="pcx-table__actions">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onRestore(item)}
                          disabled={restoring !== null}
                          aria-label={`Restore ${deletedTitle(item)}`}
                          data-testid={`pcx-restore-${item.id}`}
                        >
                          {restoring === item.id ? 'Restoring…' : 'Restore'}
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {restoreError ? (
            <p className="ppx__error" role="alert" data-testid="pcx-restore-error">
              {restoreError}
            </p>
          ) : null}
          {page.has_more ? (
            <Button variant="outline" size="sm" onClick={onMore} data-testid="pcx-deleted-more">
              Show older
            </Button>
          ) : null}
        </>
      )}
    </Panel>
  );
}

/**
 * The rules form.
 *
 * @param props - The saved policy, the form and what changing / saving it does.
 * @returns The card.
 */
function RulesCard({
  policy,
  form,
  setForm,
  preview,
  onSave,
  onDiscard,
  saving,
  message,
}: {
  policy: RetentionPolicy;
  form: CleanupForm;
  setForm: (update: (current: CleanupForm) => CleanupForm) => void;
  preview: RetentionPreview | null;
  onSave: () => void;
  onDiscard: () => void;
  saving: boolean;
  message: { tone: 'ok' | 'error'; text: string } | null;
}) {
  const readOnly = !policy.can_edit;
  const disabled = readOnly || saving;
  const [adding, setAdding] = React.useState(false);
  const set = <K extends keyof CleanupForm>(key: K, value: CleanupForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const off = OPTIONAL_RULES.filter((rule) => !form[RULE_SWITCH[rule]]);
  const checked = rulesOf(form);
  const unchanged = 'rules' in checked && sameRules(checked.rules, policy);
  const windows = Array.from(new Set<number>([...RESTORE_WINDOW_CHOICES, policy.restore_window_days])).sort((a, b) => a - b);
  const nightlyHint = form.nightly
    ? policy.next_run_at && policy.nightly_enabled
      ? `Next run ${formatWhen(policy.next_run_at)} (after 02:00 UTC).`
      : 'Runs every night after 02:00 UTC once saved.'
    : 'Off: nothing is ever removed.';

  return (
    <section className="ppx__panel pcx-rules" aria-labelledby="pcx-rules-title" data-testid="pcx-rules">
      <div className="ppx__panel-head">
        <h2 id="pcx-rules-title" className="ppx__title">
          What to keep
        </h2>
        <span className="ppx__muted">Everything else is removed nightly</span>
      </div>
      <div className="pcx-rules__list">
        <RuleRow id="deployed" count={keptCount(preview, MATCH_KEYS.deployed)} always disabled={disabled}>
          Every version <b>deployed or released</b> anywhere
        </RuleRow>
        {form.mainOn ? (
          <RuleRow
            id="main"
            count={keptCount(preview, MATCH_KEYS.main)}
            onRemove={() => set('mainOn', false)}
            removeLabel="Remove the main-branch rule"
            disabled={disabled}
          >
            The latest{' '}
            <InlineNumber
              id="pcx-main-latest"
              label="Versions kept on each main branch"
              value={form.mainLatest}
              onChange={(value) => set('mainLatest', value)}
              disabled={disabled}
            />{' '}
            versions on each pacticipant’s <b>main branch</b>
          </RuleRow>
        ) : null}
        {form.otherOn ? (
          <RuleRow
            id="other"
            count={keptCount(preview, MATCH_KEYS.other)}
            onRemove={() => set('otherOn', false)}
            removeLabel="Remove the other-branch rule"
            disabled={disabled}
          >
            The latest{' '}
            <InlineNumber
              id="pcx-other-latest"
              label="Versions kept on every other branch"
              value={form.otherLatest}
              onChange={(value) => set('otherLatest', value)}
              disabled={disabled}
            />{' '}
            on <b>every other branch</b>, for{' '}
            <InlineNumber
              id="pcx-other-days"
              label="Days the other-branch versions are kept (empty: however old)"
              value={form.otherDays}
              placeholder="any"
              onChange={(value) => set('otherDays', value)}
              disabled={disabled}
            />{' '}
            days
          </RuleRow>
        ) : null}
        {form.tagsOn ? (
          <RuleRow
            id="tags"
            count={keptCount(preview, MATCH_KEYS.tags)}
            onRemove={() => set('tagsOn', false)}
            removeLabel="Remove the tag rule"
            disabled={disabled}
          >
            Anything tagged{' '}
            <input
              id="pcx-tags"
              className="pmx-input pcx-inline-text"
              aria-label="Tags to keep, separated by commas"
              value={form.tags}
              placeholder="keep, prod"
              onChange={(event) => set('tags', event.target.value)}
              disabled={disabled}
            />
          </RuleRow>
        ) : null}
        {!readOnly ? (
          <div className="pcx-rules__add">
            {adding && off.length > 0 ? (
              <div className="pcx-rules__choices" role="group" aria-label="Add a rule">
                {off.map((rule) => (
                  <Button
                    key={rule}
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      set(RULE_SWITCH[rule], true);
                      setAdding(false);
                    }}
                    disabled={disabled}
                    data-testid={`pcx-add-${rule}`}
                  >
                    {RULE_LABELS[rule]}
                  </Button>
                ))}
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAdding(true)}
                disabled={disabled || off.length === 0}
                data-testid="pcx-add-rule"
              >
                <Plus aria-hidden />
                Add a rule
              </Button>
            )}
            <span className="ppx__muted">By branch, tag, count or age. A version kept by any rule stays.</span>
          </div>
        ) : null}
      </div>
      <div className="pcx-switch-row">
        <div>
          <div className="pcx-switch-row__title" id="pcx-nightly-label">
            Run clean-up nightly
          </div>
          <div className="ppx__muted" id="pcx-nightly-hint">
            {nightlyHint}
          </div>
        </div>
        <Switch
          checked={form.nightly}
          onCheckedChange={(value) => set('nightly', value)}
          disabled={disabled}
          aria-labelledby="pcx-nightly-label"
          aria-describedby="pcx-nightly-hint"
          data-testid="pcx-nightly"
        />
      </div>
      <div className="pmx-field pcx-window">
        <label className="ppx__field-label" htmlFor="pcx-restore-window">
          Keep deleted items restorable for
        </label>
        <select
          id="pcx-restore-window"
          className="pmx-input"
          value={form.restoreDays}
          onChange={(event) => set('restoreDays', event.target.value)}
          disabled={disabled}
        >
          {windows.map((days) => (
            <option key={days} value={String(days)}>
              {plural(days, 'day')}
            </option>
          ))}
        </select>
      </div>
      {'error' in checked && !readOnly ? (
        <p className="ppx__error" role="alert" data-testid="pcx-form-error">
          {checked.error}
        </p>
      ) : null}
      {message ? (
        <p
          className={message.tone === 'ok' ? 'ppx__muted' : 'ppx__error'}
          role={message.tone === 'ok' ? 'status' : 'alert'}
          data-testid="pcx-save-message"
        >
          {message.text}
        </p>
      ) : null}
      {!readOnly ? (
        <div className="ppx__actions">
          <Button onClick={onSave} disabled={saving || unchanged || 'error' in checked} data-testid="pcx-save">
            {saving ? 'Saving…' : 'Save rules'}
          </Button>
          <Button variant="outline" onClick={onDiscard} disabled={saving || unchanged} data-testid="pcx-discard">
            Discard
          </Button>
        </div>
      ) : null}
      {policy.last_run ? (
        <p className="ppx__muted" data-testid="pcx-last-run">
          {policy.last_run.error
            ? `The last run (${formatWhen(policy.last_run.at)}) removed nothing: ${policy.last_run.error}`
            : `The last run (${formatWhen(policy.last_run.at)}) removed ${plural(policy.last_run.deleted ?? 0, 'version')}.`}
        </p>
      ) : null}
    </section>
  );
}

/**
 * The Clean-up tab.
 *
 * @returns The tab's content.
 */
export default function CleanupTab() {
  const [policy, setPolicy] = React.useState<Read<RetentionPolicy>>({ data: null, error: null });
  const [form, setFormState] = React.useState<CleanupForm | null>(null);
  const [preview, setPreview] = React.useState<RetentionPreview | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewing, setPreviewing] = React.useState(false);
  const [deleted, setDeleted] = React.useState<Read<DeletedPage>>({ data: null, error: null });
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [restoring, setRestoring] = React.useState<string | null>(null);
  const [restoreError, setRestoreError] = React.useState<string | null>(null);
  const previewSeq = React.useRef(0);

  const loadPolicy = React.useCallback(async () => {
    setPolicy({ data: null, error: null });
    try {
      const data = await fetchPolicy();
      setPolicy({ data, error: null });
      setFormState(formOf(data));
    } catch (caught) {
      setPolicy({ data: null, error: describeFailure(caught, 'Could not load the clean-up rules') });
    }
  }, []);

  const loadDeleted = React.useCallback(async () => {
    setDeleted({ data: null, error: null });
    try {
      setDeleted({ data: await fetchDeleted(), error: null });
    } catch (caught) {
      setDeleted({ data: null, error: describeFailure(caught, 'Could not load what was deleted') });
    }
  }, []);

  React.useEffect(() => {
    void loadPolicy();
    void loadDeleted();
  }, [loadPolicy, loadDeleted]);

  const setForm = (update: (current: CleanupForm) => CleanupForm) => {
    setFormState((current) => (current ? update(current) : current));
    setMessage(null);
  };

  // The rules the preview plans: the form's when it is valid, else the saved ones.
  const checked = form ? rulesOf(form) : null;
  const draft: RetentionRules | null = checked && 'rules' in checked ? checked.rules : null;
  const saved = policy.data;
  const draftKey = draft ? JSON.stringify(draft) : '';

  const runPreview = React.useCallback(async (rules: RetentionRules | null) => {
    const seq = ++previewSeq.current;
    setPreviewing(true);
    try {
      const answer = await previewPolicy(rules);
      if (seq === previewSeq.current) {
        setPreview(answer);
        setPreviewError(null);
      }
    } catch (caught) {
      if (seq === previewSeq.current) setPreviewError(describeFailure(caught, 'Could not preview the clean-up'));
    } finally {
      if (seq === previewSeq.current) setPreviewing(false);
    }
  }, []);

  React.useEffect(() => {
    if (!saved || !draftKey) return undefined;
    const rules = JSON.parse(draftKey) as RetentionRules;
    const unsaved = !sameRules(rules, saved);
    const timer = setTimeout(() => void runPreview(unsaved ? rules : null), PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [draftKey, saved, runPreview]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const stored = await savePolicy(draft);
      setPolicy({ data: stored, error: null });
      setFormState(formOf(stored));
      setMessage({ tone: 'ok', text: 'Clean-up rules saved.' });
    } catch (caught) {
      const text = describeFailure(caught, 'Could not save the clean-up rules');
      setMessage({ tone: 'error', text: text.includes(KEEPS_IN_USE) ? KEEPS_IN_USE : text });
    } finally {
      setSaving(false);
    }
  };

  const restore = async (item: DeletedItem) => {
    setRestoring(item.id);
    setRestoreError(null);
    const answer =
      item.kind === 'pacticipant'
        ? await restorePacticipant(item.id)
        : await restoreVersion(item.pacticipant_slug, item.number ?? '');
    setRestoring(null);
    if (answer && typeof answer === 'object' && 'error' in answer && typeof answer.error === 'string') {
      setRestoreError(answer.error);
      return;
    }
    void loadDeleted();
    void runPreview(draft && saved && !sameRules(draft, saved) ? draft : null);
  };

  const more = async () => {
    const current = deleted.data;
    if (!current?.next_cursor) return;
    try {
      const next = await fetchDeleted(current.next_cursor);
      setDeleted({ data: { ...next, items: [...current.items, ...next.items] }, error: null });
    } catch (caught) {
      setDeleted({ data: null, error: describeFailure(caught, 'Could not load what was deleted') });
    }
  };

  const commandRules = draft ?? saved;
  const action = commandRules ? retentionCommandAction(commandRules) : null;

  return (
    <div className="pcx" data-testid="pact-settings-cleanup">
      {saved && !saved.can_edit ? (
        <div className="pcx-callout" role="note" data-testid="pcx-read-only">
          You can read these rules. Changing them and restoring deleted items needs the Contracts admin permission
          (pacts:delete).
        </div>
      ) : null}
      <div className="pcx-split">
        <div className="pcx-split__main">
          {policy.error ? (
            <Panel id="pcx-rules-error" title="What to keep">
              <SectionError
                title="The clean-up rules could not be read"
                error={policy.error}
                onRetry={() => void loadPolicy()}
              />
            </Panel>
          ) : saved === null || form === null ? (
            <LoadingState message="Reading the clean-up rules…" minHeightClassName="min-h-[8rem]" />
          ) : (
            <RulesCard
              policy={saved}
              form={form}
              setForm={setForm}
              preview={preview}
              onSave={() => void save()}
              onDiscard={() => {
                setFormState(formOf(saved));
                setMessage(null);
              }}
              saving={saving}
              message={message}
            />
          )}
          <RecentlyDeleted
            page={deleted.data}
            error={deleted.error}
            onRetry={() => void loadDeleted()}
            onRestore={(item) => void restore(item)}
            onMore={() => void more()}
            restoring={restoring}
            restoreError={restoreError}
          />
        </div>
        <aside className="pcx-split__aside" aria-label="Clean-up preview and commands">
          {saved ? (
            <PreviewCard
              preview={preview}
              error={previewError}
              loading={previewing}
              onRefresh={() => void runPreview(draft && !sameRules(draft, saved) ? draft : null)}
            />
          ) : null}
          {action ? (
            <section className="ppx__panel" aria-labelledby="pcx-command-title">
              <h2 id="pcx-command-title" className="pcx-caps">
                The same, from anywhere
              </h2>
              <CommandBlock
                surfaces={pactCommandSurfaces(action)}
                unsupported={unsupportedLines(action)}
                footnote="Replace {tenant} with your workspace’s handle in the REST path. apiome pact retention preview takes the same flags."
                data-testid="pcx-command-block"
              />
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
