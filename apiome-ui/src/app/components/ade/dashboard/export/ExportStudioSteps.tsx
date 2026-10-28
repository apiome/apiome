/**
 * Export studio's numbered stepper (MFX-41.1) and its five stops — shared by the studio
 * (`ExportStudio`) and the source picker the route draws without a source (E1-2, #6218).
 */

import { Check } from 'lucide-react';
import { stepperStatus } from '../../../ui/Stepper';
import type { ExportStudioStep } from './exportStudioUrlState';

/**
 * The Studio's five stepper stops (MFX-41.1). The key list is owned by `exportStudioUrlState`
 * because the URL's `step` param is validated against it (MFX-41.4); the labels stay here.
 */
export const STUDIO_STEPS: { key: ExportStudioStep; label: string }[] = [
  { key: 'source', label: 'Source' },
  { key: 'target', label: 'Target' },
  { key: 'options', label: 'Options' },
  { key: 'verify', label: 'Verify' },
  { key: 'review', label: 'Review & Generate' },
];

/**
 * The numbered stepper (MFX-41.1) — the ImportDialog/ExportDialog pill pattern, full width. Shared
 * by the studio and its source picker (E1-2), which draws it on **Source**.
 *
 * The three states are distinguished by glyph and weight as well as palette (MFX-41.5): a completed
 * step leads with a check and says so to a screen reader, the current step carries
 * `aria-current="step"`, and an upcoming step keeps its number outlined. The steps are status, not
 * controls — navigation is the Back / Continue pair.
 *
 * @param props.stepIndex The index of the current step in {@link STUDIO_STEPS}.
 * @returns The ordered list.
 */
export function ExportStudioSteps({ stepIndex }: { stepIndex: number }) {
  return (
    <ol data-testid="export-studio-stepper" aria-label="Export steps" role="list" className="xstd-steps">
      {STUDIO_STEPS.map((s, idx) => {
        const state = stepperStatus(idx, stepIndex);
        return (
          <li
            key={s.key}
            data-testid={`export-studio-step-${s.key}`}
            data-state={state}
            aria-current={state === 'current' ? 'step' : undefined}
            className="xstd-step"
          >
            <span className="xstd-step__num" aria-hidden>
              {state === 'done' ? <Check /> : idx + 1}
            </span>
            {s.label}
            <span className="sr-only">
              {state === 'done'
                ? ' — completed'
                : state === 'current'
                  ? ` — current step, ${idx + 1} of ${STUDIO_STEPS.length}`
                  : ' — not started'}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
