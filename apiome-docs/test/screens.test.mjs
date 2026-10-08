import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {afterEach, beforeEach, describe, it} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  APP_THEMES,
  SCREEN_DEFAULTS,
  checkScreenshots,
  findScreenshotReferences,
  imagePath,
  loadManifest,
  normalizeScreen,
  parseData,
  parseScreenshotArgs,
  planCapture,
  selectScreens,
  validateManifest,
} from '../scripts/lib/screens.mjs';
import {resolveScreenshot, screenshotImagePath} from '../src/components/Screenshot/resolve.ts';

const SITE_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const FIXTURE_ROOT = path.join(SITE_DIR, '..', 'apiome-ui', 'e2e', 'fixtures');

/**
 * A valid raw entry, with overrides.
 *
 * @param {Record<string, unknown>} overrides - Fields to replace or add.
 * @returns {Record<string, unknown>} The entry.
 */
function entry(overrides = {}) {
  return {id: 'catalog', route: '/ade/dashboard/catalog', waitFor: 'main', data: 'golden-path', ...overrides};
}

describe('parseData', () => {
  it('reads golden-path and fixture sources', () => {
    assert.deepEqual(parseData('golden-path'), {kind: 'golden-path'});
    assert.deepEqual(parseData('signed-out'), {kind: 'signed-out'});
    assert.deepEqual(parseData('fixture:hive-catalog/table.html'), {
      kind: 'fixture',
      dir: 'hive-catalog',
      file: 'table.html',
    });
  });
  it('rejects anything else, including paths that climb out of the fixtures', () => {
    for (const value of ['', 'fixture:', 'fixture:../x/y.html', 'fixture:a/b/c.html', 'fixture:a/b.png', 42, null]) {
      assert.equal(parseData(value), null, String(value));
    }
  });
});

describe('normalizeScreen', () => {
  it('fills in the defaults', () => {
    const {screen, problems} = normalizeScreen(entry());
    assert.deepEqual(problems, []);
    assert.deepEqual(screen.theme, ['light', 'dark']);
    assert.deepEqual(screen.viewport, SCREEN_DEFAULTS.viewport);
    assert.equal(screen.density, 'comfortable');
    assert.equal(screen.fontScale, 'md');
    assert.deepEqual(screen.mask, []);
  });
  it('keeps explicit values', () => {
    const {screen} = normalizeScreen(
      entry({
        theme: ['dark'],
        viewport: {width: 800, height: 600},
        density: 'compact',
        fontScale: 'lg',
        mask: ['time'],
        clip: {x: 0, y: 0, width: 400, height: 300},
        fallback: 'fixture:hive-catalog/table.html',
      }),
    );
    assert.deepEqual(screen.theme, ['dark']);
    assert.deepEqual(screen.clip, {x: 0, y: 0, width: 400, height: 300});
    assert.deepEqual(screen.fallback, {kind: 'fixture', dir: 'hive-catalog', file: 'table.html'});
  });
  it('keeps an app theme pin, and leaves it out when unset', () => {
    assert.equal(normalizeScreen(entry({appTheme: 'nord'})).screen.appTheme, 'nord');
    assert.equal('appTheme' in normalizeScreen(entry()).screen, false);
  });
  it('rejects an app theme the product does not have, and `system`', () => {
    for (const appTheme of ['sepia', 'system', 'Nord']) {
      const {screen, problems} = normalizeScreen(entry({appTheme}));
      assert.equal(screen, null);
      assert.match(problems[0], /`appTheme` must be one of/);
    }
  });
  it('lists the eight palettes of apiome-ui', () => {
    const source = fs.readFileSync(path.join(SITE_DIR, '..', 'apiome-ui', 'src', 'app', 'config', 'themes.ts'), 'utf8');
    const ids = [...source.matchAll(/^ {4}id: '([a-z-]+)',$/gm)].map((match) => match[1]).filter((id) => id !== 'system');
    assert.deepEqual([...new Set(ids)].sort(), [...APP_THEMES].sort());
  });
  it('reports every bad field, named by id', () => {
    const {screen, problems} = normalizeScreen(
      entry({
        route: 'ade',
        waitFor: ' ',
        data: 'stack',
        theme: ['sepia'],
        viewport: {width: 0, height: 900},
        density: 'cozy',
        fontScale: 'huge',
        mask: [''],
        clip: {x: -1, y: 0, width: 10, height: 10},
      }),
    );
    assert.equal(screen, null);
    assert.equal(problems.length, 9);
    assert.ok(problems.every((problem) => problem.startsWith('catalog: ')));
  });
  it('rejects a bad id, duplicate themes and a fallback on a fixture entry', () => {
    assert.match(normalizeScreen(entry({id: 'Catalog Page'})).problems[0], /`id`/);
    assert.match(normalizeScreen(entry({theme: ['light', 'light']})).problems[0], /`theme`/);
    assert.match(
      normalizeScreen(entry({data: 'fixture:a/b.html', fallback: 'fixture:a/c.html'})).problems[0],
      /only applies/,
    );
    assert.match(normalizeScreen(entry({fallback: 'golden-path'})).problems[0], /`fallback`/);
  });
  it('rejects a non-object entry', () => {
    assert.equal(normalizeScreen('catalog').screen, null);
    assert.equal(normalizeScreen(null).screen, null);
  });
});

