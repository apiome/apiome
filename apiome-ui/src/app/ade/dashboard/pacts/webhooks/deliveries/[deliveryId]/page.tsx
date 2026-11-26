import { DeliveryDetailClient } from '@/app/components/ade/pactWebhooks';

/**
 * `/ade/dashboard/pacts/webhooks/deliveries/{uuid}` — one webhook delivery: every attempt's
 * execution log, and **Redeliver** (PFX-5.6, #6950). A thin server wrapper that unwraps the id.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PactWebhookDeliveryPage({ params }: { params: Promise<{ deliveryId: string }> }) {
  const { deliveryId } = await params;
  return <DeliveryDetailClient id={deliveryId} />;
}
