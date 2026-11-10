'use client';

/**
 * The import wizard (HIVE-6.4, #5315).
 *
 * Authority: `docs/mockups/build/import-wizard.html`, design language `docs/mockups/DESIGN.md`.
 *
 * This file keeps every piece of state and every write it had before the redesign — the intake
 * buffers, the analysis, the async job, the quality snapshot. What
 * moved out is the skin and the decisions:
 *
 *   - the stepper, the head and the footer are `components/ade/import/ImportWizardChrome`;
 *   - which verb the footer carries, whether Back is allowed, how a job state reads and what the
 *     quality gate says are `importWizardModel`, so `import-wizard-model.test.ts` can assert the
 *     whole table without starting an import;
 *   - the source grid, the intake tab bar and the File intake are their own components.
 *
 * The flow: Source → Analyze → Preview → [Changes] → Import → Done. Adding an MCP server is not a
 * spec import and has its own dialog (`mcp/AddMcpServerDialog`). *Changes* (IXH-3.7, #6321) is asked
 * for when Preview's **Import →** is pressed: if the slug resolves to an existing Project the
 * wizard stops there to compare the spec with that project's latest version; otherwise (and for
 * the Catalog) it goes straight to Import.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { ListChecks } from 'lucide-react';
import {
  Dialog,
  DialogContent,
} from '../../../components/ui/Dialog';
import { Alert } from '../../../components/ui/Alert';
import { Button } from '../../../components/ui/Button';
import { AnalysisPanel } from './AnalysisPanel';
import { PreviewPanel, ImportOptions } from './PreviewPanel';
import { analyzeSpecification, AnalysisResult, extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import ImportExecutionPanel from './ImportExecutionPanel';
import ImportCompletePanel from './ImportCompletePanel';
import UrlImportPanel, { type UrlImportPanelHandle, type UrlImportFooterState } from './UrlImportPanel';
import { useImportSources } from './useImportSources';
import { type ImportVariant } from './importSourceCatalog';
import ClipboardImportPanel from './ClipboardImportPanel';
import GitImportPanel from './GitImportPanel';
import SwaggerHubImportPanel from './SwaggerHubImportPanel';
import PostmanImportPanel from './PostmanImportPanel';
import { startImport, getImportStatus, rollbackImport } from '../../../../../lib/db/import-actions';
import { fetchProjectDelta, type ProjectDeltaState } from '../../../utils/import-project-delta';
import { planImportVersion } from '../../../utils/import-version-label';
import { generateSlug } from '../../../utils/slug';
import { appendProjectQualitySnapshot, buildQualitySnapshotReportExtras } from '../../../utils/project-quality-score-history';
import { buildUrlImportRecord, recordUrlImport, type UrlImportSource } from '../../../utils/url-import-record';
import {
  FileIntakePanel,
  ImportChangesPanel,
  ImportIntakeTabs,
  ImportSourceCards,
  ImportWizardBody,
  ImportWizardFooter,
  ImportWizardHead,
  ImportWizardSteps,
  RecentImportJobsDrawer,
  RecentImportsList,
  importFooterFor,
  importQualityGate,
  importWizardStepsFor,
  showsChangesStep,
  stepperIdFor,
  isAcceptedImportFile,
  detectAndDescribe,
  urlTestAction,
  IMPORT_WIZARD_COPY,
  type ImportArrayChoice,
  type ImportMergeChoice,
  type ImportWizardStep,
} from '../import';

interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  tenantId: string;
  userId: string;
  /** When set, dialog opens and runs analysis with this spec (e.g. from AI Design Chat). */
  initialLLMSpec?: string | null;
  /** Called when initialLLMSpec has been consumed so parent can clear it. */
  onConsumeInitialLLMSpec?: () => void;
  /** True when this dialog was opened from New Project → Design with AI → Import This Spec. Back/Cancel then return to the New Project form (AI tab) instead of source selection. */
  openedFromNewProjectAI?: boolean;
  /** When openedFromNewProjectAI is true, called instead of onClose when user goes Back to "source" or clicks Cancel, so parent can reopen New Project on AI tab. */
  onReturnToNewProjectAI?: () => void;
  /** When set, the dialog opens straight onto this import source (e.g. 'git'). */
  initialSource?: string | null;
  /** Called once initialSource has been applied so the parent can clear it. */
  onConsumeInitialSource?: () => void;
  /**
   * Which importer surface this dialog serves (MFI-23.12). `projects` offers the native
   * OpenAPI/Swagger intake; `catalog` offers the alternative (non-OpenAPI) formats; `all` (default)
   * shows every source card. Drives which source cards the grid lists.
   */
  variant?: ImportVariant;
}

