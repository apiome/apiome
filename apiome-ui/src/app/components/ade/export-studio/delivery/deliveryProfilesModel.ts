/**
 * Export delivery profiles — the pure half (MFX-38.4, #4331).
 *
 * A delivery profile is a workspace's saved destination for finished exports: a **channel** (`git`,
 * `webhook` or `object_storage`), that channel's delivery body, and a reference to the credential it
 * delivers with (the git repository's linked account, a storage credential from the vault, or a
 * webhook signing secret sealed on the profile). These types mirror the REST models' camelCase
 * serialization; the form logic below turns a draft into the bodies `POST` / `PATCH` take and back.
 *
 * Nothing here reads a secret back: the REST layer never returns one. A webhook draft's `secret` is
 * only what the person typed, and an edit that leaves it blank keeps the stored secret.
 */

/** A delivery channel, as the API names it. */
export type DeliveryChannel = 'git' | 'webhook' | 'object_storage';

/** The channels, in the order the form offers them. */
export const DELIVERY_CHANNELS: readonly DeliveryChannel[] = ['git', 'webhook', 'object_storage'];

/** Each channel's label, in sentence case. */
export const CHANNEL_LABELS: Readonly<Record<DeliveryChannel, string>> = {
  git: 'Git repository',
  webhook: 'Webhook',
  object_storage: 'Object storage',
};

/** The object-storage partitions, in their default order. */
export const PARTITIONS = ['artifact', 'version', 'target'] as const;

/** One object-storage partition. */
export type Partition = (typeof PARTITIONS)[number];

/** A webhook secret's length bounds (the REST layer's rule). */
export const SECRET_MIN_CHARS = 16;
export const SECRET_MAX_CHARS = 512;
/** A profile name's longest form. */
export const NAME_MAX_CHARS = 120;

/** What a profile delivers with, by reference. */
export interface CredentialRef {
  kind: 'repository' | 'storage_credential' | 'webhook_secret';
  id: string | null;
}

/** A stored profile, as `GET /api/export/delivery-profiles` returns it. */
export interface DeliveryProfile {
  id: string;
  name: string;
  description: string | null;
  channel: DeliveryChannel;
  /** The channel's delivery body, minus any secret (a webhook URL without its query string). */
  destination: Record<string, unknown>;
  credentialRef: CredentialRef;
  createdAt?: string | null;
  updatedAt?: string | null;
}

/** One delivery attempt, whatever its channel. */
export interface DeliveryAttempt {
  channel: DeliveryChannel;
  runId: string | null;
  jobId: string;
  status: string;
  outcome: 'in_progress' | 'delivered' | 'failed';
  profileId: string | null;
  profileName: string | null;
  destination: string | null;
  attemptCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  startedAt: string | null;
  finishedAt?: string | null;
  /** What the delivery left at its destination (MFX-46.3); absent until it produced something. */
  result?: DeliveryResult | null;
}

/**
 * What a delivery left at its destination (mirror of REST `ExportDeliveryResult`, MFX-46.3). Only its
 * own channel's fields are set; nothing in it is secret (URLs arrive without user-info or query).
 */
export interface DeliveryResult {
  /** git: `pr` or `commit`. */
  mode?: string | null;
  pullRequestUrl?: string | null;
  pullRequestNumber?: number | null;
  branch?: string | null;
  commitSha?: string | null;
  /** webhook: the receiver's last HTTP status. */
  httpStatus?: number | null;
  /** webhook: the digest of the body sent. */
  payloadSha256?: string | null;
  /** object storage: the objects written (capped; `objectCount` counts them all). */
  objectUrls?: string[];
  objectCount?: number | null;
  manifestUrl?: string | null;
}

/** One line of a delivery's result: what to call it, and where it lives when that is a web page. */
export interface ResultLine {
  label: string;
  /** The text to show (a URL, a commit, a status). */
  value: string;
  /** A web link to open, only for an `http(s)` URL (an `s3://` URL is shown, not linked). */
  href: string | null;
}

