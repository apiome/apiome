'use client';

import * as React from 'react';
import { CalendarClock } from 'lucide-react';

export default function MigrationSchedulerView() {
  return (
    <div className="h-full flex flex-col min-h-0 p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 rounded-lg bg-accent-soft text-accent-fg">
          <CalendarClock className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-fg">Scheduler</h2>
          <p className="text-sm text-fg-muted">
            Schedule migration runs and manage execution.
          </p>
        </div>
      </div>
      <div className="flex-1 rounded-xl border border-border bg-subtle/50 p-6 text-center">
        <p className="text-fg-muted text-sm">
          Scheduling tools and workflows will be available here.
        </p>
      </div>
    </div>
  );
}
