'use client';

/**
 * **Run a verification** — `/ade/dashboard/pacts/verification/new` (PFX-8.8, #7305).
 *
 * The screen for `apiome pact verify`, built to `docs/mockups/contracts/verify.html`:
 *
 * 1. **The provider under test** — provider, the version being verified (results are recorded
 *    against it), branch; *Apiome runs it* (a target and how it signs in, or **Add a target…**) or
 *    *Your pipeline runs it* (the command only, for a provider Apiome cannot reach).
 * 2. **Which pacts to verify** — the rules as sentences with a pact count each; presets Recommended,
 *    Everything and Custom (Custom adds and removes rules); *Pending pacts cannot fail this run*;
 *    *Include work-in-progress pacts* since a date.
 * 3. **Getting the provider into the right state** — Apiome’s state handlers (how many states have
 *    one, how many are missing), the provider’s own setup endpoint, or no setup; *Allow requests
 *    that change data*, refused for a production target before anything is sent.
 *
 * The aside previews the run (`POST …/verify/preview`, refreshed as the form settles): the pacts it
 * will verify, those skipped as already verified for this exact version (*Nothing to verify* offers
 * **Run anyway**), every reason it would not start; then **The same, from anywhere**. **Run
 * verification** runs the hosted verifier; the outcome dialog says how it went — an unreachable
 * target is *Could not connect*, not a failed verification. **Save as a schedule** stores the
 * provider’s cadence and target (PFX-6.2).
 *
 * A role without `pacts:create` sees the preview and the command block, and no Run.
 */

import * as React from 'react';
import Link from 'next/link';
import { Play } from 'lucide-react';
import { Alert, Button, CommandBlock, Input, Label, Switch } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_CRUMBS } from '@lib/pact-overview';
import type { Cadence } from '@lib/pact-remediation';
import { verificationRoute } from '@lib/pact-verification';
import {
  EMPTY_FORM,
  MUTATING_PRODUCTION,
  everythingVerified,
  formProblems,
  newTargetBody,
  presetRules,
  previewBody,
  statesSentence,
  targetLabel,
  targetSignIn,
  verifyBody,
  verifyCommandAction,
  verifySurfaces,
  type FormProblem,
  type SelectorPreset,
  type StateStrategy,
  type VerifyForm,
  type VerifyRunAnswer,
  type VerifyTarget,
} from '@lib/pact-verify-run';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { AddTargetDialog, PreviewAside, RunResultDialog, ScheduleDialog, SelectorRules, type PreviewState } from './VerifyRunPanels';
import {
  createTarget,
  fetchProviders,
  fetchTargets,
  previewVerification,
  runVerification,
  saveSchedule,
  type ProviderChoice,
} from './verifyRunApi';

/** The permission running needs (REST also needs `verification_evidence:create`). */
const RUN_PERMISSION = 'pacts:create';

/** How long the form must be still before the preview is refreshed. */
const PREVIEW_DELAY_MS = 700;

/** A list being read: `null` while loading, the rows, or why it could not be read. */
type Loaded<T> = T[] | null | { error: string };

/** The presets, as the chips read. */
const PRESETS: { id: SelectorPreset; label: string }[] = [
  { id: 'recommended', label: 'Recommended' },
  { id: 'everything', label: 'Everything' },
  { id: 'custom', label: 'Custom' },
];

/** The provider-state strategies, as the option cards read. */
const STRATEGIES: { id: StateStrategy; title: string }[] = [
  { id: 'registry', title: 'Apiome’s state handlers' },
  { id: 'setup-url', title: 'The provider’s own setup endpoint' },
  { id: 'none', title: 'No setup' },
];

/** The message of one field's problem. */
function problemOf(problems: FormProblem[], field: string): string | null {
  return problems.find((p) => p.field === field)?.message ?? null;
}

/** Props for {@link VerifyRunClient}. */
export interface VerifyRunClientProps {
  /** The provider to start with (`?provider=`). */
  initialProvider?: string | null;
}

/**
 * The page.
 *
 * @param props - The provider to start with.
 * @returns The page.
 */
