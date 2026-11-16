/**
 * The usage-data controls' pure helpers — RDG-5.4 (#5789).
 *
 * Pins the rules the drawer leans on: retention can only be lowered (and the message names the
 * cap, as REST's does), a body-sample window respects its caps and needs the acknowledgement,
 * labels read the same for every viewer (UTC), and the export link stays inside REST's bounds.
 */

import {
  EMPTY_BODY_SAMPLE_DRAFT,
  bodySampleLine,
  bodySampleProblem,
  bodySampleWindow,
  daysLabel,
  exportHref,
  percentLabel,
  retentionProblem,
  retentionValue,
  utcLabel,
  type BodySamples,
} from '../src/app/components/ade/usage/usageDataModel';
import { isUsageExport, usageUpstreamPath } from '../lib/usage-proxy-path';

const SOURCE: BodySamples = { rate: 0, until: null, open: false, maxRate: 0.05, maxWindowDays: 7, retentionDays: 7 };

describe('retention', () => {
  it('accepts an empty field (back to the cap) and any value up to the cap', () => {
    expect(retentionProblem('', 30, 'Hourly retention')).toBeNull();
    expect(retentionProblem('30', 30, 'Hourly retention')).toBeNull();
    expect(retentionValue('')).toBeNull();
    expect(retentionValue(' 7 ')).toBe(7);
  });

  it('refuses a value above the cap and names the cap', () => {
    expect(retentionProblem('31', 30, 'Hourly retention')).toBe(
      "Hourly retention may be at most 30 days on this workspace's tier.",
    );
  });

  it('refuses a fraction or a value below one day, and a forever cap takes any positive value', () => {
    expect(retentionProblem('0', 30, 'X')).toMatch(/at least 1/);
    expect(retentionProblem('2.5', 30, 'X')).toMatch(/whole number/);
    expect(retentionProblem('5000', -1, 'X')).toBeNull();
  });

  it('labels days, forever and the cap', () => {
    expect(daysLabel(1)).toBe('1 day');
    expect(daysLabel(30)).toBe('30 days');
    expect(daysLabel(-1)).toBe('Forever');
    expect(daysLabel(null)).toBe('Tier cap');
  });
});

describe('body samples', () => {
  it('needs a rate within the cap, a window within 7 days, and the acknowledgement', () => {
    expect(bodySampleProblem({ ...EMPTY_BODY_SAMPLE_DRAFT, percent: '6' }, SOURCE)).toMatch(/at most 5 %/);
    expect(bodySampleProblem({ ...EMPTY_BODY_SAMPLE_DRAFT, days: '8' }, SOURCE)).toMatch(/1 to 7 days/);
    expect(bodySampleProblem(EMPTY_BODY_SAMPLE_DRAFT, SOURCE)).toBe('Tick the acknowledgement first.');
    expect(bodySampleProblem({ ...EMPTY_BODY_SAMPLE_DRAFT, acknowledged: true }, SOURCE)).toBeNull();
    expect(bodySampleProblem({ percent: '50', days: '1', acknowledged: true }, { ...SOURCE, maxRate: 1 })).toBeNull();
  });

  it('builds the REST window with the sentence and an end N days ahead', () => {
    const now = new Date('2026-11-16T12:00:00Z');
    expect(bodySampleWindow({ percent: '2', days: '3', acknowledged: true }, 'I understand.', now)).toEqual({
      rate: 0.02,
      until: '2026-11-19T12:00:00.000Z',
      acknowledgement: 'I understand.',
    });
  });

  it('describes an opt-in in one line, in UTC', () => {
    expect(bodySampleLine(SOURCE)).toBe('Off');
    expect(bodySampleLine({ ...SOURCE, rate: 0.05, open: true, until: '2026-11-18T14:00:00Z' })).toBe(
      '5 % until 18 Nov 2026, 14:00 UTC',
    );
    expect(bodySampleLine({ ...SOURCE, rate: 0.05, open: false, until: '2026-11-01T00:00:00Z' })).toBe(
      'Ended 1 Nov 2026, 00:00 UTC',
    );
    expect(percentLabel(1)).toBe('100 %');
    expect(utcLabel('not a date')).toBe('not a date');
  });
});

describe('export and proxy paths', () => {
  it('keeps the export link inside REST bounds', () => {
    expect(exportHref('pets', 'csv', 30)).toBe('/api/usage/pets/export?format=csv&days=30');
    expect(exportHref('my pets', 'json', 9999)).toBe('/api/usage/my%20pets/export?format=json&days=730');
    expect(exportHref('pets', 'csv', 0)).toBe('/api/usage/pets/export?format=csv&days=30');
  });

  it('maps every browser path to its REST path and refuses anything else', () => {
    const rest = (segments: string[]) => usageUpstreamPath('http://rest/v1', 'acme', segments)?.replace('http://rest/v1/tenants/', '');
    expect(rest([':retention'])).toBe('acme/usage/retention');
    expect(rest([':toolsets', 't1', 'body-samples'])).toBe('acme/agent-toolsets/t1/body-samples');
    expect(rest(['pets', 'sources'])).toBe('acme/projects/pets/usage/sources');
    expect(rest(['pets', 'sources', 's1'])).toBe('acme/projects/pets/usage/sources/s1');
    expect(rest(['pets', 'export'])).toBe('acme/projects/pets/usage/export');
    for (const refused of [[], [':retention', 'x'], [':toolsets', 't1'], ['pets'], ['pets', 'ingest'], ['pets', 'export', 'x']]) {
      expect(usageUpstreamPath('http://rest/v1', 'acme', refused)).toBeNull();
    }
    expect(isUsageExport(['pets', 'export'])).toBe(true);
    expect(isUsageExport(['pets', 'sources'])).toBe(false);
    expect(isUsageExport([':retention', 'export'])).toBe(false);
  });
});
