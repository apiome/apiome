/**
 * Export history — the pure half (MFX-46.1, #4379).
 *
 *  1. Filters become the REST query: allowed values only, dates as whole UTC days, pagination.
 *  2. Every verdict reads as a word and a tone.
 *  3. Deliveries summarize per channel and outcome.
 *  4. **Re-run pre-fills the Studio**: source, version, target and options, opening on Options.
 *  5. The proxy forwards only the filters REST accepts.
 */

import {
  EMPTY_FILTERS,
  HISTORY_PAGE_SIZE,
  activeFilterCount,
  channelLabel,
  decisionVerdict,
  deliverySummary,
  hasFilters,
  historyQuery,
  lintVerdict,
  preservedTone,
  rerunHref,
  sourceLabel,
  stateVerdict,
  validationVerdict,
  type ExportRunSummary,
} from '../src/app/components/ade/export-studio/history/exportHistoryModel';
import { decodeStudioOptions } from '../src/app/components/ade/dashboard/export/exportStudioUrlState';
import { exportRunQuery } from '../lib/export-history-query';

function run(overrides: Partial<ExportRunSummary> = {}): ExportRunSummary {
  return {
    job_id: 'job-1',
    artifact_id: 'proj-1',
    artifact_name: 'Petstore',
    version_record_id: 'rev-1',
    version_label: '1.4.0',
    target: 'protobuf',
    actor_id: 'u1',
    actor_label: 'ada@example.com',
    state: 'completed',
    dry_run: false,
    preserved_percent: 64,
    fidelity_tier: 'lossy',
    validation_verdict: 'valid',
    lint_verdict: 'warn',
    delivery_decision: 'allow_with_warning',
    options: { package: 'acme.v1' },
    deliveries: [],
    created_at: '2026-11-05T09:00:00Z',
    finished_at: '2026-11-05T09:01:00Z',
    ...overrides,
  };
}

const params = (query: string) => Object.fromEntries(new URLSearchParams(query));

// ---------------------------------------------------------------------------
// 1. The query
// ---------------------------------------------------------------------------

