/**
 * The Clean-up model — PFX-8.14 (#7311): form ↔ rules, the proxies' body checks (nothing unknown is
 * forwarded or dropped; a rule set that removes deployed versions never reaches REST), the preview
 * headline, and **The same, from anywhere**.
 */

import { pactCommandSurfaces } from '../lib/pact-commands';
import {
  KEEPS_IN_USE,
  checkPreviewBody,
  checkRulesBody,
  deletedDetail,
  deletedTitle,
  formOf,
  parseTags,
  previewHeadline,
  retentionCommandAction,
  rulesOf,
  sameRules,
  type RetentionPreview,
  type RetentionRules,
} from '../lib/pact-retention';
import fixture from './fixtures/pact-retention.json';

const SAVED: RetentionRules = {
  keep_main_branch_latest: 5,
  keep_other_branch_latest: 1,
  keep_other_branch_days: 90,
  keep_tags: ['keep'],
  nightly_enabled: true,
  restore_window_days: 30,
};

describe('form and rules', () => {
  it('round-trips the saved rules', () => {
    const checked = rulesOf(formOf(SAVED));
    expect(checked).toEqual({ rules: SAVED });
    expect('rules' in checked && sameRules(checked.rules, SAVED)).toBe(true);
  });

  it('turns a removed rule into null and an empty age into however old', () => {
    const form = { ...formOf(SAVED), mainOn: false, otherDays: '', tagsOn: false };
    expect(rulesOf(form)).toEqual({
      rules: { ...SAVED, keep_main_branch_latest: null, keep_other_branch_days: null, keep_tags: [] },
    });
  });

  it('starts a rule that is off from a sensible number', () => {
    const form = formOf({ ...SAVED, keep_main_branch_latest: null, keep_other_branch_latest: null, keep_tags: [] });
    expect([form.mainOn, form.mainLatest, form.otherOn, form.otherLatest, form.tagsOn]).toEqual([false, '5', false, '1', false]);
  });

  it.each([
    [{ mainLatest: '0' }, 'The main-branch count must be a whole number from 1 to 1000.'],
    [{ otherLatest: '1.5' }, 'The other-branch count must be a whole number from 1 to 1000.'],
    [{ otherDays: '4000' }, 'The other-branch days must be a whole number from 1 to 3650.'],
    [{ restoreDays: '400' }, 'The restore window must be a whole number from 1 to 365.'],
    [{ tags: 'a, a' }, 'The tag a is listed more than once.'],
  ])('refuses %p with the reason', (change, error) => {
    expect(rulesOf({ ...formOf(SAVED), ...change })).toEqual({ error });
  });

  it('reads tags from a comma-separated list, refusing what it cannot keep by', () => {
    expect(parseTags(' keep , prod ')).toEqual(['keep', 'prod']);
    expect(parseTags('')).toEqual({ error: 'Name at least one tag, or remove the tag rule.' });
    expect(parseTags(Array.from({ length: 51 }, (_, n) => `t${n}`).join(','))).toEqual({
      error: 'Keep by at most 50 tags.',
    });
    expect(parseTags('x'.repeat(256))).toEqual({ error: 'A tag is at most 255 characters.' });
  });
});

describe('the proxies’ body checks', () => {
  it('passes a rules body as it is', () => {
    expect(checkRulesBody(SAVED)).toEqual({ ok: true, body: SAVED });
  });

  it('names an unknown field and refuses turning deployed / released off', () => {
    expect(checkRulesBody({ ...SAVED, keep_everything: true })).toEqual({ ok: false, error: 'Unsupported field keep_everything.' });
    expect(checkRulesBody({ keep_deployed_or_released: false })).toEqual({ ok: false, error: KEEPS_IN_USE });
    expect(checkRulesBody([])).toEqual({ ok: false, error: 'Send the rules as a JSON object.' });
    expect(checkRulesBody(null)).toEqual({ ok: false, error: 'Send the rules as a JSON object.' });
  });

  it('previews the saved rules for {} and a draft for { rules }', () => {
    expect(checkPreviewBody({})).toEqual({ ok: true, body: {} });
    expect(checkPreviewBody({ rules: SAVED })).toEqual({ ok: true, body: { rules: SAVED } });
    expect(checkPreviewBody({ rules: { bogus: 1 } })).toEqual({ ok: false, error: 'Unsupported field bogus.' });
    expect(checkPreviewBody({ dry_run: false })).toEqual({ ok: false, error: 'Unsupported field dry_run.' });
  });
});

describe('what the tab says', () => {
  it('headlines a preview', () => {
    expect(previewHeadline(fixture.preview as RetentionPreview)).toEqual({
      title: '412 of 1,904 versions would go',
      detail: 'with 618 pacts and 2,140 results. Nothing deployed or released goes.',
    });
    const capped = { ...fixture.preview, plan: { ...fixture.preview.plan, remaining: 3 } } as RetentionPreview;
    expect(previewHeadline(capped).detail).toContain('3 more versions past one run’s cap');
  });

  it('names a deleted row and what comes back with it', () => {
    const [version, pacticipant] = fixture.deleted.items as Parameters<typeof deletedTitle>[0][];
    expect([deletedTitle(version), deletedDetail(version)]).toEqual(['Orders UI 3.2.9+c4410b7', '1 pact · 2 results']);
    expect([deletedTitle(pacticipant), deletedDetail(pacticipant)]).toEqual(['Legacy Cart', '41 versions · 6 pacts']);
  });

  it('writes the form as apiome pact retention set and the REST PUT', () => {
    const surfaces = pactCommandSurfaces(retentionCommandAction(SAVED));
    const text = JSON.stringify(surfaces);
    expect(text).toContain('apiome pact retention set');
    expect(text).toContain('--main-branch-latest 5');
    expect(text).toContain('--other-branch-days 90');
    expect(text).toContain('--keep-tag keep');
    expect(text).toContain('--nightly');
    expect(text).toContain('PUT /v1/tenants/{tenant}/pact-retention/policy');
    const off = JSON.stringify(
      pactCommandSurfaces(retentionCommandAction({ ...SAVED, keep_main_branch_latest: null, keep_tags: [], nightly_enabled: false })),
    );
    expect(off).toContain('--main-branch-latest 0');
    expect(off).toContain('--no-tags');
    expect(off).toContain('--no-nightly');
  });
});
