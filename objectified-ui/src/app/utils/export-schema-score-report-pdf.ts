/**
 * PDF export for schema metrics (complexity, documentation, naming) and timeline history (#252).
 */

import { jsPDF } from 'jspdf';
import type { LayoutQualityResult } from '@/app/utils/layout-quality';
import type { SchemaMetricsResult } from '@/app/utils/schema-metrics';
import type { CanvasSuggestion } from '@/app/utils/canvas-suggestions';

const LIST_CAP = 45;

/** Safe filename segment for downloads. */
export function sanitizeFilenameSegment(raw: string): string {
  const s = raw.replace(/[^\w\-+.]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  return s.slice(0, 96) || 'report';
}

type PdfContext = {
  pdf: jsPDF;
  margin: number;
  pageW: number;
  pageH: number;
  y: number;
};

function createContext(): PdfContext {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4' });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  return {
    pdf,
    margin: 14,
    pageW,
    pageH,
    y: 14,
  };
}

function ensureSpace(ctx: PdfContext, needMm: number): void {
  if (ctx.y + needMm <= ctx.pageH - ctx.margin) return;
  ctx.pdf.addPage();
  ctx.y = ctx.margin;
}

function writeLines(ctx: PdfContext, text: string, fontSize: number): void {
  ctx.pdf.setFontSize(fontSize);
  const maxW = ctx.pageW - 2 * ctx.margin;
  const lines = ctx.pdf.splitTextToSize(text, maxW);
  const lh = fontSize * 0.45;
  for (const line of lines) {
    ensureSpace(ctx, lh + 0.5);
    ctx.pdf.text(line, ctx.margin, ctx.y);
    ctx.y += lh;
  }
}

function section(ctx: PdfContext, title: string): void {
  ctx.y += 2;
  ensureSpace(ctx, 9);
  ctx.pdf.setFont('helvetica', 'bold');
  writeLines(ctx, title, 12);
  ctx.pdf.setFont('helvetica', 'normal');
}

function paragraph(ctx: PdfContext, text: string): void {
  writeLines(ctx, text, 10);
}

