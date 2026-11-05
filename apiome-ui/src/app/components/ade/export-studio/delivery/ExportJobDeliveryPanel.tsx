'use client';

import { useCallback, useEffect, useState } from 'react';
import { Send } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Label } from '@/app/components/ui/Label';

import { DeliveryAttemptList } from './DeliveryAttemptList';
import {
  DeliveryProfilesError,
  deliverJob,
  fetchDeliveryProfiles,
  fetchJobDeliveries,
} from './deliveryProfilesApi';
import {
  CHANNEL_LABELS,
  destinationSummary,
  type DeliveryAttempt,
  type DeliveryProfile,
} from './deliveryProfilesModel';

/** How often the panel re-reads a job's deliveries while some are still running, in ms. */
export const DELIVERY_POLL_MS = 2000;
/** The most re-reads before the panel stops waiting (the list can still be refreshed). */
export const DELIVERY_POLL_LIMIT = 30;

/** Props for {@link ExportJobDeliveryPanel}. */
export interface ExportJobDeliveryPanelProps {
  /** The completed job, or null before one is generated. */
  jobId: string | null;
  /** Before a job: the profiles chosen to deliver with on completion. */
  selected: string[];
  /** Before a job: change the chosen profiles. */
  onSelectedChange: (ids: string[]) => void;
  /** How many profiles the job was submitted with (the deliveries to wait for). */
  expected: number;
  /** The Delivery tab, for the "manage profiles" link. */
  manageHref: string;
}

/**
 * Delivery on Export studio's Review step (MFX-38.4, #4331).
 *
 * **Before Generate** it lists the workspace's delivery profiles as checkboxes — "Deliver when it
 * completes": the job is submitted with them (`delivery_profiles`) and the REST layer delivers it
 * through each one's channel as soon as it finishes. **After** it lists the job's deliveries across
 * every channel (re-read until each chosen profile has reported) and offers **Deliver now** with any
 * profile. With no profiles it says where to create one.
 *
 * @param props See {@link ExportJobDeliveryPanelProps}.
 * @returns The panel, or null while the profiles load.
 */
export function ExportJobDeliveryPanel({
  jobId,
  selected,
  onSelectedChange,
  expected,
  manageHref,
}: ExportJobDeliveryPanelProps) {
  const [profiles, setProfiles] = useState<DeliveryProfile[] | null>(null);
  const [attempts, setAttempts] = useState<DeliveryAttempt[]>([]);
  const [nowProfile, setNowProfile] = useState('');
  const [delivering, setDelivering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchDeliveryProfiles()
      .then((rows) => live && setProfiles(rows))
      .catch(() => live && setProfiles([]));
    return () => {
      live = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!jobId) return [];
    try {
      const rows = await fetchJobDeliveries(jobId);
      setAttempts(rows);
      return rows;
    } catch {
      return [];
    }
  }, [jobId]);

  // A completed job's on-completion deliveries run after it finishes: re-read until every chosen
  // profile has an attempt that is no longer in progress, or the poll budget runs out.
  useEffect(() => {
    if (!jobId) return undefined;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let live = true;
    const tick = async () => {
      const rows = await refresh();
      polls += 1;
      const settled = rows.filter((row) => row.outcome !== 'in_progress').length;
      if (live && (settled < expected || rows.some((row) => row.outcome === 'in_progress')) && polls < DELIVERY_POLL_LIMIT) {
        timer = setTimeout(() => void tick(), DELIVERY_POLL_MS);
      }
    };
    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, expected, refresh]);

  const deliverNow = useCallback(async () => {
    if (!jobId || !nowProfile) return;
    setDelivering(true);
    setError(null);
    try {
      await deliverJob(jobId, nowProfile);
      await refresh();
    } catch (cause) {
      const extra = cause instanceof DeliveryProfilesError && cause.errors.length ? ` ${cause.errors.join(' ')}` : '';
      setError(`${cause instanceof Error ? cause.message : 'The delivery could not start.'}${extra}`);
    } finally {
      setDelivering(false);
    }
  }, [jobId, nowProfile, refresh]);

  if (profiles === null) return null;

  const toggle = (id: string, on: boolean) =>
    onSelectedChange(on ? [...selected, id] : selected.filter((value) => value !== id));

  return (
    <section className="xdlv-job" aria-label="Delivery" data-testid="export-job-delivery">
      <div className="xdlv-job__head">
        <Send aria-hidden />
        <h3 className="xdlv-job__title">{jobId ? 'Deliveries' : 'Deliver when it completes'}</h3>
        <a className="xdlv-job__manage" href={manageHref}>
          Manage profiles
        </a>
      </div>

      {profiles.length === 0 && !jobId ? (
        <p className="xdlv-quiet">
          No delivery profiles yet. Create one on the <a href={manageHref}>Delivery</a> tab to send exports to a
          repository, a webhook or a bucket.
        </p>
      ) : null}

      {!jobId && profiles.length > 0 ? (
        <ul className="xdlv-job__choices">
          {profiles.map((profile) => (
            <li key={profile.id}>
              <label className="xdlv-choice">
                <input
                  type="checkbox"
                  checked={selected.includes(profile.id)}
                  disabled={!selected.includes(profile.id) && selected.length >= 5}
                  onChange={(event) => toggle(profile.id, event.target.checked)}
                />
                <span className="xdlv-choice__name">{profile.name}</span>
                <span className="xdlv-choice__meta">
                  {CHANNEL_LABELS[profile.channel]} · <span className="mono">{destinationSummary(profile)}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}

      {jobId ? (
        <>
          <DeliveryAttemptList
            attempts={attempts}
            label="This export's deliveries"
            emptyMessage={expected > 0 ? 'Delivering…' : 'Not delivered yet.'}
          />
          {profiles.length > 0 ? (
            <div className="xdlv-job__now">
              <Label htmlFor="xdlv-deliver-now" className="sr-only">
                Delivery profile
              </Label>
              <select
                id="xdlv-deliver-now"
                className="hive-control xdlv-select"
                value={nowProfile}
                onChange={(event) => setNowProfile(event.target.value)}
              >
                <option value="">Choose a profile…</option>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </select>
              <Button size="sm" variant="outline" disabled={!nowProfile || delivering} onClick={() => void deliverNow()}>
                Deliver now
              </Button>
            </div>
          ) : null}
          {error ? <p className="xdlv-job__error" role="alert">{error}</p> : null}
        </>
      ) : null}
    </section>
  );
}
