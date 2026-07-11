/**
 * Pure helpers for GOV-2.4 violation display: enrich findings with rule metadata and group by rule.
 */

import type { LintRuleCatalog, LintRuleCatalogEntry } from './lint-rule-catalog';
import { buildLintRuleDocsHref } from './lint-rule-catalog';
import type { VersionLintFinding } from './version-lint-report';

export interface LintViolationRuleMeta {
  rationale: string;
  docsHref: string | null;
}

export interface EnrichedLintViolation extends VersionLintFinding {
  guideName: string | null;
  rationale: string;
  docsHref: string | null;
}

export interface LintViolationRuleGroup {
  ruleId: string;
  guideName: string | null;
  rationale: string;
  docsHref: string | null;
  findings: EnrichedLintViolation[];
}

/**
 * Resolve display metadata for one finding's rule id.
 *
 * Built-in rules use the GOV-1.2 catalog; custom rules use the guide YAML description; unknown
 * rules fall back to the finding message with no docs link.
 */
export function resolveLintViolationRuleMeta(
  ruleId: string,
  catalog: Map<string, LintRuleCatalogEntry>,
  customDescriptions: Map<string, string>,
  docsPage: string,
  fallbackMessage?: string,
): LintViolationRuleMeta {
  const builtIn = catalog.get(ruleId);
  if (builtIn) {
    return {
      rationale: builtIn.rationale || fallbackMessage || ruleId,
      docsHref: buildLintRuleDocsHref(docsPage, builtIn.docsAnchor),
    };
  }
  const custom = customDescriptions.get(ruleId);
  if (custom) {
    return { rationale: custom, docsHref: null };
  }
  return {
    rationale: fallbackMessage?.trim() || ruleId,
    docsHref: null,
  };
}

/** Attach guide name + rule metadata to each finding for rendering. */
export function enrichLintViolations(
  findings: VersionLintFinding[],
  options: {
    guideName: string | null;
    catalog: LintRuleCatalog;
    customDescriptions?: Map<string, string>;
  },
): EnrichedLintViolation[] {
  const lookup = new Map(options.catalog.rules.map((rule) => [rule.ruleId, rule]));
  const custom = options.customDescriptions ?? new Map<string, string>();
  return findings.map((finding) => {
    const meta = resolveLintViolationRuleMeta(
      finding.rule,
      lookup,
      custom,
      options.catalog.docsPage,
      finding.message,
    );
    return {
      ...finding,
      guideName: options.guideName,
      rationale: meta.rationale,
      docsHref: meta.docsHref,
    };
  });
}

/** Cluster findings that share the same rule id (stable order: first occurrence wins). */
export function groupLintViolationsByRule(
  findings: EnrichedLintViolation[],
): LintViolationRuleGroup[] {
  const groups = new Map<string, LintViolationRuleGroup>();
  for (const finding of findings) {
    let group = groups.get(finding.rule);
    if (!group) {
      group = {
        ruleId: finding.rule,
        guideName: finding.guideName,
        rationale: finding.rationale,
        docsHref: finding.docsHref,
        findings: [],
      };
      groups.set(finding.rule, group);
    }
    group.findings.push(finding);
  }
  return [...groups.values()];
}