function addMetricsBody(
  ctx: PdfContext,
  metrics: SchemaMetricsResult,
  layoutQuality: LayoutQualityResult | null | undefined,
  suggestions: CanvasSuggestion[] | undefined
): void {
  const m = metrics;
  section(ctx, 'Summary');
  paragraph(
    ctx,
    [
      `Classes: ${m.classCount}`,
      `Properties (total): ${m.totalProperties}`,
      `Average properties per class: ${m.averagePropertiesPerClass.toFixed(1)}`,
      `Relationships: ${m.relationshipCount}`,
      `Schema complexity: ${m.complexityScore}/100 (${m.complexityLabel})`,
      `Documentation coverage: ${m.documentationCompletionPercentage}%`,
      `Naming compliance: ${m.namingCompliance.compliancePercentage}%`,
    ].join('\n')
  );

  section(ctx, 'Complexity breakdown');
  const rows: string[] = ['Factor | Value | Weight | Points'];
  for (const row of m.complexityBreakdown) {
    rows.push(`${row.label} | ${row.value} | ${row.weight} | ${row.contribution.toFixed(1)}`);
  }
  paragraph(ctx, rows.join('\n'));

  section(ctx, 'Documentation gaps');
  if (m.classesMissingDocumentation.length === 0 && m.propertiesMissingDocumentation.length === 0) {
    paragraph(ctx, 'All classes and properties have descriptions.');
  } else {
    const cls = m.classesMissingDocumentation.slice(0, LIST_CAP);
    const props = m.propertiesMissingDocumentation.slice(0, LIST_CAP);
    const parts: string[] = [];
    if (cls.length) {
      parts.push(`Classes missing description (${m.classesMissingDocumentation.length}):`);
      parts.push(cls.join(', '));
      if (m.classesMissingDocumentation.length > LIST_CAP) {
        parts.push(`+ ${m.classesMissingDocumentation.length - LIST_CAP} more (see Studio for full list)`);
      }
    }
    if (props.length) {
      parts.push(
        `Properties missing description (${m.propertiesMissingDocumentation.length}), sample:`
      );
      parts.push(
        props.map((p) => `${p.className} › ${p.propertyName}`).join('\n')
      );
      if (m.propertiesMissingDocumentation.length > LIST_CAP) {
        parts.push(`+ ${m.propertiesMissingDocumentation.length - LIST_CAP} more in Studio`);
      }
    }
    paragraph(ctx, parts.join('\n'));
  }

  section(ctx, 'Naming');
  const nc = m.namingCompliance;
  paragraph(
    ctx,
    [
      `Classes PascalCase: ${nc.classes.pascal}/${nc.classes.total}`,
      `Properties camelCase: ${nc.properties.camel}/${nc.properties.total}`,
      `Property naming: camelCase ${nc.properties.camel}, snake_case ${nc.properties.snake}, PascalCase ${nc.properties.pascal}${nc.properties.other > 0 ? `, other ${nc.properties.other}` : ''}`,
    ].join('\n')
  );
  if (nc.classesNonPascal.length || nc.propertiesNonCamel.length) {
    const cnp = nc.classesNonPascal.slice(0, LIST_CAP);
    const pnc = nc.propertiesNonCamel.slice(0, LIST_CAP);
    const lines: string[] = [];
    if (cnp.length) {
      lines.push(`Classes not PascalCase (${nc.classesNonPascal.length}): ${cnp.join(', ')}`);
      if (nc.classesNonPascal.length > LIST_CAP) {
        lines.push(`+ ${nc.classesNonPascal.length - LIST_CAP} more in Studio`);
      }
    }
    if (pnc.length) {
      lines.push(
        `Properties not camelCase (${nc.propertiesNonCamel.length}): ${pnc.map((p) => `${p.className} › ${p.propertyName}`).join('; ')}`
      );
      if (nc.propertiesNonCamel.length > LIST_CAP) {
        lines.push(`+ ${nc.propertiesNonCamel.length - LIST_CAP} more in Studio`);
      }
    }
    paragraph(ctx, lines.join('\n'));
  }

  section(ctx, 'Graph structure');
  paragraph(
    ctx,
    [
      `Most connected (hubs): ${m.hubNames.length ? m.hubNames.slice(0, 20).join(', ') : '—'}${m.hubNames.length > 20 ? ` (+${m.hubNames.length - 20} more)` : ''}`,
      `Isolated classes: ${m.isolatedNames.length ? m.isolatedNames.slice(0, 20).join(', ') : '—'}${m.isolatedNames.length > 20 ? ` (+${m.isolatedNames.length - 20} more)` : ''}`,
      `Deepest dependency chain: ${m.deepestChainLength} step(s)`,
      `Circular dependencies: ${m.circularDependencyCount}${m.circularSampleNames.length ? ` (e.g. ${m.circularSampleNames.slice(0, 5).join(', ')})` : ''}`,
    ].join('\n')
  );

  if (m.dependencyMetricsPerClass.length > 0) {
    section(ctx, 'Dependency metrics per class');
    const sorted = [...m.dependencyMetricsPerClass].sort(
      (a, b) => b.betweenness - a.betweenness || b.inDegree + b.outDegree - (a.inDegree + a.outDegree)
    );
    const cap = Math.min(sorted.length, 60);
    const hdr = 'Class | In | Out | Betweenness';
    const body = sorted
      .slice(0, cap)
      .map((r) => `${r.className} | ${r.inDegree} | ${r.outDegree} | ${r.betweenness.toFixed(2)}`);
    paragraph(ctx, [hdr, ...body].join('\n'));
    if (sorted.length > cap) {
      paragraph(ctx, `+ ${sorted.length - cap} more rows in Studio.`);
    }
  }

  if (layoutQuality) {
    section(ctx, 'Layout quality');
    paragraph(
      ctx,
      [
        `Overall: ${layoutQuality.overallScore}/100`,
        `Edge crossings: ${layoutQuality.edgeCrossingCount}`,
        `Spacing uniformity: ${layoutQuality.nodeSpacingUniformityScore}`,
        `Symmetry: ${layoutQuality.layoutSymmetryScore}`,
        `Visual balance: ${layoutQuality.visualBalanceScore}`,
      ].join('\n')
    );
  }

  if (suggestions && suggestions.length > 0) {
    section(ctx, 'Suggestions');
    const chunks = suggestions.map((s) => `• ${s.title}: ${s.description}${s.detail ? ` (${s.detail})` : ''}`);
    paragraph(ctx, chunks.join('\n'));
  }
}

