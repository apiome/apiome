'use client';

/**
 * Step 4 of the **Migration wizard** — **Switch over** (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`.
 *
 * What was copied, and the two variables a pipeline changes to publish to Apiome instead of the old
 * broker: the official Pact CLI and libraries keep working. **Download report** saves the run — its
 * counts, every failure with its reason, everything not portable, and the log — as JSON.
 */

import * as React from 'react';
import Link from 'next/link';
import { Check, Download, KeyRound } from 'lucide-react';
import { Button } from '@/app/components/ui';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  copiedHeadline,
  failedCount,
  formatCount,
  reportDocument,
  reportFileName,
  type MigrationLogLine,
  type MigrationRun,
} from '@lib/pact-migration';
import { downloadBlob } from '../dashboard/export/exportDownload';
import { API_KEYS_ROUTE } from '../pactSettings/CiTab';

/** Props for {@link SwitchOverStep}. */
export interface SwitchOverStepProps {
  run: MigrationRun;
  log: MigrationLogLine[];
  /** The workspace's `PACT_BROKER_BASE_URL`, once read. */
  broker: string | null;
  onBack: () => void;
}

/**
 * The **Switch over** step.
 *
 * @param props - See {@link SwitchOverStepProps}.
 * @returns The step's body and footer.
 */
export function SwitchOverStep({ run, log, broker, onBack }: SwitchOverStepProps) {
  const failed = failedCount(run);
  const download = () =>
    downloadBlob(
      new Blob([JSON.stringify(reportDocument(run, log), null, 2)], { type: 'application/json' }),
      reportFileName(run),
    );

  return (
    <>
      <div className="pmg-body" data-testid="pmg-switch">
        <div className="pmg-done">
          <span className="pmg-done__icon" aria-hidden>
            <Check />
          </span>
          <div>
            <div className="pmg-strong" data-testid="pmg-headline">
              {copiedHeadline(run)}
            </div>
            <div className="pmg-subtle">
              {failed > 0
                ? `${formatCount(failed)} ${failed === 1 ? 'record was' : 'records were'} not copied; the report lists each with its reason.`
                : 'Every record the source returned is in Apiome.'}
            </div>
          </div>
        </div>

        <section className="pmg-card" aria-labelledby="pmg-point-title">
          <h3 id="pmg-point-title" className="pmg-heading">
            Point your pipelines here
          </h3>
          <pre className="pcx-code" tabIndex={0} aria-label="The two variables" data-testid="pmg-variables">
            {`PACT_BROKER_BASE_URL=${broker ?? 'https://<api>/v1/tenants/<workspace>/pact-broker'}\nPACT_BROKER_TOKEN=<an Apiome API key>`}
          </pre>
          <p className="pmg-subtle">
            Nothing else changes: the official Pact CLI and libraries keep working. Until a pipeline has switched,
            run this migration again to bring over what it published to the old broker — repeats copy only what
            changed.
          </p>
          <div>
            <Button variant="outline" size="sm" asChild>
              <Link href={API_KEYS_ROUTE}>
                <KeyRound aria-hidden />
                Create a key with Pact scopes
              </Link>
            </Button>
          </div>
        </section>
      </div>
      <div className="pmg-footer">
        <Button variant="outline" className="pmg-footer__start" onClick={download} data-testid="pmg-download">
          <Download aria-hidden />
          Download report
        </Button>
        <Button variant="ghost" onClick={onBack} data-testid="pmg-back">
          Back
        </Button>
        <Button asChild>
          <Link href={CONTRACTS_ROUTE} data-testid="pmg-finish">
            Finish
          </Link>
        </Button>
      </div>
    </>
  );
}

export default SwitchOverStep;
