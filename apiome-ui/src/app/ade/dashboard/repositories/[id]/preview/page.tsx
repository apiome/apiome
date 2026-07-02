'use client';

import { Suspense } from 'react';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { RepositoryDetailClient } from '../RepositoryDetailClient';

export default function RepositoryPreviewPage() {
  return (
    <Suspense
      fallback={<LoadingState className="min-h-[40vh]" message="Loading repository…" />}
    >
      <RepositoryDetailClient />
    </Suspense>
  );
}
