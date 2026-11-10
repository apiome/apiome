'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import type { Monaco } from '@monaco-editor/react';
import {
  buildMonacoBodySchema,
  buildRequestHeaders,
  buildRequestUrl,
  buildServerOptions,
  extractOperationModel,
  isJsonContentType,
  paramKey,
  validateParams,
  type ExtraHeader,
  type ParamSpec,
} from '../../../../lib/tryit/operation';
import {
  applyAuthToRequest,
  authSecretPlaceholders,
  loadAuthCredentials,
  resolveOperationAuth,
  saveAuthCredentials,
  type AuthCredentialValues,
  type AuthCredentialsMap,
} from '../../../../lib/tryit/auth';
import {
  bodyVariantHasPrefillSupport,
  buildInitialParamValues,
  collectBodyExamples,
  describeBodySource,
  formatBodyForEditor,
  type BodySource,
  type NamedBodyExample,
} from '../../../../lib/tryit/examples';
import { fetchGeneratedBodySample, SampleSynthesisError } from '../../../../lib/tryit/sample';
import { describeSendFailure } from '../../../../lib/tryit/response';
import {
  sendTryIt,
  TryItSendError,
  type TryItResult,
  type TryItSendErrorKind,
} from '../../../../lib/tryit/send';
import { AuthHelpers } from './AuthHelpers';
import { CodeSnippetPanel } from './CodeSnippetPanel';
import { ResponseViewer } from './ResponseViewer';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="flex h-[180px] items-center justify-center rounded-lg border border-border bg-subtle text-xs text-fg-muted">
      Loading editor...
    </div>
  ),
});

/** HTTP methods that carry a request body in the Try It panel. */
const BODY_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** Sentinel value for the custom-URL entry in the server picker. */
const CUSTOM_SERVER = '__custom__';

interface TryItPanelProps {
  /** The parsed OpenAPI document the operation belongs to. */
  spec: unknown;
  /** HTTP method of the operation (any case). */
  method: string;
  /** The templated operation path, e.g. `/pets/{petId}`. */
  path: string;
  /** The version's public mock base URL; null/undefined when its mock is disabled (SIM-2.3). */
  mockBaseUrl?: string | null;
  /** Browsed version coordinates, forwarded to the SIM-3.2 relay for its allow-policy. */
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
}

/**
 * Try It request builder — SIM-3.1 (#4447).
 *
 * Rendered inline under an operation row: server picker (mock → spec `servers[]` → custom URL),
 * a parameter form generated from the spec, a Monaco body editor with JSON-schema validation,
 * the send pipeline (`lib/tryit/send`), and the SIM-3.3 response viewer (`ResponseViewer`).
 * Example prefill and schema synthesis are SIM-3.4 (#4450); copy-as-code snippets are SIM-3.5
 * (#4451); scheme-aware auth helpers are SIM-3.6 (#4452).
 */
