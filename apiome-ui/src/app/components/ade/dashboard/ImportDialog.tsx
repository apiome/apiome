'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { Upload, X, FileCode, AlertTriangle, CheckCircle2, ArrowRight } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { Alert } from '../../../components/ui/Alert';
import { Button } from '../../../components/ui/Button';
import { AnalysisPanel } from './AnalysisPanel';
import { PreviewPanel, ImportOptions } from './PreviewPanel';
import { analyzeSpecification, AnalysisResult, extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import ImportExecutionPanel from './ImportExecutionPanel';
import ImportCompletePanel from './ImportCompletePanel';
import UrlImportPanel, { type UrlImportPanelHandle, type UrlImportFooterState } from './UrlImportPanel';
import { ImportSourceTabBar, type ImportSourceTabId } from './ImportSourceTabBar';
import { useImportSources } from './useImportSources';
import { type ImportVariant } from './importSourceCatalog';
import ClipboardImportPanel from './ClipboardImportPanel';
import GitImportPanel from './GitImportPanel';
import SwaggerHubImportPanel from './SwaggerHubImportPanel';
import PostmanImportPanel from './PostmanImportPanel';
import McpImportPanel from './McpImportPanel';
import McpDiscoveryPanel from './McpDiscoveryPanel';
import {
  buildCreateEndpointBody,
  buildCredentialBody,
  emptyMcpImportForm,
  validateMcpImportForm,
  type McpImportForm,
} from './mcp/mcpImportFlow';
import { startImport, getImportStatus, rollbackImport } from '../../../../../lib/db/import-actions';
import { generateSlug } from '../../../utils/slug';
import { appendProjectQualitySnapshot, buildQualitySnapshotReportExtras } from '../../../utils/project-quality-score-history';

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
  /** When set, the dialog opens straight onto this import source (e.g. 'mcp' from MCP Servers). */
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
  const [currentStep, setCurrentStep] = useState<'source' | 'file-upload' | 'analysis' | 'preview' | 'import' | 'done'>('source');
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileMetadata, setFileMetadata] = useState<FileMetadataPreview | null>(null);
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

  // MCP Server import source (V2-MCP-24.1): collect endpoint config, then create → discover → poll.
  const [mcpForm, setMcpForm] = useState<McpImportForm>(emptyMcpImportForm);
  const [mcpEndpointId, setMcpEndpointId] = useState<string | null>(null);
  const [mcpEndpointName, setMcpEndpointName] = useState<string>('');
  const [mcpJobId, setMcpJobId] = useState<string | null>(null);
  const [mcpSubmitting, setMcpSubmitting] = useState(false);
  // A created endpoint is "committed" only once discovery succeeds, or the user explicitly keeps a
  // failed one ("Add this server anyway"). An uncommitted endpoint is discarded (deleted) on
  // back/cancel/close so a failed auth/scan never lingers in the catalog.
  const [mcpEndpointCommitted, setMcpEndpointCommitted] = useState(false);

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
  const { cards: sourceCards } = useImportSources(open, variant);

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

  // When opened with a pre-selected source (e.g. 'mcp' from MCP Servers), jump straight to it.
  useEffect(() => {
    if (!open || !initialSource) return;
    onConsumeInitialSource?.();
    setErrorMessage(null);
    setSelectedSource(initialSource);
    setCurrentStep('file-upload');
  }, [open, initialSource, onConsumeInitialSource]);

  const handleSourceClick = (source: string | ImportSourceTabId) => {
    setErrorMessage(null);
    setSelectedSource(source);
    setCurrentStep('file-upload');
    console.log('Selected source:', source);
  };

  /** Discard a catalog endpoint (best-effort) — used to clean up a failed/abandoned MCP import. */
  const deleteMcpEndpoint = async (id: string) => {
    try {
      await fetch(`/api/mcp/endpoints/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
    } catch {
      // Best-effort cleanup — ignore failures (the row is soft-deleted server-side when reached).
    }
  };

  /** Explicitly discard a failed MCP import: delete the endpoint and close the dialog. */
  const discardMcpAndClose = async () => {
    if (mcpEndpointId) {
      await deleteMcpEndpoint(mcpEndpointId);
    }
    resetDialogState();
    onClose();
  };

  const handleBack = () => {
    setErrorMessage(null);
    if (currentStep === 'done') {
      setCurrentStep('preview');
    } else if (currentStep === 'import' && selectedSource === 'mcp') {
      // MCP has no analyze/preview steps — Back returns to the endpoint config form. An uncommitted
      // endpoint (failed/in-progress scan the user didn't keep) is discarded on the way out.
      if (mcpEndpointId && !mcpEndpointCommitted) {
        void deleteMcpEndpoint(mcpEndpointId);
        setMcpEndpointId(null);
        setMcpEndpointName('');
      }
      setCurrentStep('file-upload');
      setMcpJobId(null);
      setImportComplete(false);
      setImportSucceeded(false);
    } else if (currentStep === 'import') {
      setCurrentStep('preview');
      setJobId(null);
    } else if (currentStep === 'preview') {
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
      setUrlContent(null);
      setUrlFilename(null);
      setUrlMetadata(null);
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
      setMcpForm(emptyMcpImportForm());
      setMcpEndpointId(null);
      setMcpEndpointName('');
      setMcpJobId(null);
    }
  };

  const resetDialogState = () => {
    setCurrentStep('source');
    setSelectedSource(null);
    setSelectedFile(null);
    setFileMetadata(null);
    setAnalysisResult(null);
    setImportOptions(null);
    setJobId(null);
    setImportSucceeded(false);
    setImportComplete(false);
    setUrlContent(null);
    setUrlFilename(null);
    setUrlMetadata(null);
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
    setMcpForm(emptyMcpImportForm());
    setMcpEndpointId(null);
    setMcpEndpointName('');
    setMcpJobId(null);
    setMcpSubmitting(false);
    setMcpEndpointCommitted(false);
    setErrorMessage(null);
    dryRunRef.current = false;
  };

  const handleClose = async () => {
    // Discard a created-but-uncommitted MCP endpoint: auth/scan failed (or was still running) and the
    // user did not choose "Add this server anyway", so it must not linger in the catalog.
    if (selectedSource === 'mcp' && mcpEndpointId && !mcpEndpointCommitted) {
      await deleteMcpEndpoint(mcpEndpointId);
    }

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

    // Call onSuccess callback if an import landed (a spec import succeeded, or an MCP endpoint was
    // committed — discovered, or explicitly kept via "Add this server anyway") so the list refreshes.
    if ((importSucceeded || mcpEndpointCommitted) && onSuccess) {
      onSuccess();
    }

    resetDialogState();
    onClose();
  };

  const handleAnalyze = async () => {
    if (!selectedFile && !urlContent && !clipboardContent && !gitContent && !swaggerHubContent && !postmanContent) return;

    setErrorMessage(null);
    console.log('Starting analysis...', {
      selectedFile: selectedFile?.name,
      urlFilename,
      clipboardFilename,
      gitFilename,
      swaggerHubFilename,
      postmanFilename,
      hasUrlContent: !!urlContent,
      hasClipboardContent: !!clipboardContent,
      hasGitContent: !!gitContent,
      hasSwaggerHubContent: !!swaggerHubContent,
      hasPostmanContent: !!postmanContent
    });
    setIsAnalyzing(true);
    try {
      const content = urlContent || clipboardContent || gitContent || swaggerHubContent || postmanContent || await selectedFile!.text();
      const filename = urlFilename || clipboardFilename || gitFilename || swaggerHubFilename || postmanFilename || selectedFile?.name || 'openapi-spec.yaml';
      console.log('Content loaded, length:', content.length);
      const result = await analyzeSpecification(content, filename);
      console.log('Analysis complete:', result);
      setAnalysisResult(result);
      setCurrentStep('analysis');
      console.log('State updated to analysis step');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Analysis failed. Please check the specification and try again.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleUrlSpecificationFetched = (content: string, filename: string, metadata?: FileMetadataPreview) => {
    setUrlContent(content);
    setUrlFilename(filename);
    setUrlMetadata(metadata || null);
    // Don't auto-analyze - user needs to click "Analyze →" button
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
      handleFileSelect(files[0]);
    }
  };

  const handleFileSelect = async (file: File) => {
    const validExtensions = ['.yaml', '.yml', '.json', '.zip', '.graphql', '.gql', '.raml', '.proto', '.avsc', '.thrift'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

    if (validExtensions.includes(fileExtension)) {
      setErrorMessage(null);
      setSelectedFile(file);
      setFileMetadata(null);
      console.log('File selected:', file.name);

      // Extract metadata immediately for preview
      if (fileExtension !== '.zip') {
        setIsLoadingMetadata(true);
        try {
          const content = await file.text();
          const metadata = extractFileMetadata(content);
          setFileMetadata(metadata);
          console.log('File metadata extracted:', metadata);
        } catch (error) {
          setErrorMessage(
            error instanceof Error ? error.message : 'Could not read or preview this file. Try another file or format.'
          );
        } finally {
          setIsLoadingMetadata(false);
        }
      }
    } else {
      setSelectedFile(null);
      setFileMetadata(null);
      setErrorMessage(`Unsupported file type. Allowed: ${validExtensions.join(', ')}`);
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const beginImport = async () => {
    if (!analysisResult || !importOptions) return;

    dryRunRef.current = Boolean(importOptions.dryRun);

    // Validate that we have required IDs
    if (!tenantId) {
      console.error('Import failed: No tenant ID available');
      return;
    }
    if (!userId) {
      console.error('Import failed: No user ID available');
      return;
    }

    const document = analysisResult.document;
    const sourceKind = analysisResult.format === 'arazzo' ? 'arazzo' : 'openapi';
    const job = await startImport({
      tenantId,
      userId,
      sourceKind,
      document,
      project: {
        name: importOptions.projectName || (document?.info?.title || 'New Project'),
        slug: importOptions.projectSlug || generateSlug(document?.info?.title || 'new-project') || 'imported-project',
        description: document?.info?.description || null
      },
      version: {
        versionId: importOptions.targetVersion || (document?.info?.version || '1.0.0'),
        description: 'Imported from OpenAPI specification'
      },
      options: {
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
        incrementalMode: importOptions.incrementalMode ?? false
      }
    });

    setJobId(job.jobId);
    setCurrentStep('import');
  };

  /**
   * MCP source: create the catalog endpoint, store any credential, then kick off a discovery run
   * and advance to the live-status step. The discovery commits catalog version 1 on success.
   *
   * If anything before the scan fails (registration, credential storage, or starting discovery), the
   * just-created endpoint is discarded so a half-wired entry never shows up in the catalog.
   */
  const beginMcpImport = async () => {
    const validationError = validateMcpImportForm(mcpForm);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setErrorMessage(null);
    setMcpSubmitting(true);
    // Tracks the endpoint created in this attempt so a pre-scan failure can discard it.
    let createdId: string | null = null;
    try {
      // 1. Create the endpoint.
      const createBody = buildCreateEndpointBody(mcpForm);
      const createRes = await fetch('/api/mcp/endpoints', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createBody),
      });
      const createData = await createRes.json().catch(() => ({}));
      if (!createRes.ok) {
        throw new Error(typeof createData.error === 'string' ? createData.error : 'Could not register the MCP server.');
      }
      const endpoint = createData.endpoint as { id?: string; name?: string } | undefined;
      const endpointId = endpoint?.id;
      if (!endpointId) {
        throw new Error('The MCP server was created but no id was returned.');
      }
      createdId = endpointId;
      setMcpEndpointId(endpointId);
      setMcpEndpointName(endpoint?.name || createBody.name);
      setMcpEndpointCommitted(false);

      // 2. Store the credential, when an auth type was chosen.
      const credentialBody = buildCredentialBody(mcpForm);
      if (credentialBody) {
        const credRes = await fetch(`/api/mcp/endpoints/${encodeURIComponent(endpointId)}/credentials`, {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(credentialBody),
        });
        if (!credRes.ok) {
          const credData = await credRes.json().catch(() => ({}));
          throw new Error(typeof credData.error === 'string' ? credData.error : 'Could not store the credential.');
        }
      }

      // 3. Kick off discovery.
      const discoverRes = await fetch(`/api/mcp/endpoints/${encodeURIComponent(endpointId)}/discover`, {
        method: 'POST',
        credentials: 'include',
      });
      const discoverData = await discoverRes.json().catch(() => ({}));
      if (!discoverRes.ok) {
        throw new Error(typeof discoverData.error === 'string' ? discoverData.error : 'Could not start discovery.');
      }
      const startedJob = discoverData.job as { id?: string } | undefined;
      if (!startedJob?.id) {
        throw new Error('Discovery did not start.');
      }

      setMcpJobId(startedJob.id);
      setImportComplete(false);
      setImportSucceeded(false);
      setCurrentStep('import');
    } catch (error) {
      // Registration / credential / discovery-trigger failed before the scan could run — discard the
      // half-wired endpoint so it never appears in the catalog, and let the user fix the form.
      if (createdId) {
        await deleteMcpEndpoint(createdId);
        setMcpEndpointId(null);
        setMcpEndpointName('');
      }
      setErrorMessage(error instanceof Error ? error.message : 'Could not import the MCP server.');
    } finally {
      setMcpSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) void handleClose();
      }}
    >
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden flex flex-col" showCloseButton={false} aria-describedby={undefined}>
        <DialogHeader className="border-b border-gray-200 dark:border-gray-700 pb-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-2xl font-bold text-gray-900 dark:text-white">
              Import Specification
            </DialogTitle>
            <button
              onClick={handleClose}
              className="rounded-lg p-2 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <X className="h-5 w-5 text-gray-500 dark:text-gray-400" />
            </button>
          </div>
        </DialogHeader>

        {/* Step Indicator - Fixed */}
        <div className="border-b border-gray-200 dark:border-gray-700 py-4 px-6">
          <div className="flex items-center justify-center gap-2 text-sm">
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'source' || currentStep === 'file-upload' 
                  ? 'bg-indigo-600 text-white'
                  : 'bg-green-600 text-white'
              }`}>
                {currentStep === 'analysis' || currentStep === 'preview' || currentStep === 'import' || currentStep === 'done' ? '✓' : '1'}
              </div>
              <span className={`ml-2 font-medium ${
                currentStep !== 'source' ? 'text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'
              }`}>Source</span>
            </div>
            <div className={`w-16 h-0.5 ${
              ['analysis','preview','import','done'].includes(currentStep) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
            }`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'analysis'
                  ? 'bg-indigo-600 text-white'
                  : ['preview','import','done'].includes(currentStep)
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}>
                {['preview','import','done'].includes(currentStep) ? '✓' : '2'}
              </div>
              <span className={`ml-2 ${
                ['analysis','preview','import','done'].includes(currentStep)
                  ? 'font-medium text-gray-900 dark:text-white'
                  : 'text-gray-500 dark:text-gray-400'
              }`}>Analyze</span>
            </div>
            <div className={`w-16 h-0.5 ${
              ['preview','import','done'].includes(currentStep) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
            }`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'preview'
                  ? 'bg-indigo-600 text-white'
                  : ['import','done'].includes(currentStep)
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}>
                {['import','done'].includes(currentStep) ? '✓' : '3'}
              </div>
              <span className={`ml-2 ${
                ['preview','import','done'].includes(currentStep)
                  ? 'font-medium text-gray-900 dark:text-white'
                  : 'text-gray-500 dark:text-gray-400'
              }`}>Preview</span>
            </div>
            <div className={`w-16 h-0.5 ${
              ['import','done'].includes(currentStep) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'
            }`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full font-semibold ${
                currentStep === 'import'
                  ? 'bg-indigo-600 text-white'
                  : currentStep === 'done'
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
              }`}>
                {currentStep === 'done' ? '✓' : '4'}
              </div>
              <span className={`ml-2 ${
                ['import','done'].includes(currentStep)
                  ? 'font-medium text-gray-900 dark:text-white'
                  : 'text-gray-500 dark:text-gray-400'
              }`}>Import</span>
            </div>
            <div className={`w-16 h-0.5 ${ currentStep === 'done' ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600' }`}></div>
            <div className="flex items-center">
              <div className={`flex items-center justify-center w-8 h-8 rounded-full ${ currentStep === 'done' ? 'bg-indigo-600 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400' } font-semibold`}>
                5
              </div>
              <span className={`ml-2 ${ currentStep === 'done' ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400' }`}>Done</span>
            </div>
          </div>
        </div>

        {/* Scrollable Content Area */}
        <div className="flex flex-col min-h-0 overflow-y-auto py-6 px-6 h-[60vh]">
          {errorMessage && (
            <Alert variant="error" className="mb-4 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              {errorMessage}
            </Alert>
          )}
          {(() => {
            console.log('Render check:', { currentStep, selectedSource, hasAnalysisResult: !!analysisResult });

            if (currentStep === 'source') {
              console.log('Rendering: Source selection');
              return (
            <>
              {/* Choose Import Source */}
              <div className="mb-8">
                <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/30 dark:to-purple-950/30 rounded-xl border-2 border-indigo-200 dark:border-indigo-800 p-6">
                  <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-6 text-center">
                    Choose Import Source
                  </h2>

                  {/* Source Options Grid */}
              {/*
                MFI-1.3: cards are data-driven (built-ins + registry adapters). Adding an adapter
                server-side makes a new card appear here with no change to this JSX. A card whose
                adapter has no generic intake panel yet (discovery-only) renders disabled.
              */}
              <div className="grid grid-cols-3 gap-4 mb-4">
                {sourceCards.map((card) => {
                  const Icon = card.icon;
                  const isDisabled = card.panel === null;
                  const isActive = !isDisabled && selectedSource === card.panel;
                  return (
                    <button
                      key={card.key}
                      type="button"
                      onClick={() => card.panel && handleSourceClick(card.panel)}
                      disabled={isDisabled}
                      title={isDisabled ? 'Coming soon' : undefined}
                      aria-label={card.label}
                      className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                        isDisabled
                          ? 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 opacity-60 cursor-not-allowed'
                          : isActive
                            ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                            : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                      }`}
                    >
                      <div className="flex flex-col items-center text-center">
                        <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                          isActive
                            ? 'bg-indigo-500 text-white'
                            : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                        }`}>
                          <Icon className="h-6 w-6" />
                        </div>
                        <div className={`font-semibold mb-1 ${
                          isActive ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                        }`}>
                          {card.label}
                        </div>
                        <div className="text-xs text-gray-600 dark:text-gray-400">
                          {card.description}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
            </>
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'mcp') {
              return (
                <McpImportPanel form={mcpForm} onChange={setMcpForm} />
              );
            } else if (currentStep === 'import' && selectedSource === 'mcp' && mcpEndpointId && mcpJobId) {
              return (
                <McpDiscoveryPanel
                  endpointId={mcpEndpointId}
                  jobId={mcpJobId}
                  endpointName={mcpEndpointName}
                  onComplete={(succeeded) => {
                    setImportSucceeded(succeeded);
                    setImportComplete(true);
                    // A successful scan commits the endpoint; a failed scan leaves it uncommitted so
                    // it is discarded unless the user picks "Add this server anyway".
                    if (succeeded) setMcpEndpointCommitted(true);
                  }}
                />
              );
            } else if (currentStep === 'done' && selectedSource === 'mcp') {
              return (
                <div className="flex flex-1 flex-col items-center justify-center gap-4 py-10 text-center">
                  <div
                    className={`flex h-16 w-16 items-center justify-center rounded-2xl text-white ${
                      importSucceeded ? 'bg-green-500' : 'bg-amber-500'
                    }`}
                  >
                    {importSucceeded ? (
                      <CheckCircle2 className="h-8 w-8" aria-hidden />
                    ) : (
                      <AlertTriangle className="h-8 w-8" aria-hidden />
                    )}
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                      {importSucceeded ? `${mcpEndpointName} cataloged` : `${mcpEndpointName} added`}
                    </h3>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                      {importSucceeded ? (
                        <>
                          Discovery committed catalog version&nbsp;1. Its tools, resources, and prompts
                          are now available under MCP Servers.
                        </>
                      ) : (
                        <>
                          Discovery did not complete, so this server has no cataloged capabilities yet.
                          Fix its connection or credentials, then re-run discovery from its page.
                        </>
                      )}
                    </p>
                  </div>
                  {mcpEndpointId && (
                    <Link
                      href={`/ade/dashboard/mcp/${mcpEndpointId}`}
                      onClick={() => void handleClose()}
                      className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                    >
                      View endpoint
                      <ArrowRight className="h-4 w-4" aria-hidden />
                    </Link>
                  )}
                </div>
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'file') {
              console.log('Rendering: File upload');
              return (
            <>
              {/* Step 1a: File Upload View */}

              <div className="mb-6">
                <ImportSourceTabBar active="file" onSelect={(id) => handleSourceClick(id)} />
              </div>

              {/* Drop Zone */}
              <div className="mb-6">
                <div
                  onDragEnter={handleDragEnter}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`border-2 border-dashed rounded-xl p-12 text-center transition-all ${
                    isDragging
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                      : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-600'
                  }`}
                >
                  <div className="flex flex-col items-center gap-4">
                    <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${
                      isDragging
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-400'
                    }`}>
                      <Upload className="h-8 w-8" />
                    </div>

                    {selectedFile ? (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                          <FileCode className="h-5 w-5" />
                          <span className="font-medium">{selectedFile.name}</span>
                        </div>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          {(selectedFile.size / 1024).toFixed(2)} KB
                        </p>
                        <button
                          onClick={() => {
                            setSelectedFile(null);
                            setFileMetadata(null);
                          }}
                          className="text-sm text-red-600 dark:text-red-400 hover:underline"
                        >
                          Remove file
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="space-y-2">
                          <p className="text-lg font-medium text-gray-900 dark:text-white">
                            Drop files here
                          </p>
                          <p className="text-sm text-gray-600 dark:text-gray-400">
                            or
                          </p>
                        </div>

                        <label className="cursor-pointer">
                          <input
                            type="file"
                            className="hidden"
                            accept=".yaml,.yml,.json,.zip,.graphql,.gql,.raml,.proto,.avsc,.thrift"
                            onChange={handleFileInputChange}
                          />
                          <span className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors shadow-sm">
                            <Upload className="h-5 w-5" />
                            Browse Files
                          </span>
                        </label>

                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          Supports: .yaml, .yml, .json, .zip, .graphql, .gql, .raml, .proto, .avsc, .thrift
                        </p>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* File Metadata Preview */}
              {selectedFile && (
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                    <FileCode className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
                    File Preview
                  </h3>

                  {isLoadingMetadata ? (
                    <div className="flex items-center justify-center py-8">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 dark:border-indigo-400"></div>
                      <span className="ml-3 text-gray-600 dark:text-gray-400">Analyzing file...</span>
                    </div>
                  ) : fileMetadata ? (
                    <div className="space-y-4">
                      {/* Unsupported Format Warning */}
                      {!fileMetadata.formatSupported && fileMetadata.format !== 'unknown' && (
                        <div className="p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-medium text-amber-900 dark:text-amber-200">
                                Format Not Available for Import
                              </div>
                              <div className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                                The detected format <span className="font-semibold">{fileMetadata.formatDisplayName}</span> is not yet supported for import.
                                Currently supported formats: OpenAPI 3.x, Swagger 2.x, JSON Schema, Arazzo, RAML, AsyncAPI, GraphQL, Protobuf, Thrift, Avro, and Postman.
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Parse Error */}
                      {!fileMetadata.syntaxValid && (
                        <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-medium text-red-900 dark:text-red-200">
                                File Parse Error
                              </div>
                              <div className="text-sm text-red-700 dark:text-red-300 mt-1">
                                {fileMetadata.parseError || 'Unable to parse file content'}
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Metadata Grid */}
                      <div className="grid grid-cols-3 gap-4">
                        {/* Format */}
                        <div className={`rounded-lg p-4 border ${fileMetadata.formatSupported ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'}`}>
                          <div className="flex items-center gap-2 mb-2">
                            {fileMetadata.formatSupported ? (
                              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                            ) : (
                              <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                            )}
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Detected Format
                            </span>
                          </div>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {fileMetadata.formatDisplayName}
                          </div>
                        </div>

                        {/* Spec Version */}
                        <div className="rounded-lg p-4 border bg-gray-50 dark:bg-gray-900/30 border-gray-200 dark:border-gray-700">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Version
                            </span>
                          </div>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {fileMetadata.specVersion || fileMetadata.version || 'N/A'}
                          </div>
                        </div>

                        {/* Syntax */}
                        <div className={`rounded-lg p-4 border ${fileMetadata.syntaxValid ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'}`}>
                          <div className="flex items-center gap-2 mb-2">
                            {fileMetadata.syntaxValid ? (
                              <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
                            ) : (
                              <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
                            )}
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Syntax
                            </span>
                          </div>
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {fileMetadata.syntaxValid ? `Valid ${fileMetadata.syntax.toUpperCase()}` : 'Invalid'}
                          </div>
                        </div>
                      </div>

                      {/* Title */}
                      {fileMetadata.title && (
                        <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Title
                          </span>
                          <div className="text-base font-semibold text-gray-900 dark:text-white mt-1">
                            {fileMetadata.title}
                          </div>
                        </div>
                      )}

                      {/* Description */}
                      {fileMetadata.description && (
                        <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                            Description
                          </span>
                          <div className="text-sm text-gray-700 dark:text-gray-300 mt-1 leading-relaxed line-clamp-3">
                            {fileMetadata.description}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-center py-4 text-gray-500 dark:text-gray-400">
                      <p className="text-sm">ZIP files will be analyzed after clicking Analyze</p>
                    </div>
                  )}
                </div>
              )}
            </>
              );
            } else if (currentStep === 'analysis' && analysisResult) {
              console.log('Rendering: Analysis panel');
              return (
            <>
              {/* Step 2: Analysis Panel */}
              <AnalysisPanel fileName={selectedFile?.name || ''} analysis={analysisResult} />
            </>
              );
            } else if (currentStep === 'preview' && analysisResult) {
              console.log('Rendering: Preview panel');
              return (
            <>
              {/* Step 3: Preview Panel */}
              <PreviewPanel
                analysis={analysisResult}
                onImportOptionsChange={setImportOptions}
              />
            </>
              );
            } else if (currentStep === 'import' && jobId) {
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
            } else if (currentStep === 'done') {
              return jobId ? (
                <ImportCompletePanel jobId={jobId} />
              ) : null;
            } else if (currentStep === 'file-upload' && selectedSource === 'url') {
              console.log('Rendering: URL import panel');
              return (
                <UrlImportPanel
                  ref={urlImportRef}
                  onSpecificationFetched={handleUrlSpecificationFetched}
                  onSelectSource={(id) => handleSourceClick(id)}
                  onFooterStateChange={handleUrlImportFooterState}
                />
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'clipboard') {
              console.log('Rendering: Clipboard import panel');
              return (
                <ClipboardImportPanel
                  onSpecificationReady={handleClipboardSpecificationReady}
                />
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'git') {
              console.log('Rendering: Git import panel');
              return (
                <div className="flex flex-col flex-1 min-h-0">
                  <GitImportPanel
                    userId={userId}
                    onSpecificationFetched={handleGitSpecificationFetched}
                  />
                </div>
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'swaggerhub') {
              console.log('Rendering: SwaggerHub import panel');
              return (
                <SwaggerHubImportPanel
                  onSpecificationFetched={handleSwaggerHubSpecificationFetched}
                />
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'postman') {
              console.log('Rendering: Postman import panel');
              return (
                <PostmanImportPanel
                  onSpecificationFetched={handlePostmanSpecificationFetched}
                />
              );
            } else if (selectedSource) {
              console.log('Rendering: Placeholder for', selectedSource);
              return (
            <>
              {/* Placeholder for other source views (Clipboard, etc.) */}
              <div className="text-center py-12">
                <p className="text-gray-600 dark:text-gray-400">
                  {selectedSource} import view - Coming soon
                </p>
              </div>
            </>
              );
            } else {
              console.log('Rendering: Nothing');
              return null;
            }
          })()}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between bg-gray-50 dark:bg-gray-800/50">
          {currentStep === 'done' ? (
            <>
              <Button variant="outline" onClick={() => setCurrentStep('import')}>
                ← Back
              </Button>
              <Button
                onClick={handleClose}
                className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
              >
                Done
              </Button>
            </>
          ) : currentStep === 'import' ? (
            <>
              <Button variant="outline" onClick={handleBack} disabled={!importComplete}>
                ← Back
              </Button>
              <div className="flex gap-2">
                {/* If import complete but failed/rolled back, just show Cancel */}
                {importComplete && !importSucceeded ? (
                  selectedSource === 'mcp' ? (
                    // Failed auth/scan: discard by default (Discard / Close / Back all delete the
                    // endpoint) unless the user explicitly keeps it.
                    <>
                      <Button variant="outline" onClick={() => void discardMcpAndClose()}>
                        Discard
                      </Button>
                      <Button
                        onClick={() => {
                          setMcpEndpointCommitted(true);
                          setCurrentStep('done');
                        }}
                        className="bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700"
                      >
                        Add this server anyway
                      </Button>
                    </>
                  ) : (
                    <Button variant="outline" onClick={handleClose}>
                      Cancel
                    </Button>
                  )
                ) : (
                  <>
                    <Button variant="outline" onClick={handleClose}>
                      {importComplete ? 'Close' : 'Cancel'}
                    </Button>
                    {importComplete && importSucceeded && (
                      <Button
                        onClick={() => setCurrentStep('done')}
                        className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                      >
                        Next →
                      </Button>
                    )}
                  </>
                )}
              </div>
            </>
          ) : currentStep !== 'source' ? (
            <>
              <Button variant="outline" onClick={handleBack}>
                ← Back
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={handleClose}>
                  Cancel
                </Button>
                {currentStep === 'file-upload' && selectedSource === 'url' && (
                  <Button
                    variant="outline"
                    onClick={() => void urlImportRef.current?.testUrl()}
                    disabled={!urlImportFooter.canTestUrl || urlImportFooter.isTesting}
                    className={
                      urlImportFooter.urlTestedSuccessfully
                        ? 'border-green-500 text-green-600 dark:border-green-500 dark:text-green-400'
                        : undefined
                    }
                  >
                    {urlImportFooter.isTesting
                      ? 'Testing...'
                      : urlImportFooter.urlTestedSuccessfully
                        ? 'URL tested ✓'
                        : 'Test URL'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'file' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!selectedFile || isAnalyzing || (fileMetadata !== null && !fileMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'url' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!urlContent || isAnalyzing || (urlMetadata !== null && !urlMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Next →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'clipboard' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!clipboardContent || isAnalyzing}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'git' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!gitContent || isAnalyzing || (gitMetadata !== null && !gitMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'swaggerhub' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!swaggerHubContent || isAnalyzing || (swaggerHubMetadata !== null && !swaggerHubMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'postman' && (
                  <Button
                    onClick={handleAnalyze}
                    disabled={!postmanContent || isAnalyzing || (postmanMetadata !== null && !postmanMetadata.formatSupported)}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
                  </Button>
                )}
                {currentStep === 'file-upload' && selectedSource === 'mcp' && (
                  <Button
                    onClick={beginMcpImport}
                    disabled={mcpSubmitting || validateMcpImportForm(mcpForm) !== null}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    {mcpSubmitting ? 'Starting…' : 'Discover →'}
                  </Button>
                )}
                {currentStep === 'analysis' && (
                  <Button
                    onClick={() => {
                      setCurrentStep('preview');
                    }}
                    disabled={!analysisResult?.isValid || !analysisResult?.formatSupported}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    Next →
                  </Button>
                )}
                {currentStep === 'preview' && (
                  <Button
                    onClick={beginImport}
                    disabled={!importOptions || importOptions.selectedSchemas.length === 0}
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
                  >
                    Import →
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  // This is handled by handleSourceClick
                }}
                disabled={!selectedSource}
                className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
              >
                Next →
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ImportDialog;

