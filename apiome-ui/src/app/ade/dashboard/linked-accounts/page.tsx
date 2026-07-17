import { providerSummaries } from '@lib/auth/provider-registry';
import LinkedAccountsClient from './LinkedAccountsClient';

/**
 * Linked-accounts page (server half).
 *
 * Resolves the deployment's provider availability from env via the provider registry
 * (OLO-2.3, #4195) — env is server-side only — and hands the serializable summaries to the
 * client panel, which renders exactly the enabled providers (plus coming-soon teasers).
 */
export default function LinkedAccountsPage() {
  return <LinkedAccountsClient providers={providerSummaries()} />;
}
