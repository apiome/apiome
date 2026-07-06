'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  FileWarning,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldCheck,
  ShieldX,
  Sparkles,
} from 'lucide-react';
import { Button } from '../../../ui/Button';
import { Alert } from '../../../ui/Alert';
import { FidelityWarningPanel } from './FidelityWarningPanel';
import { gradeChipClass, type LintSeverity } from '../../../../utils/version-lint-report';
import type { TargetFidelitySummary } from './exportTargetCatalog';
import {
  lensBadgeCount,
  lintSeverityCounts,
  verifyVerdictBanner,
  verifyVerdictBannerClass,
  type EmittedArtifactLintReport,
  type EmittedValidationReport,
  type ExportVerifyResponse,
  type ExportVerifyVerdict,
  type VerifyLensKey,
} from './exportVerify';

export interface VerifyWorkbenchProps {
  /** Human label of the chosen target format (e.g. `gRPC / Protobuf`). */
  targetLabel: string;
  /** One-line description of the target, shown in the fidelity lens. */
  targetDescription: string;
  /** The coarse per-target fidelity summary — feeds the fidelity lens's immediate ring/chips. */
  fidelitySummary: TargetFidelitySummary;
  /** Whether a verification is currently in flight. */
  running: boolean;
  /** Whether a verification has run and settled for the current configuration. */
  hasRun: boolean;
  /** The error from a failed run, else null. */
  error: string | null;
  /** The verify result once a run settles, else null. */
  result: ExportVerifyResponse | null;
  /** The overall verdict derived/served for {@link result}, else null before a run. */
  verdict: ExportVerifyVerdict | null;
  /** Whether the user has acknowledged a lossy conversion ("Export anyway"). */
  acknowledged: boolean;
  /** Toggle the lossy acknowledgement. */
  onAcknowledgedChange: (acknowledged: boolean) => void;
  /** Trigger (or re-trigger) a verification run. */
  onRun: () => void;
}

/** The three lenses, in tab / accordion order. */
const LENSES: { key: VerifyLensKey; label: string }[] = [
  { key: 'fidelity', label: 'Fidelity' },
  { key: 'validation', label: 'Validation' },
  { key: 'lint', label: 'Lint' },
];

/**
 * VerifyWorkbench — the Studio's Verify step orchestration UI (MFX-42.1, #4354).
 *
 * A single **Run verification** action calls the one-call dry-run verify (MFX-42.5) and yields
 * all three lenses at once — fidelity, emitted-output validation, and emitted-artifact lint —
 * under one go/no-go **verdict banner** (`Clean` / `Lossy — acknowledge to continue` /
 * `Invalid — export blocked`, per the MFX-5.3 gate + MFX-3.3 severity). The lenses lay out as
 * tabs-with-badges (count per lens) on desktop and as an accordion on narrow widths; the deeper
 * per-lens rendering lands in MFX-42.2 (validation), 42.3 (lint) and 42.4 (fidelity), which hang
 * their content under the layout this component owns.
 *
 * The verdict gates Generate: `invalid` blocks unconditionally (with the validator's detail),
 * `lossy` requires the explicit acknowledgement, `clean` is the green path. The verdict and its
 * result live in Studio state so the Review step shows the same banner.
 */
