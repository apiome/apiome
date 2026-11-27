'use client';

/**
 * **Publish a consumer pact** — `/ade/dashboard/pacts/publish` (PFX-8.3, #7300).
 *
 * Built to `docs/mockups/contracts/publish-pact.html`:
 *
 * 1. **The pact** — *Upload* (several files or a whole `pacts/` folder; each row shows its pair,
 *    specification, interaction count and kinds, or why it will not be published), *Paste*,
 *    *Derive from a project* (`apiome pact publish-consumer-contract`: the consumer's declared
 *    surface becomes the pact), or *Write interactions* (PFX-8.5, #7302: the interaction editor
 *    writes a Pact v4 document, which then publishes as any other).
 * 2. **Whose version this is** — consumer version, branch, tags, *Fill from the linked repository*,
 *    and under *More options* the build URL, *Merge* (refused with the CLI's reason) and *Also tag
 *    with the branch name*.
 * 3. **Check it before it counts** (PFX-8.4, #7301) — *Compare with* one chip per provider version
 *    (the provider's main branch, each environment, the latest draft, or any version typed in).
 * 4. The aside — the result of the check per pact (one pill per provider version, match / differs /
 *    not in spec per interaction, the difference drawer), then **The same, from anywhere**.
 *
 * **Check only** compares each pact with the chosen provider versions (`POST …/pacts/check`) and reads
 * what each pact's version already published, marking every row new, unchanged or a conflict; it
 * writes nothing. **Publish pact** sends one request per consumer, as the
 * CLI does; a row the page or REST refuses is marked and the others still go. The result dialog
 * says which pacts are new and pending, which were unchanged, what was refused, and whether webhooks
 * and comparisons ran.
 *
 * A role without `pacts:create` sees the explanation and the command block only. The import dialog
 * (PFX-5.8) opens this page pre-filled (query string, and the pact itself through sessionStorage).
 * Anything in the address that cannot be used is reported, never dropped.
 */

import * as React from 'react';
import Link from 'next/link';
import { ClipboardPaste, Download, FileUp, FolderOpen, GitCommitHorizontal, PencilRuler, ShieldCheck, Upload, WandSparkles } from 'lucide-react';
import {
  Alert,
  Badge,
  Button,
  CommandBlock,
  Input,
  Label,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useMyPermissions } from '@/app/components/ade/access/useMyPermissions';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_CRUMBS, CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  MAX_FILES,
  PUBLISH_HANDOFF_KEY,
  annotateRows,
  deriveRequest,
  pacticipantKey,
  publishBatches,
  publishCommandAction,
  publishableRows,
  readPactFile,
  refusedContractIndex,
  specLabel,
  validateDerive,
  validateWhose,
  type CheckVerdict,
  type DeriveDraft,
  type PactFileRow,
  type PublishOutcome,
  type PublishPrefill,
  type PublishSource,
  type WhoseVersion,
} from '@lib/pact-publish-page';
import {
  MAX_SELECTORS,
  checkCommandAction,
  compareChoices,
  defaultSelectors,
  differenceView,
  parseSelector,
  type CompareChoice,
  type DifferenceView,
} from '@lib/pact-publish-check';
import { EMPTY_EDITOR, buildPact, draftProblems, readPactIntoEditor, type EditorDraft } from '@lib/pact-interaction-editor';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { InteractionEditor, type SpecState } from './InteractionEditor';
import { CheckResultCard, CompareWith, DifferenceDrawer, type CheckState } from './CheckPanels';
import { FileTable, ReadOnlyNote, ResultDialog, type PublishFailure, type PublishResult } from './PublishPanels';
import {
  checkRow,
  comparePact,
  fetchCompareEnvironments,
  fetchPacticipant,
  fetchProjectConsumers,
  fetchProjects,
  fetchProviderSpec,
  publishBatch,
  publishDerived,
  type CompareEnvironment,
  type ConsumerChoice,
  type ProjectChoice,
} from './publishApi';

/** The permission publishing needs. */
const WRITE_PERMISSION = 'pacts:create';

/** The pasted pact's row id. */
const PASTE_ID = 'pasted';

/** The written pact's row id. */
const WRITTEN_ID = 'written';

/** A file the browser handed over, with the path it had inside a dropped or picked folder. */
interface PickedFile {
  name: string;
  read: () => Promise<string>;
}

/**
 * Every file under a dropped folder (or the dropped file itself).
 *
 * @param entry - A `FileSystemEntry` from `DataTransferItem.webkitGetAsEntry()`.
 * @returns The files, each named by its path in the folder.
 */