export function TryItPanel({
  spec,
  method,
  path,
  mockBaseUrl,
  tenantSlug,
  projectSlug,
  versionSlug,
}: TryItPanelProps) {
  const idBase = useId();
  const model = useMemo(() => extractOperationModel(spec, method, path), [spec, method, path]);
  const servers = useMemo(() => buildServerOptions(spec, mockBaseUrl), [spec, mockBaseUrl]);
  const operationAuth = useMemo(
    () => resolveOperationAuth(spec, method, path),
    [spec, method, path]
  );
  const authSchemeNames = useMemo(
    () => operationAuth.schemes.map((scheme) => scheme.name),
    [operationAuth]
  );

  const [serverChoice, setServerChoice] = useState<string>(
    servers.length > 0 ? '0' : CUSTOM_SERVER
  );
  const [customUrl, setCustomUrl] = useState('');
  const [customConfirmed, setCustomConfirmed] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(() =>
    buildInitialParamValues(model?.params ?? [])
  );
  const [extraHeaders, setExtraHeaders] = useState<ExtraHeader[]>([]);
  const [authCredentials, setAuthCredentials] = useState<AuthCredentialsMap>({});
  const [contentTypeIdx, setContentTypeIdx] = useState(0);
  const [bodyText, setBodyText] = useState('');
  const [bodySource, setBodySource] = useState<BodySource>({ kind: 'empty' });
  const [selectedExampleName, setSelectedExampleName] = useState<string | null>(null);
  const [generateSeed, setGenerateSeed] = useState(1);
  const [generatingSample, setGeneratingSample] = useState(false);
  const [sampleError, setSampleError] = useState<string | null>(null);
  const skipManualBodySourceRef = useRef(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<TryItResult | null>(null);
  const [sendError, setSendError] = useState<{
    kind: TryItSendErrorKind | null;
    message: string;
  } | null>(null);

  // Hydrate auth credentials from sessionStorage when the operation's schemes change.
  useEffect(() => {
    setAuthCredentials(loadAuthCredentials(authSchemeNames));
  }, [authSchemeNames]);

  // Reset the server choice if the option list changes shape (e.g. spec reloads).
  useEffect(() => {
    setServerChoice((prev) =>
      prev === CUSTOM_SERVER || Number(prev) < servers.length
        ? prev
        : servers.length > 0
        ? '0'
        : CUSTOM_SERVER
    );
  }, [servers]);

  const isCustom = serverChoice === CUSTOM_SERVER;
  const selectedServer = !isCustom ? servers[Number(serverChoice)] : undefined;
  const serverUrl = isCustom ? customUrl.trim() : selectedServer?.url ?? '';

  const hasBody = model != null && BODY_METHODS.has(model.method) && model.bodyVariants.length > 0;
  const bodyVariant = hasBody
    ? model.bodyVariants[Math.min(contentTypeIdx, model.bodyVariants.length - 1)]
    : undefined;
  const bodyIsJson = bodyVariant != null && isJsonContentType(bodyVariant.contentType);
  const bodyExamples = useMemo(
    () => (bodyVariant ? collectBodyExamples(bodyVariant) : []),
    [bodyVariant]
  );
  const canGenerateSample = bodyVariant != null && bodyVariant.schema != null;
  const showPrefillControls = hasBody && bodyVariant != null && bodyVariantHasPrefillSupport(bodyVariant);
  const bodySourceLabel = describeBodySource(bodySource);

  const applyBodyFromExample = useCallback(
    (example: NamedBodyExample) => {
      if (!bodyVariant) return;
      skipManualBodySourceRef.current = true;
      setBodyText(formatBodyForEditor(example.value, bodyIsJson));
      setBodySource({ kind: 'example', name: example.name });
      setSelectedExampleName(example.name);
      setSampleError(null);
    },
    [bodyVariant, bodyIsJson]
  );

  const applyBodyFromGenerated = useCallback(
    (value: unknown, seed: number) => {
      if (!bodyVariant) return;
      skipManualBodySourceRef.current = true;
      setBodyText(formatBodyForEditor(value, bodyIsJson));
      setBodySource({ kind: 'generated', seed });
      setSelectedExampleName(null);
      setSampleError(null);
    },
    [bodyVariant, bodyIsJson]
  );

  // Prefill from the first named example when the body variant changes (content-type switch).
  useEffect(() => {
    if (!bodyVariant) {
      setBodyText('');
      setBodySource({ kind: 'empty' });
      setSelectedExampleName(null);
      return;
    }
    const examples = collectBodyExamples(bodyVariant);
    if (examples.length > 0) {
      applyBodyFromExample(examples[0]);
    } else {
      skipManualBodySourceRef.current = true;
      setBodyText('');
      setBodySource({ kind: 'empty' });
      setSelectedExampleName(null);
    }
    setGenerateSeed(1);
    setSampleError(null);
  }, [bodyVariant, applyBodyFromExample]);

  // Rebuild param defaults when the operation model changes.
  useEffect(() => {
    if (!model) return;
    setValues(buildInitialParamValues(model.params));
  }, [model]);

  const onExampleSelect = useCallback(
    (name: string) => {
      const example = bodyExamples.find((entry) => entry.name === name);
      if (!example) return;
      applyBodyFromExample(example);
    },
    [bodyExamples, applyBodyFromExample]
  );

  const onGenerateSample = useCallback(async () => {
    if (!bodyVariant?.schema) return;
    setGeneratingSample(true);
    setSampleError(null);
    try {
      const { value, seed } = await fetchGeneratedBodySample({
        schema: bodyVariant.schema,
        spec,
        seed: generateSeed,
      });
      applyBodyFromGenerated(value, seed);
      setGenerateSeed((prev) => prev + 1);
    } catch (err) {
      setSampleError(
        err instanceof SampleSynthesisError ? err.message : 'Could not generate a sample body.'
      );
    } finally {
      setGeneratingSample(false);
    }
  }, [bodyVariant, spec, generateSeed, applyBodyFromGenerated]);
  const monacoSchema = useMemo(
    () => (bodyVariant && bodyIsJson ? buildMonacoBodySchema(spec, bodyVariant.schema) : null),
    [spec, bodyVariant, bodyIsJson]
  );
  // Unique Monaco model path so each panel's schema only validates its own editor. The extension
  // drives the model language: `.json` gets JSON diagnostics, `.txt` stays plain.
  const monacoPath = `tryit://${idBase.replace(/[^a-zA-Z0-9]/g, '')}/body.${bodyIsJson ? 'json' : 'txt'}`;

  // (Re-)register this panel's body schema with Monaco's JSON diagnostics — on first mount and
  // whenever the selected content type changes the schema. Other panels' entries are preserved.
  const monacoRef = useRef<Monaco | null>(null);
  const registerSchema = useCallback(
    (monaco: Monaco) => {
      const defaults = monaco.languages.json.jsonDefaults;
      const others = (defaults.diagnosticsOptions.schemas ?? []).filter(
        (s: { fileMatch?: string[] }) => !s.fileMatch?.some((m) => m.startsWith('tryit://') && m.includes(idBase.replace(/[^a-zA-Z0-9]/g, '')))
      );
      defaults.setDiagnosticsOptions({
        ...defaults.diagnosticsOptions,
        validate: true,
        enableSchemaRequest: false,
        schemas: monacoSchema
          ? [
              ...others,
              {
                uri: `apiome://tryit/${idBase.replace(/[^a-zA-Z0-9]/g, '')}/schema.json`,
                fileMatch: [monacoPath],
                schema: monacoSchema,
              },
            ]
          : others,
      });
    },
    [idBase, monacoPath, monacoSchema]
  );
  useEffect(() => {
    if (monacoRef.current) registerSchema(monacoRef.current);
  }, [registerSchema]);

  const setValue = useCallback((key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const onAuthChange = useCallback((schemeName: string, next: AuthCredentialValues) => {
    setAuthCredentials((prev) => ({ ...prev, [schemeName]: next }));
    saveAuthCredentials(schemeName, next);
  }, []);

  const secretPlaceholders = useMemo(
    () => authSecretPlaceholders(operationAuth.schemes, authCredentials),
    [operationAuth.schemes, authCredentials]
  );

  const onSend = useCallback(async () => {
    if (!model) return;
    setFormError(null);
    setSendError(null);
    setResult(null);

    if (!serverUrl) {
      setFormError('Pick a server or enter a custom URL before sending.');
      return;
    }
    if (isCustom && !customConfirmed) {
      setFormError('Confirm that you trust the custom host before sending.');
      return;
    }
    const nextErrors = validateParams(model.params, values);
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      setFormError('Fix the highlighted parameters before sending.');
      return;
    }
    let body: string | null = null;
    if (hasBody && bodyText.trim() !== '') {
      if (bodyIsJson) {
        try {
          JSON.parse(bodyText);
        } catch {
          setFormError('The request body is not valid JSON.');
          return;
        }
      }
      body = bodyText;
    }
    if (hasBody && body == null && model.bodyRequired) {
      setFormError('This operation requires a request body.');
      return;
    }

    const composedUrl = buildRequestUrl(serverUrl, model.path, model.params, values);
    const composedHeaders = buildRequestHeaders(
      model.params,
      values,
      extraHeaders,
      body != null && bodyVariant ? bodyVariant.contentType : null
    );
    const withAuth = applyAuthToRequest(
      composedUrl,
      composedHeaders,
      operationAuth.schemes,
      authCredentials
    );

    setSending(true);
    try {
      const response = await sendTryIt(
        {
          method: model.method,
          url: withAuth.url,
          headers: withAuth.headers,
          body,
          target: {
            kind: isCustom ? 'custom' : selectedServer?.kind ?? 'custom',
            ...(isCustom ? { customHostConfirmed: customConfirmed } : {}),
          },
          context: { tenantSlug, projectSlug, versionSlug },
        },
        { pageOrigin: window.location.origin }
      );
      setResult(response);
    } catch (err) {
      if (err instanceof TryItSendError) {
        setSendError({ kind: err.kind, message: err.message });
      } else {
        setSendError({
          kind: null,
          message: err instanceof Error ? err.message : 'Request failed.',
        });
      }
    } finally {
      setSending(false);
    }
  }, [
    model,
    serverUrl,
    isCustom,
    customConfirmed,
    values,
    hasBody,
    bodyText,
    bodyIsJson,
    extraHeaders,
    bodyVariant,
    selectedServer,
    tenantSlug,
    projectSlug,
    versionSlug,
    operationAuth.schemes,
    authCredentials,
  ]);

  if (!model) {
    return (
      <div className="rounded-lg border border-border bg-subtle p-3 text-xs text-fg-muted">
        This operation could not be read from the specification.
      </div>
    );
  }

  const pathParams = model.params.filter((p) => p.location === 'path');
  const queryParams = model.params.filter((p) => p.location === 'query');
  const headerParams = model.params.filter((p) => p.location === 'header');

  return (
    <div className="space-y-4 rounded-lg border border-border bg-subtle/60 p-4">
      {/* Server picker */}
      <div>
        <label
          htmlFor={`${idBase}-server`}
          className="mb-1 block text-2xs font-medium uppercase tracking-wider text-fg-muted"
        >
          Server
        </label>
        <select
          id={`${idBase}-server`}
          value={serverChoice}
          onChange={(e) => setServerChoice(e.target.value)}
          className="control control-sm font-mono"
        >
          {servers.map((server, i) => (
            <option key={`${server.kind}-${server.url}`} value={String(i)}>
              {server.kind === 'mock' ? `mock: ${server.url}` : server.url}
              {server.description ? ` — ${server.description}` : ''}
            </option>
          ))}
          <option value={CUSTOM_SERVER}>Custom URL…</option>
        </select>
        {isCustom && (
          <div className="mt-2 space-y-2">
            <input
              type="url"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
              aria-label="Custom server URL"
              className="control control-sm font-mono"
            />
            <label className="flex items-start gap-2 text-xs text-fg-muted">
              <input
                type="checkbox"
                checked={customConfirmed}
                onChange={(e) => setCustomConfirmed(e.target.checked)}
                className="mt-0.5 h-3.5 w-3.5 rounded-xs border-border-strong text-accent-fg"
              />
              <span>
                I trust this host — requests are relayed with the headers and body entered above.
              </span>
            </label>
          </div>
        )}
      </div>

      {/* Parameters */}
      {pathParams.length > 0 && (
        <ParamGroup label="Path parameters" params={pathParams} values={values} errors={errors} onChange={setValue} idBase={idBase} />
      )}
      {queryParams.length > 0 && (
        <ParamGroup label="Query parameters" params={queryParams} values={values} errors={errors} onChange={setValue} idBase={idBase} />
      )}
      {headerParams.length > 0 && (
        <ParamGroup label="Headers" params={headerParams} values={values} errors={errors} onChange={setValue} idBase={idBase} />
      )}

      <AuthHelpers
        auth={operationAuth}
        credentials={authCredentials}
        onChange={onAuthChange}
        isCustomHost={isCustom}
      />

      {/* User-added headers */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Additional headers
          </span>
          <button
            type="button"
            onClick={() => setExtraHeaders((prev) => [...prev, { name: '', value: '' }])}
            className="rounded-md border border-border bg-surface px-2 py-1 text-2xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
          >
            + Add header
          </button>
        </div>
        {extraHeaders.length > 0 && (
          <ul className="space-y-2">
            {extraHeaders.map((header, i) => (
              <li key={i} className="flex items-center gap-2">
                <input
                  type="text"
                  value={header.name}
                  onChange={(e) =>
                    setExtraHeaders((prev) =>
                      prev.map((h, j) => (j === i ? { ...h, name: e.target.value } : h))
                    )
                  }
                  placeholder="Header name"
                  aria-label={`Additional header ${i + 1} name`}
                  className="control control-sm w-2/5 font-mono"
                />
                <input
                  type="text"
                  value={header.value}
                  onChange={(e) =>
                    setExtraHeaders((prev) =>
                      prev.map((h, j) => (j === i ? { ...h, value: e.target.value } : h))
                    )
                  }
                  placeholder="Value"
                  aria-label={`Additional header ${i + 1} value`}
                  className="control control-sm min-w-0 flex-1 font-mono"
                />
                <button
                  type="button"
                  onClick={() => setExtraHeaders((prev) => prev.filter((_, j) => j !== i))}
                  aria-label={`Remove additional header ${i + 1}`}
                  className="rounded-md border border-border bg-surface px-2 py-1.5 text-2xs text-fg-muted shadow-xs transition-colors hover:bg-subtle hover:text-danger-fg"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Body editor */}
      {hasBody && (
        <div>
          <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <label
                htmlFor={`${idBase}-body`}
                className="text-2xs font-medium uppercase tracking-wider text-fg-muted"
              >
                Request body{model.bodyRequired ? ' (required)' : ''}
              </label>
              {bodySourceLabel && (
                <span className="rounded-md bg-inset/80 px-2 py-0.5 font-mono text-2xs text-fg-muted">
                  {bodySourceLabel}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {showPrefillControls && bodyExamples.length > 0 && (
                <select
                  value={selectedExampleName ?? ''}
                  onChange={(e) => onExampleSelect(e.target.value)}
                  aria-label="Request body example"
                  className="control control-sm font-mono w-auto"
                >
                  {bodyExamples.map((example) => (
                    <option key={example.name} value={example.name}>
                      {example.name === 'example' ? 'Example' : example.name}
                      {example.summary ? ` — ${example.summary}` : ''}
                    </option>
                  ))}
                </select>
              )}
              {showPrefillControls && canGenerateSample && (
                <button
                  type="button"
                  onClick={onGenerateSample}
                  disabled={generatingSample}
                  className="rounded-md border border-border bg-surface px-2 py-1 text-2xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {generatingSample ? 'Generating…' : 'Generate sample'}
                </button>
              )}
              {model.bodyVariants.length > 1 && (
                <select
                  value={String(contentTypeIdx)}
                  onChange={(e) => setContentTypeIdx(Number(e.target.value))}
                  aria-label="Request body content type"
                  className="control control-sm font-mono w-auto"
                >
                  {model.bodyVariants.map((variant, i) => (
                    <option key={variant.contentType} value={String(i)}>
                      {variant.contentType}
                    </option>
                  ))}
                </select>
              )}
              {model.bodyVariants.length === 1 && (
                <span className="font-mono text-2xs text-fg-muted">
                  {model.bodyVariants[0].contentType}
                </span>
              )}
            </div>
          </div>
          {sampleError && (
            <p role="alert" className="mb-1 text-2xs font-medium text-danger-fg">
              {sampleError}
            </p>
          )}
          <div
            id={`${idBase}-body`}
            className="overflow-hidden rounded-lg border border-border"
          >
            <Editor
              height="180px"
              language={bodyIsJson ? 'json' : 'plaintext'}
              path={monacoPath}
              value={bodyText}
              onChange={(next) => {
                setBodyText(next ?? '');
                if (skipManualBodySourceRef.current) {
                  skipManualBodySourceRef.current = false;
                  return;
                }
                const trimmed = (next ?? '').trim();
                setBodySource(trimmed === '' ? { kind: 'empty' } : { kind: 'manual' });
              }}
              beforeMount={(monaco) => {
                monacoRef.current = monaco;
                registerSchema(monaco);
              }}
              options={{
                minimap: { enabled: false },
                lineNumbers: 'off',
                scrollBeyondLastLine: false,
                fontSize: 12,
                fontFamily:
                  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                automaticLayout: true,
                folding: false,
                renderLineHighlight: 'none',
                tabSize: 2,
              }}
            />
          </div>
        </div>
      )}

      <CodeSnippetPanel
        method={model.method}
        serverUrl={serverUrl}
        path={model.path}
        params={model.params}
        values={values}
        extraHeaders={extraHeaders}
        bodyText={bodyText}
        contentType={
          hasBody && bodyText.trim() !== '' && bodyVariant ? bodyVariant.contentType : null
        }
        authSchemes={operationAuth.schemes}
        authCredentials={authCredentials}
        secretPlaceholders={secretPlaceholders}
      />

      {/* Send */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onSend}
          disabled={sending}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-fg-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sending ? 'Sending…' : 'Send'}
        </button>
        {formError && (
          <p role="alert" className="text-xs font-medium text-danger-fg">
            {formError}
          </p>
        )}
      </div>

      {/* Outcome — the SIM-3.3 response viewer, or a distinct card per send-failure kind */}
      <div aria-live="polite">
        {sendError && (
          <div className="rounded-lg border border-danger/30 bg-danger-soft/60 p-3">
            <p className="text-xs font-semibold text-danger-fg">
              {sendError.kind ? describeSendFailure(sendError.kind).title : 'Request failed'}
            </p>
            <p className="mt-1 text-xs text-danger-fg/90">
              {sendError.message}
            </p>
            {sendError.kind && (
              <p className="mt-1 text-xs text-danger-fg/80">
                {describeSendFailure(sendError.kind).hint}
              </p>
            )}
          </div>
        )}
        {result && <ResponseViewer result={result} operationPath={model.path} />}
      </div>
    </div>
  );
}

/** One labelled group of parameter controls (path, query, or header parameters). */
function ParamGroup({
  label,
  params,
  values,
  errors,
  onChange,
  idBase,
}: {
  label: string;
  params: ParamSpec[];
  values: Record<string, string>;
  errors: Record<string, string>;
  onChange: (key: string, value: string) => void;
  idBase: string;
}) {
  return (
    <fieldset>
      <legend className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-muted">
        {label}
      </legend>
      <div className="space-y-2">
        {params.map((param) => (
          <ParamField
            key={paramKey(param)}
            param={param}
            value={values[paramKey(param)] ?? ''}
            error={errors[paramKey(param)]}
            onChange={onChange}
            idBase={idBase}
          />
        ))}
      </div>
    </fieldset>
  );
}

/** One parameter control: select for enums, checkbox for booleans, text input otherwise. */
function ParamField({
  param,
  value,
  error,
  onChange,
  idBase,
}: {
  param: ParamSpec;
  value: string;
  error?: string;
  onChange: (key: string, value: string) => void;
  idBase: string;
}) {
  const key = paramKey(param);
  const inputId = `${idBase}-${key.replace(/[^a-zA-Z0-9]/g, '-')}`;
  const errorId = `${inputId}-error`;
  const { type, enum: allowed, format } = param.schema;

  const meta = [type, format].filter(Boolean).join(' · ');
  const labelEl = (
    <label htmlFor={inputId} className="flex items-center gap-1.5 font-mono text-xs text-fg">
      {param.name}
      {param.required && (
        <span className="text-danger-fg" title="Required">
          *
        </span>
      )}
      {meta && <span className="font-sans text-2xs text-fg-subtle">({meta})</span>}
    </label>
  );

  const inputClass = `control control-sm font-mono ${error ? 'control-invalid' : ''}`;

  return (
    <div className="grid gap-1 sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)] sm:items-center sm:gap-3">
      {labelEl}
      <div>
        {allowed ? (
          <select
            id={inputId}
            value={value}
            onChange={(e) => onChange(key, e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className={inputClass}
          >
            <option value="">{param.required ? 'Select…' : '(not set)'}</option>
            {allowed.map((v) => (
              <option key={String(v)} value={String(v)}>
                {String(v)}
              </option>
            ))}
          </select>
        ) : type === 'boolean' ? (
          <input
            id={inputId}
            type="checkbox"
            checked={value === 'true'}
            onChange={(e) => onChange(key, e.target.checked ? 'true' : '')}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="h-4 w-4 rounded-xs border-border-strong text-accent-fg"
          />
        ) : (
          <input
            id={inputId}
            type="text"
            inputMode={type === 'integer' || type === 'number' ? 'numeric' : undefined}
            value={value}
            onChange={(e) => onChange(key, e.target.value)}
            placeholder={param.description}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className={inputClass}
          />
        )}
        {error && (
          <p id={errorId} role="alert" className="mt-0.5 text-2xs font-medium text-danger-fg">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
