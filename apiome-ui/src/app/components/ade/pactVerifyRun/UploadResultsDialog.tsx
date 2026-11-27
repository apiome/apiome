'use client';

/**
 * **Upload verification results** (PFX-8.9, #7306) — the screen for `apiome pact
 * publish-verification-results`, built to the upload dialog of `docs/mockups/contracts/verify.html`.
 *
 * *Ran a verifier yourself? Attach its report to the pact it verified.* Consumer and pact version
 * (each consumer's newest pact, or a pasted SHA), provider version, report format (**Detect**, Pact
 * verifier JSON, JUnit XML, Schemathesis, Newman, Dredd), then the report — dropped or browsed. The
 * dialog says what Detect will most likely read it as, and refuses at once a file that is neither JSON
 * nor XML. The server reads the report; one it cannot read is refused with the reason and nothing is
 * recorded. **The same, from anywhere** shows the command and the REST call.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleCheck, CircleX, FileUp } from 'lucide-react';
import {
  Button,
  CommandBlock,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { verificationRoute } from '@lib/pact-verification';
import {
  EMPTY_UPLOAD,
  FORMAT_LABELS,
  REPORT_FORMATS,
  guessFormat,
  uploadBody,
  uploadCommandAction,
  uploadHeadline,
  uploadProblems,
  type ReportFormat,
  type UploadAnswer,
  type UploadForm,
} from '@lib/pact-verify-upload';
import { fetchConsumerPacts, uploadResults, type ConsumerPact } from './verifyRunApi';

/** The pact-version choice that means “type a SHA instead”. */
const OTHER_SHA = '__other';

/** Props for {@link UploadResultsDialog}. */
export interface UploadResultsDialogProps {
  open: boolean;
  onClose: () => void;
  /** The provider's handle (`''` until one is chosen on the page). */
  provider: string;
  providerName: string;
  /** What the page already knows: the version being verified and its branch. */
  providerVersion?: string;
  branch?: string;
}

/**
 * A file's text (`File.text()`, or a `FileReader` where a browser lacks it).
 *
 * @param file - The chosen file.
 * @returns Its text.
 */
function readText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

/** The message of one field's problem. */
function problemOf(
  problems: ReturnType<typeof uploadProblems>,
  field: keyof UploadForm,
): string | null {
  return problems.find((p) => p.field === field)?.message ?? null;
}

/**
 * The dialog.
 *
 * @param props - The provider and what the page already knows.
 * @returns The dialog.
 */
