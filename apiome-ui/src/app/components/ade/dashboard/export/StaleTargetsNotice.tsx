'use client';

import { Alert } from '../../../ui/Alert';
import { Button } from '../../../ui/Button';

/** Props for {@link StaleTargetsNotice}. */
export interface StaleTargetsNoticeProps {
  /** When the kept list loaded (ISO 8601), from `useExportTargets().stale`. */
  savedAt: string;
  /** Read the targets again. */
  onRetry: () => void;
}

/**
 * The export targets service could not be reached, so the screen shows this source's last list
 * (MFX-46.5, #4383) — the Export dialog and Export studio's parity with the import dialog, which keeps
 * its built-in cards when the import registry is unreachable. Says how old the list is, that its
 * fidelity may be out of date, and offers **Retry**. Verify and Generate still need the service.
 *
 * @param props See {@link StaleTargetsNoticeProps}.
 * @returns The notice.
 */
export function StaleTargetsNotice({ savedAt, onRetry }: StaleTargetsNoticeProps) {
  const when = new Date(savedAt);
  const time = Number.isNaN(when.getTime()) ? null : when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return (
    <Alert
      variant="warn"
      role="status"
      data-testid="export-targets-stale"
      actions={
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      }
    >
      Export targets couldn&rsquo;t be reached. Showing the list loaded{' '}
      {time ? <time dateTime={savedAt}>at {time}</time> : 'earlier'}; fidelity may be out of date.
    </Alert>
  );
}
