'use client';

/**
 * The parts of **Run a verification** (PFX-8.8, #7305): the selector builder, the preview aside
 * (*This run will verify …*), and the three dialogs — **Add a target**, **Save as a schedule** and
 * the run's outcome. Each is driven by the page's state; none fetches.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleAlert, CircleCheck, CircleX, Clock, Plus, X } from 'lucide-react';
import { Badge, Button, Input, Label, Switch } from '@/app/components/ui';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { CADENCES, CADENCE_TEXT, type Cadence } from '@lib/pact-remediation';
import { verificationRoute } from '@lib/pact-verification';
import {
  RULE_KINDS,
  RULE_KIND_LABELS,
  newTargetProblems,
  previewHeadline,
  rule as makeRule,
  ruleSentence,
  ruleValueField,
  runHeadline,
  type NewTargetForm,
  type PreviewPact,
  type RuleKind,
  type SelectorRule,
  type VerifyPreview,
  type VerifyRunAnswer,
} from '@lib/pact-verify-run';
import { RunOutcome } from '../pactVerification/VerificationPanels';

/** How many pacts the aside lists before *+ N more*. */
export const ASIDE_PACTS = 4;

/** The preview, as the aside shows it. */
export type PreviewState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'failed'; error: string }
  | { kind: 'ready'; preview: VerifyPreview };

// --- the selector builder --------------------------------------------------------------------------

/**
 * The rules as sentences, each with its pact count; under Custom, a way to remove each and to add one.
 *
 * @param props - The rules, the counts by position, the provider branch, whether they can be edited.
 * @returns The list and, when editable, the **Add a rule** row.
 */