async function entryFiles(entry: FileSystemEntry): Promise<PickedFile[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject));
    return [{ name: entry.fullPath.replace(/^\//, '') || file.name, read: () => file.text() }];
  }
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  // readEntries answers in pages; an empty page is the end.
  for (;;) {
    const page = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!page.length) break;
    children.push(...page);
  }
  return (await Promise.all(children.map(entryFiles))).flat();
}

/**
 * The files of a drop: folders walked when the browser offers entries, plain files otherwise.
 *
 * @param transfer - The drop's data.
 * @returns The files.
 */
async function droppedFiles(transfer: DataTransfer): Promise<PickedFile[]> {
  const entries = Array.from(transfer.items ?? [])
    .map((item) => (typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null))
    .filter((entry): entry is FileSystemEntry => entry !== null);
  if (entries.length) return (await Promise.all(entries.map(entryFiles))).flat();
  return Array.from(transfer.files).map((file) => ({ name: file.name, read: () => file.text() }));
}

/** Props for {@link PublishPactClient}. */
export interface PublishPactClientProps {
  /** What the address pre-fills. */
  prefill: PublishPrefill;
}

/**
 * The page.
 *
 * @param props - See {@link PublishPactClientProps}.
 * @returns The page.
 */
export default function PublishPactClient({ prefill }: PublishPactClientProps) {
  const permissions = useMyPermissions();
  const canWrite = permissions.status === 'ready' && permissions.can(WRITE_PERMISSION);
  const readOnly = permissions.status !== 'loading' && !canWrite;

  const [source, setSource] = React.useState<PublishSource>(prefill.source);
  const [files, setFiles] = React.useState<PactFileRow[]>([]);
  const [pasted, setPasted] = React.useState('');
  const [whose, setWhose] = React.useState<WhoseVersion>(prefill.whose);
  const [derive, setDerive] = React.useState<DeriveDraft>(prefill.derive);
  const [verdicts, setVerdicts] = React.useState<Record<string, CheckVerdict>>({});
  const [checkedVersion, setCheckedVersion] = React.useState('');
  const [problem, setProblem] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [repoNote, setRepoNote] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<'check' | 'publish' | 'fill' | null>(null);
  const [result, setResult] = React.useState<PublishResult | null>(null);
  const [projects, setProjects] = React.useState<ProjectChoice[] | null>(null);
  const [consumers, setConsumers] = React.useState<ConsumerChoice[] | null>(null);
  const [listError, setListError] = React.useState<string | null>(null);
  const [environments, setEnvironments] = React.useState<CompareEnvironment[] | null>(null);
  const [envProblem, setEnvProblem] = React.useState<string | null>(null);
  const [typedChoices, setTypedChoices] = React.useState<CompareChoice[]>([]);
  const [selectors, setSelectors] = React.useState<string[] | null>(null);
  const [checks, setChecks] = React.useState<Record<string, CheckState>>({});
  const [difference, setDifference] = React.useState<DifferenceView | null>(null);
  const [editor, setEditor] = React.useState<EditorDraft>(EMPTY_EDITOR);
  const [specState, setSpecState] = React.useState<SpecState>({ status: 'idle' });
  const [importNotes, setImportNotes] = React.useState<string[]>([]);
  const nextInteraction = React.useRef(0);
  const fileInput = React.useRef<HTMLInputElement>(null);
  const folderInput = React.useRef<HTMLInputElement>(null);
  const nextId = React.useRef(0);

  // The import dialog's hand-off: the pact it held, read once.
  React.useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(PUBLISH_HANDOFF_KEY);
      if (!raw) return;
      window.sessionStorage.removeItem(PUBLISH_HANDOFF_KEY);
      const handed = JSON.parse(raw) as { pact?: unknown };
      if (typeof handed.pact === 'string' && handed.pact.trim()) {
        setPasted(handed.pact);
        setSource('paste');
      }
    } catch {
      // Storage refused or the value was not ours: the page starts empty.
    }
  }, []);

  // **Compare with**: the workspace's environments, read once; main and production start switched on.
  React.useEffect(() => {
    if (!canWrite || environments !== null) return;
    void fetchCompareEnvironments().then((answer) => {
      if (Array.isArray(answer)) setEnvironments(answer);
      else {
        setEnvironments([]);
        setEnvProblem(`${answer.error} Type a provider version with + Another version.`);
      }
    });
  }, [canWrite, environments]);

  const chosen = selectors ?? defaultSelectors(environments ?? []);
  const choices = [
    ...compareChoices((environments ?? []).map((env) => env.name)),
    ...typedChoices,
  ].filter((choice, index, all) => all.findIndex((other) => other.selector === choice.selector) === index);

  const toggleSelector = (selector: string) => {
    if (chosen.includes(selector)) return setSelectors(chosen.filter((item) => item !== selector));
    if (chosen.length >= MAX_SELECTORS) {
      return setNotice(`A check compares with at most ${MAX_SELECTORS} provider versions: switch one off first.`);
    }
    setSelectors([...chosen, selector]);
  };

  /** **+ Another version**: add a typed selector, switched on. */
  const addSelector = (text: string): string | null => {
    const parsed = parseSelector(text);
    if ('error' in parsed) return parsed.error;
    if (!chosen.includes(parsed.selector) && chosen.length >= MAX_SELECTORS) {
      return `A check compares with at most ${MAX_SELECTORS} provider versions: switch one off first.`;
    }
    if (!choices.some((choice) => choice.selector === parsed.selector)) setTypedChoices((list) => [...list, parsed]);
    if (!chosen.includes(parsed.selector)) setSelectors([...chosen, parsed.selector]);
    return null;
  };

  // The Derive tab's choices, read when it is first opened.
  React.useEffect(() => {
    if (source !== 'derive' || !canWrite || projects !== null) return;
    void fetchProjects().then((answer) => {
      if (Array.isArray(answer)) setProjects(answer);
      else {
        setProjects([]);
        setListError(answer.error);
      }
    });
  }, [source, canWrite, projects]);

  const project = derive.project;
  React.useEffect(() => {
    setConsumers(null);
    if (source !== 'derive' || !canWrite || !project) return;
    let live = true;
    void fetchProjectConsumers(project).then((answer) => {
      if (!live) return;
      if (Array.isArray(answer)) setConsumers(answer);
      else {
        setConsumers([]);
        setListError(answer.error);
      }
    });
    return () => {
      live = false;
    };
  }, [source, canWrite, project]);

  const pastedRow = React.useMemo(() => (pasted.trim() ? readPactFile(PASTE_ID, 'Pasted pact', pasted) : null), [pasted]);
  const editorProblems = React.useMemo(() => draftProblems(editor), [editor]);
  /** The written pact as a row: read by the same reader as a file, or what stops it. */
  const writtenRow = React.useMemo(() => {
    if (!editor.interactions.length) return null;
    const built = buildPact(editor);
    const name = 'Written in the editor';
    if ('pact' in built) return readPactFile(WRITTEN_ID, name, JSON.stringify(built.pact, null, 2));
    const count = built.problems.pair.length + Object.values(built.problems.interactions).flat().length;
    return {
      ...readPactFile(WRITTEN_ID, name, ''),
      specVersion: '4.0',
      consumer: editor.consumer.trim() || null,
      provider: editor.provider.trim() || null,
      problem: `Not ready to publish: ${count === 1 ? 'one thing needs' : `${count} things need`} fixing in the editor — each interaction lists its own.`,
    };
  }, [editor]);
  const rows = React.useMemo(
    () =>
      source === 'upload'
        ? annotateRows(files)
        : source === 'paste' && pastedRow
          ? [pastedRow]
          : source === 'write' && writtenRow
            ? [writtenRow]
            : [],
    [source, files, pastedRow, writtenRow],
  );

  /** The editor changed: earlier verdicts and comparisons no longer apply. */
  const editWritten = (next: EditorDraft) => {
    setEditor(next);
    setVerdicts({});
    setChecks({});
  };

  /** Read the provider's spec, catalogue states and mock scenarios for the editor. */
  const loadSpec = async (provider: string) => {
    setSpecState({ status: 'loading', provider });
    const answer = await fetchProviderSpec(provider);
    setSpecState('error' in answer ? { status: 'error', provider, error: answer.error } : { status: 'ready', spec: answer });
  };

  /** **Start from the pasted pact**: read it into the editor; what it cannot hold is listed. */
  const startFromPasted = () => {
    const read = readPactIntoEditor(pasted, () => `ix${nextInteraction.current++}`);
    if ('error' in read) return setNotice(read.error);
    editWritten(read.draft);
    setImportNotes(read.unsupported);
    setSource('write');
    if (read.draft.provider.trim()) void loadSpec(read.draft.provider.trim());
  };

  /** **Download the pact**: the written document as a file, for `apiome pact publish pacts/`. */
  const downloadWritten = () => {
    if (!writtenRow || writtenRow.problem) return;
    const name = `${pacticipantKey(writtenRow.consumer ?? 'consumer')}-${pacticipantKey(writtenRow.provider ?? 'provider')}.json`;
    const url = URL.createObjectURL(new Blob([writtenRow.text], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  };
  const sendable = publishableRows(rows);
  const rowConsumers = [...new Set(sendable.map((row) => row.consumer as string))];

  const edit = (patch: Partial<WhoseVersion>) => {
    setWhose((current) => ({ ...current, ...patch }));
    setVerdicts({});
  };

  /** Add files from the picker, the folder picker or a drop. */
  const addFiles = async (picked: PickedFile[]) => {
    setProblem(null);
    const room = MAX_FILES - files.length;
    const taken = picked.slice(0, Math.max(0, room));
    const added = await Promise.all(
      taken.map(async (file) => {
        const id = `f${nextId.current++}`;
        if (!/\.json$/i.test(file.name)) {
          return { ...readPactFile(id, file.name, ''), problem: 'Not a .json file: a pact is a JSON document.' };
        }
        try {
          return readPactFile(id, file.name, await file.read());
        } catch {
          return { ...readPactFile(id, file.name, ''), problem: 'The browser could not read this file.' };
        }
      }),
    );
    setFiles((current) => [...current, ...added]);
    setVerdicts({});
    if (picked.length > taken.length) {
      setNotice(`${picked.length - taken.length} more files were not added: this page holds at most ${MAX_FILES}.`);
    }
  };

  const onPick = (event: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(event.target.files ?? []);
    void addFiles(list.map((file) => ({ name: file.webkitRelativePath || file.name, read: () => file.text() })));
    event.target.value = '';
  };

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    void droppedFiles(event.dataTransfer).then(addFiles);
  };

  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setPasted(text);
      setVerdicts({});
      setChecks({});
    } catch {
      setNotice('The browser did not allow reading the clipboard: paste into the box with Ctrl+V or ⌘V.');
    }
  };

  /** **Fill from the linked repository**: the consumer pacticipant's main branch and repository. */
  const fillFromRepository = async () => {
    const consumer = source === 'derive' ? derive.consumer : rowConsumers[0];
    if (!consumer) {
      setRepoNote('Add a pact first: the consumer it names is the pacticipant whose repository is read.');
      return;
    }
    setBusy('fill');
    const answer = await fetchPacticipant(pacticipantKey(consumer));
    setBusy(null);
    if (answer === null) {
      setRepoNote(`${consumer} is not a pacticipant yet, so it has no linked repository. Publishing registers it; type the branch for now.`);
    } else if ('error' in answer) {
      setRepoNote(answer.error);
    } else if (!answer.main_branch) {
      setRepoNote(`${answer.name} has no main branch recorded${answer.repository_url ? '' : ' and no linked repository'}: set them on its pacticipant page.`);
    } else {
      edit({ branch: answer.main_branch });
      setRepoNote(
        `Branch set to ${answer.main_branch}, ${answer.name}’s main branch${answer.repository_url ? ` in ${answer.repository_url}` : ''}. The version is your build’s: type its commit.`,
      );
    }
  };

  /** Compare each publishable row with the chosen provider versions. Writes nothing. */
  const compareRows = async (targets = sendable) => {
    if (!chosen.length) return;
    setChecks((current) => ({ ...current, ...Object.fromEntries(targets.map((row) => [row.id, { status: 'loading' } as CheckState])) }));
    for (const row of targets) {
      const answer = await comparePact(row, chosen);
      const state: CheckState = 'error' in answer ? { status: 'error', error: answer.error } : { status: 'done', answer };
      setChecks((current) => ({ ...current, [row.id]: state }));
    }
  };

  /**
   * **Check only**: compare each pact with the chosen provider versions, and read what each row's
   * version already published. Writes nothing.
   */
  const checkOnly = async () => {
    setProblem(null);
    setNotice(null);
    if (source === 'derive') {
      setNotice('A derived pact is generated when it is published, so there is nothing to compare yet. Its findings are listed after publishing.');
      return;
    }
    if (!sendable.length) return setProblem(rows.length ? 'No pact here can be published: each row says why.' : 'Add a pact first.');
    const issue = validateWhose({ ...whose, merge: false });
    if (issue && !chosen.length) return setProblem(issue);
    setBusy('check');
    const compared = compareRows();
    if (issue) {
      setNotice(`Compared with the provider versions. ${issue} — then check again to see whether this version already published a pact.`);
    } else {
      const version = whose.version.trim();
      const answers = await Promise.all(sendable.map(async (row) => [row.id, await checkRow(row, version)] as const));
      setVerdicts(Object.fromEntries(answers));
      setCheckedVersion(version);
    }
    await compared;
    setBusy(null);
  };

  /** **Publish pact**. */
  const publish = async () => {
    setProblem(null);
    setNotice(null);
    const issue = validateWhose(whose) ?? (source === 'derive' ? validateDerive(derive) : null);
    if (issue) return setProblem(issue);
    if (source === 'derive') {
      setBusy('publish');
      const answer = await publishDerived(deriveRequest(derive, whose));
      setBusy(null);
      if ('error' in answer) {
        setResult({ version: whose.version.trim(), branch: whose.branch.trim(), outcomes: [], skipped: [], derived: null, failures: [{ consumer: derive.consumer, ...answer }] });
      } else {
        setResult({ version: whose.version.trim(), branch: whose.branch.trim(), outcomes: [answer], skipped: [], failures: [], derived: answer });
      }
      return;
    }
    if (!sendable.length) return setProblem(rows.length ? 'No pact here can be published: each row says why.' : 'Add a pact first.');
    setBusy('publish');
    const outcomes: PublishOutcome[] = [];
    const failures: PublishFailure[] = [];
    const refused: Record<string, string> = {};
    for (const batch of publishBatches(rows, whose)) {
      let current = batch;
      // REST refuses a whole request for one bad contract and names it: mark it, send the rest.
      for (;;) {
        const answer = await publishBatch(current);
        if (!('error' in answer)) {
          outcomes.push(answer);
          break;
        }
        const index = answer.status === 422 ? refusedContractIndex(answer.error) : null;
        if (index === null || !current.rows[index] || current.rows.length === 1) {
          if (index !== null && current.rows[index]) refused[current.rows[index].id] = answer.error;
          else failures.push({ consumer: current.consumer, error: answer.error, status: answer.status });
          break;
        }
        refused[current.rows[index].id] = answer.error;
        const left = current.rows.filter((_, i) => i !== index);
        current = publishBatches(left, whose)[0];
      }
    }
    setBusy(null);
    if (Object.keys(refused).length) {
      setFiles((list) => list.map((row) => (refused[row.id] ? { ...row, problem: refused[row.id] } : row)));
    }
    const skipped = [
      ...rows.filter((row) => row.problem),
      ...sendable.filter((row) => refused[row.id]).map((row) => ({ ...row, problem: refused[row.id] })),
    ];
    setResult({ version: whose.version.trim(), branch: whose.branch.trim(), outcomes, failures, skipped, derived: null });
  };

  const reset = () => {
    setResult(null);
    setFiles([]);
    setPasted('');
    setVerdicts({});
    setChecks({});
    setEditor(EMPTY_EDITOR);
    setImportNotes([]);
  };

  const action = publishCommandAction({ source, rows, whose, derive, tenant: '' });
  const commandBlock = (
    <CommandBlock
      className="ppub-command-block"
      surfaces={pactCommandSurfaces(action)}
      unsupported={unsupportedLines(action)}
      footnote="Replace {tenant} with your workspace’s handle in the REST path. In CI the GitHub Action fills the version and branch from the run."
      data-testid="ppub-command-block"
    />
  );
  const statusLine = problem ?? notice ?? (prefill.problems.length ? prefill.problems.join(' ') : null);
  const tone = problem ? 'danger' : 'warn';

  return (
    <Page>
      <PageHeader
        title="Publish a consumer pact"
        breadcrumb={[...CONTRACTS_CRUMBS, { label: 'Publish a pact' }]}
        description="Bring pacts in, check them against what is published, then publish. Nothing is saved until you do."
        tabs={<ContractsTabs active="overview" />}
        actions={
          canWrite ? (
            <>
              <Button variant="outline" asChild>
                <Link href={CONTRACTS_ROUTE}>Cancel</Link>
              </Button>
              <Button variant="outline" onClick={() => void checkOnly()} disabled={busy !== null} title="Runs the checks and publishes nothing" data-testid="ppub-check">
                Check only
              </Button>
            </>
          ) : undefined
        }
        primaryAction={
          canWrite ? (
            <Button onClick={() => void publish()} disabled={busy !== null} data-testid="ppub-publish">
              <FileUp aria-hidden />
              {busy === 'publish' ? 'Publishing…' : 'Publish pact'}
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="ppub" data-testid="pact-publish">
          {statusLine ? (
            <Alert variant={tone} data-testid="ppub-status">
              {statusLine}
            </Alert>
          ) : null}
          <div className="ppub__split">
            <div className="ppub__main">
              {readOnly ? <ReadOnlyNote unknown={permissions.status === 'error'} /> : null}
              {canWrite ? (
                <>
                  <section className="ppub-card" aria-labelledby="ppub-step-1">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppub-step-1">
                        <span className="ppub-step" aria-hidden>
                          1
                        </span>
                        The pact
                      </h2>
                    </div>
                    <Tabs value={source} onValueChange={(value) => { setSource(value as PublishSource); setVerdicts({}); }}>
                      <TabsList aria-label="Pact source">
                        <TabsTrigger value="upload">
                          <Upload aria-hidden className="ppub-tab__glyph" />
                          Upload
                        </TabsTrigger>
                        <TabsTrigger value="paste">
                          <ClipboardPaste aria-hidden className="ppub-tab__glyph" />
                          Paste
                        </TabsTrigger>
                        <TabsTrigger value="derive">
                          <WandSparkles aria-hidden className="ppub-tab__glyph" />
                          Derive from a project
                        </TabsTrigger>
                        <TabsTrigger value="write">
                          <PencilRuler aria-hidden className="ppub-tab__glyph" />
                          Write interactions
                        </TabsTrigger>
                      </TabsList>
                      <TabsContent value="upload" className="ppub-panel">
                        <div
                          className="ppub-drop"
                          role="button"
                          tabIndex={0}
                          aria-label="Drop pact files or a folder, or press Enter to browse"
                          onClick={() => fileInput.current?.click()}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              fileInput.current?.click();
                            }
                          }}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={onDrop}
                          data-testid="ppub-drop"
                        >
                          <Upload aria-hidden className="ppub-drop__glyph" />
                          <span className="ppub-drop__title">
                            Drop pact files or a whole <span className="ppx__mono">pacts/</span> folder
                          </span>
                          <span className="ppub-drop__hint">Pact v1 to v4 · .json · several providers and consumers at once is fine</span>
                        </div>
                        <div className="ppub-row-actions">
                          <Button type="button" variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
                            <FileUp aria-hidden />
                            Browse files
                          </Button>
                          <Button type="button" variant="outline" size="sm" onClick={() => folderInput.current?.click()}>
                            <FolderOpen aria-hidden />
                            Browse a folder
                          </Button>
                        </div>
                        <input
                          ref={fileInput}
                          type="file"
                          multiple
                          accept="application/json,.json"
                          className="ppub-file-input"
                          onChange={onPick}
                          data-testid="ppub-file-input"
                          aria-label="Pact files"
                        />
                        <input
                          ref={(node) => {
                            folderInput.current = node;
                            // `webkitdirectory` is not in React's typings; set it on the element.
                            node?.setAttribute('webkitdirectory', '');
                          }}
                          type="file"
                          multiple
                          className="ppub-file-input"
                          onChange={onPick}
                          data-testid="ppub-folder-input"
                          aria-label="A folder of pact files"
                        />
                        {files.length ? (
                          <FileTable
                            rows={rows}
                            verdicts={verdicts}
                            checkedVersion={checkedVersion}
                            onRemove={(id) => {
                              setFiles((list) => list.filter((row) => row.id !== id));
                              setVerdicts({});
                            }}
                          />
                        ) : null}
                      </TabsContent>
                      <TabsContent value="paste" className="ppub-panel">
                        <div className="ppub-row-actions">
                          <Button type="button" variant="outline" size="sm" onClick={() => void pasteFromClipboard()}>
                            <ClipboardPaste aria-hidden />
                            Paste from clipboard
                          </Button>
                          {pastedRow && !pastedRow.problem ? (
                            <Badge variant="accent" data-testid="ppub-paste-detected">
                              {specLabel(pastedRow.specVersion)} detected
                            </Badge>
                          ) : null}
                        </div>
                        <Label htmlFor="ppub-paste">Pact JSON</Label>
                        <Textarea
                          id="ppub-paste"
                          className="ppx__mono ppub-paste"
                          rows={10}
                          spellCheck={false}
                          value={pasted}
                          placeholder='{ "consumer": { "name": "Orders UI" }, "provider": { "name": "Billing Service" }, "interactions": [ … ] }'
                          onChange={(event) => {
                            setPasted(event.target.value);
                            setVerdicts({});
                            setChecks({});
                          }}
                        />
                        {pastedRow ? (
                          <FileTable rows={[pastedRow]} verdicts={verdicts} checkedVersion={checkedVersion} onRemove={() => setPasted('')} />
                        ) : null}
                        {pastedRow && !pastedRow.problem ? (
                          <div className="ppub-row-actions">
                            <Button type="button" variant="outline" size="sm" onClick={startFromPasted} data-testid="ppub-edit-pasted">
                              <PencilRuler aria-hidden />
                              Edit in Write interactions
                            </Button>
                          </div>
                        ) : null}
                      </TabsContent>
                      <TabsContent value="write" className="ppub-panel">
                        <p className="ppub-card__lead">
                          No Pact tests yet? Write what the consumer sends and the answer it needs. The editor writes a Pact v4
                          document, which is checked and published like any other.
                        </p>
                        <InteractionEditor
                          draft={editor}
                          onChange={editWritten}
                          problems={editorProblems}
                          spec={specState}
                          onLoadSpec={(provider) => void loadSpec(provider)}
                          nextId={() => `ix${nextInteraction.current++}`}
                          importNotes={importNotes}
                        />
                        {writtenRow ? (
                          <>
                            <FileTable rows={[writtenRow]} verdicts={verdicts} checkedVersion={checkedVersion} />
                            <div className="ppub-row-actions">
                              <Button type="button" variant="outline" size="sm" onClick={downloadWritten} disabled={Boolean(writtenRow.problem)} data-testid="ppub-download-written">
                                <Download aria-hidden />
                                Download the pact
                              </Button>
                              <span className="ppub-hint">Commit it under pacts/ to publish it from CI with the command beside.</span>
                            </div>
                          </>
                        ) : null}
                      </TabsContent>
                      <TabsContent value="derive" className="ppub-panel">
                        <p className="ppub-card__lead">
                          Publish a consumer’s declared surface in a project as its pact — the operations and fields it uses, with the
                          spec’s examples as sample values. Every value that had to be invented and everything left out is listed after
                          publishing. Choosing operations and previewing the pact come with the <b>Export</b> page.
                        </p>
                        {listError ? <p className="ppub-hint ppub-hint--danger">{listError}</p> : null}
                        <div className="ppub-grid">
                          <div className="ppub-field">
                            <Label htmlFor="ppub-derive-project">Project</Label>
                            <select
                              id="ppub-derive-project"
                              className="ppub-select"
                              value={derive.project}
                              onChange={(event) => setDerive({ ...derive, project: event.target.value, consumer: '' })}
                            >
                              <option value="">{projects === null ? 'Loading projects…' : 'Choose a project'}</option>
                              {derive.project && !(projects ?? []).some((p) => p.slug === derive.project || p.id === derive.project) ? (
                                <option value={derive.project}>{derive.project}</option>
                              ) : null}
                              {(projects ?? []).map((p) => (
                                <option key={p.id} value={p.slug}>
                                  {p.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppub-derive-consumer">Consumer</Label>
                            <select
                              id="ppub-derive-consumer"
                              className="ppub-select"
                              value={derive.consumer}
                              disabled={!derive.project}
                              onChange={(event) => setDerive({ ...derive, consumer: event.target.value })}
                              aria-describedby="ppub-derive-consumer-hint"
                            >
                              <option value="">{derive.project && consumers === null ? 'Loading consumers…' : 'Choose a consumer'}</option>
                              {derive.consumer && !(consumers ?? []).some((c) => c.slug === derive.consumer) ? (
                                <option value={derive.consumer}>{derive.consumer}</option>
                              ) : null}
                              {(consumers ?? []).map((c) => (
                                <option key={c.slug} value={c.slug} disabled={c.unavailable !== null}>
                                  {c.unavailable ? `${c.name} — ${c.unavailable}` : c.name}
                                </option>
                              ))}
                            </select>
                            <p className="ppub-hint" id="ppub-derive-consumer-hint">
                              Only a consumer declared with the picker can be derived.
                            </p>
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppub-derive-revision">Revision (optional)</Label>
                            <Input
                              id="ppub-derive-revision"
                              inputMode="numeric"
                              value={derive.revision}
                              placeholder="The current one"
                              onChange={(event) => setDerive({ ...derive, revision: event.target.value })}
                            />
                          </div>
                          <div className="ppub-field">
                            <Label htmlFor="ppub-derive-provider">Provider (optional)</Label>
                            <Input
                              id="ppub-derive-provider"
                              value={derive.provider}
                              maxLength={200}
                              placeholder="The project’s provider pacticipant"
                              onChange={(event) => setDerive({ ...derive, provider: event.target.value })}
                            />
                          </div>
                        </div>
                      </TabsContent>
                    </Tabs>
                  </section>

                  <section className="ppub-card" aria-labelledby="ppub-step-2">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppub-step-2">
                        <span className="ppub-step" aria-hidden>
                          2
                        </span>
                        Whose version this is
                      </h2>
                      <Button type="button" variant="outline" size="sm" onClick={() => void fillFromRepository()} disabled={busy !== null}>
                        <GitCommitHorizontal aria-hidden />
                        Fill from the linked repository
                      </Button>
                    </div>
                    {repoNote ? (
                      <p className="ppub-hint" role="status" data-testid="ppub-repo-note">
                        {repoNote}
                      </p>
                    ) : null}
                    <div className="ppub-grid">
                      <div className="ppub-field">
                        <span className="ppub-field__label">Consumer</span>
                        <p className="ppub-field__value" data-testid="ppub-consumer">
                          {source === 'derive'
                            ? derive.consumer || 'The consumer you derive from'
                            : rowConsumers.length
                              ? rowConsumers.join(', ')
                              : 'Named by the pact'}
                        </p>
                        <p className="ppub-hint">
                          {rowConsumers.length > 1 ? 'One request per consumer, as apiome pact publish sends them.' : 'Each pact names its consumer.'}
                        </p>
                      </div>
                      <div className="ppub-field">
                        <Label htmlFor="ppub-version">Consumer version</Label>
                        <Input
                          id="ppub-version"
                          className="ppx__mono"
                          value={whose.version}
                          maxLength={255}
                          placeholder="3.4.0+a1c9e02"
                          aria-describedby="ppub-version-hint"
                          onChange={(event) => edit({ version: event.target.value })}
                        />
                        <p className="ppub-hint" id="ppub-version-hint">
                          A version that changes with every build — a git SHA is ideal.
                        </p>
                      </div>
                      <div className="ppub-field">
                        <Label htmlFor="ppub-branch">Branch</Label>
                        <Input id="ppub-branch" value={whose.branch} maxLength={255} placeholder="main" onChange={(event) => edit({ branch: event.target.value })} />
                      </div>
                      <div className="ppub-field">
                        <Label htmlFor="ppub-tags">Tags (optional)</Label>
                        <Input id="ppub-tags" value={whose.tags} placeholder="dev, rc" onChange={(event) => edit({ tags: event.target.value })} />
                      </div>
                    </div>
                    <details className="ppub-more" open={prefill.whose.buildUrl ? true : undefined}>
                      <summary>More options</summary>
                      <div className="ppub-more__body">
                        <div className="ppub-field">
                          <Label htmlFor="ppub-build-url">Build URL</Label>
                          <Input
                            id="ppub-build-url"
                            value={whose.buildUrl}
                            maxLength={2048}
                            placeholder="https://ci.example.com/builds/4821"
                            onChange={(event) => edit({ buildUrl: event.target.value })}
                          />
                        </div>
                        <div className="ppub-switch">
                          <div>
                            <Label htmlFor="ppub-merge">Merge with the pact already published for this version</Label>
                            <p className="ppub-hint" id="ppub-merge-hint">
                              {whose.merge
                                ? 'Not supported: Apiome stores a version’s pact as published.'
                                : 'For test suites that publish in several parts. Apiome does not merge: a different pact for a version that has one is refused.'}
                            </p>
                          </div>
                          <Switch id="ppub-merge" checked={whose.merge} aria-describedby="ppub-merge-hint" onCheckedChange={(merge: boolean) => edit({ merge })} />
                        </div>
                        <div className="ppub-switch">
                          <div>
                            <Label htmlFor="ppub-tag-branch">Also tag with the branch name</Label>
                            <p className="ppub-hint" id="ppub-tag-branch-hint">
                              For pipelines that still select pacts by tag.
                            </p>
                          </div>
                          <Switch
                            id="ppub-tag-branch"
                            checked={whose.tagWithBranch}
                            aria-describedby="ppub-tag-branch-hint"
                            onCheckedChange={(tagWithBranch: boolean) => edit({ tagWithBranch })}
                          />
                        </div>
                      </div>
                    </details>
                  </section>

                  <section className="ppub-card" aria-labelledby="ppub-step-3" data-testid="ppub-step-check">
                    <div className="ppub-card__head">
                      <h2 className="ppub-card__title" id="ppub-step-3">
                        <span className="ppub-step" aria-hidden>
                          3
                        </span>
                        Check it before it counts
                      </h2>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void checkOnly()}
                        disabled={busy !== null || !chosen.length}
                        data-testid="ppub-compare"
                      >
                        <ShieldCheck aria-hidden />
                        {busy === 'check' ? 'Checking…' : 'Compare now'}
                      </Button>
                    </div>
                    <CompareWith choices={choices} selected={chosen} onToggle={toggleSelector} onAdd={addSelector} problem={envProblem} />
                    {source === 'derive' ? (
                      <p className="ppub-hint">A derived pact is generated when it is published, so it is compared after publishing.</p>
                    ) : null}
                    <CommandBlock
                      title="The same check, from anywhere"
                      surfaces={pactCommandSurfaces(checkCommandAction({ selectors: chosen, tenant: '' }))}
                      footnote="Exits 0 when every pact matches every provider version checked, 1 otherwise. Replace {tenant} in the REST path."
                      data-testid="ppub-check-command"
                    />
                  </section>
                </>
              ) : null}
            </div>
            <aside className="ppub__aside" aria-label="Result of the check and the same, from anywhere">
              {sendable
                .filter((row) => checks[row.id])
                .map((row) => (
                  <CheckResultCard
                    key={row.id}
                    pair={`${row.consumer} → ${row.provider}`}
                    state={checks[row.id]}
                    onRecheck={() => void compareRows([row])}
                    onOpen={(interaction, picked, provider) => setDifference(differenceView(interaction, picked, provider))}
                  />
                ))}
              {commandBlock}
            </aside>
          </div>
          <ResultDialog result={result} onClose={() => setResult(null)} onAgain={reset} />
          <DifferenceDrawer view={difference} onClose={() => setDifference(null)} />
        </div>
      </PageBody>
    </Page>
  );
}
