/**
 * The Export page's proxies — PFX-8.18 (#7315). Server-only: each call is made to apiome-rest as
 * the signed-in user, so tenant scoping and the `pacts` permission (and, for a derived pact,
 * `consumer_contracts`) stay REST's.
 *
 * Unlike the plain forwarders in `pact-proxy.ts`, a refusal keeps what the page must show next to
 * it: REST's `code`, and the `findings` (a derive that yields no interaction) or `notices` (a pact
 * with no HTTP interaction) that say what was left out and why — nothing is dropped.
 */

import { NextResponse } from 'next/server';
import { resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { createRestAuthHeaders } from '@lib/rest-auth';
import { PACT_UNAVAILABLE, pactError } from '@lib/pact-proxy';
import { fileStem, MAX_ZIP_PACTS, pactFilePath, storedPact, type PactChoice } from '@lib/pact-export';
import { createZip, type ZipEntry } from '@lib/zip-store';

/** A REST answer, read. */
interface RestAnswer {
  ok: boolean;
  status: number;
  body: unknown;
}

/** How a proxy reads or writes a path below `/v1/tenants/{slug}` as the signed-in user. */
export type ExportCaller = (path: string, init?: { method: string; body?: unknown }) => Promise<RestAnswer>;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * The browser's body for a refusal: REST's message and code, and the findings or notices it sent.
 *
 * @param body - REST's error body (`{ detail: string | { code, message, findings?, notices? } }`).
 * @param status - REST's status.
 * @returns `{ success: false, error, code?, findings?, notices? }`.
 */
export function refusalBody(body: unknown, status: number): Record<string, unknown> {
  const detail = isObject(body) ? body.detail : undefined;
  if (typeof detail === 'string' && detail) return { success: false, error: detail };
  if (isObject(detail)) {
    const out: Record<string, unknown> = {
      success: false,
      error: typeof detail.message === 'string' && detail.message ? detail.message : `HTTP ${status}`,
    };
    if (typeof detail.code === 'string') out.code = detail.code;
    if (Array.isArray(detail.findings)) out.findings = detail.findings;
    if (Array.isArray(detail.notices)) out.notices = detail.notices;
    return out;
  }
  return { success: false, error: `The export was refused (HTTP ${status}).` };
}

/**
 * Run a proxy with a caller bound to the signed-in user's workspace.
 *
 * @param run - What to do with the caller.
 * @returns The proxy's answer; an unreachable REST is a 503.
 */
async function withCaller(run: (call: ExportCaller) => Promise<Response>): Promise<Response> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const headers = createRestAuthHeaders(resolved.user);
  const call: ExportCaller = async (path, init) => {
    const rest = await fetch(tenantUrl(resolved.slug, path), {
      method: init?.method ?? 'GET',
      headers: { ...headers, ...(init?.body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(init?.body === undefined ? {} : { body: JSON.stringify(init.body) }),
      cache: 'no-store',
    });
    return { ok: rest.ok, status: rest.status, body: await rest.json().catch(() => ({})) };
  };
  try {
    return await run(call);
  } catch {
    return pactError(503, PACT_UNAVAILABLE);
  }
}

/**
 * Forward one export (the derived pact, the Postman collection) and keep a refusal's detail.
 *
 * @param path - REST's path below the tenant, with its checked query.
 * @param method - `GET` or `POST`.
 * @param body - The checked body of a `POST`.
 * @returns REST's answer, or its refusal with `code`, `findings` and `notices`.
 */
export async function forwardExport(path: string, method: 'GET' | 'POST', body?: unknown): Promise<Response> {
  return withCaller(async (call) => {
    const answer = await call(path, { method, body });
    if (answer.ok) return NextResponse.json(answer.body);
    return NextResponse.json(refusalBody(answer.body, answer.status), { status: answer.status >= 400 ? answer.status : 502 });
  });
}

/**
 * One stored pact, exactly as published (the broker's `_links` and `createdAt` taken off).
 *
 * @param picked - The checked pair and choice.
 * @returns `{ pact, fileName }`, or REST's refusal (a 404 when the pair has no such pact).
 */
export async function forwardPactFile(picked: { provider: string; consumer: string; choice: PactChoice; value: string }): Promise<Response> {
  return withCaller(async (call) => {
    const answer = await call(pactFilePath(picked.provider, picked.consumer, picked.choice, picked.value));
    if (!answer.ok || !isObject(answer.body)) {
      return NextResponse.json(refusalBody(answer.body, answer.status), { status: answer.status >= 400 ? answer.status : 502 });
    }
    return NextResponse.json({ pact: storedPact(answer.body), fileName: `${fileStem(picked.consumer, picked.provider)}.json` });
  });
}

/** One consumer the zip could not carry, and why. */
export interface LeftOutPact {
  consumer: string;
  reason: string;
}

/**
 * The consumers with a pact for the provider, from the broker's provider-pacts list.
 *
 * @param body - `GET …/pacts/provider/{p}/latest[/{tag}]`'s body.
 * @returns The consumer names in the list's order (sorted by REST).
 */
export function providerPactConsumers(body: unknown): string[] {
  const links = isObject(body) && isObject(body._links) ? body._links['pb:pacts'] : undefined;
  if (!Array.isArray(links)) return [];
  return links.flatMap((link) => (isObject(link) && typeof link.name === 'string' && link.name ? [link.name] : []));
}

/**
 * The zip's README: which pacts it holds and, for each consumer it does not, why.
 *
 * @param provider - The provider.
 * @param selection - E.g. `latest`, `latest on branch main`.
 * @param included - The files written.
 * @param leftOut - Each consumer left out and why.
 * @returns The text.
 */
export function zipReadme(provider: string, selection: string, included: string[], leftOut: LeftOutPact[]): string {
  const lines = [`Pacts for ${provider} (${selection}), exported by Apiome exactly as published.`, '', `Included (${included.length}):`];
  for (const name of included) lines.push(`  ${name}`);
  lines.push('', `Left out (${leftOut.length}):`);
  if (leftOut.length === 0) lines.push('  none');
  for (const item of leftOut) lines.push(`  ${item.consumer}: ${item.reason}`);
  return `${lines.join('\n')}\n`;
}

/** How many pacts are read at the same time. */
const ZIP_READ_BATCH = 4;

/**
 * Every pact for a provider as a zip: one `<consumer>-<provider>.json` per consumer (its latest
 * pact, or its latest with the tag / on the branch) and a `README.txt` naming every consumer left
 * out and why. At most {@link MAX_ZIP_PACTS} pacts; the rest are listed in the README.
 *
 * @param picked - The checked provider and choice (`latest`, `branch` or `tag`).
 * @returns The archive (`application/zip`, as an attachment), or REST's refusal; a 404 when no
 *   consumer has such a pact.
 */
export async function forwardProviderPacts(picked: { provider: string; choice: PactChoice; value: string }): Promise<Response> {
  return withCaller(async (call) => {
    const base = `pact-broker/pacts/provider/${encodeURIComponent(picked.provider)}/latest`;
    const list = await call(picked.choice === 'tag' ? `${base}/${encodeURIComponent(picked.value)}` : base);
    if (!list.ok) {
      return NextResponse.json(refusalBody(list.body, list.status), { status: list.status >= 400 ? list.status : 502 });
    }
    const consumers = providerPactConsumers(list.body);
    const leftOut: LeftOutPact[] = consumers
      .slice(MAX_ZIP_PACTS)
      .map((consumer) => ({ consumer, reason: `over the limit of ${MAX_ZIP_PACTS} pacts in one zip; download it on its own` }));
    const encoder = new TextEncoder();
    const entries: ZipEntry[] = [];
    const wanted = consumers.slice(0, MAX_ZIP_PACTS);
    for (let start = 0; start < wanted.length; start += ZIP_READ_BATCH) {
      const batch = wanted.slice(start, start + ZIP_READ_BATCH);
      const answers = await Promise.all(batch.map((consumer) => call(pactFilePath(picked.provider, consumer, picked.choice, picked.value))));
      answers.forEach((answer, index) => {
        const consumer = batch[index];
        if (answer.ok && isObject(answer.body)) {
          const name = `${fileStem(consumer, picked.provider)}.json`;
          const unique = entries.some((entry) => entry.name === name) ? `${fileStem(consumer, picked.provider)}-${start + index}.json` : name;
          entries.push({ name: unique, data: encoder.encode(`${JSON.stringify(storedPact(answer.body), null, 2)}\n`) });
        } else {
          leftOut.push({ consumer, reason: String(refusalBody(answer.body, answer.status).error) });
        }
      });
    }
    const selection = picked.choice === 'branch' ? `latest on branch ${picked.value}` : picked.choice === 'tag' ? `latest with tag ${picked.value}` : 'latest';
    if (entries.length === 0) {
      const why = leftOut.length ? ` ${leftOut.map((item) => `${item.consumer}: ${item.reason}`).join('; ')}` : '';
      return pactError(404, `No consumer has published a pact (${selection}) for ${picked.provider}.${why}`);
    }
    entries.push({ name: 'README.txt', data: encoder.encode(zipReadme(picked.provider, selection, entries.map((e) => e.name), leftOut)) });
    const archive = createZip(entries);
    return new Response(archive.buffer as ArrayBuffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="${fileStem(picked.provider)}-pacts.zip"`,
        'Cache-Control': 'no-store',
      },
    });
  });
}
