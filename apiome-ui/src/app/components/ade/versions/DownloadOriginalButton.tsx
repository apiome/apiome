'use client';

/**
 * "Download original" (COA-5.7, #7083): saves the file a version was imported from, under its
 * original name, from `GET /v1/versions/{tenant}/{project}/{version}/original`.
 *
 * Used on the version view (the spec viewer's footer) and on the catalog item page. A version with
 * no stored original, or one withheld at import, answers with a toast that says so.
 */

import * as React from 'react';
import { FileDown, Loader2 } from 'lucide-react';

import { Button, type ButtonProps } from '@/app/components/ui/Button';
import { downloadVersionOriginal } from '@/app/utils/version-original';
import { toast } from '../../ui/toast';

export interface DownloadOriginalButtonProps {
  /** The project (or catalog item) UUID. */
  projectId: string;
  /** The revision UUID. */
  versionId: string;
  /** Button variant (default `outline`). */
  variant?: ButtonProps['variant'];
  /** Button size. */
  size?: ButtonProps['size'];
  /** Test id (default `download-original`). */
  testId?: string;
}

/**
 * Render the button. See {@link DownloadOriginalButtonProps}.
 *
 * @returns The button.
 */
export default function DownloadOriginalButton({
  projectId,
  versionId,
  variant = 'outline',
  size,
  testId = 'download-original',
}: DownloadOriginalButtonProps) {
  const [busy, setBusy] = React.useState(false);

  const handleClick = async () => {
    setBusy(true);
    try {
      const result = await downloadVersionOriginal(projectId, versionId);
      if (result.ok) toast.success(`Downloaded ${result.filename}`);
      else toast.error(result.error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      onClick={() => void handleClick()}
      disabled={busy}
      title="Download the file this version was imported from"
      data-testid={testId}
    >
      {busy ? <Loader2 className="animate-spin" aria-hidden /> : <FileDown aria-hidden />}
      Download original
    </Button>
  );
}
