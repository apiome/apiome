'use client';

import { usePathname } from 'next/navigation';
import TopHeader from './TopHeader';

export default function ConditionalHeader() {
  const pathname = usePathname();

  // Don't show TopHeader on the main /ade landing page
  if (pathname === '/ade') {
    return null;
  }

  return <TopHeader />;
}

