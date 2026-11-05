'use client';

import { Badge } from '@/app/components/ui/Badge';

import {
  CHANNEL_LABELS,
  OUTCOME_LABELS,
  outcomeTone,
  type DeliveryAttempt,
} from './deliveryProfilesModel';

/** Props for {@link DeliveryAttemptList}. */
export interface DeliveryAttemptListProps {
  /** The attempts, newest first. */
  attempts: DeliveryAttempt[];
  /** Shown when there are none. */
  emptyMessage: string;
  /** Show the profile column (off on a profile's own trail). */
  showProfile?: boolean;
  /** The list's accessible name. */
  label: string;
}

/**
 * Delivery attempts as a list — one row per attempt, whatever its channel (MFX-38.4, #4331).
 *
 * Shared by a profile's trail on the **Delivery** tab and a job's deliveries on Review. Each row
 * names the channel, the outcome, where it went, how many attempts it took and, on a failure, the
 * channel's error code and message.
 *
 * @param props See {@link DeliveryAttemptListProps}.
 * @returns The list.
 */
export function DeliveryAttemptList({ attempts, emptyMessage, showProfile = true, label }: DeliveryAttemptListProps) {
  if (attempts.length === 0) {
    return <p className="xdlv-quiet">{emptyMessage}</p>;
  }
  return (
    <ul className="xdlv-attempts" aria-label={label}>
      {attempts.map((attempt, index) => (
        <li
          key={attempt.runId ?? `${attempt.channel}-${index}`}
          className="xdlv-attempt"
          data-outcome={attempt.outcome}
          data-testid="delivery-attempt"
        >
          <div className="xdlv-attempt__head">
            <Badge variant={outcomeTone(attempt.outcome)}>{OUTCOME_LABELS[attempt.outcome]}</Badge>
            <span className="xdlv-attempt__channel">{CHANNEL_LABELS[attempt.channel] ?? attempt.channel}</span>
            {showProfile && attempt.profileName ? (
              <span className="xdlv-attempt__profile">{attempt.profileName}</span>
            ) : null}
            <span className="xdlv-attempt__status mono">{attempt.status}</span>
          </div>
          <div className="xdlv-attempt__meta">
            {attempt.destination ? <span className="mono">{attempt.destination}</span> : null}
            {attempt.attemptCount > 1 ? <span>{attempt.attemptCount} attempts</span> : null}
            {attempt.startedAt ? <time dateTime={attempt.startedAt}>{new Date(attempt.startedAt).toLocaleString()}</time> : null}
          </div>
          {attempt.errorCode ? (
            <p className="xdlv-attempt__error">
              <code className="mono">{attempt.errorCode}</code>
              {attempt.errorMessage ? ` — ${attempt.errorMessage}` : null}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
