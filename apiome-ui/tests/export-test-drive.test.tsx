/**
 * The Review step's Test drive tabs — MFX-44.1 (#4367).
 *
 * - `testDriveTabs` turns a target's registry `test_tools` into one tab per drawable kind, in registry
 *   order, grouping several tools of a kind and skipping kinds this build cannot draw;
 * - a tab whose every tool is unavailable is disabled, with the server's reasons;
 * - `TestDrivePanel` draws the tabs from the data alone: a kind it has never seen appears as soon as a
 *   renderer for it exists, and a target without tools draws nothing;
 * - disabled tabs do not open and the arrow keys skip them; the toolchain tab lists each check's status.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  initialTestDriveTab,
  testDriveTabs,
  type ExportTestTool,
} from '../src/app/components/ade/dashboard/export/exportTestDrive';
import {
  TestDrivePanel,
  type TestDriveRenderers,
} from '../src/app/components/ade/dashboard/export/TestDrivePanel';
import { ToolchainChecksConsole } from '../src/app/components/ade/dashboard/export/ToolchainChecksConsole';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const tool = (kind: string, label: string, extra: Partial<ExportTestTool> = {}): ExportTestTool => ({
  kind,
  label,
  params: {},
  server_side: kind === 'mock-server' || kind === 'toolchain',
  available: true,
  unavailable_reason: null,
  ...extra,
});

const OPENAPI: ExportTestTool[] = [
  tool('swagger-ui', 'Swagger UI'),
  tool('redoc', 'ReDoc'),
  tool('toolchain', 'redocly lint', { params: { tool: 'redocly', check: 'lint' } }),
  tool('mock-server', 'Mock server', { available: false, unavailable_reason: 'Export test-drive mocks are disabled on this server.' }),
];

const PROTO: ExportTestTool[] = [
  tool('toolchain', 'buf lint', { available: false, unavailable_reason: 'The buf toolchain is not installed on this server.' }),
  tool('toolchain', 'buf build', { available: false, unavailable_reason: 'The buf toolchain is not installed on this server.' }),
];

const RENDERERS: TestDriveRenderers = {
  'swagger-ui': () => <p>swagger body</p>,
  'mock-server': () => <p>mock body</p>,
  toolchain: (tab) => <ToolchainChecksConsole tools={tab.tools} runs={{}} onRun={() => undefined} />,
};

describe('testDriveTabs', () => {
  it('keeps registry order, groups a kind and skips kinds this build cannot draw', () => {
    const tabs = testDriveTabs(OPENAPI, new Set(['swagger-ui', 'toolchain', 'mock-server']));
    expect(tabs.map((tab) => [tab.kind, tab.label, tab.available])).toEqual([
      ['swagger-ui', 'Swagger UI', true],
      ['toolchain', 'redocly lint', true],
      ['mock-server', 'Mock server', false],
    ]);
    expect(tabs[2].reason).toBe('Export test-drive mocks are disabled on this server.');
    expect(initialTestDriveTab(tabs)).toBe('swagger-ui');
  });

  it('names a tab of several checks by its kind and joins distinct reasons', () => {
    const [tab] = testDriveTabs(PROTO, new Set(['toolchain']));
    expect(tab.label).toBe('Toolchain checks');
    expect(tab.tools).toHaveLength(2);
    expect(tab.available).toBe(false);
    expect(tab.reason).toBe('The buf toolchain is not installed on this server.');
    expect(initialTestDriveTab([tab])).toBeNull();
  });

  it('is available when any one tool of the kind is, and treats a missing flag as available', () => {
    const [tab] = testDriveTabs(
      [PROTO[0], { kind: 'toolchain', label: 'tsp compile', server_side: true }],
      new Set(['toolchain']),
    );
    expect(tab.available).toBe(true);
    expect(tab.reason).toBeNull();
  });

  it('has no tabs for a target without tools or an older server', () => {
    expect(testDriveTabs([], new Set(['toolchain']))).toEqual([]);
    expect(testDriveTabs(undefined, new Set(['toolchain']))).toEqual([]);
  });
});

describe('TestDrivePanel', () => {
  it('draws a tab per declared, drawable kind and opens the first available one', () => {
    render(<TestDrivePanel tools={OPENAPI} targetKey="openapi" renderers={RENDERERS} />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Swagger UI', 'redocly lint', 'Mock server']);
    expect(screen.getByTestId('test-drive-body-swagger-ui')).toHaveTextContent('swagger body');
    fireEvent.click(screen.getByTestId('test-drive-tab-toolchain'));
    expect(screen.getByTestId('toolchain-checks')).toHaveTextContent('redocly lint');
    expect(screen.getByTestId('toolchain-checks')).toHaveTextContent('Installed on this server');
  });

  it('draws an unavailable tool disabled, with the reason, and does not open it', () => {
    render(<TestDrivePanel tools={OPENAPI} targetKey="openapi" renderers={RENDERERS} />);
    const mock = screen.getByTestId('test-drive-tab-mock-server');
    expect(mock).toHaveAttribute('aria-disabled', 'true');
    expect(mock).toHaveAttribute('title', 'Export test-drive mocks are disabled on this server.');
    expect(screen.getByTestId('test-drive-unavailable')).toHaveTextContent(
      'Mock server is unavailable on this server: Export test-drive mocks are disabled on this server.',
    );
    fireEvent.click(mock);
    expect(screen.queryByText('mock body')).not.toBeInTheDocument();
  });

  it('moves between the tabs that open with the arrow keys, skipping disabled ones', () => {
    render(<TestDrivePanel tools={OPENAPI} targetKey="openapi" renderers={RENDERERS} />);
    const list = screen.getByRole('tablist');
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(screen.getByTestId('test-drive-tab-toolchain')).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(screen.getByTestId('test-drive-tab-swagger-ui')).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(list, { key: 'End' });
    expect(screen.getByTestId('test-drive-tab-toolchain')).toHaveAttribute('aria-selected', 'true');
  });

  it('shows only the reasons when nothing can run here', () => {
    render(<TestDrivePanel tools={PROTO} targetKey="protobuf" renderers={RENDERERS} />);
    expect(screen.getByTestId('test-drive-tab-toolchain')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument();
    expect(screen.getByTestId('test-drive-unavailable')).toHaveTextContent('Toolchain checks is unavailable on this server');
  });

  it('follows the registry: tabs change with the target, and a new kind needs only its renderer', () => {
    const { rerender } = render(<TestDrivePanel tools={OPENAPI} targetKey="openapi" renderers={RENDERERS} />);
    rerender(<TestDrivePanel tools={[tool('graphiql', 'GraphiQL')]} targetKey="graphql" renderers={RENDERERS} />);
    expect(screen.queryByTestId('test-drive-panel')).not.toBeInTheDocument();
    rerender(
      <TestDrivePanel
        tools={[tool('graphiql', 'GraphiQL')]}
        targetKey="graphql"
        renderers={{ ...RENDERERS, graphiql: () => <p>graphiql body</p> }}
      />,
    );
    const panel = screen.getByTestId('test-drive-panel');
    expect(within(panel).getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['GraphiQL']);
    expect(within(panel).getByText('graphiql body')).toBeInTheDocument();
  });
});

/**
 * The documentation site's Export studio page (`apiome-docs/screens.json`, id `export-studio-test-drive`)
 * captures the strip from this dump: `A11Y_FIXTURE_DUMP=1 npx jest tests/export-test-drive.test.tsx -t
 * "docs fixture"` — an OpenAPI target on a server with `redocly` installed and mocks disabled, as the
 * registry reports it (Swagger UI and ReDoc have no renderer in this build yet).
 */
describe('the docs fixture', () => {
  it('renders an OpenAPI target with a toolchain check open and the mock unavailable', () => {
    render(<TestDrivePanel tools={OPENAPI} targetKey="openapi" renderers={{
      'mock-server': RENDERERS['mock-server'], toolchain: RENDERERS.toolchain,
    }} />);
    expect(screen.getByTestId('test-drive-tab-toolchain')).toHaveAttribute('aria-selected', 'true');
    writeA11yFixture('export-studio-test-drive', document.body.firstElementChild!.outerHTML);
  });
});
