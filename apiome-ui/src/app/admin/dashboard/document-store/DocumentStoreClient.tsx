'use client';

/**
 * **Document store** in the admin console (`/admin/dashboard/document-store`, COA-5.9, #7085).
 *
 * Shows where Apiome keeps captured originals, rendered documents and large export downloads:
 * the active backend and its settings, whether it answers, how much the document index holds and
 * when an integrity run last verified an object. **Test connection** asks apiome-rest to write,
 * read back and delete a probe object and lists each step.
 *
 * The REST server's environment (`APIOME_DOCUMENT_STORE*`) is the only place the store is set,
 * so nothing here is editable, and no credential ever reaches the browser. Every read goes
 * through the super-admin proxy (`/api/admin/document-store`); the UI never talks to the bucket.
 */
import { useCallback, useEffect, useId, useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleSlash, Loader2, PlugZap, RefreshCw, XCircle } from 'lucide-react';
import { extractRestErrorMessage } from '@lib/auth/admin-provider-config';
import {
  PROBE_STEP_LABELS,
  backendLabel,
  formatBytes,
  formatWhen,
  settingRows,
  type DocumentStoreProbeResult,
  type DocumentStoreStatus,
} from '@lib/admin-document-store';
import { NEUTRAL_CHIP_CLASSES, PRIMARY_BUTTON_CLASSES, SECONDARY_BUTTON_CLASSES } from '../settings/settingsStyles';

/** Proxy route the page reads from. */
const STATUS_URL = '/api/admin/document-store';
/** Proxy route the connection test posts to. */
const TEST_URL = '/api/admin/document-store/test';
/** Shown when the proxy rejects the admin session. */
const SESSION_EXPIRED = 'Your admin session has expired. Sign out and back in.';

/** Shared classes for the page's cards. */
const CARD_CLASSES =
  'rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900';
/** Shared classes for a card heading. */
const CARD_TITLE_CLASSES = 'text-base font-semibold text-slate-900 dark:text-slate-100';
/** Green "working" chip. */
const OK_CHIP_CLASSES =
  'inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-2xs font-medium text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300';
/** Red "failing" chip. */
const FAIL_CHIP_CLASSES =
  'inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-2xs font-medium text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300';
/** Amber notice, for the startup fallback. */
const WARNING_CLASSES =
  'flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200';
/** Red notice, for a load failure. */
const ERROR_CLASSES =
  'flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300';
/** A label in a definition list. */
const TERM_CLASSES = 'text-sm text-slate-500 dark:text-slate-400';
/** A value in a definition list. */
const VALUE_CLASSES = 'text-sm text-slate-900 dark:text-slate-100 break-all';

/**
 * Read a proxy response: the parsed body, or the message to show instead.
 *
 * @param response The proxy's response.
 * @param fallback The message when the body names none.
 * @returns `{ body }` on success, `{ error }` otherwise.
 */
async function readResponse<T>(response: Response, fallback: string): Promise<{ body: T } | { error: string }> {
  const body: unknown = await response.json().catch(() => null);
  if (response.ok) return { body: body as T };
  if (response.status === 401 || response.status === 403) return { error: SESSION_EXPIRED };
  return { error: extractRestErrorMessage(body, fallback) };
}

/** The page: status, settings, usage and the connection test. */
export default function DocumentStoreClient() {
  const [status, setStatus] = useState<DocumentStoreStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [probe, setProbe] = useState<DocumentStoreProbeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await readResponse<DocumentStoreStatus>(
        await fetch(STATUS_URL, { cache: 'no-store' }),
        'Could not load the document store.',
      );
      if ('error' in result) setLoadError(result.error);
      else setStatus(result.body);
    } catch {
      setLoadError('Could not load the document store: the server could not be reached.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runTest = useCallback(async () => {
    setTesting(true);
    setProbeError(null);
    try {
      const result = await readResponse<DocumentStoreProbeResult>(
        await fetch(TEST_URL, { method: 'POST', cache: 'no-store' }),
        'The connection test could not run.',
      );
      if ('error' in result) {
        setProbe(null);
        setProbeError(result.error);
        return;
      }
      setProbe(result.body);
      // The test refreshes the server's health check; show it.
      void load();
    } catch {
      setProbe(null);
      setProbeError('The connection test could not run: the server could not be reached.');
    } finally {
      setTesting(false);
    }
  }, [load]);

  return (
    <>
      <header className="shrink-0 border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-4 px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Document store</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Where Apiome keeps captured originals, rendered documents and large exports. Set by the REST
              server&apos;s <code className="font-mono">APIOME_DOCUMENT_STORE*</code> environment; read-only here.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              className={SECONDARY_BUTTON_CLASSES}
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Refresh
            </button>
            <button
              type="button"
              onClick={() => void runTest()}
              disabled={testing || status === null}
              className={PRIMARY_BUTTON_CLASSES}
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}
              {testing ? 'Testing…' : 'Test connection'}
            </button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-6 dark:bg-slate-950" data-testid="document-store-page">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {loading && status === null && (
            <div className="flex items-center gap-2 py-10 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading the document store…
            </div>
          )}

          {loadError && (
            <div role="alert" className={ERROR_CLASSES}>
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>{loadError}</p>
            </div>
          )}

          {status && (
            <>
              {status.fallback && (
                <div role="status" className={WARNING_CLASSES} data-testid="document-store-fallback">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
                  <div className="min-w-0">
                    <p className="font-medium">
                      Running on the database store: the configured {backendLabel(status.configuredBackend)} is not
                      usable.
                    </p>
                    {status.fallbackReason && <p className="mt-1 break-words">{status.fallbackReason}</p>}
                    <p className="mt-1">
                      Fix the <code className="font-mono">APIOME_DOCUMENT_STORE_*</code> settings and restart the REST
                      server. <code className="font-mono">APIOME_DOCUMENT_STORE_FALLBACK=db</code> allowed it to start.
                    </p>
                  </div>
                </div>
              )}
              <StatusCard status={status} />
              {(probe || probeError) && <ProbeCard probe={probe} error={probeError} />}
              <SettingsCard status={status} />
              <UsageCard status={status} />
            </>
          )}
        </div>
      </main>
    </>
  );
}

