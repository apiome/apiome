/**
 * ExportMappingGraphPanel — the fidelity heatmap overlay (MFX-45.2, #4375).
 *
 * The ticket's acceptance criteria at the component level:
 *
 *  1. A lossy proto export shows exactly which messages/fields degrade and how: each node
 *     wears its worst kind (glyph + word + colour) and its accessible name says what the
 *     report holds for it; hovering or focusing it shows the LossItem detail.
 *  2. Filters isolate kinds — on the graph and on the treemap.
 *  3. The legend matches the report's counts exactly.
 *
 * The real Petstore → proto3 report and manifest (`fixtures/fidelityOverlayPetstoreProto.json`,
 * captured from apiome-rest) pin the criteria on what the product actually produces, and draw
 * the docs screenshots (`FIDELITY_OVERLAY_FIXTURE_DUMP=1`).
 *
 * Without a report the panel draws exactly as before (covered by the IXH-4.2 suite).
 */

import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';
import { jest } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';

import { ExportMappingGraphPanel } from '../src/app/components/ade/dashboard/export/ExportMappingGraphPanel';
import { mappingRowId } from '../src/app/components/ade/dashboard/export/exportMappingGraph';
import type {
  LossItem,
  LossinessReport,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';
import type {
  ExportManifestEntity,
  ExportPreviewManifestPage,
} from '../src/app/components/ade/dashboard/export/exportPreviewManifest';

expect.extend(toHaveNoViolations);

// ---------------------------------------------------------------------------
// Fixtures — the Petstore exported to Protocol Buffers (proto3), plus one drop
// ---------------------------------------------------------------------------

function entity(overrides: Partial<ExportManifestEntity>): ExportManifestEntity {
  return {
    key: 'Entity',
    name: 'Entity',
    entity_kind: 'type',
    parent_key: null,
    order: 0,
    description: null,
    deprecated: false,
    status: 'retained',
    reason: null,
    severity: 'info',
    detail: 'carried faithfully',
    target_mapping: null,
    emitted: true,
    location: null,
    aggregated: false,
    reported: true,
    native_name: null,
    native_id: null,
    source_location: null,
    ...overrides,
  };
}

const ENTITIES: ExportManifestEntity[] = [
  entity({ key: 'GET /pets', name: 'GET /pets', entity_kind: 'operation', order: 0 }),
  entity({ key: 'Pet', name: 'Pet', order: 1 }),
  entity({
    key: 'Pet.id', name: 'id', entity_kind: 'field', parent_key: 'Pet', order: 2,
    status: 'approximated', severity: 'warn', reason: 'destination_unsupported',
  }),
  entity({
    key: 'Pet.tag', name: 'tag', entity_kind: 'field', parent_key: 'Pet', order: 3,
    status: 'synthesized', severity: 'warn',
  }),
  entity({
    key: 'Pet.links', name: 'links', entity_kind: 'field', parent_key: 'Pet', order: 4,
    status: 'dropped', severity: 'critical', reason: 'destination_unsupported', emitted: false,
  }),
];

const ITEMS: LossItem[] = [
  { construct: 'GET /pets', kind: 'ok', severity: 'info', message: 'operation carried to Protocol Buffers (proto3)' },
  { construct: 'Pet', kind: 'ok', severity: 'info', message: 'object carried to Protocol Buffers (proto3)' },
  {
    construct: 'Pet.id', kind: 'approx', severity: 'warn',
    message: 'Protocol Buffers (proto3) cannot enforce validation constraints',
    target_mapping: 'constraint → comment',
  },
  {
    construct: 'Pet.id', kind: 'synth', severity: 'warn',
    message: 'Protocol Buffers (proto3) requires stable field numbers; one is synthesized',
  },
  {
    construct: 'Pet.tag', kind: 'synth', severity: 'warn',
    message: 'Protocol Buffers (proto3) requires stable field numbers; one is synthesized',
  },
  { construct: 'Pet.links', kind: 'drop', severity: 'critical', message: 'proto3 has no hyperlinks' },
];

const REPORT: LossinessReport = {
  items: ITEMS,
  kind_counts: { drop: 1, approx: 1, synth: 2, ok: 2 },
  severity_counts: { info: 2, warn: 3, critical: 1 },
};

function page(): ExportPreviewManifestPage {
  return {
    manifest_hash: 'hash-4375',
    target: {
      key: 'proto3',
      format: 'protobuf',
      label: 'Protocol Buffers (proto3)',
      emitter_version: '1.0.0',
      apiome_version: '2.1.0',
      registry_version: '2025.07.01',
    },
    status_counts: {
      retained: 2, transformed: 0, approximated: 1, synthesized: 1, dropped: 1, unavailable: 0, 'not-applicable': 0,
    },
    reason_counts: { destination_unsupported: 2 },
    entities: ENTITIES,
    total_entities: ENTITIES.length,
    dropped_entities: 1,
    files: [{ path: 'petstore.proto', media_type: 'text/plain', line_count: 40, entity_count: 5 }],
    page_size: 1000,
    next_cursor: null,
    truncated: false,
  };
}

type PanelProps = React.ComponentProps<typeof ExportMappingGraphPanel>;

async function renderPanel(props: Partial<PanelProps> = {}) {
  const onSelectEntity = props.onSelectEntity ?? jest.fn();
  const utils = render(
    <ExportMappingGraphPanel
      page={page()}
      entities={ENTITIES}
      loading={false}
      error={null}
      complete
      onLoadMore={jest.fn()}
      targetLabel="Protocol Buffers (proto3)"
      selectedEntityKey={null}
      onSelectEntity={onSelectEntity}
      onClearSelection={jest.fn()}
      report={REPORT}
      {...props}
    />,
  );
  await act(async () => {});
  return { ...utils, onSelectEntity };
}

const node = (key: string) => screen.getByTestId(`export-mapping-node-${mappingRowId(key)}`);

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, reasons: [] }) }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Off without a report
// ---------------------------------------------------------------------------

