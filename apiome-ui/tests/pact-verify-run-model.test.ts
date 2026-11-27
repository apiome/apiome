/**
 * The model of **Run a verification** — PFX-8.8 (#7305), `lib/pact-verify-run.ts`.
 *
 * * each rule is one consumer-version selector and one sentence; the presets; duplicates once;
 * * the form's problems — the production rule first among the ones shown at once;
 * * the run's REST body and the preview's carry the same selection;
 * * `apiome pact verify` carries every option the form sets; a self-run is the Pact verifier with
 *   the same selectors, publishing back — and says what the native verifier does differently;
 * * the answers are read tolerantly; the sentences the page writes.
 */

import {
  EMPTY_FORM,
  MUTATING_PRODUCTION,
  SELF_RUN_NO_HOSTED,
  everythingVerified,
  formProblems,
  formSelectors,
  isSetupUrl,
  newTargetBody,
  newTargetProblems,
  parseContext,
  presetRules,
  previewBody,
  previewHeadline,
  readPreview,
  readRun,
  readTargets,
  rule,
  ruleSelector,
  ruleSentence,
  runHeadline,
  statesSentence,
  targetLabel,
  targetSignIn,
  targetSlug,
  verifyBody,
  verifyCommandAction,
  verifyRunRoute,
  verifySurfaces,
  type VerifyForm,
} from '../lib/pact-verify-run';
import { pactCommandSurfaces } from '../lib/pact-commands';

const FORM: VerifyForm = {
  ...EMPTY_FORM,
  provider: 'billing-service',
  providerVersion: '2.7.0+9f31c20',
  branch: 'feature/credit-notes',
  target: 'staging',
};

describe('rules', () => {
  it('stand for one selector each and read as sentences', () => {
    expect(ruleSelector(rule('mainBranch'))).toEqual({ mainBranch: true });
    expect(ruleSelector(rule('deployedOrReleased', 'production'))).toEqual({ deployedOrReleased: true, environment: 'production' });
    expect(ruleSelector(rule('tag', 'prod'))).toEqual({ tag: 'prod', latest: true });
    expect(ruleSelector({ ...rule('branch', 'feat'), consumer: 'Orders UI' })).toEqual({ branch: 'feat', consumer: 'Orders UI' });
    expect(ruleSentence(rule('mainBranch'))).toBe('Each consumer’s latest pact on its main branch');
    expect(ruleSentence(rule('deployedOrReleased'))).toBe('Pacts of every consumer version deployed or released anywhere');
    expect(ruleSentence(rule('matchingBranch'), 'feature/credit-notes')).toBe(
      'Pacts on a consumer branch named like this one — feature/credit-notes',
    );
    expect(ruleSentence({ ...rule('branch', 'feat'), consumer: 'web' })).toBe('The latest pact on branch feat, from web only');
  });

  it('come in presets; Custom keeps what is there', () => {
    expect(presetRules('recommended').map((r) => r.kind)).toEqual(['mainBranch', 'deployedOrReleased', 'matchingBranch']);
    expect(presetRules('everything').map((r) => r.kind)).toEqual(['mainBranch', 'deployedOrReleased', 'matchingBranch', 'latest']);
    const mine = [rule('tag', 'prod')];
    expect(presetRules('custom', mine)).toBe(mine);
  });

  it('are verified once when two say the same', () => {
    expect(formSelectors({ rules: [rule('mainBranch', '', 'a'), rule('mainBranch', '', 'b')] })).toEqual([{ mainBranch: true }]);
  });
});

describe('problems', () => {
  it('needs a provider, a version and a target for a hosted run', () => {
    const fields = formProblems({ ...EMPTY_FORM }).map((p) => p.field);
    expect(fields).toEqual(expect.arrayContaining(['provider', 'providerVersion', 'target', 'branch']));
    expect(formProblems(FORM)).toEqual([]);
  });

  it('a self-run needs no version and no target', () => {
    expect(formProblems({ ...FORM, mode: 'self', target: '', providerVersion: '' })).toEqual([]);
  });

  it('never allows mutating requests against a production target', () => {
    expect(formProblems({ ...FORM, allowMutating: true }, { environment: 'production' })).toEqual([
      { field: 'allowMutating', message: MUTATING_PRODUCTION },
    ]);
    expect(formProblems({ ...FORM, allowMutating: true }, { environment: 'staging' })).toEqual([]);
    expect(formProblems({ ...FORM, allowMutating: false }, { environment: 'production' })).toEqual([]);
  });

  it('checks a named rule, the WIP date, the setup URL, the build URL and the context', () => {
    const problems = formProblems({
      ...FORM,
      rules: [rule('branch', '', 'r1')],
      wip: true,
      wipSince: 'yesterday',
      states: 'setup-url',
      setupUrl: '//elsewhere/x',
      buildUrl: 'ftp://ci',
      context: 'commit=abc\nnonsense',
    });
    expect(problems.map((p) => p.field)).toEqual(['buildUrl', 'rule:r1', 'wipSince', 'setupUrl', 'context']);
    expect(problems.find((p) => p.field === 'context')?.message).toBe('“nonsense” is not KEY=VALUE.');
  });

  it('reads setup URLs and context like REST', () => {
    expect(isSetupUrl('/_pact/provider-states')).toBe(true);
    expect(isSetupUrl('https://states.example/setup')).toBe(true);
    expect(isSetupUrl('//elsewhere')).toBe(false);
    expect(isSetupUrl('javascript:alert(1)')).toBe(false);
    expect(parseContext(' commit=abc \n\nurl=a=b')).toEqual({ ok: true, context: { commit: 'abc', url: 'a=b' } });
  });
});

