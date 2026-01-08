'use client';

import { useEffect } from 'react';

export default function StudioPage() {
  useEffect(() => {
    // Direct navigation to avoid router issues
    window.location.href = '/ade/studio/editor';
  }, []);

  return (
    <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <p className="text-sm text-gray-500 dark:text-gray-400">Redirecting to Studio Editor...</p>
      </div>
    </div>
  );
}
