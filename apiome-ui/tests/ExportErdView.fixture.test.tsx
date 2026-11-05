/**
 * The docs screenshot `export-erd` (MFX-45.3) is drawn from this dump: the real React Flow renders the
 * SQL export captured in `fixtures/exportErdShop.json` (tables with known sizes and handles draw without
 * measuring), with React Flow's own stylesheet inlined. Written only with `ERD_FIXTURE_DUMP=1`.
 */

import React from 'react';
import * as fs from 'fs';
import * as path from 'path';
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ExportErdView } from '../src/app/components/ade/dashboard/export/ExportErdView';
import type { RelationalSchema } from '../src/app/components/ade/dashboard/export/exportErd';
import { polyfillSvgBBox, writeFlowFixture } from './helpers/flow-fixture';

const SHOP = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportErdShop.json'), 'utf-8')) as {
  manifest: { relational: RelationalSchema };
};

beforeAll(() => polyfillSvgBBox());

describe('ExportErdView — docs fixture', () => {
  it('draws the tables and their foreign keys with the real React Flow (and writes it on request)', async () => {
    const { container } = render(
      <div className="page">
        <ExportErdView schema={SHOP.manifest.relational} selectedEntityKey="Order.shipTo" onSelectEntityKey={() => {}} />
      </div>,
    );
    await act(async () => {});
    for (const table of SHOP.manifest.relational.tables) {
      expect(screen.getByTestId(`erd-table-${table.name}`)).toBeInTheDocument();
    }
    expect(container.querySelectorAll('.react-flow__edge').length).toBe(4);
    if (process.env.ERD_FIXTURE_DUMP === '1') writeFlowFixture('export-erd', 'erd.html', container.innerHTML);
  });
});
