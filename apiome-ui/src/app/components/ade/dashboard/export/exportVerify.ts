/**
 * One-call Verify result envelope + verdict/lens presentation helpers (MFX-42.1, #4354).
 *
 * The Studio's Verify step runs a single dry-run that returns all three verification lenses at
 * once — fidelity (MFX-2.5/6.2), emitted-output validation (MFX-5.1/5.3), and emitted-artifact
 * lint (MFX-5.2) — through the one-call verify endpoint (MFX-42.5, `POST /api/export/verify`),
 * **without** producing or persisting an artifact. This module mirrors that response field-for-
 * field so it deserialises directly, and adds the pure presentation logic the workbench needs:
 * the go/no-go verdict band (`clean` / `lossy` / `invalid`, per MFX-5.3 gating + MFX-3.3
 * severity), the banner copy/tone per verdict, the per-lens badge counts, and the Generate gate.
 *
 * Everything here is pure (no React, no fetch) so it can be unit-tested directly — mirroring
 * `./exportFidelityPreview.ts` and `./exportTargetCatalog.ts`. The lens *rendering* deepens in
 * MFX-42.2 (validation), 42.3 (lint) and 42.4 (fidelity); this module owns the orchestration
 * verdict those lenses hang under.
 */

import { requiresExportAcknowledgement, type ExportFidelityEnvelope } from './exportFidelityPreview';
import type { LintSeverity } from '../../../../utils/version-lint-report';

/**
 * The emitted-output validation band (mirrors Python `ValidationVerdict`, MFX-5.3):
 * `valid` re-parsed cleanly · `invalid` a validator ran and rejected (blocks delivery) ·
 * `skipped` a required toolchain was unavailable (warns, does not block) · `not_applicable`
 * no importer matches the format (nothing to validate).
 */
export type EmittedValidationVerdict = 'valid' | 'invalid' | 'skipped' | 'not_applicable';

/** One structured emitted-artifact validation failure (mirrors Python `ValidationFinding`). */
export interface EmittedValidationFinding {
  /** Human-readable failure description. */
  message: string;
  /** JSON-pointer path into the emitted document, when the validator provides one. */
  path?: string | null;
  /** File within a multi-file bundle the failure is in, when applicable. */
  file?: string | null;
  /** 1-based line number when the validator reports a location. */
  line?: number | null;
  /** 1-based column number when the validator reports a location. */
  column?: number | null;
  /** Validator-specific rule keyword (e.g. a JSON Schema `keyword`), when available. */
  keyword?: string | null;
}

/**
 * The emitted-output validation gate + report (mirrors Python `EmittedValidationReport`,
 * MFX-5.3). The single gate the export surfaces read is {@link blocks_delivery} (true only for
 * an `invalid` verdict); {@link warns} is true only for a `skipped` (toolchain-unavailable) one.
 */
export interface EmittedValidationReport {
  /** The validation band: valid / invalid / skipped / not_applicable. */
  verdict: EmittedValidationVerdict;
  /** The resolved target format key that was validated (e.g. `openapi-3.1`). */
  target: string;
  /** True only for an `invalid` verdict — a validator ran and rejected the artifact. */
  blocks_delivery: boolean;
  /** True only for a `skipped` verdict — validation could not run (toolchain unavailable). */
  warns: boolean;
  /** Whether the emitted artifact re-parsed cleanly when validation ran. */
  valid: boolean;
  /** The validator identity that ran (or would have run) for this target, when known. */
  tool?: string | null;
  /** Structured parser/toolchain failures for UI rendering; non-empty only when `invalid`. */
  findings: EmittedValidationFinding[];
  /** Why validation did not run (skipped / not_applicable); null when validation ran. */
  detail?: string | null;
  /** Short banner heading for the validation gate (e.g. `Invalid — export blocked`). */
  headline: string;
  /** The user-facing gate message. */
  message: string;
}

/** One emitted-artifact lint finding (mirrors the import-side `LintFindingOut` shape, MFX-5.2). */
export interface EmittedLintFinding {
  /** How much the finding matters: error / warning / info. */
  severity: LintSeverity;
  /** The lint rule id that fired (e.g. `oas3-schema` or a target pack rule). */
  rule: string;
  /** Human-readable description of the finding. */
  message: string;
  /** The rule's category grouping, when the pack provides one. */
  category?: string | null;
  /** File within a multi-file bundle the finding is in, when applicable. */
  file?: string | null;
  /** JSON-pointer path into the emitted document, when the linter provides one. */
  path?: string | null;
  /** 1-based line number when the linter reports a location. */
  line?: number | null;
  /** 1-based column number when the linter reports a location. */
  column?: number | null;
}

/**
 * The emitted-artifact lint report for one export (MFX-5.2), advisory (it never blocks the
 * gate). When {@link applicable} is false the target has no lint pack — the lens shows an
 * explicit empty state rather than a misleading clean score.
 */
