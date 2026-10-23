'use client';

import * as React from 'react';

import { describeLicenseError, LICENSE_SEATS_EXHAUSTED_CODE } from '@/app/ade/dashboard/tenants/licenseErrors';
import { formatSeatUsage } from '@/app/ade/dashboard/tenants/licenseSeats';
import type { TenantLicensePlan, TenantLicenseSeats } from '@/app/ade/dashboard/tenants/licenseApi';
import { Alert } from '@/app/components/ui/Alert';
import { FactsLine } from '@/app/components/ui/FactsLine';
import { Progress } from '@/app/components/ui/metrics';

import {
  inviteBlockedBySeats,
  memberFacts,
  memberSeatProgress,
  type MemberSummary,
} from './membersModel';

/**
 * The Members summary — HIVE-11.9 (#5605).
 *
 * Authority: `docs/mockups/PROPOSALS.md` (finding 1, "Members: seat meter → facts line") and
 * HIVE-11.5's `FactsLine`. One line — members · active · pending · suspended · seats used —
 * replaces the seat-meter card, so the first member row moves up. Two things the card did are
 * kept, each only when it has something to say:
 *
 * - a thin seat bar once usage reaches the 80 % warn line (tone from the shared quota bands);
 * - the at-capacity warning, with the `license-seats-exhausted` sentence the REST refusal uses,
 *   because with every seat taken the **Invite member** button is not offered at all.
 */

/** Props for {@link MemberFactsLine}. */
export interface MemberFactsLineProps {
  /** Counts from `summariseMembers`. */
  summary: MemberSummary;
  /** Seat usage, or `null` when the licence could not be read (no seat fact, bar or warning). */
  seats: TenantLicenseSeats | null;
  /** The tenant's plan, shown as a muted aside. */
  plan?: TenantLicensePlan | null;
  /** The roster is still loading: draw the skeleton line. */
  loading?: boolean;
}

/**
 * The facts line, its seat bar and the at-capacity warning.
 *
 * @param props See {@link MemberFactsLineProps}.
 * @returns The summary block.
 */
export default function MemberFactsLine({ summary, seats, plan, loading = false }: MemberFactsLineProps) {
  const progress = memberSeatProgress(seats);
  return (
    <div className="mbr-facts" data-testid="member-facts">
      <FactsLine
        page="members"
        aria-label="Members summary"
        facts={memberFacts(summary, seats, plan)}
        loading={loading}
      />
      {progress && seats && (
        <Progress
          thin
          className="mbr-facts__seats"
          value={progress.percent}
          tone={progress.tone}
          label={`Member seats: ${formatSeatUsage(seats)}`}
          data-testid="member-seat-progress"
        />
      )}
      {inviteBlockedBySeats(seats) && (
        <Alert variant="warn" data-testid="member-seats-exhausted">
          <strong className="block font-semibold">All member seats are in use</strong>
          {describeLicenseError({ code: LICENSE_SEATS_EXHAUSTED_CODE })}
        </Alert>
      )}
    </div>
  );
}
