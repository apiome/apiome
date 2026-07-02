/**
 * PDF export for generated migration guides (#747) — plain-text rendering of Markdown body.
 */

import { jsPDF } from 'jspdf';
import { sanitizeFilenameSegment } from '@/app/utils/filename-utils';

type PdfCtx = {
  pdf: jsPDF;
  margin: number;
  pageW: number;
  pageH: number;
  y: number;
};

function createCtx(): PdfCtx {
  const pdf = new jsPDF({ unit: 'mm', format: 'a4' });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  return { pdf, margin: 14, pageW, pageH, y: 14 };
}

function ensureSpace(ctx: PdfCtx, needMm: number): void {
  if (ctx.y + needMm <= ctx.pageH - ctx.margin) return;
  ctx.pdf.addPage();
  ctx.y = ctx.margin;
}

function writeLines(ctx: PdfCtx, text: string, fontSize: number): void {
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

/** Download a printable PDF of the migration guide (same content as Markdown export). */
export function downloadMigrationGuidePdf(params: {
  body: string;
  projectName: string;
  baseVersionLabel: string;
  targetVersionLabel: string;
}): void {
  const { body, projectName, baseVersionLabel, targetVersionLabel } = params;
  const ctx = createCtx();
  ctx.pdf.setProperties({
    title: `Migration guide ${baseVersionLabel} → ${targetVersionLabel}`,
    subject: 'Apiome migration guide',
  });
  ctx.pdf.setFont('helvetica', 'bold');
  writeLines(ctx, `Migration guide — ${projectName}`, 14);
  ctx.pdf.setFont('helvetica', 'normal');
  ctx.y += 1;
  writeLines(ctx, `${baseVersionLabel} → ${targetVersionLabel}`, 11);
  ctx.y += 2;
  writeLines(ctx, `Exported ${new Date().toISOString()}`, 9);
  ctx.y += 3;
  ctx.pdf.setFont('courier', 'normal');
  writeLines(ctx, body.trim() || '(empty)', 8);
  const base = sanitizeFilenameSegment(projectName);
  const vb = sanitizeFilenameSegment(baseVersionLabel);
  const vt = sanitizeFilenameSegment(targetVersionLabel);
  const filename = `migration-guide-${base}-${vb}-to-${vt}.pdf`;
  ctx.pdf.save(filename);
}
