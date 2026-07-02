import { jest, describe, it, expect, beforeEach } from '@jest/globals';
import {
  computeMaintainabilityIndexReport,
  computeTechnicalDebtMetricsReport,
  type SchemaMetricsResult,
} from '@/app/utils/schema-metrics';

// ── jsPDF mock ────────────────────────────────────────────────────────────────

const mockSave = jest.fn();
const mockText = jest.fn();
const mockSetFont = jest.fn();
const mockSetFontSize = jest.fn();
const mockSetTextColor = jest.fn();
const mockAddPage = jest.fn();
const mockSplitTextToSize = jest.fn((text: string) => (text as string).split('\n'));

const mockPdfInstance = {
  save: mockSave,
  text: mockText,
  setFont: mockSetFont,
  setFontSize: mockSetFontSize,
  setTextColor: mockSetTextColor,
  addPage: mockAddPage,
  splitTextToSize: mockSplitTextToSize,
  internal: {
    pageSize: {
      getWidth: () => 210,
      getHeight: () => 297,
    },
  },
};

jest.mock('jspdf', () => ({
  jsPDF: jest.fn(() => mockPdfInstance),
}));

// ── Imports (after mock) ───────────────────────────────────────────────────────

import {
  sanitizeFilenameSegment,
  downloadSchemaScoreReportPdf,
  downloadSchemaTimelineScoreReportPdf,
} from '@/app/utils/export-schema-score-report-pdf';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeMinimalMetrics(overrides: Partial<SchemaMetricsResult> = {}): SchemaMetricsResult {
  const merged: SchemaMetricsResult = {
    classCount: 3,
    totalProperties: 9,
    averagePropertiesPerClass: 3,
    relationshipCount: 2,
    hubClassIds: [],
    hubNames: [],
    isolatedClassIds: [],
    isolatedNames: [],
    deepestChainLength: 2,
    circularDependencyCount: 0,
    circularSampleNames: [],
    circularDependencyNodeIds: [],
    complexityScore: 30,
    complexityLabel: 'Low',
    complexityBreakdown: [
      { label: 'Class count', value: 3, weight: 10, contribution: 3 },
    ],
    conditionalSchemaCyclomaticTotal: 0,
    documentationCompletionPercentage: 100,
    classesMissingDocumentation: [],
    propertiesMissingDocumentation: [],
    namingCompliance: {
      classes: { pascal: 3, camel: 0, snake: 0, other: 0, total: 3 },
      properties: { pascal: 0, camel: 9, snake: 0, other: 0, total: 9 },
      compliancePercentage: 100,
      classesNonPascal: [],
      propertiesNonCamel: [],
    },
    dependencyMetricsPerClass: [],
    cognitiveComplexityPerClass: [],
    dependencyGraphComplexity: {
      edgeCount: 0,
      deepestChainSteps: 0,
      circularGroupCount: 0,
      score: 0,
      scoreLabel: 'Low',
      breakdown: [
        { label: 'Dependency edges', value: 0, weight: 1.2, contribution: 0 },
        { label: 'Deepest ref chain (steps)', value: 0, weight: 4, contribution: 0 },
        { label: 'Circular groups (deps)', value: 0, weight: 6, contribution: 0 },
      ],
    },
    ...overrides,
  };
  merged.maintainabilityIndex =
    overrides.maintainabilityIndex ??
    computeMaintainabilityIndexReport({
      documentationCompletionPercentage: merged.documentationCompletionPercentage,
      namingCompliancePercentage: merged.namingCompliance.compliancePercentage,
      complexityScore: merged.complexityScore,
      dependencyGraphScore: merged.dependencyGraphComplexity.score,
      cognitiveComplexityPerClass: merged.cognitiveComplexityPerClass,
      averagePropertiesPerClass: merged.averagePropertiesPerClass,
      classCount: merged.classCount,
    });
  merged.technicalDebtMetrics =
    overrides.technicalDebtMetrics ??
    computeTechnicalDebtMetricsReport({
      documentationCompletionPercentage: merged.documentationCompletionPercentage,
      namingCompliancePercentage: merged.namingCompliance.compliancePercentage,
      complexityScore: merged.complexityScore,
      dependencyGraphScore: merged.dependencyGraphComplexity.score,
      conditionalSchemaCyclomaticTotal: merged.conditionalSchemaCyclomaticTotal,
      circularDependencyCount: merged.circularDependencyCount,
      deepestChainLength: merged.deepestChainLength,
      classCount: merged.classCount,
      isolatedClassCount: merged.isolatedClassIds.length,
      cognitiveComplexityPerClass: merged.cognitiveComplexityPerClass,
      averagePropertiesPerClass: merged.averagePropertiesPerClass,
    });
  return merged;
}

// ── sanitizeFilenameSegment ───────────────────────────────────────────────────

