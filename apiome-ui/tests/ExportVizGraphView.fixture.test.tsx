/**
 * The docs screenshots `export-viz-service-map` and `export-viz-channel-topology` (MFX-45.4) are drawn
 * from these dumps: the real React Flow renders the graphs apiome-rest built for the Petstore exported to
 * Protocol Buffers and for the order-events AsyncAPI document (`fixtures/exportVizGraphs.json`). Written
 * only with `VIZ_FIXTURE_DUMP=1`.
 */

import React from 'react';
import * as fs from 'fs';
import * as path from 'path';
import { act, render } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ExportVizGraphView } from '../src/app/components/ade/dashboard/export/ExportVizGraphView';
import type { VizGraph } from '../src/app/components/ade/dashboard/export/exportViz';
import { polyfillSvgBBox, writeFlowFixture } from './helpers/flow-fixture';

const CAPTURED = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportVizGraphs.json'), 'utf-8')) as Record<
  string,
  { views: Record<string, VizGraph> }
>;

beforeAll(() => polyfillSvgBBox());

describe('ExportVizGraphView — docs fixtures', () => {
  it.each([
    ['proto3', 'service-map', 'Service map', 'Pet', 'service-map.html'],
    ['asyncapi', 'channel-topology', 'Channel topology', 'order/placed', 'channel-topology.html'],
  ])('draws the %s %s with the real React Flow (and writes it on request)', async (source, mode, title, selected, file) => {
    const graph = CAPTURED[source].views[mode];
    const { container } = render(
      <div className="page">
        <ExportVizGraphView graph={graph} title={title} selectedEntityKey={selected} onSelectEntityKey={() => {}} />
      </div>,
    );
    await act(async () => {});
    expect(container.querySelectorAll('.react-flow__node').length).toBe(graph.nodes.length);
    expect(container.querySelectorAll('.react-flow__edge').length).toBe(graph.edges.length);
    if (process.env.VIZ_FIXTURE_DUMP === '1') writeFlowFixture('export-viz', file, container.innerHTML);
  });
});
