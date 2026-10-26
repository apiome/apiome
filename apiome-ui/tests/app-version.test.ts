/**
 * The build badge (`lib/app-version.ts`): an unstamped build names its release candidate.
 */
import packageJson from '../package.json';

describe('app-version', () => {
  const original = process.env.NEXT_PUBLIC_APP_BUILD_LABEL;

  afterEach(() => {
    if (original === undefined) delete process.env.NEXT_PUBLIC_APP_BUILD_LABEL;
    else process.env.NEXT_PUBLIC_APP_BUILD_LABEL = original;
    jest.resetModules();
  });

  function load(label?: string) {
    if (label === undefined) delete process.env.NEXT_PUBLIC_APP_BUILD_LABEL;
    else process.env.NEXT_PUBLIC_APP_BUILD_LABEL = label;
    let mod: typeof import('../lib/app-version') | undefined;
    jest.isolateModules(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports -- re-read the env per test
      mod = require('../lib/app-version');
    });
    return mod!;
  }

  test('an unstamped build shows the semver and RC7', () => {
    const { APP_VERSION_BADGE, APP_RELEASE_CANDIDATE } = load();
    expect(APP_RELEASE_CANDIDATE).toBe('RC7');
    expect(APP_VERSION_BADGE).toBe(`v${packageJson.version} RC7`);
  });

  test('a blank build label still reads as unstamped', () => {
    expect(load('   ').APP_VERSION_BADGE).toBe(`v${packageJson.version} RC7`);
  });

  test('a CI build label wins', () => {
    expect(load('2026.10.25-abc1234').APP_VERSION_BADGE).toBe('2026.10.25-abc1234');
  });
});
