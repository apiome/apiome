/**
 * RoundtripComparisonPanel — the Review step's round-trip evidence panel (IXH-4.4, #5112).
 *
 * Pins the ticket's UI acceptance criteria:
 *
 *  - the action is explicit: an unrun panel renders a "Run round-trip check" button and
 *    triggers nothing on its own;
 *  - differences render grouped — expected (each paired with the fidelity finding that
 *    explains it) versus unexplained/over-claimed, flagged as a fidelity bug;
 *  - unexplained differences offer the one-click issue-report link, carrying reproduction
 *    coordinates and naming any withheld credential-shaped option keys;
 *  - a target with no import adapter shows the skip explanation instead of a result;
 *  - a transport failure degrades to a retryable notice and never gates the export;
 *  - the panel has no axe violations in its key states.
 */

import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';
import { jest } from '@jest/globals';
import * as fs from 'fs';
import * as path from 'path';

import { RoundtripComparisonPanel } from '../src/app/components/ade/dashboard/export/RoundtripComparisonPanel';
import type { ExportRoundtripResponse } from '../src/app/components/ade/dashboard/export/exportRoundtrip';

expect.extend(toHaveNoViolations);

// Monaco does not run in jsdom: the diff viewer is stood in for by its two texts (MFX-43.4).
jest.mock('@/app/components/ui/code/JsonDiffViewer', () => ({
  JsonDiffViewer: ({ original, modified, language }: { original: string; modified: string; language?: string }) =>
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require('react').createElement('div', {
      'data-testid': 'json-diff-viewer',
      'data-original': original,
      'data-modified': modified,
      'data-language': language,
    }),
}));

function response(overrides: Partial<ExportRoundtripResponse> = {}): ExportRoundtripResponse {
  return {
    artifact: 'proj-1',
    version: '1.0.0',
    version_record_id: 'rev-1',
    version_label: '1.0.0',
    target: 'openapi-3.1',
    emit_key: 'openapi',
    adapter_key: 'openapi',
    status: 'pass',
    reason: null,
    diff_count: 0,
    matched_count: 0,
    matched: [],
    unexplained: [],
    overclaims: [],
    loss_drop: 0,
    loss_approx: 0,
    loss_synth: 0,
    loss_ok: 4,
    source_fingerprint: 'aaaa1111bbbb2222',
    reimported_fingerprint: 'aaaa1111bbbb2222',
    emitter_version: '1.0',
    apiome_version: '1.107.0',
    registry_version: '1',
    ...overrides,
  };
}

const baseProps = {
  result: null,
  running: false,
  hasRun: false,
  error: null,
  fromCache: false,
  onRun: jest.fn(),
  targetLabel: 'OpenAPI 3.1',
};

afterEach(() => jest.clearAllMocks());

