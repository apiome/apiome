/**
 * Shared steps of the Catalog Exporter journey (X2, #6223): importing a spec into the Catalog
 * through the import dialog, and reading a downloaded export archive.
 */
import { readFile } from 'node:fs/promises';
import { expect, type Download, type Page } from '@playwright/test';
import { readZip, type ReadZipFile } from '../../../src/app/components/ade/dashboard/export/zipBundle';

/**
 * Paste ``source`` into the Catalog's **Import to catalog** dialog and import it, waiting until the
 * import reports the item is stored. The wizard's routing and options steps are walked with
 * **Continue**; the quality step's own **Import** finishes it.
 *
 * @param page The signed-in page.
 * @param source The spec text to paste.
 */
export async function importIntoCatalog(page: Page, source: string): Promise<void> {
  await page.goto('/ade/dashboard/catalog');
  await page.getByTestId('catalog-import').click();

  await page.getByTestId('catalog-import-source-paste').click();
  await page.getByLabel('Source content').fill(source);
  await page.getByRole('button', { name: /detect pasted source/i }).click();
  await expect(page.getByText(/Auto-detected/i).first()).toBeVisible({ timeout: 30_000 });

  const quality = page.getByTestId('import-quality-grade');
  const next = page.getByRole('button', { name: /^continue$/i });
  for (let step = 0; step < 3 && !(await quality.isVisible()); step += 1) {
    await next.click();
    await expect(quality.or(next)).toBeVisible({ timeout: 30_000 });
  }
  await expect(quality).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('import-quality-import').click();

  await expect(page.getByText(/Stored in the catalog in its original format/)).toBeVisible({
    timeout: 120_000,
  });
  await page.keyboard.press('Escape');
}

/**
 * Acknowledge a lossy or severe conversion when the screen asks: a typed phrase (the input's
 * placeholder) for a near-empty result, else the "Export anyway" checkbox. A clean conversion asks
 * for neither.
 *
 * @param page The page showing a fidelity panel.
 */
export async function acknowledgeLossIfAsked(page: Page): Promise<void> {
  const typed = page.getByTestId('export-ack-typed-input');
  if (await typed.isVisible()) {
    await typed.fill((await typed.getAttribute('placeholder')) ?? '');
    return;
  }
  const ack = page.getByTestId('export-ack');
  if (await ack.isVisible()) await ack.click();
}

/**
 * Click ``trigger`` and return the archive the browser downloaded, unpacked.
 *
 * @param page The page.
 * @param trigger Clicks the button that downloads.
 * @returns The download's suggested filename and its files.
 */
export async function downloadArchive(
  page: Page,
  trigger: () => Promise<void>,
): Promise<{ filename: string; files: ReadZipFile[] }> {
  const [download]: [Download, void] = await Promise.all([
    page.waitForEvent('download', { timeout: 120_000 }),
    trigger(),
  ]);
  const path = await download.path();
  const bytes = new Uint8Array(await readFile(path));
  return { filename: download.suggestedFilename(), files: await readZip(bytes) };
}
