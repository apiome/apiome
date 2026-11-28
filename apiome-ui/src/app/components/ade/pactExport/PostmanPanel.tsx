'use client';

/**
 * **A Postman collection** — the Export page's second kind (PFX-8.18, #7315):
 * `apiome pact export-postman`.
 *
 * Name a stored pact (provider and consumer — or **All consumers**, one folder each — and which pact:
 * the latest, on a branch, with a tag, a consumer version or a pact version SHA) or upload a pact
 * file; set the `{{baseUrl}}` value, provider-state setup scripts and test scripts; **Export
 * collection** asks REST for the Postman Collection v2.1. The result card shows the fidelity bar
 * (what the collection keeps) and every notice — what was left out, not asserted or not applied,
 * with REST's reason. Nothing is stored.
 */

import * as React from 'react';
import { Download, Mailbox, Upload } from 'lucide-react';
import { Badge, Button, CommandBlock, Input, Label, Switch } from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import {
  fidelity,
  noPactMessage,
  PACT_CHOICE_LABELS,
  PACT_CHOICES,
  postmanExportAction,
  postmanFileName,
  postmanRequestBody,
  previewable,
  sizeLabel,
  validatePostman,
  type PostmanDraft,
  type PostmanNotice,
  type PostmanOutcome,
} from '@lib/pact-export';
import { exportPostman, isFailure, saveFile, type ExportFailure } from './exportApi';
import { PacticipantField } from './PacticipantField';

/** Props of {@link PostmanPanel}. */
export interface PostmanPanelProps {
  draft: PostmanDraft;
  onDraft: (draft: PostmanDraft) => void;
  /** The workspace's pacticipant names, for the provider and consumer suggestions. */
  pacticipants: string[];
  onStatus: (status: { tone: 'warn' | 'danger'; text: string } | null) => void;
}

