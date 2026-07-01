'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  FileCode,
  FileUp,
  GitBranch,
  Link2,
  Loader2,
  Upload,
  X,
} from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../ui/Dialog';
import { Button } from '../../../ui/Button';
import { Alert } from '../../../ui/Alert';
import { extractFileMetadata, type FileMetadataPreview } from '../../../../utils/openapi-analyzer';
import { generateSlug } from '../../../../utils/slug';
import { FormatPill } from '../../../ui/catalog/FormatPill';
import {
  catalogAdapterForFormat,
  decideCatalogImportRouting,
  CATALOG_STORABLE_SOURCES,
  type CatalogImportRoutingDecision,
} from '../../../../utils/catalog-import-formats';
import { useCatalogImportAvailability } from './useCatalogImportAvailability';

interface CatalogImportDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  onJsonSchemaAsCurrent?: (payload: JsonSchemaHandoffPayload) => void;
}

export interface JsonSchemaHandoffPayload {
  text: string;
  label: string;
  document: Record<string, unknown> | null;
}

type SourceMethod = 'file' | 'url' | 'paste';
type Step = 'source' | 'detect' | 'options' | 'import';
type ImportState = 'idle' | 'detecting' | 'fetching-url' | 'storing' | 'done';
type JsonSchemaChoice = 'catalog' | 'types';

interface DetectionCandidate {
  format: string;
  confidence: number;
  reason?: string | null;
  source_key?: string | null;
  importable: boolean;
}

interface DetectionResult {
  matched: boolean;
  detected?: DetectionCandidate | null;
  ambiguous?: boolean;
  candidates?: DetectionCandidate[];
  ambiguous_candidates?: DetectionCandidate[];
}

const PREVIEW_LIMIT = 4000;

function toBase64(text: string): string {
  return btoa(unescape(encodeURIComponent(text)));
}

function baseName(fileName: string): string {
  const noPath = fileName.split(/[\\/]/).pop() ?? fileName;
  return noPath.replace(/\.[^.]+$/, '') || noPath;
}

function parseJsonDocument(text: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'unknown confidence';
  return `${Math.round(value * 100)}% confidence`;
}

function routingTone(destination: CatalogImportRoutingDecision['destination']): string {
  switch (destination) {
    case 'catalog':
      return 'border-indigo-200 bg-indigo-50 text-indigo-900 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100';
    case 'project':
      return 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100';
    case 'json-schema-choice':
      return 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100';
    default:
      return 'border-gray-200 bg-gray-50 text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200';
  }
}