describe('without a report', () => {
  it('draws the graph exactly as before — no overlay controls or marks', async () => {
    await renderPanel({ report: null });
    expect(screen.queryByTestId('fidelity-overlay-controls')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fidelity-overlay-marker')).not.toBeInTheDocument();
    expect(node('Pet.id')).not.toHaveAttribute('data-loss-kind');
    expect(node('Pet.id').getAttribute('aria-label')).not.toMatch(/fidelity report/);
  });
});

// ---------------------------------------------------------------------------
// AC 1 — which messages/fields degrade, and how
// ---------------------------------------------------------------------------

describe('a lossy proto export', () => {
  it('paints every node with the worst kind of its report items', async () => {
    await renderPanel();
    expect(node('Pet.links')).toHaveAttribute('data-loss-kind', 'drop');
    expect(node('Pet.id')).toHaveAttribute('data-loss-kind', 'approx');
    expect(node('Pet.tag')).toHaveAttribute('data-loss-kind', 'synth');
    expect(node('Pet')).toHaveAttribute('data-loss-kind', 'ok');
    expect(node('GET /pets')).toHaveAttribute('data-loss-kind', 'ok');
  });

  it('marks each node with the kind glyph and item count — not colour alone', async () => {
    await renderPanel();
    const marker = within(node('Pet.id')).getByTestId('fidelity-overlay-marker');
    expect(marker).toHaveAttribute('data-kind', 'approx');
    expect(marker).toHaveTextContent('≈ 2');
    expect(within(node('Pet.links')).getByTestId('fidelity-overlay-marker')).toHaveTextContent('✕ 1');
  });

  it('says in the accessible name what the report holds — on the node and its table row', async () => {
    await renderPanel();
    const label = node('Pet.id').getAttribute('aria-label');
    expect(label).toMatch(/fidelity report: 1 APPROX, 1 SYNTH$/);
    expect(screen.getByTestId(`export-mapping-row-select-${mappingRowId('Pet.id')}`)).toHaveAttribute(
      'aria-label',
      label!,
    );
  });

  it('shows the LossItem detail on hover and on focus', async () => {
    await renderPanel();
    const detail = screen.getByTestId('fidelity-overlay-detail');
    expect(detail).toHaveTextContent(/Hover or focus a construct/);

    fireEvent.mouseEnter(node('Pet.id'));
    expect(detail).toHaveTextContent('2 findings');
    expect(detail).toHaveTextContent('cannot enforce validation constraints');
    expect(detail).toHaveTextContent('In the target: constraint → comment');
    expect(detail).toHaveTextContent('requires stable field numbers');
    // Worst kind first, as the report row prints it.
    const kinds = within(detail).getAllByTestId(/export-fidelity-kind-/).map((el) => el.dataset.testid);
    expect(kinds).toEqual(['export-fidelity-kind-approx', 'export-fidelity-kind-synth']);

    fireEvent.mouseLeave(node('Pet.id'));
    expect(detail).toHaveTextContent(/Hover or focus a construct/);

    fireEvent.focus(node('Pet.links'));
    expect(detail).toHaveTextContent('proto3 has no hyperlinks');
  });
});

// ---------------------------------------------------------------------------
// AC 3 — the counts are the report's
// ---------------------------------------------------------------------------

describe('legend', () => {
  it('prints the report’s kind counts exactly, and says they reconcile', async () => {
    await renderPanel();
    expect(screen.getByTestId('fidelity-overlay-count-drop')).toHaveTextContent('1');
    expect(screen.getByTestId('fidelity-overlay-count-approx')).toHaveTextContent('1');
    expect(screen.getByTestId('fidelity-overlay-count-synth')).toHaveTextContent('2');
    expect(screen.getByTestId('fidelity-overlay-count-ok')).toHaveTextContent('2');
    expect(screen.getByTestId('fidelity-overlay-reconciliation')).toHaveTextContent(
      '6 findings, the counts of the fidelity report.',
    );
  });

  it('states the findings the graph does not draw yet', async () => {
    await renderPanel({ entities: ENTITIES.slice(0, 2) });
    expect(screen.getByTestId('fidelity-overlay-reconciliation')).toHaveTextContent(
      '4 are on constructs the graph does not draw (yet)',
    );
  });

  it('names a disagreement instead of printing a count the drawing does not carry', async () => {
    await renderPanel({ report: { ...REPORT, kind_counts: { ...REPORT.kind_counts, synth: 5 } } });
    const line = screen.getByTestId('fidelity-overlay-reconciliation');
    expect(line).toHaveAttribute('role', 'status');
    expect(line).toHaveTextContent('SYNTH counted 2, reported 5');
  });
});

// ---------------------------------------------------------------------------
// AC 2 — filters isolate kinds
// ---------------------------------------------------------------------------

describe('kind filter', () => {
  it('isolates a kind: only nodes with it stay lit, on the graph and in the table', async () => {
    await renderPanel();
    for (const kind of ['approx', 'synth', 'ok'] as const) {
      fireEvent.click(screen.getByTestId(`fidelity-overlay-kind-${kind}`));
    }
    expect(screen.getByTestId('fidelity-overlay-kind-drop')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('fidelity-overlay-kind-ok')).toHaveAttribute('aria-pressed', 'false');
    expect(node('Pet.links')).toHaveAttribute('data-dimmed', 'false');
    for (const key of ['Pet.id', 'Pet.tag', 'Pet', 'GET /pets']) {
      expect(node(key)).toHaveAttribute('data-dimmed', 'true');
      expect(node(key)).toHaveClass('xstd-fov-dimmed');
    }
    expect(screen.getByTestId(`export-mapping-table-row-${mappingRowId('Pet.id')}`)).toHaveClass(
      'xstd-fov-dimmed',
    );
    // The legend still prints the report's counts — the filter hides, it never recounts.
    expect(screen.getByTestId('fidelity-overlay-count-ok')).toHaveTextContent('2');
  });

  it('keeps a node lit when any of its items is of the active kind', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-drop'));
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-approx'));
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-ok'));
    expect(node('Pet.id')).toHaveAttribute('data-dimmed', 'false'); // worst APPROX, also SYNTH
    expect(node('Pet.tag')).toHaveAttribute('data-dimmed', 'false');
    expect(node('Pet.links')).toHaveAttribute('data-dimmed', 'true');
  });

  it('never switches the last kind off, and “Show all kinds” resets', async () => {
    await renderPanel();
    expect(screen.queryByTestId('fidelity-overlay-show-all')).not.toBeInTheDocument();
    for (const kind of ['drop', 'approx', 'synth', 'ok'] as const) {
      fireEvent.click(screen.getByTestId(`fidelity-overlay-kind-${kind}`));
    }
    expect(screen.getByTestId('fidelity-overlay-kind-ok')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByTestId('fidelity-overlay-show-all'));
    for (const kind of ['drop', 'approx', 'synth', 'ok'] as const) {
      expect(screen.getByTestId(`fidelity-overlay-kind-${kind}`)).toHaveAttribute('aria-pressed', 'true');
    }
    expect(node('Pet.links')).toHaveAttribute('data-dimmed', 'false');
  });
});

