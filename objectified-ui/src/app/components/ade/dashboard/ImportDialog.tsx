'use client';

import { useState } from 'react';
import { Upload, Link2, FileText, Github, Cloud, Package, X, FileCode, AlertTriangle, CheckCircle2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { AnalysisPanel } from './AnalysisPanel';
import { PreviewPanel, ImportOptions } from './PreviewPanel';
import { analyzeSpecification, AnalysisResult, extractFileMetadata, FileMetadataPreview } from '../../../utils/openapi-analyzer';
import ImportExecutionPanel from './ImportExecutionPanel';
import ImportCompletePanel from './ImportCompletePanel';
import UrlImportPanel from './UrlImportPanel';
import ClipboardImportPanel from './ClipboardImportPanel';
import { startImport, getImportStatus, rollbackImport } from '../../../../../lib/db/import-actions';

interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  tenantId: string;
  userId: string;
}

const ImportDialog: React.FC<ImportDialogProps> = ({
  open,
  onClose,
  onSuccess,
  tenantId, // Will be used in future steps for project creation
  userId    // Will be used in future steps for tracking import activity
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

  const handleSourceClick = (source: string) => {
    setSelectedSource(source);
    setCurrentStep('file-upload');
    console.log('Selected source:', source);
  };

  const handleBack = () => {
    if (currentStep === 'done') {
      setCurrentStep('preview');
    } else if (currentStep === 'import') {
      setCurrentStep('preview');
      setJobId(null);
    } else if (currentStep === 'preview') {
      setCurrentStep('analysis');
    } else if (currentStep === 'analysis') {
      setCurrentStep('file-upload');
      setAnalysisResult(null);
    } else if (currentStep === 'file-upload') {
      setCurrentStep('source');
      setSelectedSource(null);
      setSelectedFile(null);
      setFileMetadata(null);
      setUrlContent(null);
      setUrlFilename(null);
      setUrlMetadata(null);
      setClipboardContent(null);
      setClipboardFilename(null);
    }
  };

  const handleClose = async () => {
    // If there's a pending import job (during import step), roll back the transaction
    if (jobId && currentStep === 'import') {
      try {
        await rollbackImport(jobId);
      } catch (e) {
        console.error('Failed to rollback import on close:', e);
      }
    }

    // Call onSuccess callback if import completed successfully
    if (importSucceeded && onSuccess) {
      onSuccess();
    }

    // Reset all state
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
    onClose();
  };

  const handleAnalyze = async () => {
    if (!selectedFile && !urlContent && !clipboardContent) return;

    console.log('Starting analysis...', {
      selectedFile: selectedFile?.name,
      urlFilename,
      clipboardFilename,
      hasUrlContent: !!urlContent,
      hasClipboardContent: !!clipboardContent
    });
    setIsAnalyzing(true);
    try {
      const content = urlContent || clipboardContent || await selectedFile!.text();
      const filename = urlFilename || clipboardFilename || selectedFile?.name || 'openapi-spec.yaml';
      console.log('Content loaded, length:', content.length);
      const result = await analyzeSpecification(content, filename);
      console.log('Analysis complete:', result);
      setAnalysisResult(result);
      setCurrentStep('analysis');
      console.log('State updated to analysis step');
    } catch (error) {
      console.error('Analysis error:', error);
      // TODO: Show error message
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
    const validExtensions = ['.yaml', '.yml', '.json', '.zip'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

    if (validExtensions.includes(fileExtension)) {
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
          console.error('Error extracting metadata:', error);
        } finally {
          setIsLoadingMetadata(false);
        }
      }
    } else {
      console.error('Invalid file type');
      // TODO: Show error message
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
  };

  const beginImport = async () => {
    if (!analysisResult || !importOptions) return;

    const document = analysisResult.document;
    const job = await startImport({
      tenantId,
      userId,
      sourceKind: 'openapi',
      document,
      project: {
        name: importOptions.projectName || (document?.info?.title || 'New Project'),
        slug: (document?.info?.title || 'new-project').toLowerCase().replace(/[^a-z0-9-]/g, '-').replace(/--+/g,'-'),
        description: document?.info?.description || null
      },
      version: {
        versionId: importOptions.targetVersion || (document?.info?.version || '1.0.0'),
        description: 'Imported from OpenAPI specification'
      },
      options: {
        selectedSchemas: importOptions.selectedSchemas
      }
    });

    setJobId(job.jobId);
    setCurrentStep('import');
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden flex flex-col" showCloseButton={false}>
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
        <div className="overflow-y-auto py-6 px-6 h-[60vh]">
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
              <div className="grid grid-cols-3 gap-4 mb-4">
                {/* File Upload */}
                <button
                  onClick={() => handleSourceClick('file')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'file'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'file'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Upload className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'file' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      File Upload
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Drop files or click to browse
                    </div>
                  </div>
                </button>

                {/* URL Import */}
                <button
                  onClick={() => handleSourceClick('url')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'url'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'url'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Link2 className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'url' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      URL Import
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Fetch from URL or repository
                    </div>
                  </div>
                </button>

                {/* Clipboard */}
                <button
                  onClick={() => handleSourceClick('clipboard')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'clipboard'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'clipboard'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <FileText className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'clipboard' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      Clipboard Paste
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Paste JSON or YAML content
                    </div>
                  </div>
                </button>

                {/* Git Repository */}
                <button
                  disabled
                  className="group relative p-6 rounded-lg border-2 border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 opacity-60 cursor-not-allowed"
                  title="Coming soon"
                >
                  <div className="flex flex-col items-center text-center">
                    <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-3 bg-gray-100 dark:bg-gray-700 text-gray-400">
                      <Github className="h-6 w-6" />
                    </div>
                    <div className="font-semibold mb-1 text-gray-500 dark:text-gray-400">
                      Git Repository
                    </div>
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      Clone from GitHub/GitLab
                    </div>
                  </div>
                </button>

                {/* SwaggerHub */}
                <button
                  disabled
                  className="group relative p-6 rounded-lg border-2 border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 opacity-60 cursor-not-allowed"
                  title="Coming soon"
                >
                  <div className="flex flex-col items-center text-center">
                    <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-3 bg-gray-100 dark:bg-gray-700 text-gray-400">
                      <Cloud className="h-6 w-6" />
                    </div>
                    <div className="font-semibold mb-1 text-gray-500 dark:text-gray-400">
                      SwaggerHub Integration
                    </div>
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      Import from SwaggerHub
                    </div>
                  </div>
                </button>

                {/* Registry Import */}
                <button
                  disabled
                  className="group relative p-6 rounded-lg border-2 border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 opacity-60 cursor-not-allowed"
                  title="Coming soon"
                >
                  <div className="flex flex-col items-center text-center">
                    <div className="w-12 h-12 rounded-xl flex items-center justify-center mb-3 bg-gray-100 dark:bg-gray-700 text-gray-400">
                      <Package className="h-6 w-6" />
                    </div>
                    <div className="font-semibold mb-1 text-gray-500 dark:text-gray-400">
                      Registry Import
                    </div>
                    <div className="text-xs text-gray-400 dark:text-gray-500">
                      Import from schema registry
                    </div>
                  </div>
                </button>
              </div>
            </div>
          </div>
            </>
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'file') {
              console.log('Rendering: File upload');
              return (
            <>
              {/* Step 1a: File Upload View */}

              {/* Source Tabs */}
              <div className="mb-6">
                <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
                  <button
                    className="px-4 py-2 text-sm font-medium border-b-2 border-indigo-600 text-indigo-600 dark:text-indigo-400"
                  >
                    📁 File
                  </button>
                  <button
                    disabled
                    className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50"
                    title="Coming soon"
                  >
                    🔗 URL
                  </button>
                  <button
                    disabled
                    className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50"
                    title="Coming soon"
                  >
                    📋 Clipboard
                  </button>
                  <button
                    disabled
                    className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50"
                    title="Coming soon"
                  >
                    🐙 Git
                  </button>
                  <button
                    disabled
                    className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50"
                    title="Coming soon"
                  >
                    ☁️ SwaggerHub
                  </button>
                  <button
                    disabled
                    className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50"
                    title="Coming soon"
                  >
                    📦 Registry
                  </button>
                </div>
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
                            accept=".yaml,.yml,.json,.zip"
                            onChange={handleFileInputChange}
                          />
                          <span className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg transition-colors shadow-sm">
                            <Upload className="h-5 w-5" />
                            Browse Files
                          </span>
                        </label>

                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          Supports: .yaml, .yml, .json, .zip
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
                                Currently supported formats: OpenAPI 3.x, Swagger 2.x, and JSON Schema.
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
                  isReviewing={importComplete}
                  onComplete={(succeeded) => {
                    setImportComplete(true);
                    setImportSucceeded(succeeded);
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
                  onSpecificationFetched={handleUrlSpecificationFetched}
                />
              );
            } else if (currentStep === 'file-upload' && selectedSource === 'clipboard') {
              console.log('Rendering: Clipboard import panel');
              return (
                <ClipboardImportPanel
                  onSpecificationReady={handleClipboardSpecificationReady}
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
                  <Button variant="outline" onClick={handleClose}>
                    Cancel
                  </Button>
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
                    {isAnalyzing ? 'Analyzing...' : 'Analyze →'}
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

