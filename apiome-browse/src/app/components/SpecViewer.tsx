'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import YAML from 'yaml';
import { useTheme, specThemes, SpecTheme } from './ThemeProvider';
import { operationAnchorId, schemaAnchorId } from './SpecSidebar';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="flex h-[600px] items-center justify-center bg-zinc-50 dark:bg-zinc-900">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-sm text-zinc-600 dark:text-zinc-400">Loading editor...</span>
      </div>
    </div>
  ),
});

const SpecVisualCanvas = dynamic(() => import('./SpecVisualCanvas').then((m) => m.SpecVisualCanvas), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-[520px] items-center justify-center rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-sm text-zinc-600 dark:text-zinc-400">Loading visual canvas...</span>
      </div>
    </div>
  ),
});

interface SpecViewerProps {
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
  /** Notify parent (e.g. sidebar) of spec + format changes. */
  onSpecChange?: (spec: unknown, format: SpecFormat) => void;
}

export type SpecFormat = 'openapi' | 'arazzo' | 'jsonschema';
type ViewMode = 'overview' | 'code' | 'visual';

const monacoThemeMap: Record<SpecTheme, string> = {
  default: 'vs',
  monokai: 'vs-dark',
  github: 'vs',
  darcula: 'vs-dark',
  solarized: 'vs-dark',
  nord: 'vs-dark',
};

const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'];

