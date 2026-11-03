'use client';

/**
 * `/ade/dashboard/repositories/refresh-defaults` — the workspace refresh defaults (RAR-6.5, #3542).
 *
 * `refresh-defaults` is a static sibling of `[id]`; Next.js matches static segments first, so this
 * route is never shadowed by the repository detail page.
 */

import { RefreshDefaultsClient } from './RefreshDefaultsClient';

export default function RepositoryRefreshDefaultsPage() {
  return <RefreshDefaultsClient />;
}