describe('historyQuery', () => {
  it('asks for the first page with no filter', () => {
    expect(params(historyQuery(EMPTY_FILTERS))).toEqual({ limit: String(HISTORY_PAGE_SIZE), offset: '0' });
  });

  it('carries every filter, dates as whole UTC days, and the page offset', () => {
    const query = historyQuery(
      {
        artifact: 'proj-1',
        target: 'protobuf',
        actor: 'u1',
        state: 'failed',
        channel: 'git',
        validation: 'invalid',
        decision: 'block',
        from: '2026-11-01',
        to: '2026-11-05',
      },
      2,
      10,
    );
    expect(params(query)).toEqual({
      artifact: 'proj-1',
      target: 'protobuf',
      actor: 'u1',
      state: 'failed',
      channel: 'git',
      validation: 'invalid',
      decision: 'block',
      finished_after: '2026-11-01T00:00:00Z',
      finished_before: '2026-11-05T23:59:59Z',
      limit: '10',
      offset: '20',
    });
  });

  it('never sends a value outside its allowed set, or a malformed date', () => {
    const query = params(
      historyQuery({ ...EMPTY_FILTERS, state: 'exploded', channel: 'ftp', decision: 'maybe', from: '11/01/2026' }),
    );
    expect(query).toEqual({ limit: String(HISTORY_PAGE_SIZE), offset: '0' });
  });

  it('counts the filters set', () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false);
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    const narrowed = { ...EMPTY_FILTERS, target: 'protobuf', from: '2026-11-01' };
    expect(hasFilters(narrowed)).toBe(true);
    expect(activeFilterCount(narrowed)).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// 2. Words and tones
// ---------------------------------------------------------------------------

describe('verdicts', () => {
  it('says each outcome and verdict in words, with a tone', () => {
    expect(stateVerdict('failed')).toEqual({ label: 'Failed', tone: 'danger' });
    expect(validationVerdict('skipped')).toEqual({ label: 'Skipped', tone: 'warn' });
    expect(validationVerdict('not_applicable')).toEqual({ label: 'Not checked', tone: 'neutral' });
    expect(lintVerdict('block')).toEqual({ label: 'Blocking', tone: 'danger' });
    expect(decisionVerdict('allow_with_warning')).toEqual({ label: 'Allowed with warnings', tone: 'warn' });
  });

  it('has no verdict for a run that never got that far, and passes an unknown one through', () => {
    expect(validationVerdict(null)).toBeNull();
    expect(lintVerdict(undefined)).toBeNull();
    expect(decisionVerdict('')).toBeNull();
    expect(stateVerdict('paused')).toEqual({ label: 'paused', tone: 'neutral' });
  });

  it('tones the share preserved', () => {
    expect(preservedTone(100)).toBe('ok');
    expect(preservedTone(85)).toBe('warn');
    expect(preservedTone(41)).toBe('danger');
    expect(preservedTone(null)).toBe('neutral');
  });

  it('names the source with its version, falling back to its id', () => {
    expect(sourceLabel(run())).toBe('Petstore @ 1.4.0');
    expect(sourceLabel(run({ artifact_name: null, version_label: null }))).toBe('proj-1');
    expect(channelLabel('object-storage')).toBe('Object storage');
    expect(channelLabel('none')).toBe('Not delivered');
  });
});

// ---------------------------------------------------------------------------
// 3. Deliveries
// ---------------------------------------------------------------------------

describe('deliverySummary', () => {
  it('says nothing for a run never delivered', () => {
    expect(deliverySummary([])).toBeNull();
  });

  it('summarizes per channel and outcome, counting repeats', () => {
    expect(
      deliverySummary([
        { channel: 'git', status: 'opened', outcome: 'delivered' },
        { channel: 'git', status: 'updated', outcome: 'delivered' },
        { channel: 'webhook', status: 'failed', outcome: 'failed' },
        { channel: 'object-storage', status: 'in_progress', outcome: 'in_progress' },
      ]),
    ).toBe('Git delivered ×2 · Webhook failed · Object storage in progress');
  });
});

// ---------------------------------------------------------------------------
// 4. Re-run
// ---------------------------------------------------------------------------

describe('rerunHref', () => {
  it('pre-fills the Studio with the source, version, target and options, on Options', () => {
    const href = rerunHref(run());
    const [path, query] = href.split('?');
    expect(path).toBe('/ade/dashboard/export/studio');
    const q = new URLSearchParams(query);
    expect(q.get('artifact')).toBe('proj-1');
    expect(q.get('version')).toBe('rev-1');
    expect(q.get('label')).toBe('Petstore');
    expect(q.get('target')).toBe('protobuf');
    expect(q.get('step')).toBe('options');
    expect(decodeStudioOptions(q.get('opts'))).toEqual({ package: 'acme.v1' });
  });

  it('opens a multi-target run on Target, with nothing pre-selected', () => {
    const q = new URLSearchParams(rerunHref(run({ target: 'openapi,protobuf', version_record_id: null })).split('?')[1]);
    expect(q.get('target')).toBeNull();
    expect(q.get('opts')).toBeNull();
    expect(q.get('step')).toBe('target');
    expect(q.get('version')).toBe('1.4.0');
  });
});

// ---------------------------------------------------------------------------
// 5. The proxy's allow-list
// ---------------------------------------------------------------------------

describe('exportRunQuery', () => {
  it('forwards only the filters REST accepts', () => {
    const incoming = new URLSearchParams(
      'artifact=proj-1&channel=git&limit=25&offset=0&tenant=evil&finished_after=2026-11-01T00:00:00Z&target=',
    );
    expect(params(exportRunQuery(incoming).slice(1))).toEqual({
      artifact: 'proj-1',
      channel: 'git',
      limit: '25',
      offset: '0',
      finished_after: '2026-11-01T00:00:00Z',
    });
    expect(exportRunQuery(new URLSearchParams(''))).toBe('');
  });
});
