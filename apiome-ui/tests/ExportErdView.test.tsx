/**
 * ExportErdView + the artifact viewer's ERD toggle — MFX-45.3 (#4376).
 *
 * The ticket's acceptance criteria at the component level, on a real SQL export captured from
 * apiome-rest (`fixtures/exportErdShop.json`):
 *
 *  1. A SQL export renders a correct ERD — every table with its columns (type, NOT NULL, PK / FK / UQ)
 *     and every foreign key — with the synthesized keys and the junction / child tables marked.
 *  2. Toggling between the ERD and the DDL text preserves the selection: an ERD click selects the
 *     construct (the step records it), the step's selection highlights in the ERD, and coming back to
 *     the text reveals the selected construct's line.
 *
 * React Flow is replaced by `helpers/xyflow-mock` (it renders the real table nodes); Monaco by a fake
 * that records reveals.
 */

jest.mock('@xyflow/react', () =>
  jest.requireActual<typeof import('./helpers/xyflow-mock')>('./helpers/xyflow-mock').xyflowMock(),
);

jest.mock('@monaco-editor/react', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const editor = {
    getAction: jest.fn(() => ({ run: jest.fn() })),
    getModel: () => ({ getLineCount: () => 1000, isDisposed: () => false }),
    revealLineInCenter: jest.fn(),
    setPosition: jest.fn(),
    focus: jest.fn(),
    onMouseDown: () => ({ dispose: () => undefined }),
    createDecorationsCollection: jest.fn(() => ({ clear: jest.fn(), set: jest.fn() })),
  };
  const monaco = { editor: { setModelMarkers: jest.fn() } };
  function MockMonaco({ value, onMount }: { value?: string; onMount?: (ed: typeof editor, m: typeof monaco) => void }) {
    React.useEffect(() => {
      onMount?.(editor, monaco);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return <div data-testid="mock-monaco">{value}</div>;
  }
  return { __esModule: true, default: MockMonaco, __editor: editor };
});

import React, { useState } from 'react';
import * as fs from 'fs';
import * as path from 'path';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';
import { ExportErdView } from '../src/app/components/ade/dashboard/export/ExportErdView';
import { ArtifactPreviewCard } from '../src/app/components/ade/dashboard/export/ArtifactPreviewCard';
import type { RelationalSchema } from '../src/app/components/ade/dashboard/export/exportErd';
import type {
  ExportManifestEntity,
  ExportPreviewManifestPage,
} from '../src/app/components/ade/dashboard/export/exportPreviewManifest';
import { fitViewMock } from './helpers/xyflow-mock';

expect.extend(toHaveNoViolations);

const SHOP = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportErdShop.json'), 'utf-8')) as {
  manifest: ExportPreviewManifestPage & { relational: RelationalSchema };
  script: string;
  filename: string;
};
const SCHEMA = SHOP.manifest.relational;
const ENTITIES = SHOP.manifest.entities;

const { __editor: monacoEditor } = jest.requireMock<{
  __editor: { revealLineInCenter: jest.Mock };
}>('@monaco-editor/react');

beforeEach(() => {
  fitViewMock.mockClear();
  monacoEditor.revealLineInCenter.mockClear();
});

// ---------------------------------------------------------------------------
// AC 1 — a correct ERD, made-up keys and tables marked
// ---------------------------------------------------------------------------

