'use client';

/**
 * The version page's **Feedback** tab — COL-4.4 (#4528).
 *
 * Signed out, it explains feedback and links to reader sign-in (signed-out users cannot file
 * feedback). Signed in to this portal, it shows the **Send feedback** form — the whole API or one
 * operation, and a message — and the reader's own threads with the team's replies, a reply box, and
 * **Resolve** / **Reopen**. Every call goes through Browse's `/api/portal/feedback/…` routes, which
 * add the reader session the browser cannot read.
 */

import Link from 'next/link';
import { useEffect, useMemo, useState, type FormEvent } from 'react';

import {
  createBody,
  feedbackBffUrl,
  feedbackErrorCopy,
  specOperations,
  targetValue,
  threadSubject,
  WHOLE_API,
  type FeedbackAction,
  type FeedbackThread,
  type FeedbackThreadList,
} from '../../../../../../lib/portal/feedback';
import { portalPath } from '../../../../../../lib/portal/session';

interface FeedbackPanelProps {
  /** The portal. */
  tenantSlug: string;
  /** The project. */
  projectSlug: string;
  /** The version label. */
  versionSlug: string;
  /** The organization's display name. */
  tenantName: string;
  /** The signed-in reader's address, or null when nobody is signed in to this portal. */
  readerEmail: string | null;
  /** The parsed spec, for the operation picker (null while it loads). */
  spec: unknown;
}

/** The base path Next does not add to a `fetch`. */
const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

/**
 * Read `detail.code` from an error response.
 *
 * @param response - A non-OK response.
 * @returns The code, or null.
 */
async function errorCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: { code?: unknown } };
    return typeof body.detail?.code === 'string' ? body.detail.code : null;
  } catch {
    return null;
  }
}

/**
 * Format a timestamp for a message.
 *
 * @param iso - The ISO timestamp.
 * @returns A short local date and time.
 */
function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function FeedbackPanel({ tenantSlug, projectSlug, versionSlug, tenantName, readerEmail, spec }: FeedbackPanelProps) {
  const [threads, setThreads] = useState<FeedbackThread[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState(WHOLE_API);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const operations = useMemo(() => specOperations(spec), [spec]);
  const returnTo = `/tenant/${tenantSlug}/${projectSlug}/${versionSlug}?tab=feedback`;

  const listUrl = feedbackBffUrl(BASE_PATH, tenantSlug, projectSlug, versionSlug);

  useEffect(() => {
    if (!readerEmail) return;
    let cancelled = false;
    fetch(listUrl, { cache: 'no-store' })
      .then(async (response) => {
        if (cancelled) return;
        if (!response.ok) {
          const code = await errorCode(response);
          if (cancelled) return;
          setError(feedbackErrorCopy(response.status, code));
          setThreads([]);
          return;
        }
        const list = (await response.json()) as FeedbackThreadList;
        if (!cancelled) setThreads(list.threads);
      })
      .catch(() => {
        if (cancelled) return;
        setError(feedbackErrorCopy(0, null));
        setThreads([]);
      });
    return () => {
      cancelled = true;
    };
  }, [readerEmail, listUrl]);

  /** Replace one thread in the list with the version the server returned. */
  const upsert = (thread: FeedbackThread) =>
    setThreads((current) => [thread, ...(current ?? []).filter((item) => item.id !== thread.id)]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setError(null);
    const response = await fetch(listUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(createBody(target, message)),
    });
    setSending(false);
    if (!response.ok) {
      setError(feedbackErrorCopy(response.status, await errorCode(response)));
      return;
    }
    upsert((await response.json()) as FeedbackThread);
    setMessage('');
    setTarget(WHOLE_API);
  }

  async function act(threadId: string, action: FeedbackAction, body?: string): Promise<boolean> {
    setError(null);
    const response = await fetch(feedbackBffUrl(BASE_PATH, tenantSlug, projectSlug, versionSlug, threadId, action), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body !== undefined ? { body } : {}),
    });
    if (!response.ok) {
      setError(feedbackErrorCopy(response.status, await errorCode(response)));
      return false;
    }
    upsert((await response.json()) as FeedbackThread);
    return true;
  }

  if (!readerEmail) {
    return (
      <section className="feedback-panel" data-testid="feedback-signed-out">
        <h2 className="feedback-title">Tell the {tenantName} team what you think</h2>
        <p className="feedback-body">
          Found a response that does not match, or a description that is unclear? Sign in and send feedback on this
          version or on one of its operations. The team replies here.
        </p>
        <Link
          className="portal-button feedback-sign-in"
          href={portalPath('/portal/sign-in', { tenant: tenantSlug, return_to: returnTo })}
          data-testid="feedback-sign-in"
        >
          Sign in to send feedback
        </Link>
      </section>
    );
  }

  return (
    <section className="feedback-panel" data-testid="feedback-panel">
      <form className="feedback-form" onSubmit={send} data-testid="feedback-form">
        <h2 className="feedback-title">Send feedback</h2>
        <label className="portal-label" htmlFor="feedback-target">
          About
        </label>
        <select
          id="feedback-target"
          className="portal-input"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
        >
          <option value={WHOLE_API}>Whole API</option>
          {operations.map((operation) => (
            <option key={targetValue(operation)} value={targetValue(operation)}>
              {operation.method} {operation.path}
            </option>
          ))}
        </select>
        <label className="portal-label" htmlFor="feedback-message">
          Message
        </label>
        <textarea
          id="feedback-message"
          className="portal-input feedback-textarea"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          maxLength={20000}
          rows={4}
          placeholder="For example: the 404 response has no schema."
        />
        <div className="feedback-actions">
          <span className="feedback-hint">Signed in as {readerEmail}. Only you and the team see your feedback.</span>
          <button className="portal-button" type="submit" disabled={sending || !message.trim()}>
            {sending ? 'Sending…' : 'Send feedback'}
          </button>
        </div>
      </form>

      {error ? (
        <p className="portal-notice portal-notice-danger" role="alert">
          {error}
        </p>
      ) : null}

      <h2 className="feedback-title">Your feedback</h2>
      {threads === null ? (
        <p className="feedback-body">Loading…</p>
      ) : threads.length === 0 ? (
        <p className="feedback-body" data-testid="feedback-empty">
          You have not sent feedback on this version yet.
        </p>
      ) : (
        <ul className="feedback-threads">
          {threads.map((thread) => (
            <FeedbackThreadItem key={thread.id} thread={thread} onAction={act} />
          ))}
        </ul>
      )}
    </section>
  );
}