export function VerifyRunClient({ initialProvider }: VerifyRunClientProps) {
  const permissions = useMyPermissions();
  const canRun = permissions.status === 'ready' && permissions.can(RUN_PERMISSION);
  const [form, setForm] = React.useState<VerifyForm>({ ...EMPTY_FORM, provider: initialProvider ?? '' });
  const [providers, setProviders] = React.useState<Loaded<ProviderChoice>>(null);
  const [targets, setTargets] = React.useState<Loaded<VerifyTarget>>(null);
  const [preview, setPreview] = React.useState<PreviewState>({ kind: 'idle' });
  const [tried, setTried] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<VerifyRunAnswer | null>(null);
  const [addingTarget, setAddingTarget] = React.useState(false);
  const [scheduling, setScheduling] = React.useState(false);

  const edit = (patch: Partial<VerifyForm>) => setForm((current) => ({ ...current, ...patch }));

  React.useEffect(() => {
    let live = true;
    void fetchProviders().then((answer) => live && setProviders('error' in answer ? { error: answer.error } : answer));
    void fetchTargets().then((answer) => live && setTargets('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, []);

  const targetList = Array.isArray(targets) ? targets : [];
  const target = targetList.find((t) => t.slug === form.target) ?? null;
  const providerList = Array.isArray(providers) ? providers : [];
  const provider = providerList.find((p) => p.slug === form.provider) ?? null;

  // The branch defaults to the provider's main branch, once, when the provider is chosen.
  React.useEffect(() => {
    if (provider?.mainBranch) setForm((current) => (current.branch ? current : { ...current, branch: provider.mainBranch ?? '' }));
  }, [provider?.mainBranch]);

  // The preview, refreshed once the form has been still for a moment.
  const previewKey = form.provider.trim() ? JSON.stringify(previewBody(form)) + form.provider : '';
  React.useEffect(() => {
    if (!previewKey) {
      setPreview({ kind: 'idle' });
      return;
    }
    let live = true;
    setPreview({ kind: 'loading' });
    const timer = window.setTimeout(() => {
      void previewVerification(form.provider.trim(), previewBody(form)).then((answer) => {
        if (!live) return;
        setPreview('error' in answer ? { kind: 'failed', error: answer.error } : { kind: 'ready', preview: answer });
      });
    }, PREVIEW_DELAY_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // previewKey stands for every input of the preview.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  const problems = formProblems(form, target);
  const ready = preview.kind === 'ready' ? preview.preview : null;
  const counts = form.rules.map((_r, index) => ready?.rules[index]?.pacts ?? null);
  const hint = (field: string) => {
    // The production rule shows at once (the mockup's *blocked* state); the rest after a try.
    const message = tried || field === 'allowMutating' ? problemOf(problems, field) : null;
    return message ? (
      <p className="ppub-hint ppub-hint--danger" data-testid={`pvr-problem-${field}`}>
        {message}
      </p>
    ) : null;
  };
  const ruleProblems = Object.fromEntries(
    tried ? problems.filter((p) => p.field.startsWith('rule:')).map((p) => [p.field.slice(5), p.message]) : [],
  );

  const run = async (runAnyway = false) => {
    setTried(true);
    setProblem(null);
    if (form.mode !== 'hosted' || problems.length) return;
    setBusy(true);
    const answer = await runVerification(form.provider.trim(), verifyBody(form, { runAnyway }));
    setBusy(false);
    if ('error' in answer) setProblem(answer.error);
    else setResult(answer);
  };

  const addTarget = async (draft: Parameters<typeof newTargetBody>[0]): Promise<string | null> => {
    const answer = await createTarget(newTargetBody(draft));
    if ('error' in answer) return answer.error;
    setTargets((current) => [...(Array.isArray(current) ? current : []), answer]);
    edit({ target: answer.slug });
    setAddingTarget(false);
    return null;
  };

  const schedule = async (cadence: Cadence): Promise<string | null> => {
    const refused = await saveSchedule(form.provider.trim(), cadence, form.target.trim());
    return refused ? refused.error : null;
  };

  const action = verifyCommandAction(form, '');
  const nothing = everythingVerified(ready);
  const hosted = form.mode === 'hosted';
  const blocked = Boolean(problemOf(problems, 'allowMutating'));

  return (
    <Page>
      <PageHeader
        title="Run a verification"
        breadcrumb={[...CONTRACTS_CRUMBS, { label: 'Verification' }, { label: 'Run' }]}
        description="Replay consumers’ pacts against a running provider and record what it really answers."
        tabs={<ContractsTabs active="verification" />}
        actions={
          canRun && hosted ? (
            <Button
              variant="outline"
              onClick={() => setScheduling(true)}
              disabled={!form.provider.trim() || !form.target.trim()}
              title="Scheduled runs re-verify this provider’s overdue pacts on the chosen target"
              data-testid="pvr-save-schedule"
            >
              Save as a schedule
            </Button>
          ) : undefined
        }
        primaryAction={
          canRun && hosted ? (
            <Button onClick={() => void run()} disabled={busy || blocked || nothing} data-testid="pvr-run">
              <Play aria-hidden />
              {busy ? 'Verifying…' : 'Run verification'}
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="ppub" data-testid="pact-verify-run">
          {problem ? (
            <Alert variant="danger" data-testid="pvr-status">
              {problem}
            </Alert>
          ) : null}
          <div className="ppub__split">
            <div className="ppub__main">
              <section className="ppub-card" aria-labelledby="pvr-step-1">
                <div className="ppub-card__head">
                  <h2 className="ppub-card__title" id="pvr-step-1">
                    <span className="ppub-step" aria-hidden>
                      1
                    </span>
                    The provider under test
                  </h2>
                </div>
                <div className="ppub-grid">
                  <div className="ppub-field">
                    <Label htmlFor="pvr-provider">Provider</Label>
                    <select id="pvr-provider" className="ppub-select" value={form.provider} onChange={(e) => edit({ provider: e.target.value, branch: '' })}>
                      <option value="">{providers === null ? 'Loading providers…' : 'Choose a provider'}</option>
                      {form.provider && !provider ? <option value={form.provider}>{form.provider}</option> : null}
                      {providerList.map((p) => (
                        <option key={p.slug} value={p.slug}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    {providers && 'error' in providers ? <p className="ppub-hint ppub-hint--danger">{providers.error}</p> : null}
                    {hint('provider')}
                  </div>
                  <div className="ppub-field">
                    <Label htmlFor="pvr-version">Version being verified</Label>
                    <Input
                      id="pvr-version"
                      className="ppx__mono"
                      value={form.providerVersion}
                      maxLength={255}
                      placeholder={hosted ? '2.7.0+9f31c20' : '$GIT_COMMIT in your pipeline'}
                      aria-describedby="pvr-version-hint"
                      onChange={(e) => edit({ providerVersion: e.target.value })}
                    />
                    <p className="ppub-hint" id="pvr-version-hint">
                      Results are recorded against this version.
                    </p>
                    {hint('providerVersion')}
                  </div>
                  <div className="ppub-field">
                    <Label htmlFor="pvr-branch">Branch</Label>
                    <Input id="pvr-branch" value={form.branch} maxLength={255} placeholder="main" onChange={(e) => edit({ branch: e.target.value })} />
                    {hint('branch')}
                  </div>
                </div>
                <fieldset className="ppc-options pvr-modes">
                  <legend className="ppub-field__label">Who runs it</legend>
                  {(
                    [
                      ['hosted', 'Apiome runs it', 'The hosted verifier calls a reachable instance. Nothing to install.'],
                      ['self', 'Your pipeline runs it', 'For providers Apiome cannot reach. Copy the command; results come back here.'],
                    ] as const
                  ).map(([id, title, description]) => (
                    <label key={id} className={`ppc-option${form.mode === id ? ' is-active' : ''}`} data-testid={`pvr-mode-${id}`}>
                      <input type="radio" name="pvr-mode" className="ppc-option__radio" checked={form.mode === id} onChange={() => edit({ mode: id })} />
                      <span className="ppc-option__body">
                        <span className="ppc-option__title">{title}</span>
                        <span className="ppc-option__desc">{description}</span>
                      </span>
                    </label>
                  ))}
                </fieldset>
                {hosted ? (
                  <div className="ppub-grid">
                    <div className="ppub-field">
                      <Label htmlFor="pvr-target">Target</Label>
                      <select
                        id="pvr-target"
                        className="ppub-select"
                        value={form.target}
                        onChange={(e) => {
                          if (e.target.value === '__add') setAddingTarget(true);
                          else edit({ target: e.target.value });
                        }}
                      >
                        <option value="">{targets === null ? 'Loading targets…' : targetList.length ? 'Choose a target' : 'No target yet'}</option>
                        {targetList.map((t) => (
                          <option key={t.slug} value={t.slug} disabled={!t.enabled}>
                            {targetLabel(t)}
                          </option>
                        ))}
                        {canRun ? <option value="__add">Add a target…</option> : null}
                      </select>
                      {targets && 'error' in targets ? <p className="ppub-hint ppub-hint--danger">{targets.error}</p> : null}
                      {hint('target')}
                    </div>
                    <div className="ppub-field">
                      <span className="ppub-field__label">Sign in with</span>
                      <p className="ppub-field__value" data-testid="pvr-sign-in">
                        {target ? targetSignIn(target) : '—'}
                      </p>
                      <p className="ppub-hint">The target’s credential. The run never sends one of its own.</p>
                    </div>
                  </div>
                ) : (
                  <p className="ppc-callout" data-testid="pvr-self-run-note">
                    Set everything below, then copy the command from the right. It carries the same selectors and options, and publishes its
                    results back.
                  </p>
                )}
                <details className="ppub-more">
                  <summary>More options</summary>
                  <div className="ppub-more__body">
                    <div className="ppub-field">
                      <Label htmlFor="pvr-build-url">Build URL</Label>
                      <Input id="pvr-build-url" value={form.buildUrl} maxLength={2000} placeholder="https://ci.example.com/build/42" onChange={(e) => edit({ buildUrl: e.target.value })} />
                      {hint('buildUrl')}
                    </div>
                    <div className="ppub-field">
                      <Label htmlFor="pvr-context">CI context</Label>
                      <textarea
                        id="pvr-context"
                        className="ppub-select pvr-context"
                        value={form.context}
                        rows={2}
                        placeholder="commit=9f31c20"
                        aria-describedby="pvr-context-hint"
                        onChange={(e) => edit({ context: e.target.value })}
                      />
                      <p className="ppub-hint" id="pvr-context-hint">
                        One KEY=VALUE per line, stored with the evidence. Never credentials.
                      </p>
                      {hint('context')}
                    </div>
                    <div className="ppub-switch">
                      <div>
                        <Label htmlFor="pvr-publish">Publish the results</Label>
                        <p className="ppub-hint">Off is a dry run: everything is replayed and reported, nothing is recorded.</p>
                      </div>
                      <Switch id="pvr-publish" checked={form.publish} onCheckedChange={(publish: boolean) => edit({ publish })} />
                    </div>
                    <div className="ppub-switch">
                      <div>
                        <Label htmlFor="pvr-skip">Skip pacts already verified for this version</Label>
                        <p className="ppub-hint">They keep the result they have; Run anyway verifies them again.</p>
                      </div>
                      <Switch id="pvr-skip" checked={form.skipVerified} onCheckedChange={(skipVerified: boolean) => edit({ skipVerified })} />
                    </div>
                  </div>
                </details>
              </section>

              <section className="ppub-card" aria-labelledby="pvr-step-2">
                <div className="ppub-card__head">
                  <h2 className="ppub-card__title" id="pvr-step-2">
                    <span className="ppub-step" aria-hidden>
                      2
                    </span>
                    Which pacts to verify
                  </h2>
                  <div className="ppub-chips" role="group" aria-label="Preset">
                    {PRESETS.map((preset) => (
                      <button
                        key={preset.id}
                        type="button"
                        className={`ppub-chip${form.preset === preset.id ? ' is-active' : ''}`}
                        aria-pressed={form.preset === preset.id}
                        data-testid={`pvr-preset-${preset.id}`}
                        onClick={() => edit({ preset: preset.id, rules: presetRules(preset.id, form.rules) })}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>
                <SelectorRules
                  rules={form.rules}
                  counts={counts}
                  branch={form.branch}
                  editable={form.preset === 'custom'}
                  problems={ruleProblems}
                  onChange={(rules) => edit({ rules })}
                />
                {hint('rules')}
                <div className="ppub-switch">
                  <div>
                    <Label htmlFor="pvr-pending">Pending pacts cannot fail this run</Label>
                    <p className="ppub-hint">A pact this provider has never passed is reported, not enforced.</p>
                  </div>
                  <Switch id="pvr-pending" checked={form.pending} onCheckedChange={(pending: boolean) => edit({ pending })} />
                </div>
                <div className="ppub-switch">
                  <div>
                    <Label htmlFor="pvr-wip">Include work-in-progress pacts</Label>
                    <p className="ppub-hint">Also try pacts from feature branches newer than a date.</p>
                  </div>
                  <Switch id="pvr-wip" checked={form.wip} onCheckedChange={(wip: boolean) => edit({ wip })} />
                </div>
                {form.wip ? (
                  <div className="ppub-field pvr-narrow">
                    <Label htmlFor="pvr-wip-since">Work in progress since</Label>
                    <Input id="pvr-wip-since" type="date" value={form.wipSince} onChange={(e) => edit({ wipSince: e.target.value })} />
                    {hint('wipSince')}
                  </div>
                ) : null}
              </section>

              <section className="ppub-card" aria-labelledby="pvr-step-3">
                <div className="ppub-card__head">
                  <h2 className="ppub-card__title" id="pvr-step-3">
                    <span className="ppub-step" aria-hidden>
                      3
                    </span>
                    Getting the provider into the right state
                  </h2>
                </div>
                <fieldset className="ppc-options">
                  <legend className="ppub-field__label">Provider states</legend>
                  {STRATEGIES.map((strategy) => (
                    <label key={strategy.id} className={`ppc-option${form.states === strategy.id ? ' is-active' : ''}`} data-testid={`pvr-states-${strategy.id}`}>
                      <input
                        type="radio"
                        name="pvr-states"
                        className="ppc-option__radio"
                        checked={form.states === strategy.id}
                        onChange={() => edit({ states: strategy.id })}
                      />
                      <span className="ppc-option__body">
                        <span className="ppc-option__title">{strategy.title}</span>
                        <span className="ppc-option__desc" data-testid={strategy.id === 'registry' ? 'pvr-states-sentence' : undefined}>
                          {strategy.id === 'registry'
                            ? form.states === 'registry'
                              ? statesSentence(ready)
                              : 'Each state is set up by the handler registered for it.'
                            : strategy.id === 'setup-url'
                              ? 'Apiome POSTs each state to a URL on the provider before the interaction.'
                              : 'Replay as-is. Interactions that need a state are likely to fail.'}
                        </span>
                      </span>
                    </label>
                  ))}
                </fieldset>
                {form.states === 'setup-url' ? (
                  <div className="ppub-field">
                    <Label htmlFor="pvr-setup-url">Setup endpoint</Label>
                    <Input
                      id="pvr-setup-url"
                      className="ppx__mono"
                      value={form.setupUrl}
                      maxLength={2048}
                      placeholder="/_pact/provider-states"
                      aria-describedby="pvr-setup-url-hint"
                      onChange={(e) => edit({ setupUrl: e.target.value })}
                    />
                    <p className="ppub-hint" id="pvr-setup-url-hint">
                      A path on the target carries the target’s credential; another URL gets none.
                    </p>
                    {hint('setupUrl')}
                  </div>
                ) : null}
                {form.states === 'registry' && ready && ready.states.missing.length ? (
                  <p className="ppub-hint" data-testid="pvr-states-missing">
                    Missing: {ready.states.missing.join(', ')}. <Link href="/ade/dashboard/pacts/provider-states">Register a state handler</Link>
                  </p>
                ) : null}
                <div className="ppub-switch">
                  <div>
                    <Label htmlFor="pvr-mutating">Allow requests that change data</Label>
                    <p className="ppub-hint" id="pvr-mutating-hint">
                      POST, PUT, PATCH and DELETE are sent. Off, they are reported as “not run”. Never on for a production target.
                    </p>
                  </div>
                  <Switch
                    id="pvr-mutating"
                    checked={form.allowMutating}
                    aria-describedby="pvr-mutating-hint"
                    onCheckedChange={(allowMutating: boolean) => edit({ allowMutating })}
                  />
                </div>
                {hint('allowMutating')}
                {hosted && target?.environment === 'production' && !form.allowMutating ? (
                  <p className="ppub-hint" data-testid="pvr-production-note">
                    {target.name} is a production target. {MUTATING_PRODUCTION}
                  </p>
                ) : null}
              </section>
            </div>
            <aside className="ppub__aside" aria-label="What this run will verify, and the same from anywhere">
              <PreviewAside
                state={preview}
                selfRun={!hosted}
                version={form.providerVersion.trim()}
                onRunAnyway={canRun && hosted ? () => void run(true) : null}
              />
              <CommandBlock
                key={form.mode}
                className="ppub-command-block"
                surfaces={verifySurfaces(form, '')}
                unsupported={unsupportedLines(action)}
                footnote="Replace {tenant} with your workspace’s handle in the REST path. In CI, pass the commit as the provider version."
                data-testid="pvr-command-block"
              />
              {form.provider.trim() ? (
                <p className="ppub-hint">
                  Past runs are on <Link href={verificationRoute(form.provider.trim())}>{provider?.name ?? form.provider}’s Verification page</Link>.
                </p>
              ) : null}
            </aside>
          </div>
          <AddTargetDialog open={addingTarget} onSave={addTarget} onClose={() => setAddingTarget(false)} />
          <ScheduleDialog
            open={scheduling}
            provider={provider?.name ?? form.provider}
            target={target?.name ?? form.target}
            onSave={schedule}
            onClose={() => setScheduling(false)}
          />
          <RunResultDialog run={result} onClose={() => setResult(null)} />
        </div>
      </PageBody>
    </Page>
  );
}

export default VerifyRunClient;