// ---------------------------------------------------------------------------
// Treemap
// ---------------------------------------------------------------------------

describe('treemap view', () => {
  it('replaces the graph with one tile per construct, grouped by path', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    expect(screen.getByTestId('fidelity-overlay-view-treemap')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('export-mapping-svg')).not.toBeInTheDocument();
    expect(screen.getByTestId('fidelity-treemap')).toBeInTheDocument();
    expect(screen.getByTestId('fidelity-treemap-group-Pet')).toBeInTheDocument();
    for (const construct of ['GET /pets', 'Pet', 'Pet.id', 'Pet.tag', 'Pet.links']) {
      expect(screen.getByTestId(`fidelity-treemap-tile-${construct}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId('fidelity-treemap-tile-Pet.links')).toHaveAttribute('data-kind', 'drop');
    expect(screen.getByTestId('fidelity-treemap-tile-Pet.id')).toHaveAttribute(
      'aria-label',
      'Pet.id: 1 approximated — represented imperfectly, 1 synthesized — invented to satisfy the target',
    );
    // The table — the text alternative — stays.
    expect(screen.getByTestId('export-mapping-table')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-graph'));
    expect(screen.getByTestId('export-mapping-svg')).toBeInTheDocument();
  });

  it('isolates kinds: only tiles with the active kinds remain', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-ok'));
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-approx'));
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-drop'));
    expect(screen.getByTestId('fidelity-treemap-tile-Pet.id')).toHaveAttribute('data-kind', 'synth');
    expect(screen.getByTestId('fidelity-treemap-tile-Pet.tag')).toBeInTheDocument();
    expect(screen.queryByTestId('fidelity-treemap-tile-Pet.links')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fidelity-treemap-tile-Pet')).not.toBeInTheDocument();
  });

  it('hover shows the detail, click and Enter select the entity', async () => {
    const { onSelectEntity } = await renderPanel();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    const tile = screen.getByTestId('fidelity-treemap-tile-Pet.links');
    fireEvent.mouseEnter(tile);
    expect(screen.getByTestId('fidelity-overlay-detail')).toHaveTextContent('proto3 has no hyperlinks');
    fireEvent.click(tile);
    expect(onSelectEntity).toHaveBeenCalledWith(expect.objectContaining({ key: 'Pet.links' }));
    fireEvent.keyDown(screen.getByTestId('fidelity-treemap-tile-Pet.id'), { key: 'Enter' });
    expect(onSelectEntity).toHaveBeenLastCalledWith(expect.objectContaining({ key: 'Pet.id' }));
  });

  it('moves focus between tiles with the arrow keys (roving tabindex)', async () => {
    await renderPanel();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    const tiles = within(screen.getByTestId('fidelity-treemap')).getAllByRole('button');
    expect(tiles.filter((t) => t.getAttribute('tabindex') === '0')).toHaveLength(1);
    tiles[0].focus();
    fireEvent.keyDown(tiles[0], { key: 'ArrowRight' });
    expect(document.activeElement).toBe(tiles[1]);
    fireEvent.keyDown(tiles[1], { key: 'End' });
    expect(document.activeElement).toBe(tiles[tiles.length - 1]);
  });

  it('says so when no finding is of the active kinds', async () => {
    await renderPanel({ report: { ...REPORT, items: ITEMS.filter((i) => i.kind === 'ok'), kind_counts: { drop: 0, approx: 0, synth: 0, ok: 2 } } });
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    // Switch OK off: the report holds nothing of the remaining kinds.
    fireEvent.click(screen.getByTestId('fidelity-overlay-kind-ok'));
    expect(screen.getByTestId('fidelity-treemap-empty')).toHaveTextContent('No findings of the selected kinds.');
  });
});

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------

describe('accessibility', () => {
  it('is axe-clean with the overlay on, in both views', async () => {
    const { container } = await renderPanel();
    expect(await axe(container)).toHaveNoViolations();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// The real Petstore → proto3 export, and the docs screenshots
// ---------------------------------------------------------------------------

const PETSTORE = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'fixtures', 'fidelityOverlayPetstoreProto.json'), 'utf-8'),
) as { report: LossinessReport; manifest: ExportPreviewManifestPage };

/** Write one docs-screenshot fixture when `FIDELITY_OVERLAY_FIXTURE_DUMP=1`. */
function dumpFixture(name: string, html: string) {
  if (process.env.FIDELITY_OVERLAY_FIXTURE_DUMP !== '1') return;
  const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'export-fidelity-overlay');
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, name), `${html}\n`);
}

describe('the Petstore exported to Protocol Buffers', () => {
  const renderPetstore = () =>
    renderPanel({
      page: PETSTORE.manifest,
      entities: PETSTORE.manifest.entities,
      report: PETSTORE.report,
      selectedEntityKey: null,
    });

  it('matches the report’s counts exactly, every finding on its construct', async () => {
    await renderPetstore();
    const counts = PETSTORE.report.kind_counts;
    for (const kind of ['drop', 'approx', 'synth', 'ok'] as const) {
      expect(screen.getByTestId(`fidelity-overlay-count-${kind}`)).toHaveTextContent(String(counts[kind]));
    }
    expect(screen.getByTestId('fidelity-overlay-reconciliation')).toHaveTextContent(
      `${PETSTORE.report.items.length} findings, the counts of the fidelity report.`,
    );
    expect(screen.getByTestId('fidelity-overlay-reconciliation')).not.toHaveTextContent(/does not draw/);
  });

  it('shows which messages and fields degrade, and how', async () => {
    await renderPetstore();
    // Every field: nullable → optional (APPROX) and a synthesized field number (SYNTH).
    for (const field of ['Pet.id', 'Pet.name', 'Pet.age', 'Category.id']) {
      expect(node(field)).toHaveAttribute('data-loss-kind', 'approx');
      expect(node(field).getAttribute('aria-label')).toMatch(/SYNTH/);
    }
    // The messages and the operations themselves are carried.
    for (const key of ['Pet', 'Category', 'GET /pets']) expect(node(key)).toHaveAttribute('data-loss-kind', 'ok');
    fireEvent.mouseEnter(node('Pet.id'));
    expect(screen.getByTestId('fidelity-overlay-detail')).toHaveTextContent('requires stable field numbers');
  });

  it('isolates the synthesized constructs', async () => {
    await renderPetstore();
    for (const kind of ['drop', 'approx', 'ok'] as const) {
      fireEvent.click(screen.getByTestId(`fidelity-overlay-kind-${kind}`));
    }
    const lit = PETSTORE.manifest.entities.filter(
      (e) => node(e.key).getAttribute('data-dimmed') === 'false',
    );
    const synthesized = new Set(PETSTORE.report.items.filter((i) => i.kind === 'synth').map((i) => i.construct));
    expect(new Set(lit.map((e) => e.key))).toEqual(synthesized);
  });

  it('draws the docs screenshots (and writes them on request)', async () => {
    const graph = await renderPetstore();
    fireEvent.mouseEnter(node('Pet.id'));
    dumpFixture('graph.html', `<div class="page">${graph.container.innerHTML}</div>`);
    graph.unmount();

    const tree = await renderPetstore();
    fireEvent.click(screen.getByTestId('fidelity-overlay-view-treemap'));
    fireEvent.mouseEnter(screen.getByTestId('fidelity-treemap-tile-Pet.weight'));
    expect(screen.getByTestId('fidelity-treemap-group-Pet')).toBeInTheDocument();
    dumpFixture('treemap.html', `<div class="page">${tree.container.innerHTML}</div>`);
  });
});
