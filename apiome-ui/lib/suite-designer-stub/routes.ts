import type { ComponentType, ReactNode } from 'react';

export function StudioLayout({ children }: { children: ReactNode }) {
  return children;
}

export async function resolveStudioPage(_slug?: string[]): Promise<ComponentType> {
  throw new Error('Suite designer is not available in this build.');
}
