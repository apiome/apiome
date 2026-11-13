'use client';

/**
 * The notice a deprecated type shows above its schema (#3482).
 *
 * One `Alert`, and every word in it comes from {@link deprecationNotice}: the title carries the
 * sunset date, the body the author's message, the advisory line what deprecation does *not* do
 * (nothing stops resolving), and — when one was named — a link to the replacement type. It
 * turns from a warning to an error once the sunset date has passed; the tone is never the only
 * signal, because the title says "sunset passed" in words.
 */

import * as React from 'react';
import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';

import type { DeprecationNoticeView } from './primitiveDetailView';

export interface DeprecationNoticeProps {
  /** The notice to draw — `deprecationNotice()`'s result for a deprecated type. */
  notice: DeprecationNoticeView;
}

/**
 * Render the notice. See {@link DeprecationNoticeProps}.
 *
 * @returns The banner: title, message, advisory line and the replacement link.
 */
export default function DeprecationNotice({ notice }: DeprecationNoticeProps) {
  return (
    <Alert
      variant={notice.sunsetPassed ? 'error' : 'warning'}
      data-testid="primitive-detail-deprecation"
      data-sunset-passed={notice.sunsetPassed ? 'true' : 'false'}
    >
      <div className="pd-deprecation">
        <AlertTitle>{notice.title}</AlertTitle>
        <AlertDescription>
          <span className="pd-deprecation__message">{notice.message}</span>{' '}
          <span className="hive-quiet">{notice.advisory}</span>
        </AlertDescription>
        {notice.replacement ? (
          <p className="pd-deprecation__replacement">
            Use instead:{' '}
            <Link
              href={notice.replacement.href}
              className="prm-ref-link mono"
              data-testid="primitive-detail-replacement"
            >
              {notice.replacement.label}
            </Link>
          </p>
        ) : null}
      </div>
    </Alert>
  );
}
