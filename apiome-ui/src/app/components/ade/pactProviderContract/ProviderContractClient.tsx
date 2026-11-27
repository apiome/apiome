'use client';

/**
 * **Publish a provider contract** — `/ade/dashboard/pacts/provider-contracts/new` (PFX-8.6, #7303).
 *
 * The screen for `apiome pact publish-provider-contract`, built to
 * `docs/mockups/contracts/provider-contract.html`:
 *
 * 1. **The contract** — *A project version* (rendered from the canonical model, `apiomeVersion`),
 *    *Upload* (OpenAPI 3.x or AsyncAPI 2.x / 3.x, JSON or YAML; the format pill says what was read,
 *    or why it cannot be published) or *URL* (read once by REST, then published as those bytes).
 * 2. **Whose version this is** — provider, provider version, branch, tags; build URL under *More options*.
 * 3. **Evidence the provider really behaves this way** — five option cards, each with its strength
 *    and its inputs: run the hosted verifier now, attach a report, reuse a recorded run, the
 *    pipeline's exit code, or none yet.
 *
 * The aside is **If you publish now**: the verdict per consumer pact before anything is saved
 * (`POST …/check`, refreshed as the form settles), **Nobody uses** (operations no pact touches),
 * then **The same, from anywhere**. **Compare only** runs the check and publishes nothing;
 * **Publish contract** publishes — after **Run it now**, only when the run passed (otherwise the
 * failing operations are listed and nothing is stored). The result dialog lists the verdicts
 * recorded, says what was notified, and links to can-i-deploy.
 *
 * **Standing sources** (PFX-8.7, #7304): **Do this on every publish** on the project tab makes each
 * published version of the project the provider's contract (saved with the publish; a provider
 * bound to no project is bound to it), and the *Repository* tab follows a file of a registered
 * repository — **Follow this file** saves it, and every push publishes it with the commit as the
 * version. Under the provider, **Published automatically** says where its contract already comes
 * from, with REST's warnings and a way to stop each source (new publishes only).
 *
 * A role without `pacts:create` sees the explanation and the command block only.
 */

import * as React from 'react';
import Link from 'next/link';
import { FileCheck2, FileUp, FolderKanban, GitBranch, Link2, Upload } from 'lucide-react';
import { Alert, Badge, Button, CommandBlock, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_CRUMBS, CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  EMPTY_FORM,
  UNVERIFIED_RULE,
  checkRequest,
  conflictSentence,
  detectContract,
  formProblems,
  providerContractCommandAction,
  publishRequest,
  type CheckAnswer,
  type ContractRequestBody,
  type ContractSource,
  type FormProblem,
  type PickedText,
  type ProviderContractForm,
  type PublishAnswer,
} from '@lib/pact-provider-contract';
import { REPOSITORY_NO_PREVIEW, followedNotice, type ContractSources, type RepositoryChoice, type SourcesPatch } from '@lib/pact-contract-sources';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { fetchProjects, type ProjectChoice } from '../pactPublish/publishApi';
import { ContractResultDialog, EvidenceOptions, FailedRunCard, PublishNowAside, type AsideState } from './ProviderContractPanels';
import { FollowProjectToggle, RepositoryFields, StandingSourcesNote } from './StandingSources';
import {
  checkProviderContract,
  fetchReports,
  fetchRepositories,
  fetchSources,
  fetchTargets,
  fetchVersions,
  publishProviderContract,
  saveSources,
  reportLabel,
  type ReportChoice,
  type TargetChoice,
  type VersionChoice,
} from './providerContractApi';

/** The permission publishing needs. */
const WRITE_PERMISSION = 'pacts:create';

/** How long the form must be still before the aside is refreshed. */
const CHECK_DELAY_MS = 900;

/** A list being read: `null` while loading, the rows, or why it could not be read. */
type Loaded<T> = T[] | null | { error: string };

/**
 * A file the user dropped or picked, read as text.
 *
 * @param list - The files.
 * @returns The first one, or `null`.
 */
