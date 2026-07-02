'use client';

import { TooltipProvider } from '@/app/components/ui/Tooltip';

export function DashboardTooltipProvider({ children }: { children: React.ReactNode }) {
  return <TooltipProvider delayDuration={400}>{children}</TooltipProvider>;
}