/** Backend and reachability. */
function StatusCard({ status }: { status: DocumentStoreStatus }) {
  const headingId = useId();
  const { health } = status;
  return (
    <section aria-labelledby={headingId} className={CARD_CLASSES} data-testid="document-store-status">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className={CARD_TITLE_CLASSES}>
          {backendLabel(status.backend)}
        </h3>
        <span className={NEUTRAL_CHIP_CLASSES}>{status.backend}</span>
        {health.ok ? (
          <span className={OK_CHIP_CLASSES}>
            <CheckCircle2 className="h-3 w-3" /> Reachable
          </span>
        ) : (
          <span className={FAIL_CHIP_CLASSES}>
            <XCircle className="h-3 w-3" /> Unreachable
          </span>
        )}
      </div>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">Last checked {formatWhen(health.checkedAt)}.</p>
      {health.error && (
        <p role="alert" className="mt-2 break-words text-sm text-rose-700 dark:text-rose-400">
          {health.error}
        </p>
      )}
    </section>
  );
}

/** The outcome of the last **Test connection**. */
function ProbeCard({ probe, error }: { probe: DocumentStoreProbeResult | null; error: string | null }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={CARD_CLASSES} data-testid="document-store-probe">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className={CARD_TITLE_CLASSES}>
          Connection test
        </h3>
        {probe &&
          (probe.ok ? (
            <span className={OK_CHIP_CLASSES}>
              <CheckCircle2 className="h-3 w-3" /> Passed
            </span>
          ) : (
            <span className={FAIL_CHIP_CLASSES}>
              <XCircle className="h-3 w-3" /> Failed
            </span>
          ))}
        {probe && (
          <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
            {formatWhen(probe.checkedAt)} · {Math.round(probe.durationMs)} ms
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-rose-700 dark:text-rose-400">
          {error}
        </p>
      )}
      {probe && (
        <ol className="mt-3 flex flex-col gap-2">
          {probe.steps.map((step) => (
            <li key={step.name} className="flex items-start gap-2 text-sm" data-testid={`probe-step-${step.name}`}>
              {step.skipped ? (
                <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden />
              ) : step.ok ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600 dark:text-rose-400" aria-hidden />
              )}
              <div className="min-w-0">
                <p className="text-slate-900 dark:text-slate-100">
                  {PROBE_STEP_LABELS[step.name]}{' '}
                  <span className="text-slate-500 dark:text-slate-400">
                    {step.skipped ? '— skipped' : step.ok ? `— ${Math.round(step.durationMs)} ms` : '— failed'}
                  </span>
                </p>
                {step.error && <p className="break-words text-rose-700 dark:text-rose-400">{step.error}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** The non-secret settings of the active backend. */
function SettingsCard({ status }: { status: DocumentStoreStatus }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={CARD_CLASSES} data-testid="document-store-settings">
      <h3 id={headingId} className={CARD_TITLE_CLASSES}>
        Settings
      </h3>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[12rem_1fr]">
        {settingRows(status).map((row) => (
          <div key={row.label} className="contents">
            <dt className={TERM_CLASSES}>{row.label}</dt>
            <dd className={`${VALUE_CLASSES} ${row.mono ? 'font-mono' : ''}`}>{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Index totals, per backend, and the latest integrity verification. */
function UsageCard({ status }: { status: DocumentStoreStatus }) {
  const headingId = useId();
  const { usage } = status;
  return (
    <section aria-labelledby={headingId} className={CARD_CLASSES} data-testid="document-store-usage">
      <h3 id={headingId} className={CARD_TITLE_CLASSES}>
        Usage
      </h3>
      {!usage ? (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          The document index could not be read. Check that the database migrations have been applied.
        </p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[12rem_1fr]">
            <dt className={TERM_CLASSES}>Objects</dt>
            <dd className={VALUE_CLASSES}>{usage.objects.toLocaleString()}</dd>
            <dt className={TERM_CLASSES}>Size</dt>
            <dd className={VALUE_CLASSES}>{formatBytes(usage.bytes)}</dd>
            <dt className={TERM_CLASSES}>Last integrity check</dt>
            <dd className={VALUE_CLASSES}>
              {usage.integrity.lastVerifiedAt
                ? `${formatWhen(usage.integrity.lastVerifiedAt)} · ${usage.integrity.verifiedObjects.toLocaleString()} verified`
                : 'No object has been verified yet'}
            </dd>
          </dl>
          {usage.byBackend.length > 1 && (
            <div className="mt-4 overflow-x-auto rounded-md border border-slate-200 dark:border-slate-700">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">Backend</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Objects</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Size</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700 dark:divide-slate-800 dark:text-slate-200">
                  {usage.byBackend.map((row) => (
                    <tr key={row.backend} data-testid="document-store-backend-row">
                      <td className="px-3 py-2">{backendLabel(row.backend)}</td>
                      <td className="px-3 py-2 text-right">{row.objects.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{formatBytes(row.bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
            Counts the document index: captured originals, rendered documents and frozen schemas.
          </p>
        </>
      )}
    </section>
  );
}
