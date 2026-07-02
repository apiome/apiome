/**
 * Deterministic migration-guide Markdown from schema diff (#747).
 * Companion to breaking-changes doc (#746) and compatibility classification (#506).
 */

import {
  BREAKING_CHANGES_DOC_TEMPLATE_ID,
  BREAKING_CHANGES_DOC_TEMPLATE_VERSION,
  buildBreakingChangesBullets,
} from './breaking-changes-doc';
import { compareSchemas, type DiffSummary } from './schema-diff';

/** Bump when output shape or step narrative changes (determinism contract). */
export const MIGRATION_GUIDE_DOC_TEMPLATE_ID = 'apiome-migration-guide' as const;
export const MIGRATION_GUIDE_DOC_TEMPLATE_VERSION = 1;

export interface GenerateMigrationGuideMarkdownOptions {
  baseLabel?: string;
  targetLabel?: string;
  baseRevisionId?: string;
  targetRevisionId?: string;
  /** Lines from revision changelogs — e.g. `breaking:` bullets (#502). */
  breakingHintsFromChangelog?: string[];
}

/**
 * Ordered migration steps for each **breaking** diff item, plus revision-pair metadata.
 * Embeds references to the breaking-changes doc template (#746).
 */
export function generateMigrationGuideMarkdownFromSummary(
  summary: DiffSummary,
  options?: GenerateMigrationGuideMarkdownOptions
): string {
  const bullets = buildBreakingChangesBullets(summary).filter((b) => b.category === 'breaking');
  const base = options?.baseLabel ?? 'base';
  const target = options?.targetLabel ?? 'target';
  const baseId = options?.baseRevisionId?.trim() || '—';
  const targetId = options?.targetRevisionId?.trim() || '—';
  const hints = options?.breakingHintsFromChangelog?.filter((h) => h.trim()) ?? [];

  const lines: string[] = [
    `<!-- ${MIGRATION_GUIDE_DOC_TEMPLATE_ID} v${MIGRATION_GUIDE_DOC_TEMPLATE_VERSION} -->`,
    '',
    `# Migration guide (generated)`,
    '',
    `**Range:** ${base} → ${target}`,
    '',
    `**Revision pair:** \`${baseId}\` → \`${targetId}\``,
    '',
    `**Guide template:** \`${MIGRATION_GUIDE_DOC_TEMPLATE_ID}\` v${MIGRATION_GUIDE_DOC_TEMPLATE_VERSION}`,
    '',
    `**Companion (breaking changes doc, #746):** Use the **Breaking doc** tab for the same compare. It uses template \`${BREAKING_CHANGES_DOC_TEMPLATE_ID}\` v${BREAKING_CHANGES_DOC_TEMPLATE_VERSION} (**Breaking** / **Additions** / **Other**). Keep this guide aligned with that output for this revision pair.`,
    '',
    `**Compatibility (#506):** Use the backward-compatibility report for this pair (merge preview or REST) when you need a safe / breaking / unknown gate.`,
    '',
    `## Migration steps`,
    '',
  ];

  if (bullets.length === 0) {
    lines.push(
      '_No breaking changes were detected in the structural diff._ If you still expect runtime or data issues, validate with integration tests and the compatibility report.',
      ''
    );
  } else {
    let step = 1;
    for (const b of bullets) {
      lines.push(`### Step ${step} — \`${b.stableId}\``, '');
      lines.push(`- **Change:** ${b.text}`, '');
      lines.push('**Suggested actions:**', '');
      lines.push(
        '1. Find API clients, SDKs, and server-side mappers that reference this schema path.',
        '2. Update request/response models and validation to match the target revision.',
        '3. Regenerate OpenAPI-derived artifacts and run contract tests.',
        '4. For persisted data, plan backfills or transforms if identifiers or required fields changed.',
        ''
      );
      step += 1;
    }
  }

  if (hints.length > 0) {
    lines.push(`## Author notes (from version changelog)`, '');
    lines.push(
      '_From `breaking:` lines in revision notes (#502); edit as needed._',
      ''
    );
    const seen = new Set<string>();
    for (const h of hints) {
      const t = h.trim();
      if (seen.has(t)) continue;
      seen.add(t);
      lines.push(`- ${t}`, '');
    }
  }

  return lines.join('\n').replace(/\n+$/, '\n');
}

export function generateMigrationGuideMarkdown(
  spec1: unknown,
  spec2: unknown,
  options?: GenerateMigrationGuideMarkdownOptions
): string {
  const summary = compareSchemas(spec1, spec2);
  return generateMigrationGuideMarkdownFromSummary(summary, options);
}