describe('RoundtripComparisonPanel', () => {
  it('offers an explicit action when unrun, and triggers nothing on its own', () => {
    const onRun = jest.fn();
    render(<RoundtripComparisonPanel {...baseProps} onRun={onRun} />);
    expect(screen.getByTestId('roundtrip-run')).toBeInTheDocument();
    expect(onRun).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('roundtrip-run'));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it('states what is happening while the loop runs', () => {
    render(<RoundtripComparisonPanel {...baseProps} running />);
    expect(screen.getByTestId('roundtrip-running')).toHaveTextContent(/re-importing/i);
  });

  it('degrades a transport failure to a retryable notice', () => {
    const onRun = jest.fn();
    render(
      <RoundtripComparisonPanel {...baseProps} hasRun error="upstream 502" onRun={onRun} />,
    );
    expect(screen.getByTestId('roundtrip-error')).toHaveTextContent('upstream 502');
    expect(screen.getByTestId('roundtrip-error')).toHaveTextContent(/unaffected/);
    fireEvent.click(screen.getByTestId('roundtrip-retry'));
    expect(onRun).toHaveBeenCalledWith(true);
  });

  it('presents a verified round trip with its summary and provenance', () => {
    render(<RoundtripComparisonPanel {...baseProps} hasRun result={response()} />);
    expect(screen.getByTestId('roundtrip-status-pass')).toHaveTextContent('Round trip verified');
    expect(screen.getByTestId('roundtrip-summary')).toHaveTextContent(/identical to the source/);
    expect(screen.getByTestId('roundtrip-provenance')).toHaveTextContent('source aaaa1111bbbb');
    expect(screen.queryByTestId('roundtrip-report-issue')).not.toBeInTheDocument();
  });

  it('labels a cached result as restored and offers a re-run', () => {
    const onRun = jest.fn();
    render(
      <RoundtripComparisonPanel {...baseProps} hasRun fromCache result={response()} onRun={onRun} />,
    );
    expect(screen.getByTestId('roundtrip-from-cache')).toHaveTextContent(/restored/);
    fireEvent.click(screen.getByTestId('roundtrip-rerun'));
    expect(onRun).toHaveBeenCalledWith(true);
  });

  it('groups differences into expected (paired with findings) and unexplained', () => {
    const result = response({
      status: 'fail',
      diff_count: 2,
      matched_count: 1,
      matched: [
        {
          entry: { entity: 'type', key: 'Org', change: 'removed' },
          finding: {
            construct: 'Org',
            kind: 'drop',
            severity: 'warn',
            message: 'target cannot carry Org',
            target_mapping: null,
          },
        },
      ],
      unexplained: [{ entity: 'type', key: 'User', change: 'removed' }],
      overclaims: [
        {
          construct: 'Status',
          kind: 'ok',
          severity: 'info',
          message: 'preserved',
          target_mapping: null,
        },
      ],
      reimported_fingerprint: 'cccc3333dddd4444',
    });
    render(<RoundtripComparisonPanel {...baseProps} hasRun result={result} />);

    const explained = screen.getByTestId('roundtrip-explained');
    expect(explained).toHaveTextContent('Expected differences · explained by the fidelity report (1)');
    expect(explained).toHaveTextContent('Org');
    expect(explained).toHaveTextContent('target cannot carry Org');

    const unexplained = screen.getByTestId('roundtrip-unexplained');
    expect(unexplained).toHaveTextContent('Unexplained differences (2)');
    expect(unexplained).toHaveTextContent('User');
    expect(screen.getByTestId('roundtrip-overclaim')).toHaveTextContent('Status');

    expect(screen.getByTestId('roundtrip-status-fail')).toHaveTextContent(/fidelity bug/i);
  });

  it('offers the one-click issue report carrying reproduction coordinates, secrets stripped', () => {
    const result = response({
      status: 'fail',
      diff_count: 1,
      unexplained: [{ entity: 'type', key: 'User', change: 'removed' }],
    });
    render(
      <RoundtripComparisonPanel
        {...baseProps}
        hasRun
        result={result}
        options={{ package: 'com.example', api_token: 'hunter2' }}
      />,
    );
    const link = screen.getByTestId('roundtrip-report-issue');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    const href = link.getAttribute('href') ?? '';
    expect(href.startsWith('https://github.com/apiome/apiome/issues/new?')).toBe(true);
    expect(href).toContain(encodeURIComponent('rev-1'));
    expect(href).toContain(encodeURIComponent('com.example'));
    expect(href).not.toContain(encodeURIComponent('hunter2'));
    expect(screen.getByTestId('roundtrip-unexplained')).toHaveTextContent(
      'credential-shaped options withheld: api_token',
    );
  });

  it('shows the skip explanation when no import adapter exists, with no issue link', () => {
    const result = response({
      status: 'unsupported',
      adapter_key: null,
      reimported_fingerprint: null,
      reason: "No import adapter can re-import emit format 'sample-noop' (emit key 'sample').",
    });
    render(<RoundtripComparisonPanel {...baseProps} hasRun result={result} />);
    expect(screen.getByTestId('roundtrip-status-unsupported')).toHaveTextContent(
      'Comparison skipped',
    );
    expect(screen.getByTestId('roundtrip-status-unsupported')).toHaveTextContent(
      /No import adapter can re-import/,
    );
    expect(screen.queryByTestId('roundtrip-report-issue')).not.toBeInTheDocument();
  });

  it('has no axe violations across its key states', async () => {
    const unrun = render(<RoundtripComparisonPanel {...baseProps} />);
    expect(await axe(unrun.container)).toHaveNoViolations();
    unrun.unmount();

    const failed = render(
      <RoundtripComparisonPanel
        {...baseProps}
        hasRun
        result={response({
          status: 'fail',
          diff_count: 1,
          unexplained: [{ entity: 'type', key: 'User', change: 'removed' }],
        })}
      />,
    );
    expect(await axe(failed.container)).toHaveNoViolations();
  });
});

describe('RoundtripComparisonPanel — model and text diff (MFX-43.4)', () => {
  const settled = { ...baseProps, hasRun: true };
  const dropMatched = response({
    target: 'graphql',
    emit_key: 'graphql',
    diff_count: 2,
    matched_count: 1,
    matched: [
      {
        entry: { entity: 'operation', key: 'GET /pets', change: 'removed' },
        finding: { construct: 'GET /pets', kind: 'drop', severity: 'warn', message: 'REST operations are dropped.' },
      },
    ],
    unexplained: [{ entity: 'type', key: 'Pet', change: 'changed' }],
    status: 'fail',
    loss_drop: 2,
    text_diff: {
      filename: 'schema.graphql',
      media_type: 'application/graphql',
      emitted: 'type Pet { id: ID! }\n',
      reemitted: 'type Pet { id: ID }\n',
      identical: false,
    },
  });
  const predicted = [
    { construct: 'GET /pets', kind: 'drop' as const, severity: 'warn' as const, message: 'REST operations are dropped.' },
    { construct: 'Pet.tags', kind: 'drop' as const, severity: 'info' as const, message: 'Arrays of enums are dropped.' },
    { construct: 'Pet.id', kind: 'ok' as const, severity: 'info' as const, message: 'Kept.' },
  ];

  it('opens on the model diff, with every predicted drop beside what the round trip saw', () => {
    render(<RoundtripComparisonPanel {...settled} result={dropMatched} predictedItems={predicted} />);
    expect(screen.getByTestId('roundtrip-mode-model')).toHaveAttribute('aria-selected', 'true');
    const drops = screen.getByTestId('roundtrip-predicted-drops');
    expect(drops).toHaveTextContent('Predicted drops · 1 of 2 seen in the round trip');
    const rows = within(drops).getAllByRole('listitem');
    expect(rows.map((row) => row.getAttribute('data-observed'))).toEqual(['true', 'false']);
    expect(rows[0]).toHaveTextContent('Seen: removed operation GET /pets');
    expect(rows[1]).toHaveTextContent('Not seen in the round trip');
    expect(screen.getByTestId('roundtrip-unexplained')).toHaveTextContent('type Pet');
  });

  it('lists no predicted drops when the report has none', () => {
    render(<RoundtripComparisonPanel {...settled} result={dropMatched} predictedItems={[predicted[2]]} />);
    expect(screen.queryByTestId('roundtrip-predicted-drops')).not.toBeInTheDocument();
  });

  it('shows the emitted and re-emitted texts side by side on the text diff', () => {
    render(<RoundtripComparisonPanel {...settled} result={dropMatched} targetKey="graphql" />);
    fireEvent.mouseDown(screen.getByTestId('roundtrip-mode-text'));
    fireEvent.click(screen.getByTestId('roundtrip-mode-text'));
    const viewer = screen.getByTestId('json-diff-viewer');
    expect(viewer).toHaveAttribute('data-original', 'type Pet { id: ID! }\n');
    expect(viewer).toHaveAttribute('data-modified', 'type Pet { id: ID }\n');
    expect(viewer).toHaveAttribute('data-language', 'graphql');
    expect(screen.getByTestId('roundtrip-text-diff-summary')).toHaveTextContent(
      'the same file after it is re-imported and exported again',
    );
  });

  it('says a byte-identical round trip changes nothing', () => {
    const same = response({
      text_diff: { filename: 'openapi.json', emitted: '{}', reemitted: '{}', identical: true },
    });
    render(<RoundtripComparisonPanel {...settled} result={same} />);
    fireEvent.mouseDown(screen.getByTestId('roundtrip-mode-text'));
    fireEvent.click(screen.getByTestId('roundtrip-mode-text'));
    expect(screen.getByTestId('roundtrip-text-diff-summary')).toHaveTextContent('comes back byte for byte');
  });

  it('explains why there is no text diff for a bundle', () => {
    const bundle = response({ text_diff: null, text_diff_reason: 'The artifact is a multi-file bundle; …' });
    render(<RoundtripComparisonPanel {...settled} result={bundle} />);
    fireEvent.mouseDown(screen.getByTestId('roundtrip-mode-text'));
    fireEvent.click(screen.getByTestId('roundtrip-mode-text'));
    expect(screen.getByTestId('roundtrip-text-diff-unavailable')).toHaveTextContent('multi-file bundle');
    expect(screen.queryByTestId('json-diff-viewer')).not.toBeInTheDocument();
  });

  it('has no axe violations with both modes present', async () => {
    const { container } = render(
      <RoundtripComparisonPanel {...settled} result={dropMatched} predictedItems={predicted} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

/**
 * The docs screenshot `export-roundtrip-model-diff` (MFX-43.4) is drawn from this dump: a lossy
 * GraphQL export whose round trip confirms one predicted drop, misses another and finds one
 * unexplained difference. Written only with `ROUNDTRIP_FIXTURE_DUMP=1`.
 */
describe('RoundtripComparisonPanel — docs fixture', () => {
  it('renders the model diff the docs screenshot shows (and writes it on request)', () => {
    const result = response({
      target: 'graphql',
      emit_key: 'graphql',
      adapter_key: 'graphql',
      status: 'fail',
      reason: 'unexplained: changed type Pet',
      diff_count: 3,
      matched_count: 2,
      matched: [
        {
          entry: { entity: 'operation', key: 'POST /pets', change: 'removed' },
          finding: { construct: 'POST /pets', kind: 'drop', severity: 'warn', message: 'A REST operation with no GraphQL mutation is dropped.' },
        },
        {
          entry: { entity: 'type', key: 'Error', change: 'changed' },
          finding: { construct: 'Error.code', kind: 'approx', severity: 'info', message: 'An integer enum becomes Int.' },
        },
      ],
      unexplained: [{ entity: 'type', key: 'Pet', change: 'changed' }],
      loss_drop: 2,
      loss_approx: 1,
      loss_ok: 9,
      reimported_fingerprint: 'cccc3333dddd4444',
    });
    const predicted = [
      { construct: 'POST /pets', kind: 'drop' as const, severity: 'warn' as const, message: 'dropped' },
      { construct: 'Pet.tags', kind: 'drop' as const, severity: 'info' as const, message: 'dropped' },
    ];
    const { container } = render(
      <div className="page">
        <RoundtripComparisonPanel
          {...baseProps}
          hasRun
          result={result}
          predictedItems={predicted}
          targetLabel="GraphQL SDL"
          targetKey="graphql"
        />
      </div>,
    );
    expect(screen.getByTestId('roundtrip-predicted-drops')).toHaveTextContent('1 of 2 seen');
    if (process.env.ROUNDTRIP_FIXTURE_DUMP === '1') {
      const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'export-roundtrip');
      fs.mkdirSync(out, { recursive: true });
      fs.writeFileSync(path.join(out, 'model-diff.html'), `${container.innerHTML}\n`);
    }
  });
});