describe('REST bodies', () => {
  it('the run carries every option set, and the preview the same selection', () => {
    const form: VerifyForm = {
      ...FORM,
      buildUrl: 'https://ci.example/42',
      wip: true,
      wipSince: '2026-11-01',
      states: 'setup-url',
      setupUrl: '/_pact/states',
      allowMutating: true,
      publish: false,
      context: 'commit=9f31c20',
    };
    const body = verifyBody(form);
    expect(body).toEqual({
      target_ref: 'staging',
      provider_version: '2.7.0+9f31c20',
      provider_branch: 'feature/credit-notes',
      build_url: 'https://ci.example/42',
      publish: false,
      selection: {
        consumerVersionSelectors: [{ mainBranch: true }, { deployedOrReleased: true }, { matchingBranch: true }],
        includePendingStatus: true,
        includeWipPactsSince: '2026-11-01',
      },
      verification: { allow_mutating: true, provider_states_setup_url: '/_pact/states' },
      skip_already_verified: true,
      context: { commit: '9f31c20' },
    });
    expect(previewBody(form).selection).toEqual(body.selection);
    expect(previewBody(form).verification).toEqual(body.verification);
    expect(previewBody({ ...form, mode: 'self' })).not.toHaveProperty('target_ref');
  });

  it('Run anyway drops the skip; No setup replays as-is', () => {
    expect(verifyBody(FORM, { runAnyway: true })).not.toHaveProperty('skip_already_verified');
    expect(verifyBody({ ...FORM, states: 'none' }).verification).toEqual({ replay_without_state_setup: true });
  });
});

describe('the same, from anywhere', () => {
  it('writes apiome pact verify with every option the form sets', () => {
    const form: VerifyForm = { ...FORM, wip: true, wipSince: '2026-11-01', states: 'setup-url', setupUrl: '/_pact/states', publish: false };
    const [apiome] = pactCommandSurfaces(verifyCommandAction(form, 'acme'));
    expect(apiome.text).toContain('apiome pact verify');
    for (const part of [
      '--provider billing-service',
      '--provider-app-version 2.7.0+9f31c20',
      '--target staging',
      '--branch feature/credit-notes',
      `--consumer-version-selector '{"mainBranch":true}'`,
      `--consumer-version-selector '{"deployedOrReleased":true}'`,
      '--enable-pending',
      '--include-wip-pacts-since 2026-11-01',
      '--provider-states-setup-url /_pact/states',
      '--skip-already-verified',
      '--no-publish-verification-results',
    ]) {
      expect(apiome.text).toContain(part);
    }
    expect(verifyCommandAction(form, 'acme').rest.path).toBe('/v1/tenants/acme/pact-verifier/pacts/provider/billing-service/verify');
  });

  it('a hosted run shows apiome, the Pact verifier, the pipeline step and REST', () => {
    const surfaces = verifySurfaces(FORM, '');
    expect(surfaces.map((s) => s.label)).toEqual(['apiome', 'Pact verifier', 'GitHub Action', 'REST']);
  });

  it('a self-run is the Pact verifier with the same selectors, publishing back', () => {
    const [verifier, ...others] = verifySurfaces({ ...FORM, mode: 'self', providerVersion: '' }, '');
    expect(verifier.label).toBe('Pact verifier');
    expect(verifier.text).toContain('pact-provider-verifier');
    expect(verifier.text).toContain('--pact-broker-base-url "$PACT_BROKER_BASE_URL"');
    expect(verifier.text).toContain(`--consumer-version-selector '{"matchingBranch":true}'`);
    expect(verifier.text).toContain('--publish-verification-results');
    expect(verifier.text).toContain('--provider-app-version "$GIT_COMMIT"');
    expect(verifier.notes?.join(' ')).toContain('sends every interaction');
    for (const surface of others) expect(surface).toMatchObject({ text: null, unavailable: SELF_RUN_NO_HOSTED });
  });
});