describe('validateManifest', () => {
  it('needs a screens array', () => {
    assert.deepEqual(validateManifest({}).problems, ['screens.json must be {"screens": [ … ]}']);
  });
  it('rejects duplicate ids and keeps the first', () => {
    const {screens, problems} = validateManifest({screens: [entry(), entry({route: '/other'})]});
    assert.equal(screens.length, 1);
    assert.deepEqual(problems, ['catalog: duplicate id']);
  });
});

describe('the committed screens.json', () => {
  const {screens, problems} = loadManifest(path.join(SITE_DIR, 'screens.json'));

  it('is valid', () => {
    assert.deepEqual(problems, []);
    assert.ok(screens.length > 0);
  });
  it('names fixtures that exist', () => {
    for (const screen of screens) {
      for (const source of [screen.data, screen.fallback].filter((s) => s?.kind === 'fixture')) {
        assert.ok(fs.existsSync(path.join(FIXTURE_ROOT, source.dir, source.file)), `${screen.id}: ${source.dir}/${source.file}`);
      }
    }
  });
  it('captures every entry at 1440 × 900 in light and dark', () => {
    for (const screen of screens) {
      assert.deepEqual(screen.viewport, {width: 1440, height: 900}, screen.id);
      assert.deepEqual(screen.theme, ['light', 'dark'], screen.id);
    }
  });
});

describe('loadManifest', () => {
  it('reports a missing or unparsable file instead of throwing', () => {
    assert.match(loadManifest('/no/such/screens.json').problems[0], /screens\.json/);
  });
});

describe('imagePath and the component agree', () => {
  it('name the same file', () => {
    assert.equal(`/${imagePath('catalog', 'dark')}`, screenshotImagePath('catalog', 'dark'));
  });
});

describe('selectScreens', () => {
  const screens = [
    normalizeScreen(entry()).screen,
    normalizeScreen(entry({id: 'versions', route: '/ade/dashboard/versions'})).screen,
    normalizeScreen(entry({id: 'sunset', route: '/ade/dashboard/versions/sunset-timeline'})).screen,
  ];
  it('selects everything without filters', () => {
    assert.equal(selectScreens(screens).length, 3);
  });
  it('filters by exact id', () => {
    assert.deepEqual(selectScreens(screens, {ids: ['versions']}).map((s) => s.id), ['versions']);
  });
  it('filters by route prefix', () => {
    assert.deepEqual(selectScreens(screens, {routes: ['/ade/dashboard/versions']}).map((s) => s.id), [
      'versions',
      'sunset',
    ]);
  });
});

describe('planCapture', () => {
  const golden = normalizeScreen(entry()).screen;
  const withFallback = normalizeScreen(entry({id: 'b', fallback: 'fixture:d/f.html'})).screen;
  const fixture = normalizeScreen(entry({id: 'c', data: 'fixture:d/g.html', theme: ['dark']})).screen;

  it('captures golden-path entries from the stack when it is up', () => {
    const {jobs, skipped} = planCapture([golden, withFallback, fixture], {stackAvailable: true});
    assert.deepEqual(skipped, []);
    assert.deepEqual(
      jobs.map((job) => `${job.output}:${job.source.kind}`),
      [
        'img/screens/catalog.light.png:golden-path',
        'img/screens/catalog.dark.png:golden-path',
        'img/screens/b.light.png:golden-path',
        'img/screens/b.dark.png:golden-path',
        'img/screens/c.dark.png:fixture',
      ],
    );
  });
  it('captures a signed-out entry from the live route whether or not the stack is up', () => {
    const login = normalizeScreen(entry({id: 'login', route: '/login', data: 'signed-out'})).screen;
    for (const stackAvailable of [true, false]) {
      const {jobs, skipped} = planCapture([login], {stackAvailable});
      assert.deepEqual(skipped, []);
      assert.deepEqual(jobs.map((job) => job.source.kind), ['signed-out', 'signed-out']);
    }
  });
  it('rejects a fallback on a signed-out entry', () => {
    assert.match(normalizeScreen(entry({data: 'signed-out', fallback: 'fixture:a/b.html'})).problems[0], /only applies/);
  });
  it('falls back to the fixture, or skips, when the stack is down', () => {
    const {jobs, skipped} = planCapture([golden, withFallback, fixture], {stackAvailable: false});
    assert.deepEqual(skipped.map((s) => s.id), ['catalog']);
    assert.deepEqual(jobs.map((job) => `${job.screen.id}:${job.source.kind}`), ['b:fixture', 'b:fixture', 'c:fixture']);
  });
});