/** Whether `url` can be opened in a browser. */
function webLink(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

/**
 * A delivery's result as lines to show (MFX-46.3): the pull request (or commit) a git delivery made, the
 * receipt a webhook got, the objects and manifest an object-storage delivery wrote.
 *
 * @param channel The delivery's channel.
 * @param result Its result, or nothing yet.
 * @returns The lines, in reading order; empty when there is nothing to show.
 */
export function resultLines(channel: DeliveryChannel, result: DeliveryResult | null | undefined): ResultLine[] {
  if (!result) return [];
  const lines: ResultLine[] = [];
  if (channel === 'git') {
    if (result.pullRequestUrl) {
      lines.push({
        label: result.pullRequestNumber ? `Pull request #${result.pullRequestNumber}` : 'Pull request',
        value: result.pullRequestUrl,
        href: webLink(result.pullRequestUrl),
      });
    }
    if (result.commitSha) {
      const where = result.branch ? ` on ${result.branch}` : '';
      lines.push({ label: 'Commit', value: `${result.commitSha.slice(0, 12)}${where}`, href: null });
    }
  } else if (channel === 'webhook') {
    if (result.httpStatus != null) {
      lines.push({ label: 'Receiver answered', value: `HTTP ${result.httpStatus}`, href: null });
    }
    if (result.payloadSha256) {
      lines.push({ label: 'Body sent', value: `sha256:${result.payloadSha256.slice(0, 16)}…`, href: null });
    }
  } else if (channel === 'object_storage') {
    const urls = result.objectUrls ?? [];
    urls.forEach((url) => lines.push({ label: 'Object', value: url, href: webLink(url) }));
    const more = (result.objectCount ?? urls.length) - urls.length;
    if (more > 0) lines.push({ label: 'Object', value: `and ${more} more`, href: null });
    if (result.manifestUrl) {
      lines.push({ label: 'Manifest', value: result.manifestUrl, href: webLink(result.manifestUrl) });
    }
  }
  return lines;
}

/** The form's state for one profile. Every channel's fields are kept, so switching back loses nothing. */
export interface DeliveryProfileDraft {
  name: string;
  description: string;
  channel: DeliveryChannel;
  git: { repositoryId: string; targetPath: string; baseBranch: string; mode: 'pr' | 'commit' };
  webhook: { url: string; secret: string; artifact: 'auto' | 'fetch' };
  objectStorage: { credentialId: string; bucket: string; prefix: string; partitioning: Partition[] };
}

/**
 * A blank draft.
 *
 * @param channel The channel to start on.
 * @returns A draft with each channel's defaults.
 */
export function emptyDraft(channel: DeliveryChannel = 'git'): DeliveryProfileDraft {
  return {
    name: '',
    description: '',
    channel,
    git: { repositoryId: '', targetPath: '', baseBranch: '', mode: 'pr' },
    webhook: { url: '', secret: '', artifact: 'auto' },
    objectStorage: { credentialId: '', bucket: '', prefix: '', partitioning: [...PARTITIONS] },
  };
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * A draft for editing a stored profile (its secret is never known, so it starts blank).
 *
 * @param profile The stored profile.
 * @returns The draft.
 */
export function draftFromProfile(profile: DeliveryProfile): DeliveryProfileDraft {
  const draft = emptyDraft(profile.channel);
  const d = profile.destination ?? {};
  draft.name = profile.name;
  draft.description = profile.description ?? '';
  if (profile.channel === 'git') {
    draft.git = {
      repositoryId: text(d.repositoryId),
      targetPath: text(d.targetPath),
      baseBranch: text(d.baseBranch),
      mode: d.mode === 'commit' ? 'commit' : 'pr',
    };
  } else if (profile.channel === 'webhook') {
    // The stored URL is shown without its query string, which may hold a token: an edit must
    // re-enter the whole URL to change it, so the form starts empty rather than with a broken one.
    const url = text(d.url);
    draft.webhook = { url: url.endsWith('?…') ? '' : url, secret: '', artifact: d.artifact === 'fetch' ? 'fetch' : 'auto' };
  } else {
    const parts = Array.isArray(d.partitioning) ? d.partitioning : [];
    draft.objectStorage = {
      credentialId: text(d.credentialId),
      bucket: text(d.bucket),
      prefix: text(d.prefix),
      partitioning: parts.filter((p): p is Partition => (PARTITIONS as readonly string[]).includes(String(p))),
    };
  }
  return draft;
}

/** The API block name for each channel. */
const BLOCKS: Readonly<Record<DeliveryChannel, 'git' | 'webhook' | 'objectStorage'>> = {
  git: 'git',
  webhook: 'webhook',
  object_storage: 'objectStorage',
};

/**
 * The channel block a draft sends.
 *
 * @param draft The draft.
 * @returns `{ git | webhook | objectStorage: {...} }` — a webhook block carries `secret` only when typed.
 */
export function destinationBlock(draft: DeliveryProfileDraft): Record<string, Record<string, unknown>> {
  if (draft.channel === 'git') {
    const g = draft.git;
    return {
      git: {
        repositoryId: g.repositoryId.trim(),
        targetPath: g.targetPath.trim(),
        mode: g.mode,
        ...(g.baseBranch.trim() ? { baseBranch: g.baseBranch.trim() } : {}),
      },
    };
  }
  if (draft.channel === 'webhook') {
    const w = draft.webhook;
    return { webhook: { url: w.url.trim(), artifact: w.artifact, ...(w.secret ? { secret: w.secret } : {}) } };
  }
  const o = draft.objectStorage;
  return {
    objectStorage: {
      credentialId: o.credentialId,
      bucket: o.bucket.trim(),
      prefix: o.prefix.trim(),
      partitioning: [...o.partitioning],
    },
  };
}

/**
 * The `POST` body for a new profile.
 *
 * @param draft The draft.
 * @returns `{ name, description?, channel, <block> }`.
 */
export function createBody(draft: DeliveryProfileDraft): Record<string, unknown> {
  return {
    name: draft.name.trim(),
    ...(draft.description.trim() ? { description: draft.description.trim() } : {}),
    channel: draft.channel,
    ...destinationBlock(draft),
  };
}

/**
 * The `PATCH` body for an edit: the name and description always, the destination when it changed or
 * a new secret was typed (a destination is replaced whole).
 *
 * @param draft The edited draft.
 * @param original The draft the edit started from.
 * @returns The body.
 */
export function updateBody(draft: DeliveryProfileDraft, original: DeliveryProfileDraft): Record<string, unknown> {
  const changed =
    JSON.stringify(destinationBlock({ ...draft, webhook: { ...draft.webhook, secret: '' } })) !==
      JSON.stringify(destinationBlock({ ...original, webhook: { ...original.webhook, secret: '' } })) ||
    (draft.channel === 'webhook' && draft.webhook.secret !== '');
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    ...(changed ? destinationBlock(draft) : {}),
  };
}

/**
 * The problems that would stop a draft being saved — the REST layer's rules, checked first so the
 * form can mark them before a round trip. The server still checks everything.
 *
 * @param draft The draft.
 * @param creating Whether this is a new profile (a webhook then needs its secret).
 * @param original For an edit, the draft it started from: a webhook URL may stay blank (kept as
 *   stored) unless the destination changed, which sends it whole.
 * @returns One message per problem; empty when the draft can be sent.
 */
export function validateDraft(
  draft: DeliveryProfileDraft,
  creating: boolean,
  original?: DeliveryProfileDraft,
): string[] {
  const problems: string[] = [];
  const name = draft.name.trim();
  if (!name) problems.push('Name the profile.');
  else if (name.length > NAME_MAX_CHARS) problems.push(`The name is longer than ${NAME_MAX_CHARS} characters.`);
  if (draft.channel === 'git') {
    if (!draft.git.repositoryId) problems.push('Choose a repository.');
    if (draft.git.targetPath.split('/').includes('..')) problems.push('The path cannot contain "..".');
  } else if (draft.channel === 'webhook') {
    const url = draft.webhook.url.trim();
    const keepsStoredUrl = !creating && !url && !(original && needsWebhookUrl(draft, original));
    if (!keepsStoredUrl && !/^https?:\/\/[^\s/]+/i.test(url)) {
      problems.push(creating || url ? 'Enter the receiver URL (https://…).' : 'Re-enter the receiver URL to change the destination.');
    }
    const secret = draft.webhook.secret;
    if (creating && !secret) problems.push('Enter the signing secret.');
    if (secret && (secret.length < SECRET_MIN_CHARS || secret.length > SECRET_MAX_CHARS)) {
      problems.push(`The secret must be ${SECRET_MIN_CHARS}–${SECRET_MAX_CHARS} characters.`);
    }
  } else {
    if (!draft.objectStorage.credentialId) problems.push('Choose a storage credential.');
    if (!/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(draft.objectStorage.bucket.trim())) {
      problems.push('The bucket must be 3–63 lowercase letters, digits, "." and "-".');
    }
    if (draft.objectStorage.prefix.split('/').includes('..')) problems.push('The prefix cannot contain "..".');
  }
  return problems;
}

/**
 * Whether the webhook draft of an edit must re-enter its URL: any webhook change is sent whole.
 *
 * @param draft The edited draft.
 * @param original The draft the edit started from.
 * @returns True when the destination changed but the URL is blank.
 */
export function needsWebhookUrl(draft: DeliveryProfileDraft, original: DeliveryProfileDraft): boolean {
  if (draft.channel !== 'webhook') return false;
  return 'webhook' in updateBody(draft, original) && !draft.webhook.url.trim();
}

/**
 * One line for a profile's destination.
 *
 * @param profile The profile.
 * @param names Repository and storage-credential names by id, when known.
 * @returns e.g. `acme/specs → specs/orders (pull request)`, `https://ci.example.com/hook`, `data-lake/exports`.
 */
export function destinationSummary(profile: DeliveryProfile, names: Readonly<Record<string, string>> = {}): string {
  const d = profile.destination ?? {};
  if (profile.channel === 'git') {
    const repo = names[text(d.repositoryId)] ?? text(d.repositoryId);
    const path = text(d.targetPath) || '/';
    return `${repo} → ${path} (${d.mode === 'commit' ? 'direct commit' : 'pull request'})`;
  }
  if (profile.channel === 'webhook') return text(d.url);
  const prefix = text(d.prefix);
  return prefix ? `${text(d.bucket)}/${prefix}` : text(d.bucket);
}

/**
 * The tone a delivery outcome is drawn in.
 *
 * @param outcome The attempt's outcome.
 * @returns `ok`, `danger` or `neutral`.
 */
export function outcomeTone(outcome: DeliveryAttempt['outcome']): 'ok' | 'danger' | 'neutral' {
  if (outcome === 'delivered') return 'ok';
  if (outcome === 'failed') return 'danger';
  return 'neutral';
}

/** Each outcome's label. */
export const OUTCOME_LABELS: Readonly<Record<DeliveryAttempt['outcome'], string>> = {
  in_progress: 'In progress',
  delivered: 'Delivered',
  failed: 'Failed',
};

/**
 * How many on-completion deliveries a job's events have reported so far.
 *
 * @param events The job's events.
 * @returns The `EXPORT_DELIVERED` / `EXPORT_DELIVERY_FAILED` count.
 */
export function deliveryEventCount(events: ReadonlyArray<{ code: string }> | null | undefined): number {
  return (events ?? []).filter((e) => e.code === 'EXPORT_DELIVERED' || e.code === 'EXPORT_DELIVERY_FAILED').length;
}

/** The block name a channel's body travels under (exported for the form's field ids). */
export function blockName(channel: DeliveryChannel): 'git' | 'webhook' | 'objectStorage' {
  return BLOCKS[channel];
}
