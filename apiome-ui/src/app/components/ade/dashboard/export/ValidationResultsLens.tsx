/**
 * ValidationResultsLens — the Verify workbench's emitted-output validation lens (MFX-42.2, #4355).
 *
 * MFX-5.1/5.3 re-parse the emitted artifact with the target format's own toolchain (`buf build`
 * for protobuf, `xmlschema` for XSD, the Postman collection schema, …) and produce a structured
 * verdict. This lens renders that verdict:
 *
 *  - the overall band as a toned headline (valid / invalid / toolchain-unavailable / not-applicable),
 *    naming the validator that ran (or would have run);
 *  - for a rejection, the structured error list — message plus file-in-bundle, JSON pointer, and
 *    line/column wherever the validator supplies them (these locations feed MFX-43.3's markers);
 *  - external-toolchain unavailability as an explicit **warning** ("validator not installed on the
 *    server"), never a silent pass — so a skipped validation is visibly not the same as a clean one;
 *  - a positive verdict when the artifact re-parsed with zero errors.
 *
 * The lens itself never gates the export — the workbench's overall verdict (MFX-42.1) owns the
 * Generate gate; a rejection here is what drives an `invalid` band there.
 */

import { CheckCircle2, FileWarning, Gauge, ShieldCheck, ShieldX, Wrench } from 'lucide-react';
import { FindingLocation } from './FindingLocation';
import {
  validationLensState,
  validationLensTone,
  validatorToolLabel,
  type EmittedValidationReport,
  type ValidationLensTone,
} from './exportVerify';

export interface ValidationResultsLensProps {
  /** The emitted-output validation report to render (mirrors REST `EmittedValidationReport`). */
  validation: EmittedValidationReport;
}

/** Tailwind text colour for each lens tone (headline text + icon). */
function toneTextClass(tone: ValidationLensTone): string {
  switch (tone) {
    case 'invalid':
      return 'text-rose-700 dark:text-rose-300';
    case 'warn':
      return 'text-amber-700 dark:text-amber-300';
    case 'ok':
      return 'text-emerald-700 dark:text-emerald-300';
    case 'neutral':
    default:
      return 'text-gray-600 dark:text-gray-300';
  }
}

/**
 * ValidationResultsLens — renders one emitted-output validation report (MFX-42.2).
 *
 * Leads with a toned headline (and the validator identity when known), then branches by state:
 * an invalid verdict lists the structured errors with their locations; a toolchain-unavailable
 * verdict shows a distinct warning callout; a clean verdict shows a positive confirmation.
 */
export function ValidationResultsLens({ validation }: ValidationResultsLensProps) {
  const state = validationLensState(validation);
  const tone = validationLensTone(state);
  // Select an existing icon component by tone (assigned, not created — the ternary keeps each
  // branch a static component reference so it survives re-renders without resetting state).
  const Icon = tone === 'invalid' ? ShieldX : tone === 'warn' ? FileWarning : tone === 'ok' ? ShieldCheck : Gauge;
  const toneClass = toneTextClass(tone);
  const tool = validatorToolLabel(validation);

  return (
    <div className="space-y-3" data-testid="verify-validation" data-validation-state={state}>
      {/* The overall verdict headline: band + message, plus the validator identity when known. */}
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${toneClass}`} aria-hidden />
        <div className="space-y-0.5">
          <div className={`text-sm font-semibold ${toneClass}`} data-testid="verify-validation-headline">
            {validation.headline}
          </div>
          <p className="text-xs text-gray-600 dark:text-gray-300">{validation.message}</p>
          {tool && (
            <p className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400" data-testid="verify-validation-tool">
              <Wrench className="h-3 w-3 shrink-0" aria-hidden />
              {state === 'unavailable' ? (
                <span>
                  <code className="font-mono">{tool}</code> is not installed on the server.
                </span>
              ) : (
                <span>
                  Validated with <code className="font-mono">{tool}</code>.
                </span>
              )}
            </p>
          )}
        </div>
      </div>

      {/* Toolchain-unavailable is a distinct warning, not silent success: the artifact was not
          validated. Spell out the reason (the report's `detail`) and that the export is not blocked. */}
      {state === 'unavailable' && (
        <div
          data-testid="verify-validation-unavailable"
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
        >
          The emitted artifact was <strong>not validated</strong> — the validator could not run on
          this server.
          {validation.detail && <span className="mt-1 block text-amber-800 dark:text-amber-200">{validation.detail}</span>}
        </div>
      )}

      {/* Not-applicable: no toolchain matches the format, so there is genuinely nothing to check. */}
      {state === 'not_applicable' && (
        <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="verify-validation-not-applicable">
          No validator matches this format — there is nothing to validate for this target.
        </p>
      )}

      {/* A clean pass: an explicit positive confirmation (never left as an empty panel). */}
      {state === 'valid' && (
        <p className="text-sm text-emerald-700 dark:text-emerald-300" data-testid="verify-validation-clean">
          <CheckCircle2 className="mr-1.5 inline h-4 w-4 align-text-bottom" aria-hidden />
          The emitted artifact re-parsed with no validation errors.
        </p>
      )}

      {/* A rejection: the structured, actionable error list with per-finding locations. */}
      {validation.findings.length > 0 && (
        <ul className="space-y-2" data-testid="verify-validation-findings">
          {validation.findings.map((finding, idx) => (
            <li
              key={`${finding.keyword ?? 'err'}-${idx}`}
              className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm dark:border-rose-900 dark:bg-rose-950/30"
            >
              <div className="text-gray-900 dark:text-gray-100">{finding.message}</div>
              <FindingLocation
                file={finding.file}
                path={finding.path}
                line={finding.line}
                column={finding.column}
                rule={finding.keyword}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default ValidationResultsLens;