export function UploadResultsDialog({
  open,
  onClose,
  provider,
  providerName,
  providerVersion = '',
  branch = '',
}: UploadResultsDialogProps) {
  const [form, setForm] = React.useState<UploadForm>({ ...EMPTY_UPLOAD, providerVersion, branch });
  const [pacts, setPacts] = React.useState<ConsumerPact[] | { error: string } | null>(null);
  const [typedSha, setTypedSha] = React.useState(false);
  const [tried, setTried] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [refusal, setRefusal] = React.useState<{ error: string; pointer: string | null } | null>(
    null,
  );
  const [answer, setAnswer] = React.useState<UploadAnswer | null>(null);
  const [over, setOver] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    if (!open) return undefined;
    setForm({ ...EMPTY_UPLOAD, providerVersion, branch });
    setTried(false);
    setRefusal(null);
    setAnswer(null);
    setTypedSha(false);
    if (!provider) {
      setPacts([]);
      return undefined;
    }
    let live = true;
    setPacts(null);
    void fetchConsumerPacts(provider).then(
      (loaded) => live && setPacts('error' in loaded ? { error: loaded.error } : loaded),
    );
    return () => {
      live = false;
    };
  }, [open, provider, providerVersion, branch]);

  const edit = (patch: Partial<UploadForm>) => setForm((current) => ({ ...current, ...patch }));
  const list = Array.isArray(pacts) ? pacts : [];
  const consumers = Array.from(new Map(list.map((p) => [p.consumer, p.consumerName])).entries());
  const consumerPacts = list.filter((p) => p.consumer === form.consumer);
  const problems = uploadProblems(form);
  const guess = form.file ? guessFormat(form.file.name, form.file.text) : null;
  const shown = (field: keyof UploadForm) => (tried ? problemOf(problems, field) : null);

  const choose = async (file: File | undefined | null) => {
    if (!file) return;
    edit({ file: { name: file.name, text: await readText(file) } });
  };

  const submit = async () => {
    setTried(true);
    setRefusal(null);
    if (problems.length || !provider) return;
    setBusy(true);
    const result = await uploadResults(uploadBody(provider, form));
    setBusy(false);
    if ('error' in result) setRefusal({ error: result.error, pointer: result.pointer });
    else setAnswer(result);
  };

  const action = uploadCommandAction(providerName || provider, form, '');
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      {open ? (
        <DialogContent data-testid="pvu-dialog">
          <DialogHeader>
            <DialogTitle>Upload verification results</DialogTitle>
            <DialogDescription>
              Ran a verifier yourself? Attach its report to the pact it verified.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {answer ? (
              <div className="ppub-result" data-testid="pvu-result">
                <p
                  className={`ppc-result__line ppc-result__line--${answer.success ? 'ok' : 'danger'}`}
                >
                  {answer.success ? (
                    <CircleCheck aria-hidden className="ppub-ix__glyph ppub-ix__glyph--ok" />
                  ) : (
                    <CircleX aria-hidden className="ppub-ix__glyph ppub-ix__glyph--danger" />
                  )}
                  <span data-testid="pvu-headline">{uploadHeadline(answer)}</span>
                </p>
                {answer.notices.length ? (
                  <ul className="pvu-notices" data-testid="pvu-notices">
                    {answer.notices.map((notice) => (
                      <li key={`${notice.pointer}:${notice.reason}`}>
                        <span className="pvl-mono">{notice.pointer || '(report)'}</span> —{' '}
                        {notice.reason}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <>
                {!provider ? (
                  <p
                    className="ppub-hint ppub-hint--danger"
                    role="alert"
                    data-testid="pvu-no-provider"
                  >
                    Choose the provider under test on the page first.
                  </p>
                ) : null}
                <div className="pvu-grid">
                  <div className="ppub-field">
                    <Label htmlFor="pvu-consumer">Consumer</Label>
                    <select
                      id="pvu-consumer"
                      className="ppub-select"
                      value={form.consumer}
                      onChange={(e) => {
                        const newest = list.find((p) => p.consumer === e.target.value);
                        setTypedSha(false);
                        edit({ consumer: e.target.value, sha: newest?.sha ?? '' });
                      }}
                      aria-invalid={Boolean(shown('consumer'))}
                    >
                      <option value="">{pacts === null ? 'Loading…' : 'Choose a consumer'}</option>
                      {consumers.map(([slug, name]) => (
                        <option key={slug} value={slug}>
                          {name}
                        </option>
                      ))}
                    </select>
                    {pacts && !Array.isArray(pacts) ? (
                      <p className="ppub-hint ppub-hint--danger">{pacts.error}</p>
                    ) : null}
                    {shown('consumer') ? (
                      <p className="ppub-hint ppub-hint--danger">{shown('consumer')}</p>
                    ) : null}
                  </div>
                  <div className="ppub-field">
                    <Label htmlFor="pvu-sha">Pact version</Label>
                    <select
                      id="pvu-sha"
                      className="ppub-select"
                      value={typedSha ? OTHER_SHA : form.sha}
                      onChange={(e) => {
                        const other = e.target.value === OTHER_SHA;
                        setTypedSha(other);
                        edit({ sha: other ? '' : e.target.value });
                      }}
                      disabled={!form.consumer}
                    >
                      <option value="">Choose a pact version</option>
                      {consumerPacts.map((p) => (
                        <option key={p.sha} value={p.sha}>
                          {p.sha.slice(0, 6)} · consumer {p.consumerVersion}
                        </option>
                      ))}
                      <option value={OTHER_SHA}>Another pact version…</option>
                    </select>
                    {typedSha ? (
                      <Input
                        aria-label="Pact version SHA"
                        className="ppx__mono"
                        value={form.sha}
                        maxLength={64}
                        placeholder="The pact's 64-character SHA-256"
                        onChange={(e) => edit({ sha: e.target.value })}
                        data-testid="pvu-sha-input"
                      />
                    ) : null}
                    {shown('sha') ? (
                      <p className="ppub-hint ppub-hint--danger">{shown('sha')}</p>
                    ) : null}
                  </div>
                  <div className="ppub-field">
                    <Label htmlFor="pvu-version">Provider version</Label>
                    <Input
                      id="pvu-version"
                      className="ppx__mono"
                      value={form.providerVersion}
                      maxLength={255}
                      placeholder="2.7.0+9f31c20"
                      onChange={(e) => edit({ providerVersion: e.target.value })}
                      aria-invalid={Boolean(shown('providerVersion'))}
                    />
                    {shown('providerVersion') ? (
                      <p className="ppub-hint ppub-hint--danger">{shown('providerVersion')}</p>
                    ) : null}
                  </div>
                  <div className="ppub-field">
                    <Label htmlFor="pvu-format">Report format</Label>
                    <select
                      id="pvu-format"
                      className="ppub-select"
                      value={form.format}
                      onChange={(e) => edit({ format: e.target.value as ReportFormat })}
                    >
                      {REPORT_FORMATS.map((format) => (
                        <option key={format} value={format}>
                          {FORMAT_LABELS[format]}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div
                  className={`pvu-drop${over ? ' pvu-drop--over' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOver(true);
                  }}
                  onDragLeave={() => setOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setOver(false);
                    void choose(e.dataTransfer.files?.[0]);
                  }}
                  data-testid="pvu-drop"
                >
                  <FileUp aria-hidden />
                  {form.file ? (
                    <span className="pvu-drop__name">{form.file.name}</span>
                  ) : (
                    <span>Drop the report here</span>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => fileInput.current?.click()}
                    data-testid="pvu-browse"
                  >
                    Browse
                  </Button>
                  <input
                    ref={fileInput}
                    type="file"
                    className="pvu-file"
                    accept=".json,.xml,.ndjson,.jsonl,application/json,application/xml,text/xml"
                    aria-label="The report"
                    onChange={(e) => void choose(e.target.files?.[0])}
                    data-testid="pvu-file"
                  />
                </div>
                {guess ? (
                  <p
                    className={`ppub-hint${guess.format ? '' : ' ppub-hint--danger'}`}
                    data-testid="pvu-guess"
                  >
                    {guess.sentence}
                    {guess.format &&
                    form.format !== 'auto' &&
                    form.format !== guess.format &&
                    !(form.format === 'newman' && guess.format === 'junit')
                      ? ` You chose ${FORMAT_LABELS[form.format]}; the server will refuse the report if it is not one.`
                      : ''}
                  </p>
                ) : null}
                {/* An unreadable file is already named by the guess above; any other file problem shows here. */}
                {shown('file') && (!guess || guess.format) ? (
                  <p className="ppub-hint ppub-hint--danger" data-testid="pvu-file-problem">
                    {shown('file')}
                  </p>
                ) : null}

                <details className="ppub-more">
                  <summary>More options</summary>
                  <div className="pvu-grid">
                    <div className="ppub-field">
                      <Label htmlFor="pvu-branch">Branch</Label>
                      <Input
                        id="pvu-branch"
                        value={form.branch}
                        maxLength={255}
                        onChange={(e) => edit({ branch: e.target.value })}
                      />
                    </div>
                    <div className="ppub-field">
                      <Label htmlFor="pvu-build">Build URL</Label>
                      <Input
                        id="pvu-build"
                        value={form.buildUrl}
                        maxLength={2000}
                        placeholder="https://ci.example.com/builds/77"
                        onChange={(e) => edit({ buildUrl: e.target.value })}
                      />
                      {shown('buildUrl') ? (
                        <p className="ppub-hint ppub-hint--danger">{shown('buildUrl')}</p>
                      ) : null}
                    </div>
                    <div className="ppub-field">
                      <Label htmlFor="pvu-tags">Tags</Label>
                      <Input
                        id="pvu-tags"
                        value={form.tags}
                        placeholder="staging, rc"
                        onChange={(e) => edit({ tags: e.target.value })}
                      />
                    </div>
                    <div className="ppub-field">
                      <Label htmlFor="pvu-verifier">Verifier</Label>
                      <Input
                        id="pvu-verifier"
                        value={form.verifier}
                        maxLength={255}
                        placeholder="From the report"
                        onChange={(e) => edit({ verifier: e.target.value })}
                      />
                    </div>
                    <div className="ppub-field">
                      <Label htmlFor="pvu-verifier-version">Verifier version</Label>
                      <Input
                        id="pvu-verifier-version"
                        value={form.verifierVersion}
                        maxLength={255}
                        onChange={(e) => edit({ verifierVersion: e.target.value })}
                      />
                    </div>
                  </div>
                </details>

                {refusal ? (
                  <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pvu-refusal">
                    {refusal.error}
                    {refusal.pointer ? ` (at ${refusal.pointer})` : ''} Nothing was recorded.
                  </p>
                ) : null}

                <CommandBlock
                  surfaces={pactCommandSurfaces(action)}
                  unsupported={unsupportedLines(action)}
                  headingLevel={3}
                  data-testid="pvu-command"
                />
              </>
            )}
          </DialogBody>
          <DialogFooter>
            {answer ? (
              <>
                <Button variant="outline" onClick={onClose}>
                  Close
                </Button>
                <Button asChild>
                  <Link href={verificationRoute(provider, form.consumer)}>
                    Open the Verification page
                  </Link>
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  onClick={() => void submit()}
                  disabled={busy || !provider}
                  data-testid="pvu-submit"
                >
                  {busy ? 'Uploading…' : 'Upload results'}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export default UploadResultsDialog;
