'use client';

import { useCallback, useState } from 'react';
import {
  coverageSummary,
  hasPackages,
  publicSdkDownloadUrl,
  publicSdkErrorFromResponse,
  sdkFallbackFilename,
  type PublicSdkCoordinates,
  type PublicSdkInfoResponse,
} from '../../../../lib/sdk/publicSdk';
import { filenameFromContentDisposition } from '../../../../lib/export/publicExport';

interface GetSdkPanelProps {
  /** The info payload, already fetched. The panel does not exist without one (see below). */
  info: PublicSdkInfoResponse;
  /** The tenant/project/version slugs of the viewed published version. */
  coords: PublicSdkCoordinates;
  /** The browser-reachable REST base URL, ending in `/v1`. */
  restApiBaseUrl: string;
}

/**
 * The "Get SDK" panel on a published version page — SDK-3.3 (#4493).
 *
 * Shows the package names the publisher's SDK settings resolve to, what to install, and a button
 * that downloads the client kit: a zip of runnable per-operation snippets in TypeScript, Python
 * and cURL plus the contract itself.
 *
 * **It has no disabled state.** A project that has not opted into public SDK access answers the
 * info route with the same 404 an unpublished version does, so the parent renders nothing at all
 * rather than an empty panel advertising something the visitor cannot have.
 */
export function GetSdkPanel({ info, coords, restApiBaseUrl }: GetSdkPanelProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDownload = useCallback(async () => {
    setDownloading(true);
    setError(null);
    try {
      const response = await fetch(publicSdkDownloadUrl(restApiBaseUrl, coords));
      if (!response.ok) {
        throw new Error(await publicSdkErrorFromResponse(response));
      }
      const blob = await response.blob();
      const filename = filenameFromContentDisposition(
        response.headers.get('Content-Disposition'),
        info.download.filename || sdkFallbackFilename(coords)
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed.');
    } finally {
      setDownloading(false);
    }
  }, [restApiBaseUrl, coords, info.download.filename]);

  return (
    <section className="surface-card overflow-hidden" data-testid="get-sdk-panel">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 px-4 py-3 dark:border-zinc-800/80">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Get SDK</h2>
          <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
            {coverageSummary(info)}
          </p>
        </div>
        <button
          type="button"
          onClick={runDownload}
          disabled={downloading}
          className="btn-brand inline-flex shrink-0 items-center gap-1.5 px-3 py-1.5 text-xs disabled:opacity-60"
        >
          {downloading ? (
            <Spinner />
          ) : (
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
              />
            </svg>
          )}
          {downloading ? 'Preparing…' : 'Download SDK'}
        </button>
      </header>

      <div className="space-y-4 p-4">
        {hasPackages(info) && (
          <div className="space-y-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              Packages
            </h3>
            <ul className="space-y-2">
              {info.packages.map((pkg) => (
                <li key={pkg.ecosystem} className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex shrink-0 items-center rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                    {pkg.ecosystem}
                  </span>
                  <code className="min-w-0 break-all font-mono text-[12.5px] text-zinc-800 dark:text-zinc-200">
                    {pkg.name}
                  </code>
                  {pkg.install && <CopyableCommand command={pkg.install} />}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            What you get
          </h3>
          <ul className="space-y-1 text-[13px] text-zinc-600 dark:text-zinc-400">
            <li>
              Runnable examples in{' '}
              {info.languages.map((language, index) => (
                <span key={language.lang}>
                  {index > 0 && (index === info.languages.length - 1 ? ' and ' : ', ')}
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">
                    {language.label}
                  </span>
                </span>
              ))}
              .
            </li>
            <li>The published specification, exactly as its author wrote it.</li>
            <li>
              A manifest recording which revision this came from
              {info.version_label ? ` (v${info.version_label})` : ''}.
            </li>
          </ul>
        </div>

        {info.truncated && (
          <p className="text-[12px] text-amber-700 dark:text-amber-300">
            This API declares {info.total_operation_count} operations; the download carries the
            first {info.operation_count}.
          </p>
        )}

        {error && (
          <p role="alert" className="text-[12.5px] text-rose-700 dark:text-rose-300">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}

/** A monospace command with a copy button beside it. */
function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // A browser that refuses clipboard access leaves the command on screen to select by hand;
      // there is nothing useful to tell the reader here.
    }
  }, [command]);

  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <code className="min-w-0 break-all rounded bg-zinc-50 px-2 py-1 font-mono text-[11.5px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
        {command}
      </code>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copy "${command}"`}
        className="shrink-0 rounded p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
      >
        {copied ? (
          <svg
            className="h-3.5 w-3.5 text-[var(--success)]"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
        ) : (
          <svg
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.75}
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75"
            />
          </svg>
        )}
      </button>
    </span>
  );
}

/** The app's standard inline spinner. */
function Spinner() {
  return (
    <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
