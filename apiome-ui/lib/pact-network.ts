/**
 * A pacticipant's integration network — PFX-5.3 (#6947).
 *
 * The data behind the **Network** page (`/ade/dashboard/pacts/pacticipants/{handle}/network`): the
 * group of pacticipants connected to one pacticipant through pacts, and the newest pact of each
 * integration with its verification verdict. It answers what the Pact Broker's
 * `/groups/{pacticipant}` resource answers for its network diagram.
 *
 * Apiome's broker does not serve that resource, so the `/api/pact/*` proxy collects the group
 * ({@link collectPactNetwork}): it reads the matrix of the pacticipant, then of each pacticipant
 * found, {@link ENVIRONMENT_READ_BATCH} at a time, until the group is complete or
 * {@link NETWORK_READ_LIMIT} pacticipants were read. Nothing found is dropped: a pacticipant whose
 * matrix was not read (the limit) or could not be read (a refusal) stays in the network, marked
 * with the reason, with every integration already known to reach it.
 */

import {
  ENVIRONMENT_READ_BATCH,
  RollupError,
  isPacticipantHandle,
  pacticipantRoute,
  type RestRead,
  type RestReader,
} from '@lib/pact-pacticipants';
import {
  PACTICIPANT_PACTS_ROW_LIMIT,
  pacticipantPactsProxyPath,
  parsePacticipantPacts,
  verificationVerdict,
  type PacticipantPact,
  type VerificationVerdict,
} from '@lib/pact-detail';

/** How many pacticipants' matrices the roll-up reads, at most, the starting one included. */
export const NETWORK_READ_LIMIT = 25;

/** Why a pacticipant's own integrations are not all known. */
export type NetworkGap =
  /** Its matrix was not read: the network reached {@link NETWORK_READ_LIMIT} first. */
  | 'not-read'
  /** Its matrix could not be read (the reason is in `error`). */
  | 'failed'
  /** Its matrix filled {@link PACTICIPANT_PACTS_ROW_LIMIT} rows, so some integrations may be missing. */
  | 'truncated';

/** One pacticipant of the network. */
export interface NetworkPacticipant {
  slug: string;
  name: string;
  /** Hops from the pacticipant the network is drawn around (0 for it). */
  distance: number;
  /** Why some of its integrations may be missing; absent when all are known. */
  gap?: NetworkGap;
  /** REST's message when `gap` is `failed`. */
  error?: string;
}

/** One integration of the network: its newest pact and that pact's verdict. */
export interface NetworkIntegration extends PacticipantPact {
  verdict: VerificationVerdict;
}

/** What `GET /api/pact/pacticipants/{handle}/network` answers. */
export interface PactNetwork {
  /** The handle the network is drawn around. */
  centre: string;
  /** Nearest first, then by name. */
  pacticipants: NetworkPacticipant[];
  /** By consumer name, then provider name. */
  integrations: NetworkIntegration[];
}

/** The route of a pacticipant's network page. */
export function networkRoute(slug: string): string {
  return `${pacticipantRoute(slug)}/network`;
}

/** REST's message from a failed read, or the fallback. */
function failureMessage(read: RestRead, fallback: string): string {
  const body =
    read.body && typeof read.body === 'object' ? (read.body as Record<string, unknown>) : {};
  const detail = body.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === 'string' && message) return message;
  }
  return fallback;
}

/**
 * Collect the network of pacticipants connected to one, breadth first.
 *
 * @param read - Reads a path below `/v1/tenants/{slug}` as the signed-in user.
 * @param slug - The pacticipant to start from (an already checked handle).
 * @param readLimit - How many matrices to read at most (tests lower it).
 * @returns The network.
 * @throws RollupError when the starting pacticipant's own matrix is refused (REST's status kept).
 */
