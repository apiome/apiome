'use client';

import * as React from 'react';
import { CalendarClock } from 'lucide-react';

export default function MigrationSchedulerView() {
  return (
    <div className="h-full flex flex-col min-h-0 p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400">
          <CalendarClock className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Scheduler</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Schedule migration runs and manage execution.
          </p>
        </div>
      </div>
      <div className="flex-1 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-800/50 p-6 text-center">
        <p className="text-gray-500 dark:text-gray-400 text-sm">
          Scheduling tools and workflows will be available here.
        </p>
      </div>
    </div>
  );
}