export interface EmittedArtifactLintReport {
  /** Whether a lint pack is registered for this target's format. */
  applicable: boolean;
  /** The lint pack that ran (e.g. `spectral:oas`), when applicable. */
  pack?: string | null;
  /** The 0–100 quality score, when the pack computes one. */
  score?: number | null;
  /** The A–F letter grade, when the pack computes one. */
  grade?: string | null;
  /** The itemized findings, in the server's order. */
  findings: EmittedLintFinding[];
}

/**
 * The overall Verify verdict band shown in the workbench banner (MFX-42.1):
 * `clean` green go · `lossy` acknowledge-to-continue · `invalid` export blocked.
 */
export type ExportVerifyVerdict = 'clean' | 'lossy' | 'invalid';

/**
 * The `POST /api/export/verify` response (mirrors REST `ExportVerifyResponse`, MFX-42.5).
 *
 * Carries all three lenses computed in one dry-run plus an optional server-side {@link verdict}.
 * The shape is a superset of `ExportPreviewResponse` (same source coordinates + `fidelity`
 * envelope), so the fidelity lens reuses the existing warning panel unchanged.
 */
export interface ExportVerifyResponse {
  /** The artifact (project / catalog-item) id the verification was computed for. */
  artifact: string;
  /** The version selector as requested (label, UUID, or null for latest). */
  version?: string | null;
  /** The resolved revision record id. */
  version_record_id: string;
  /** The resolved revision's version label, e.g. `"1.2.0"`. */
  version_label?: string | null;
  /** The full fidelity envelope (target + summary + per-construct report + advisory). */
  fidelity: ExportFidelityEnvelope;
  /** The emitted-output validation gate + report (MFX-5.3). */
  validation: EmittedValidationReport;
  /** The emitted-artifact lint report (MFX-5.2); null when the endpoint ran no lint pass. */
  lint: EmittedArtifactLintReport | null;
  /**
   * The server-computed overall verdict, when the endpoint supplies one. The workbench prefers
   * this; when absent it derives the same band from the lenses via {@link deriveVerifyVerdict}.
   */
  verdict?: ExportVerifyVerdict | null;
}

/**
 * The overall go/no-go verdict for a verify result (MFX-42.1), per the MFX-5.3 gate + MFX-3.3
 * severity classes:
 *
 * - **invalid** — a validator ran and rejected the artifact ({@link EmittedValidationReport.blocks_delivery});
 *   the export is blocked and no acknowledgement can override it.
 * - **lossy** — the conversion is not lossless (its fidelity tier requires acknowledgement,
 *   MFX-6.2); the user may continue only after the explicit "Export anyway" acknowledgement.
 * - **clean** — a lossless conversion that validated (or was not-applicable/skipped); the green
 *   path. A `skipped` validation (toolchain unavailable) warns but does not demote a clean band.
 *
 * The server's own {@link ExportVerifyResponse.verdict} wins when present; this derivation is the
 * client fallback and keeps the two in agreement.
 *
 * @param result The verify result to classify.
 * @returns The overall verdict band.
 */
export function deriveVerifyVerdict(result: ExportVerifyResponse): ExportVerifyVerdict {
  if (result.verdict) return result.verdict;
  if (result.validation.blocks_delivery) return 'invalid';
  if (requiresExportAcknowledgement(result.fidelity.summary.tier)) return 'lossy';
  return 'clean';
}

/** The verdict banner's presentation: its short label, longer description, and colour tone. */
export interface VerifyVerdictBanner {
  /** The banner heading (e.g. `Invalid — export blocked`). */
  label: string;
  /** The one-line explanation under the heading. */
  description: string;
  /** The colour tone driving the banner classes and icon. */
  tone: 'clean' | 'lossy' | 'invalid';
}

/**
 * The banner copy + tone for a verdict (MFX-42.1). The labels are the roadmap's exact strings so
 * the Verify and Review steps read identically:
 * `Clean` / `Lossy — acknowledge to continue` / `Invalid — export blocked`.
 *
 * @param verdict The overall verdict band.
 * @returns The banner label, description, and tone.
 */
export function verifyVerdictBanner(verdict: ExportVerifyVerdict): VerifyVerdictBanner {
  switch (verdict) {
    case 'invalid':
      return {
        label: 'Invalid — export blocked',
        description:
          'A validator re-parsed the emitted artifact and rejected it. Fix the source or choose a different target — this export cannot be generated.',
        tone: 'invalid',
      };
    case 'lossy':
      return {
        label: 'Lossy — acknowledge to continue',
        description:
          'The artifact is valid but the conversion drops or approximates some constructs. Review the fidelity lens, then acknowledge the loss to continue.',
        tone: 'lossy',
      };
    case 'clean':
    default:
      return {
        label: 'Clean',
        description:
          'The conversion is lossless and the emitted artifact validated cleanly. You can generate this export.',
        tone: 'clean',
      };
  }
}