export async function collectPactNetwork(
  read: RestReader,
  slug: string,
  readLimit = NETWORK_READ_LIMIT,
): Promise<PactNetwork> {
  const pacticipants = new Map<string, NetworkPacticipant>([
    [slug, { slug, name: slug, distance: 0, gap: 'not-read' }],
  ]);
  const integrations = new Map<string, NetworkIntegration>();
  let frontier = [slug];
  let reads = 0;

  /** Note one end of an integration, keeping the nearest distance and the name the matrix gave. */
  const meet = (end: { slug: string; name: string }, distance: number, next: string[]) => {
    const known = pacticipants.get(end.slug);
    if (known) {
      if (end.name && known.name === known.slug) known.name = end.name;
      return;
    }
    pacticipants.set(end.slug, {
      slug: end.slug,
      name: end.name || end.slug,
      distance,
      gap: 'not-read',
    });
    next.push(end.slug);
  };

  while (frontier.length > 0 && reads < readLimit) {
    const next: string[] = [];
    const batchable = frontier.slice(0, readLimit - reads);
    for (let start = 0; start < batchable.length; start += ENVIRONMENT_READ_BATCH) {
      const batch = batchable.slice(start, start + ENVIRONMENT_READ_BATCH);
      reads += batch.length;
      const answers = await Promise.all(
        batch.map((handle) => read(pacticipantPactsProxyPath(handle))),
      );
      batch.forEach((handle, index) => {
        const answer = answers[index];
        const node = pacticipants.get(handle)!;
        if (!answer.ok) {
          if (handle === slug) {
            throw new RollupError(
              answer.status,
              failureMessage(answer, 'The network could not be read.'),
            );
          }
          node.gap = 'failed';
          node.error = failureMessage(answer, `HTTP ${answer.status}`);
          return;
        }
        const parsed = parsePacticipantPacts(answer.body, PACTICIPANT_PACTS_ROW_LIMIT);
        delete node.gap;
        if (parsed.truncated) node.gap = 'truncated';
        for (const pact of parsed.pacts) {
          if (!isPacticipantHandle(pact.consumer.slug) || !isPacticipantHandle(pact.provider.slug))
            continue;
          if (pact.consumer.slug === handle) node.name = pact.consumer.name || node.name;
          if (pact.provider.slug === handle) node.name = pact.provider.name || node.name;
          meet(pact.consumer, node.distance + 1, next);
          meet(pact.provider, node.distance + 1, next);
          const key = `${pact.consumer.slug}|${pact.provider.slug}`;
          if (!integrations.has(key)) {
            integrations.set(key, {
              ...pact,
              verdict: verificationVerdict(pact.latestVerification),
            });
          }
        }
      });
    }
    // The next hop is read in handle order, so the limit always leaves out the same ones. What it
    // leaves unread stays in the network, marked `not-read`.
    frontier = next.sort();
  }

  const byName = (a: { name: string; slug: string }, b: { name: string; slug: string }) =>
    a.name.localeCompare(b.name) || a.slug.localeCompare(b.slug);
  return {
    centre: slug,
    pacticipants: [...pacticipants.values()].sort(
      (a, b) => a.distance - b.distance || byName(a, b),
    ),
    integrations: [...integrations.values()].sort(
      (a, b) => byName(a.consumer, b.consumer) || byName(a.provider, b.provider),
    ),
  };
}

/** How each gap reads next to a pacticipant. */
export const GAP_TEXT: Record<NetworkGap, string> = {
  'not-read': 'not read: the network is larger than is read at once',
  failed: 'could not be read',
  truncated: 'has more pacts than are read at once',
};

/**
 * The notices above the diagram: one sentence per kind of gap, naming the pacticipants.
 *
 * @param network - The network.
 * @returns The sentences, empty when every integration is known.
 */
export function networkNotices(network: PactNetwork): string[] {
  const names = (gap: NetworkGap) =>
    network.pacticipants
      .filter((p) => p.gap === gap)
      .map((p) => (gap === 'failed' && p.error ? `${p.name} (${p.error})` : p.name));
  const notices: string[] = [];
  const notRead = names('not-read');
  if (notRead.length > 0) {
    notices.push(
      `Only ${NETWORK_READ_LIMIT} pacticipants are read at once. The pacts of ${notRead.join(', ')} were not read, so integrations further out are not shown. Open one of them to see its network.`,
    );
  }
  const failed = names('failed');
  if (failed.length > 0) {
    notices.push(
      `The pacts of ${failed.join(', ')} could not be read, so some of their integrations may be missing.`,
    );
  }
  const truncated = names('truncated');
  if (truncated.length > 0) {
    notices.push(
      `${truncated.join(', ')} ${truncated.length === 1 ? 'has' : 'have'} more pacts than are read at once; some integrations may be missing.`,
    );
  }
  return notices;
}

/**
 * How many integrations have each verdict.
 *
 * @param integrations - The network's integrations.
 * @returns A count for every verdict (zero included).
 */
export function verdictCounts(
  integrations: readonly NetworkIntegration[],
): Record<VerificationVerdict, number> {
  const counts: Record<VerificationVerdict, number> = {
    verified: 0,
    failed: 0,
    'failed-pending': 0,
    unverified: 0,
  };
  for (const integration of integrations) counts[integration.verdict] += 1;
  return counts;
}
