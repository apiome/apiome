'use client';

import Link from 'next/link';
import { COMPARE_MAX, compareHref, compareLabel } from '../../../../lib/search/compare';
import type { CatalogSearchHit } from '../../../../lib/search/hits';

/**
 * The sticky compare bar under the results (BDX-2.6). It lists the ticked hits, says why the last
 * tick was refused, and — once two hits of one project in two versions are ticked — offers
 * *Compare v1.0.0 → v2.0.0*, linking to that project's compare page at those versions.
 *
 * @param selection The ticked hits, in tick order.
 * @param error The last refusal message, or null.
 * @param onRemove Untick one hit.
 * @param onClear Untick everything and drop the message.
 */
export function CompareBar({
  selection,
  error,
  onRemove,
  onClear,
}: {
  selection: readonly CatalogSearchHit[];
  error: string | null;
  onRemove: (hit: CatalogSearchHit) => void;
  onClear: () => void;
}) {
  const href = compareHref(selection);
  const label = compareLabel(selection);
  return (
    <div className="compare-bar" role="region" aria-label="Compare selection" data-testid="compare-bar">
      <div className="compare-bar-picks">
        {selection.length === 0 ? (
          <span>Tick two hits of one project to compare their versions.</span>
        ) : (
          <>
            {selection.map((hit) => (
              <span key={hit.hit_id} className="compare-bar-pick">
                <span className="truncate">
                  {hit.project_name ?? hit.project_slug} · v{hit.version_slug}
                </span>
                <button type="button" onClick={() => onRemove(hit)} aria-label={`Remove v${hit.version_slug} from compare`} className="rounded-full p-0.5 hover:bg-[var(--brand-soft-hover)]">
                  <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
            {selection.length < COMPARE_MAX && <span>Tick one more hit of this project in another version.</span>}
          </>
        )}
      </div>
      <button type="button" onClick={onClear} className="text-[12px] text-[var(--text-secondary)] hover:underline">
        Clear
      </button>
      {href && label ? (
        <Link href={href} className="btn-brand compare-bar-go" data-testid="compare-bar-go">
          ▸ {label}
        </Link>
      ) : (
        <span className="btn-brand compare-bar-go" aria-disabled="true">
          ▸ Compare
        </span>
      )}
      {error && (
        <p className="compare-bar-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
