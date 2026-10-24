/**
 * @jest-environment node
 */
/**
 * The fetch-state ledger for Catalog, Projects and Versions (RC6-H3, #6210).
 *
 * RC6 releases Catalog, Projects and Versions, and no read on them may leave a blank area or a
 * stale view: while pending it draws a skeleton (or a named loading state), and when it fails it
 * says what failed and offers a retry. The audit behind this ticket found every read those screens
 * make; this file is that audit, kept honest.
 *
 *   - **`PRIMARY_READS`** fill a screen, a tab or a dialog. Each names the source that makes the
 *     read and the Jest tests that hold it **pending** and make it **fail**. The suite fails if a
 *     source stops making the read (the ledger is stale) or a named test is renamed or deleted.
 *   - **`ENRICHMENT_READS`** decorate content that is already on screen — tag filter options,
 *     review pills, sparklines, rule descriptions. They stay silent by design: a failure leaves
 *     the content without the decoration, never blank and never faked. Each says what the screen
 *     shows when it fails, and the suite holds the source to still making the read.
 *
 * A new read on these screens goes into one list or the other, with its tests.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = join(__dirname, '..');

/** A test, by file and by the exact title it is declared with. */
interface NamedTest {
  /** Path under `tests/`. */
  file: string;
  /** The `it(…)` / `test(…)` title, or a unique prefix of it. */
  title: string;
}

/** A read that fills a screen, tab or dialog. */
interface PrimaryRead {
  /** Audit row id (A = Catalog list, B = catalog item, C = Projects, D = Versions, S = Sunset). */
  id: string;
  /** Where the reader meets it. */
  surface: string;
  /** The source that makes the read, under the package. */
  source: string;
  /** A fragment of the source that is the read (a URL or a call). */
  needle: string;
  /** The test that holds it pending. */
  pending: NamedTest;
  /** The test that makes it fail and checks the retry. */
  failed: NamedTest;
}

/** A read that decorates content already on screen, and fails silently by design. */
interface EnrichmentRead {
  id: string;
  surface: string;
  source: string;
  needle: string;
  /** What the screen shows when the read fails. */
  onFailure: string;
}

const C = 'src/app/components/ade/dashboard/catalog/';

