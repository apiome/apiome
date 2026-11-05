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

const SHOP = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportErdShop.json'), 'utf-8')) as {
  manifest: { relational: RelationalSchema };
};

// jsdom has no SVG layout: React Flow sizes an edge label's background from `getBBox`.
beforeAll(() => {
  const proto = window.SVGElement.prototype as unknown as { getBBox?: () => DOMRect };
  // Roughly the label's monospace width, so the background fits its text.
  proto.getBBox ??= function getBBox(this: SVGElement) {
    return { x: 0, y: 0, width: (this.textContent ?? '').length * 6.6, height: 14 } as DOMRect;
  };
});

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
    if (process.env.ERD_FIXTURE_DUMP === '1') {
      const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'export-erd');
      fs.mkdirSync(out, { recursive: true });
      // The app imports React Flow's stylesheet with the component; the fixture page only has the app's
      // own CSS, so the dump carries it inline.
      // (Read from node_modules directly: under Jest the module resolver maps `.css` to a stub.)
      const flowCss = fs.readFileSync(
        [path.join(__dirname, '..', 'node_modules'), path.join(__dirname, '..', '..', 'node_modules')]
          .map((root) => path.join(root, '@xyflow', 'react', 'dist', 'style.css'))
          .find((file) => fs.existsSync(file))!,
        'utf-8',
      );
      fs.writeFileSync(path.join(out, 'erd.html'), `${container.innerHTML}<style>${flowCss}</style>\n`);
    }
  });
});
