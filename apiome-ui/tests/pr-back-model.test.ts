/**
 * The PR-back browser model (REPO-5.8, #2793): reply parsers refuse malformed shapes, the request
 * whitelists drop anything else, reviewers are split the way a person types them, and the
 * summary sentences say what the settings and outcomes mean.
 */

import { describe, expect, test } from '@jest/globals';

import {
  MAX_REVIEWERS,
  PR_BACK_STATUS_LABEL,
  PR_BACK_STATUS_TONE,
  outcomeSentence,
  parsePrBackOutcome,
  parsePrBackRepositories,
  parsePrBackSettings,
  parseReviewers,
  sanitizePrBackRequest,
  sanitizePrBackSettingsInput,
  settingsSummary,
  type PrBackOutcome,
  type PrBackSettings,
} from '@lib/pr-back';

const REPO = '66666666-6666-4666-8666-666666666666';
const PROJECT = '22222222-2222-4222-8222-222222222222';

const SETTINGS: PrBackSettings = {
  repositoryId: REPO,
  configured: true,
  projectPolicy: 'allow',
  projects: [{ id: PROJECT, name: 'Shop' }],
  targetBranch: null,
  commitMessageTemplate: null,
  defaultCommitMessageTemplate: 'Sync {{project}} {{version}} from Apiome',
  reviewers: [],
  updatedAt: null,
};

function outcome(fields: Partial<PrBackOutcome> = {}): PrBackOutcome {
  return {
    status: 'opened',
    dryRun: false,
    versionLabel: '1.4.0',
    repositoryFullName: 'acme/shop',
    baseBranch: 'main',
    branchName: 'apiome/pr-back-shop-main',
    pullRequestNumber: 7,
    pullRequestUrl: 'https://github.com/acme/shop/pull/7',
    title: 'Apiome: sync Shop 1.4.0',
    body: '## Shop',
    commitMessage: 'Sync Shop 1.4.0 from Apiome',
    reviewers: [],
    files: [
      { path: 'a.yaml', status: 'modified', paths: 1, schemas: 1, counts: {}, foreignRefs: [], notes: [] },
      { path: 'b.json', status: 'unchanged', paths: 1, schemas: 0, counts: {}, foreignRefs: [], notes: [] },
    ],
    skipped: [],
    errorCode: null,
    errorMessage: null,
    ...fields,
  };
}

describe('parsers', () => {
  test('settings parse with defaults and refuse non-settings', () => {
    expect(parsePrBackSettings({ success: false })).toBeNull();
    const parsed = parsePrBackSettings({
      repositoryId: REPO,
      configured: true,
      projectPolicy: 'deny',
      projects: [{ id: PROJECT, name: null }, { name: 'no id' }],
      reviewers: ['octocat', 3],
      defaultCommitMessageTemplate: 'x',
    });
    expect(parsed).toMatchObject({
      projectPolicy: 'deny',
      projects: [{ id: PROJECT, name: null }],
      reviewers: ['octocat'],
      targetBranch: null,
    });
    expect(parsePrBackSettings({ repositoryId: REPO, projectPolicy: 'weird' })?.projectPolicy).toBe('allow');
  });

  test('repositories parse and drop rows without an id', () => {
    expect(parsePrBackRepositories({})).toBeNull();
    const parsed = parsePrBackRepositories({
      repositories: [
        { repositoryId: REPO, eligible: true, baseBranch: 'main', files: [{ path: 'a.yaml', branch: 'main', precedence: 1 }] },
        { eligible: true },
        { repositoryId: 'r2', eligible: false, reasonCode: 'pr-back-not-configured', reason: 'Off.' },
      ],
    });
    expect(parsed).toHaveLength(2);
    expect(parsed?.[0].files).toEqual([{ path: 'a.yaml', branch: 'main', precedence: 1 }]);
    expect(parsed?.[1]).toMatchObject({ eligible: false, reason: 'Off.' });
  });

  test('outcomes parse and refuse unknown statuses', () => {
    expect(parsePrBackOutcome({ status: 'exploded' })).toBeNull();
    const parsed = parsePrBackOutcome({
      status: 'preview',
      dryRun: true,
      files: [{ path: 'a.yaml', status: 'added', paths: 2, schemas: 1, counts: { properties: 3, bad: 'x' } }],
      skipped: ['x'],
    });
    expect(parsed?.files[0]).toMatchObject({ path: 'a.yaml', counts: { properties: 3 } });
    expect(parsed?.dryRun).toBe(true);
    expect(parsed?.pullRequestNumber).toBeNull();
  });
});

