/**
 * MCP → Agent access, in a browser (AGX-3.4, #4540).
 *
 * The ticket's acceptance criteria, driven through the real app:
 *
 *   1. **A tenant goes from a published version to a working agent key with a curated toolset
 *      entirely in the UI** — Enable Agent Access on the seeded published version, curate its
 *      tools, mint a key from the toolset editor, see the secret once.
 *   2. **Enabling a write operation surfaces the explicit confirmation**, and only the confirm
 *      sends `confirmWriteOp: true`.
 *   3. **The usage charts render** calls, errors, latency, calls per tool and top agents, and the
 *      page never scrolls sideways.
 *
 * Stack contract is the same as the other journey specs (`playwright.journey.config.ts` brings up
 * a dev server; REST + Postgres must already be up). The tenant, a credentials user and a
 * published version come from `support/review-fixture.ts`. The `/api/agent-access/*` BFF is
 * answered in the browser by an in-memory fake: a toolset needs a version with captured source and
 * usage needs rollups written by the MCP runtime, neither of which a seeded database can produce
 * on demand. The fake follows apiome-rest's contract, including the
 * `agent-toolset-write-op-unconfirmed` refusal.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { closeDb } from './support/db';
import { closeReviewFixtureDb, seedReviewFixture, type ReviewFixture } from './support/review-fixture';

let fixture: ReviewFixture;

interface FakeTool {
  id: string;
  operation: string;
  toolName: string;
  writeOp: boolean;
  enabled: boolean;
}

/** The fake BFF's state, and every write it saw. */
interface FakeState {
  toolsets: Array<Record<string, unknown> & { id: string; tools: FakeTool[] }>;
  keys: Array<Record<string, unknown>>;
  writes: Array<{ method: string; path: string; body: unknown }>;
}

/** Counts a toolset reply carries. */
function counts(tools: FakeTool[]) {
  return {
    toolCount: tools.length,
    enabledToolCount: tools.filter((t) => t.enabled).length,
    enabledWriteOpCount: tools.filter((t) => t.enabled && t.writeOp).length,
  };
}

/**
 * Answer `/api/agent-access/**` from an in-memory fake.
 *
 * @param page - The Playwright page.
 * @returns The fake's state, for assertions.
 */
async function fakeAgentAccess(page: Page): Promise<FakeState> {
  const state: FakeState = { toolsets: [], keys: [], writes: [] };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

  await page.route('**/api/agent-access/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const body = request.postData() ? JSON.parse(request.postData() as string) : undefined;
    const parts = url.pathname.replace('/api/agent-access/', '').split('/');
    if (method !== 'GET') state.writes.push({ method, path: url.pathname, body });

    if (parts[0] === 'toolsets' && parts.length === 1) {
      if (method === 'POST') {
        const tools: FakeTool[] = [
          { id: 'tl', operation: 'GET /pets', toolName: 'listPets', writeOp: false, enabled: true },
          { id: 'tc', operation: 'POST /pets', toolName: 'createPet', writeOp: true, enabled: false },
        ];
        const created = {
          id: 'ts-1',
          versionId: body.versionId,
          projectId: fixture.projectId,
          versionLabel: fixture.baseline.label,
          enabled: true,
          target: body.target,
          tools,
        };
        state.toolsets.push(created);
        return json(route, { success: true, data: { ...created, ...counts(tools) } }, 201);
      }
      return json(route, {
        success: true,
        data: { toolsets: state.toolsets.map((t) => ({ ...t, ...counts(t.tools), tools: undefined })) },
      });
    }
    if (parts[0] === 'toolsets') {
      const ts = state.toolsets.find((t) => t.id === parts[1]);
      if (!ts) return json(route, { success: false, error: 'no such agent toolset' }, 404);
      if (parts[2] === 'tools') {
        const tool = ts.tools.find((t) => t.id === parts[3]) as FakeTool;
        if (body.enabled && tool.writeOp && !tool.enabled && !body.confirmWriteOp) {
          return json(
            route,
            { success: false, error: 'needs confirmWriteOp', code: 'agent-toolset-write-op-unconfirmed' },
            422
          );
        }
        tool.enabled = body.enabled;
        return json(route, { success: true, data: tool });
      }
      if (method === 'PATCH') Object.assign(ts, body);
      return json(route, { success: true, data: { ...ts, ...counts(ts.tools) } });
    }
    if (parts[0] === 'keys' && parts.length === 1) {
      if (method === 'POST') {
        const key = {
          id: 'k-1',
          name: body.name,
          keyPrefix: 'ak_e2e00001...',
          toolsetId: body.toolsetId,
          toolAllowlist: body.toolAllowlist,
          status: 'active',
          expiresAt: body.expiresAt ?? null,
        };
        state.keys.push(key);
        return json(route, { success: true, data: { ...key, secret: 'ak_e2e_secret_once' } }, 201);
      }
      return json(route, { success: true, data: { keys: state.keys } });
    }
    if (parts[0] === 'keys' && parts[2] === 'usage') {
      return json(route, {
        success: true,
        data: {
          keyId: parts[1],
          rps: { cap: 2 },
          dailyCalls: { day: '2026-10-06', cap: 1000, used: 240, remaining: 760, resetsAt: 'x' },
        },
      });
    }
    if (parts[0] === 'usage') {
      const day = (i: number) => ({
        day: `2026-10-0${i + 1}`,
        calls: 20 + i,
        errors: 1,
        errorRate: 1 / (20 + i),
        latencyAvgMs: 150 + i * 10,
        latencyP95MaxMs: 300,
      });
      return json(route, {
        success: true,
        data: {
          startDay: '2026-10-01',
          endDay: '2026-10-07',
          days: 7,
          totals: {
            calls: 161, errors: 7, errorRate: 7 / 161, latencyAvgMs: 180, latencyP95MaxMs: 300,
            successCalls: 154, upstreamErrors: 5, validationFailures: 0, quotaRejections: 2, internalErrors: 0,
          },
          daily: Array.from({ length: 7 }, (_, i) => day(i)),
          tools: [{ toolName: 'listPets', calls: 161, errors: 7, errorRate: 7 / 161, latencyAvgMs: 180, latencyP95MaxMs: 300 }],
          agents: [{ keyId: 'k-1', name: 'claude-desktop', keyPrefix: 'ak_e2e00001...', revoked: false, calls: 161, errors: 7, errorRate: 7 / 161, latencyAvgMs: 180, latencyP95MaxMs: 300 }],
        },
      });
    }
    return json(route, { success: false, error: `unrouted ${method} ${url.pathname}` }, 500);
  });
  return state;
}

