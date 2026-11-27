'use client';

import { useEffect, useState } from 'react';
import {
  consumersSummary,
  pactBadgesUrl,
  parsePactBadges,
  type PactBadgeItem,
} from '../../../../../lib/pact/pactBadges';

/**
 * The "Pact verification" strip of a public project (PFX-1.10, #6923): one badge per pacticipant
 * bound to the project, with its consumers (PFX-7.5, #6965) — a count line and, per consumer, the
 * status of its pact. It reads the public REST route in the browser and draws nothing while
 * loading, on any error, or when no pacticipant is bound.
 *
 * `compact` (the portal product page) drops the heading and the per-consumer list, keeping the
 * badges and the consumer count line so a member row stays one glance tall.
 */
export function PactBadges({
  tenantSlug,
  projectSlug,
  compact = false,
}: {
  tenantSlug: string;
  projectSlug: string;
  compact?: boolean;
}) {
  const [items, setItems] = useState<PactBadgeItem[]>([]);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
    const controller = new AbortController();
    fetch(pactBadgesUrl(base, tenantSlug, projectSlug), { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => setItems(parsePactBadges(body)))
      .catch(() => setItems([]));
    return () => controller.abort();
  }, [tenantSlug, projectSlug]);

  if (items.length === 0) return null;
  return (
    <section className="space-y-2" aria-label="Pact verification" data-testid="pact-badges">
      {compact ? null : (
        <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Pact verification</h2>
      )}
      <ul className="flex flex-wrap items-start gap-x-4 gap-y-2">
        {items.map((item) => {
          const summary = consumersSummary(item);
          return (
            <li key={item.slug} className="space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element -- an SVG served by the REST API */}
              <img src={item.badge_url} alt={`Pact verification of ${item.name}: ${item.status}`} height={20} />
              {summary ? (
                <p className="text-xs text-zinc-600 dark:text-zinc-400" data-testid="pact-consumers-summary">
                  {summary}
                </p>
              ) : null}
              {!compact && item.consumers.length > 0 ? (
                <ul className="text-xs text-zinc-700 dark:text-zinc-300" aria-label={`Consumers of ${item.name}`}>
                  {item.consumers.map((consumer) => (
                    <li key={consumer.slug}>
                      {consumer.name} — {consumer.status}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
