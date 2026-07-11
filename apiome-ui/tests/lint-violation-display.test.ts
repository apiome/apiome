import {
  buildLintRuleDocsHref,
  customRuleDescriptionsFromYaml,
  lintRuleCatalogFromPayload,
} from '@/app/utils/lint-rule-catalog';
import {
  enrichLintViolations,
  groupLintViolationsByRule,
  resolveLintViolationRuleMeta,
} from '@/app/utils/lint-violation-display';
import {
  persistLintViolationDisplayPreferences,
  readLintViolationDisplayPreferences,
} from '@/app/utils/lint-violation-display-preferences';

describe('lint-rule-catalog', () => {
  it('builds a GitHub docs href from page + anchor', () => {
    expect(buildLintRuleDocsHref('docs/guide/lint-rules.md', 'naming-schema-pascal-case')).toBe(
      'https://github.com/apiome/apiome/blob/main/docs/guide/lint-rules.md#naming-schema-pascal-case',
    );
  });

  it('parses catalog payloads', () => {
    const catalog = lintRuleCatalogFromPayload({
      rules: [
        {
          ruleId: 'documentation.info-missing-description',
          pack: 'openapi',
          category: 'documentation',
          defaultSeverity: 'info',
          rationale: 'Info should have a description.',
          docsAnchor: 'documentation-info-missing-description',
        },
      ],
      count: 1,
      docsPage: 'docs/guide/lint-rules.md',
    });
    expect(catalog?.rules[0]?.ruleId).toBe('documentation.info-missing-description');
  });

  it('extracts custom rule descriptions from YAML', () => {
    const map = customRuleDescriptionsFromYaml(`
rules:
  team.no-plain-text-passwords:
    description: Password fields must not be plain strings.
    given: "$"
    then:
      function: pattern
`);
    expect(map.get('team.no-plain-text-passwords')).toContain('plain strings');
  });
});

describe('lint-violation-display', () => {
  const catalog = {
    rules: [
      {
        ruleId: 'naming.schema-pascal-case',
        pack: 'openapi',
        category: 'naming',
        defaultSeverity: 'warning',
        rationale: 'Schemas should be PascalCase.',
        docsAnchor: 'naming-schema-pascal-case',
      },
    ],
    count: 1,
    docsPage: 'docs/guide/lint-rules.md',
  };

  it('resolves built-in rule metadata', () => {
    const lookup = new Map(catalog.rules.map((r) => [r.ruleId, r]));
    const meta = resolveLintViolationRuleMeta(
      'naming.schema-pascal-case',
      lookup,
      new Map(),
      catalog.docsPage,
    );
    expect(meta.rationale).toContain('PascalCase');
    expect(meta.docsHref).toContain('naming-schema-pascal-case');
  });

  it('uses custom description when rule is not in catalog', () => {
    const meta = resolveLintViolationRuleMeta(
      'custom.team-rule',
      new Map(),
      new Map([['custom.team-rule', 'Team-specific check.']]),
      catalog.docsPage,
    );
    expect(meta.rationale).toBe('Team-specific check.');
    expect(meta.docsHref).toBeNull();
  });

  it('enriches findings with guide name and rationale', () => {
    const enriched = enrichLintViolations(
      [
        {
          id: '1',
          path: 'components.schemas.User',
          category: 'naming',
          rule: 'naming.schema-pascal-case',
          severity: 'warning',
          message: 'Bad name',
        },
      ],
      { guideName: 'Payments Guide', catalog, customDescriptions: new Map() },
    );
    expect(enriched[0].guideName).toBe('Payments Guide');
    expect(enriched[0].rationale).toContain('PascalCase');
  });

  it('groups enriched findings by rule id', () => {
    const enriched = enrichLintViolations(
      [
        {
          id: '1',
          path: 'a',
          category: 'naming',
          rule: 'naming.schema-pascal-case',
          severity: 'warning',
          message: 'm1',
        },
        {
          id: '2',
          path: 'b',
          category: 'naming',
          rule: 'naming.schema-pascal-case',
          severity: 'warning',
          message: 'm2',
        },
      ],
      { guideName: 'Guide', catalog, customDescriptions: new Map() },
    );
    const groups = groupLintViolationsByRule(enriched);
    expect(groups).toHaveLength(1);
    expect(groups[0].findings).toHaveLength(2);
  });
});

describe('lint-violation-display-preferences', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('round-trips group-by-rule per view', () => {
    persistLintViolationDisplayPreferences('studio-lint', { groupByRule: true });
    persistLintViolationDisplayPreferences('catalog-lint', { groupByRule: false });
    expect(readLintViolationDisplayPreferences('studio-lint').groupByRule).toBe(true);
    expect(readLintViolationDisplayPreferences('catalog-lint').groupByRule).toBe(false);
    expect(readLintViolationDisplayPreferences('import-report').groupByRule).toBe(false);
  });
});