export function CatalogImportDialog({
  open,
  onClose,
  onSuccess,
  onJsonSchemaAsCurrent,
}: CatalogImportDialogProps) {
  const [step, setStep] = useState<Step>('source');
  const [sourceMethod, setSourceMethod] = useState<SourceMethod>('file');
  const [state, setState] = useState<ImportState>('idle');
  const [fileName, setFileName] = useState('');
  const [content, setContent] = useState('');
  const [urlInput, setUrlInput] = useState('');
  const [pasteText, setPasteText] = useState('');
  const [metadata, setMetadata] = useState<FileMetadataPreview | null>(null);
  const [detection, setDetection] = useState<DetectionResult | null>(null);
  const [jsonSchemaChoice, setJsonSchemaChoice] = useState<JsonSchemaChoice>('catalog');
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const availability = useCatalogImportAvailability(open);

  const detectedFormat = detection?.detected?.format || metadata?.format || null;
  const routing = useMemo(() => decideCatalogImportRouting(detectedFormat), [detectedFormat]);
  const adapter = routing.destination === 'catalog'
    ? routing.adapter ?? catalogAdapterForFormat(detectedFormat)
    : null;
  const adapterUnavailable = adapter !== null && !availability.isAvailable(adapter.sourceKind);
  const unavailableReason = adapter ? availability.reasonFor(adapter.sourceKind) : null;
  const supportedLabel = CATALOG_STORABLE_SOURCES.filter((s) => availability.isAvailable(s.sourceKind))
    .map((s) => s.label)
    .join(', ') || CATALOG_STORABLE_SOURCES.map((s) => s.label).join(', ');
  const canStoreCatalog = routing.destination === 'catalog' && adapter !== null && !adapterUnavailable;
  const canContinueFromDetect =
    routing.destination === 'catalog' || routing.destination === 'json-schema-choice';

  const reset = useCallback(() => {
    setStep('source');
    setSourceMethod('file');
    setState('idle');
    setFileName('');
    setContent('');
    setUrlInput('');
    setPasteText('');
    setMetadata(null);
    setDetection(null);
    setJsonSchemaChoice('catalog');
    setError(null);
    setIsDragging(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const detectContent = useCallback(async (text: string, label: string, method: SourceMethod) => {
    setState('detecting');
    setError(null);
    const preview = extractFileMetadata(text);
    setMetadata(preview);
    setContent(text);
    setFileName(label);
    setSourceMethod(method);
    try {
      const res = await fetch('/api/import/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, filename: label, url: method === 'url' ? label : undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.success === false) {
        throw new Error(data?.error || 'Could not detect that source.');
      }
      setDetection(data as DetectionResult);
    } catch (e) {
      setDetection(null);
      setError(e instanceof Error ? e.message : 'Could not detect that source.');
    } finally {
      setState('idle');
      setStep('detect');
    }
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      try {
        const text = await file.text();
        await detectContent(text, file.name, 'file');
      } catch {
        setError('Could not read that file. Try another file.');
      }
    },
    [detectContent],
  );

  const handleUrlFetch = useCallback(async () => {
    const url = urlInput.trim();
    if (!url) {
      setError('Enter a URL to import.');
      return;
    }
    try {
      new URL(url);
    } catch {
      setError('Enter a valid URL.');
      return;
    }
    setState('fetching-url');
    setError(null);
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Fetch failed with HTTP ${res.status}.`);
      const text = await res.text();
      await detectContent(text, url, 'url');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not fetch that URL.');
    } finally {
      setState('idle');
    }
  }, [detectContent, urlInput]);

  const handlePasteDetect = useCallback(async () => {
    const text = pasteText.trim();
    if (!text) {
      setError('Paste source content before continuing.');
      return;
    }
    await detectContent(text, 'Pasted source', 'paste');
  }, [detectContent, pasteText]);

  const handleStoreCatalog = useCallback(async () => {
    if (!adapter || adapterUnavailable || !content) return;
    setStep('import');
    setState('storing');
    setError(null);
    try {
      const name = (metadata?.title || baseName(fileName) || 'Imported source').trim();
      const slug = generateSlug(name) || 'imported-source';
      const startRes = await fetch('/api/catalog/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metadata: {
            source_kind: adapter.sourceKind,
            project: { name, slug, description: metadata?.description ?? null },
            version: { version_id: metadata?.specVersion || '1.0.0' },
            options: {},
          },
          document_base64: toBase64(content),
          filename: fileName || 'source',
        }),
      });
      const startData = await startRes.json().catch(() => ({}));
      if (!startRes.ok || startData?.success === false) {
        throw new Error(startData?.error || 'Failed to start the import.');
      }
      const jobId: string | undefined = startData?.job_id;
      if (!jobId) throw new Error('The import did not start (no job id returned).');

      const terminal = new Set(['completed', 'failed', 'canceled', 'rolled-back', 'pending-approval']);
      for (let i = 0; i < 150; i++) {
        await new Promise((r) => setTimeout(r, 400));
        const pollRes = await fetch(`/api/catalog/import/${encodeURIComponent(jobId)}`);
        const pollData = await pollRes.json().catch(() => ({}));
        if (!pollRes.ok || pollData?.success === false) {
          throw new Error(pollData?.error || 'Failed to check import status.');
        }
        const jobState: string | undefined = pollData?.state;
        if (jobState && terminal.has(jobState)) {
          if (jobState === 'completed') {
            setState('done');
            onSuccess?.();
            return;
          }
          const failEvent = Array.isArray(pollData?.events)
            ? [...pollData.events].reverse().find((e: { level?: string }) => e?.level === 'error')
            : null;
          throw new Error(failEvent?.message || `Import ${jobState}.`);
        }
      }
      throw new Error('The import is taking longer than expected. Check the catalog shortly.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to store the source.');
      setState('idle');
      setStep('options');
    }
  }, [adapter, adapterUnavailable, content, fileName, metadata, onSuccess]);

  const handleJsonSchemaChoice = useCallback(() => {
    if (jsonSchemaChoice === 'catalog') {
      setError('Catalog storage for JSON Schema is not adapter-backed yet. Choose Types/Projects for now.');
      return;
    }
    onJsonSchemaAsCurrent?.({
      text: content,
      label: fileName || 'JSON Schema',
      document: parseJsonDocument(content),
    });
    handleClose();
  }, [content, fileName, handleClose, jsonSchemaChoice, onJsonSchemaAsCurrent]);

  const stepIndex = ['source', 'detect', 'options', 'import'].indexOf(step);
  const detected = detection?.detected;

  return (
    <Dialog open={open} onOpenChange={(o) => (!o ? handleClose() : undefined)}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col">
        <DialogHeader>
          <DialogTitle>Import to catalog</DialogTitle>
          <DialogDescription>
            Start with File Upload, URL Import, or Clipboard paste. Catalog imports are stored in
            their original format and converted only when explicitly requested.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
          {(['Source', 'Detect & route', 'Options', 'Import'] as const).map((label, idx) => (
            <div
              key={label}
              className={`rounded-full border px-3 py-1.5 text-center ${
                idx <= stepIndex
                  ? 'border-indigo-200 bg-indigo-50 font-medium text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200'
                  : 'border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400'
              }`}
            >
              {idx + 1}. {label}
            </div>
          ))}
        </div>

        {error && (
          <Alert variant="error" className="mt-3">
            {error}
          </Alert>
        )}

        {step === 'source' && (
          <div className="mt-4 grid gap-4 lg:grid-cols-[1.35fr_.9fr]">
            <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                <Upload className="h-4 w-4 text-indigo-500" aria-hidden />
                Choose a source
              </div>
              <div className="my-3 h-px bg-gray-200 dark:bg-gray-700" />
              <div className="grid gap-2 sm:grid-cols-3">
                {([
                  ['file', FileUp, 'File', '.proto .graphql .yaml .json'],
                  ['url', Link2, 'URL', 'Fetch a remote document'],
                  ['paste', Clipboard, 'Clipboard', 'Paste raw text'],
                ] as const).map(([kind, Icon, title, desc]) => (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => {
                      setSourceMethod(kind);
                      setError(null);
                    }}
                    className={`rounded-lg border p-3 text-center transition ${
                      sourceMethod === kind
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100'
                        : 'border-gray-200 bg-white text-gray-700 hover:border-indigo-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-200'
                    }`}
                  >
                    <Icon className="mx-auto mb-2 h-5 w-5" aria-hidden />
                    <div className="text-sm font-medium">{title}</div>
                    <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">{desc}</div>
                  </button>
                ))}
              </div>

              <div className="mt-4">
                {sourceMethod === 'file' && (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      setIsDragging(true);
                    }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setIsDragging(false);
                      const file = e.dataTransfer.files?.[0];
                      if (file) void handleFile(file);
                    }}
                    className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 text-center ${
                      isDragging
                        ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
                        : 'border-gray-300 dark:border-gray-700'
                    }`}
                  >
                    <FileUp className="h-8 w-8 text-gray-400" aria-hidden />
                    <div className="text-sm text-gray-600 dark:text-gray-300">
                      Drop a source file here, or browse.
                    </div>
                    <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                      Browse files
                    </Button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="hidden"
                      accept=".proto,.graphql,.gql,.yaml,.yml,.json"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) void handleFile(file);
                      }}
                    />
                  </div>
                )}

                {sourceMethod === 'url' && (
                  <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-200" htmlFor="catalog-import-url">
                      Document URL
                    </label>
                    <input
                      id="catalog-import-url"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      placeholder="https://api.example.com/schema.graphql"
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950"
                    />
                    <Button onClick={handleUrlFetch} disabled={state === 'fetching-url'}>
                      {state === 'fetching-url' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Link2 className="h-4 w-4" aria-hidden />}
                      Fetch and detect
                    </Button>
                  </div>
                )}

                {sourceMethod === 'paste' && (
                  <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-200" htmlFor="catalog-import-paste">
                      Source content
                    </label>
                    <textarea
                      id="catalog-import-paste"
                      value={pasteText}
                      onChange={(e) => setPasteText(e.target.value)}
                      placeholder="Paste GraphQL SDL, .proto, AsyncAPI, or JSON Schema content..."
                      rows={9}
                      className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-xs dark:border-gray-700 dark:bg-gray-950"
                    />
                    <Button onClick={handlePasteDetect}>
                      <Clipboard className="h-4 w-4" aria-hidden />
                      Detect pasted source
                    </Button>
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                <GitBranch className="h-4 w-4 text-indigo-500" aria-hidden />
                Destination guide
              </div>
              <div className="my-3 h-px bg-gray-200 dark:bg-gray-700" />
              <div className="space-y-3 text-sm">
                <div>
                  <div className="font-medium">Catalog only</div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {supportedLabel} stay non-publishable until explicit Convert.
                  </p>
                </div>
                <div>
                  <div className="font-medium">Projects</div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    OpenAPI, Swagger, and Arazzo create publishable Project versions.
                  </p>
                </div>
                <div>
                  <div className="font-medium">JSON Schema asks first</div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Choose Catalog for later conversion or Types/Projects as current schema.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 'detect' && (
          <div className="mt-4 space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
              <div className="flex min-w-0 items-center gap-2">
                <FileCode className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                <span className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">{fileName}</span>
              </div>
              <div className="flex items-center gap-2">
                <FormatPill format={detectedFormat === 'unknown' ? null : detectedFormat} />
                <button
                  type="button"
                  onClick={reset}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                  aria-label="Choose a different source"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </div>
            </div>

            <div className="rounded-lg border border-gray-200 p-4 dark:border-gray-700">
              <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                Auto-detected: {detected?.format || metadata?.formatDisplayName || 'Unknown'}
              </div>
              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {formatPercent(detected?.confidence)}{detected?.reason ? ` · ${detected.reason}` : ''}
              </div>
            </div>

            <div className={`rounded-lg border p-4 ${routingTone(routing.destination)}`}>
              <div className="flex items-start gap-2">
                {routing.destination === 'not-importable' ? (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                ) : (
                  <GitBranch className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                )}
                <div>
                  <div className="text-sm font-semibold">Routing decision → {routing.label}</div>
                  <div className="mt-1 text-xs opacity-90">{routing.description}</div>
                  {adapterUnavailable && (
                    <div className="mt-2 text-xs font-medium">
                      {unavailableReason || `${adapter?.label} import is unavailable in this runtime.`}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="max-h-56 overflow-auto rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900">
              <pre className="whitespace-pre-wrap p-3 font-mono text-[11px] leading-snug text-gray-700 dark:text-gray-300">
                {content.slice(0, PREVIEW_LIMIT)}
                {content.length > PREVIEW_LIMIT ? '\n…' : ''}
              </pre>
            </div>
          </div>
        )}

        {step === 'options' && (
          <div className="mt-4 space-y-4">
            {routing.destination === 'catalog' && (
              <Alert variant="info">
                <div className="font-medium">Store in catalog</div>
                <div className="text-sm">
                  This source will be kept verbatim as {adapter?.label}. It will not create a
                  Project or auto-convert to OpenAPI.
                </div>
              </Alert>
            )}
            {routing.destination === 'json-schema-choice' && (
              <div className="space-y-3">
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  Choose where this JSON Schema should go.
                </div>
                <label className="flex gap-3 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                  <input
                    type="radio"
                    name="jsonSchemaChoice"
                    checked={jsonSchemaChoice === 'catalog'}
                    onChange={() => setJsonSchemaChoice('catalog')}
                  />
                  <span>
                    <span className="block text-sm font-medium">Catalog for later conversion</span>
                    <span className="block text-xs text-gray-500 dark:text-gray-400">
                      Deferred until a JSON Schema catalog adapter is available.
                    </span>
                  </span>
                </label>
                <label className="flex gap-3 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                  <input
                    type="radio"
                    name="jsonSchemaChoice"
                    checked={jsonSchemaChoice === 'types'}
                    onChange={() => setJsonSchemaChoice('types')}
                  />
                  <span>
                    <span className="block text-sm font-medium">Types/Projects as current schema</span>
                    <span className="block text-xs text-gray-500 dark:text-gray-400">
                      Opens the existing type import review with this schema preloaded.
                    </span>
                  </span>
                </label>
              </div>
            )}
          </div>
        )}

        {step === 'import' && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 py-10 text-center">
            {state === 'done' ? (
              <>
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-green-500 text-white">
                  <CheckCircle2 className="h-7 w-7" aria-hidden />
                </div>
                <div className="text-sm text-gray-700 dark:text-gray-200">
                  Stored in the catalog in its original format. Use <strong>Convert to OpenAPI</strong> when ready.
                </div>
              </>
            ) : (
              <>
                <Loader2 className="h-8 w-8 animate-spin text-indigo-500" aria-hidden />
                <div className="text-sm text-gray-700 dark:text-gray-200">Storing source in catalog…</div>
              </>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-between gap-2 border-t border-gray-200 pt-3 dark:border-gray-700">
          <Button variant="outline" onClick={handleClose} disabled={state === 'storing'}>
            {state === 'done' ? 'Close' : 'Cancel'}
          </Button>
          <div className="flex gap-2">
            {step !== 'source' && step !== 'import' && (
              <Button variant="outline" onClick={() => setStep(step === 'options' ? 'detect' : 'source')}>
                Back
              </Button>
            )}
            {step === 'detect' && (
              <Button onClick={() => setStep('options')} disabled={!canContinueFromDetect || adapterUnavailable}>
                Continue
              </Button>
            )}
            {step === 'options' && routing.destination === 'catalog' && (
              <Button onClick={handleStoreCatalog} disabled={!canStoreCatalog || state === 'storing'}>
                Store in catalog
              </Button>
            )}
            {step === 'options' && routing.destination === 'json-schema-choice' && (
              <Button onClick={handleJsonSchemaChoice}>
                Continue
              </Button>
            )}
            {step === 'import' && state === 'done' && (
              <Button onClick={handleClose}>Done</Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default CatalogImportDialog;