/** The notices of an export or a refusal: one line each, with its reason. */
function NoticeList({ notices }: { notices: PostmanNotice[] }) {
  if (notices.length === 0) return null;
  return (
    <ul className="pexp-findings" data-testid="pexp-postman-notices">
      {notices.map((notice, index) => (
        <li key={index} className={notice.outcome === 'left-out' ? 'pexp-finding pexp-finding--omitted' : 'pexp-finding'}>
          <Badge variant={notice.outcome === 'left-out' ? 'danger' : notice.outcome === 'info' ? 'secondary' : 'warning'}>{notice.outcome}</Badge>
          <span>
            {notice.consumer ? `${notice.consumer} · ` : ''}
            {notice.description ? `“${notice.description}”: ` : ''}
            {notice.message}
            {notice.paths?.length ? ` (${notice.paths.join(', ')})` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function PostmanPanel({ draft, onDraft, pacticipants, onStatus }: PostmanPanelProps) {
  const [busy, setBusy] = React.useState(false);
  const [outcome, setOutcome] = React.useState<PostmanOutcome | null>(null);
  const [refusal, setRefusal] = React.useState<ExportFailure | null>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const edit = (patch: Partial<PostmanDraft>) => {
    onDraft({ ...draft, ...patch });
    setOutcome(null);
    setRefusal(null);
  };

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    edit({ fileName: file.name, fileText: await file.text() });
  };

  const run = async () => {
    const problem = validatePostman(draft);
    if (problem) return onStatus({ tone: 'danger', text: problem });
    onStatus(null);
    setBusy(true);
    const answer = await exportPostman(postmanRequestBody(draft));
    setBusy(false);
    if (isFailure(answer)) {
      setOutcome(null);
      setRefusal(answer);
      const missing = answer.status === 404 && draft.source === 'stored' && !draft.allConsumers;
      onStatus({ tone: 'danger', text: missing ? `${noPactMessage(draft.consumer, draft.provider)} (${answer.error})` : answer.error });
      return;
    }
    setRefusal(null);
    setOutcome(answer);
  };

  const text = outcome ? `${JSON.stringify(outcome.collection, null, 2)}\n` : '';
  const bar = outcome ? fidelity(outcome.counts) : null;
  const leftOut = outcome ? outcome.notices.filter((notice) => notice.outcome === 'left-out') : [];
  const action = postmanExportAction(draft, '');
  const choiceField = PACT_CHOICE_LABELS[draft.choice].field;

  return (
    <div className="ppub__split" data-testid="pexp-postman">
      <section className="ppub-card" aria-labelledby="pexp-postman-title">
        <div className="ppub-card__head">
          <h2 className="ppub-card__title" id="pexp-postman-title">
            A Postman collection from a pact
          </h2>
          <Badge variant="secondary">Postman v2.1</Badge>
        </div>
        <div className="ppub-grid">
          <div className="ppub-field">
            <Label htmlFor="pexp-postman-source">Which pact</Label>
            <select
              id="pexp-postman-source"
              className="ppub-select"
              value={draft.source === 'file' ? 'file' : draft.choice}
              onChange={(event) =>
                event.target.value === 'file'
                  ? edit({ source: 'file', allConsumers: false })
                  : edit({ source: 'stored', choice: event.target.value as PostmanDraft['choice'], choiceValue: '' })
              }
            >
              {PACT_CHOICES.map((choice) => (
                <option key={choice} value={choice} disabled={draft.allConsumers && (choice === 'version' || choice === 'sha')}>
                  {PACT_CHOICE_LABELS[choice].label}
                </option>
              ))}
              <option value="file">Upload a pact file…</option>
            </select>
          </div>
          {draft.source === 'stored' && choiceField ? (
            <div className="ppub-field">
              <Label htmlFor="pexp-postman-choice">{choiceField}</Label>
              <Input id="pexp-postman-choice" value={draft.choiceValue} onChange={(event) => edit({ choiceValue: event.target.value })} />
            </div>
          ) : null}
          {draft.source === 'file' ? (
            <div className="ppub-field">
              <span className="ppub-field__label">Pact file</span>
              <input ref={fileInput} type="file" accept=".json,application/json" className="ppub-file-input" aria-label="Pact file" onChange={(event) => void pickFile(event.target.files?.[0])} data-testid="pexp-postman-file" />
              <Button variant="outline" onClick={() => fileInput.current?.click()}>
                <Upload aria-hidden />
                {draft.fileName ? draft.fileName : 'Choose a pact file'}
              </Button>
              <p className="ppub-hint">Sent once to make the collection; nothing is published or stored.</p>
            </div>
          ) : (
            <>
              <PacticipantField id="pexp-postman-provider" label="Provider" value={draft.provider} options={pacticipants} onChange={(provider) => edit({ provider })} />
              <div className="ppub-field">
                <PacticipantField
                  id="pexp-postman-consumer"
                  label="Consumer"
                  value={draft.allConsumers ? '' : draft.consumer}
                  options={pacticipants}
                  disabled={draft.allConsumers}
                  placeholder={draft.allConsumers ? 'Every consumer of the provider' : undefined}
                  onChange={(consumer) => edit({ consumer })}
                />
                <label className="pexp-inline-check">
                  <input
                    type="checkbox"
                    checked={draft.allConsumers}
                    onChange={(event) =>
                      edit({
                        allConsumers: event.target.checked,
                        ...(event.target.checked && (draft.choice === 'version' || draft.choice === 'sha') ? { choice: 'latest' as const, choiceValue: '' } : {}),
                      })
                    }
                    data-testid="pexp-postman-all"
                  />
                  All consumers — one folder each
                </label>
              </div>
            </>
          )}
          <div className="ppub-field">
            <Label htmlFor="pexp-postman-base">Provider base URL</Label>
            <Input id="pexp-postman-base" className="mono" value={draft.baseUrl} placeholder="{{baseUrl}}" aria-describedby="pexp-postman-base-hint" onChange={(event) => edit({ baseUrl: event.target.value })} />
            <p className="ppub-hint" id="pexp-postman-base-hint">
              Empty keeps the <code className="pexp-code">{'{{baseUrl}}'}</code> variable to fill in (Newman: <code className="pexp-code">--env-var baseUrl=…</code>). Point it at a mock to try it safely.
            </p>
          </div>
        </div>
        <div className="ppub-switch">
          <div>
            <Label htmlFor="pexp-state-setup">Include provider-state setup as pre-request scripts</Label>
            <p className="ppub-hint" id="pexp-state-setup-hint">
              Each request first asks the provider to get into the right state: it POSTs <code className="pexp-code">{'{ state, params, action: "setup" }'}</code> to the state change URL, as the Pact verifier does.
            </p>
          </div>
          <Switch id="pexp-state-setup" checked={draft.stateSetup} aria-describedby="pexp-state-setup-hint" onCheckedChange={(stateSetup: boolean) => edit({ stateSetup })} />
        </div>
        {draft.stateSetup ? (
          <div className="ppub-field">
            <Label htmlFor="pexp-state-url">State change URL (optional)</Label>
            <Input id="pexp-state-url" className="mono" value={draft.stateChangeUrl} placeholder="{{stateChangeUrl}}" onChange={(event) => edit({ stateChangeUrl: event.target.value })} />
          </div>
        ) : null}
        <div className="ppub-switch">
          <div>
            <Label htmlFor="pexp-tests">Give each request a test script</Label>
            <p className="ppub-hint" id="pexp-tests-hint">
              Checks the status, the expected headers and the body by Pact’s default rules.
            </p>
          </div>
          <Switch id="pexp-tests" checked={draft.tests} aria-describedby="pexp-tests-hint" onCheckedChange={(tests: boolean) => edit({ tests })} />
        </div>
        <div className="ppub-switch">
          <div>
            <Label htmlFor="pexp-fail-left-out">Fail if any interaction is left out</Label>
            <p className="ppub-hint" id="pexp-fail-left-out-hint">
              In CI, exit non-zero instead of writing a partial collection. Here, what was left out is listed with the result.
            </p>
          </div>
          <Switch id="pexp-fail-left-out" checked={draft.failOnLeftOut} aria-describedby="pexp-fail-left-out-hint" onCheckedChange={(failOnLeftOut: boolean) => onDraft({ ...draft, failOnLeftOut })} />
        </div>
        <div className="ppub-row-actions">
          <Button variant="outline" onClick={() => void run()} disabled={busy} title={busy ? 'The collection is being exported' : undefined} data-testid="pexp-postman-run">
            <Mailbox aria-hidden />
            {busy ? 'Exporting…' : outcome ? 'Export again' : 'Export collection'}
          </Button>
        </div>
        {refusal ? <NoticeList notices={refusal.notices} /> : null}
      </section>

      <aside className="ppub__aside">
        <section className="ppub-card" aria-labelledby="pexp-postman-result">
          <h3 className="ppub-caps" id="pexp-postman-result">
            Result
          </h3>
          {!outcome || !bar ? (
            <p className="ppub-hint">Export the collection to see what it keeps.</p>
          ) : (
            <>
              <div className="pexp-result">
                <span className="pexp-result__glyph" aria-hidden>
                  <Mailbox />
                </span>
                <div className="pexp-result__body">
                  <div className="pexp-result__name">{postmanFileName(outcome)}</div>
                  <div className="ppub-hint">
                    {outcome.counts.exported} request{outcome.counts.exported === 1 ? '' : 's'}
                    {draft.tests ? ', each with the pact’s assertions as tests' : ''} · {sizeLabel(text.length)}
                  </div>
                </div>
              </div>
              <div className="ppub-card__head">
                <span className="ppub-field__label">What the collection keeps</span>
                <span className="ppub-hint" data-testid="pexp-fidelity-label">
                  {bar.kept} of {bar.total} interaction{bar.total === 1 ? '' : 's'}
                </span>
              </div>
              <progress
                className="pexp-bar"
                value={bar.kept}
                max={Math.max(bar.total, 1)}
                aria-label={`${bar.kept} of ${bar.total} interactions included`}
                data-testid="pexp-fidelity"
              />
              {leftOut.length ? (
                <p className="ppub-hint">
                  {leftOut.length} left out: {leftOut.map((notice) => notice.message).join('; ')}.
                </p>
              ) : null}
              <NoticeList notices={outcome.notices} />
              {previewable(text) ? null : (
                <p className="ppub-hint" data-testid="pexp-postman-large">
                  This collection is {sizeLabel(text.length)} — download it to read it.
                </p>
              )}
              <div className="ppub-row-actions">
                <Button onClick={() => saveFile(postmanFileName(outcome), text)} data-testid="pexp-postman-download">
                  <Download aria-hidden />
                  Download collection
                </Button>
              </div>
            </>
          )}
        </section>
        <CommandBlock surfaces={pactCommandSurfaces(action)} unsupported={unsupportedLines(action)} footnote="Replace {tenant} with your workspace’s handle in the REST path." data-testid="pexp-postman-command" />
      </aside>
    </div>
  );
}
