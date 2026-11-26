import { WebhooksClient } from '@/app/components/ade/pactWebhooks';

/**
 * `/ade/dashboard/pacts/webhooks` — the workspace's contract webhooks, each with its newest
 * delivery, and the recent deliveries (PFX-5.6, #6950). A thin server wrapper.
 *
 * @returns The page.
 */
export default function PactWebhooksPage() {
  return <WebhooksClient />;
}
