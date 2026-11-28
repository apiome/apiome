'use client';

/**
 * **A pact from a project** — the Export page's first kind (PFX-8.18, #7315):
 * `apiome pact export-consumer-contract`.
 *
 * Pick a project, a consumer declared there with the picker, and optionally a revision and the
 * provider's name; **Derive pact** asks REST for the Pact v4 file. The operation checklist then says,
 * per operation, where its examples came from (the spec's own, or generated from the schema — to
 * review) or why it was left out, and lets you untick operations before downloading. Every finding
 * is listed. A large pact downloads without an inline preview. **Review and publish** hands the pact
 * to the Publish page (PFX-8.3).
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Download, FileUp, WandSparkles } from 'lucide-react';
import { Badge, Button, CommandBlock, Input, Label, MethodChip, Switch } from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import {
  deriveExportAction,
  fileStem,
  interactionCount,
  NOTHING_TO_DERIVE,
  pactWithout,
  previewable,
  sizeLabel,
  validateDeriveExport,
  type DerivedPact,
  type DeriveExportDraft,
  type ExportFinding,
} from '@lib/pact-export';
import { PUBLISH_HANDOFF_KEY, publishRoute } from '@lib/pact-publish-page';
import { fetchProjectConsumers, fetchProjects, type ConsumerChoice, type ProjectChoice } from '../pactPublish/publishApi';
import { derivePact, isFailure, saveFile, type ExportFailure } from './exportApi';

/** Props of {@link DerivePanel}. */
export interface DerivePanelProps {
  draft: DeriveExportDraft;
  onDraft: (draft: DeriveExportDraft) => void;
  /** Whether **Review and publish** is offered (`pacts:create`). */
  canPublish: boolean;
  /** Sends a sentence to the page's one status line (`null` clears it). */
  onStatus: (status: { tone: 'warn' | 'danger'; text: string } | null) => void;
}