export const PRIMARY_READS: readonly PrimaryRead[] = [
  // ---- Catalog list --------------------------------------------------------------------------
  {
    id: 'A1',
    surface: 'Catalog list (cards and table)',
    source: 'src/app/ade/dashboard/catalog/CatalogClient.tsx',
    needle: '/api/catalog',
    pending: { file: 'catalog-hive-redesign.test.tsx', title: 'holds the cards view with card-shaped skeletons' },
    failed: { file: 'catalog-hive-redesign.test.tsx', title: 'says a failed read failed, instead of showing an empty catalog' },
  },
  {
    id: 'A1b',
    surface: 'Catalog list, table view',
    source: 'src/app/ade/dashboard/catalog/CatalogClient.tsx',
    needle: '/api/catalog',
    pending: { file: 'catalog-hive-redesign.test.tsx', title: 'holds the table with per-column skeleton rows while the first read is in flight' },
    failed: { file: 'catalog-hive-redesign.test.tsx', title: 'says a failed read failed in the table view too' },
  },
  {
    id: 'A2',
    surface: 'Lint report dialog',
    source: 'src/app/utils/version-lint-report.ts',
    needle: '/lint',
    pending: { file: 'catalog-lint-report-dialog.test.tsx', title: 'holds the dialog with a lint-summary skeleton' },
    failed: { file: 'catalog-lint-report-dialog.test.tsx', title: 'shows an error with a retry that re-fetches successfully' },
  },
  {
    id: 'A3',
    surface: 'Convert to OpenAPI dialog',
    source: 'src/app/utils/conversion-fidelity.ts',
    needle: 'dryRun=true',
    pending: { file: 'conversion-preview-dialog.test.tsx', title: 'holds the dialog with the report’s two columns as placeholders' },
    failed: { file: 'conversion-preview-dialog.test.tsx', title: 'shows an error with a retry that re-runs the dry-run' },
  },
  {
    id: 'A4',
    surface: 'Convert dialog → Projection graph; catalog item → Conversions',
    source: 'src/app/utils/conversion-projection.ts',
    needle: '/projection',
    pending: { file: 'ConversionProjectionGraphPanel.test.tsx', title: 'holds the table’s place with placeholder rows' },
    failed: { file: 'ConversionProjectionGraphPanel.test.tsx', title: 'offers retry on a transport error and recovers' },
  },
  {
    id: 'A5',
    surface: 'Bulk Convert dialog',
    source: 'src/app/components/ade/catalog/CatalogBulkConvertDialog.tsx',
    needle: 'fetchConversionDryRun(',
    pending: { file: 'catalog-bulk-convert.test.tsx', title: 'marks each row as previewing while its dry run is pending' },
    failed: { file: 'catalog-bulk-convert.test.tsx', title: 'says a row’s preview failed, and retries just that row' },
  },
  {
    id: 'A8',
    surface: 'Import to catalog → format detection',
    source: `${C}CatalogImportDialog.tsx`,
    needle: '/api/import/detect',
    pending: { file: 'catalog-import-read-states.test.tsx', title: 'says detection is running, and holds the paste button' },
    failed: { file: 'catalog-import-read-states.test.tsx', title: 'says a failed detection failed, with a retry that detects again' },
  },
  {
    id: 'A9',
    surface: 'Import to catalog → URL import',
    source: `${C}CatalogImportDialog.tsx`,
    needle: 'await fetch(url)',
    pending: { file: 'catalog-import-read-states.test.tsx', title: 'says detection is running, and holds the paste button' },
    failed: { file: 'catalog-import-read-states.test.tsx', title: 'retries a failed URL fetch' },
  },
  {
    id: 'A10',
    surface: 'Import to catalog → Git repository',
    source: `${C}CatalogImportDialog.tsx`,
    needle: '/api/catalog/import/git',
    pending: { file: 'catalog-import-read-states.test.tsx', title: 'says detection is running, and holds the paste button' },
    failed: { file: 'catalog-import-read-states.test.tsx', title: 'retries a failed repository read' },
  },
  {
    id: 'A12',
    surface: 'Import to catalog → quality step',
    source: 'src/app/utils/import-preflight.ts',
    needle: '/api/import/preflight',
    pending: { file: 'import-preview-a11y.test.tsx', title: 'scans clean in the loading state' },
    failed: { file: 'CatalogImportQualityStep.test.tsx', title: 'explains a transport failure and offers retry or proceed-without-score' },
  },
  {
    id: 'A13',
    surface: 'Quality step → What this import adds',
    source: 'src/app/utils/import-preview-manifest.ts',
    needle: '/api/import/preview-manifest',
    pending: { file: 'CatalogImportPreviewPanel.test.tsx', title: 'holds the tab with placeholder rows while the preview builds' },
    failed: { file: 'CatalogImportPreviewPanel.test.tsx', title: 'offers retry after a transport failure, and recovers' },
  },
  {
    id: 'A14',
    surface: 'Quality step → Bundle files',
    source: 'src/app/utils/import-bundle-inventory.ts',
    needle: '/api/import/bundle-inventory',
    pending: { file: 'CatalogImportBundlePanel.test.tsx', title: 'holds the tab with placeholder rows while the bundle reads' },
    failed: { file: 'CatalogImportBundlePanel.test.tsx', title: 'offers a retry after a transport failure' },
  },
  {
    id: 'A15',
    surface: 'Import to catalog → recent imports',
    source: 'src/app/components/ade/dashboard/asyncJobs/RecentAsyncJobsPanel.tsx',
    needle: 'recentAsyncJobsUrl(kind, pageLimit, nextOffset)',
    pending: { file: 'RecentAsyncJobsPanel.test.tsx', title: 'skeletons the table while the first page is pending' },
    failed: { file: 'RecentAsyncJobsPanel.test.tsx', title: 'says a failed read failed, with a retry that reads again' },
  },
  // ---- Catalog item ----------------------------------------------------------------------------
  {
    id: 'B1',
    surface: 'Catalog item page',
    source: 'src/app/ade/dashboard/catalog/[id]/CatalogItemDetailClient.tsx',
    needle: '/api/catalog/${encodeURIComponent(itemId)}',
    pending: { file: 'catalog-item-detail-hive.test.tsx', title: 'draws the header, tab strip and Overview as skeletons while loading' },
    failed: { file: 'catalog-item-detail-hive.test.tsx', title: 'offers a retry and a way back when the item cannot be read' },
  },
  {
    id: 'B2',
    surface: 'Catalog item → Format details',
    source: 'src/app/utils/catalog-payload-analysis.ts',
    needle: '/analysis',
    pending: { file: 'catalog-format-detail-panel.test.tsx', title: 'still loads the record when the reader leaves the tab while it is in flight' },
    failed: { file: 'catalog-format-detail-panel.test.tsx', title: 'retries a failed read from the error state' },
  },
  {
    id: 'B4',
    surface: 'Catalog item → Source & code',
    source: `${C}CatalogSourceViewer.tsx`,
    needle: 'await fetch(sourceHref)',
    pending: { file: 'catalog-source-viewer.test.tsx', title: 'holds the viewer with code-shaped placeholders while the source loads' },
    failed: { file: 'catalog-source-viewer.test.tsx', title: 'retries a failed read from the error state' },
  },
  {
    id: 'B5',
    surface: 'Catalog item → Conversions',
    source: 'src/app/utils/conversion-provenance.ts',
    needle: '/conversions',
    pending: { file: 'CatalogConversionHistoryPanel.test.tsx', title: 'holds the tab with timeline placeholders while the history loads' },
    failed: { file: 'CatalogConversionHistoryPanel.test.tsx', title: 'renders a retryable error when the history fetch fails' },
  },
  {
    id: 'B7',
    surface: 'Catalog item → Lint & score',
    source: `${C}CatalogLintPanel.tsx`,
    needle: 'fetchCatalogLintReport',
    pending: { file: 'catalog-lint-panel.test.tsx', title: 'holds the summary tiles and findings with skeletons while loading' },
    failed: { file: 'catalog-lint-panel.test.tsx', title: 'surfaces an error with a working retry' },
  },
  {
    id: 'B9',
    surface: 'Catalog item → Lint & score → source pane',
    source: `${C}CatalogLintPanel.tsx`,
    needle: 'await fetch(sourceHref)',
    pending: { file: 'catalog-lint-panel.test.tsx', title: 'holds the source pane with code placeholders while the source loads' },
    failed: { file: 'catalog-lint-panel.test.tsx', title: 'says a failed source read failed, with a retry' },
  },
  {
    id: 'B11',
    surface: 'Catalog item → Versions',
    source: `${C}CatalogVersionsPanel.tsx`,
    needle: '/api/versions?',
    pending: { file: 'catalog-versions-panel.test.tsx', title: 'holds the timeline with skeleton rows, not a text line, while loading' },
    failed: { file: 'catalog-versions-panel.test.tsx', title: 'surfaces a retryable error when the version fetch fails' },
  },
  {
    id: 'B12',
    surface: 'Catalog item → Versions → inline diff',
    source: `${C}CatalogVersionsPanel.tsx`,
    needle: 'loadCatalogRevisionSpec(',
    pending: { file: 'catalog-versions-panel.test.tsx', title: 'holds the diff with code placeholders while the two revisions build' },
    failed: { file: 'catalog-versions-panel.test.tsx', title: 'surfaces a retryable error when the compare read fails' },
  },
  {
    id: 'B13',
    surface: 'Related artifacts → Suggest links',
    source: `${C}CatalogRelatedArtifactsPanel.tsx`,
    needle: '/suggestions',
    pending: { file: 'related-artifacts-states.test.tsx', title: 'says the button is busy while the suggestions read' },
    failed: { file: 'related-artifacts-states.test.tsx', title: 'says a failed read failed in the panel, with a retry' },
  },
  {
    id: 'B14',
    surface: 'Catalog item / Versions → Test bench',
    source: 'src/app/components/ade/dashboard/test-bench/SchemaTestBench.tsx',
    needle: '/api/schemas/targets',
    pending: { file: 'schema-test-bench.test.tsx', title: 'surfaces a targets addressing fault instead of an empty picker' },
    failed: { file: 'schema-test-bench.test.tsx', title: 'surfaces a targets addressing fault instead of an empty picker' },
  },
  // ---- Projects ------------------------------------------------------------------------------
  {
    id: 'C1',
    surface: 'Projects (cards and table)',
    source: 'src/app/ade/dashboard/projects/ProjectsClient.tsx',
    needle: '/api/projects',
    pending: { file: 'projects-hive-redesign.test.tsx', title: 'holds the cards view with card-shaped skeletons while the read is pending' },
    failed: { file: 'projects-hive-redesign.test.tsx', title: 'says a failed read failed, with a retry, instead of "No projects yet"' },
  },
  {
    id: 'C1b',
    surface: 'Projects, table view',
    source: 'src/app/ade/dashboard/projects/ProjectsClient.tsx',
    needle: '/api/projects',
    pending: { file: 'projects-hive-redesign.test.tsx', title: 'shows the table view’s skeleton rows and its error state too' },
    failed: { file: 'projects-hive-redesign.test.tsx', title: 'shows the table view’s skeleton rows and its error state too' },
  },
  // ---- Versions ------------------------------------------------------------------------------
  {
    id: 'D1',
    surface: 'Versions page, projects',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/api/projects?include_catalog=true',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'shows a loading state, not "No projects yet"' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'says a failed projects read failed, and retries it' },
  },
  {
    id: 'D2',
    surface: 'Versions timeline',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/api/versions?',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'holds the table with skeleton rows while the versions read is pending' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'says a failed versions read failed, instead of "No versions yet"' },
  },
  {
    id: 'D6',
    surface: 'New version dialog → branches',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/version-branches',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'New version: a failed branch read says so' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'New version: a failed branch read says so' },
  },
  {
    id: 'D8',
    surface: 'Versions → Changes, classifications',
    source: 'src/app/ade/dashboard/versions/VersionChangesPanel.tsx',
    needle: '/changelogs',
    pending: { file: 'version-changes-panel.test.tsx', title: 'draws placeholder badges, not "Pending", while the classifications load' },
    failed: { file: 'version-changes-panel.test.tsx', title: 'says the classifications failed, with a retry that restores the badges' },
  },
  {
    id: 'D9',
    surface: 'Versions → Changes, changelog',
    source: 'src/app/ade/dashboard/versions/VersionChangesPanel.tsx',
    needle: '/changelog?',
    pending: { file: 'version-changes-panel.test.tsx', title: 'holds the changelog with a skeleton, then says a failed read failed' },
    failed: { file: 'version-changes-panel.test.tsx', title: 'holds the changelog with a skeleton, then says a failed read failed' },
  },
  {
    id: 'D10',
    surface: 'Versions → Related artifacts',
    source: 'src/app/components/ade/dashboard/ProjectRelatedArtifactsSection.tsx',
    needle: '/api/projects/${encodeURIComponent(projectId)}',
    pending: { file: 'related-artifacts-states.test.tsx', title: 'holds a card-shaped placeholder while the project reads' },
    failed: { file: 'related-artifacts-states.test.tsx', title: 'says a rejected read failed, with a retry that brings the panel back' },
  },
  {
    id: 'D11',
    surface: 'Versions → Sources',
    source: 'src/app/components/ade/versions/RepositorySourcesPanel.tsx',
    needle: '/repository-sources?version=',
    pending: { file: 'repository-sources-panel.test.tsx', title: 'holds the panel with a skeleton while the sources read' },
    failed: { file: 'repository-sources-panel.test.tsx', title: 'a failed read names what failed and retries it' },
  },
  {
    id: 'D12',
    surface: 'Versions → Sources → Federation',
    source: 'src/app/components/ade/versions/FederationSwitch.tsx',
    needle: '/repository-federation',
    pending: { file: 'repository-federation-ui.test.tsx', title: 'the switch shows a placeholder while it reads' },
    failed: { file: 'repository-federation-ui.test.tsx', title: 'the switch shows a placeholder while it reads, and a failed read can be retried' },
  },
  {
    id: 'D13',
    surface: 'Versions → Sources → Merge history',
    source: 'src/app/components/ade/versions/FederationMergeHistory.tsx',
    needle: 'await fetch(url)',
    pending: { file: 'repository-federation-ui.test.tsx', title: 'the merge history holds a skeleton, then retries a failed read' },
    failed: { file: 'repository-federation-ui.test.tsx', title: 'the merge history holds a skeleton, then retries a failed read' },
  },
  {
    id: 'D14',
    surface: 'Versions → Sources → Sync back',
    source: 'src/app/components/ade/versions/PrBackPanel.tsx',
    needle: '/pr-back/repositories',
    pending: { file: 'pr-back-panel.test.tsx', title: 'holds the section with a skeleton while the repositories read' },
    failed: { file: 'pr-back-panel.test.tsx', title: 'retries a failed repositories read' },
  },
  {
    id: 'D15',
    surface: 'View spec dialog',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: 'await buildOpenApiSpecJsonForVersion(',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'View spec: a code skeleton while the spec builds' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'View spec: a code skeleton while the spec builds, then an error with a retry' },
  },
  {
    id: 'D16',
    surface: 'Heatmap dialog',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: 'getPropertiesForClassesBatch(',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'Heatmap: tile skeletons while the classes load' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'Heatmap: tile skeletons while the classes load, then an error with a retry' },
  },
  {
    id: 'D17',
    surface: 'Compare dialog',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: 'loadVersionSpec(baseId)',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'Compare: a failed spec build is said in the dialog' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'Compare: a failed spec build is said in the dialog' },
  },
  {
    id: 'D19',
    surface: 'Compare dialog → Canvas',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: 'loadLayoutStateForVersionCompare(compareVersion1Id',
    pending: { file: 'versions-hive-redesign.test.tsx', title: 'Compare › Canvas: a spinner while the layouts load' },
    failed: { file: 'versions-hive-redesign.test.tsx', title: 'Compare › Canvas: a spinner while the layouts load, then an error with a retry' },
  },
  {
    id: 'D22',
    surface: 'Publish dialog → Style guide',
    source: 'src/app/components/ade/dashboard/PublishGuideViolationsPanel.tsx',
    needle: 'fetchVersionLintReport(',
    pending: { file: 'publish-guide-violations-panel.test.tsx', title: 'says what it is checking while the report is pending' },
    failed: { file: 'publish-guide-violations-panel.test.tsx', title: 'says the check failed, with a retry that loads the report' },
  },
  {
    id: 'D23',
    surface: 'Publish dialog → Breaking changes',
    source: 'src/app/components/ade/dashboard/BreakingPublishGuardrailPanel.tsx',
    needle: 'fetchBreakingPublishGuardrail(',
    pending: { file: 'breaking-publish-guardrail-panel.test.tsx', title: 'says what it is checking while the read is pending' },
    failed: { file: 'breaking-publish-guardrail-panel.test.tsx', title: 'says the check failed, with a retry that runs it again' },
  },
  {
    id: 'D26',
    surface: 'Versions → Repository (binding)',
    source: 'src/app/components/ade/bindings/VersionBindingPanel.tsx',
    needle: '/bindings',
    pending: { file: 'version-binding-panel.test.tsx', title: 'holds the binding’s place with a card placeholder while it reads' },
    failed: { file: 'version-binding-panel.test.tsx', title: 'says a failed read failed, with a retry that reads the binding again' },
  },
  {
    id: 'D27',
    surface: 'Versions → Discussion',
    source: 'src/app/components/ade/discussion/ProjectDiscussionPanel.tsx',
    needle: '/comment-threads',
    pending: { file: 'project-discussion-panel.test.tsx', title: 'shows the loading state until the list arrives' },
    failed: { file: 'project-discussion-panel.test.tsx', title: 'retries a failed list read from the error state' },
  },
  {
    id: 'D28',
    surface: 'Version → Export dialog',
    source: 'src/app/components/ade/dashboard/export/useExportTargets.ts',
    needle: '/api/export/targets',
    pending: { file: 'ExportDialog.test.tsx', title: 'says it is measuring while the targets load' },
    failed: { file: 'ExportDialog.test.tsx', title: 'says a failed targets read failed, with a retry that loads them' },
  },
  // ---- Sunset timeline -----------------------------------------------------------------------
  {
    id: 'S1',
    surface: 'Sunset timeline',
    source: 'src/app/ade/dashboard/versions/sunset-timeline/page.tsx',
    needle: '/api/versions/sunset-timeline',
    pending: { file: 'sunset-timeline-hive-redesign.test.tsx', title: 'holds the table with skeleton rows while the timeline read is pending' },
    failed: { file: 'sunset-timeline-hive-redesign.test.tsx', title: 'draws a failed read as a failure with a retry, not as an empty workspace' },
  },
];