describe('parseScreenshotArgs', () => {
  it('reads repeated, comma-separated and inline values, and ignores a bare --', () => {
    const args = parseScreenshotArgs(['--', '--id', 'a,b', '--id=c', '--route', '/ade', '--start-ui', '--boot']);
    assert.deepEqual(args.ids, ['a', 'b', 'c']);
    assert.deepEqual(args.routes, ['/ade']);
    assert.equal(args.startUi, true);
    assert.equal(args.boot, true);
    assert.equal(args.fixturesOnly, false);
  });
  it('trims a trailing slash from --ui-url', () => {
    assert.equal(parseScreenshotArgs(['--ui-url', 'http://localhost:3300/']).uiUrl, 'http://localhost:3300');
  });
  it('rejects unknown options and missing values', () => {
    assert.throws(() => parseScreenshotArgs(['--theme', 'dark']), /unknown option --theme/);
    assert.throws(() => parseScreenshotArgs(['--id']), /--id needs a value/);
    assert.throws(() => parseScreenshotArgs(['--id', '--boot']), /--id needs a value/);
  });
});

describe('findScreenshotReferences', () => {
  it('finds ids in every quoting style', () => {
    const source = `<Screenshot id="a" alt="A"/>\n<Screenshot alt='B' id='b'/>\n<Screenshot id={"c"} alt="C" />`;
    assert.deepEqual(findScreenshotReferences(source), ['a', 'b', 'c']);
  });
  it('skips examples in fenced and inline code, and lists each id once', () => {
    const source = [
      '<Screenshot id="a" alt="A"/>',
      '   ```mdx',
      '   <Screenshot id="in-fence" alt="x"/>',
      '   ```',
      'Use `<Screenshot id="inline" alt="x"/>` like this.',
      '<Screenshot id="a" alt="A again"/>',
    ].join('\n');
    assert.deepEqual(findScreenshotReferences(source), ['a']);
  });
  it('ignores other components', () => {
    assert.deepEqual(findScreenshotReferences('<Route path="/x"/> <ScreenshotGallery id="z"/>'), []);
  });
});

describe('checkScreenshots', () => {
  let staticDir;
  const screens = [normalizeScreen(entry()).screen, normalizeScreen(entry({id: 'dark-only', theme: ['dark']})).screen];

  beforeEach(() => {
    staticDir = fs.mkdtempSync(path.join(os.tmpdir(), 'docs-screens-'));
    fs.mkdirSync(path.join(staticDir, 'img', 'screens'), {recursive: true});
  });
  afterEach(() => fs.rmSync(staticDir, {recursive: true, force: true}));

  /** Write an empty image file. */
  const touch = (id, theme) => fs.writeFileSync(path.join(staticDir, imagePath(id, theme)), '');

  it('passes when every entry has its images and pages reference known, two-theme ids', () => {
    touch('catalog', 'light');
    touch('catalog', 'dark');
    touch('dark-only', 'dark');
    const pages = [{page: 'docs/a.mdx', source: '<Screenshot id="catalog" alt="x"/>'}];
    assert.deepEqual(checkScreenshots({screens, pages, staticDir}), []);
  });
  it('fails for a manifest entry without its image', () => {
    touch('catalog', 'light');
    touch('dark-only', 'dark');
    const problems = checkScreenshots({screens, pages: [], staticDir});
    assert.equal(problems.length, 1);
    assert.match(problems[0], /`catalog` has no dark image/);
  });
  it('fails for an unknown id and for a one-theme entry on a page', () => {
    touch('catalog', 'light');
    touch('catalog', 'dark');
    touch('dark-only', 'dark');
    const pages = [{page: 'docs/a.mdx', source: '<Screenshot id="nope" alt="x"/> <Screenshot id="dark-only" alt="y"/>'}];
    assert.deepEqual(checkScreenshots({screens, pages, staticDir}), [
      'docs/a.mdx: <Screenshot id="nope"/> is not in screens.json',
      'docs/a.mdx: <Screenshot id="dark-only"/> needs both a light and a dark image',
    ]);
  });
});

describe('resolveScreenshot', () => {
  const screens = [
    {id: 'catalog', route: '/ade/dashboard/catalog'},
    {id: 'dark-only', route: '/x', theme: ['dark']},
    {id: 'small', route: '/y', viewport: {width: 800, height: 500}},
  ];
  it('returns the route, both images and the capture size', () => {
    assert.deepEqual(resolveScreenshot(screens, 'catalog', 'The catalog'), {
      route: '/ade/dashboard/catalog',
      sources: {light: '/img/screens/catalog.light.png', dark: '/img/screens/catalog.dark.png'},
      width: 1440,
      height: 900,
    });
    assert.equal(resolveScreenshot(screens, 'small', 'Small').width, 800);
  });
  it('refuses blank alt text, an unknown id and a one-theme entry', () => {
    assert.throws(() => resolveScreenshot(screens, 'catalog', '  '), /needs alt text/);
    assert.throws(() => resolveScreenshot(screens, 'nope', 'x'), /no such id/);
    assert.throws(() => resolveScreenshot(screens, 'dark-only', 'x'), /light and dark/);
  });
});
