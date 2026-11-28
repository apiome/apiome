'use client';

/**
 * The **Past migrations** drawer of the Migration wizard (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`: every run the workspace started — its source, its state and
 * when — newest first. Opening one puts it back in the wizard: a dry run on **Choose**, a copy on
 * **Copy** (to watch, resume or retry) or **Switch over** (to read its report).
 */

import * as React from 'react';
import {
  Badge,
  Button,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/app/components/ui';
import { formatWhen, runBadge, type MigrationRun } from '@lib/pact-migration';

/** Props for {@link PastMigrationsDrawer}. */
export interface PastMigrationsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runs: MigrationRun[];
  /** Why the list could not be read, if it could not. */
  error: string | null;
  onOpenRun: (run: MigrationRun) => void;
}

/**
 * The drawer.
 *
 * @param props - See {@link PastMigrationsDrawerProps}.
 * @returns The drawer.
 */
export function PastMigrationsDrawer({ open, onOpenChange, runs, error, onOpenRun }: PastMigrationsDrawerProps) {
  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent data-testid="pmg-drawer">
        <DrawerHeader>
          <DrawerTitle>Past migrations</DrawerTitle>
          <DrawerDescription>Open one to resume it or read its report.</DrawerDescription>
        </DrawerHeader>
        <DrawerBody className="pvl">
          {error ? (
            <p className="ppub-hint ppub-hint--danger" role="alert">
              {error}
            </p>
          ) : null}
          <table className="pvl-table" data-testid="pmg-runs">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">State</th>
                <th scope="col">When</th>
                <th scope="col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const badge = runBadge(run);
                return (
                  <tr key={run.id} data-testid="pmg-run-row">
                    <td className="pvl-mono">{run.host}</td>
                    <td>
                      <Badge status={badge.status}>{badge.label}</Badge>
                    </td>
                    <td className="pvl-subtle">
                      {formatWhen(run.created_at)}
                      {run.started_by ? ` · ${run.started_by}` : ''}
                    </td>
                    <td>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onOpenRun(run)}
                        aria-label={`Open the migration from ${run.host} of ${formatWhen(run.created_at)}`}
                      >
                        Open
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {runs.length === 0 && !error ? (
                <tr>
                  <td colSpan={4} className="pvl-subtle">
                    No migration has been run in this workspace yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}

export default PastMigrationsDrawer;
