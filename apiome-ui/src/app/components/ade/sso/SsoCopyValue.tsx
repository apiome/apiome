'use client';

import * as React from 'react';
import { Check, Copy } from 'lucide-react';

import { Button } from '@/app/components/ui';

/** Props for {@link SsoCopyValue}. */
export interface SsoCopyValueProps {
  /** What the value is, e.g. "Redirect URI" — names the copy button for screen readers. */
  label: string;
  /** The value to show and copy. Never a secret. */
  value: string;
}

/**
 * A value someone pastes elsewhere — a redirect URI, a DNS record name, a token — in monospace
 * with a Copy button beside it (EID-1.2, #5012).
 *
 * @param props See {@link SsoCopyValueProps}.
 * @returns The value and its button.
 */
export function SsoCopyValue({ label, value }: SsoCopyValueProps) {
  const [copied, setCopied] = React.useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // No clipboard (insecure origin, denied permission): the value is on screen to select.
    }
  };

  return (
    <span className="wsso-copy">
      <code className="wsso-copy__value mono">{value}</code>
      <Button type="button" variant="ghost" size="sm" onClick={() => void copy()} aria-label={`Copy ${label}`}>
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </span>
  );
}