export function VerifyWorkbench({
  targetLabel,
  targetDescription,
  fidelitySummary,
  running,
  hasRun,
  error,
  result,
  verdict,
  acknowledged,
  onAcknowledgedChange,
  onRun,
}: VerifyWorkbenchProps) {
  // Lead with the lens that most needs attention: the validator's detail for a blocked export,
  // else the fidelity lens (where the loss + acknowledgement live).
  const defaultLensFor = (v: ExportVerifyVerdict | null): VerifyLensKey =>
    v === 'invalid' ? 'validation' : 'fidelity';
  const [activeLens, setActiveLens] = useState<VerifyLensKey>(() => defaultLensFor(verdict));

  // Reset the tab when the verdict changes (a fresh run) using the "adjust state during render"
  // pattern — not an effect — so a manual tab pick still survives re-renders that don't change the
  // verdict.
  const [verdictAtLastReset, setVerdictAtLastReset] = useState(verdict);
  if (verdict !== verdictAtLastReset) {
    setVerdictAtLastReset(verdict);
    setActiveLens(defaultLensFor(verdict));
  }

  // Before the first run (and not mid-run): the explicit call to action.
  if (!hasRun && !running) {
    return (
      <div className="space-y-4" data-testid="verify-workbench">
        <VerifyIntro targetLabel={targetLabel} />
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900 dark:bg-indigo-950/40">
          <p className="max-w-xl text-sm text-indigo-900 dark:text-indigo-100">
            Run all three checks — fidelity, validation, and lint — in one pass, before you
            generate anything. Nothing is emitted or stored until you choose to generate.
          </p>
          <Button data-testid="verify-run" onClick={onRun}>
            <Sparkles className="h-4 w-4" aria-hidden />
            Run verification
          </Button>
        </div>
      </div>
    );
  }

  // While the single dry-run is in flight: a per-lens progress list (MFX-42.1 "progress states
  // per lens"). The one call fans out to all three; each row is pending until the call settles.
  if (running) {
    return (
      <div className="space-y-4" data-testid="verify-workbench">
        <VerifyIntro targetLabel={targetLabel} />
        <ul className="space-y-2" data-testid="verify-progress">
          {LENSES.map((lens) => (
            <li
              key={lens.key}
              data-testid={`verify-progress-${lens.key}`}
              className="flex items-center gap-2 rounded-lg border border-gray-200 p-3 text-sm text-gray-600 dark:border-gray-700 dark:text-gray-300"
            >
              <Loader2 className="h-4 w-4 animate-spin text-indigo-500" aria-hidden />
              Checking {lens.label.toLowerCase()}…
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // A failed run: no lens has a coarse fallback, so the gate stays closed. Offer a retry.
  if (error || !result || !verdict) {
    return (
      <div className="space-y-4" data-testid="verify-workbench">
        <Alert variant="error" data-testid="verify-error">
          {error || 'Verification did not return a result. Try again.'}
        </Alert>
        <Button variant="outline" data-testid="verify-rerun" onClick={onRun}>
          <RefreshCw className="h-4 w-4" aria-hidden />
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="verify-workbench">
      <VerdictBanner verdict={verdict} />

      {/* Desktop: tabs-with-badges + the active lens panel. */}
      <div className="hidden sm:block" data-testid="verify-lens-tabs">
        <div
          role="tablist"
          aria-label="Verification lenses"
          className="flex flex-wrap gap-2 border-b border-gray-200 dark:border-gray-700"
        >
          {LENSES.map((lens) => {
            const selected = lens.key === activeLens;
            return (
              <button
                key={lens.key}
                role="tab"
                type="button"
                aria-selected={selected}
                data-testid={`verify-tab-${lens.key}`}
                onClick={() => setActiveLens(lens.key)}
                className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium ${
                  selected
                    ? 'border-indigo-500 text-indigo-700 dark:text-indigo-300'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
                }`}
              >
                {lens.label}
                <LensBadge lens={lens.key} result={result} />
              </button>
            );
          })}
        </div>
        <div role="tabpanel" data-testid={`verify-panel-${activeLens}`} className="pt-4">
          <LensBody
            lens={activeLens}
            result={result}
            targetLabel={targetLabel}
            targetDescription={targetDescription}
            fidelitySummary={fidelitySummary}
            acknowledged={acknowledged}
            onAcknowledgedChange={onAcknowledgedChange}
          />
        </div>
      </div>

      {/* Narrow: the same three lenses as an accordion (all bodies present, no hidden detail). */}
      <div className="space-y-2 sm:hidden" data-testid="verify-lens-accordion">
        {LENSES.map((lens) => (
          <details
            key={lens.key}
            data-testid={`verify-accordion-${lens.key}`}
            open={lens.key === activeLens}
            className="rounded-lg border border-gray-200 dark:border-gray-700"
          >
            <summary className="flex cursor-pointer items-center justify-between gap-2 px-3 py-2 text-sm font-medium text-gray-900 dark:text-gray-100">
              <span className="flex items-center gap-2">
                {lens.label}
                <LensBadge lens={lens.key} result={result} />
              </span>
            </summary>
            <div className="border-t border-gray-200 p-3 dark:border-gray-700">
              <LensBody
                lens={lens.key}
                result={result}
                targetLabel={targetLabel}
                targetDescription={targetDescription}
                fidelitySummary={fidelitySummary}
                acknowledged={acknowledged}
                onAcknowledgedChange={onAcknowledgedChange}
              />
            </div>
          </details>
        ))}
      </div>

      <div className="flex justify-end">
        <Button variant="outline" data-testid="verify-rerun" onClick={onRun}>
          <RefreshCw className="h-4 w-4" aria-hidden />
          Re-run verification
        </Button>
      </div>
    </div>
  );
}

/** The Verify step's framing line — shown before, during, and (implicitly) after a run. */
function VerifyIntro({ targetLabel }: { targetLabel: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
      <ShieldCheck className="h-4 w-4 text-indigo-500" aria-hidden />
      Verify the {targetLabel} conversion
    </div>
  );
}

/** The single go/no-go verdict banner shown above the lenses (and reused on Review). */
export function VerdictBanner({ verdict }: { verdict: ExportVerifyVerdict }) {
  const banner = verifyVerdictBanner(verdict);
  const Icon = banner.tone === 'invalid' ? ShieldX : banner.tone === 'lossy' ? AlertTriangle : CheckCircle2;
  return (
    <div
      data-testid="verify-verdict"
      data-verdict={verdict}
      className={`flex items-start gap-3 rounded-lg border p-4 ${verifyVerdictBannerClass(banner.tone)}`}
    >
      <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <div className="space-y-1">
        <div className="text-sm font-semibold">{banner.label}</div>
        <p className="text-xs opacity-90">{banner.description}</p>
      </div>
    </div>
  );
}

/** A lens tab/accordion count badge; toned by how much the lens is flagging. */
function LensBadge({ lens, result }: { lens: VerifyLensKey; result: ExportVerifyResponse | null }) {
  const count = lensBadgeCount(lens, result);
  const tone = lensBadgeTone(lens, result, count);
  return (
    <span
      data-testid={`verify-badge-${lens}`}
      className={`inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-[0.65rem] font-semibold tabular-nums ${tone}`}
    >
      {count}
    </span>
  );
}

/** Badge colour: red when the lens blocks/errors, amber when it warns, neutral/green when clean. */
function lensBadgeTone(
  lens: VerifyLensKey,
  result: ExportVerifyResponse | null,
  count: number,
): string {
  const neutral = 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300';
  const amber = 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
  const rose = 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
  if (count === 0) return neutral;
  if (lens === 'validation') return result?.validation.blocks_delivery ? rose : amber;
  if (lens === 'lint') {
    return (result?.lint?.findings ?? []).some((f) => f.severity === 'error') ? rose : amber;
  }
  return amber;
}

interface LensBodyProps {
  lens: VerifyLensKey;
  result: ExportVerifyResponse;
  targetLabel: string;
  targetDescription: string;
  fidelitySummary: TargetFidelitySummary;
  acknowledged: boolean;
  onAcknowledgedChange: (acknowledged: boolean) => void;
}

/** Dispatch a lens key to its body; shared by the desktop tab panel and the narrow accordion. */
function LensBody({
  lens,
  result,
  targetLabel,
  targetDescription,
  fidelitySummary,
  acknowledged,
  onAcknowledgedChange,
}: LensBodyProps) {
  if (lens === 'fidelity') {
    return (
      <FidelityWarningPanel
        targetLabel={targetLabel}
        targetDescription={targetDescription}
        fidelity={fidelitySummary}
        preview={result}
        previewLoading={false}
        previewError={null}
        acknowledged={acknowledged}
        onAcknowledgedChange={onAcknowledgedChange}
      />
    );
  }
  if (lens === 'validation') return <ValidationLens validation={result.validation} />;
  return <LintLens lint={result.lint} />;
}

/**
 * The emitted-output validation lens (MFX-42.1 scaffold; deepened in MFX-42.2). Shows the gate's
 * verdict headline and — when the artifact was rejected — the structured errors with locations.
 */
function ValidationLens({ validation }: { validation: EmittedValidationReport }) {
  const tone =
    validation.verdict === 'invalid'
      ? 'invalid'
      : validation.verdict === 'skipped'
        ? 'warn'
        : validation.verdict === 'not_applicable'
          ? 'neutral'
          : 'ok';
  return (
    <div className="space-y-3" data-testid="verify-validation">
      <VerdictHeadline
        tone={tone}
        headline={validation.headline}
        message={validation.message}
        detail={validation.detail}
      />
      {validation.findings.length > 0 && (
        <ul className="space-y-2" data-testid="verify-validation-findings">
          {validation.findings.map((finding, idx) => (
            <li
              key={`${finding.rule ?? 'err'}-${idx}`}
              className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm dark:border-rose-900 dark:bg-rose-950/30"
            >
              <div className="text-gray-900 dark:text-gray-100">{finding.message}</div>
              <FindingLocation
                file={finding.file}
                path={finding.path}
                line={finding.line}
                column={finding.column}
                rule={finding.rule}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The emitted-artifact lint lens (MFX-42.1 scaffold; deepened in MFX-42.3). Shows the score/grade
 * when the pack computes one, a severity breakdown, and the findings — or an explicit empty state
 * when no lint pack applies to the target.
 */
function LintLens({ lint }: { lint: EmittedArtifactLintReport | null }) {
  const counts = useMemo(() => lintSeverityCounts(lint?.findings ?? []), [lint]);
  if (!lint || !lint.applicable) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="verify-lint-empty">
        No lint pack is registered for this target — there is nothing to lint. The export is not
        blocked by lint.
      </p>
    );
  }
  return (
    <div className="space-y-3" data-testid="verify-lint">
      <div className="flex flex-wrap items-center gap-2">
        {typeof lint.score === 'number' && (
          <span
            data-testid="verify-lint-grade"
            className={`inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold ${gradeChipClass(lint.grade ?? '')}`}
          >
            {(lint.grade ?? '–').trim() || '–'} · {lint.score}/100
          </span>
        )}
        <SeverityChip severity="error" count={counts.error} />
        <SeverityChip severity="warning" count={counts.warning} />
        <SeverityChip severity="info" count={counts.info} />
      </div>
      {lint.findings.length === 0 ? (
        <p className="text-sm text-emerald-700 dark:text-emerald-300" data-testid="verify-lint-clean">
          <CheckCircle2 className="mr-1.5 inline h-4 w-4 align-text-bottom" aria-hidden />
          The lint pack reported no findings.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="verify-lint-findings">
          {lint.findings.map((finding, idx) => (
            <li
              key={`${finding.rule}-${idx}`}
              className="rounded-md border border-gray-200 p-3 text-sm dark:border-gray-700"
            >
              <div className="flex items-center gap-2">
                <SeverityChip severity={finding.severity} />
                <code className="text-xs text-gray-600 dark:text-gray-300">{finding.rule}</code>
              </div>
              <div className="mt-1 text-gray-900 dark:text-gray-100">{finding.message}</div>
              <FindingLocation file={finding.file} path={finding.path} line={finding.line} column={finding.column} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The one-line "file · pointer · line:col · rule" location under a finding, when known. */
function FindingLocation({
  file,
  path,
  line,
  column,
  rule,
}: {
  file?: string | null;
  path?: string | null;
  line?: number | null;
  column?: number | null;
  rule?: string | null;
}) {
  const parts: string[] = [];
  if (file) parts.push(file);
  if (path) parts.push(path);
  if (typeof line === 'number') parts.push(typeof column === 'number' ? `${line}:${column}` : `line ${line}`);
  if (rule) parts.push(rule);
  if (parts.length === 0) return null;
  return (
    <div className="mt-1 font-mono text-xs text-gray-500 dark:text-gray-400" data-testid="verify-finding-location">
      {parts.join(' · ')}
    </div>
  );
}

/** A lens verdict headline row with an icon, message, and optional detail. */
function VerdictHeadline({
  tone,
  headline,
  message,
  detail,
}: {
  tone: 'ok' | 'warn' | 'invalid' | 'neutral';
  headline: string;
  message: string;
  detail?: string | null;
}) {
  const Icon = tone === 'invalid' ? ShieldX : tone === 'warn' ? FileWarning : tone === 'ok' ? ShieldCheck : Gauge;
  const toneClass =
    tone === 'invalid'
      ? 'text-rose-700 dark:text-rose-300'
      : tone === 'warn'
        ? 'text-amber-700 dark:text-amber-300'
        : tone === 'ok'
          ? 'text-emerald-700 dark:text-emerald-300'
          : 'text-gray-600 dark:text-gray-300';
  return (
    <div className="flex items-start gap-2">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${toneClass}`} aria-hidden />
      <div className="space-y-0.5">
        <div className={`text-sm font-semibold ${toneClass}`} data-testid="verify-validation-headline">
          {headline}
        </div>
        <p className="text-xs text-gray-600 dark:text-gray-300">{message}</p>
        {detail && <p className="text-xs text-gray-500 dark:text-gray-400">{detail}</p>}
      </div>
    </div>
  );
}

/** A severity chip (`3 errors`) or, without a count, a bare severity tag on a finding. */
function SeverityChip({ severity, count }: { severity: LintSeverity; count?: number }) {
  if (typeof count === 'number' && count === 0) return null;
  const cls =
    severity === 'error'
      ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300'
      : severity === 'warning'
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
        : 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300';
  const label =
    typeof count === 'number' ? `${count} ${severity}${count === 1 ? '' : 's'}` : severity;
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium capitalize ${cls}`}>
      {label}
    </span>
  );
}

export default VerifyWorkbench;