describe('sanitizeFilenameSegment', () => {
  it('keeps alphanumerics and common safe chars', () => {
    expect(sanitizeFilenameSegment('My Project v1.0')).toBe('My_Project_v1.0');
  });

  it('returns fallback for empty result', () => {
    expect(sanitizeFilenameSegment('!!!')).toBe('report');
  });

  it('truncates very long strings', () => {
    const long = 'a'.repeat(200);
    expect(sanitizeFilenameSegment(long).length).toBeLessThanOrEqual(96);
  });
});

// ── downloadSchemaScoreReportPdf ──────────────────────────────────────────────

describe('downloadSchemaScoreReportPdf', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSplitTextToSize.mockImplementation((text: string) => (text as string).split('\n'));
  });

  it('calls pdf.save() with sanitized project and version in filename', () => {
    downloadSchemaScoreReportPdf({
      metrics: makeMinimalMetrics(),
      projectName: 'My Project',
      versionLabel: 'v1.0',
    });
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockSave).toHaveBeenCalledWith('schema-score-report-My_Project-v1.0.pdf');
  });

  it('uses fallback filename segments when project/version are absent', () => {
    downloadSchemaScoreReportPdf({ metrics: makeMinimalMetrics() });
    expect(mockSave).toHaveBeenCalledWith('schema-score-report-schema-version.pdf');
  });

  it('sanitizes long project names in the filename', () => {
    const longName = 'x'.repeat(200);
    downloadSchemaScoreReportPdf({
      metrics: makeMinimalMetrics(),
      projectName: longName,
      versionLabel: 'v2',
    });
    const [filename] = (mockSave.mock.calls[0] as string[]);
    expect(filename.length).toBeLessThanOrEqual('schema-score-report--v2.pdf'.length + 96);
    expect(filename).toMatch(/^schema-score-report-.+-v2\.pdf$/);
  });

  it('does not throw when metrics contain documentation and naming gaps', () => {
    const metrics = makeMinimalMetrics({
      classesMissingDocumentation: ['ClassA', 'ClassB'],
      propertiesMissingDocumentation: [{ className: 'ClassA', propertyName: 'foo' }],
      namingCompliance: {
        classes: { pascal: 1, camel: 0, snake: 1, other: 0, total: 2 },
        properties: { pascal: 0, camel: 1, snake: 1, other: 0, total: 2 },
        compliancePercentage: 50,
        classesNonPascal: ['snake_class'],
        propertiesNonCamel: [{ className: 'ClassA', propertyName: 'BadProp' }],
      },
    });
    expect(() =>
      downloadSchemaScoreReportPdf({ metrics, projectName: 'P', versionLabel: 'v1' })
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it('includes cognitive complexity section when rows are present', () => {
    const metrics = makeMinimalMetrics({
      cognitiveComplexityPerClass: [
        {
          classId: 'c1',
          className: 'Heavy',
          score: 15,
          propertyContribution: 12,
          referenceContribution: 3,
          conditionalSchemaCyclomaticContribution: 0,
        },
      ],
    });
    downloadSchemaScoreReportPdf({ metrics, projectName: 'P', versionLabel: 'v1' });
    const joined = (mockText.mock.calls as Array<[string, ...unknown[]]>).map((c) => String(c[0])).join('\n');
    expect(joined).toContain('Cognitive complexity per class');
    expect(joined).toContain('Heavy | 15 | 12 | 3 | 0');
  });

  it('includes conditional schema cyclomatic in summary (#612)', () => {
    downloadSchemaScoreReportPdf({
      metrics: makeMinimalMetrics({ conditionalSchemaCyclomaticTotal: 4 }),
      projectName: 'P',
      versionLabel: 'v1',
    });
    const joined = (mockText.mock.calls as Array<[string, ...unknown[]]>).map((c) => String(c[0])).join('\n');
    expect(joined).toContain('Conditional schema cyclomatic (#612): 4');
  });

  it('includes dependency graph complexity section (#611)', () => {
    downloadSchemaScoreReportPdf({ metrics: makeMinimalMetrics(), projectName: 'P', versionLabel: 'v1' });
    const joined = (mockText.mock.calls as Array<[string, ...unknown[]]>).map((c) => String(c[0])).join('\n');
    expect(joined).toContain('Dependency graph complexity (#611)');
    expect(joined).toContain('Dependency-only edges: 0');
  });

  it('includes maintainability index section (#613)', () => {
    downloadSchemaScoreReportPdf({ metrics: makeMinimalMetrics(), projectName: 'P', versionLabel: 'v1' });
    const joined = (mockText.mock.calls as Array<[string, ...unknown[]]>).map((c) => String(c[0])).join('\n');
    expect(joined).toContain('Maintainability index (#613)');
    expect(joined).toContain('easier to evolve');
    expect(joined).toContain('Simplicity vs schema complexity');
  });

  it('includes technical debt section (#614)', () => {
    downloadSchemaScoreReportPdf({ metrics: makeMinimalMetrics(), projectName: 'P', versionLabel: 'v1' });
    const joined = (mockText.mock.calls as Array<[string, ...unknown[]]>).map((c) => String(c[0])).join('\n');
    expect(joined).toContain('Technical debt (#614)');
    expect(joined).toContain('Aggregate debt score:');
    expect(joined).toContain('Documentation gap (100');
  });

  it('does not throw with dependency metrics and layout quality', () => {
    const metrics = makeMinimalMetrics({
      dependencyMetricsPerClass: [
        { classId: 'c1', className: 'Order', inDegree: 2, outDegree: 1, betweenness: 0.5 },
      ],
    });
    const layoutQuality = {
      overallScore: 80,
      edgeCrossingCount: 2,
      nodeSpacingUniformityScore: 70,
      layoutSymmetryScore: 75,
      visualBalanceScore: 85,
    };
    expect(() =>
      downloadSchemaScoreReportPdf({ metrics, layoutQuality, projectName: 'P', versionLabel: 'v1' })
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it('does not add an extra page just for the footer', () => {
    // Simulate body content ending near the bottom of the page (ctx.y close to pageH - margin).
    // If ensureSpace were still called before the footer draw, it would trigger addPage.
    // We verify addPage is NOT called merely for the footer line.
    const addPageCallsBefore = (mockAddPage.mock.calls as unknown[]).length;
    downloadSchemaScoreReportPdf({
      metrics: makeMinimalMetrics(),
      projectName: 'P',
      versionLabel: 'v1',
    });
    // addPage may be called if content overflows, but save() must always be called exactly once.
    expect(mockSave).toHaveBeenCalledTimes(1);
    // The footer text should be drawn at pageH - 10 (fixed bottom position).
    const textCalls = mockText.mock.calls as Array<[string, number, number]>;
    const footerCall = textCalls.find(([t]) => (t as string).includes('Apiome Studio'));
    expect(footerCall).toBeDefined();
    expect(footerCall![2]).toBe(297 - 10); // pageH - 10
    // addPage is only for body overflow (schema report includes many sections; #614 may push minimal fixtures to 2 pages).
    expect((mockAddPage.mock.calls as unknown[]).length - addPageCallsBefore).toBeLessThanOrEqual(1);
  });
});

// ── downloadSchemaTimelineScoreReportPdf ──────────────────────────────────────

describe('downloadSchemaTimelineScoreReportPdf', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSplitTextToSize.mockImplementation((text: string) => (text as string).split('\n'));
  });

  it('calls pdf.save() with sanitized project name in filename', () => {
    downloadSchemaTimelineScoreReportPdf({
      rows: [{ versionLabel: 'v1', createdAt: null, metrics: makeMinimalMetrics() }],
      projectName: 'My Schemas',
    });
    expect(mockSave).toHaveBeenCalledWith('schema-score-history-My_Schemas.pdf');
  });

  it('uses fallback filename when projectName is absent', () => {
    downloadSchemaTimelineScoreReportPdf({ rows: [] });
    expect(mockSave).toHaveBeenCalledWith('schema-score-history-schema.pdf');
  });

  it('does not throw for rows with loadError', () => {
    expect(() =>
      downloadSchemaTimelineScoreReportPdf({
        rows: [
          { versionLabel: 'v1', createdAt: '2024-01-01', metrics: null, loadError: 'Network error' },
          { versionLabel: 'v2', createdAt: '2024-02-01', metrics: makeMinimalMetrics() },
        ],
        projectName: 'Proj',
      })
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it('does not throw for rows with null metrics and no loadError', () => {
    expect(() =>
      downloadSchemaTimelineScoreReportPdf({
        rows: [{ versionLabel: 'v1', createdAt: null, metrics: null }],
        projectName: 'Proj',
      })
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it('handles empty rows array without throwing', () => {
    expect(() =>
      downloadSchemaTimelineScoreReportPdf({ rows: [], projectName: 'Empty' })
    ).not.toThrow();
    expect(mockSave).toHaveBeenCalledWith('schema-score-history-Empty.pdf');
  });

  it('meta text uses ASCII arrow, not Unicode', () => {
    downloadSchemaTimelineScoreReportPdf({ rows: [], projectName: 'P' });
    // The splitTextToSize mock receives raw text — check it never contains the Unicode arrow.
    const allTexts = (mockSplitTextToSize.mock.calls as Array<[string]>).map(([t]) => t as string);
    const combined = allTexts.join('');
    expect(combined).not.toContain('\u2192'); // Unicode right arrow →
    expect(combined).toContain('->');
  });

  it('does not add an extra page just for the footer', () => {
    downloadSchemaTimelineScoreReportPdf({
      rows: [{ versionLabel: 'v1', createdAt: '2024-01-01', metrics: makeMinimalMetrics() }],
      projectName: 'P',
    });
    expect(mockSave).toHaveBeenCalledTimes(1);
    const textCalls = mockText.mock.calls as Array<[string, number, number]>;
    const footerCall = textCalls.find(([t]) => (t as string).includes('Apiome Studio'));
    expect(footerCall).toBeDefined();
    expect(footerCall![2]).toBe(297 - 10);
    expect((mockAddPage.mock.calls as unknown[]).length).toBe(0);
  });
});

