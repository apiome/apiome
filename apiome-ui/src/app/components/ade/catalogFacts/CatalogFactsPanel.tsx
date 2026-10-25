'use client';

/**
 * The **Facts** checklist of a catalog entity — CDG-5.4 (#5982).
 *
 * The facts the entity carries for per-kind scorecards — owner, consumers, dependencies, freshness,
 * deployment, shadow APIs, registry level, trust baseline, agent readiness, whichever apply to its
 * kind — each with a status (shown as an icon *and* words), what it is based on, and links to the
 * evidence. Until maturity ladders (GVM-1.x) exist there is **no score**: the panel never shows a
 * grade or a percentage, because one computed from partial facts would mislead. Loads only when
 * `active`.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleCheck, CircleDashed, CircleMinus, CircleX, RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import { FACT_STATUS_LABELS, releasedFacts, type CatalogFactsResponse, type FactStatus } from '@lib/catalog-facts';
import { fetchCatalogFacts } from './catalogFactsApi';

/** Props for {@link CatalogFactsPanel}. */
export interface CatalogFactsPanelProps {
  /** The registry kind (`spec`, `api`, `mcp_server`, `connector`, `agent`, `model`, `gateway_config`). */
  kind: string;
  /** The entity id. */
  id: string;
  /** Load once the panel is shown. */
  active?: boolean;
}

/** The icon each status leads with. */
const STATUS_ICONS: Readonly<Record<FactStatus, typeof CircleCheck>> = {
  met: CircleCheck,
  unmet: CircleX,
  not_applicable: CircleMinus,
  not_assessed: CircleDashed,
};

/**
 * The facts checklist.
 *
 * @param props - See {@link CatalogFactsPanelProps}.
 * @returns The section.
 */
export function CatalogFactsPanel({ kind, id, active = true }: CatalogFactsPanelProps) {
  const [facts, setFacts] = React.useState<CatalogFactsResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setFacts(await fetchCatalogFacts(kind, id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the facts');
    }
  }, [kind, id]);

  React.useEffect(() => {
    if (active && facts === null && error === null) void load();
  }, [active, facts, error, load]);

  // Facts about held-back features, and evidence links into their pages, wait for their release.
  const shown = facts ? releasedFacts(facts.facts) : [];

  return (
    <section className="cfx" aria-labelledby={`cfx-title-${id}`} data-testid="catalog-facts">
      <div className="cfx__head">
        <h2 id={`cfx-title-${id}`} className="cfx__title">
          Facts
        </h2>
        <p className="cfx__note">A checklist for scorecards. No score until maturity ladders are available.</p>
      </div>
      {error ? (
        <EmptyState
          variant="compact"
          surface={false}
          tone="danger"
          title="The facts could not be read"
          description={error}
          action={
            <Button variant="soft" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Try again
            </Button>
          }
        />
      ) : !facts ? (
        <LoadingState message="Reading the facts…" minHeightClassName="min-h-[6rem]" />
      ) : shown.length === 0 ? (
        <p className="cfx__note">No facts apply to this kind of entity.</p>
      ) : (
        <ul className="cfx__list">
          {shown.map((fact) => {
            const Icon = STATUS_ICONS[fact.status];
            return (
              <li key={fact.key} className="cfx__item" data-status={fact.status} data-testid={`catalog-fact-${fact.key}`}>
                <Icon className="cfx__icon" aria-hidden />
                <div className="cfx__body">
                  <div className="cfx__line">
                    <span className="cfx__label">{fact.label}</span>
                    <span className="cfx__status">{FACT_STATUS_LABELS[fact.status]}</span>
                    {typeof fact.value === 'number' ? <span className="cfx__value">{fact.value}</span> : null}
                  </div>
                  {fact.detail ? <p className="cfx__detail">{fact.detail}</p> : null}
                  {fact.evidence.some((entry) => entry.href) ? (
                    <p className="cfx__evidence">
                      {fact.evidence
                        .filter((entry) => entry.href)
                        .map((entry) => (
                          <Link key={`${entry.label}:${entry.href}`} className="cfx__link" href={entry.href!}>
                            {entry.label}
                          </Link>
                        ))}
                    </p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