async function firstFile(list: FileList | null | undefined): Promise<PickedText | null> {
  const file = list?.[0];
  return file ? { name: file.name, text: await file.text() } : null;
}

/** The problem of one field, for its hint. */
function problemOf(problems: FormProblem[], field: keyof ProviderContractForm): string | null {
  return problems.find((p) => p.field === field)?.message ?? null;
}

/**
 * A drop zone with a Browse button: one file.
 *
 * @param props - Its label, hint, what it accepts, and what to do with the file.
 * @returns The zone.
 */
function DropFile({
  id,
  title,
  hint,
  accept,
  picked,
  small,
  onPick,
}: {
  id: string;
  title: string;
  hint: string;
  accept: string;
  picked: PickedText | null;
  small?: boolean;
  onPick: (file: PickedText | null) => void;
}) {
  const input = React.useRef<HTMLInputElement | null>(null);
  return (
    <>
      <div
        className={small ? 'ppub-drop ppc-drop--small' : 'ppub-drop'}
        role="button"
        tabIndex={0}
        aria-label={`${title}, or press Enter to browse`}
        onClick={() => input.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          void firstFile(event.dataTransfer.files).then(onPick);
        }}
        data-testid={`${id}-drop`}
      >
        <Upload aria-hidden className="ppub-drop__glyph" />
        <span className="ppub-drop__title">{picked ? picked.name : title}</span>
        <span className="ppub-drop__hint">{hint}</span>
      </div>
      <div className="ppub-row-actions">
        <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
          <FileUp aria-hidden />
          Browse files
        </Button>
        {picked ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => onPick(null)}>
            Remove
          </Button>
        ) : null}
      </div>
      <input
        ref={input}
        id={id}
        type="file"
        accept={accept}
        className="ppub-file-input"
        aria-label={title}
        onChange={(event) => {
          const files = event.target.files;
          void firstFile(files).then(onPick);
          event.target.value = '';
        }}
        data-testid={`${id}-input`}
      />
    </>
  );
}

/**
 * The page.
 *
 * @returns The form, the aside and the result dialog.
 */
