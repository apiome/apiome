'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function StudioPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/ade/studio/editor');
  }, [router]);

  return (
    <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <p className="text-sm text-gray-500 dark:text-gray-400">Redirecting to Data Designer ...</p>
      </div>
    </div>
  );
}
