/**
 * Shared member-seat presentation helpers (OLO-5.5 / OLO-6.3).
 *
 * Both the tenant License panel (OLO-5.5, #4215) and the member-management
 * screen (OLO-6.3, #4220) render a tenant's member-seat usage against its
 * license limit and gate seat-consuming actions on the same
 * `license-seats-exhausted` condition apiome-rest enforces (OLO-5.3). Keeping
 * the pure logic here — rather than duplicating it per surface — guarantees the
 * two screens agree on when a tenant is "at capacity" and how the usage reads.
 *
 * Seat data arrives from the OLO-5.4 license surface as `{ used, max }` (see
 * {@link ./licenseApi}.TenantLicenseSeats). A negative `max` means the plan
 * grants unlimited seats (Sponsor tier); those tenants are never at capacity.
 */

import type { TenantLicenseSeats } from './licenseApi';

/** Seat-usage fraction (0–100) at which the meter switches to the warning tint. */
export const SEAT_WARNING_PERCENT = 80;

/**
 * Whether the license grants unlimited member seats.
 *
 * @param seats Seat usage from the license surface.
 * @returns True when `max` is negative (the OLO-5.4 unlimited sentinel).
 */
export function seatsUnlimited(seats: TenantLicenseSeats): boolean {
  return seats.max < 0;
}

/**
 * Whether every licensed member seat is occupied.
 *
 * Mirrors the apiome-rest guard (OLO-5.3): a seat-consuming action (invite /
 * reinstate) is refused once `used` reaches `max`. Unlimited plans (negative
 * `max`) are never exhausted.
 *
 * @param seats Seat usage from the license surface.
 * @returns True when the tenant is at capacity and further invites will 403.
 */
export function seatsExhausted(seats: TenantLicenseSeats): boolean {
  return seats.max >= 0 && seats.used >= seats.max;
}

/**
 * Human summary of seat usage for a compact, always-visible indicator.
 *
 * @param seats Seat usage from the license surface.
 * @returns e.g. `"4 of 5 seats used"`, or `"4 seats used"` for an unlimited plan.
 */
export function formatSeatUsage(seats: TenantLicenseSeats): string {
  const noun = seats.used === 1 ? 'seat' : 'seats';
  if (seatsUnlimited(seats)) {
    return `${seats.used} ${noun} used`;
  }
  return `${seats.used} of ${seats.max} ${noun} used`;
}

/**
 * Meter fill + label classes by seat usage.
 *
 * @param used Seats occupied.
 * @param max Seat limit (0 or negative renders as full).
 * @returns Percentage (0–100) plus Tailwind classes for the bar and count.
 */
export function seatMeterAppearance(
  used: number,
  max: number,
): { percent: number; barClass: string; countClass: string } {
  const percent = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 100;
  if (percent >= 100) {
    return {
      percent,
      barClass: 'bg-red-500',
      countClass: 'text-red-600 dark:text-red-400',
    };
  }
  if (percent >= SEAT_WARNING_PERCENT) {
    return {
      percent,
      barClass: 'bg-amber-500',
      countClass: 'text-amber-600 dark:text-amber-400',
    };
  }
  return {
    percent,
    barClass: 'bg-emerald-500',
    countClass: 'text-gray-700 dark:text-gray-300',
  };
}
