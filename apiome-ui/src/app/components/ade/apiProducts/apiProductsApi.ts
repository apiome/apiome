/**
 * Browser calls for API products (APX-1.1, #6098), through the `/api/products` proxy.
 *
 * Nothing here talks to apiome-rest directly. A failure is thrown as an `Error` carrying REST's
 * message, so a caller can show it next to the control that failed.
 */

import type {
  ApiProduct,
  ApiProductInput,
  ApiProductPatch,
  ProductMemberInput,
} from '@lib/api-products';

/**
 * Read a proxy answer, or throw its message.
 *
 * @param response - The proxy response.
 * @param fallback - The message when the answer carries none.
 * @returns The parsed body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/**
 * Send a JSON body.
 *
 * @param url - The proxy URL.
 * @param method - `POST` or `PATCH`.
 * @param body - The body.
 * @returns The response.
 */
function send(url: string, method: 'POST' | 'PATCH', body: unknown): Promise<Response> {
  return fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/** The proxy URL of one product. */
function productUrl(slug: string): string {
  return `/api/products/${encodeURIComponent(slug)}`;
}

/**
 * Every live product of the workspace, by name.
 *
 * @returns The products (without their member lists).
 */
export async function fetchProducts(): Promise<ApiProduct[]> {
  const body = await readJson<{ products?: ApiProduct[] }>(
    await fetch('/api/products', { cache: 'no-store' }),
    'Could not load the API products',
  );
  return Array.isArray(body.products) ? body.products : [];
}

/**
 * One product with its resolved members.
 *
 * @param slug - The product's slug.
 * @returns The product.
 */
export async function fetchProduct(slug: string): Promise<ApiProduct> {
  return readJson<ApiProduct>(await fetch(productUrl(slug), { cache: 'no-store' }), 'Could not load the product');
}

/**
 * Create a product.
 *
 * @param input - The product.
 * @returns The stored product.
 */
export async function createProduct(input: ApiProductInput): Promise<ApiProduct> {
  return readJson<ApiProduct>(await send('/api/products', 'POST', input), 'Could not create the product');
}

/**
 * Update a product.
 *
 * @param slug - The product's slug.
 * @param patch - The fields to change.
 * @returns The stored product.
 */
export async function updateProduct(slug: string, patch: ApiProductPatch): Promise<ApiProduct> {
  return readJson<ApiProduct>(await send(productUrl(slug), 'PATCH', patch), 'Could not save the product');
}

/**
 * Delete a product.
 *
 * @param slug - The product's slug.
 */
export async function deleteProduct(slug: string): Promise<void> {
  await readJson<unknown>(await fetch(productUrl(slug), { method: 'DELETE' }), 'Could not delete the product');
}

/**
 * Add a member.
 *
 * @param slug - The product's slug.
 * @param input - The member.
 * @returns The product with its members.
 */
export async function addProductMember(slug: string, input: ProductMemberInput): Promise<ApiProduct> {
  return readJson<ApiProduct>(await send(`${productUrl(slug)}/members`, 'POST', input), 'Could not add the member');
}

/**
 * Remove a member.
 *
 * @param slug - The product's slug.
 * @param memberId - The member's id.
 * @returns The product with its remaining members.
 */
export async function removeProductMember(slug: string, memberId: string): Promise<ApiProduct> {
  return readJson<ApiProduct>(
    await fetch(`${productUrl(slug)}/members/${encodeURIComponent(memberId)}`, { method: 'DELETE' }),
    'Could not remove the member',
  );
}
