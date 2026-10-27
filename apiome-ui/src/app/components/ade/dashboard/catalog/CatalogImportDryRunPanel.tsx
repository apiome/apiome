'use client';

import { FlaskConical } from 'lucide-react';
import { Alert } from '../../../ui/Alert';
import { Card } from '../../../ui/Card';
import { ErrorBanner } from '../../../ui/ErrorState';
import { LoadingState } from '../../../ui/LoadingState';
import { describeDryRunCounts, type CatalogDryRunPrediction } from './catalogImportDryRun';

/** How many characters of the revision fingerprint to show; the full value is in the tooltip. */
const FINGERPRINT_CHARS = 12;

export interface CatalogImportDryRunPanelProps {
  /** A dry run is in flight. */
  running: boolean;
  /** The finished dry run's prediction, or `null` before one has finished. */
  prediction: CatalogDryRunPrediction | null;
  /** The dry run itself failed (transport or proxy), as opposed to predicting a failed import. */
  error: string | null;
  /** Run the dry run again after {@link error}. */
  onRetry: () => void;
}

/**
 * The Options step's **Dry run** result (MFI-26.4, #4097): what Import would do, with nothing
 * written.
 *
 * Three states share one region so the step does not jump: running, failed to run (with retry),
 * and the prediction — the format, where the importer would route it and why, the catalog item it
 * would create or add a revision to, and what that item would hold. A prediction that the import
 * would *fail* is still a successful dry run, and says so with the importer's own remediation.
 *
 * @param props See {@link CatalogImportDryRunPanelProps}.
 * @returns The panel, or `null` when no dry run has been asked for.
 */
export function CatalogImportDryRunPanel({
  running,
  prediction,
  error,
  onRetry,
}: CatalogImportDryRunPanelProps) {
  if (running) {
    return (
      <LoadingState
        message="Running a dry run…"
        data-testid="catalog-import-dry-run-running"
      />
    );
  }
  if (error) {
    return (
      <ErrorBanner
        title="Couldn't run the dry run"
        description={error}
        onRetry={onRetry}
        data-testid="catalog-import-dry-run-error"
      />
    );
  }
  if (!prediction) return null;

  const { identity, lint, fingerprint } = prediction;
  return (
    <Card className="cat-imp-card cat-imp-dryrun" data-testid="catalog-import-dry-run">
      <div className="cat-imp-card__title" role="status">
        <FlaskConical aria-hidden />
        Dry run complete. Nothing was saved.
      </div>
      <p className="cat-imp-note">
        This is what <strong>Import</strong> would do with this source. Choose{' '}
        <strong>Continue</strong> to review its quality, then <strong>Import</strong> to store it.
      </p>

      {!prediction.ok && prediction.error && (
        <Alert variant="danger" data-testid="catalog-import-dry-run-failure">
          <div>
            <div className="font-medium">Import would fail: {prediction.error.message}</div>
            {prediction.error.remediation && (
              <div className="text-sm">{prediction.error.remediation}</div>
            )}
          </div>
        </Alert>
      )}

      {prediction.routesElsewhere && (
        <Alert variant="warn" data-testid="catalog-import-dry-run-elsewhere">
          The importer would route this source to {prediction.destinationLabel}, not the catalog.
        </Alert>
      )}

      <dl className="cat-imp-dryrun__facts">
        <dt>Format</dt>
        <dd data-testid="catalog-import-dry-run-format">
          {prediction.formatLabel ?? 'Not recognized'}
          {prediction.paradigmLabel ? ` · paradigm ${prediction.paradigmLabel}` : ''}
        </dd>
        <dt>Destination</dt>
        <dd data-testid="catalog-import-dry-run-destination">
          {prediction.destinationLabel ?? 'Not decided — the importer stopped first'}
        </dd>
        {prediction.reason && (
          <>
            <dt>Why</dt>
            <dd>{prediction.reason}</dd>
          </>
        )}
        <dt>Catalog item</dt>
        <dd data-testid="catalog-import-dry-run-item">
          {identity.name} <span className="mono">({identity.slug})</span>
        </dd>
        {prediction.ok && (
          <>
            <dt>Contents</dt>
            <dd>{describeDryRunCounts(prediction.counts)}</dd>
          </>
        )}
        {lint && (
          <>
            <dt>Quality</dt>
            <dd>
              {Math.round(lint.score)} / 100{lint.grade ? ` · grade ${lint.grade}` : ''}
            </dd>
          </>
        )}
        {fingerprint && (
          <>
            <dt>Fingerprint</dt>
            <dd className="mono" title={fingerprint}>
              {fingerprint.slice(0, FINGERPRINT_CHARS)}
            </dd>
          </>
        )}
      </dl>
    </Card>
  );
}
