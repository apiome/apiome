'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import YAML from 'yaml';
import { useTheme, specThemes, SpecTheme } from './ThemeProvider';
import { operationAnchorId, schemaAnchorId } from '../../../lib/search/anchors';
import { HTTP_METHOD_TONE } from './search/httpMethodTone';
import { TryItPanel } from './tryit/TryItPanel';
import { OperationSnippetTabs } from './sdk/OperationSnippetTabs';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="flex h-[600px] items-center justify-center bg-subtle">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-base text-fg-muted">Loading editor...</span>
      </div>
    </div>
  ),
});

const SpecVisualCanvas = dynamic(() => import('./SpecVisualCanvas').then((m) => m.SpecVisualCanvas), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-[520px] items-center justify-center rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="text-base text-fg-muted">Loading visual canvas...</span>
      </div>
    </div>
  ),
});

interface SpecViewerProps {
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
  /**
   * Public mock base URL for the browsed version; null/undefined when its mock is disabled.
   * Surfaced in the overview's server list and the prop surface the try-it server picker
   * (SIM-3.1) will consume (SIM-2.3, #4444).
   */
  mockBaseUrl?: string | null;
  /**
   * Whether this project has opted into public SDK access (SDK-3.3, #4493). When false the
   * per-operation snippet tabs are not offered at all — the route that feeds them answers 404
   * for a project that has not opted in, so an offered tab would only ever show an error.
   */
  sdkEnabled?: boolean;
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


/**
 * One operation as the overview projects it out of the OpenAPI document.
 *
 * `operationId` is carried for the SDK-3.3 snippet tabs, which address an operation by it when
 * the spec declares one.
 */
interface SpecOperation {
  method: string;
  path: string;
  summary?: string;
  deprecated?: boolean;
  operationId?: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function Spinner() {
  return (
    <svg className="h-5 w-5 animate-spin text-accent-fg" fill="none" viewBox="0 0 24 24">
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
  mockBaseUrl,
  sdkEnabled = false,
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
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-2 shadow-xs">
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
                  className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
                  aria-label="Code theme"
                  aria-expanded={showThemePicker}
                >
                  <div
                    className="h-3.5 w-3.5 rounded-sm border border-border-strong"
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
                    <div className="animate-fade-in absolute right-0 top-full z-50 mt-1 w-44 rounded-lg border border-border bg-surface p-1 shadow-lg">
                      {(Object.entries(specThemes) as [SpecTheme, typeof specThemes.default][]).map(([key, value]) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => {
                            setSpecTheme(key);
                            setShowThemePicker(false);
                          }}
                          className={`flex w-full items-center gap-2 rounded-xs px-2 py-1.5 text-xs ${
                            specTheme === key
                              ? 'bg-accent-soft text-accent-fg'
                              : 'text-fg-muted hover:bg-subtle'
                          }`}
                        >
                          <div
                            className="h-3.5 w-3.5 rounded-sm border border-border"
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
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
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
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-xs font-medium text-fg-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
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
        <div className="flex items-center justify-center rounded-lg border border-border bg-surface p-16 shadow-xs">
          <div className="flex items-center gap-3">
            <Spinner />
            <span className="text-base text-fg-muted">Loading specification...</span>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-danger/30 bg-danger-soft/60 p-5">
          <div className="flex items-start gap-3">
            <svg className="mt-0.5 h-5 w-5 shrink-0 text-danger-fg" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <h3 className="text-base font-semibold text-danger-fg">
                Could not load specification
              </h3>
              <p className="mt-1 text-sm text-danger-fg">{error}</p>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && spec != null && viewMode === 'overview' && (
        <SpecOverview
          spec={spec}
          format={format}
          mockBaseUrl={mockBaseUrl}
          tenantSlug={tenantSlug}
          projectSlug={projectSlug}
          versionSlug={versionSlug}
          restApiBaseUrl={restApiBaseUrl}
          sdkEnabled={sdkEnabled}
        />
      )}

      {!loading && !error && spec != null && viewMode === 'visual' && (
        <SpecVisualCanvas spec={spec} format={format} isDark={resolvedTheme === 'dark'} />
      )}

      {!loading && !error && spec != null && viewMode === 'code' && (
        <div className="overflow-hidden rounded-lg border border-border">
          <div className="flex items-center justify-between border-b border-border bg-subtle/80 px-3 py-1.5">
            <div className="flex items-center gap-3 text-xs">
              <span className="font-mono font-medium text-fg-muted">
                {format === 'openapi'
                  ? `openapi.${viewFormat}`
                  : format === 'arazzo'
                  ? `arazzo.${viewFormat}`
                  : `schema.${viewFormat}`}
              </span>
              <span className="text-fg-muted tabular-nums">{lineCount} lines</span>
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
      <div className="text-2xs text-fg-muted">
        {ver && <span>v{ver}</span>}
        {oapi && <span> &middot; OpenAPI {oapi}</span>}
      </div>
    );
  }
  return null;
}

function SpecOverview({
  spec,
  format,
  mockBaseUrl,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
  sdkEnabled,
}: {
  spec: unknown;
  format: SpecFormat;
  mockBaseUrl?: string | null;
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
  /** Whether this project publishes an SDK, gating the per-operation snippet tabs (SDK-3.3). */
  sdkEnabled: boolean;
}) {
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
    const groups = new Map<string, { tag: string; description?: string; ops: SpecOperation[] }>();
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
            // SDK-3.3 (#4493): how the snippet route addresses this operation. Absent is fine —
            // the snippet helpers fall back to the canonical `GET /pets/{id}` key.
            operationId: typeof opRaw.operationId === 'string' ? opRaw.operationId : undefined,
          });
        }
      }
    }

    const orderedGroups = Array.from(groups.values());

    return (
      <div className="space-y-5">
        {/* Info card */}
        <div className="rounded-lg border border-border bg-surface p-5 shadow-xs">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-xl font-semibold text-fg">
                {info && typeof info.title === 'string' ? info.title : 'API'}
              </h3>
              {info && typeof info.description === 'string' && (
                <p className="mt-1 max-w-3xl text-sm leading-relaxed text-fg-muted">
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
        {(servers.length > 0 || mockBaseUrl) && (
          <section className="rounded-lg border border-border bg-surface p-5 shadow-xs">
            <h4 className="mb-3 text-2xs font-semibold uppercase tracking-wider text-fg-muted">
              Servers
            </h4>
            <ul className="space-y-2">
              {mockBaseUrl && (
                <li className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-xs bg-ok-soft text-ok-fg">
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="block break-all rounded-xs bg-subtle px-2 py-1 font-mono text-xs text-fg">
                        {mockBaseUrl}
                      </code>
                      <span className="inline-flex items-center rounded-full bg-ok-soft px-1.5 py-0.5 text-2xs font-medium text-ok-fg">
                        Mock
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-fg-muted">
                      Mock server — responses generated from this specification.
                    </p>
                  </div>
                </li>
              )}
              {servers.map((s, i) => {
                if (!isObject(s)) return null;
                const url = typeof s.url === 'string' ? s.url : '';
                const desc = typeof s.description === 'string' ? s.description : undefined;
                return (
                  <li key={i} className="flex items-start gap-3">
                    <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-xs bg-subtle text-fg-muted">
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" />
                      </svg>
                    </span>
                    <div className="min-w-0 flex-1">
                      <code className="block break-all rounded-xs bg-subtle px-2 py-1 font-mono text-xs text-fg">
                        {url}
                      </code>
                      {desc && <p className="mt-1 text-xs text-fg-muted">{desc}</p>}
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
            <h4 className="text-2xs font-semibold uppercase tracking-wider text-fg-muted">
              Operations
            </h4>
            {orderedGroups.map((group) => (
              <div
                key={group.tag}
                className="overflow-hidden rounded-lg border border-border bg-surface shadow-xs"
              >
                <div className="border-b border-border bg-subtle/60 px-4 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h5 className="text-base font-semibold text-fg">{group.tag}</h5>
                      {group.description && (
                        <p className="mt-0.5 text-xs text-fg-muted">{group.description}</p>
                      )}
                    </div>
                    <span className="text-2xs tabular-nums text-fg-muted">
                      {group.ops.length} {group.ops.length === 1 ? 'operation' : 'operations'}
                    </span>
                  </div>
                </div>
                <ul className="divide-y divide-border">
                  {group.ops.map((op, idx) => (
                    <OperationRow
                      key={`${operationAnchorId(op.method, op.path)}-${idx}`}
                      op={op}
                      spec={spec}
                      mockBaseUrl={mockBaseUrl}
                      tenantSlug={tenantSlug}
                      projectSlug={projectSlug}
                      versionSlug={versionSlug}
                      restApiBaseUrl={restApiBaseUrl}
                      sdkEnabled={sdkEnabled}
                    />
                  ))}
                </ul>
              </div>
            ))}
          </section>
        )}

        {schemaNames.length > 0 && (
          <section className="space-y-3">
            <h4 className="text-2xs font-semibold uppercase tracking-wider text-fg-muted">
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
                    className="scroll-mt-24 rounded-lg border border-border bg-surface p-4 shadow-xs"
                  >
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 shrink-0 rounded-xs bg-violet-soft px-1.5 py-0.5 font-mono text-2xs font-semibold uppercase text-violet-fg">
                        CLS
                      </span>
                      <div className="min-w-0 flex-1">
                        <code className="break-all font-mono text-sm font-semibold text-fg">
                          {schemaName}
                        </code>
                        {title && (
                          <p className="mt-1 text-xs font-medium text-fg-muted">{title}</p>
                        )}
                        {description && (
                          <p className="mt-1 line-clamp-4 text-xs leading-relaxed text-fg-muted">
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
      <div className="rounded-lg border border-border bg-surface p-5 shadow-xs">
        <h3 className="text-xl font-semibold text-fg">Arazzo workflows</h3>
        <p className="mt-1 text-sm text-fg-muted">
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
                  className="scroll-mt-24 rounded-lg border border-border p-3"
                >
                  <div className="flex items-center gap-2">
                    <span className="rounded-xs bg-accent-soft px-1.5 py-0.5 font-mono text-2xs font-semibold uppercase text-accent-fg">
                      WF
                    </span>
                    <code className="font-mono text-sm font-medium text-fg">{id}</code>
                  </div>
                  {summary && <p className="mt-1 text-xs text-fg-muted">{summary}</p>}
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
    <div className="rounded-lg border border-border bg-surface p-5 shadow-xs">
      <h3 className="text-xl font-semibold text-fg">JSON Schema</h3>
      <p className="mt-1 text-sm text-fg-muted">
        {defNames.length} top-level definition{defNames.length === 1 ? '' : 's'}.
      </p>
      {defNames.length > 0 && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {defNames.map((name) => (
            <li
              key={name}
              id={`def-${name.replace(/[^a-z0-9]+/gi, '-')}`}
              className="scroll-mt-24 rounded-xs border border-border px-3 py-2 font-mono text-xs text-fg"
            >
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One operation row in the overview list, with its inline "Try It" disclosure — SIM-3.1 (#4447)
 * — and, for projects that publish an SDK, its "Code" disclosure — SDK-3.3 (#4493).
 *
 * Neither panel lives here: Try It is `tryit/TryItPanel` and the snippets are
 * `sdk/OperationSnippetTabs`. This row owns only which of the two is expanded — at most one, so
 * a long row never pushes the next operation off the screen twice over.
 */
function OperationRow({
  op,
  spec,
  mockBaseUrl,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
  sdkEnabled,
}: {
  op: SpecOperation;
  spec: unknown;
  mockBaseUrl?: string | null;
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
  sdkEnabled: boolean;
}) {
  const [openPanel, setOpenPanel] = useState<'tryit' | 'code' | null>(null);
  const anchor = operationAnchorId(op.method, op.path);
  const panelId = `${anchor}-tryit`;
  const codePanelId = `${anchor}-code`;
  const tryItOpen = openPanel === 'tryit';
  const codeOpen = openPanel === 'code';
  const toggle = (panel: 'tryit' | 'code') =>
    setOpenPanel((current) => (current === panel ? null : panel));

  return (
    <li id={anchor} className="scroll-mt-24">
      <div className="flex items-start gap-3 px-4 py-2.5">
        <span
          className={`shrink-0 rounded-xs px-1.5 py-0.5 font-mono text-2xs font-semibold uppercase tracking-wide ring-1 ring-inset ${
            HTTP_METHOD_TONE[op.method.toLowerCase()] ?? HTTP_METHOD_TONE.options
          }`}
        >
          {op.method}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <code className="break-all font-mono text-sm font-medium text-fg">
              {op.path}
            </code>
            {op.deprecated && (
              <span className="inline-flex items-center rounded-full bg-honey-soft px-1.5 py-0.5 text-2xs font-medium text-honey-fg">
                deprecated
              </span>
            )}
          </div>
          {op.summary && (
            <p className="mt-0.5 text-xs text-fg-muted">{op.summary}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {sdkEnabled && (
            <DisclosureButton
              label="Code"
              open={codeOpen}
              controls={codePanelId}
              onClick={() => toggle('code')}
            />
          )}
          <DisclosureButton
            label="Try It"
            open={tryItOpen}
            controls={panelId}
            onClick={() => toggle('tryit')}
          />
        </div>
      </div>
      {codeOpen && (
        <div id={codePanelId} className="px-4 pb-4">
          <OperationSnippetTabs
            coords={{ tenantSlug, projectSlug, versionSlug }}
            restApiBaseUrl={restApiBaseUrl}
            method={op.method}
            path={op.path}
            operationId={op.operationId}
          />
        </div>
      )}
      {tryItOpen && (
        <div id={panelId} className="px-4 pb-4">
          <TryItPanel
            spec={spec}
            method={op.method}
            path={op.path}
            mockBaseUrl={mockBaseUrl}
            tenantSlug={tenantSlug}
            projectSlug={projectSlug}
            versionSlug={versionSlug}
          />
        </div>
      )}
    </li>
  );
}

/** The chevron toggle both operation-row disclosures use. */
function DisclosureButton({
  label,
  open,
  controls,
  onClick,
}: {
  label: string;
  open: boolean;
  controls: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      aria-controls={controls}
      className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1 text-2xs font-medium transition-colors ${
        open
          ? 'bg-accent-soft text-accent-fg'
          : 'border border-border bg-surface text-fg-muted shadow-xs hover:bg-subtle'
      }`}
    >
      {label}
      <svg
        className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    </button>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-subtle px-3 py-2">
      <div className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
        {label}
      </div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums text-fg">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function Pill({ children, tone }: { children: React.ReactNode; tone: 'brand' | 'neutral' }) {
  const cls =
    tone === 'brand'
      ? 'bg-accent-soft text-accent-fg'
      : 'bg-subtle text-fg-muted';
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium ${cls}`}>
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
    <div className="inline-flex items-center gap-0.5 rounded-md bg-subtle p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-xs px-2.5 py-1 text-xs font-medium transition-colors ${
            value === opt.value
              ? 'bg-surface text-fg shadow-xs'
              : 'text-fg-muted hover:text-fg'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function Divider() {
  return <span className="hidden h-5 w-px bg-inset sm:inline-block" />;
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
          ? 'bg-accent-soft text-accent-fg'
          : 'border border-border bg-surface text-fg-muted shadow-xs hover:bg-subtle'
      }`}
    >
      {children}
    </button>
  );
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4 text-ok-fg" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  );
}
