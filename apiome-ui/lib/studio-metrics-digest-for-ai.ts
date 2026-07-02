/**
 * Compact digest of Schema Metrics for Ollama improvement-suggestions (#253).
 * Caps list sizes so large canvases stay within prompt budget.
 */

import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';

const MAX_NAMES = 48;
const MAX_PROP_ROWS = 60;
const MAX_DEP_ROWS = 24;
const MAX_COGNITIVE_ROWS = 40;

function take<T>(arr: T[], n: number): T[] {
  return arr.length <= n ? arr : arr.slice(0, n);
}

/**
 * Human-readable block appended to the model system prompt.
 */
export function buildStudioMetricsDigestForAi(
  metrics: SchemaMetricsResult,
  /** Current Studio overall schema quality score (0–100); helps the model estimate per-fix deltas (#255). */
  overallQualityScore?: number | null
): string {
  const lines: string[] = [];
  lines.push('## Live schema metrics (Studio canvas)');
  lines.push(`- Classes: ${metrics.classCount}`);
  lines.push(`- Total properties: ${metrics.totalProperties}`);
  lines.push(`- Avg properties per class: ${metrics.averagePropertiesPerClass.toFixed(1)}`);
  lines.push(`- Relationship edges: ${metrics.relationshipCount}`);
  lines.push(`- Complexity score: ${metrics.complexityScore} (${metrics.complexityLabel})`);
  lines.push(`- Documentation completion: ${metrics.documentationCompletionPercentage}%`);
  lines.push(`- Naming compliance (PascalCase classes + camelCase props): ${metrics.namingCompliance.compliancePercentage}%`);
  lines.push(`- Circular dependency groups: ${metrics.circularDependencyCount}`);
  lines.push(`- Deepest dependency chain length: ${metrics.deepestChainLength}`);
  lines.push(
    `- Conditional schema cyclomatic (#612): ${metrics.conditionalSchemaCyclomaticTotal} (if/then/else decision points summed across classes and property inline schemas)`,
  );
  const dg = metrics.dependencyGraphComplexity;
  lines.push(
    `- Dependency graph complexity (#611): ${dg.score}/100 (${dg.scoreLabel}) — ${dg.edgeCount} dependency-only edges, deepest chain ${dg.deepestChainSteps} step(s), ${dg.circularGroupCount} cycle group(s) on refs/composition graph`,
  );
  const mi = metrics.maintainabilityIndex;
  lines.push(
    `- Maintainability index (#613): ${mi.score}/100 (${mi.scoreLabel}) — composite from documentation, naming, inverted schema/dependency complexity, mean cognitive load per class, and class-size pressure`,
  );
  const td = metrics.technicalDebtMetrics;
  lines.push(
    `- Technical debt (#614): ${td.debtScore}/100 (${td.scoreLabel} debt) — weighted documentation/naming gaps, schema and dependency-graph load, conditional branching, cycles, chain depth, mean cognitive load, isolated classes, wide-class pressure`,
  );
  if (typeof overallQualityScore === 'number' && Number.isFinite(overallQualityScore)) {
    lines.push(
      `- Overall schema quality score (0–100 composite: docs, naming, structural load, layout when available): ${Math.min(100, Math.max(0, Math.round(overallQualityScore)))}`,
    );
  }

  if (metrics.hubNames.length) {
    lines.push(`- Hub classes (sample): ${take(metrics.hubNames, MAX_NAMES).join(', ')}${metrics.hubNames.length > MAX_NAMES ? ' …' : ''}`);
  }
  if (metrics.isolatedNames.length) {
    lines.push(`- Isolated classes (sample): ${take(metrics.isolatedNames, MAX_NAMES).join(', ')}${metrics.isolatedNames.length > MAX_NAMES ? ' …' : ''}`);
  }
  if (metrics.circularSampleNames.length) {
    lines.push(
      `- Classes in cycles (sample): ${take(metrics.circularSampleNames, MAX_NAMES).join(', ')}${metrics.circularSampleNames.length > MAX_NAMES ? ' …' : ''}`,
    );
  }

  if (metrics.classesMissingDocumentation.length) {
    const c = take(metrics.classesMissingDocumentation, MAX_NAMES);
    lines.push(
      `- Classes missing description (${metrics.classesMissingDocumentation.length}): ${c.join(', ')}${metrics.classesMissingDocumentation.length > MAX_NAMES ? ' …' : ''}`,
    );
  }
  if (metrics.propertiesMissingDocumentation.length) {
    lines.push('- Properties missing description (sample):');
    for (const row of take(metrics.propertiesMissingDocumentation, MAX_PROP_ROWS)) {
      lines.push(`  - ${row.className}.${row.propertyName}`);
    }
    if (metrics.propertiesMissingDocumentation.length > MAX_PROP_ROWS) {
      lines.push(`  … and ${metrics.propertiesMissingDocumentation.length - MAX_PROP_ROWS} more`);
    }
  }

  if (metrics.namingCompliance.classesNonPascal.length) {
    const c = take(metrics.namingCompliance.classesNonPascal, MAX_NAMES);
    lines.push(
      `- Class names not PascalCase (${metrics.namingCompliance.classesNonPascal.length}): ${c.join(', ')}${metrics.namingCompliance.classesNonPascal.length > MAX_NAMES ? ' …' : ''}`,
    );
  }
  if (metrics.namingCompliance.propertiesNonCamel.length) {
    lines.push('- Properties not camelCase (sample):');
    for (const row of take(metrics.namingCompliance.propertiesNonCamel, MAX_PROP_ROWS)) {
      lines.push(`  - ${row.className}.${row.propertyName}`);
    }
    if (metrics.namingCompliance.propertiesNonCamel.length > MAX_PROP_ROWS) {
      lines.push(`  … and ${metrics.namingCompliance.propertiesNonCamel.length - MAX_PROP_ROWS} more`);
    }
  }

  if (metrics.dependencyMetricsPerClass?.length) {
    const sorted = [...metrics.dependencyMetricsPerClass].sort((a, b) => b.outDegree + b.inDegree - (a.outDegree + a.inDegree));
    lines.push('- Heaviest classes by degree (sample):');
    for (const row of take(sorted, MAX_DEP_ROWS)) {
      lines.push(`  - ${row.className}: in ${row.inDegree}, out ${row.outDegree}, betweenness ${row.betweenness.toFixed(3)}`);
    }
  }

  if (metrics.cognitiveComplexityPerClass?.length) {
    const sorted = [...metrics.cognitiveComplexityPerClass].sort((a, b) => b.score - a.score || a.className.localeCompare(b.className));
    lines.push(
      '- Per-class cognitive complexity (#610 + #612; props + weighted refs + conditional cyclomatic; higher = harder to reason about):',
    );
    for (const row of take(sorted, MAX_COGNITIVE_ROWS)) {
      lines.push(
        `  - ${row.className}: ${row.score} (props +${row.propertyContribution}, refs +${row.referenceContribution}, conditionals +${row.conditionalSchemaCyclomaticContribution})`,
      );
    }
    if (sorted.length > MAX_COGNITIVE_ROWS) {
      lines.push(`  … and ${sorted.length - MAX_COGNITIVE_ROWS} more classes`);
    }
  }

  lines.push('');
  lines.push('Use these numbers and names to make suggestions concrete (quote class/property names when relevant).');
  return lines.join('\n');
}
