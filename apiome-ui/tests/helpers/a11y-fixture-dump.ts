/**
 * Fixture dumps for the HIVE-10.2 axe gate (#5338).
 *
 * A few redesigned surfaces only render behind a session (the shell, the launcher, the
 * onboarding wizard, OAuth sign-up, the settings pane), and the browser gate runs with no
 * database. Their Jest suites therefore write what they rendered into
 * `e2e/fixtures/hive-a11y/` when `A11Y_FIXTURE_DUMP=1` is set:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/app-shell.test.tsx -t fixture
 *
 * and `e2e/a11y/gate.spec.ts` mounts those files into `/login` (which compiles the real
 * `globals.css`) and runs axe over them in every gate theme. Without the variable the test still
 * renders the surface and checks the markup is non-empty, so a change that would leave a fixture
 * stale fails here first.
 */

import fs from 'node:fs';
import path from 'node:path';

/** Where the gate reads these fixtures from. */
export const A11Y_FIXTURE_DIR = path.join(__dirname, '..', '..', 'e2e', 'fixtures', 'hive-a11y');

/**
 * Write one fixture, or just assert it could be written.
 *
 * @param name File stem, e.g. `shell` → `shell.html`.
 * @param html The rendered markup.
 */
export function writeA11yFixture(name: string, html: string): void {
  expect(html.length).toBeGreaterThan(0);
  if (process.env.A11Y_FIXTURE_DUMP !== '1') return;
  fs.mkdirSync(A11Y_FIXTURE_DIR, { recursive: true });
  fs.writeFileSync(path.join(A11Y_FIXTURE_DIR, `${name}.html`), `${html}\n`);
}
