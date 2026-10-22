'use client';

/**
 * The registry tab's right rail (HIVE-6.5, #5316).
 *
 * Authority: `docs/mockups/build/primitives.html` §Registry → *Right rail* — the last eight
 * imports.
 *
 * HIVE-11.8 (#5604) moved the rail's other card, the relative `$ref` explainer with its worked
 * example, into `RefResolutionDialog`, opened from the **How resolution works** ghost link in the
 * page description; "Recent activity" stays.
 *
 * ### What this replaces
 *
 * `PrimitivesRecentActivity`, which drew both panels as `dashboardPanelClass` divs and painted
 * the code sample by hand: `bg-gray-900 dark:bg-black/40` behind `text-gray-300`,
 * `text-emerald-300` and `text-indigo-300` spans, and three `bg-*-400` dots chosen in a helper
 * that returned Tailwind palette classes. None of those could follow a theme; the sample was
 * literally a dark box in Whiteboard.
 */

import * as React from 'react';
import { Activity } from 'lucide-react';

import { Card, CardHeader, CardTitle } from '@/app/components/ui/Card';
import { STATUS_TONE_DOT_CLASS } from '@/app/components/ui/statusVocabulary';
import { cn } from '@lib/utils';
import {
  formatRelativeTime,
  sourceKindLabel,
  type PrimitiveImportActivity,
} from '@/app/ade/dashboard/primitives/primitivesRegistryTypes';

import { importActivityTitle, importActivityTone } from './primitivesModel';

export interface RegistryRailProps {
  /** The last few imports, newest first. */
  imports: readonly PrimitiveImportActivity[];
  /** True while the registry overview is being read. */
  loading: boolean;
}

/**
 * Render the rail. See {@link RegistryRailProps}.
 *
 * @returns The recent-activity card.
 */
export default function RegistryRail({ imports, loading }: RegistryRailProps) {
  return (
    <aside className="prm-rail" aria-label="Registry reference">
      <Card className="prm-rail__card prm-rail__card--flush">
        <CardHeader className="prm-rail__activity-head">
          <CardTitle className="prm-rail__title">
            <Activity aria-hidden />
            Recent activity
          </CardTitle>
          <span className="prm-rail__aside">last 8 imports</span>
        </CardHeader>

        {loading ? (
          <p className="prm-rail__state" role="status">
            Loading activity…
          </p>
        ) : imports.length === 0 ? (
          <p className="prm-rail__state">No import activity yet.</p>
        ) : (
          <ul className="prm-activity">
            {imports.map((item) => (
              <li key={item.id} className="prm-activity__row">
                <span
                  aria-hidden
                  className={cn(
                    'prm-activity__dot',
                    STATUS_TONE_DOT_CLASS[importActivityTone(item.source_kind)]
                  )}
                />
                <span className="prm-activity__text">
                  <span className="prm-activity__title">{importActivityTitle(item)}</span>
                  <span className="prm-activity__sub">
                    {[
                      sourceKindLabel(item.source_kind),
                      item.target_namespace,
                      item.created_at ? formatRelativeTime(item.created_at) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </aside>
  );
}
