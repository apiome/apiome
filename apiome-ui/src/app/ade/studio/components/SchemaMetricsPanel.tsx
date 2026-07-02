'use client';

import * as React from 'react';
import { BarChart3, ChevronDown, ChevronUp, X, Link2, Unlink, GitBranch, RefreshCw, Layout, Gauge, Lightbulb, LayoutGrid, Box, Layers, FileText, Type, Network, FileDown, Brain, Sprout, Hammer } from 'lucide-react';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as Popover from '@radix-ui/react-popover';
import { cn } from '../../../../../lib/utils';
import type { LayoutQualityResult } from '@/app/utils/layout-quality';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import type { CanvasSuggestion } from '@/app/utils/canvas-suggestions';
import type { CanvasLayoutGraphAnalysis } from '@/app/utils/canvas-layout-graph-analysis';
import { downloadSchemaScoreReportPdf } from '@/app/utils/export-schema-score-report-pdf';
import { CanvasLayoutIntelligenceSection } from './CanvasLayoutIntelligenceSection';
import { getNumericScoreTier, NUMERIC_SCORE_TIER_LEGEND } from '@/app/utils/numeric-score-tier';
import { OVERALL_SCHEMA_QUALITY_WEIGHTS, type OverallSchemaQualityDetail } from '@/app/utils/overall-schema-quality';

interface SchemaMetricsPanelProps {
  metrics: SchemaMetricsResult | null;
  layoutQuality?: LayoutQualityResult | null;
  /** Weighted overall + letter grade; same formula as Studio header (#2548) */
  overallSchemaQualityDetail?: OverallSchemaQualityDetail | null;
  /** Canvas improvement suggestions (#474) */
  suggestions?: CanvasSuggestion[];
  /** Deterministic ReactFlow layout analysis (#623) */
  canvasLayoutAnalysis?: CanvasLayoutGraphAnalysis | null;
  tenantId?: string | null;
  projectId?: string | null;
  versionId?: string | null;
  onPreviewLayoutDirection?: (direction: 'TB' | 'LR') => void;
  /** Shown on exported PDF cover (#252) */
  projectName?: string;
  versionLabel?: string;
  /** Called when user triggers an action (e.g. apply layout) */
  onSuggestionAction?: (suggestion: CanvasSuggestion) => void;
  /** Opens AI improvement suggestions from live metrics (#253). */
  onOpenAiImprovementSuggestions?: () => void;
  onClose?: () => void;
  isMinimized?: boolean;
  onMinimizeToggle?: () => void;
}

