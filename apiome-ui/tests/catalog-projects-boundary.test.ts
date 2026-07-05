/**
 * Source-contract tests for the Catalog/Projects boundary (#4587) and the catalog export entry
 * (MFX-41.2, #4349).
 *
 * The boundary rule: a file imported into the catalog (a `publishable=false` project, MFI-23.1)
 * lives in Dashboard → Catalog until it is converted to OpenAPI — conversion is what mints a
 * Project and version. Catalog items therefore must never list on the Projects page nor in the
 * versions page's project selector, and exporting a catalog item happens from the catalog
 * surfaces, not by surfacing the item under Projects.
 *
 * The pages involved are heavy on app-router / next-auth wiring, so — matching the project's
 * convention (`catalog-page.test.ts`) — these assert the source-level contract rather than
 * standing up the full render stack. If a page reintroduces the leak, this goes red.
 */

import * as fs from 'fs';
import * as path from 'path';

const APP = path.resolve(__dirname, '..', 'src', 'app');
const projectsSrc = fs.readFileSync(path.join(APP, 'ade', 'dashboard', 'projects', 'page.tsx'), 'utf8');
const versionsSrc = fs.readFileSync(path.join(APP, 'ade', 'dashboard', 'versions', 'page.tsx'), 'utf8');
const catalogSrc = fs.readFileSync(path.join(APP, 'ade', 'dashboard', 'catalog', 'page.tsx'), 'utf8');
const detailSrc = fs.readFileSync(
  path.join(APP, 'ade', 'dashboard', 'catalog', '[id]', 'CatalogItemDetailClient.tsx'),
  'utf8',
);

describe('Projects page excludes catalog items (#4587)', () => {
  it('imports the shared publishability predicate', () => {
    expect(projectsSrc).toMatch(/import \{ isProjectPublishable \} from '.*catalog-publishable'/);
  });

  it('filters the loaded project list through isProjectPublishable', () => {
    expect(projectsSrc).toContain(
      'setProjects((data.projects as Project[]).filter(isProjectPublishable))',
    );
  });

  it('carries the publishable flag on its Project shape', () => {
    expect(projectsSrc).toMatch(/publishable\?: boolean/);
  });
});

describe('Versions page selector excludes catalog items but keeps deep-links working (#4587)', () => {
  it('keeps the full unfiltered list in state (publish gating + deep-links need it)', () => {
    expect(versionsSrc).toContain('setProjects(data.projects)');
  });

  it('derives publishable-only selector options, appending only a deep-linked selection', () => {
    expect(versionsSrc).toContain('const selectableProjects = useMemo');
    expect(versionsSrc).toContain('projects.filter(isProjectPublishable)');
    expect(versionsSrc).toContain(
      'selectableProjects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)',
    );
  });

  it('never auto-selects a catalog item as the default project', () => {
    expect(versionsSrc).toContain("projects.find((p) => isProjectPublishable(p))?.id ?? ''");
  });

  it('offers only real Projects as fork targets', () => {
    expect(versionsSrc).toContain(
      'projects.filter((p) => p.id !== selectedProjectId && isProjectPublishable(p))',
    );
  });
});

describe('Catalog list export entry (MFX-41.2, #4349)', () => {
  it('offers an Export row action with the Export-vs-Convert copy', () => {
    expect(catalogSrc).toContain('data-testid="catalog-action-export"');
    expect(catalogSrc).toContain('Export to another format…');
    expect(catalogSrc).toContain('CATALOG_EXPORT_VS_CONVERT_COPY');
  });

  it('mounts the shared ExportDialog aimed at the item (a catalog id is a project id)', () => {
    expect(catalogSrc).toMatch(/import ExportDialog, \{ type ExportedArtifactSummary \}/);
    expect(catalogSrc).toContain('artifact={exportDialogItem.id}');
    expect(catalogSrc).toContain('artifactLabel={exportDialogItem.name}');
  });

  it('records the export in the browser-local recent-exports store (MFX-6.5)', () => {
    expect(catalogSrc).toContain('recordRecentExport(exportDialogItem.id, null, summary)');
  });

  it('leaves Convert untouched (Export must not replace it)', () => {
    expect(catalogSrc).toContain('convertActionLabel(item.conversion)');
    expect(catalogSrc).toContain('onConvert={handleConvert}');
  });
});

describe('Catalog detail export CTA (MFX-41.2, #4349)', () => {
  it('offers an Export CTA beside Convert with the distinction copy', () => {
    expect(detailSrc).toContain('data-testid="catalog-detail-export"');
    expect(detailSrc).toContain('data-testid="catalog-detail-convert"');
    expect(detailSrc).toContain('CATALOG_EXPORT_VS_CONVERT_COPY');
  });

  it('mounts the shared ExportDialog and records the export', () => {
    expect(detailSrc).toContain('artifact={item.id}');
    expect(detailSrc).toContain('recordRecentExport(item.id, null, summary)');
  });
});
