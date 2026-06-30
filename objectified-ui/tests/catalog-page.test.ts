/**
 * Source-contract tests for the Catalog dashboard screen (MFI-23.3, #4012).
 *
 * The Catalog screen is cloned from the Projects dashboard and is heavy on app-router / next-auth /
 * dialog-provider wiring, so — matching the project's convention for the Projects page and the
 * `catalog-proxy.test.ts` proxy tests — these assert the source-level contract the feature depends
 * on rather than standing up the full render stack: the route exists, reaches `/api/catalog`,
 * offers card/table views, the four filter chips, the six sort options, search, soft-delete /
 * undelete via the reused project server actions, and an empty state that explains the catalog.
 * If the page drops one of these behaviours, this goes red.
 */

import * as fs from 'fs';
import * as path from 'path';

const PAGE = path.resolve(__dirname, '..', 'src', 'app', 'ade', 'dashboard', 'catalog', 'page.tsx');
const src = fs.readFileSync(PAGE, 'utf8');

describe('catalog screen route', () => {
  it('exists at /ade/dashboard/catalog and is a default-exported client component', () => {
    expect(fs.existsSync(PAGE)).toBe(true);
    expect(src).toMatch(/^'use client';/);
    expect(src).toMatch(/export default Catalog/);
  });
});

describe('data wiring', () => {
  it('reads the catalog list from the /api/catalog proxy (MFI-23.2)', () => {
    expect(src).toMatch(/fetch\(`\/api\/catalog\$\{qs\}`\)/);
    expect(src).toContain('data.catalog');
  });

  it('forwards include_deleted for trash/restore parity', () => {
    expect(src).toContain("showDeleted ? '?include_deleted=true' : ''");
  });

  it('does not create or edit items (catalog is read-only here)', () => {
    expect(src).not.toMatch(/createProject|updateProject/);
    expect(src).not.toContain('Create item');
    expect(src).not.toContain('Edit item');
  });
});

describe('soft-delete / undelete via reused project server actions', () => {
  it('imports the project delete/restore/permanent-delete helpers', () => {
    expect(src).toMatch(/import\s*\{[^}]*deleteProject[^}]*\}\s*from\s*'.*lib\/db\/helper'/s);
    expect(src).toContain('restoreProject');
    expect(src).toContain('permanentDeleteProject');
  });

  it('wires delete, undelete and permanent-delete handlers', () => {
    expect(src).toContain('await deleteProject(itemId)');
    expect(src).toContain('await restoreProject(item.id)');
    expect(src).toContain('await permanentDeleteProject(item.id)');
  });

  it('double-confirms a permanent delete', () => {
    expect(src).toContain('Final Confirmation');
  });
});

describe('views, filters, sort and search', () => {
  it('offers a card/table view toggle', () => {
    expect(src).toContain("setViewMode('cards')");
    expect(src).toContain("setViewMode('table')");
  });

  it('offers all four filter chips', () => {
    for (const chip of ['all', 'active', 'attention', 'deleted']) {
      expect(src).toContain(`setFilterChip('${chip}')`);
    }
  });

  it('exposes exactly the six required sort options', () => {
    for (const col of ['name', 'created', 'updated', 'quality', 'grade', 'format']) {
      expect(src).toContain(`column: '${col}'`);
    }
  });

  it('sorts via the dedicated catalog sorter', () => {
    expect(src).toContain('sortCatalogDashboardRows');
  });

  it('has a search box that filters the list', () => {
    expect(src).toContain('setSearchQuery');
    expect(src).toMatch(/i\.name\.toLowerCase\(\)\.includes\(q\)/);
  });
});

describe('CatalogItemCard wiring (MFI-23.4)', () => {
  it('renders the card grid via the dedicated CatalogItemCard component', () => {
    expect(src).toContain("import { CatalogItemCard }");
    expect(src).toMatch(/<CatalogItemCard\b/);
  });

  it('passes a format/source pill slot (MFI-23.5) and an actions slot to the card', () => {
    expect(src).toMatch(/formatSlot=\{<CatalogFormatBadge/);
    expect(src).toMatch(/actionsSlot=\{/);
  });

  it('wires the quality orb to the shared ProjectQualityHistoryDialog', () => {
    expect(src).toContain('ProjectQualityHistoryDialog');
    expect(src).toContain('onOpenQualityHistory={() => handleOpenQuality(item)}');
  });

  it('wires the lint orb to the server-backed CatalogLintReportDialog (MFI-23.10)', () => {
    expect(src).toContain('CatalogLintReportDialog');
    expect(src).toContain('onOpenLintReport={() => handleOpenLint(item)}');
    // The lint action opens the server report, not the browser-local quality dialog's lint tab.
    expect(src).toMatch(/handleOpenLint[\s\S]{0,80}?setLintDialogItem\(item\)/);
  });

  it('offers View / Lint / Convert to OpenAPI actions but never Publish', () => {
    expect(src).toMatch(/<Eye[\s\S]{0,80}?>\s*View/);
    expect(src).toMatch(/<ScanLine[\s\S]{0,80}?>\s*Lint/);
    expect(src).toContain('Convert to OpenAPI');
    // No publish action label, handler or icon — the catalog is the non-publishable slice (MFI-23.1).
    expect(src).not.toMatch(/>\s*Publish/);
    expect(src).not.toMatch(/onPublish|handlePublish|publishProject/);
  });
});

describe('detail navigation (MFI-23.9)', () => {
  it('navigates to the catalog item detail route on open-detail', () => {
    expect(src).toMatch(/handleOpenDetail[\s\S]{0,120}?\/ade\/dashboard\/catalog\/\$\{encodeURIComponent\(item\.id\)\}/);
  });

  it('opens the detail view from the card body click', () => {
    expect(src).toContain('onOpenDetail={() => handleOpenDetail(item)}');
  });

  it('offers a Details action distinct from View (which still goes to versions)', () => {
    expect(src).toMatch(/<PanelsTopLeft[\s\S]{0,80}?>\s*Details/);
    expect(src).toContain('onOpenDetail={handleOpenDetail}');
    expect(src).toMatch(/handleView[\s\S]{0,120}?\/ade\/dashboard\/versions\?projectId=/);
  });
});

describe('empty state', () => {
  it('explains what the catalog is and how items get here', () => {
    expect(src).toContain('Your catalog is empty');
    expect(src).toMatch(/non-OpenAPI/);
  });
});
