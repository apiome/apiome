'use client';

import { useState } from 'react';
import { Check, CircleSlash, Copy, Loader2, Play, RotateCcw, TerminalSquare } from 'lucide-react';

import { Badge } from '../../../ui/Badge';
import { Button } from '../../../ui/Button';
import { toolAvailable, type ExportTestTool } from './exportTestDrive';
import {
  consoleTranscript,
  formatToolCheckDuration,
  toolCheckId,
  toolCheckParams,
  toolCheckStatusLabel,
  toolCheckStatusTone,
  type ToolCheckResult,
  type ToolCheckRun,
} from './exportToolChecks';

export interface ToolchainChecksConsoleProps {
  /** The tab's toolchain checks, straight from the registry (`descriptor.test_tools`). */
  tools: readonly ExportTestTool[];
  /** Each check's console for the artifact under review, by `toolCheckId`. */
  runs: Record<string, ToolCheckRun>;
  /** Run (or re-run) one check. */
  onRun: (tool: ExportTestTool) => void;
}

/**
 * ToolchainChecksConsole — the **Toolchain checks** test-drive tab (MFX-44.6, #4372).
 *
 * One row per check the target's registry entry declares (`buf lint`, `tsp compile`…). **Run** sends
 * the check to the server, which runs the format's own toolchain on the artifact under review; its
 * stdout and stderr stream into a console under the row (monospace, ANSI codes removed, **Copy**),
 * and a status chip reports how it ended — *Passed*, *Failed · exit N*, *Timed out*, *Not installed*.
 * A check whose tool is not installed on this server shows the server's reason and no Run button.
 *
 * @param props See {@link ToolchainChecksConsoleProps}.
 * @returns The list of checks.
 */
export function ToolchainChecksConsole({ tools, runs, onRun }: ToolchainChecksConsoleProps) {
  return (
    <ul className="xstd-testdrive__checks" data-testid="toolchain-checks">
      {tools.map((tool) => {
        const id = toolCheckId(tool);
        return <ToolchainCheckRow key={id} id={id} tool={tool} run={runs[id] ?? null} onRun={onRun} />;
      })}
    </ul>
  );
}

/** One declared check: its label, availability or status chip, Run, and its console once run. */
function ToolchainCheckRow({
  id,
  tool,
  run,
  onRun,
}: {
  id: string;
  tool: ExportTestTool;
  run: ToolCheckRun | null;
  onRun: (tool: ExportTestTool) => void;
}) {
  const installed = toolAvailable(tool);
  const runnable = installed && toolCheckParams(tool) !== null;
  const running = run?.state === 'running';
  const testId = id.replace(/\s+/g, '-');
  return (
    <li className="xstd-testdrive__check-item" data-testid={`toolchain-check-${testId}`}>
      <div className="xstd-testdrive__check" data-tone={installed ? 'ok' : 'muted'}>
        {installed ? <TerminalSquare aria-hidden /> : <CircleSlash aria-hidden />}
        <code className="mono">{tool.label}</code>
        {!installed ? (
          <span className="xstd-testdrive__check-status">
            {tool.unavailable_reason ?? 'Not installed on this server.'}
          </span>
        ) : running ? (
          <span className="xstd-testdrive__check-status" role="status">
            <Loader2 className="xstd-testdrive__spinner motion-safe:animate-spin" aria-hidden /> Running…
          </span>
        ) : run?.result ? (
          <Badge variant={toolCheckStatusTone(run.result.status)} data-testid={`toolchain-status-${testId}`}>
            {toolCheckStatusLabel(run.result)}
          </Badge>
        ) : run?.error ? (
          <Badge variant="warn" data-testid={`toolchain-status-${testId}`}>
            Could not run
          </Badge>
        ) : (
          <span className="xstd-testdrive__check-status">Installed on this server</span>
        )}
        {runnable && (
          <Button title={running ? 'Wait for the check that is running' : undefined}
            size="sm"
            variant="outline"
            className="xstd-testdrive__check-run"
            disabled={running}
            onClick={() => onRun(tool)}
            data-testid={`toolchain-run-${testId}`}
            aria-label={`${run ? 'Run again' : 'Run'}: ${tool.label}`}
          >
            {run ? <RotateCcw aria-hidden /> : <Play aria-hidden />}
            {run ? 'Run again' : 'Run'}
          </Button>
        )}
      </div>
      {run && <ToolchainConsole label={tool.label} run={run} testId={testId} />}
    </li>
  );
}

