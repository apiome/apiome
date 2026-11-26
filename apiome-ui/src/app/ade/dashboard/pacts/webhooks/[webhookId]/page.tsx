import { WebhookDetailClient } from '@/app/components/ade/pactWebhooks';

/**
 * `/ade/dashboard/pacts/webhooks/{uuid}` — one contract webhook: what it sends and when, **Test**,
 * **Edit**, **Enable** / **Disable**, **Delete**, and its delivery log (PFX-5.6, #6950). A thin
 * server wrapper that unwraps the id.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PactWebhookPage({ params }: { params: Promise<{ webhookId: string }> }) {
  const { webhookId } = await params;
  return <WebhookDetailClient id={webhookId} />;
}