/** CSS utility classes for the verdict banner container, keyed by tone. */
export function verifyVerdictBannerClass(tone: VerifyVerdictBanner['tone']): string {
  switch (tone) {
    case 'invalid':
      return 'border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-100';
    case 'lossy':
      return 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100';
    case 'clean':
    default:
      return 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100';
  }
}

/** The three Verify lenses, in their tab / accordion order. */
export type VerifyLensKey = 'fidelity' | 'validation' | 'lint';

/**
 * The count shown on a lens's tab badge (MFX-42.1): the number of items that lens surfaces —
 * fidelity: constructs that are not carried faithfully (drop + approx + synth); validation:
 * structured errors; lint: findings. Zero renders a neutral/clean badge.
 *
 * @param lens The lens whose badge count is wanted.
 * @param result The verify result, or null before a run.
 * @returns The badge count (0 when there is nothing to flag or no result yet).
 */
export function lensBadgeCount(lens: VerifyLensKey, result: ExportVerifyResponse | null): number {
  if (!result) return 0;
  switch (lens) {
    case 'fidelity': {
      const counts = result.fidelity.report.kind_counts;
      return (counts.drop ?? 0) + (counts.approx ?? 0) + (counts.synth ?? 0);
    }
    case 'validation':
      return result.validation.findings.length;
    case 'lint':
      return result.lint?.findings.length ?? 0;
    default:
      return 0;
  }
}

/**
 * The visual state the validation lens renders in (MFX-42.2). It tracks the report's verdict
 * one-for-one but renames `skipped` to `unavailable` to name the case the lens must surface as a
 * *warning* — an external toolchain (e.g. `buf build`) was not installed on the server, so the
 * artifact was **not** validated — never as silent success:
 *
 * - **valid** — a validator ran and the emitted artifact re-parsed cleanly (the positive verdict).
 * - **invalid** — a validator ran and rejected the artifact (blocks delivery); findings render.
 * - **unavailable** — the required toolchain was missing; validation could not run (warns).
 * - **not_applicable** — no validator matches the target format; there is nothing to validate.
 *
 * @param validation The emitted-output validation report.
 * @returns The lens presentation state.
 */
export function validationLensState(validation: EmittedValidationReport): ValidationLensState {
  switch (validation.verdict) {
    case 'invalid':
      return 'invalid';
    case 'skipped':
      return 'unavailable';
    case 'not_applicable':
      return 'not_applicable';
    case 'valid':
    default:
      return 'valid';
  }
}

/** The four states the validation lens can present (MFX-42.2). */
export type ValidationLensState = 'valid' | 'invalid' | 'unavailable' | 'not_applicable';

/** The colour tone driving the validation lens's headline icon and classes. */
export type ValidationLensTone = 'ok' | 'invalid' | 'warn' | 'neutral';

/**
 * The colour tone for a validation lens state (MFX-42.2): a clean pass is `ok` (green), a
 * rejection is `invalid` (red), a missing toolchain is `warn` (amber — distinct from success),
 * and a not-applicable format is `neutral`.
 *
 * @param state The validation lens state.
 * @returns The tone token.
 */
export function validationLensTone(state: ValidationLensState): ValidationLensTone {
  switch (state) {
    case 'invalid':
      return 'invalid';
    case 'unavailable':
      return 'warn';
    case 'not_applicable':
      return 'neutral';
    case 'valid':
    default:
      return 'ok';
  }
}

/**
 * The validator identity to display, trimmed, or null when the report names no tool (MFX-42.2).
 * Drives the "Validated with `buf build`" / "`xmlschema` is not installed on the server" lines so
 * the user knows which toolchain produced (or would have produced) the verdict.
 *
 * @param validation The emitted-output validation report.
 * @returns The tool identity, or null when none is known.
 */
export function validatorToolLabel(validation: EmittedValidationReport): string | null {
  const tool = validation.tool?.trim();
  return tool ? tool : null;
}

/** Per-severity counts for a lint report's findings, zero-filled for every severity. */
export function lintSeverityCounts(
  findings: EmittedLintFinding[],
): Record<LintSeverity, number> {
  const counts: Record<LintSeverity, number> = { error: 0, warning: 0, info: 0 };
  for (const finding of findings) counts[finding.severity] += 1;
  return counts;
}

/**
 * Whether the Verify gate permits generating the export (MFX-42.1 acceptance):
 *
 * - **invalid** — never; the export is blocked regardless of acknowledgement.
 * - **lossy** — only once the loss has been acknowledged.
 * - **clean** — always.
 *
 * @param verdict The overall verdict, or null before a verification has run.
 * @param acknowledged Whether the user has acknowledged a lossy conversion.
 * @returns True when Generate should be enabled.
 */
export function verifyGatePasses(
  verdict: ExportVerifyVerdict | null,
  acknowledged: boolean,
): boolean {
  if (!verdict) return false;
  if (verdict === 'invalid') return false;
  if (verdict === 'lossy') return acknowledged;
  return true;
}