/** A check's streamed console: the command, its output (stderr toned), and the outcome in words. */
function ToolchainConsole({ label, run, testId }: { label: string; run: ToolCheckRun; testId: string }) {
  const empty = run.output.length === 0;
  return (
    <div className="xstd-console" data-testid={`toolchain-console-${testId}`}>
      <div className="xstd-console__bar">
        <code className="mono xstd-console__command">$ {run.command ?? label}</code>
        {run.result && (
          <span className="xstd-console__meta">{formatToolCheckDuration(run.result.duration_ms)}</span>
        )}
        <CopyTranscript run={run} testId={testId} />
      </div>
      <pre className="xstd-console__output" role="log" aria-live="polite" aria-label={`${label} output`} tabIndex={0}>
        {run.truncated && <span className="xstd-console__note">{'(earlier output trimmed)\n'}</span>}
        {run.output.map((chunk, index) => (
          <span key={index} data-stream={chunk.stream}>
            {chunk.text}
          </span>
        ))}
        {empty && run.state === 'done' && !run.error && <span className="xstd-console__note">(no output)</span>}
        {empty && run.state === 'running' && <span className="xstd-console__note">Waiting for output…</span>}
      </pre>
      {(run.error || run.result?.message) && (
        <p className="xstd-console__message" data-testid={`toolchain-message-${testId}`}>
          {run.error ?? run.result?.message}
        </p>
      )}
    </div>
  );
}

/** Copy the console as text, confirming only once the clipboard actually took it. */
function CopyTranscript({ run, testId }: { run: ToolCheckRun; testId: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="ghost"
      data-testid={`toolchain-copy-${testId}`}
      aria-label="Copy the console output"
      onClick={() => {
        // `navigator.clipboard` is absent in an insecure context; the output stays selectable.
        const written = navigator.clipboard?.writeText(consoleTranscript(run));
        if (!written) return;
        void written.then(
          () => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
          },
          () => undefined,
        );
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? 'Copied' : 'Copy'}
    </Button>
  );
}

/**
 * The toolchain checks run on this configuration, attached to its verify report (MFX-44.6).
 *
 * Rendered under the verify verdict on the Review step once at least one check has settled, so what
 * the format's own toolchain said sits beside what Verify said.
 *
 * @param props The settled results.
 * @returns The summary, or nothing before any check has run.
 */
export function ToolCheckReport({ results }: { results: readonly ToolCheckResult[] }) {
  if (results.length === 0) return null;
  return (
    <section className="xstd-panel xstd-toolcheck-report" aria-labelledby="xstd-toolcheck-report-title" data-testid="toolcheck-report">
      <h3 id="xstd-toolcheck-report-title" className="xstd-caps">
        <TerminalSquare aria-hidden />
        Toolchain checks
      </h3>
      <ul className="xstd-toolcheck-report__list">
        {results.map((result) => (
          <li key={`${result.tool} ${result.check}`} className="xstd-toolcheck-report__item">
            <code className="mono">{result.label}</code>
            <Badge variant={toolCheckStatusTone(result.status)}>{toolCheckStatusLabel(result)}</Badge>
            {result.files.length > 0 && (
              <span className="xstd-toolcheck-report__files">
                {result.files.length === 1 ? result.files[0] : `${result.files.length} files`}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