export default function SchemaMetricsPanel({
  metrics,
  layoutQuality,
  overallSchemaQualityDetail = null,
  suggestions = [],
  canvasLayoutAnalysis = null,
  tenantId,
  projectId,
  versionId,
  onPreviewLayoutDirection,
  projectName,
  versionLabel,
  onSuggestionAction,
  onOpenAiImprovementSuggestions,
  onClose,
  isMinimized = false,
  onMinimizeToggle,
}: SchemaMetricsPanelProps) {
  if (!metrics) {
    const hasVersionLoaded = Boolean(versionLabel && versionLabel.trim().length > 0);
    const emptyMessage = hasVersionLoaded
      ? 'No classes in this version.'
      : 'Load a version to see metrics.';
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
        <p className="text-sm text-gray-500 dark:text-gray-400">{emptyMessage}</p>
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
    documentationCompletionPercentage,
    classesMissingDocumentation,
    propertiesMissingDocumentation,
    namingCompliance,
    dependencyMetricsPerClass = [],
    cognitiveComplexityPerClass = [],
    dependencyGraphComplexity,
    maintainabilityIndex,
    technicalDebtMetrics,
  } = metrics;

  const docsScoreTier = getNumericScoreTier(documentationCompletionPercentage);
  const namingScoreTier = getNumericScoreTier(namingCompliance.compliancePercentage);

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
          <span className="tabular-nums">{classCount} classes · {totalProperties} props · {relationshipCount} rels · complexity {complexityScore} · docs {documentationCompletionPercentage}% · naming {namingCompliance.compliancePercentage}%</span>
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
            {onOpenAiImprovementSuggestions && (
              <button
                type="button"
                onClick={onOpenAiImprovementSuggestions}
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-amber-600 dark:text-amber-400"
                title="AI improvement suggestions from these metrics"
                aria-label="AI improvement suggestions from these metrics"
                data-testid="schema-metrics-ai-improvements"
              >
                <Lightbulb className="w-4 h-4" />
              </button>
            )}
            <button
              type="button"
              onClick={() =>
                downloadSchemaScoreReportPdf({
                  metrics,
                  layoutQuality,
                  suggestions,
                  projectName,
                  versionLabel,
                })
              }
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
              title="Export score report as PDF"
              aria-label="Export score report as PDF"
            >
              <FileDown className="w-4 h-4" />
            </button>
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
          {/* Overall schema quality — matches import Quality Score presentation (#2548) */}
          {overallSchemaQualityDetail && (
            <div className="mt-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900/50 dark:to-gray-800/50 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <div
                    className={`text-3xl font-bold tabular-nums leading-none shrink-0 ${overallSchemaQualityDetail.tier.textClass}`}
                    title={`${overallSchemaQualityDetail.tier.shortLabel} (${overallSchemaQualityDetail.tier.rangeLabel})`}
                  >
                    {overallSchemaQualityDetail.letterGrade}
                  </div>
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 leading-none">
                      Schema quality
                    </div>
                    <div className={`text-xs font-semibold mt-0.5 leading-tight ${overallSchemaQualityDetail.tier.textClass}`}>
                      {overallSchemaQualityDetail.tier.shortLabel} — {overallSchemaQualityDetail.tier.detailLabel}
                    </div>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className={`text-2xl font-bold tabular-nums leading-none ${overallSchemaQualityDetail.tier.textClass}`}>
                    {overallSchemaQualityDetail.overall}
                  </div>
                  <div className="text-[10px] text-gray-500 dark:text-gray-400 tabular-nums">/ 100</div>
                </div>
              </div>
              <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-2 leading-snug">
                Weighted blend — documentation {OVERALL_SCHEMA_QUALITY_WEIGHTS.documentation}, naming {OVERALL_SCHEMA_QUALITY_WEIGHTS.naming}, structural load {OVERALL_SCHEMA_QUALITY_WEIGHTS.structuralLoad}
                {overallSchemaQualityDetail.layoutIncluded
                  ? `, canvas layout ${OVERALL_SCHEMA_QUALITY_WEIGHTS.layout}.`
                  : '.'}
              </p>
              <div className="mt-2 pt-2 border-t border-gray-200/80 dark:border-gray-600/80">
                <div className="text-[9px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1.5">
                  Score guide
                </div>
                <ul className="space-y-1 text-[10px] text-gray-600 dark:text-gray-300">
                  {NUMERIC_SCORE_TIER_LEGEND.map((row) => (
                    <li key={row.band} className="flex items-start gap-1.5">
                      <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${row.barSolidClass}`} aria-hidden />
                      <span>
                        <span className="font-medium tabular-nums">{row.rangeLabel}:</span> {row.shortLabel}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
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
            {/* Documentation and Naming side-by-side */}
            <div className="flex gap-2 mt-2">
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="flex-1 min-w-0 rounded-lg bg-gray-50 dark:bg-gray-700/50 dark:border dark:border-gray-600/50 px-2.5 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/50 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  aria-label="Documentation coverage; click to see where coverage is missing"
                  title="Click to see where coverage needs to be completed"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <FileText className="w-4 h-4 text-indigo-500 shrink-0" aria-hidden />
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Docs
                      </span>
                    </div>
                    <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                      {documentationCompletionPercentage}%
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-gray-200 dark:bg-gray-600 overflow-hidden">
                    <div
                      className={cn('h-full rounded-full transition-all duration-300', docsScoreTier.barSolidClass)}
                      style={{ width: `${documentationCompletionPercentage}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-1 truncate">Click for gaps</p>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[10000] w-80 max-h-[min(60vh,400px)] rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none flex flex-col"
                  sideOffset={6}
                  align="start"
                >
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2 shrink-0">
                    Where coverage needs to be completed
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3 shrink-0">
                    Classes and properties below are missing a non-empty description.
                  </p>
                  <div className="min-h-0 overflow-y-auto space-y-3">
                    {classesMissingDocumentation.length > 0 && (
                      <div>
                        <div className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                          Classes missing description ({classesMissingDocumentation.length})
                        </div>
                        <ul className="space-y-0.5 text-[11px] text-gray-700 dark:text-gray-300">
                          {classesMissingDocumentation.slice(0, 50).map((name, i) => (
                            <li key={i} className="truncate font-medium" title={name}>
                              {name}
                            </li>
                          ))}
                          {classesMissingDocumentation.length > 50 && (
                            <li className="text-gray-500 dark:text-gray-400">+{classesMissingDocumentation.length - 50} more</li>
                          )}
                        </ul>
                      </div>
                    )}
                    {propertiesMissingDocumentation.length > 0 && (
                      <div>
                        <div className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                          Properties missing description ({propertiesMissingDocumentation.length})
                        </div>
                        <ul className="space-y-0.5 text-[11px] text-gray-700 dark:text-gray-300">
                          {propertiesMissingDocumentation.slice(0, 50).map((item, i) => (
                            <li key={i} className="truncate" title={`${item.className} › ${item.propertyName}`}>
                              <span className="text-gray-500 dark:text-gray-400">{item.className}</span>
                              <span className="mx-1 text-gray-400 dark:text-gray-500">›</span>
                              <span className="font-medium">{item.propertyName}</span>
                            </li>
                          ))}
                          {propertiesMissingDocumentation.length > 50 && (
                            <li className="text-gray-500 dark:text-gray-400">+{propertiesMissingDocumentation.length - 50} more</li>
                          )}
                        </ul>
                      </div>
                    )}
                    {classesMissingDocumentation.length === 0 && propertiesMissingDocumentation.length === 0 && (
                      <p className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                        All classes and properties have descriptions.
                      </p>
                    )}
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="flex-1 min-w-0 rounded-lg bg-gray-50 dark:bg-gray-700/50 dark:border dark:border-gray-600/50 px-2.5 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/50 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  aria-label="Naming convention compliance; click to see breakdown"
                  title="Click to see PascalCase / camelCase / snake_case breakdown"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <Type className="w-4 h-4 text-indigo-500 shrink-0" aria-hidden />
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        Naming
                      </span>
                    </div>
                    <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                      {namingCompliance.compliancePercentage}%
                    </span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-gray-200 dark:bg-gray-600 overflow-hidden">
                    <div
                      className={cn('h-full rounded-full transition-all duration-300', namingScoreTier.barSolidClass)}
                      style={{ width: `${namingCompliance.compliancePercentage}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-1 truncate" title="Classes PascalCase, properties camelCase">Pascal / camel</p>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[10000] w-80 max-h-[min(60vh,400px)] rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none flex flex-col"
                  sideOffset={6}
                  align="start"
                >
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2 shrink-0">
                    Naming convention compliance
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3 shrink-0">
                    Recommended: class names PascalCase, property names camelCase.
                  </p>
                  <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
                    <div className="rounded bg-gray-50 dark:bg-gray-700/50 px-2 py-1.5">
                      <span className="text-gray-500 dark:text-gray-400">Classes (PascalCase)</span>
                      <div className="font-semibold text-gray-800 dark:text-gray-200">
                        {namingCompliance.classes.pascal}/{namingCompliance.classes.total}
                      </div>
                    </div>
                    <div className="rounded bg-gray-50 dark:bg-gray-700/50 px-2 py-1.5">
                      <span className="text-gray-500 dark:text-gray-400">Properties (camelCase)</span>
                      <div className="font-semibold text-gray-800 dark:text-gray-200">
                        {namingCompliance.properties.camel}/{namingCompliance.properties.total}
                      </div>
                    </div>
                  </div>
                  <div className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                    Property naming breakdown
                  </div>
                  <ul className="text-[11px] text-gray-600 dark:text-gray-400 space-y-0.5 mb-3">
                    <li>camelCase: {namingCompliance.properties.camel}</li>
                    <li>snake_case: {namingCompliance.properties.snake}</li>
                    <li>PascalCase: {namingCompliance.properties.pascal}</li>
                    {namingCompliance.properties.other > 0 && <li>other: {namingCompliance.properties.other}</li>}
                  </ul>
                  <div className="min-h-0 overflow-y-auto space-y-3">
                    {namingCompliance.classesNonPascal.length > 0 && (
                      <div>
                        <div className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                          Classes not PascalCase ({namingCompliance.classesNonPascal.length})
                        </div>
                        <ul className="space-y-0.5 text-[11px] text-gray-700 dark:text-gray-300">
                          {namingCompliance.classesNonPascal.slice(0, 30).map((name, i) => (
                            <li key={i} className="truncate font-medium" title={name}>{name}</li>
                          ))}
                          {namingCompliance.classesNonPascal.length > 30 && (
                            <li className="text-gray-500 dark:text-gray-400">+{namingCompliance.classesNonPascal.length - 30} more</li>
                          )}
                        </ul>
                      </div>
                    )}
                    {namingCompliance.propertiesNonCamel.length > 0 && (
                      <div>
                        <div className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                          Properties not camelCase ({namingCompliance.propertiesNonCamel.length})
                        </div>
                        <ul className="space-y-0.5 text-[11px] text-gray-700 dark:text-gray-300">
                          {namingCompliance.propertiesNonCamel.slice(0, 30).map((item, i) => (
                            <li key={i} className="truncate" title={`${item.className} › ${item.propertyName}`}>
                              <span className="text-gray-500 dark:text-gray-400">{item.className}</span>
                              <span className="mx-1 text-gray-400 dark:text-gray-500">›</span>
                              <span className="font-medium">{item.propertyName}</span>
                            </li>
                          ))}
                          {namingCompliance.propertiesNonCamel.length > 30 && (
                            <li className="text-gray-500 dark:text-gray-400">+{namingCompliance.propertiesNonCamel.length - 30} more</li>
                          )}
                        </ul>
                      </div>
                    )}
                    {namingCompliance.classesNonPascal.length === 0 && namingCompliance.propertiesNonCamel.length === 0 && (
                      <p className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                        All class names are PascalCase and all property names are camelCase.
                      </p>
                    )}
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
            </div>
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

          {/* #611: Dependency-only graph complexity (score + factor breakdown) */}
          <div>
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="w-full rounded-lg bg-gray-50 dark:bg-gray-700/40 dark:border dark:border-gray-600/40 px-2.5 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/40 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  aria-label="Dependency graph complexity; click for breakdown"
                  title="Property references and class composition edges only — click for breakdown"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Network className="w-4 h-4 text-indigo-500 shrink-0" aria-hidden />
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider truncate">
                        Dependency graph complexity
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                        {dependencyGraphComplexity.score}
                      </span>
                      <span
                        className={cn(
                          'text-xs font-medium px-1.5 py-0.5 rounded',
                          dependencyGraphComplexity.scoreLabel === 'Low' &&
                            'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
                          dependencyGraphComplexity.scoreLabel === 'Medium' &&
                            'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
                          dependencyGraphComplexity.scoreLabel === 'High' &&
                            'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
                        )}
                      >
                        {dependencyGraphComplexity.scoreLabel}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-1 leading-snug">
                    {dependencyGraphComplexity.edgeCount} dependency edge
                    {dependencyGraphComplexity.edgeCount !== 1 ? 's' : ''} · deepest chain{' '}
                    {dependencyGraphComplexity.deepestChainSteps} step
                    {dependencyGraphComplexity.deepestChainSteps !== 1 ? 's' : ''} ·{' '}
                    {dependencyGraphComplexity.circularGroupCount} cycle group
                    {dependencyGraphComplexity.circularGroupCount !== 1 ? 's' : ''}
                  </p>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">Click for factor breakdown</p>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[10000] w-72 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none"
                  sideOffset={6}
                  align="start"
                >
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2">
                    Why this dependency graph score?
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
                    Uses only property references and class-level allOf, anyOf, and oneOf links—the same
                    dependency edges as the per-class table below. Layout-only canvas edges are excluded.
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
                      {dependencyGraphComplexity.breakdown.map((row, i) => (
                        <tr key={i} className="border-b border-gray-100 dark:border-gray-700/80">
                          <td className="py-1 pr-2 text-gray-700 dark:text-gray-300">{row.label}</td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-700 dark:text-gray-300">{row.value}</td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-500 dark:text-gray-400">{row.weight}</td>
                          <td className="py-1 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200">
                            {row.contribution.toFixed(1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 flex justify-between text-[11px]">
                    <span className="text-gray-500 dark:text-gray-400">Raw sum → capped</span>
                    <span className="font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                      {dependencyGraphComplexity.score}/100
                    </span>
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </div>

          {/* #613: Maintainability index (higher = easier to evolve) */}
          <div>
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="w-full rounded-lg bg-gray-50 dark:bg-gray-700/40 dark:border dark:border-gray-600/40 px-2.5 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/40 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  aria-label="Maintainability index; click for breakdown"
                  title="Composite from docs, naming, inverted structural complexity, cognitive load, and class size"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Sprout className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" aria-hidden />
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider truncate">
                        Maintainability index
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                        {maintainabilityIndex.score}
                      </span>
                      <span
                        className={cn(
                          'text-xs font-medium px-1.5 py-0.5 rounded',
                          maintainabilityIndex.scoreLabel === 'High' &&
                            'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
                          maintainabilityIndex.scoreLabel === 'Medium' &&
                            'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
                          maintainabilityIndex.scoreLabel === 'Low' &&
                            'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
                        )}
                      >
                        {maintainabilityIndex.scoreLabel}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-1 leading-snug">
                    Higher scores mean easier long-term evolution (docs + naming + simplicity, minus load penalties).
                  </p>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">Click for factor breakdown</p>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[10000] w-72 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none"
                  sideOffset={6}
                  align="start"
                >
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2">
                    Why this maintainability score? (#613)
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
                    Weighted blend of documentation and naming quality, inverted aggregate schema complexity and
                    dependency-graph tangling, minus mean per-class cognitive complexity and a penalty when average
                    properties per class exceed 14.
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
                      {maintainabilityIndex.breakdown.map((row, i) => (
                        <tr key={i} className="border-b border-gray-100 dark:border-gray-700/80">
                          <td className="py-1 pr-2 text-gray-700 dark:text-gray-300">{row.label}</td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                            {row.value}
                          </td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-500 dark:text-gray-400">
                            {row.weight}
                          </td>
                          <td className="py-1 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200">
                            {row.contribution.toFixed(1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 flex justify-between text-[11px]">
                    <span className="text-gray-500 dark:text-gray-400">Composite → capped 0–100</span>
                    <span className="font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                      {maintainabilityIndex.score}/100
                    </span>
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </div>

          {/* #614: Technical debt aggregate (higher = more remediation pressure) */}
          <div>
            <Popover.Root>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  className="w-full rounded-lg bg-gray-50 dark:bg-gray-700/40 dark:border dark:border-gray-600/40 px-2.5 py-2 text-left cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600/40 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-gray-800"
                  aria-label="Technical debt score; click for breakdown"
                  title="Composite debt from docs, naming, complexity, dependencies, branching, cycles, depth, cognitive load, isolation, and class width"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Hammer className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" aria-hidden />
                      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider truncate">
                        Technical debt
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-lg font-bold text-gray-800 dark:text-gray-200 tabular-nums">
                        {technicalDebtMetrics.debtScore}
                      </span>
                      <span
                        className={cn(
                          'text-xs font-medium px-1.5 py-0.5 rounded',
                          technicalDebtMetrics.scoreLabel === 'Low' &&
                            'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
                          technicalDebtMetrics.scoreLabel === 'Medium' &&
                            'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
                          technicalDebtMetrics.scoreLabel === 'High' &&
                            'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
                        )}
                      >
                        {technicalDebtMetrics.scoreLabel}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-1 leading-snug">
                    Higher scores mean more aggregate remediation pressure (inverse of “healthy and simple”).
                  </p>
                  <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">Click for factor breakdown</p>
                </button>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  className="z-[10000] w-72 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg p-3 focus:outline-none"
                  sideOffset={6}
                  align="start"
                >
                  <div className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2">
                    Why this technical debt score? (#614)
                  </div>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
                    Each factor is capped 0–100, then weighted into a 0–100 aggregate. Low debt is better; included in
                    the schema score PDF export and AI metrics digest.
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
                      {technicalDebtMetrics.breakdown.map((row, i) => (
                        <tr key={i} className="border-b border-gray-100 dark:border-gray-700/80">
                          <td className="py-1 pr-2 text-gray-700 dark:text-gray-300">{row.label}</td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                            {row.value}
                          </td>
                          <td className="py-1 pr-2 text-right tabular-nums text-gray-500 dark:text-gray-400">
                            {row.weight}
                          </td>
                          <td className="py-1 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200">
                            {row.contribution.toFixed(1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 flex justify-between text-[11px]">
                    <span className="text-gray-500 dark:text-gray-400">Weighted sum → capped 0–100</span>
                    <span className="font-semibold text-gray-800 dark:text-gray-200 tabular-nums">
                      {technicalDebtMetrics.debtScore}/100
                    </span>
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </div>

          {/* #553: Dependency metrics per class (in-degree, out-degree, betweenness) */}
          {dependencyMetricsPerClass.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                <Network className="w-3 h-3" />
                Dependency metrics per class
              </div>
              <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
                In = refs into this class; Out = refs from this class; Betweenness = bridge score.
              </p>
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 overflow-hidden max-h-48 overflow-y-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="sticky top-0 bg-gray-50 dark:bg-gray-700/80 text-left">
                    <tr>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400">Class</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-12">In</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-12">Out</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-14">Between</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...dependencyMetricsPerClass]
                      .sort((a, b) => b.betweenness - a.betweenness || (b.inDegree + b.outDegree) - (a.inDegree + a.outDegree))
                      .map((row, i) => (
                        <tr key={row.classId} className={i % 2 === 0 ? 'bg-white dark:bg-gray-800/50' : 'bg-gray-50/80 dark:bg-gray-700/30'}>
                          <td className="py-1 px-2 truncate max-w-[120px] text-gray-800 dark:text-gray-200 font-medium" title={row.className}>
                            {row.className}
                          </td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{row.inDegree}</td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{row.outDegree}</td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">
                            {row.betweenness.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* #610: Cognitive complexity per class (for humans + AI digest) */}
          {cognitiveComplexityPerClass.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                <Brain className="w-3 h-3" />
                Cognitive complexity per class
              </div>
              <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
                Props + weighted outgoing refs (anyOf/oneOf count double) + conditional-schema cyclomatic (#612). Higher scores mean more to hold in mind when reading the model.
              </p>
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 overflow-hidden max-h-48 overflow-y-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="sticky top-0 bg-gray-50 dark:bg-gray-700/80 text-left">
                    <tr>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400">Class</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-14">Score</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-12">Props</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-12">Refs</th>
                      <th className="py-1.5 px-2 font-medium text-gray-600 dark:text-gray-400 text-right w-10" title="Cyclomatic-style if/then/else load (#612)">
                        If
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...cognitiveComplexityPerClass]
                      .sort((a, b) => b.score - a.score || a.className.localeCompare(b.className))
                      .map((row, i) => (
                        <tr key={row.classId} className={i % 2 === 0 ? 'bg-white dark:bg-gray-800/50' : 'bg-gray-50/80 dark:bg-gray-700/30'}>
                          <td className="py-1 px-2 truncate max-w-[100px] text-gray-800 dark:text-gray-200 font-medium" title={row.className}>
                            {row.className}
                          </td>
                          <td className="py-1 px-2 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200">{row.score}</td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{row.propertyContribution}</td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{row.referenceContribution}</td>
                          <td className="py-1 px-2 text-right tabular-nums text-gray-600 dark:text-gray-400">{row.conditionalSchemaCyclomaticContribution}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

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

          {canvasLayoutAnalysis && canvasLayoutAnalysis.classCount >= 2 && onPreviewLayoutDirection && (
            <CanvasLayoutIntelligenceSection
              analysis={canvasLayoutAnalysis}
              tenantId={tenantId}
              projectId={projectId}
              versionId={versionId}
              onPreviewLayoutDirection={onPreviewLayoutDirection}
            />
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