export function SelectorRules({
  rules,
  counts,
  branch,
  editable,
  problems,
  onChange,
}: {
  rules: SelectorRule[];
  /** Pacts per rule, by position; `null` while unknown. */
  counts: (number | null)[];
  branch: string;
  editable: boolean;
  /** A problem per rule id. */
  problems: Record<string, string>;
  onChange: (rules: SelectorRule[]) => void;
}) {
  const [kind, setKind] = React.useState<RuleKind>('branch');
  const [value, setValue] = React.useState('');
  const [consumer, setConsumer] = React.useState('');
  const field = ruleValueField(kind);
  const add = () => {
    const next = { ...makeRule(kind, value.trim(), `${kind}:${value.trim()}:${Date.now()}`), consumer: consumer.trim() };
    onChange([...rules, next]);
    setValue('');
    setConsumer('');
  };
  return (
    <div className="pvr-rules" data-testid="pvr-rules">
      <ul className="pvr-rules__list">
        {rules.map((r, index) => (
          <li key={r.id} className="pvr-rule" data-testid="pvr-rule">
            <span className="pvr-rule__text">{ruleSentence(r, branch)}</span>
            <span className="pvr-rule__count" data-testid="pvr-rule-count">
              {counts[index] === null || counts[index] === undefined ? '…' : `${counts[index]} ${counts[index] === 1 ? 'pact' : 'pacts'}`}
            </span>
            {editable ? (
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Remove “${ruleSentence(r, branch)}”`}
                onClick={() => onChange(rules.filter((other) => other.id !== r.id))}
              >
                <X aria-hidden />
              </Button>
            ) : null}
            {problems[r.id] ? (
              <p className="ppub-hint ppub-hint--danger pvr-rule__problem" role="alert">
                {problems[r.id]}
              </p>
            ) : null}
          </li>
        ))}
        {rules.length === 0 ? <li className="ppub-hint">No rule: the broker’s default — each consumer’s latest pact.</li> : null}
      </ul>
      {editable ? (
        <div className="pvr-add" data-testid="pvr-add-rule">
          <div className="ppub-field">
            <Label htmlFor="pvr-add-kind">Add a rule</Label>
            <select id="pvr-add-kind" className="ppub-select" value={kind} onChange={(event) => setKind(event.target.value as RuleKind)}>
              {RULE_KINDS.map((option) => (
                <option key={option} value={option}>
                  {RULE_KIND_LABELS[option]}
                </option>
              ))}
            </select>
          </div>
          {field ? (
            <div className="ppub-field">
              <Label htmlFor="pvr-add-value">{field.label}</Label>
              <Input id="pvr-add-value" value={value} maxLength={255} onChange={(event) => setValue(event.target.value)} />
            </div>
          ) : null}
          <div className="ppub-field">
            <Label htmlFor="pvr-add-consumer">Consumer (optional)</Label>
            <Input id="pvr-add-consumer" value={consumer} maxLength={255} onChange={(event) => setConsumer(event.target.value)} />
          </div>
          <Button variant="outline" onClick={add} disabled={Boolean(field?.required && !value.trim())} data-testid="pvr-add-rule-button">
            <Plus aria-hidden />
            Add
          </Button>
        </div>
      ) : null}
      <p className="ppub-hint">By branch, tag, environment, consumer or “latest”. Duplicates are verified once.</p>
    </div>
  );
}

// --- the aside -------------------------------------------------------------------------------------

/** The initials a consumer's avatar shows. */
function initials(name: string): string {
  const words = name.split(/[\s_-]+/).filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words[1][0]}` : name.slice(0, 2)).toUpperCase();
}

/**
 * What one pact's row says under its name.
 *
 * @param pact - The pact.
 * @returns E.g. `6 interactions · last result: failed`.
 */
export function pactSubline(pact: PreviewPact): string {
  const parts = [`${pact.interactions} ${pact.interactions === 1 ? 'interaction' : 'interactions'}`];
  if (pact.already_verified) parts.push('already verified for this version');
  else if (pact.last_result) parts.push(`last result: ${pact.last_result.success ? 'verified' : 'failed'}`);
  else parts.push('never verified');
  if (pact.held_back) parts.push(`${pact.held_back} held back`);
  return parts.join(' · ');
}

/**
 * Where a pact comes from: its branch, or where it is deployed.
 *
 * @param pact - The pact.
 * @returns E.g. `main`, `production`.
 */
function pactWhere(pact: PreviewPact): string {
  return pact.deployed_to[0] ?? pact.released_in[0] ?? pact.branches[0] ?? pact.short_description;
}

/**
 * **This run will verify …** — the pacts the run would verify, those skipped as already verified,
 * every refusal, and the *Nothing to verify* state with **Run anyway**.
 *
 * @param props - The preview state, whether the run is self-run, and the Run anyway handler.
 * @returns The aside's first card.
 */
export function PreviewAside({
  state,
  selfRun,
  version,
  onRunAnyway,
}: {
  state: PreviewState;
  selfRun: boolean;
  version: string;
  onRunAnyway: (() => void) | null;
}) {
  if (state.kind !== 'ready') {
    return (
      <section className="ppub-card" data-testid="pvr-preview" aria-busy={state.kind === 'loading'}>
        <p className="ppub-caps">{selfRun ? 'Your pipeline will verify' : 'This run will verify'}</p>
        <p className={state.kind === 'failed' ? 'ppub-hint ppub-hint--danger' : 'ppub-hint'} data-testid="pvr-preview-note">
          {state.kind === 'failed'
            ? state.error
            : state.kind === 'loading'
              ? 'Selecting the pacts…'
              : 'Choose the provider: the pacts the rules select appear here before anything runs.'}
        </p>
      </section>
    );
  }
  const { preview } = state;
  const shown = preview.pacts.slice(0, ASIDE_PACTS);
  const more = preview.selected - shown.length;
  const nothing = preview.selected > 0 && preview.will_run === 0 && preview.skipped > 0;
  return (
    <section className="ppub-card" data-testid="pvr-preview">
      <div className="ppc-aside__head">
        <p className="ppub-caps">{selfRun ? 'Your pipeline will verify' : 'Preview'}</p>
        <span className="ppub-hint">live · nothing sent</span>
      </div>
      {nothing ? (
        <div className="pvr-nothing" data-testid="pvr-nothing">
          <p className="ppc-headline__title">Every selected pact is already verified for {version}.</p>
          {onRunAnyway ? (
            <Button variant="outline" onClick={onRunAnyway} data-testid="pvr-run-anyway">
              Run anyway
            </Button>
          ) : null}
        </div>
      ) : (
        <p className="ppc-headline__title" data-testid="pvr-headline">
          {preview.selected === 0 ? 'The rules select no pact.' : previewHeadline(preview)}
        </p>
      )}
      {shown.length ? (
        <ul className="ppub-ix__list" data-testid="pvr-pacts">
          {shown.map((pact) => (
            <li key={`${pact.consumer}-${pact.pact_version_sha}`} className="ppub-ix" data-testid="pvr-pact">
              <span className="pvr-avatar" aria-hidden>
                {initials(pact.consumer_name)}
              </span>
              <div className="ppub-ix__main">
                <span className="ppub-ix__name">
                  <b>{pact.consumer_name}</b>{' '}
                  <span className="ppub-hint">
                    {pact.consumer_version} · {pactWhere(pact)}
                  </span>
                </span>
                <span className="ppub-ix__sub">{pactSubline(pact)}</span>
              </div>
              {!pact.will_run ? (
                <Badge variant="neutral">Skipped</Badge>
              ) : pact.wip ? (
                <Badge variant="warn">WIP</Badge>
              ) : pact.pending ? (
                <Badge variant="warn">Pending</Badge>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {more > 0 || preview.skipped > 0 ? (
        <p className="ppub-hint" data-testid="pvr-more">
          {more > 0 ? `+ ${more} more` : ''}
          {more > 0 && preview.skipped > 0 ? ' · ' : ''}
          {preview.skipped > 0
            ? `${preview.skipped} already verified for this exact version ${preview.skipped === 1 ? 'is' : 'are'} skipped`
            : ''}
        </p>
      ) : null}
      {preview.refusals.length ? (
        <ul className="ppub-result__list" data-testid="pvr-refusals">
          {preview.refusals.map((refusal) => (
            <li key={refusal.code + refusal.message} className="ppc-result__line ppc-result__line--danger">
              <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
              <span>{refusal.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

// --- dialogs ---------------------------------------------------------------------------------------

/**
 * **Add a target**: a name, the base URL, whether it is production, and the secret it signs in with.
 *
 * @param props - Whether it is open, how to save and close.
 * @returns The dialog.
 */
export function AddTargetDialog({
  open,
  onSave,
  onClose,
}: {
  open: boolean;
  /** Saves; resolves to the refusal, or `null` when saved. */
  onSave: (form: NewTargetForm) => Promise<string | null>;
  onClose: () => void;
}) {
  const [form, setForm] = React.useState<NewTargetForm>({ name: '', baseUrl: '', production: false, secret: '' });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [tried, setTried] = React.useState(false);
  const problems = newTargetProblems(form);
  const save = async () => {
    setTried(true);
    if (problems.length) return;
    setBusy(true);
    const refused = await onSave(form);
    setBusy(false);
    setError(refused);
    if (!refused) {
      setForm({ name: '', baseUrl: '', production: false, secret: '' });
      setTried(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      {open ? (
        <DialogContent data-testid="pvr-add-target">
          <DialogHeader>
            <DialogTitle>Add a target</DialogTitle>
            <DialogDescription>A running instance of the provider that Apiome may call.</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div className="ppub-field">
              <Label htmlFor="pvr-target-name">Name</Label>
              <Input id="pvr-target-name" value={form.name} maxLength={200} placeholder="billing-staging" onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="ppub-field">
              <Label htmlFor="pvr-target-url">Base URL</Label>
              <Input
                id="pvr-target-url"
                value={form.baseUrl}
                maxLength={2000}
                placeholder="https://billing.staging.example.com"
                onChange={(e) => setForm({ ...form, baseUrl: e.target.value })}
              />
            </div>
            <div className="ppub-field">
              <Label htmlFor="pvr-target-secret">Sign in with a secret (optional)</Label>
              <Input
                id="pvr-target-secret"
                className="ppx__mono"
                value={form.secret}
                maxLength={128}
                placeholder="billing-staging-token"
                aria-describedby="pvr-target-secret-hint"
                onChange={(e) => setForm({ ...form, secret: e.target.value })}
              />
              <p className="ppub-hint" id="pvr-target-secret-hint">
                The name of a workspace secret, sent as a bearer token. Never the value itself.
              </p>
            </div>
            <div className="ppub-switch">
              <div>
                <Label htmlFor="pvr-target-production">This is production</Label>
                <p className="ppub-hint" id="pvr-target-production-hint">
                  A production target is read-only: requests that change data are never sent to it.
                </p>
              </div>
              <Switch
                id="pvr-target-production"
                checked={form.production}
                aria-describedby="pvr-target-production-hint"
                onCheckedChange={(production: boolean) => setForm({ ...form, production })}
              />
            </div>
            {tried && problems.length ? (
              <ul className="ppub-result__list" role="alert">
                {problems.map((problem) => (
                  <li key={problem} className="ppub-hint ppub-hint--danger">
                    {problem}
                  </li>
                ))}
              </ul>
            ) : null}
            {error ? (
              <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pvr-add-target-error">
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={busy} data-testid="pvr-add-target-save">
              {busy ? 'Adding…' : 'Add target'}
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

/**
 * **Save as a schedule**: the provider's PFX-6.2 cadence and target, so scheduled runs verify it.
 *
 * @param props - The provider and target, how to save and close.
 * @returns The dialog.
 */
export function ScheduleDialog({
  open,
  provider,
  target,
  onSave,
  onClose,
}: {
  open: boolean;
  provider: string;
  target: string;
  onSave: (cadence: Cadence) => Promise<string | null>;
  onClose: () => void;
}) {
  const [cadence, setCadence] = React.useState<Cadence>('nightly');
  const [state, setState] = React.useState<{ busy: boolean; error: string | null; saved: boolean }>({ busy: false, error: null, saved: false });
  const save = async () => {
    setState({ busy: true, error: null, saved: false });
    const refused = await onSave(cadence);
    setState({ busy: false, error: refused, saved: !refused });
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setState({ busy: false, error: null, saved: false });
          onClose();
        }
      }}
    >
      {open ? (
        <DialogContent data-testid="pvr-schedule">
          <DialogHeader>
            <DialogTitle>Save as a schedule</DialogTitle>
            <DialogDescription>
              Scheduled runs re-verify {provider}’s overdue pacts against {target} on this cadence.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <div className="ppub-field">
              <Label htmlFor="pvr-schedule-cadence">Cadence</Label>
              <select id="pvr-schedule-cadence" className="ppub-select" value={cadence} onChange={(e) => setCadence(e.target.value as Cadence)}>
                {CADENCES.map((option) => (
                  <option key={option} value={option}>
                    {CADENCE_TEXT[option].label}
                  </option>
                ))}
              </select>
              <p className="ppub-hint">{CADENCE_TEXT[cadence].description}</p>
            </div>
            <p className="ppub-hint">
              A schedule keeps the provider’s pacts verified on this target. It does not keep these rules or options: a scheduled
              run verifies what is overdue, read-only. Change it later in <Link href="/ade/dashboard/pacts/settings">Verification settings</Link>.
            </p>
            {state.error ? (
              <p className="ppub-hint ppub-hint--danger" role="alert">
                {state.error}
              </p>
            ) : null}
            {state.saved ? (
              <p className="ppc-result__line ppc-result__line--ok" role="status" data-testid="pvr-schedule-saved">
                <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
                <span>Saved: {CADENCE_TEXT[cadence].label.toLowerCase()} against {target}.</span>
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
            <Button onClick={() => void save()} disabled={state.busy} data-testid="pvr-schedule-save">
              <Clock aria-hidden />
              {state.busy ? 'Saving…' : 'Save schedule'}
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

/**
 * The run's outcome: the sentence, each pact's outcome and every pact not run, and where to read more.
 *
 * @param props - The answer, how to close.
 * @returns The dialog.
 */
export function RunResultDialog({ run, onClose }: { run: VerifyRunAnswer | null; onClose: () => void }) {
  const tone = run?.connection_error || run?.outcome === 'failed' ? 'danger' : run?.success ? 'ok' : 'warn';
  return (
    <Dialog open={run !== null} onOpenChange={(next) => !next && onClose()}>
      {run ? (
        <DialogContent data-testid="pvr-result">
          <DialogHeader>
            <DialogTitle>{run.connection_error ? 'Could not connect' : run.success ? 'Verification passed' : 'Verification finished'}</DialogTitle>
            <DialogDescription>
              {run.provider} {run.provider_version}
              {run.target.slug ? ` · against ${run.target.slug}` : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <p className={`ppc-result__line ppc-result__line--${tone}`} data-testid="pvr-result-headline">
              {tone === 'ok' ? (
                <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
              ) : tone === 'danger' ? (
                <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
              ) : (
                <CircleAlert aria-hidden className="ppub-ix__glyph ppub-ix__glyph--warn" />
              )}
              <span>{runHeadline(run)}</span>
            </p>
            {run.pacts.length || run.skipped.length ? <RunOutcome run={run} /> : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>
              Close
            </Button>
            <Button asChild>
              <Link href={verificationRoute(run.provider)}>Open the Verification page</Link>
            </Button>
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
