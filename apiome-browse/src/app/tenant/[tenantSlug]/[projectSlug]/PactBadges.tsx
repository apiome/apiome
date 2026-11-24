'use client';

import { useEffect, useState } from 'react';
import { pactBadgesUrl, parsePactBadges, type PactBadgeItem } from '../../../../../lib/pact/pactBadges';

/**
 * The "Pact verification" strip of a public project (PFX-1.10, #6923): one badge per pacticipant
 * bound to the project. It reads the public REST route in the browser and draws nothing while
 * loading, on any error, or when no pacticipant is bound.
 */
export function PactBadges({ tenantSlug, projectSlug }: { tenantSlug: string; projectSlug: string }) {
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
    <section className="space-y-2" aria-label="Pact verification">
      <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Pact verification</h2>
      <ul className="flex flex-wrap items-center gap-3">
        {items.map((item) => (
          <li key={item.slug}>
            {/* eslint-disable-next-line @next/next/no-img-element -- an SVG served by the REST API */}
            <img src={item.badge_url} alt={`Pact verification of ${item.name}: ${item.status}`} height={20} />
          </li>
        ))}
      </ul>
    </section>
  );
}
