'use client';

import { ReactNode, useState } from 'react';

type ContainerSize = 'narrow' | 'normal' | 'wide' | 'full';

interface AppShellProps {
  children: ReactNode;
  sidebar?: ReactNode;
  containerSize?: ContainerSize;
}

const containerWidth: Record<ContainerSize, string> = {
  narrow: 'max-w-3xl',
  normal: 'max-w-7xl',
  wide: 'max-w-[1480px]',
  full: 'max-w-none',
};

export function AppShell({ children, sidebar, containerSize = 'normal' }: AppShellProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  if (!sidebar) {
    return (
      <div className={`mx-auto w-full px-4 sm:px-6 lg:px-8 ${containerWidth[containerSize]}`}>
        {children}
      </div>
    );
  }

  return (
    <div className={`mx-auto w-full px-4 sm:px-6 lg:px-8 ${containerWidth[containerSize]}`}>
      <div className="lg:grid lg:grid-cols-[var(--shell-sidebar-width)_1fr] lg:gap-8">
        {/* Mobile sidebar trigger */}
        <div className="mb-4 flex items-center gap-2 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileSidebarOpen(true)}
            className="inline-flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-xs hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            aria-label="Open navigation"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            Browse
          </button>
        </div>

        {/* Desktop sidebar */}
        <aside className="hidden lg:block">
          <div className="sticky top-[5rem] max-h-[calc(100vh-6rem)] overflow-y-auto pb-8">
            {sidebar}
          </div>
        </aside>

        {/* Main content */}
        <div className="min-w-0">{children}</div>

        {/* Mobile drawer */}
        {mobileSidebarOpen && (
          <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
            <div
              className="absolute inset-0 bg-zinc-900/50 backdrop-blur-sm"
              onClick={() => setMobileSidebarOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-[300px] max-w-[85vw] overflow-y-auto border-r border-zinc-200 bg-white p-4 shadow-lg dark:border-zinc-800 dark:bg-zinc-950">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Browse</span>
                <button
                  type="button"
                  onClick={() => setMobileSidebarOpen(false)}
                  className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50"
                  aria-label="Close navigation"
                >
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              {sidebar}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
