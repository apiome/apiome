'use client';

/**
 * The review page's Spec tab — COL-2.2 (#4518).
 *
 * The version under review, as its OpenAPI document, read-only: JSON or YAML (the same two
 * renderings the Versions screen's spec viewer offers, from `specRendering.ts`) in the shared
 * read-only code viewer, with a Copy button. The document is built when the tab is first shown.
 */

import * as React from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { ReadOnlyCodeViewer } from '@/app/components/ade/dashboard/export/ReadOnlyCodeViewer';
import {
  SPEC_FORMATS,
  renderSpec,
  specDownloadName,
  type SpecFormat,
} from '@/app/components/ade/versions/specRendering';

/** A load in progress, failed, or done. */
type Loaded = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; spec: string };

export interface ReviewSpecPanelProps {
  /** The review whose version is shown. */
  reviewId: string;
  /** The project's slug, for the document's name. */
  projectSlug: string;
  /** The version's label, for the document's name. */
  versionLabel: string | null;
}

/**
 * The Spec tab.
 *
 * @param props - See {@link ReviewSpecPanelProps}.
 * @returns The panel.
 */
export function ReviewSpecPanel({ reviewId, projectSlug, versionLabel }: ReviewSpecPanelProps) {
  const url = `/api/reviews/${encodeURIComponent(reviewId)}/spec?side=head`;
  const [loaded, setLoaded] = React.useState<Loaded>({ status: 'loading' });
  const [format, setFormat] = React.useState<SpecFormat>('json');

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(url);
        const json = (await response.json()) as { success?: boolean; error?: string; spec?: unknown };
        if (cancelled) return;
        if (!json.success || typeof json.spec !== 'string') {
          setLoaded({ status: 'error', message: json.error || 'Could not build the document.' });
          return;
        }
        setLoaded({ status: 'ready', spec: json.spec });
      } catch (error) {
        if (!cancelled) {
          setLoaded({ status: 'error', message: error instanceof Error ? error.message : 'Could not build the document.' });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url]);

  const rendered = React.useMemo(() => {
    if (loaded.status !== 'ready') return '';
    try {
      return renderSpec(loaded.spec, format);
    } catch {
      // A document that is not valid JSON still reads as its own text.
      return loaded.spec;
    }
  }, [loaded, format]);

  /** Copy the document in the chosen rendering. */
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(rendered);
      toast.success('Copied the document.');
    } catch {
      toast.error('Could not copy the document.');
    }
  };

  if (loaded.status === 'loading') {
    return <LoadingState message="Building the document…" minHeightClassName="rvw-min-h" data-testid="review-spec-loading" />;
  }

  if (loaded.status === 'error') {
    return (
      <div className="rvw-state">
        <Alert variant="error" data-testid="review-spec-error">
          {loaded.message}
        </Alert>
      </div>
    );
  }

  return (
    <section className="rvw-spec" aria-label="Spec" data-testid="review-spec">
      <div className="rvw-spec__head">
        <Segmented
          size="sm"
          value={format}
          onValueChange={(next) => setFormat(next as SpecFormat)}
          aria-label="Document format"
        >
          {SPEC_FORMATS.map((entry) => (
            <SegmentedItem key={entry} value={entry} data-testid={`review-spec-format-${entry}`}>
              {entry.toUpperCase()}
            </SegmentedItem>
          ))}
        </Segmented>
        <Button variant="outline" size="sm" onClick={() => void copy()} data-testid="review-spec-copy">
          <Copy aria-hidden />
          Copy
        </Button>
      </div>
      <ReadOnlyCodeViewer
        value={rendered}
        language={format}
        theme="hive"
        height="100%"
        className="rvw-spec__viewer"
        documentLabel={specDownloadName(projectSlug, versionLabel ?? undefined, format)}
        editorTestId="review-spec-editor"
        fallbackTestId="review-spec-fallback"
      />
    </section>
  );
}
