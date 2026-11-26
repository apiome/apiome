import { VerificationSettingsClient } from '@/app/components/ade/pactRemediation';

/**
 * `/ade/dashboard/pacts/settings` — the workspace's Pact verification settings: cadence, stale
 * threshold, concurrent scheduled runs, re-publish request window, and provider / pair overrides
 * (PFX-6.2, #6954). A thin server wrapper.
 *
 * @returns The page.
 */
export default function PactVerificationSettingsPage() {
  return <VerificationSettingsClient />;
}