export interface SchemaScoreReportPdfOptions {
  metrics: SchemaMetricsResult;
  layoutQuality?: LayoutQualityResult | null;
  suggestions?: CanvasSuggestion[];
  projectName?: string;
  versionLabel?: string;
}

/** Builds a downloadable PDF of the current schema metrics panel content. */
export function downloadSchemaScoreReportPdf(options: SchemaScoreReportPdfOptions): void {
  const { metrics, layoutQuality, suggestions, projectName, versionLabel } = options;
  const ctx = createContext();
  const { pdf } = ctx;

  pdf.setFont('helvetica', 'bold');
  writeLines(ctx, 'Schema score report', 16);
  pdf.setFont('helvetica', 'normal');

  const meta: string[] = [];
  if (projectName) meta.push(`Project: ${projectName}`);
  if (versionLabel) meta.push(`Version: ${versionLabel}`);
  meta.push(`Generated: ${new Date().toLocaleString()}`);
  paragraph(ctx, meta.join('\n'));

  addMetricsBody(ctx, metrics, layoutQuality ?? null, suggestions);

  pdf.setFontSize(8);
  pdf.setTextColor(100, 100, 100);
  pdf.text('Generated by Objectified Studio', ctx.margin, ctx.pageH - 10);

  const proj = sanitizeFilenameSegment(projectName || 'schema');
  const ver = sanitizeFilenameSegment(versionLabel || 'version');
  pdf.save(`schema-score-report-${proj}-${ver}.pdf`);
}

export interface SchemaTimelineScoreRow {
  versionLabel: string;
  createdAt: string | null;
  metrics: SchemaMetricsResult | null;
  loadError?: string;
}

export interface SchemaTimelineScoreReportPdfOptions {
  rows: SchemaTimelineScoreRow[];
  projectName?: string;
}

/** PDF table of complexity and size metrics across schema versions (timeline). */
export function downloadSchemaTimelineScoreReportPdf(options: SchemaTimelineScoreReportPdfOptions): void {
  const { rows, projectName } = options;
  const ctx = createContext();
  const { pdf } = ctx;

  pdf.setFont('helvetica', 'bold');
  writeLines(ctx, 'Schema score history', 16);
  pdf.setFont('helvetica', 'normal');

  const meta: string[] = [];
  if (projectName) meta.push(`Project: ${projectName}`);
  meta.push(`Generated: ${new Date().toLocaleString()}`);
  meta.push('Metrics are listed in version order (oldest -> newest).');
  paragraph(ctx, meta.join('\n'));

  section(ctx, 'Versions');
  const lines: string[] = [
    'Version | Date | Classes | Rels | Complexity | Band | Notes',
  ];
  for (const r of rows) {
    const date =
      r.createdAt && Number.isFinite(Date.parse(r.createdAt))
        ? new Date(r.createdAt).toLocaleDateString()
        : '—';
    if (r.loadError) {
      lines.push(`${r.versionLabel} | ${date} | — | — | — | — | ${r.loadError}`);
      continue;
    }
    if (!r.metrics) {
      lines.push(`${r.versionLabel} | ${date} | — | — | — | — | No metrics`);
      continue;
    }
    const m = r.metrics;
    lines.push(
      `${r.versionLabel} | ${date} | ${m.classCount} | ${m.relationshipCount} | ${m.complexityScore} | ${m.complexityLabel} |`
    );
  }
  paragraph(ctx, lines.join('\n'));

  pdf.setFontSize(8);
  pdf.setTextColor(100, 100, 100);
  pdf.text('Generated by Objectified Studio', ctx.margin, ctx.pageH - 10);

  const proj = sanitizeFilenameSegment(projectName || 'schema');
  pdf.save(`schema-score-history-${proj}.pdf`);
}
