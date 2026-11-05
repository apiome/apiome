/**
 * Paradigm-specific pictures of an export — MFX-45.4 (#4377).
 *
 * The ticket's acceptance criteria at the component level, on real manifests captured from apiome-rest
 * (`fixtures/exportVizGraphs.json`):
 *
 *  1. Each mode renders for its family and is absent otherwise — a proto bundle offers an **Import
 *     graph** and a **Service map**, an AsyncAPI or xRegistry export a **Channel topology**, and a target
 *     that declares none (or has no data for one) shows no switch.
 *  2. The mode choice persists per target in the session: a viewer for the same target opens on the
 *     mode last chosen for it, a viewer for another target on its own choice.
 *
 * Plus the graph view itself: nodes in words, external nodes marked, selection shared with the step.
 * React Flow is replaced by `helpers/xyflow-mock` (it renders the real nodes); Monaco by a fake.
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
import { act, fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';
import { ExportVizGraphView } from '../src/app/components/ade/dashboard/export/ExportVizGraphView';
import { ArtifactPreviewCard } from '../src/app/components/ade/dashboard/export/ArtifactPreviewCard';
import { BundleExplorer } from '../src/app/components/ade/dashboard/export/BundleExplorer';
import { buildBundleManifest } from '../src/app/components/ade/dashboard/export/exportBundle';
import type { ExportVizMode, VizGraph } from '../src/app/components/ade/dashboard/export/exportViz';
import type { ExportManifestEntity } from '../src/app/components/ade/dashboard/export/exportPreviewManifest';
import { fitViewMock } from './helpers/xyflow-mock';

expect.extend(toHaveNoViolations);

interface Captured {
  viz_modes: ExportVizMode[];
  entities: ExportManifestEntity[];
  views: Record<string, VizGraph>;
  files: { path: string; text: string }[];
}
const CAPTURED = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'exportVizGraphs.json'), 'utf-8')) as Record<
  'proto3' | 'asyncapi' | 'xregistry',
  Captured
>;
const PROTO = CAPTURED.proto3;
const ASYNC = CAPTURED.asyncapi;
const XREG = CAPTURED.xregistry;

const { __editor: monacoEditor } = jest.requireMock<{ __editor: { revealLineInCenter: jest.Mock } }>(
  '@monaco-editor/react',
);

beforeEach(() => {
  fitViewMock.mockClear();
  monacoEditor.revealLineInCenter.mockClear();
  window.sessionStorage.clear();
});

// ---------------------------------------------------------------------------
// The graph view
// ---------------------------------------------------------------------------

describe('ExportVizGraphView', () => {
  const renderGraph = (graph: VizGraph, selected: string | null = null, onSelect = jest.fn()) => ({
    onSelect,
    ...render(<ExportVizGraphView graph={graph} title="Service map" selectedEntityKey={selected} onSelectEntityKey={onSelect} />),
  });

  it('draws a service map: services, methods and the messages they take and return', () => {
    renderGraph(PROTO.views['service-map']);
    expect(screen.getByTestId('export-viz-service-map')).toBeInTheDocument();
    expect(screen.getByTestId('export-viz-summary')).toHaveTextContent('1 service · 5 methods · 2 messages · 1 external');
    expect(screen.getByTestId('viz-node-method:default.getPetById')).toHaveAccessibleName('Method getPetById');
    const empty = screen.getByTestId('viz-node-message:google.protobuf.Empty');
    expect(empty).toHaveAttribute('data-external', 'true');
    expect(empty).toBeDisabled();
    expect(empty).toHaveAttribute('title', 'This node has no source construct to select');
    expect(screen.getByTestId('flow-edge-response:method:default.getPetById->message:Pet')).toHaveTextContent('response');
  });

  it('selects the construct a node stands for, and highlights and focuses the step’s selection', () => {
    const { onSelect } = renderGraph(PROTO.views['service-map'], 'Pet');
    fireEvent.click(screen.getByTestId('viz-node-method:default.createPet'));
    expect(onSelect).toHaveBeenCalledWith('POST /pets');
    expect(screen.getByTestId('viz-node-message:Pet')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('viz-node-service:default')).toHaveAttribute('aria-pressed', 'false');
    expect(fitViewMock).toHaveBeenLastCalledWith(expect.objectContaining({ nodes: [{ id: 'message:Pet' }] }));
  });

  it('draws an AsyncAPI and an xRegistry channel topology', () => {
    const { unmount } = renderGraph(ASYNC.views['channel-topology']);
    expect(screen.getByTestId('viz-node-channel:orderPlaced')).toHaveAccessibleName('Channel orderPlaced, order/placed');
    expect(screen.getByTestId('viz-node-operation:receiveOrderPlaced')).toHaveAccessibleName(
      'Operation receiveOrderPlaced, receive',
    );
    unmount();
    renderGraph(XREG.views['channel-topology']);
    expect(screen.getByTestId('viz-node-type:order/placed')).toHaveAccessibleName('Event type order/placed');
    expect(screen.getByTestId('viz-node-group:default')).toHaveAccessibleName('Message group default, CloudEvents/1.0');
  });

  it('is axe-clean', async () => {
    const { container } = renderGraph(PROTO.views['service-map'], 'Pet');
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ---------------------------------------------------------------------------
// The single-document viewer
// ---------------------------------------------------------------------------

function Card({ data, targetKey, vizModes }: { data: Captured; targetKey: string; vizModes?: ExportVizMode[] | null }) {
  const [selected, setSelected] = useState<string | null>(null);
  const file = data.files[0];
  return (
    <>
      <span data-testid="step-selection">{selected ?? ''}</span>
      <ArtifactPreviewCard
        artifact={{ filename: file.path, mediaType: 'application/json', text: file.text }}
        report={null}
        targetKey={targetKey}
        manifestEntities={data.entities}
        selectedEntityKey={selected}
        views={data.views}
        vizModes={vizModes === undefined ? data.viz_modes : vizModes}
        onSelectEntity={(entity) => setSelected(entity.key)}
      />
    </>
  );
}

describe('ArtifactPreviewCard — modes for its family', () => {
  it('offers the channel topology of an AsyncAPI export', async () => {
    render(<Card data={ASYNC} targetKey="asyncapi-3" />);
    await act(async () => {});
    expect(screen.getByTestId('export-artifact-view-text')).toHaveTextContent('Text');
    fireEvent.click(screen.getByTestId('export-artifact-view-channel-topology'));
    expect(screen.getByTestId('export-viz-channel-topology')).toBeInTheDocument();
    expect(screen.getByTestId('export-artifact-text-view')).not.toBeVisible();
    fireEvent.click(screen.getByTestId('viz-node-channel:orderPlaced'));
    expect(screen.getByTestId('step-selection')).toHaveTextContent('order/placed');
  });

  it('shows no switch for a target that declares no mode, whatever the data', async () => {
    render(<Card data={ASYNC} targetKey="openapi-3.1" vizModes={[]} />);
    await act(async () => {});
    expect(screen.queryByTestId('export-artifact-view-toggle')).not.toBeInTheDocument();
  });

  it('shows no switch for a declared mode with nothing to draw', async () => {
    render(<Card data={{ ...ASYNC, views: {} }} targetKey="asyncapi-3" />);
    await act(async () => {});
    expect(screen.queryByTestId('export-artifact-view-toggle')).not.toBeInTheDocument();
  });

  it('remembers the chosen mode per target for the session', async () => {
    const first = render(<Card data={ASYNC} targetKey="asyncapi-3" />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId('export-artifact-view-channel-topology'));
    first.unmount();

    // The same target opens on its mode again…
    const again = render(<Card data={ASYNC} targetKey="asyncapi-3" />);
    await act(async () => {});
    expect(screen.getByTestId('export-artifact-view-channel-topology')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('export-viz-channel-topology')).toBeInTheDocument();
    again.unmount();

    // …another target on its own choice (the text, never chosen).
    render(<Card data={XREG} targetKey="xregistry" />);
    await act(async () => {});
    expect(screen.getByTestId('export-artifact-view-text')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('export-viz-channel-topology')).not.toBeInTheDocument();
  });

  it('restores the remembered mode once the manifest’s data arrives', async () => {
    window.sessionStorage.setItem('apiome.export.view.asyncapi-3', 'channel-topology');
    const { rerender } = render(<Card data={{ ...ASYNC, views: {} }} targetKey="asyncapi-3" />);
    await act(async () => {});
    expect(screen.queryByTestId('export-viz-channel-topology')).not.toBeInTheDocument();
    rerender(<Card data={ASYNC} targetKey="asyncapi-3" />);
    expect(screen.getByTestId('export-viz-channel-topology')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// The bundle explorer
// ---------------------------------------------------------------------------

const EMPTY_PROTO = { path: 'google/protobuf/empty.proto', text: 'syntax = "proto3";\npackage google.protobuf;\nmessage Empty {}\n' };

function Bundle({ vizModes = PROTO.viz_modes, targetKey = 'protobuf' }: { vizModes?: ExportVizMode[] | null; targetKey?: string }) {
  const [selected, setSelected] = useState<string | null>(null);
  const manifest = buildBundleManifest([...PROTO.files, EMPTY_PROTO].map((f) => ({ path: f.path, text: f.text, mediaType: 'text/plain' })));
  return (
    <>
      <span data-testid="step-selection">{selected ?? ''}</span>
      <BundleExplorer
        manifest={manifest}
        countsByPath={new Map()}
        targetKey={targetKey}
        manifestEntities={PROTO.entities}
        selectedEntityKey={selected}
        views={PROTO.views}
        vizModes={vizModes}
        onSelectEntity={(entity) => setSelected(entity.key)}
        onEntityLineClick={(entity) => setSelected(entity.key)}
      />
    </>
  );
}

describe('BundleExplorer — a proto bundle’s import graph and service map', () => {
  it('offers both modes beside the files', async () => {
    render(<Bundle />);
    await act(async () => {});
    expect(screen.getByTestId('bundle-view-text')).toHaveTextContent('Files');
    expect(screen.getByTestId('bundle-view-proto-imports')).toHaveTextContent('Import graph');
    expect(screen.getByTestId('bundle-view-service-map')).toHaveTextContent('Service map');

    fireEvent.click(screen.getByTestId('bundle-view-proto-imports'));
    expect(screen.getByTestId('export-viz-proto-imports')).toBeInTheDocument();
    expect(screen.getByTestId('bundle-text-view')).not.toBeVisible();
    expect(screen.getByTestId('flow-edge-import:file:api.proto->file:google/protobuf/empty.proto')).toBeInTheDocument();
  });

  it('keeps a service-map selection when going back to the files, and reveals its line', async () => {
    render(<Bundle />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId('bundle-view-service-map'));
    fireEvent.click(screen.getByTestId('viz-node-message:Pet'));
    expect(screen.getByTestId('step-selection')).toHaveTextContent('Pet');

    fireEvent.click(screen.getByTestId('bundle-view-text'));
    await act(async () => {});
    const line = PROTO.entities.find((e) => e.key === 'Pet')!.location!.line;
    expect(monacoEditor.revealLineInCenter).toHaveBeenLastCalledWith(line);
  });

  it('shows no switch when the target declares no mode', async () => {
    render(<Bundle vizModes={[]} targetKey="avro" />);
    await act(async () => {});
    expect(screen.queryByTestId('bundle-view-toggle')).not.toBeInTheDocument();
  });

  it('remembers the bundle’s mode per target', async () => {
    const first = render(<Bundle />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId('bundle-view-service-map'));
    first.unmount();
    render(<Bundle />);
    await act(async () => {});
    expect(screen.getByTestId('bundle-view-service-map')).toHaveAttribute('aria-pressed', 'true');
  });
});