export const ENRICHMENT_READS: readonly EnrichmentRead[] = [
  {
    id: 'A6',
    surface: 'How the catalog works → supported formats',
    source: `${C}useCatalogImportAvailability.ts`,
    needle: '/api/import/sources',
    onFailure: 'The shipped list of formats; the dialog still explains the catalog.',
  },
  {
    id: 'A7',
    surface: 'Import to catalog → source tiles',
    source: 'src/app/components/ade/dashboard/useImportSources.ts',
    needle: '/api/import/sources',
    onFailure: 'The built-in source tiles; every intake method still works.',
  },
  {
    id: 'A11',
    surface: 'Import to catalog → "import them all" banner',
    source: `${C}CatalogImportDialog.tsx`,
    needle: '/api/catalog/import/bulk/plan',
    onFailure: 'No bulk banner; the single-spec import goes on as before.',
  },
  {
    id: 'A13b',
    surface: 'What this import adds → Load all',
    source: `${C}CatalogImportPreviewPanel.tsx`,
    needle: 'fetchImportPreviewManifest(',
    onFailure: 'The pages already shown stay; the windowed view keeps working.',
  },
  {
    id: 'A14b',
    surface: 'Bundle files → remaining pages',
    source: `${C}CatalogImportBundlePanel.tsx`,
    needle: 'fetchImportBundleInventory(',
    onFailure: 'The files already listed stay.',
  },
  {
    id: 'B3',
    surface: 'Format details → capability explanations',
    source: `${C}useFormatCapabilities.ts`,
    needle: '/api/import/format-capabilities',
    onFailure: 'The analysis without the per-capability notes.',
  },
  {
    id: 'B8',
    surface: 'Lint & score → decision badges',
    source: `${C}CatalogLintPanel.tsx`,
    needle: '/api/lint/decisions',
    onFailure: 'Findings without waiver/decision badges.',
  },
  {
    id: 'B10',
    surface: 'Lint & score → rule descriptions',
    source: 'src/app/utils/lint-rule-catalog.ts',
    needle: '/api/lint/rules',
    onFailure: 'Findings with their rule ids, without the catalog descriptions.',
  },
  {
    id: 'C2',
    surface: 'Projects / Versions → review pills',
    source: 'src/app/hooks/useOpenReviews.ts',
    needle: '/api/reviews/status',
    onFailure: 'Rows without a review pill.',
  },
  {
    id: 'D3',
    surface: 'Versions → tag filter options',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/version-tags',
    onFailure: 'The tag filter offers no tags; the table is unchanged.',
  },
  {
    id: 'D4',
    surface: 'Versions → row menu "freeze schema" state',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/has-class-schema',
    onFailure: 'The freeze action falls back to its default state.',
  },
  {
    id: 'D5',
    surface: 'Versions → compatibility chip in the status strip',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/changelogs',
    onFailure: 'No compatibility chip; the other statuses stay.',
  },
  {
    id: 'D7',
    surface: 'Versions → Conversion tab',
    source: `${C}useConversionHistory.ts`,
    needle: 'fetchProjectConversionHistory',
    onFailure: 'No Conversion tab (it only exists when a project has conversions).',
  },
  {
    id: 'D18',
    surface: 'Compare dialog → stored classification badge',
    source: 'src/app/ade/dashboard/versions/page.tsx',
    needle: '/changelog?${qs.toString()}`',
    onFailure: 'The diff without the stored severity badge.',
  },
  {
    id: 'D20',
    surface: 'Versions → mock usage sparklines',
    source: 'src/app/hooks/useMockUsage.ts',
    needle: '/api/mocks/usage',
    onFailure: 'An empty sparkline in the mock cell.',
  },
  {
    id: 'D24',
    surface: 'Publish dialog → verification policy',
    source: 'src/app/components/ade/dashboard/VerificationPolicyDecisionPanel.tsx',
    needle: "verificationPolicyApi<VerificationPolicyDecision>('evaluate'",
    onFailure: 'An error alert with a Re-evaluate button; publish follows the policy result.',
  },
  {
    id: 'S2',
    surface: 'Sunset timeline → project filter options',
    source: 'src/app/ade/dashboard/versions/sunset-timeline/page.tsx',
    needle: '/api/projects',
    onFailure: 'The project filter lists no projects; every entry still shows.',
  },
];

