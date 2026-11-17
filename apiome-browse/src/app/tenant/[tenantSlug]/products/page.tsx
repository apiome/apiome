/**
 * `/tenant/<tenant>/products` — there is no product index of its own: the tenant page lists its
 * products (APX-1.3, #6100), so this sends the reader there.
 */

import { redirect } from 'next/navigation';

export default async function ProductsIndexPage({ params }: { params: Promise<{ tenantSlug: string }> }) {
  const { tenantSlug } = await params;
  redirect(`/tenant/${encodeURIComponent(tenantSlug)}#products`);
}