/** The finding list under the checklist: every placeholder and omission, with its reason. */
function FindingList({ findings, testId }: { findings: ExportFinding[]; testId: string }) {
  if (findings.length === 0) return null;
  return (
    <ul className="pexp-findings" data-testid={testId}>
      {findings.map((finding, index) => (
        <li key={index} className={finding.outcome === 'omitted' ? 'pexp-finding pexp-finding--omitted' : 'pexp-finding'}>
          <Badge variant={finding.outcome === 'omitted' ? 'danger' : 'warning'}>{finding.outcome === 'omitted' ? 'Left out' : 'Generated'}</Badge>
          <span>
            {[finding.method, finding.path, finding.status, finding.field ? `${finding.location ?? ''} ${finding.field}`.trim() : null].filter(Boolean).join(' · ')}
            {finding.method || finding.path || finding.field ? ': ' : ''}
            {finding.message} <code className="pexp-code">{finding.reason}</code>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function DerivePanel({ draft, onDraft, canPublish, onStatus }: DerivePanelProps) {
  const router = useRouter();
  const [projects, setProjects] = React.useState<ProjectChoice[] | null>(null);
  const [consumers, setConsumers] = React.useState<ConsumerChoice[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [derived, setDerived] = React.useState<DerivedPact | null>(null);
  const [refusal, setRefusal] = React.useState<ExportFailure | null>(null);
  const [excluded, setExcluded] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    void fetchProjects().then((answer) => {
      if (Array.isArray(answer)) setProjects(answer);
      else {
        setProjects([]);
        onStatus({ tone: 'warn', text: `${answer.error} Type the project’s handle instead.` });
      }
    });
    // Read once, when the kind is first shown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!draft.project) {
      setConsumers(null);
      return;
    }
    let live = true;
    setConsumers(null);
    void fetchProjectConsumers(draft.project).then((answer) => {
      if (!live) return;
      if (Array.isArray(answer)) setConsumers(answer);
      else {
        setConsumers([]);
        onStatus({ tone: 'warn', text: answer.error });
      }
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.project]);

  const edit = (patch: Partial<DeriveExportDraft>) => {
    onDraft({ ...draft, ...patch });
    if ('project' in patch || 'consumer' in patch || 'revision' in patch || 'provider' in patch) {
      setDerived(null);
      setRefusal(null);
      setExcluded(new Set());
    }
  };

  const derive = async () => {
    const problem = validateDeriveExport(draft);
    if (problem) return onStatus({ tone: 'danger', text: problem });
    onStatus(null);
    setBusy(true);
    const answer = await derivePact(draft);
    setBusy(false);
    setExcluded(new Set());
    if (isFailure(answer)) {
      setDerived(null);
      setRefusal(answer);
      onStatus({ tone: 'danger', text: answer.code === 'consumer-pact-export-empty' ? `${NOTHING_TO_DERIVE} ${answer.error}` : answer.error });
      return;
    }
    setRefusal(null);
    setDerived(answer);
  };

  const toggle = (key: string) => {
    const next = new Set(excluded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setExcluded(next);
  };

  const pact = derived ? pactWithout(derived, excluded) : null;
  const text = pact ? `${JSON.stringify(pact, null, 2)}\n` : '';
  const kept = pact ? interactionCount(pact) : 0;
  const fileName = derived ? `${fileStem(derived.consumerName, derived.providerName)}.json` : 'pact.json';
  const includable = derived ? derived.operations.filter((row) => row.interactions.length > 0) : [];
  const allChecked = includable.length > 0 && includable.every((row) => !excluded.has(row.key));

  const reviewAndPublish = () => {
    if (!pact || kept === 0) return;
    // The whole surface at the current revision publishes as derived (keeping its provenance);
    // anything else — some operations left out, an older revision — hands over the exact file.
    if (excluded.size === 0 && !draft.revision.trim()) {
      router.push(publishRoute({ source: 'derive', project: draft.project, consumer: draft.consumer, provider: draft.provider }));
      return;
    }
    try {
      window.sessionStorage.setItem(PUBLISH_HANDOFF_KEY, JSON.stringify({ pact: text }));
    } catch {
      return onStatus({ tone: 'danger', text: 'The browser refused to hand the pact over. Download it and upload it on the Publish page.' });
    }
    router.push(publishRoute({ source: 'paste' }));
  };

  const action = deriveExportAction(draft, { tenant: '', excluded: [...excluded] });
  /** Why the pact cannot be downloaded or published yet, or `null`. */
  const unavailable = !pact ? 'Derive the pact first' : kept === 0 ? 'Every operation is unticked' : null;

  return (
    <div className="ppub__split" data-testid="pexp-derive">
      <section className="ppub-card" aria-labelledby="pexp-derive-title">
        <div className="ppub-card__head">
          <h2 className="ppub-card__title" id="pexp-derive-title">
            Derive a pact from a project
          </h2>
          <Badge variant="secondary">Pact v4</Badge>
        </div>
        <p className="ppub-card__lead">
          One interaction per operation and response status the consumer declares, with only the fields it reads and the spec’s examples as sample values.
        </p>
        <div className="ppub-grid">
          <div className="ppub-field">
            <Label htmlFor="pexp-derive-project">Project</Label>
            <select id="pexp-derive-project" className="ppub-select" value={draft.project} onChange={(event) => edit({ project: event.target.value, consumer: '' })}>
              <option value="">{projects === null ? 'Loading projects…' : 'Choose a project'}</option>
              {draft.project && !(projects ?? []).some((p) => p.slug === draft.project || p.id === draft.project) ? <option value={draft.project}>{draft.project}</option> : null}
              {(projects ?? []).map((p) => (
                <option key={p.id} value={p.slug}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="ppub-field">
            <Label htmlFor="pexp-derive-consumer">Consumer</Label>
            <select
              id="pexp-derive-consumer"
              className="ppub-select"
              value={draft.consumer}
              disabled={!draft.project}
              onChange={(event) => edit({ consumer: event.target.value })}
              aria-describedby="pexp-derive-consumer-hint"
            >
              <option value="">{draft.project && consumers === null ? 'Loading consumers…' : 'Choose a consumer'}</option>
              {draft.consumer && !(consumers ?? []).some((c) => c.slug === draft.consumer) ? <option value={draft.consumer}>{draft.consumer}</option> : null}
              {(consumers ?? []).map((c) => (
                <option key={c.slug} value={c.slug} disabled={c.unavailable !== null}>
                  {c.unavailable ? `${c.name} — ${c.unavailable}` : c.name}
                </option>
              ))}
            </select>
            <p className="ppub-hint" id="pexp-derive-consumer-hint">
              Only a consumer declared with the picker can be derived.
            </p>
          </div>
          <div className="ppub-field">
            <Label htmlFor="pexp-derive-revision">Revision (optional)</Label>
            <Input id="pexp-derive-revision" inputMode="numeric" value={draft.revision} placeholder="The current revision" onChange={(event) => edit({ revision: event.target.value })} />
          </div>
          <div className="ppub-field">
            <Label htmlFor="pexp-derive-provider">Provider (optional)</Label>
            <Input id="pexp-derive-provider" value={draft.provider} placeholder="The project’s provider pacticipant" onChange={(event) => edit({ provider: event.target.value })} />
          </div>
        </div>
        <div className="ppub-row-actions">
          <Button variant="outline" onClick={() => void derive()} disabled={busy} title={busy ? 'The pact is being derived' : undefined} data-testid="pexp-derive-run">
            <WandSparkles aria-hidden />
            {busy ? 'Deriving…' : derived ? 'Derive again' : 'Derive pact'}
          </Button>
        </div>

        {derived ? (
          <>
            <div className="ppub-table-wrap">
              <table className="ppub-table" data-testid="pexp-operations">
                <thead>
                  <tr>
                    <th scope="col" className="pexp-check-col">
                      <input
                        type="checkbox"
                        aria-label="Include every operation"
                        checked={allChecked}
                        disabled={includable.length === 0}
                        onChange={() => setExcluded(allChecked ? new Set(includable.map((row) => row.key)) : new Set())}
                      />
                    </th>
                    <th scope="col">Operation</th>
                    <th scope="col">Example comes from</th>
                  </tr>
                </thead>
                <tbody>
                  {derived.operations.map((row) => {
                    const leftOut = row.interactions.length === 0;
                    return (
                      <tr key={row.key} data-testid="pexp-operation">
                        <td className="pexp-check-col">
                          <input
                            type="checkbox"
                            aria-label={leftOut ? `${row.key} cannot be included` : `Include ${row.key}`}
                            checked={!leftOut && !excluded.has(row.key)}
                            disabled={leftOut}
                            onChange={() => toggle(row.key)}
                          />
                        </td>
                        <td>
                          <span className="pexp-op">
                            <MethodChip method={row.method} />
                            <span className="pexp-path">{row.path}</span>
                          </span>
                        </td>
                        <td className={`pexp-source pexp-source--${row.source}`}>{row.note}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <FindingList findings={derived.findings} testId="pexp-derive-findings" />
          </>
        ) : refusal && refusal.findings.length ? (
          <FindingList findings={refusal.findings} testId="pexp-derive-findings" />
        ) : null}

        <div className="ppub-switch">
          <div>
            <Label htmlFor="pexp-fail-on-findings">Fail if anything needs review</Label>
            <p className="ppub-hint" id="pexp-fail-on-findings-hint">
              In CI, exit non-zero when an example had to be generated or anything was left out. Here, every finding is listed above.
            </p>
          </div>
          <Switch id="pexp-fail-on-findings" checked={draft.failOnFindings} aria-describedby="pexp-fail-on-findings-hint" onCheckedChange={(failOnFindings: boolean) => onDraft({ ...draft, failOnFindings })} />
        </div>
      </section>

      <aside className="ppub__aside">
        <section className="ppub-card" aria-labelledby="pexp-derive-preview">
          <div className="ppub-card__head">
            <h3 className="ppub-caps" id="pexp-derive-preview">
              Preview
            </h3>
            {pact ? (
              <span className="ppub-hint">
                {kept} interaction{kept === 1 ? '' : 's'} · Pact v4 · {sizeLabel(text.length)}
              </span>
            ) : null}
          </div>
          {!pact ? (
            <p className="ppub-hint">Derive the pact to see it here.</p>
          ) : previewable(text) ? (
            <pre className="pexp-preview" aria-label="Pact preview" tabIndex={0} data-testid="pexp-derive-preview">
              {text}
            </pre>
          ) : (
            <p className="ppub-hint" data-testid="pexp-derive-large">
              This pact is {sizeLabel(text.length)} — too large to preview. Download it to read it.
            </p>
          )}
          <div className="ppub-row-actions">
            <Button onClick={() => pact && saveFile(fileName, text)} disabled={!pact || kept === 0} title={unavailable ?? undefined} data-testid="pexp-derive-download">
              <Download aria-hidden />
              Download pact
            </Button>
            {canPublish ? (
              <Button variant="outline" onClick={reviewAndPublish} disabled={!pact || kept === 0} title={unavailable ?? 'Opens the Publish page; nothing is published until you do'} data-testid="pexp-derive-publish">
                <FileUp aria-hidden />
                Review and publish
              </Button>
            ) : null}
          </div>
          {pact && kept === 0 ? <p className="ppub-hint ppub-hint--danger">Every operation is unticked: there is nothing to download.</p> : null}
        </section>
        <CommandBlock surfaces={pactCommandSurfaces(action)} unsupported={unsupportedLines(action)} footnote="Replace {tenant} with your workspace’s handle in the REST path." data-testid="pexp-derive-command" />
      </aside>
    </div>
  );
}