/** The text of a file under the package. */
function read(path: string): string {
  return readFileSync(join(ROOT, path), 'utf8');
}

describe('primary reads: a skeleton while pending, an error with a retry when failed', () => {
  it('lists each audit row once', () => {
    const ids = [...PRIMARY_READS, ...ENRICHMENT_READS].map((row) => row.id);
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([]);
  });

  it.each(PRIMARY_READS.map((row) => [row.id, row] as const))('%s is still made where the ledger says', (_id, row) => {
    expect(existsSync(join(ROOT, row.source))).toBe(true);
    expect(read(row.source)).toContain(row.needle);
  });

  it.each(PRIMARY_READS.map((row) => [row.id, row] as const))('%s has a pending test and a failed test', (_id, row) => {
    for (const named of [row.pending, row.failed]) {
      const path = join('tests', named.file);
      expect(existsSync(join(ROOT, path))).toBe(true);
      expect(read(path)).toContain(named.title);
    }
  });
});

describe('enrichment reads: silent by design, never blank or faked', () => {
  it.each(ENRICHMENT_READS.map((row) => [row.id, row] as const))('%s is still made where the ledger says', (_id, row) => {
    expect(existsSync(join(ROOT, row.source))).toBe(true);
    expect(read(row.source)).toContain(row.needle);
    expect(row.onFailure.trim().length).toBeGreaterThan(0);
  });
});