/**
 * Sign the fixture's credentials user in.
 *
 * @param page - The Playwright page.
 */
async function signIn(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.getByRole('button', { name: 'or use your email' }).click();
  await page.locator('#email').fill(fixture.reviewer.email);
  await page.locator('#password').fill(fixture.reviewer.password);
  await page.locator('#credentials-form').getByRole('button', { name: /Sign In/ }).click();
  await page.waitForURL(/\/ade/, { timeout: 60_000 });
}

/**
 * Whether the document scrolls sideways.
 *
 * @param page - The Playwright page.
 */
async function scrollsSideways(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fixture = await seedReviewFixture();
});

test.afterAll(async () => {
  await closeReviewFixtureDb();
  await closeDb();
});

test.describe('AGX-3.4 — agent access', () => {
  test('published version → curated toolset → agent key, entirely in the UI', async ({ page }) => {
    const fake = await fakeAgentAccess(page);
    await signIn(page);
    await page.goto('/ade/dashboard/mcp/agents');
    await expect(page.getByRole('heading', { level: 1, name: 'Agent access' })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('mcp-section-tab-agents')).toHaveAttribute('aria-current', 'page');

    // Enable Agent Access on the seeded published version.
    await page.getByTestId('agx-toolsets-empty-enable').click();
    const enable = page.getByTestId('agx-enable-dialog');
    await expect(enable.getByLabel('Published version')).toContainText(fixture.baseline.label);
    await enable.getByTestId('agx-enable-submit').click();
    await expect(page.getByTestId('agx-tool-row-createPet')).toBeVisible();
    expect(fake.writes[0]).toMatchObject({
      method: 'POST',
      body: { versionId: fixture.baseline.id, target: 'prod' },
    });

    // The write op asks first, and only the confirm carries confirmWriteOp.
    await page.getByTestId('agx-tool-switch-createPet').click({ force: true });
    const confirm = page.getByTestId('agx-write-confirm');
    await expect(confirm).toContainText('createPet');
    await confirm.getByTestId('agx-write-confirm-confirm').click();
    await expect(page.getByTestId('agx-tool-switch-createPet')).toBeChecked();
    expect(fake.writes.at(-1)).toMatchObject({ body: { enabled: true, confirmWriteOp: true } });

    // Mint a key from the toolset editor.
    await page.getByTestId('agx-toolset-create-key').click();
    const create = page.getByTestId('agx-key-create-dialog');
    await create.getByLabel(/Name/).fill('claude-desktop');
    await expect(create.getByLabel('createPet')).toBeChecked();
    await create.getByTestId('agx-key-create-submit').click();

    const reveal = page.getByTestId('api-key-secret-dialog');
    await expect(reveal.getByTestId('api-key-secret-value')).toHaveText('ak_e2e_secret_once');
    await reveal.getByTestId('api-key-secret-ack').click();
    await expect(page.getByText('ak_e2e_secret_once')).toHaveCount(0);

    const row = page.getByTestId('agx-key-row-k-1');
    await expect(row).toContainText('claude-desktop');
    await expect(row.getByRole('meter')).toBeVisible();
    expect(await scrollsSideways(page)).toBe(false);
  });

  test('usage charts render from the rollups', async ({ page }) => {
    await fakeAgentAccess(page);
    await signIn(page);
    await page.goto('/ade/dashboard/mcp/agents');
    await page.getByTestId('agx-tab-usage').click();
    for (const chart of ['calls', 'errors', 'latency', 'tools', 'agents']) {
      await expect(page.getByTestId(`agx-chart-${chart}`).locator('svg').first()).toBeVisible();
    }
    await expect(page.getByTestId('agx-usage-agents-table')).toContainText('claude-desktop');
    expect(await scrollsSideways(page)).toBe(false);
  });
});