describe('ExportErdView', () => {
  const renderErd = (selectedEntityKey: string | null = null, onSelectEntityKey = jest.fn()) => ({
    onSelectEntityKey,
    ...render(
      <ExportErdView schema={SCHEMA} selectedEntityKey={selectedEntityKey} onSelectEntityKey={onSelectEntityKey} />,
    ),
  });

  it('draws every table with every column, and every foreign key', () => {
    renderErd();
    for (const table of SCHEMA.tables) {
      const node = screen.getByTestId(`erd-table-${table.name}`);
      for (const column of table.columns) {
        expect(within(node).getByTestId(`erd-column-${table.name}.${column.name}`)).toHaveTextContent(column.type);
      }
    }
    expect(screen.getByTestId('export-erd-summary')).toHaveTextContent(
      '5 tables · 4 foreign keys · made up by the export: 2 tables',
    );
    const shipTo = screen.getByTestId('flow-edge-fk:order:ship_to_id');
    expect(shipTo).toHaveAttribute('data-source', 'order');
    expect(shipTo).toHaveAttribute('data-target', 'address');
    expect(shipTo).toHaveAttribute('data-aria-label', 'Foreign key ship_to_id → address.id, made up by the export');
  });

  it('marks the made-up junction and child tables, keys and references', () => {
    renderErd();
    expect(screen.getByTestId('erd-table-order_lines')).toHaveAttribute('data-synthesized', 'true');
    expect(screen.getByTestId('erd-table-synth-order_lines')).toHaveTextContent('SYNTH');
    expect(screen.getByTestId('erd-table-select-order_lines')).toHaveTextContent('junction');
    expect(screen.getByTestId('erd-table-select-order_tags')).toHaveTextContent('child table');
    expect(screen.queryByTestId('erd-table-synth-order')).not.toBeInTheDocument();

    const key = screen.getByTestId('erd-column-order.id');
    expect(key).toHaveAttribute('data-synthesized', 'true');
    expect(key).toHaveTextContent('PK');
    expect(key).toHaveTextContent('✚ id');
    expect(key).toHaveAttribute('aria-label', 'order.id: BIGINT, primary key, not null, generated, made up by the export');
    const ref = screen.getByTestId('erd-column-order.ship_to_id');
    expect(ref).toHaveTextContent('FK');
    expect(ref).toHaveAttribute('data-synthesized', 'true');
    // A declared key is not made up.
    expect(screen.getByTestId('erd-column-address.id')).toHaveAttribute('data-synthesized', 'false');
    expect(screen.getByTestId('erd-column-order.user')).toHaveTextContent('NOT NULL');
    expect(screen.getByTestId('flow-edge-fk:order:ship_to_id').getAttribute('data-class')).toContain(
      'xstd-erd__edge--synth',
    );
  });

  it('selects the construct a table or a column came from', () => {
    const { onSelectEntityKey } = renderErd();
    fireEvent.click(screen.getByTestId('erd-table-select-order'));
    expect(onSelectEntityKey).toHaveBeenLastCalledWith('Order');
    fireEvent.click(screen.getByTestId('erd-table-select-order_lines'));
    expect(onSelectEntityKey).toHaveBeenLastCalledWith('Order.lines');
    fireEvent.click(screen.getByTestId('erd-column-order.ship_to_id'));
    expect(onSelectEntityKey).toHaveBeenLastCalledWith('Order.shipTo');
  });

  it('highlights the selected construct, labels its keys and brings its table into view', () => {
    renderErd('Order');
    expect(screen.getByTestId('erd-table-select-order')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('erd-table-order')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('erd-column-order.id')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('erd-table-select-address')).toHaveAttribute('aria-pressed', 'false');
    // Only the focused table's keys carry a visible label.
    expect(screen.getByTestId('flow-edge-fk:order:ship_to_id')).toHaveTextContent('ship_to_id → address.id');
    expect(screen.getByTestId('flow-edge-fk:order_lines:order_line_id')).toHaveTextContent('');
    expect(fitViewMock).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: [{ id: 'order' }] }));
  });

  it('is axe-clean', async () => {
    const { container } = renderErd('Order.shipTo');
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// AC 2 — the toggle keeps the selection
// ---------------------------------------------------------------------------

/** The card wired the way the Review step wires it: one selection, recorded by the step. */
function Harness({ relational = SCHEMA }: { relational?: RelationalSchema | null }) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <span data-testid="step-selection">{selected ?? ''}</span>
      <ArtifactPreviewCard
        artifact={{ filename: SHOP.filename, mediaType: 'application/sql', text: SHOP.script }}
        report={null}
        targetKey="sql-ddl"
        manifestEntities={ENTITIES as ExportManifestEntity[]}
        selectedEntityKey={selected}
        relational={relational}
        onSelectEntity={(entity) => setSelected(entity.key)}
        onEntityLineClick={(entity) => setSelected(entity.key)}
      />
      <button type="button" onClick={() => setSelected('Address')}>
        select Address from the tree
      </button>
    </>
  );
}

describe('ArtifactPreviewCard ERD toggle', () => {
  it('offers no toggle for a target without a relational projection', async () => {
    render(<Harness relational={null} />);
    await act(async () => {});
    expect(screen.queryByTestId('export-artifact-view-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('export-erd')).not.toBeInTheDocument();
  });

  it('switches between the DDL text and the ERD', async () => {
    render(<Harness />);
    await act(async () => {});
    expect(screen.getByTestId('export-artifact-view-text')).toHaveTextContent('DDL text');
    expect(screen.getByTestId('export-artifact-view-text')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('export-erd')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('export-artifact-view-erd'));
    expect(screen.getByTestId('export-artifact-view-erd')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('export-erd')).toBeInTheDocument();
    // The text stays mounted under the ERD (its selection decoration survives), just hidden.
    expect(screen.getByTestId('export-artifact-text-view')).not.toBeVisible();

    fireEvent.click(screen.getByTestId('export-artifact-view-text'));
    expect(screen.queryByTestId('export-erd')).not.toBeInTheDocument();
    expect(screen.getByTestId('export-artifact-text-view')).toBeVisible();
  });

  it('keeps an ERD selection when going back to the text, and reveals its line there', async () => {
    render(<Harness />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId('export-artifact-view-erd'));
    fireEvent.click(screen.getByTestId('erd-column-order.ship_to_id'));
    expect(screen.getByTestId('step-selection')).toHaveTextContent('Order.shipTo');

    fireEvent.click(screen.getByTestId('export-artifact-view-text'));
    const line = ENTITIES.find((e) => e.key === 'Order.shipTo')!.location!.line;
    expect(monacoEditor.revealLineInCenter).toHaveBeenLastCalledWith(line);
    expect(screen.getByTestId('step-selection')).toHaveTextContent('Order.shipTo');
  });

  it('keeps a text-side selection when going to the ERD, highlighted there', async () => {
    render(<Harness />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'select Address from the tree' }));
    fireEvent.click(screen.getByTestId('export-artifact-view-erd'));
    expect(screen.getByTestId('erd-table-select-address')).toHaveAttribute('aria-pressed', 'true');
    expect(fitViewMock).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: [{ id: 'address' }] }));
  });

  it('names the text after the output: DBML, Prisma schema, Changelog', async () => {
    const { rerender } = render(<Harness relational={{ ...SCHEMA, output: 'dbml' }} />);
    await act(async () => {});
    expect(screen.getByTestId('export-artifact-view-text')).toHaveTextContent('DBML text');
    rerender(<Harness relational={{ ...SCHEMA, output: 'prisma' }} />);
    expect(screen.getByTestId('export-artifact-view-text')).toHaveTextContent('Prisma schema text');
    rerender(<Harness relational={{ ...SCHEMA, output: 'flyway' }} />);
    expect(screen.getByTestId('export-artifact-view-text')).toHaveTextContent('Changelog text');
  });
});