describe('whitelists', () => {
  test('sync request keeps only repositoryId, version and dryRun', () => {
    expect(sanitizePrBackRequest({ repositoryId: 'nope' })).toBeNull();
    expect(sanitizePrBackRequest(null)).toBeNull();
    expect(sanitizePrBackRequest({ repositoryId: REPO, version: ' 1.4.0 ', dryRun: true, token: 'x' })).toEqual({
      repositoryId: REPO,
      version: '1.4.0',
      dryRun: true,
    });
    expect(sanitizePrBackRequest({ repositoryId: REPO, version: '  ' })).toEqual({ repositoryId: REPO, dryRun: false });
  });

  test('settings body keeps only the five fields', () => {
    expect(sanitizePrBackSettingsInput('x')).toBeNull();
    expect(
      sanitizePrBackSettingsInput({
        projectPolicy: 'deny',
        projectIds: [PROJECT, 1],
        targetBranch: '  ',
        commitMessageTemplate: ' api ',
        reviewers: Array.from({ length: MAX_REVIEWERS + 5 }, (_, i) => `u${i}`),
        updated_by: 'me',
      }),
    ).toEqual({
      projectPolicy: 'deny',
      projectIds: [PROJECT],
      targetBranch: null,
      commitMessageTemplate: 'api',
      reviewers: Array.from({ length: MAX_REVIEWERS + 1 }, (_, i) => `u${i}`),
    });
  });

  test('reviewers split on commas, spaces and lines, dropping @ and duplicates', () => {
    expect(parseReviewers('@octocat, acme/api-reviewers\nOctocat  hubot,,')).toEqual([
      'octocat',
      'acme/api-reviewers',
      'hubot',
    ]);
    expect(parseReviewers('   ')).toEqual([]);
  });
});

describe('sentences', () => {
  test('settings summary covers every state', () => {
    expect(settingsSummary({ ...SETTINGS, configured: false })).toMatch(/PR-back is off/);
    expect(settingsSummary(SETTINGS)).toBe('1 project may open pull requests.');
    expect(settingsSummary({ ...SETTINGS, projects: [], targetBranch: 'develop' })).toMatch(/tick the projects/);
    expect(settingsSummary({ ...SETTINGS, projectPolicy: 'deny', projects: [], targetBranch: 'develop' })).toBe(
      'Every project imported from this repository may open pull requests into develop.',
    );
    expect(settingsSummary({ ...SETTINGS, projectPolicy: 'deny' })).toBe('Every project except 1 may open pull requests.');
  });

  test('outcome sentences, labels and tones exist for every status', () => {
    expect(outcomeSentence(outcome())).toBe('Opened pull request #7 into main.');
    expect(outcomeSentence(outcome({ status: 'preview' }))).toBe(
      'Opening a pull request would write 1 of 2 file(s) into main.',
    );
    expect(outcomeSentence(outcome({ status: 'updated' }))).toMatch(/Updated the open pull request #7/);
    expect(outcomeSentence(outcome({ status: 'unchanged' }))).toMatch(/already carries/);
    expect(outcomeSentence(outcome({ status: 'up_to_date' }))).toMatch(/main already holds/);
    expect(outcomeSentence(outcome({ status: 'failed', errorMessage: 'Token revoked.' }))).toBe('Token revoked.');
    expect(outcomeSentence(outcome({ status: 'failed' }))).toBe('The sync failed.');
    for (const status of ['preview', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed'] as const) {
      expect(PR_BACK_STATUS_LABEL[status]).toBeTruthy();
      expect(PR_BACK_STATUS_TONE[status]).toBeTruthy();
    }
  });
});