const ImportDialog: React.FC<ImportDialogProps> = ({
  open,
  onClose,
  onSuccess,
  tenantId,
  userId,
  initialLLMSpec,
  onConsumeInitialLLMSpec,
  openedFromNewProjectAI,
  onReturnToNewProjectAI,
  initialSource,
  onConsumeInitialSource,
  variant = 'all',
}) => {
  const [currentStep, setCurrentStep] = useState<ImportWizardStep>('source');
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileMetadata, setFileMetadata] = useState<FileMetadataPreview | null>(null);
  // A non-blocking notice about the picked file (FMT-1.1, #5412): either its extension is one no
  // registered adapter declares, or analysis failed and the detector identified the format. Never
  // an error — the file is analyzed regardless, and content sniffing has the final word.
  const [advisoryNotice, setAdvisoryNotice] = useState<string | null>(null);
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [importOptions, setImportOptions] = useState<ImportOptions | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [importSucceeded, setImportSucceeded] = useState(false);
  const [importComplete, setImportComplete] = useState(false);
  const [urlContent, setUrlContent] = useState<string | null>(null);
  const [urlFilename, setUrlFilename] = useState<string | null>(null);
  const [urlMetadata, setUrlMetadata] = useState<FileMetadataPreview | null>(null);
  /** Where a URL Import document came from; recorded for auto-refresh after the import (RAR-6.1). */
  const [urlSource, setUrlSource] = useState<UrlImportSource | null>(null);
  /** The importer kind and options a URL import used, captured when it starts. */
  const urlRecordRef = useRef<{ jobId: string; sourceKind: string; options: Record<string, unknown> } | null>(null);
  const [clipboardContent, setClipboardContent] = useState<string | null>(null);
  const [clipboardFilename, setClipboardFilename] = useState<string | null>(null);
  const [gitContent, setGitContent] = useState<string | null>(null);
  const [gitFilename, setGitFilename] = useState<string | null>(null);
  const [gitMetadata, setGitMetadata] = useState<FileMetadataPreview | null>(null);
  const [swaggerHubContent, setSwaggerHubContent] = useState<string | null>(null);
  const [swaggerHubFilename, setSwaggerHubFilename] = useState<string | null>(null);
  const [swaggerHubMetadata, setSwaggerHubMetadata] = useState<FileMetadataPreview | null>(null);
  const [postmanContent, setPostmanContent] = useState<string | null>(null);
  const [postmanFilename, setPostmanFilename] = useState<string | null>(null);
  const [postmanMetadata, setPostmanMetadata] = useState<FileMetadataPreview | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  /** The Changes step's comparison with the target project's latest version (IXH-3.7). */
  const [projectDelta, setProjectDelta] = useState<ProjectDeltaState>({ status: 'idle' });
  /** Bumped per comparison request (and on Back / reset) so a stale answer is ignored. */
  const deltaRequestRef = useRef(0);
  /** The Changes step's merge strategy: `replace` (default), `additive` (#591) or `override` (#592). */
  const [mergeChoice, setMergeChoice] = useState<ImportMergeChoice>('replace');
  /** Under a merge, how arrays both sides define are combined (#595): `replace` (default), `append`, `deduplicate`. */
  const [arrayChoice, setArrayChoice] = useState<ImportArrayChoice>('replace');
  /** The mockup's *Recent import jobs* side-sheet (HIVE-6.4). */
  const [jobsDrawerOpen, setJobsDrawerOpen] = useState(false);

  const urlImportRef = useRef<UrlImportPanelHandle>(null);
  const dryRunRef = useRef(false);
  const [urlImportFooter, setUrlImportFooter] = useState<UrlImportFooterState>({
    canTestUrl: false,
    isTesting: false,
    urlTestedSuccessfully: false,
  });
  const handleUrlImportFooterState = useCallback((s: UrlImportFooterState) => {
    setUrlImportFooter(s);
  }, []);

  // MFI-1.3: the source-selection grid is data-driven. Built-in cards render immediately; any
  // server-registered adapter is merged in once `GET /api/import/sources` resolves. Only fetched
  // while the dialog is open.
  const { cards: sourceCards, fileExtensions } = useImportSources(open, variant);

  useEffect(() => {
    if (!importComplete || !importSucceeded || !jobId || !analysisResult?.qualityScore) return;
    if (dryRunRef.current) return;

    let cancelled = false;
    void (async () => {
      try {
        const status = await getImportStatus(jobId);
        if (cancelled) return;
        const projectId = (status as { result?: { projectId?: string } }).result?.projectId;
        if (!projectId) return;
        appendProjectQualitySnapshot(projectId, {
          overall: analysisResult.qualityScore.overall,
          grade: analysisResult.qualityScore.grade,
          importJobId: jobId,
          ...buildQualitySnapshotReportExtras(analysisResult),
        });
      } catch {
        // ignore
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [importComplete, importSucceeded, jobId, analysisResult]);

  // RAR-6.1: a successful URL import is recorded so REST re-checks the URL on its refresh cadence.
  // Best-effort and once per job; a dry run is never recorded (urlRecordRef is null for one).
  useEffect(() => {
    const pending = urlRecordRef.current;
    if (!importComplete || !importSucceeded || !jobId || !pending || pending.jobId !== jobId) return;
    urlRecordRef.current = null;
    const source = urlSource;
    void (async () => {
      try {
        const status = await getImportStatus(jobId);
        const result = (status as { result?: { projectId?: string; versionId?: string } }).result;
        const body = buildUrlImportRecord(source, result, pending.sourceKind, pending.options);
        if (body) await recordUrlImport(body);
      } catch {
        // The import succeeded; only its auto-refresh is missing.
      }
    })();
  }, [importComplete, importSucceeded, jobId, urlSource]);

  // When opened with spec from AI Design Chat (Projects dashboard), run analysis immediately
  useEffect(() => {
    if (!open || !initialLLMSpec) return;
    onConsumeInitialLLMSpec?.();
    setSelectedSource('llm');
    setClipboardContent(initialLLMSpec);
    setClipboardFilename('ai-generated-spec.json');
    setCurrentStep('file-upload');
    setErrorMessage(null);
    setIsAnalyzing(true);
    analyzeSpecification(initialLLMSpec, 'ai-generated-spec.json')
      .then((result) => {
        setAnalysisResult(result);
        setCurrentStep('analysis');
      })
      .catch((err) => {
        setErrorMessage(err instanceof Error ? err.message : 'Analysis failed');
      })
      .finally(() => setIsAnalyzing(false));
  }, [open, initialLLMSpec, onConsumeInitialLLMSpec]);

  // When opened with a pre-selected source, jump straight to it.
  useEffect(() => {
    if (!open || !initialSource) return;
    onConsumeInitialSource?.();
    setErrorMessage(null);
    setSelectedSource(initialSource);
    setCurrentStep('file-upload');
  }, [open, initialSource, onConsumeInitialSource]);

  const handleSourceClick = (source: string) => {
    setErrorMessage(null);
    setSelectedSource(source);
    setCurrentStep('file-upload');
  };

  const handleBack = () => {
    setErrorMessage(null);
    if (currentStep === 'done') {
      setCurrentStep('import');
    } else if (currentStep === 'import') {
      setCurrentStep(showsChangesStep(projectDelta) ? 'changes' : 'preview');
      setJobId(null);
    } else if (currentStep === 'changes') {
      deltaRequestRef.current += 1;
      setCurrentStep('preview');
    } else if (currentStep === 'preview') {
      deltaRequestRef.current += 1;
      setProjectDelta({ status: 'idle' });
      setCurrentStep('analysis');
    } else if (currentStep === 'analysis') {
      // If the source was LLM and we were opened from New Project AI, return to that conversation instead of source
      if (selectedSource === 'llm' && openedFromNewProjectAI && onReturnToNewProjectAI) {
        onReturnToNewProjectAI();
        return;
      }
      // If the source was LLM, skip file-upload and go straight back to source selection
      if (selectedSource === 'llm') {
        setCurrentStep('source');
        setSelectedSource(null);
        setClipboardContent(null);
        setClipboardFilename(null);
      } else {
        setCurrentStep('file-upload');
      }
      setAnalysisResult(null);
    } else if (currentStep === 'file-upload') {
      // If we were opened from New Project AI (e.g. landed on analysis then went back to file-upload), return to that conversation
      if (openedFromNewProjectAI && onReturnToNewProjectAI) {
        onReturnToNewProjectAI();
        return;
      }
      setCurrentStep('source');
      setSelectedSource(null);
      setSelectedFile(null);
      setFileMetadata(null);
      setAdvisoryNotice(null);
      setUrlContent(null);
      setUrlFilename(null);
      setUrlMetadata(null);
      setUrlSource(null);
      setClipboardContent(null);
      setClipboardFilename(null);
      setGitContent(null);
      setGitFilename(null);
      setGitMetadata(null);
      setSwaggerHubContent(null);
      setSwaggerHubFilename(null);
      setSwaggerHubMetadata(null);
      setPostmanContent(null);
      setPostmanFilename(null);
      setPostmanMetadata(null);
    }
  };

  const resetDialogState = () => {
    setCurrentStep('source');
    setSelectedSource(null);
    setSelectedFile(null);
    setFileMetadata(null);
    setAdvisoryNotice(null);
    setAnalysisResult(null);
    setImportOptions(null);
    setJobId(null);
    setImportSucceeded(false);
    setImportComplete(false);
    setUrlContent(null);
    setUrlFilename(null);
    setUrlMetadata(null);
    setUrlSource(null);
    setClipboardContent(null);
    setClipboardFilename(null);
    setGitContent(null);
    setGitFilename(null);
    setGitMetadata(null);
    setSwaggerHubContent(null);
    setSwaggerHubFilename(null);
    setSwaggerHubMetadata(null);
    setPostmanContent(null);
    setPostmanFilename(null);
    setPostmanMetadata(null);
    setErrorMessage(null);
    setJobsDrawerOpen(false);
    deltaRequestRef.current += 1;
    setProjectDelta({ status: 'idle' });
    setMergeChoice('replace');
    setArrayChoice('replace');
    dryRunRef.current = false;
  };

  const handleClose = async () => {
    // If opened from New Project AI, return to that conversation instead of closing to projects list
    if (openedFromNewProjectAI && onReturnToNewProjectAI) {
      if (jobId && currentStep === 'import') {
        try {
          await rollbackImport(jobId);
        } catch (e) {
          console.error('Failed to rollback import on close:', e);
        }
      }
      resetDialogState();
      onReturnToNewProjectAI();
      return;
    }

    // If there's a pending import job (during import step), roll back the transaction
    if (jobId && currentStep === 'import') {
      try {
        await rollbackImport(jobId);
      } catch (e) {
        console.error('Failed to rollback import on close:', e);
      }
    }

    // Call onSuccess callback if an import landed so the list refreshes.
    if (importSucceeded && onSuccess) {
      onSuccess();
    }

    resetDialogState();
    onClose();
  };

  const handleAnalyze = async () => {
    if (!selectedFile && !urlContent && !clipboardContent && !gitContent && !swaggerHubContent && !postmanContent) return;

    setErrorMessage(null);
    setIsAnalyzing(true);
    try {
      const content = urlContent || clipboardContent || gitContent || swaggerHubContent || postmanContent || await selectedFile!.text();
      const filename = urlFilename || clipboardFilename || gitFilename || swaggerHubFilename || postmanFilename || selectedFile?.name || 'openapi-spec.yaml';
      const result = await analyzeSpecification(content, filename);
      // FMT-1.1 (#5412): the local analyzer reads only the OpenAPI/Swagger/Arazzo family. When it
      // cannot place a document, ask the registry-wide detector what the bytes actually are and
      // report *its* verdict, instead of leaving the user with a bare parse error.
      if (!result.formatSupported) {
        setAdvisoryNotice(await detectAndDescribe(content, filename));
      } else {
        setAdvisoryNotice(null);
      }
      setAnalysisResult(result);
      setCurrentStep('analysis');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Analysis failed. Please check the specification and try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleUrlSpecificationFetched = (
    content: string,
    filename: string,
    metadata?: FileMetadataPreview,
    source?: UrlImportSource
  ) => {
    setUrlContent(content);
    setUrlFilename(filename);
    setUrlMetadata(metadata || null);
    setUrlSource(source ?? null);
    // Don't auto-analyze - user needs to click "Continue"
  };

  const handleClipboardSpecificationReady = (content: string, filename: string) => {
    setClipboardContent(content);
    setClipboardFilename(filename);
  };

  const handleGitSpecificationFetched = (content: string, filename: string, metadata?: FileMetadataPreview) => {
    setGitContent(content);
    setGitFilename(filename);
    setGitMetadata(metadata || null);
    // Don't auto-analyze - user needs to click "Analyze →" button
  };

  const handleSwaggerHubSpecificationFetched = (content: string, filename: string, metadata?: FileMetadataPreview) => {
    setSwaggerHubContent(content);
    setSwaggerHubFilename(filename);
    setSwaggerHubMetadata(metadata || null);
    // Don't auto-analyze - user needs to click "Analyze →" button
  };

  const handlePostmanSpecificationFetched = (content: string, filename: string, metadata?: FileMetadataPreview) => {
    setPostmanContent(content);
    setPostmanFilename(filename);
    setPostmanMetadata(metadata || null);
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      void handleFileSelect(files[0]);
    }
  };

  const handleFileSelect = async (file: File) => {
    // FMT-1.1 (#5412): the extension is a *hint*, not a gate. This used to reject anything outside a
    // hard-coded ten-entry list, which made thirty-three registered adapters unreachable. An
    // unrecognized name is now accepted and routed to detection — content sniffing decides the
    // format, and the detector's verdict is what the user is told if it turns out to be nothing.
    const recognized = isAcceptedImportFile(file.name, fileExtensions);

    setErrorMessage(null);
    setSelectedFile(file);
    setFileMetadata(null);
    setAdvisoryNotice(
      recognized
        ? null
        : `No import source claims the extension on "${file.name}". We'll analyze its contents anyway and tell you what it turns out to be.`,
    );

    // A ZIP is a bundle, not a document — it is only opened once Analyze runs.
    if (file.name.toLowerCase().endsWith('.zip')) return;

    setIsLoadingMetadata(true);
    try {
      const content = await file.text();
      setFileMetadata(extractFileMetadata(content));
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : 'Could not read or preview this file. Try another file or format.'
      );
    } finally {
      setIsLoadingMetadata(false);
    }
  };

  /**
   * The project slug the commit will use — Preview's slug, else one derived from the title.
   * Shared by the commit and the Changes comparison so both resolve the same project.
   */
  const importProjectSlug = (): string =>
    importOptions?.projectSlug ||
    generateSlug(analysisResult?.document?.info?.title || 'new-project') ||
    'imported-project';

  /**
   * Ask whether this import is a new version of an existing Project (IXH-3.7).
   *
   * @param fromPreview `true` when Preview's primary asked: a "not a new version" answer then goes
   *   straight on to the import. From the Changes step's retry it only refreshes the step.
   */
  const checkProjectDelta = async (fromPreview: boolean) => {
    if (!analysisResult || !importOptions) return;
    // An Arazzo workflow document is not an API version — there is nothing to compare.
    if (analysisResult.format === 'arazzo') {
      if (fromPreview) void beginImport();
      return;
    }
    const request = ++deltaRequestRef.current;
    setProjectDelta({ status: 'checking' });
    // A new comparison (another project or spec) starts from the default strategy (#591).
    if (fromPreview) {
      setMergeChoice('replace');
      setArrayChoice('replace');
    }
    const next = await fetchProjectDelta({
      document: analysisResult.document,
      project_slug: importProjectSlug(),
    });
    if (request !== deltaRequestRef.current) return; // the reader moved on
    setProjectDelta(next);
    if (!fromPreview) return;
    if (showsChangesStep(next)) setCurrentStep('changes');
    else void beginImport();
  };

  /** The version label Preview asks for. */
  const requestedVersionLabel = (): string =>
    importOptions?.targetVersion || analysisResult?.document?.info?.version || '1.0.0';

  /**
   * The version the import will create, when it lands in an existing project (#590): the requested
   * label, or the next free sub-version (`1.0.0b`) when the project already has it. `null` for a
   * first-time import, or when the comparison could not say.
   */
  const versionPlan =
    projectDelta.status === 'ready'
      ? planImportVersion(requestedVersionLabel(), projectDelta.delta.existing_version_labels)
      : null;

  const beginImport = async () => {
    if (!analysisResult || !importOptions) return;

    dryRunRef.current = Boolean(importOptions.dryRun);

    // Validate that we have required IDs
    if (!tenantId) {
      setErrorMessage('Import failed: no workspace is selected.');
      return;
    }
    if (!userId) {
      setErrorMessage('Import failed: you are not signed in.');
      return;
    }

    const document = analysisResult.document;
    const sourceKind = analysisResult.format === 'arazzo' ? 'arazzo' : 'openapi';
    const jobOptions = {
      selectedSchemas: importOptions.selectedSchemas,
      applyNamingConvention: importOptions.applyNamingConvention ?? true,
      classNamingConvention: importOptions.classNamingConvention ?? 'PascalCase',
      propertyNamingConvention: importOptions.propertyNamingConvention ?? 'camelCase',
      classNameMap: importOptions.classNameMap,
      classPrefix: (importOptions.classPrefix ?? '').trim() || undefined,
      classSuffix: (importOptions.classSuffix ?? '').trim() || undefined,
      typeMapping: importOptions.typeMapping,
      defaultValues: importOptions.defaultValues,
      requiredOverrides: importOptions.requiredOverrides,
      descriptionOverrides: importOptions.descriptionOverrides,
      generateExamples: importOptions.generateExamples ?? false,
      dryRun: importOptions.dryRun ?? false,
      incrementalMode: importOptions.incrementalMode ?? false,
      // #590: an import the Changes step showed lands in an existing project; if its label is taken
      // by the time it commits, the importer picks the next free sub-version rather than failing.
      ...(versionPlan ? { onVersionConflict: 'create-version' as const } : {}),
      // #591: the Changes step's merge strategy; only offered there, so only sent when it was shown.
      ...(showsChangesStep(projectDelta) && mergeChoice !== 'replace' ? { mergeStrategy: mergeChoice } : {}),
      // #595: how that merge combines arrays; only under a merge, and only when not the default.
      ...(showsChangesStep(projectDelta) && mergeChoice !== 'replace' && arrayChoice !== 'replace'
        ? { arrayMergeStrategy: arrayChoice }
        : {}),
    };
    const job = await startImport({
      tenantId,
      userId,
      sourceKind,
      document,
      project: {
        name: importOptions.projectName || (document?.info?.title || 'New Project'),
        slug: importProjectSlug(),
        description: document?.info?.description || null
      },
      version: {
        versionId: versionPlan?.label ?? requestedVersionLabel(),
        description: 'Imported from OpenAPI specification'
      },
      options: jobOptions
    });

    urlRecordRef.current =
      selectedSource === 'url' && !importOptions.dryRun
        ? { jobId: job.jobId, sourceKind, options: { ...jobOptions } }
        : null;
    setJobId(job.jobId);
    setCurrentStep('import');
  };

  /**
   * Whether the chosen intake has produced something Analyze can read.
   *
   * One expression rather than the six `disabled={…}` clauses the old footer carried, so the
   * "Analyze is offered exactly when there is content and the format is importable" rule holds
   * for every source rather than for whichever branch was edited last.
   */
  const intakeReady = useMemo(() => {
    switch (selectedSource) {
      case 'file':
        return Boolean(selectedFile) && (fileMetadata === null || fileMetadata.formatSupported);
      case 'url':
        return Boolean(urlContent) && (urlMetadata === null || urlMetadata.formatSupported);
      case 'clipboard':
      case 'llm':
        return Boolean(clipboardContent);
      case 'git':
        return Boolean(gitContent) && (gitMetadata === null || gitMetadata.formatSupported);
      case 'swaggerhub':
        return Boolean(swaggerHubContent) && (swaggerHubMetadata === null || swaggerHubMetadata.formatSupported);
      case 'postman':
        return Boolean(postmanContent) && (postmanMetadata === null || postmanMetadata.formatSupported);
      default:
        return false;
    }
  }, [
    selectedSource,
    selectedFile,
    fileMetadata,
    urlContent,
    urlMetadata,
    clipboardContent,
    gitContent,
    gitMetadata,
    swaggerHubContent,
    swaggerHubMetadata,
    postmanContent,
    postmanMetadata,
  ]);

  const footer = importFooterFor({
    step: currentStep,
    source: selectedSource,
    importComplete,
    importSucceeded,
    analyzing: isAnalyzing,
    intakeReady,
    analysisImportable: Boolean(analysisResult?.isValid && analysisResult?.formatSupported),
    hasSelection: Boolean(importOptions && importOptions.selectedSchemas.length > 0),
    checkingChanges: currentStep === 'preview' && projectDelta.status === 'checking',
  });

  const qualityGate = currentStep === 'analysis' ? importQualityGate(analysisResult) : null;

  /** The one forward action of the step the wizard is on. */
  const handlePrimary = () => {
    if (currentStep === 'analysis') {
      setCurrentStep('preview');
      return;
    }
    if (currentStep === 'preview') {
      void checkProjectDelta(true);
      return;
    }
    if (currentStep === 'changes') {
      void beginImport();
      return;
    }
    if (currentStep === 'import') {
      setCurrentStep('done');
      return;
    }
    if (currentStep === 'done') {
      void handleClose();
      return;
    }
    if (currentStep === 'file-upload') {
      void handleAnalyze();
    }
  };

  const handleCancel = () => {
    void handleClose();
  };

  const urlTest = urlTestAction(urlImportFooter);
  const showUrlTest = currentStep === 'file-upload' && selectedSource === 'url';

  /** The intake panel for the chosen source, or the card grid when none is chosen yet. */
  const renderStep = () => {
    if (currentStep === 'source') {
      return (
        <div className="flex flex-col gap-5">
          <ImportSourceCards
            cards={sourceCards}
            selected={selectedSource}
            onSelect={handleSourceClick}
            hotkeys
          />
          {/* HIVE-11.11: the space under the tiles shows the last three imports, when any. */}
          <RecentImportsList onShowAll={() => setJobsDrawerOpen(true)} />
        </div>
      );
    }

    if (currentStep === 'analysis' && analysisResult) {
      return (
        <div className="flex flex-col gap-4">
          {qualityGate ? (
            <Alert variant={qualityGate.tone}>
              <span className="font-semibold">{qualityGate.title}</span> — {qualityGate.body}
            </Alert>
          ) : null}
          <AnalysisPanel fileName={selectedFile?.name || ''} analysis={analysisResult} />
        </div>
      );
    }

    if (currentStep === 'preview' && analysisResult) {
      return <PreviewPanel analysis={analysisResult} onImportOptionsChange={setImportOptions} />;
    }

    if (currentStep === 'changes') {
      return (
        <ImportChangesPanel
          state={projectDelta}
          onRetry={() => void checkProjectDelta(false)}
          versionPlan={versionPlan}
          mergeChoice={mergeChoice}
          onMergeChoiceChange={setMergeChoice}
          arrayChoice={arrayChoice}
          onArrayChoiceChange={setArrayChoice}
        />
      );
    }

    if (currentStep === 'import' && jobId) {
      return (
        <ImportExecutionPanel
          jobId={jobId}
          selectedSchemas={importOptions?.selectedSchemas ?? []}
          isReviewing={importComplete}
          onComplete={(succeeded) => {
            setImportComplete(true);
            setImportSucceeded(succeeded);
          }}
          onRetry={(newJobId) => {
            setJobId(newJobId);
            setImportComplete(false);
          }}
        />
      );
    }

    if (currentStep === 'done') {
      return jobId ? <ImportCompletePanel jobId={jobId} /> : null;
    }

    // Everything below is the intake step: the tab bar, then the chosen source's panel.
    const intake = (() => {
      switch (selectedSource) {
        case 'file':
          return (
            <FileIntakePanel
              extensions={fileExtensions}
              file={selectedFile}
              metadata={fileMetadata}
              loading={isLoadingMetadata}
              dragging={isDragging}
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onPick={(file) => void handleFileSelect(file)}
              onRemove={() => {
                setSelectedFile(null);
                setFileMetadata(null);
                setAdvisoryNotice(null);
              }}
            />
          );
        case 'url':
          return (
            <UrlImportPanel
              ref={urlImportRef}
              onSpecificationFetched={handleUrlSpecificationFetched}
              onFooterStateChange={handleUrlImportFooterState}
            />
          );
        case 'clipboard':
        case 'llm':
          return <ClipboardImportPanel onSpecificationReady={handleClipboardSpecificationReady} />;
        case 'git':
          return <GitImportPanel userId={userId} onSpecificationFetched={handleGitSpecificationFetched} />;
        case 'swaggerhub':
          return <SwaggerHubImportPanel onSpecificationFetched={handleSwaggerHubSpecificationFetched} />;
        case 'postman':
          return <PostmanImportPanel onSpecificationFetched={handlePostmanSpecificationFetched} />;
        default:
          return null;
      }
    })();

    return (
      <div className="flex min-h-0 flex-col gap-4">
        <ImportIntakeTabs cards={sourceCards} active={selectedSource} onSelect={handleSourceClick} />
        {intake}
      </div>
    );
  };

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) void handleClose();
        }}
      >
        {/* HIVE-11.11: `lg` and as tall as the step needs (up to the viewport), not a fixed
            full-height sheet that leaves the source step half empty. `steps` gives it a
            height floor and a fixed top edge, so the frame holds still between steps. */}
        <DialogContent
          size="lg"
          steps
          className="imp-wizard imp-wizard--fit"
          closeLabel={IMPORT_WIZARD_COPY.closeWarning}
        >
          <ImportWizardHead
            actions={
              <Button variant="ghost" size="sm" onClick={() => setJobsDrawerOpen(true)}>
                <ListChecks aria-hidden />
                {IMPORT_WIZARD_COPY.jobsDrawerTitle}
              </Button>
            }
          />
          <ImportWizardSteps
            steps={importWizardStepsFor(showsChangesStep(projectDelta))}
            current={stepperIdFor(currentStep)}
            complete={currentStep === 'done'}
          />
          <ImportWizardBody>
            {errorMessage ? (
              <Alert variant="danger" className="mb-4">
                {errorMessage}
              </Alert>
            ) : null}
            {/*
              FMT-1.1 (#5412): an extension no adapter declares is a *warning*, not a rejection —
              the file is analyzed anyway and detection decides. `info`, never `danger`: nothing has
              failed yet, and the common case is a correctly-named file of a format whose adapter
              simply does not spell that suffix.
            */}
            {advisoryNotice ? (
              <Alert variant="info" className="mb-4" data-testid="import-advisory-notice">
                {advisoryNotice}
              </Alert>
            ) : null}
            {renderStep()}
          </ImportWizardBody>
          <ImportWizardFooter
            footer={footer}
            onBack={handleBack}
            onCancel={handleCancel}
            onPrimary={handlePrimary}
            extra={
              showUrlTest ? (
                <Button
                  variant={urlTest.tested ? 'success' : 'outline'}
                  onClick={() => void urlImportRef.current?.testUrl()}
                  disabled={urlTest.disabled}
                >
                  {urlTest.label}
                </Button>
              ) : undefined
            }
          />
        </DialogContent>
      </Dialog>
      <RecentImportJobsDrawer open={jobsDrawerOpen} onOpenChange={setJobsDrawerOpen} />
    </>
  );
};

export default ImportDialog;
