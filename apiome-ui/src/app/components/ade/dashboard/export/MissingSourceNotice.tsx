'use client';

import Link from 'next/link';
import { RotateCcw } from 'lucide-react';
import { Alert } from '../../../ui/Alert';
import { Button } from '../../../ui/Button';
import { OPEN_ACTIONS, openActionHref } from '../../../shell/openActions';

/** The export refusal codes for a source with nothing captured to export from (E1-6, #6221). */
export const MISSING_SOURCE_CODES = ['source-not-captured', 'source-withheld'] as const;

/** Where **Re-import** goes: the Catalog with its Import to catalog dialog open. */
export const REIMPORT_HREF = openActionHref('/ade/dashboard/catalog', OPEN_ACTIONS.importCatalog);

/**
 * Whether a refusal code means the source has nothing captured to export from.
 *
 * @param code The `code` of a failed export read (`useExportTargets().code`).
 * @returns True for `source-not-captured` / `source-withheld`.
 */
export function isMissingSourceCode(code: string | null | undefined): boolean {
  return (MISSING_SOURCE_CODES as readonly string[]).includes(code ?? '');
}

/** Props for {@link MissingSourceNotice}. */
export interface MissingSourceNoticeProps {
  /** The refusal code (`source-not-captured` or `source-withheld`). */
  code: string;
  /** The item's name, when known. */
  sourceLabel?: string | null;
  /** Extra class names for placement. */
  className?: string;
}

/**
 * Why a catalog item cannot be exported, and the way out (E1-6, #6221).
 *
 * An item whose source was never captured — or was deliberately not stored because it carried
 * credentials — has nothing to rebuild an export from. Instead of a bare 422 the dialog and the
 * studio say so and offer **Re-import**, which opens **Import to catalog**.
 */
export function MissingSourceNotice({ code, sourceLabel, className }: MissingSourceNoticeProps) {
  const name = sourceLabel ? <strong>{sourceLabel}</strong> : 'This item';
  return (
    <Alert
      variant="warn"
      className={className}
      data-testid="export-missing-source"
      data-code={code}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href={REIMPORT_HREF} data-testid="export-missing-source-reimport">
            <RotateCcw aria-hidden />
            Re-import
          </Link>
        </Button>
      }
    >
      {code === 'source-withheld' ? (
        <>
          {name} can&apos;t be exported: its source wasn&apos;t stored because it contained credentials.
          Re-import the source without them to export it.
        </>
      ) : (
        <>
          {name} can&apos;t be exported: its source file wasn&apos;t kept when it was imported. Re-import
          the source to export it.
        </>
      )}
    </Alert>
  );
}
