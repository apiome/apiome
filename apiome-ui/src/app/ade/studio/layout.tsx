import { notFound } from 'next/navigation';
import type { ReactNode } from 'react';

const isCommercial = process.env.APIOME_BUILD_PROFILE === 'commercial';

export default async function StudioRouteLayout({ children }: { children: ReactNode }) {
  if (!isCommercial) {
    notFound();
  }

  const { StudioLayout } = await import('@suite/designer/routes');
  return <StudioLayout>{children}</StudioLayout>;
}
