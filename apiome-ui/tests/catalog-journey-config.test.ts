/**
 * @jest-environment node
 */
/**
 * The wiring of the Catalog → Project journey (RC6-H1, #6208), held without a browser.
 *
 * The journey itself (`e2e/journey/catalog-project-journey.spec.ts`) needs a live stack and runs
 * in `.github/workflows/e2e-catalog-journey.yml`. What can silently break it without that stack is
 * pinned here:
 *
 *   - its server runs with **no preview override**, even when `.env` or the shell sets one;
 *   - its config runs that spec alone, and the OLO journey config (which turns every preview on)
 *     never runs it;
 *   - the workflow runs on pull requests touching apiome-ui, apiome-rest or apiome-db, with the
 *     override empty at build time too;
 *   - the spec waits on screens, never on a clock, and every `data-testid` it waits on is still
 *     drawn somewhere in `src/` — a renamed test id fails here, not an hour later in CI.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { parse as parseYaml } from 'yaml';

import { isFeatureReleased, UNRELEASED_FEATURE_IDS } from '../lib/feature-release';
import { catalogJourneyServerEnv, journeyServerEnv } from '../e2e/journey/support/env';

const ROOT = join(__dirname, '..');
const SPEC = join(ROOT, 'e2e', 'journey', 'catalog-project-journey.spec.ts');
const WORKFLOW = join(ROOT, '..', '.github', 'workflows', 'e2e-catalog-journey.yml');

/** Every `.ts` / `.tsx` source under `src/`, read once. */
function sourceText(directory: string = join(ROOT, 'src')): string {
  return readdirSync(directory)
    .map((entry) => {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) return sourceText(path);
      return /\.tsx?$/.test(entry) ? readFileSync(path, 'utf8') : '';
    })
    .join('\n');
}

describe('the journey server environment', () => {
  const saved = { ...process.env };

  beforeEach(() => {
    process.env.DATABASE_URL = 'postgresql://journey:journey@localhost:5432/apiome';
  });

  afterEach(() => {
    process.env = { ...saved };
  });

  it('clears the preview override, even when the shell sets one', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    const env = catalogJourneyServerEnv();
    expect(env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES).toBe('');
    for (const id of UNRELEASED_FEATURE_IDS) {
      expect(isFeatureReleased(id, env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES)).toBe(false);
    }
  });

  it('keeps everything else the OLO journey server boots with', () => {
    const { NEXT_PUBLIC_APIOME_PREVIEW_FEATURES: catalogPreview, ...catalog } = catalogJourneyServerEnv();
    const { NEXT_PUBLIC_APIOME_PREVIEW_FEATURES: oloPreview, ...olo } = journeyServerEnv();
    expect(catalog).toEqual(olo);
    expect(oloPreview).toBe('all');
    expect(catalogPreview).toBe('');
  });
});

describe('the Playwright configs', () => {
  const read = (name: string) => readFileSync(join(ROOT, name), 'utf8');

  it('runs the journey alone, on the no-preview server', () => {
    const config = read('playwright.catalog-journey.config.ts');
    expect(config).toContain("testMatch: 'catalog-project-journey.spec.ts'");
    expect(config).toContain('env: catalogJourneyServerEnv()');
    expect(config).not.toContain('journeyServerEnv()\n');
  });

  it('keeps the journey out of the OLO config, which turns every preview on', () => {
    expect(read('playwright.journey.config.ts')).toContain("testIgnore: ['catalog-project-journey.spec.ts']");
  });

  it('has a package script', () => {
    const { scripts } = JSON.parse(read('package.json')) as { scripts: Record<string, string> };
    expect(scripts['test:e2e:catalog-journey']).toBe(
      'playwright test --config playwright.catalog-journey.config.ts'
    );
  });
});

describe('the CI workflow', () => {
  const workflow = parseYaml(readFileSync(WORKFLOW, 'utf8')) as {
    on: { pull_request: { paths: string[] }; workflow_dispatch: unknown };
    jobs: { journey: { env: Record<string, string>; steps: { name: string; run?: string; env?: Record<string, string> }[] } };
  };

  it('runs on every pull request that touches apiome-ui, apiome-rest or apiome-db', () => {
    expect(workflow.on.pull_request.paths).toEqual(
      expect.arrayContaining(['apiome-ui/**', 'apiome-rest/**', 'apiome-db/**'])
    );
    expect(workflow.on).toHaveProperty('workflow_dispatch');
  });

  it('builds and runs with the preview override empty', () => {
    const { env, steps } = workflow.jobs.journey;
    expect(env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES).toBe('');
    const build = steps.findIndex((step) => step.run === 'yarn build');
    const run = steps.findIndex((step) => step.run === 'yarn test:e2e:catalog-journey');
    expect(build).toBeGreaterThan(-1);
    expect(run).toBeGreaterThan(build);
    expect(steps[run].env?.CATALOG_JOURNEY_USE_BUILD).toBe('1');
  });
});

describe('the journey spec', () => {
  const spec = readFileSync(SPEC, 'utf8');

  it('waits on screens, never on a clock', () => {
    expect(spec).not.toMatch(/waitForTimeout|setTimeout|\bsleep\(/);
  });

  it('never sets a preview override of its own', () => {
    expect(spec).not.toMatch(/NEXT_PUBLIC_APIOME_PREVIEW_FEATURES\s*[:=]/);
  });

  it('waits only on test ids the app still draws', () => {
    const source = sourceText();
    const ids = [...spec.matchAll(/getByTestId\(\s*(['`])([^'`]+)\1/g)].map((match) => match[2]);
    const prefixes = [...spec.matchAll(/\[data-testid\^="([^"]+)"\]/g)].map((match) => match[1]);
    expect(ids.length).toBeGreaterThan(20);

    const missing = [
      ...ids.map((id) => {
        // `versions-row-menu-${versionRecordId}` → the app draws `versions-row-menu-${version.id}`.
        const prefix = id.split('${')[0];
        if (prefix === '') return null;
        if (id.includes('${')) return source.includes(`data-testid={\`${prefix}`) ? null : id;
        // A literal id is drawn as written, or built from a template whose stem it starts with
        // (`catalog-import-source-${tile.method}` draws `catalog-import-source-paste`).
        const stem = id.slice(0, id.lastIndexOf('-') + 1);
        const drawn =
          source.includes(`data-testid="${id}"`) ||
          source.includes(`'${id}'`) ||
          (stem !== '' && source.includes(`\`${stem}\${`));
        return drawn ? null : id;
      }),
      ...prefixes.map((prefix) => (source.includes(`data-testid={\`${prefix}`) ? null : prefix)),
    ].filter(Boolean);
    expect(missing).toEqual([]);
  });
});