const PREVIEW = {
  provider: 'billing-service',
  provider_name: 'Billing Service',
  provider_version: '2.7.0',
  target: { slug: 'staging', name: 'Staging', environment: 'staging', production: false, allow_mutating_methods: true, enabled: true },
  rules: [{ index: 0, selector: { mainBranch: true }, pacts: 4 }],
  selected: 6,
  will_run: 4,
  skipped: 2,
  interactions: 61,
  pacts: [{ consumer: 'orders-ui', consumer_name: 'Orders UI', consumer_version: '3.4.0', pact_version_sha: '8d2f1c', interactions: 6, will_run: true }],
  truncated: false,
  states: { strategy: 'registry', used: 11, handled: 9, missing: ['a', 'b'], registered: 9 },
  max_pacts_per_run: 25,
  refusals: [],
};

describe('answers', () => {
  it('reads the preview and writes its sentences', () => {
    const preview = readPreview(PREVIEW);
    expect(preview.pacts[0]).toMatchObject({ consumer_name: 'Orders UI', branches: [], already_verified: false, last_result: null });
    expect(previewHeadline(preview)).toBe('This run will verify 4 pacts · 61 interactions');
    expect(statesSentence(preview)).toBe(
      '9 of the 11 states these pacts use have a handler. 2 are missing — those interactions will be skipped and reported.',
    );
    expect(statesSentence(readPreview({ ...PREVIEW, states: { used: 0 } }))).toBe('These pacts name no provider state.');
    expect(everythingVerified(preview)).toBe(false);
    expect(everythingVerified(readPreview({ ...PREVIEW, will_run: 0 }))).toBe(true);
    expect(readPreview({}).states.strategy).toBe('registry');
  });

  it('reads the run and says how it went — an unreachable target is not a failure', () => {
    const run = readRun({
      provider: 'billing-service',
      provider_version: '2.7.0',
      target: { slug: 'staging' },
      outcome: 'could-not-connect',
      success: false,
      connection_error: 'Could not connect to billing.staging.acme.dev (timeout)',
      pacts: [],
      skipped: [],
    });
    expect(runHeadline(run)).toBe('Could not connect to billing.staging.acme.dev (timeout) — not a failed verification; nothing was published.');
    expect(runHeadline({ ...run, connection_error: null, outcome: 'already-verified' })).toBe('Every selected pact is already verified for 2.7.0.');
    expect(runHeadline({ ...run, connection_error: null, outcome: 'failed' })).toContain('a pact failed');
  });
});

describe('targets', () => {
  it('lists targets, says how each signs in, and marks production', () => {
    const [prod, staging] = readTargets({
      targets: [
        { slug: 'off', name: 'Old', enabled: false, base_url: 'https://old' },
        { slug: 'prod', name: 'Prod', environment: 'production', base_url: 'https://billing', auth: { kind: 'secret', ref: 'billing-token' } },
        { slug: 'staging', name: 'Staging', environment: 'staging', base_url: 'https://staging' },
      ],
    });
    expect(targetLabel(prod)).toBe('Prod (production) — https://billing');
    expect(targetSignIn(prod)).toBe('Secret · billing-token');
    expect(targetSignIn(staging)).toBe('None');
    expect(readTargets({ targets: [{ name: 'no slug' }] })).toEqual([]);
  });

  it('adds a production target read-only, signing in with a secret by name', () => {
    expect(targetSlug(' Billing Staging! ')).toBe('billing-staging');
    expect(newTargetProblems({ name: '', baseUrl: 'nope', production: false, secret: 'has space' })).toHaveLength(3);
    expect(newTargetBody({ name: 'Billing prod', baseUrl: 'https://billing.example', production: true, secret: 'billing-token' })).toEqual({
      slug: 'billing-prod',
      name: 'Billing prod',
      environment: 'production',
      base_url: 'https://billing.example',
      auth: { kind: 'secret', scheme: 'bearer', ref: 'billing-token' },
      policy: { allow_mutating_methods: false },
    });
  });

  it('links to the page for one provider', () => {
    expect(verifyRunRoute('billing service')).toBe('/ade/dashboard/pacts/verification/new?provider=billing+service');
    expect(verifyRunRoute()).toBe('/ade/dashboard/pacts/verification/new');
  });
});