interface FeedbackThreadItemProps {
  thread: FeedbackThread;
  onAction: (threadId: string, action: FeedbackAction, body?: string) => Promise<boolean>;
}

/** One thread: subject, status, messages, a reply box, and Resolve / Reopen. */
function FeedbackThreadItem({ thread, onAction }: FeedbackThreadItemProps) {
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);
  const resolved = thread.status === 'resolved';

  async function run(action: FeedbackAction, body?: string) {
    setBusy(true);
    const ok = await onAction(thread.id, action, body);
    setBusy(false);
    if (ok && action === 'comments') setReply('');
  }

  return (
    <li className="feedback-thread" data-testid="feedback-thread" data-status={thread.status}>
      <div className="feedback-thread-head">
        <span className="feedback-subject">{threadSubject(thread)}</span>
        <span className={resolved ? 'feedback-status feedback-status-resolved' : 'feedback-status'}>
          {resolved ? 'Resolved' : 'Open'}
        </span>
      </div>
      <ol className="feedback-messages">
        {thread.comments.map((comment) => (
          <li key={comment.id} className={comment.from_team ? 'feedback-message feedback-message-team' : 'feedback-message'}>
            <div className="feedback-message-meta">
              <span>{comment.from_team ? comment.author_name ?? 'Team' : 'You'}</span>
              {comment.from_team ? <span className="feedback-team-badge">Team</span> : null}
              <time dateTime={comment.created_at}>{when(comment.created_at)}</time>
            </div>
            <p className="feedback-message-body">{comment.body}</p>
          </li>
        ))}
      </ol>
      <form
        className="feedback-reply"
        onSubmit={(event) => {
          event.preventDefault();
          void run('comments', reply);
        }}
      >
        <label className="sr-only" htmlFor={`feedback-reply-${thread.id}`}>
          Reply
        </label>
        <input
          id={`feedback-reply-${thread.id}`}
          className="portal-input"
          value={reply}
          onChange={(event) => setReply(event.target.value)}
          placeholder="Reply"
          maxLength={20000}
        />
        <button className="portal-button" type="submit" disabled={busy || !reply.trim()}>
          Reply
        </button>
        <button
          className="feedback-secondary"
          type="button"
          disabled={busy}
          onClick={() => void run(resolved ? 'reopen' : 'resolve')}
        >
          {resolved ? 'Reopen' : 'Resolve'}
        </button>
      </form>
    </li>
  );
}
