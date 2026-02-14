'use client';

import * as React from 'react';
import { BarChart3, ChevronDown, ChevronUp, X, Link2, Unlink, GitBranch, RefreshCw, Layout, Gauge, Lightbulb, LayoutGrid, Box, Layers } from 'lucide-react';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as Popover from '@radix-ui/react-popover';
import { cn } from '../../../../../lib/utils';
import type { LayoutQualityResult } from '@/app/utils/layout-quality';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import type { CanvasSuggestion } from '@/app/utils/canvas-suggestions';

interface SchemaMetricsPanelProps {
  metrics: SchemaMetricsResult | null;
  layoutQuality?: LayoutQualityResult | null;
  /** Canvas improvement suggestions (#474) */
  suggestions?: CanvasSuggestion[];
  /** Called when user triggers an action (e.g. apply layout) */
  onSuggestionAction?: (suggestion: CanvasSuggestion) => void;
  onClose?: () => void;
  isMinimized?: boolean;
  onMinimizeToggle?: () => void;
}

export default function SchemaMetricsPanel({
  metrics,
  layoutQuality,
  suggestions = [],
  onSuggestionAction,
  onClose,
  isMinimized = false,
  onMinimizeToggle,
}: SchemaMetricsPanelProps) {
  if (!metrics) {
    return (
      <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 w-72 p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Schema Metrics</span>
          </div>
          {onClose && (
            <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500" title="Close">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">Load a version to see metrics.</p>
      </div>
    );
  }

  const {
    classCount,
    totalProperties,
    averagePropertiesPerClass,
    relationshipCount,
    hubNames,
    isolatedNames,
    deepestChainLength,
    circularDependencyCount,
    circularSampleNames,
    complexityScore,
    complexityLabel,
    complexityBreakdown,
  } = metrics;

  const hasHubs = hubNames.length > 0;
  const hasIsolated = isolatedNames.length > 0;
  const hasCircular = circularDependencyCount > 0;

  if (isMinimized) {
    return (
      <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-lg shadow-lg border border-gray-200/80 dark:border-gray-700/80 p-2">
        <button
          onClick={onMinimizeToggle}
          className="flex items-center gap-2 text-xs font-medium text-gray-700 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <BarChart3 className="w-4 h-4 shrink-0" />
          <span className="tabular-nums">{classCount} classes · {totalProperties} props · {relationshipCount} rels · complexity {complexityScore}</span>
          <ChevronUp className="w-3 h-3 shrink-0" />
        </button>
      </div>
    );
  }

  return (
    <Tooltip.Provider>
      <div className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200/80 dark:border-gray-700/80 w-80 max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Schema Metrics</span>
          </div>
          <div className="flex items-center gap-1">
            {onMinimizeToggle && (
              <button
                onClick={onMinimizeToggle}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                title="Minimize"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
            )}
            {onClose && (
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Totals: static at top (#555) */}
        <div className="shrink-0 px-3 pt-3 pb-2">
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded-lg bg-gray-50 dark:bg-gray-700/50 px-2.5 py-2 text-center">
              <Box className="w-4 h-4 mx-auto mb-1 text-indigo-500" aria-hidden />
              <div className="text-lg font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                {classCount}
              </div>
              <div className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Classes
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 dark:bg-gray-700/50 px-2.5 py-2 text-center">
              <Layers className="w-4 h-4 mx-auto mb-1 text-indigo-500" aria-hidden />
              <div className="text-lg font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                {totalProperties}
              </div>
              <div className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Properties
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 dark:bg-gray-700/50 px-2.5 py-2 text-center">
              <Link2 className="w-4 h-4 mx-auto mb-1 text-indigo-500" aria-hidden />
              <div className="text-lg font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                {relationshipCount}
              </div>
              <div className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Relationships
              </div>
            </div>
          </div>
          {/* Realtime schema complexity score (#556); click to see why */}
          <Popover.Root>
            <Popover.Trigger asChild>
              <button
                type="button"
                className="mt-2 w-full rounded-lg bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 dark:border dark:border-indigo-800/30 px-3 py-2 text-left cursor-pointer hover:from-indigo-100 hover:to-purple-100 dark:hover:from-indigo-800/30 dark:hover:to-purple-800/30 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                aria-label="Schema complexity score; click to see breakdown"
                title="Click to see why this score"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <Gauge className="w-4 h-4 text-indigo-500 shrink-0" aria-hidden />
                    <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Schema complexity
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                      {complexityScore}
                    </span>
                    <span className={cn(
                      'text-xs font-medium px-1.5 py-0.5 rounded',
                      complexityLabel === 'Low' && 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
                      complexityLabel === 'Medium' && 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
                      complexityLabel === 'High' && 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300'
                    )}>
                      {complexityLabel}
                    </span>
                  </div>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                  <div
                    className={cn(
                      'h-full rounded-full transition-all duration-300',
                      complexityLabel === 'Low' && 'bg-emerald-500',
                      complexityLabel === 'Medium' && 'bg-amber-500',
                      complexityLabel === 'High' && 'bg-rose-500'
                    )}
                    style={{ width: `${complexityScore}%` }}
                  />
                </div>
                <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-1">Click for breakdown</p>
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                className="z-[10000] w-72 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none"
                sideOffset={6}
                align="start"
              >
                <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2">
                  Why is this score?
                </div>
                <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
                  Each factor contributes (value × weight) to the raw total, then capped to 0–100.
                </p>
                <table className="w-full text-[11px] text-left border-collapse">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-600">
                      <th className="py-1 pr-2 font-medium text-gray-600 dark:text-gray-400">Factor</th>
                      <th className="py-1 pr-2 font-medium text-gray-600 dark:text-gray-400 text-right">Value</th>
                      <th className="py-1 pr-2 font-medium text-gray-600 dark:text-gray-400 text-right">× weight</th>
                      <th className="py-1 font-medium text-gray-600 dark:text-gray-400 text-right">Points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {complexityBreakdown.map((row, i) => (
                      <tr key={i} className="border-b border-gray-100 dark:border-gray-700/80">
                        <td className="py-1 pr-2 text-gray-700 dark:text-gray-300">{row.label}</td>
                        <td className="py-1 pr-2 text-right tabular-nums text-gray-700 dark:text-gray-300">{row.value}</td>
                        <td className="py-1 pr-2 text-right tabular-nums text-gray-500 dark:text-gray-400">{row.weight}</td>
                        <td className="py-1 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200">{row.contribution.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 flex justify-between text-[11px]">
                  <span className="text-gray-500 dark:text-gray-400">Raw sum → capped</span>
                  <span className="font-semibold text-gray-800 dark:text-gray-200 tabular-nums">{complexityScore}/100</span>
                </div>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-3 space-y-4">
          {/* Average properties per class */}
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
              <BarChart3 className="w-3 h-3" />
              Average properties per class
            </div>
            <div className="text-lg font-semibold text-gray-800 dark:text-gray-200">
              {averagePropertiesPerClass.toFixed(1)}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {totalProperties} properties across {classCount} classes
            </p>
          </div>

          {/* Most connected (hubs) */}
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
              <Link2 className="w-3 h-3" />
              Most connected classes (hubs)
            </div>
            {hasHubs ? (
              <>
                <p className="text-sm text-gray-700 dark:text-gray-300">
                  {hubNames.length} class{hubNames.length !== 1 ? 'es' : ''} with relationships
                </p>
                <ul className="mt-1.5 space-y-0.5 text-xs text-gray-600 dark:text-gray-400 max-h-24 overflow-y-auto">
                  {hubNames.slice(0, 10).map((name, i) => (
                    <li key={i} className="truncate" title={name}>
                      {name}
                    </li>
                  ))}
                  {hubNames.length > 10 && (
                    <li className="text-gray-500 dark:text-gray-500">+{hubNames.length - 10} more</li>
                  )}
                </ul>
              </>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">No relationships in this schema.</p>
            )}
          </div>

          {/* Isolated classes */}
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
              <Unlink className="w-3 h-3" />
              Isolated classes (no relationships)
            </div>
            {hasIsolated ? (
              <>
                <p className="text-sm text-gray-700 dark:text-gray-300">
                  {isolatedNames.length} class{isolatedNames.length !== 1 ? 'es' : ''}
                </p>
                <ul className="mt-1.5 space-y-0.5 text-xs text-gray-600 dark:text-gray-400 max-h-24 overflow-y-auto">
                  {isolatedNames.slice(0, 10).map((name, i) => (
                    <li key={i} className="truncate" title={name}>
                      {name}
                    </li>
                  ))}
                  {isolatedNames.length > 10 && (
                    <li className="text-gray-500 dark:text-gray-500">+{isolatedNames.length - 10} more</li>
                  )}
                </ul>
              </>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">All classes have at least one relationship.</p>
            )}
          </div>

          {/* Deepest dependency chain */}
          <div>
            <Tooltip.Root>
              <Tooltip.Trigger asChild>
                <div>
                  <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
                    <GitBranch className="w-3 h-3" />
                    Deepest dependency chain
                  </div>
                  <div className="text-lg font-semibold text-gray-800 dark:text-gray-200">
                    {deepestChainLength} step{deepestChainLength !== 1 ? 's' : ''}
                  </div>
                </div>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content
                  className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs"
                  sideOffset={4}
                >
                  Longest path of class-to-class references (number of edges).
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          </div>

          {/* Circular dependencies */}
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1">
              <RefreshCw className="w-3 h-3" />
              Circular dependencies
            </div>
            <div className="text-lg font-semibold text-gray-800 dark:text-gray-200">
              {circularDependencyCount} cycle{circularDependencyCount !== 1 ? 's' : ''}
            </div>
            {hasCircular && circularSampleNames.length > 0 && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                e.g. {circularSampleNames.slice(0, 3).join(', ')}
                {circularSampleNames.length > 3 ? '…' : ''}
              </p>
            )}
          </div>

          {/* Layout Quality (#473) */}
          {layoutQuality && (
            <>
              <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                  <Layout className="w-3 h-3" />
                  Layout quality
                </div>
                <div className="flex items-center gap-2 mb-3">
                  <Gauge className="w-5 h-5 text-indigo-500 shrink-0" />
                  <span className="text-2xl font-bold text-gray-800 dark:text-gray-200">
                    {layoutQuality.overallScore}
                  </span>
                  <span className="text-sm text-gray-500 dark:text-gray-400">/ 100</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <Tooltip.Root>
                    <Tooltip.Trigger asChild>
                      <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg px-2 py-1.5">
                        <span className="text-gray-500 dark:text-gray-400">Edge crossings</span>
                        <div className="font-semibold text-gray-800 dark:text-gray-200">
                          {layoutQuality.edgeCrossingCount}
                        </div>
                        <span className="text-[10px] text-gray-400">lower is better</span>
                      </div>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs" sideOffset={4}>
                        Number of pairs of edges that cross. Fewer crossings improve readability.
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                  <Tooltip.Root>
                    <Tooltip.Trigger asChild>
                      <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg px-2 py-1.5">
                        <span className="text-gray-500 dark:text-gray-400">Spacing</span>
                        <div className="font-semibold text-gray-800 dark:text-gray-200">
                          {layoutQuality.nodeSpacingUniformityScore}
                        </div>
                        <span className="text-[10px] text-gray-400">uniformity 0–100</span>
                      </div>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs" sideOffset={4}>
                        How uniform the spacing between neighboring nodes is.
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                  <Tooltip.Root>
                    <Tooltip.Trigger asChild>
                      <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg px-2 py-1.5">
                        <span className="text-gray-500 dark:text-gray-400">Symmetry</span>
                        <div className="font-semibold text-gray-800 dark:text-gray-200">
                          {layoutQuality.layoutSymmetryScore}
                        </div>
                        <span className="text-[10px] text-gray-400">0–100</span>
                      </div>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs" sideOffset={4}>
                        How symmetric the layout is around its center.
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                  <Tooltip.Root>
                    <Tooltip.Trigger asChild>
                      <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg px-2 py-1.5">
                        <span className="text-gray-500 dark:text-gray-400">Balance</span>
                        <div className="font-semibold text-gray-800 dark:text-gray-200">
                          {layoutQuality.visualBalanceScore}
                        </div>
                        <span className="text-[10px] text-gray-400">0–100</span>
                      </div>
                    </Tooltip.Trigger>
                    <Tooltip.Portal>
                      <Tooltip.Content className="bg-gray-900 text-white text-xs px-2 py-1 rounded shadow-lg max-w-xs" sideOffset={4}>
                        How well the node mass is balanced around the center of the layout.
                      </Tooltip.Content>
                    </Tooltip.Portal>
                  </Tooltip.Root>
                </div>
              </div>
            </>
          )}

          {/* Suggestions (#474) */}
          {suggestions.length > 0 && (
            <div className="pt-2 border-t border-gray-200 dark:border-gray-700">
              <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
                <Lightbulb className="w-3 h-3" />
                Suggestions
              </div>
              <ul className="space-y-2">
                {suggestions.map((s) => (
                  <li
                    key={s.id}
                    className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200/80 dark:border-amber-700/50 px-2.5 py-2"
                  >
                    <div className="font-medium text-xs text-amber-900 dark:text-amber-200">
                      {s.title}
                    </div>
                    <p className="text-xs text-amber-800/90 dark:text-amber-300/90 mt-0.5">
                      {s.description}
                    </p>
                    {s.detail && (
                      <p className="text-[11px] text-amber-700/80 dark:text-amber-400/80 mt-1 truncate" title={s.detail}>
                        {s.detail}
                      </p>
                    )}
                    {s.action?.type === 'apply_hierarchical_layout' && onSuggestionAction && (
                      <button
                        type="button"
                        onClick={() => onSuggestionAction(s)}
                        className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-amber-700 dark:text-amber-300 hover:text-amber-800 dark:hover:text-amber-200 hover:underline"
                      >
                        <LayoutGrid className="w-3.5 h-3.5" />
                        Try Auto-organize
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </Tooltip.Provider>
  );
}