export function ProviderContractClient() {
  const permissions = useMyPermissions();
  const canWrite = permissions.status === 'ready' && permissions.can(WRITE_PERMISSION);
  const readOnly = permissions.status !== 'loading' && !canWrite;

  const [form, setForm] = React.useState<ProviderContractForm>(EMPTY_FORM);
  const [projects, setProjects] = React.useState<Loaded<ProjectChoice>>(null);
  const [versions, setVersions] = React.useState<Loaded<VersionChoice>>(null);
  const [targets, setTargets] = React.useState<Loaded<TargetChoice>>(null);
  const [reports, setReports] = React.useState<Loaded<ReportChoice>>(null);
  const [aside, setAside] = React.useState<AsideState>({ kind: 'idle' });
  const [checked, setChecked] = React.useState<{ key: string; answer: CheckAnswer } | null>(null);
  const [busy, setBusy] = React.useState<'check' | 'publish' | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [showProblems, setShowProblems] = React.useState(false);
  const [failedRun, setFailedRun] = React.useState<Extract<PublishAnswer, { published: false }> | null>(null);
  const [result, setResult] = React.useState<Extract<PublishAnswer, { published: true }> | null>(null);
  const [repositories, setRepositories] = React.useState<Loaded<RepositoryChoice>>(null);
  const [sources, setSources] = React.useState<ContractSources | null>(null);
  const [savingSources, setSavingSources] = React.useState(false);
  const [followLine, setFollowLine] = React.useState<{ tone: 'ok' | 'warn'; text: string } | null>(null);
  const following = form.source === 'repository';

  const edit = (patch: Partial<ProviderContractForm>) => {
    setForm((current) => ({ ...current, ...patch }));
    setProblem(null);
    setFailedRun(null);
  };

  const project = Array.isArray(projects) ? projects.find((p) => p.slug === form.project) ?? null : null;

  // Projects, once.
  React.useEffect(() => {
    if (!canWrite || projects !== null) return;
    let live = true;
    void fetchProjects().then((answer) => live && setProjects('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, [canWrite, projects]);

  // The chosen project's versions.
  React.useEffect(() => {
    if (!project) return;
    let live = true;
    setVersions(null);
    void fetchVersions(project.id).then((answer) => live && setVersions('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, [project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // The targets, when Run it now is chosen.
  React.useEffect(() => {
    if (!canWrite || form.evidence !== 'run' || targets !== null) return;
    let live = true;
    void fetchTargets().then((answer) => live && setTargets('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, [canWrite, form.evidence, targets]);

  // The recorded runs of the chosen version, when Reuse is chosen.
  React.useEffect(() => {
    if (!canWrite || form.evidence !== 'reuse' || form.source !== 'project' || !form.project || !form.version) return;
    let live = true;
    setReports(null);
    void fetchReports(form.project, form.version).then((answer) => live && setReports('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, [canWrite, form.evidence, form.source, form.project, form.version]);

  // The registered repositories, when the Repository tab is chosen.
  React.useEffect(() => {
    if (!canWrite || !following || repositories !== null) return;
    let live = true;
    void fetchRepositories().then((answer) => live && setRepositories('error' in answer ? { error: answer.error } : answer));
    return () => {
      live = false;
    };
  }, [canWrite, following, repositories]);

  // Where the named provider's contract already comes from, once its name has settled.
  const providerName = form.provider.trim();
  React.useEffect(() => {
    setSources(null);
    if (!canWrite || !providerName) return;
    let live = true;
    const timer = setTimeout(() => {
      void fetchSources(providerName).then((answer) => live && setSources(answer && !('error' in answer) ? answer : null));
    }, CHECK_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [canWrite, providerName]);

  /** Change the provider's standing sources; answers REST's stored sources, or why not. */
  const changeSources = async (patch: SourcesPatch): Promise<ContractSources | { error: string }> => {
    setSavingSources(true);
    const answer = await saveSources(providerName, patch);
    setSavingSources(false);
    if ('error' in answer) return { error: answer.error };
    setSources(answer);
    return answer;
  };

  const stopSource = async (patch: SourcesPatch, what: string) => {
    setNotice(null);
    const answer = await changeSources(patch);
    if ('error' in answer) return setProblem(answer.error);
    setProblem(null);
    setNotice(`${what} New publishes stop; contracts already published stay.`);
  };

  const problems = formProblems(form);
  // The check does not depend on the evidence inputs that Run it now adds later, or on tags / build URL.
  // A repository source publishes nothing now, so there is nothing to check yet.
  const checkBody = problems.length === 0 && !following ? checkRequest(form) : null;
  const checkKey = checkBody ? JSON.stringify(checkBody) : '';

  const runCheck = React.useCallback(async (body: ContractRequestBody, key: string): Promise<CheckAnswer | null> => {
    setAside({ kind: 'checking' });
    const answer = await checkProviderContract(body);
    if ('error' in answer) {
      setAside({ kind: 'failed', error: answer.error });
      setChecked(null);
      return null;
    }
    setAside({ kind: 'ready', answer });
    setChecked({ key, answer });
    return answer;
  }, []);

  // The live aside: refresh once the form has been still for a moment (a URL is read only on demand).
  React.useEffect(() => {
    if (!canWrite || !checkBody || form.source === 'url' || checked?.key === checkKey) return;
    const timer = setTimeout(() => void runCheck(checkBody, checkKey), CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [canWrite, checkKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const compareOnly = async () => {
    setShowProblems(true);
    setNotice(null);
    if (!checkBody) return setProblem(problems[0]?.message ?? 'Fill in the form first.');
    setBusy('check');
    const answer = await runCheck(checkBody, checkKey);
    setBusy(null);
    if (!answer) return;
    if (!answer.publishable) return setProblem(conflictSentence(form.providerVersion.trim()));
    setNotice('Compared and nothing was published. The verdicts are beside the form.');
  };

  const follow = async () => {
    setShowProblems(true);
    setNotice(null);
    if (problems.length) return setProblem(problems[0].message);
    setBusy('publish');
    const answer = await changeSources({
      repository: { repositoryId: form.repositoryId, path: form.repositoryPath.trim(), branch: form.repositoryBranch.trim() },
    });
    setBusy(null);
    if ('error' in answer) return setProblem(answer.error);
    setProblem(null);
    setNotice(followedNotice(answer));
  };

  const publish = async () => {
    if (following) return follow();
    setShowProblems(true);
    setNotice(null);
    setFailedRun(null);
    setFollowLine(null);
    if (problems.length) return setProblem(problems[0].message);
    setBusy('publish');
    let answer = checked?.key === checkKey ? checked.answer : null;
    // A URL is published as the bytes a check read from it, so read it first when needed.
    if (form.source === 'url' && !answer?.fetched && checkBody) answer = await runCheck(checkBody, checkKey);
    if (form.source === 'url' && !answer?.fetched) {
      setBusy(null);
      return setProblem('The specification could not be read from the URL, so nothing was published. The reason is beside the form.');
    }
    if (answer && !answer.publishable) {
      setBusy(null);
      return setProblem(conflictSentence(form.providerVersion.trim()));
    }
    const published = await publishProviderContract(publishRequest(form, answer?.fetched?.content ?? null));
    setBusy(null);
    if ('error' in published) {
      return setProblem(published.status === 409 ? conflictSentence(form.providerVersion.trim()) : published.error);
    }
    if (!published.published) {
      setFailedRun(published);
      return setProblem(published.message);
    }
    // Do this on every publish: saved once the provider exists (the publish registered it).
    if (form.source === 'project' && form.followProject) {
      const followed = await changeSources({ onProjectPublish: true, bindProject: form.project.trim() });
      setFollowLine(
        'error' in followed
          ? { tone: 'warn', text: `Not published on every publish: ${followed.error}` }
          : { tone: 'ok', text: `Each published version of ${project?.name ?? form.project} now becomes ${published.provider}’s contract.` },
      );
    }
    setResult(published);
  };

  const reset = () => {
    setResult(null);
    setForm(EMPTY_FORM);
    setChecked(null);
    setAside({ kind: 'idle' });
    setShowProblems(false);
    setProblem(null);
    setNotice(null);
    setFollowLine(null);
  };

  const detected = form.source === 'upload' && form.file ? detectContract(form.file.text, form.file.name) : null;
  const format = detected?.format ?? (checked?.answer.format && checked.key === checkKey ? checked.answer.format : null);
  const hint = (field: keyof ProviderContractForm) => {
    // An uploaded file's problem shows at once (the mockup's *Unreadable document*); the rest after a try.
    const message = showProblems || (field === 'file' && form.file) ? problemOf(problems, field) : null;
    return message ? (
      <p className="ppub-hint ppub-hint--danger" data-testid={`ppc-problem-${field}`}>
        {message}
      </p>
    ) : null;
  };

  const action = providerContractCommandAction(form, '');
  const statusLine = problem ?? notice;

  return (
    <Page>
      <PageHeader
        title="Publish a provider contract"
        breadcrumb={[...CONTRACTS_CRUMBS, { label: 'Publish a provider contract' }]}
        description="Say what a provider promises, show that it is true, and see which consumers it would break — before it is recorded."
        tabs={<ContractsTabs active="overview" />}
        actions={
          canWrite ? (
            <>
              <Button variant="outline" asChild>
                <Link href={CONTRACTS_ROUTE}>Cancel</Link>
              </Button>
              <Button
                variant="outline"
                onClick={() => void compareOnly()}
                disabled={busy !== null || following}
                title={following ? REPOSITORY_NO_PREVIEW : 'Compares and publishes nothing'}
                data-testid="ppc-compare"
              >
                {busy === 'check' ? 'Comparing…' : 'Compare only'}
              </Button>
            </>
          ) : undefined
        }
        primaryAction={
          canWrite ? (
            <Button onClick={() => void publish()} disabled={busy !== null || Boolean(detected?.problem)} data-testid="ppc-publish">
              {following ? <GitBranch aria-hidden /> : <FileCheck2 aria-hidden />}
              {following
                ? busy === 'publish'
                  ? 'Saving…'
                  : 'Follow this file'
                : busy === 'publish'
                  ? form.evidence === 'run'
                    ? 'Verifying, then publishing…'
                    : 'Publishing…'
                  : 'Publish contract'}
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="ppub" data-testid="pact-provider-contract">
          {statusLine ? (
            <Alert variant={problem ? 'danger' : 'warn'} data-testid="ppc-status">
              {statusLine}
            </Alert>
          ) : null}
          <div className="ppub__split">
            <div className="ppub__main">
              {readOnly ? (
                <section className="ppub-card ppub-readonly" aria-labelledby="ppc-readonly-title" data-testid="ppc-readonly">
                  <h2 className="ppub-card__title" id="ppc-readonly-title">
                    {permissions.status === 'error' ? 'Your permissions could not be read' : 'Your role cannot publish provider contracts'}
                  </h2>
                  <p className="ppub-card__lead">
                    Publishing needs the <b>Pacts</b> create permission, which the <b>Editor</b>, <b>Admin</b> and <b>Owner</b> roles hold. Ask
                    a workspace owner for it, or publish from your build with the command beside — a build’s API key carries its own
                    permissions.
                  </p>
                </section>
              ) : null}
              {failedRun ? <FailedRunCard answer={failedRun} /> : null}
              {canWrite ? (
                <>
                  <section className="ppub-card" aria-labelledby="ppc-step-1">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppc-step-1">
                        <span className="ppub-step" aria-hidden>
                          1
                        </span>
                        The contract
                      </h2>
                      {format ? (
                        <Badge variant="accent" data-testid="ppc-format">
                          {format}
                        </Badge>
                      ) : null}
                    </div>
                    <Tabs value={form.source} onValueChange={(value) => edit({ source: value as ContractSource })}>
                      <TabsList aria-label="Contract source">
                        <TabsTrigger value="project">
                          <FolderKanban aria-hidden className="ppub-tab__glyph" />A project version
                        </TabsTrigger>
                        <TabsTrigger value="upload">
                          <FileUp aria-hidden className="ppub-tab__glyph" />
                          Upload
                        </TabsTrigger>
                        <TabsTrigger value="url">
                          <Link2 aria-hidden className="ppub-tab__glyph" />
                          URL
                        </TabsTrigger>
                        <TabsTrigger value="repository">
                          <GitBranch aria-hidden className="ppub-tab__glyph" />
                          Repository
                        </TabsTrigger>
                      </TabsList>
                      <TabsContent value="project" className="ppub-panel">
                        {projects && 'error' in projects ? <p className="ppub-hint ppub-hint--danger">{projects.error}</p> : null}
                        <div className="ppub-grid">
                          <div className="ppub-field">
                            <Label htmlFor="ppc-project">Project</Label>
                            <select
                              id="ppc-project"
                              className="ppub-select"
                              value={form.project}
                              onChange={(event) => edit({ project: event.target.value, version: '', reportId: '' })}
                            >
                              <option value="">{projects === null ? 'Loading projects…' : 'Choose a project'}</option>
                              {(Array.isArray(projects) ? projects : []).map((p) => (
                                <option key={p.id} value={p.slug}>
                                  {p.name}
                                </option>
                              ))}
                            </select>
                            {hint('project')}
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppc-version">Version</Label>
                            <select
                              id="ppc-version"
                              className="ppub-select"
                              value={form.version}
                              disabled={!form.project}
                              onChange={(event) => edit({ version: event.target.value, reportId: '' })}
                            >
                              <option value="">{form.project && versions === null ? 'Loading versions…' : 'Choose a version'}</option>
                              {(Array.isArray(versions) ? versions : []).map((v) => (
                                <option key={v.label} value={v.label}>
                                  {v.label} · {v.published ? 'published' : 'draft'}
                                </option>
                              ))}
                            </select>
                            {versions && 'error' in versions ? <p className="ppub-hint ppub-hint--danger">{versions.error}</p> : null}
                            {hint('version')}
                          </div>
                        </div>
                        <p className="ppub-hint">Rendered from the canonical model as OpenAPI 3.1, the same document the version’s schema download serves.</p>
                        <FollowProjectToggle
                          checked={form.followProject}
                          projectName={project?.name ?? null}
                          providerName={form.provider}
                          onChange={(followProject) => edit({ followProject })}
                        />
                      </TabsContent>
                      <TabsContent value="upload" className="ppub-panel">
                        <DropFile
                          id="ppc-file"
                          title="Drop an OpenAPI or AsyncAPI document"
                          hint=".yaml · .yml · .json · the format is detected"
                          accept=".yaml,.yml,.json,application/json,application/yaml"
                          picked={form.file}
                          onPick={(file) => edit({ file })}
                        />
                        {hint('file')}
                      </TabsContent>
                      <TabsContent value="url" className="ppub-panel">
                        <div className="ppub-field">
                          <Label htmlFor="ppc-url">Specification URL</Label>
                          <Input
                            id="ppc-url"
                            value={form.url}
                            maxLength={2048}
                            placeholder="https://api.example.com/openapi.yaml"
                            aria-describedby="ppc-url-hint"
                            onChange={(event) => edit({ url: event.target.value })}
                          />
                          <p className="ppub-hint" id="ppc-url-hint">
                            Read once, now, by Apiome (public addresses only) — then published as those exact bytes. <b>Compare only</b> reads it.
                          </p>
                          {checked?.answer.fetched && checked.key === checkKey ? (
                            <p className="ppub-hint" data-testid="ppc-fetched">
                              Read {checked.answer.fetched.bytes.toLocaleString()} bytes from {checked.answer.fetched.url}.
                            </p>
                          ) : null}
                          {hint('url')}
                        </div>
                      </TabsContent>
                      <TabsContent value="repository" className="ppub-panel">
                        <RepositoryFields form={form} edit={edit} repositories={repositories} hint={hint} />
                      </TabsContent>
                    </Tabs>
                  </section>

                  <section className="ppub-card" aria-labelledby="ppc-step-2">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppc-step-2">
                        <span className="ppub-step" aria-hidden>
                          2
                        </span>
                        Whose version this is
                      </h2>
                    </div>
                    <div className="ppub-grid">
                      <div className="ppub-field">
                        <Label htmlFor="ppc-provider">Provider</Label>
                        <Input
                          id="ppc-provider"
                          value={form.provider}
                          maxLength={255}
                          placeholder="Billing Service"
                          aria-describedby="ppc-provider-hint"
                          onChange={(event) => edit({ provider: event.target.value })}
                        />
                        <p className="ppub-hint" id="ppc-provider-hint">
                          The pacticipant consumers name in their pacts; registered on first publish.
                        </p>
                        {hint('provider')}
                      </div>
                      {following ? (
                        <p className="ppub-hint ppc-span" data-testid="ppc-push-version">
                          Each push is a provider version: its commit, on the pushed branch.
                        </p>
                      ) : (
                        <>
                      <div className="ppub-field">
                        <Label htmlFor="ppc-provider-version">Provider version</Label>
                        <Input
                          id="ppc-provider-version"
                          className="ppx__mono"
                          value={form.providerVersion}
                          maxLength={255}
                          placeholder="2.7.0+9f31c20"
                          onChange={(event) => edit({ providerVersion: event.target.value })}
                        />
                        {hint('providerVersion')}
                      </div>
                      <div className="ppub-field">
                        <Label htmlFor="ppc-branch">Branch</Label>
                        <Input id="ppc-branch" value={form.branch} maxLength={255} placeholder="main" onChange={(event) => edit({ branch: event.target.value })} />
                        {hint('branch')}
                      </div>
                      <div className="ppub-field">
                        <Label htmlFor="ppc-tags">Tags (optional)</Label>
                        <Input id="ppc-tags" value={form.tags} placeholder="comma separated" onChange={(event) => edit({ tags: event.target.value })} />
                        {hint('tags')}
                      </div>
                        </>
                      )}
                    </div>
                    <StandingSourcesNote
                      sources={sources}
                      busy={savingSources}
                      onStopProject={() => void stopSource({ onProjectPublish: false }, 'Project versions are no longer published as the contract.')}
                      onStopRepository={() => void stopSource({ repository: null }, 'The file is no longer followed.')}
                    />
                    {following ? null : (
                    <details className="ppub-more">
                      <summary>More options</summary>
                      <div className="ppub-more__body">
                        <div className="ppub-field">
                          <Label htmlFor="ppc-build-url">Build URL</Label>
                          <Input
                            id="ppc-build-url"
                            value={form.buildUrl}
                            maxLength={2048}
                            placeholder="https://ci.example.com/builds/4821"
                            onChange={(event) => edit({ buildUrl: event.target.value })}
                          />
                          {hint('buildUrl')}
                        </div>
                      </div>
                    </details>
                    )}
                  </section>

                  {following ? null : (
                  <section className="ppub-card" aria-labelledby="ppc-step-3">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppc-step-3">
                        <span className="ppub-step" aria-hidden>
                          3
                        </span>
                        Evidence the provider really behaves this way
                      </h2>
                    </div>
                    <p className="ppub-card__lead">A spec is a claim. Verdicts built on it are marked with how well the claim is backed.</p>
                    <EvidenceOptions value={form.evidence} onChange={(evidence) => edit({ evidence })}>
                      {form.evidence === 'run' ? (
                        <div className="ppub-grid">
                          <div className="ppub-field">
                            <Label htmlFor="ppc-target">Target</Label>
                            <select id="ppc-target" className="ppub-select" value={form.target} onChange={(event) => edit({ target: event.target.value })}>
                              <option value="">{targets === null ? 'Loading targets…' : 'Choose a target'}</option>
                              {(Array.isArray(targets) ? targets : []).map((t) => (
                                <option key={t.slug} value={t.slug}>
                                  {t.environment ? `${t.environment} — ` : ''}
                                  {t.baseUrl || t.name}
                                </option>
                              ))}
                            </select>
                            {targets && 'error' in targets ? <p className="ppub-hint ppub-hint--danger">{targets.error}</p> : null}
                            {hint('target')}
                          </div>
                          <p className="ppub-hint ppc-span">
                            Signs in with the credential the target names. Read-only operations by default. A run that does not pass publishes
                            nothing and lists the failing operations.
                          </p>
                        </div>
                      ) : null}
                      {form.evidence === 'report' ? (
                        <>
                          <DropFile
                            id="ppc-report"
                            small
                            title="Drop a report — JUnit XML, Newman JSON or Schemathesis NDJSON"
                            hint=".xml · .json · .ndjson · read per test"
                            accept=".xml,.json,.ndjson,.jsonl,.txt"
                            picked={form.report}
                            onPick={(report) => edit({ report })}
                          />
                          {hint('report')}
                          <div className="ppub-grid ppc-grid-3">
                            <div className="ppub-field">
                              <Label htmlFor="ppc-report-verifier">Verifier (optional)</Label>
                              <Input id="ppc-report-verifier" value={form.verifier} placeholder="schemathesis" onChange={(event) => edit({ verifier: event.target.value })} />
                            </div>
                            <div className="ppub-field">
                              <Label htmlFor="ppc-report-verifier-version">Verifier version (optional)</Label>
                              <Input
                                id="ppc-report-verifier-version"
                                className="ppx__mono"
                                value={form.verifierVersion}
                                placeholder="3.39.2"
                                onChange={(event) => edit({ verifierVersion: event.target.value })}
                              />
                            </div>
                            <div className="ppub-field">
                              <Label htmlFor="ppc-report-exit">Exit code (optional)</Label>
                              <Input
                                id="ppc-report-exit"
                                className="ppx__mono"
                                inputMode="numeric"
                                value={form.exitCode}
                                placeholder="0"
                                onChange={(event) => edit({ exitCode: event.target.value })}
                              />
                              {hint('exitCode')}
                            </div>
                          </div>
                        </>
                      ) : null}
                      {form.evidence === 'reuse' ? (
                        <div className="ppub-field">
                          <Label htmlFor="ppc-reuse">Run</Label>
                          {form.source === 'project' ? (
                            <select id="ppc-reuse" className="ppub-select" value={form.reportId} onChange={(event) => edit({ reportId: event.target.value })}>
                              <option value="">
                                {!form.version
                                  ? 'Choose the version first'
                                  : reports === null
                                    ? 'Loading runs…'
                                    : Array.isArray(reports) && !reports.length
                                      ? 'No run recorded for this version'
                                      : 'Choose a run'}
                              </option>
                              {(Array.isArray(reports) ? reports : []).map((r) => (
                                <option key={r.id} value={r.id}>
                                  {reportLabel(r)}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <Input
                              id="ppc-reuse"
                              className="ppx__mono"
                              value={form.reportId}
                              placeholder="The provider-verification report id"
                              onChange={(event) => edit({ reportId: event.target.value })}
                            />
                          )}
                          {reports && 'error' in reports ? <p className="ppub-hint ppub-hint--danger">{reports.error}</p> : null}
                          <p className="ppub-hint">A run of another version is read as inconclusive, not as proof.</p>
                          {hint('reportId')}
                        </div>
                      ) : null}
                      {form.evidence === 'exit' ? (
                        <div className="ppub-grid ppc-grid-3">
                          <div className="ppub-field">
                            <Label htmlFor="ppc-verifier">Verifier</Label>
                            <Input id="ppc-verifier" value={form.verifier} placeholder="schemathesis" onChange={(event) => edit({ verifier: event.target.value })} />
                            {hint('verifier')}
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppc-verifier-version">Version</Label>
                            <Input
                              id="ppc-verifier-version"
                              className="ppx__mono"
                              value={form.verifierVersion}
                              placeholder="3.39.2"
                              onChange={(event) => edit({ verifierVersion: event.target.value })}
                            />
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppc-exit">Exit code</Label>
                            <Input
                              id="ppc-exit"
                              className="ppx__mono"
                              inputMode="numeric"
                              value={form.exitCode}
                              placeholder="0"
                              onChange={(event) => edit({ exitCode: event.target.value })}
                            />
                            {hint('exitCode')}
                          </div>
                        </div>
                      ) : null}
                      {form.evidence === 'none' ? (
                        <p className="ppc-callout" data-testid="ppc-unverified-rule">
                          {UNVERIFIED_RULE}
                        </p>
                      ) : null}
                    </EvidenceOptions>
                  </section>
                  )}
                </>
              ) : null}
            </div>
            <aside className="ppub__aside" aria-label="If you publish now, and the same from anywhere">
              {canWrite ? (
                <PublishNowAside
                  state={following ? { kind: 'idle' } : aside}
                  idleNote={following ? REPOSITORY_NO_PREVIEW : null}
                  version={form.providerVersion.trim()}
                  evidenceNote={form.evidence === 'run' ? 'read from the hosted run when you publish — until then the verdicts read unverified.' : null}
                />
              ) : null}
              <CommandBlock
                className="ppub-command-block"
                surfaces={pactCommandSurfaces(action)}
                unsupported={unsupportedLines(action)}
                footnote="Replace {tenant} with your workspace’s handle in the REST path. Add --fail-on-unverified to fail the build when the contract has no passing evidence."
                data-testid="ppc-command-block"
              />
            </aside>
          </div>
          <ContractResultDialog answer={result} followLine={followLine} onClose={() => setResult(null)} onAgain={reset} />
        </div>
      </PageBody>
    </Page>
  );
}