const HTTP_METHOD_TONE: Record<string, string> = {
  get: 'bg-emerald-50 text-emerald-700 ring-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30',
  post: 'bg-sky-50 text-sky-700 ring-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30',
  put: 'bg-amber-50 text-amber-700 ring-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30',
  patch: 'bg-violet-50 text-violet-700 ring-violet-500/20 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30',
  delete: 'bg-rose-50 text-rose-700 ring-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30',
  options: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
  head: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
  trace: 'bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700',
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function Spinner() {
  return (
    <svg className="h-5 w-5 animate-spin text-[var(--brand)]" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

export function SpecViewer({
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
  onSpecChange,
}: SpecViewerProps) {
  const { specTheme, setSpecTheme, resolvedTheme } = useTheme();
  const [format, setFormat] = useState<SpecFormat>('openapi');
  const [viewFormat, setViewFormat] = useState<'json' | 'yaml'>('json');
  const [viewMode, setViewMode] = useState<ViewMode>('overview');
  const [spec, setSpec] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [urlCopied, setUrlCopied] = useState(false);
  const [showThemePicker, setShowThemePicker] = useState(false);
  const [lineNumbers, setLineNumbers] = useState(true);
  const [wordWrap, setWordWrap] = useState(false);

  const buildUrl = useCallback(
    (f: SpecFormat) => {
      const endpoint = f === 'openapi' ? 'schema' : f === 'arazzo' ? 'arazzo' : 'json';
      return `${restApiBaseUrl}/${endpoint}/${tenantSlug}/${projectSlug}/${versionSlug}`;
    },
    [restApiBaseUrl, tenantSlug, projectSlug, versionSlug]
  );

  const loadSpec = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = buildUrl(format);
      const response = await fetch(url);
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to load specification (${response.status}): ${response.statusText}${
            errorText ? `. ${errorText.substring(0, 100)}` : ''
          }`
        );
      }
      const data: unknown = await response.json();
      setSpec(data);
      onSpecChange?.(data, format);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      if (message.includes('Failed to fetch')) {
        setError(
          `Cannot connect to API. Please ensure the REST API is running at ${restApiBaseUrl} and CORS is configured.`
        );
      } else {
        setError(message);
      }
      setSpec(null);
      onSpecChange?.(null, format);
    } finally {
      setLoading(false);
    }
  }, [buildUrl, format, restApiBaseUrl, onSpecChange]);

  useEffect(() => {
    loadSpec();
  }, [loadSpec]);

  const specContent = spec
    ? viewFormat === 'json'
      ? JSON.stringify(spec, null, 2)
      : YAML.stringify(spec)
    : '';
  const lineCount = specContent.split('\n').length;

  const downloadSpec = () => {
    if (!spec) return;
    const blob = new Blob([specContent], {
      type: viewFormat === 'json' ? 'application/json' : 'text/yaml',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${projectSlug}-${versionSlug}-${format}.${viewFormat === 'json' ? 'json' : 'yaml'}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const copyToClipboard = async () => {
    if (!spec) return;
    await navigator.clipboard.writeText(specContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const copyUrl = async () => {
    await navigator.clipboard.writeText(buildUrl(format));
    setUrlCopied(true);
    setTimeout(() => setUrlCopied(false), 1800);
  };

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-white p-2 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex flex-wrap items-center gap-2">
          {/* Format tabs */}
          <SegmentedControl
            value={format}
            options={[
              { value: 'openapi', label: 'OpenAPI' },
              { value: 'arazzo', label: 'Arazzo' },
              { value: 'jsonschema', label: 'JSON Schema' },
            ]}
            onChange={(v) => setFormat(v as SpecFormat)}
          />

          <Divider />

          {/* View mode */}
          <SegmentedControl
            value={viewMode}
            options={[
              { value: 'overview', label: 'Overview' },
              { value: 'code', label: 'Code' },
              { value: 'visual', label: 'Visual' },
            ]}
            onChange={(v) => setViewMode(v as ViewMode)}
          />

          {viewMode === 'code' && (
            <>
              <Divider />
              <SegmentedControl
                value={viewFormat}
                options={[
                  { value: 'json', label: 'JSON' },
                  { value: 'yaml', label: 'YAML' },
                ]}
                onChange={(v) => setViewFormat(v as 'json' | 'yaml')}
              />
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {viewMode === 'code' && (
            <>
              <ToolbarButton
                onClick={() => setLineNumbers(!lineNumbers)}
                active={lineNumbers}
                label="Toggle line numbers"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                </svg>
              </ToolbarButton>
              <ToolbarButton
                onClick={() => setWordWrap(!wordWrap)}
                active={wordWrap}
                label="Toggle word wrap"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h11m-11 6h7" />
                </svg>
              </ToolbarButton>

              {/* Theme picker (code mode only) */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setShowThemePicker(!showThemePicker)}
                  className="flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  aria-label="Code theme"
                  aria-expanded={showThemePicker}
                >
                  <div
                    className="h-3.5 w-3.5 rounded-sm border border-zinc-300 dark:border-zinc-700"
                    style={{ backgroundColor: specThemes[specTheme].bgColor }}
                  ></div>
                  <span>{specThemes[specTheme].name}</span>
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {showThemePicker && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setShowThemePicker(false)} aria-hidden="true" />
                    <div className="animate-fade-in absolute right-0 top-full z-50 mt-1 w-44 rounded-lg border border-zinc-200 bg-white p-1 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
                      {(Object.entries(specThemes) as [SpecTheme, typeof specThemes.default][]).map(([key, value]) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => {
                            setSpecTheme(key);
                            setShowThemePicker(false);
                          }}
                          className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-[12px] ${
                            specTheme === key
                              ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]'
                              : 'text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
                          }`}
                        >
                          <div
                            className="h-3.5 w-3.5 rounded-sm border border-zinc-200 dark:border-zinc-700"
                            style={{ backgroundColor: value.bgColor }}
                          ></div>
                          {value.name}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </>
          )}

          <Divider />

          <a
            href={`${restApiBaseUrl}/swagger/${tenantSlug}/${projectSlug}/${versionSlug}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Swagger UI
            <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>

          <ToolbarButton onClick={copyUrl} label="Copy spec URL">
            {urlCopied ? (
              <CheckIcon />
            ) : (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            )}
          </ToolbarButton>
          <ToolbarButton onClick={copyToClipboard} label="Copy contents" disabled={!spec}>
            {copied ? (
              <CheckIcon />
            ) : (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            )}
          </ToolbarButton>
          <button
            type="button"
            onClick={downloadSpec}
            disabled={!spec}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--brand)] px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[var(--brand-hover)] disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Download specification"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download
          </button>
        </div>
      </div>

      {/* Content */}
      {loading && (
        <div className="flex items-center justify-center rounded-xl border border-zinc-200 bg-white p-16 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex items-center gap-3">
            <Spinner />
            <span className="text-sm text-zinc-600 dark:text-zinc-400">Loading specification...</span>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-5 dark:border-rose-900/50 dark:bg-rose-950/20">
          <div className="flex items-start gap-3">
            <svg className="mt-0.5 h-5 w-5 shrink-0 text-rose-600 dark:text-rose-400" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <h3 className="text-sm font-semibold text-rose-900 dark:text-rose-200">
                Could not load specification
              </h3>
              <p className="mt-1 text-[13px] text-rose-800 dark:text-rose-300/90">{error}</p>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && spec != null && viewMode === 'overview' && (
        <SpecOverview spec={spec} format={format} />
      )}

      {!loading && !error && spec != null && viewMode === 'visual' && (
        <SpecVisualCanvas spec={spec} format={format} isDark={resolvedTheme === 'dark'} />
      )}

      {!loading && !error && spec != null && viewMode === 'code' && (
        <div className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50/80 px-3 py-1.5 dark:border-zinc-800 dark:bg-zinc-900/40">
            <div className="flex items-center gap-3 text-[12px]">
              <span className="font-mono font-medium text-zinc-700 dark:text-zinc-300">
                {format === 'openapi'
                  ? `openapi.${viewFormat}`
                  : format === 'arazzo'
                  ? `arazzo.${viewFormat}`
                  : `schema.${viewFormat}`}
              </span>
              <span className="text-zinc-500 dark:text-zinc-400 tabular-nums">{lineCount} lines</span>
            </div>
            <SpecMetaSummary spec={spec} format={format} />
          </div>
          <Editor
            height="600px"
            language={viewFormat}
            value={specContent}
            theme={monacoThemeMap[specTheme]}
            options={{
              readOnly: true,
              minimap: { enabled: true },
              lineNumbers: lineNumbers ? 'on' : 'off',
              wordWrap: wordWrap ? 'on' : 'off',
              scrollBeyondLastLine: false,
              fontSize: 13,
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
              automaticLayout: true,
              folding: true,
              foldingHighlight: true,
              renderLineHighlight: 'line',
              scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
            }}
          />
        </div>
      )}
    </div>
  );
}

function SpecMetaSummary({ spec, format }: { spec: unknown; format: SpecFormat }) {
  if (!isObject(spec)) return null;
  if (format === 'openapi') {
    const info = isObject(spec.info) ? spec.info : null;
    const ver = info && typeof info.version === 'string' ? info.version : undefined;
    const oapi = typeof spec.openapi === 'string' ? spec.openapi : undefined;
    return (
      <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
        {ver && <span>v{ver}</span>}
        {oapi && <span> &middot; OpenAPI {oapi}</span>}
      </div>
    );
  }
  return null;
}

function SpecOverview({ spec, format }: { spec: unknown; format: SpecFormat }) {
  if (!isObject(spec)) return null;

  if (format === 'openapi') {
    const info = isObject(spec.info) ? spec.info : null;
    const servers = Array.isArray(spec.servers) ? spec.servers : [];
    const declaredTags = Array.isArray(spec.tags) ? spec.tags : [];
    const paths = isObject(spec.paths) ? spec.paths : {};
    const components = isObject(spec.components) ? spec.components : null;
    const componentSchemas = components && isObject(components.schemas) ? components.schemas : {};
    const legacyDefinitions = isObject(spec.definitions) ? spec.definitions : {};

    const pathEntries = Object.entries(paths);
    const schemaNames = [
      ...new Set([...Object.keys(componentSchemas), ...Object.keys(legacyDefinitions)]),
    ].sort((a, b) => a.localeCompare(b));
    const schemaCount = schemaNames.length;
    let opCount = 0;
    const groups = new Map<string, { tag: string; description?: string; ops: { method: string; path: string; summary?: string; deprecated?: boolean }[] }>();
    const ensure = (tag: string) => {
      let g = groups.get(tag);
      if (!g) {
        g = { tag, ops: [] };
        groups.set(tag, g);
      }
      return g;
    };
    for (const t of declaredTags) {
      if (isObject(t) && typeof t.name === 'string') {
        ensure(t.name).description = typeof t.description === 'string' ? t.description : undefined;
      }
    }
    for (const [pathKey, valueRaw] of pathEntries) {
      if (!isObject(valueRaw)) continue;
      for (const method of HTTP_METHODS) {
        const opRaw = valueRaw[method];
        if (!isObject(opRaw)) continue;
        opCount++;
        const tags = Array.isArray(opRaw.tags) && opRaw.tags.length > 0
          ? (opRaw.tags as unknown[]).filter((t): t is string => typeof t === 'string')
          : ['Untagged'];
        for (const t of tags) {
          ensure(t).ops.push({
            method: method.toUpperCase(),
            path: pathKey,
            summary: typeof opRaw.summary === 'string' ? opRaw.summary : undefined,
            deprecated: opRaw.deprecated === true,
          });
        }
      }
    }

    const orderedGroups = Array.from(groups.values());

    return (
      <div className="space-y-5">
        {/* Info card */}
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
                {info && typeof info.title === 'string' ? info.title : 'API'}
              </h3>
              {info && typeof info.description === 'string' && (
                <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {info.description}
                </p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {info && typeof info.version === 'string' && (
                <Pill tone="brand">v{info.version}</Pill>
              )}
              {typeof spec.openapi === 'string' && <Pill tone="neutral">OpenAPI {spec.openapi}</Pill>}
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Endpoints" value={opCount} />
            <Metric label="Paths" value={pathEntries.length} />
            <Metric label="Tags" value={Math.max(orderedGroups.length, declaredTags.length)} />
            <Metric label="Schemas" value={schemaCount} />
          </div>
        </div>

        {/* Servers */}
        {servers.length > 0 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
            <h4 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Servers
            </h4>
            <ul className="space-y-2">
              {servers.map((s, i) => {
                if (!isObject(s)) return null;
                const url = typeof s.url === 'string' ? s.url : '';
                const desc = typeof s.description === 'string' ? s.description : undefined;
                return (
                  <li key={i} className="flex items-start gap-3">
                    <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" />
                      </svg>
                    </span>
                    <div className="min-w-0 flex-1">
                      <code className="block break-all rounded bg-zinc-50 px-2 py-1 font-mono text-[12px] text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
                        {url}
                      </code>
                      {desc && <p className="mt-1 text-[12px] text-zinc-500 dark:text-zinc-400">{desc}</p>}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* Operations grouped by tag */}
        {orderedGroups.length > 0 && (
          <section className="space-y-3">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Operations
            </h4>
            {orderedGroups.map((group) => (
              <div
                key={group.tag}
                className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-950"
              >
                <div className="border-b border-zinc-200 bg-zinc-50/60 px-4 py-2 dark:border-zinc-800 dark:bg-zinc-900/40">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h5 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{group.tag}</h5>
                      {group.description && (
                        <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">{group.description}</p>
                      )}
                    </div>
                    <span className="text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
                      {group.ops.length} {group.ops.length === 1 ? 'operation' : 'operations'}
                    </span>
                  </div>
                </div>
                <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
                  {group.ops.map((op, idx) => {
                    const anchor = operationAnchorId(op.method, op.path);
                    return (
                      <li key={`${anchor}-${idx}`} id={anchor} className="scroll-mt-24">
                        <div className="flex items-start gap-3 px-4 py-2.5">
                          <span
                            className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${
                              HTTP_METHOD_TONE[op.method.toLowerCase()] ?? HTTP_METHOD_TONE.options
                            }`}
                          >
                            {op.method}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <code className="break-all font-mono text-[13px] font-medium text-zinc-900 dark:text-zinc-50">
                                {op.path}
                              </code>
                              {op.deprecated && (
                                <span className="inline-flex items-center rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                                  deprecated
                                </span>
                              )}
                            </div>
                            {op.summary && (
                              <p className="mt-0.5 text-[12px] text-zinc-600 dark:text-zinc-400">{op.summary}</p>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        )}

        {schemaNames.length > 0 && (
          <section className="space-y-3">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Schemas
            </h4>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {schemaNames.map((schemaName) => {
                const schemaObj =
                  (isObject(componentSchemas[schemaName]) ? componentSchemas[schemaName] : null) ??
                  (isObject(legacyDefinitions[schemaName]) ? legacyDefinitions[schemaName] : null);
                const title =
                  isObject(schemaObj) && typeof schemaObj.title === 'string' ? schemaObj.title : undefined;
                const description =
                  isObject(schemaObj) && typeof schemaObj.description === 'string'
                    ? schemaObj.description
                    : undefined;
                const anchor = schemaAnchorId(schemaName);
                return (
                  <div
                    key={schemaName}
                    id={anchor}
                    className="scroll-mt-24 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs dark:border-zinc-800 dark:bg-zinc-950"
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 shrink-0 rounded bg-fuchsia-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-fuchsia-800 dark:bg-fuchsia-500/10 dark:text-fuchsia-300">
                        CLS
                      </span>
                      <div className="min-w-0 flex-1">
                        <code className="break-all font-mono text-[13px] font-semibold text-zinc-900 dark:text-zinc-50">
                          {schemaName}
                        </code>
                        {title && (
                          <p className="mt-1 text-[12px] font-medium text-zinc-700 dark:text-zinc-300">{title}</p>
                        )}
                        {description && (
                          <p className="mt-1 line-clamp-4 text-[12px] leading-relaxed text-zinc-600 dark:text-zinc-400">
                            {description}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    );
  }

  if (format === 'arazzo') {
    const workflows = Array.isArray(spec.workflows) ? spec.workflows : [];
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Arazzo workflows</h3>
        <p className="mt-1 text-[13px] text-zinc-500 dark:text-zinc-400">
          {workflows.length} workflow{workflows.length === 1 ? '' : 's'} declared.
        </p>
        {workflows.length > 0 && (
          <ul className="mt-4 space-y-2">
            {workflows.map((w, i) => {
              if (!isObject(w)) return null;
              const id = typeof w.workflowId === 'string' ? w.workflowId : `workflow-${i}`;
              const summary = typeof w.summary === 'string' ? w.summary : undefined;
              return (
                <li
                  key={id}
                  id={`wf-${id}`}
                  className="scroll-mt-24 rounded-lg border border-zinc-100 p-3 dark:border-zinc-800"
                >
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-violet-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                      WF
                    </span>
                    <code className="font-mono text-[13px] font-medium text-zinc-900 dark:text-zinc-50">{id}</code>
                  </div>
                  {summary && <p className="mt-1 text-[12px] text-zinc-500 dark:text-zinc-400">{summary}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  // jsonschema
  const defs =
    (isObject(spec.$defs) && (spec.$defs as Record<string, unknown>)) ||
    (isObject(spec.definitions) && (spec.definitions as Record<string, unknown>)) ||
    null;
  const defNames = defs ? Object.keys(defs) : [];
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">JSON Schema</h3>
      <p className="mt-1 text-[13px] text-zinc-500 dark:text-zinc-400">
        {defNames.length} top-level definition{defNames.length === 1 ? '' : 's'}.
      </p>
      {defNames.length > 0 && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {defNames.map((name) => (
            <li
              key={name}
              id={`def-${name.replace(/[^a-z0-9]+/gi, '-')}`}
              className="scroll-mt-24 rounded border border-zinc-100 px-3 py-2 font-mono text-[12px] text-zinc-800 dark:border-zinc-800 dark:text-zinc-200"
            >
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-zinc-50 px-3 py-2 dark:bg-zinc-900/60">
      <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone: 'brand' | 'neutral' }) {
  const cls =
    tone === 'brand'
      ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]'
      : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md bg-zinc-100 p-0.5 dark:bg-zinc-800/80">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
            value === opt.value
              ? 'bg-white text-zinc-900 shadow-xs dark:bg-zinc-700 dark:text-zinc-50'
              : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Divider() {
  return <span className="hidden h-5 w-px bg-zinc-200 dark:bg-zinc-700 sm:inline-block" />;
}

function ToolbarButton({
  onClick,
  children,
  label,
  active,
  disabled,
}: {
  onClick: () => void;
  children: React.ReactNode;
  label: string;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`flex h-7 w-7 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]'
          : 'border border-zinc-200 bg-white text-zinc-600 shadow-xs hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800'
      }`}
    >
      {children}
    </button>
  );
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}
