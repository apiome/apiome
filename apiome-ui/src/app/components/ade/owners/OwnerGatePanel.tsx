'use client';

/**
 * The owner gate in the publish dialog — CDG-2.5 (#5964).
 *
 * "No silent success": the panel always says where the gate stands — **off** (publishing does not
 * require an owner), **met** (the project's owner team), or **blocked** (no confirmed owner; publish
 * will be refused with reason `no-owner` unless forced). It reports and decides nothing: the refusal
 * itself comes from apiome-rest's publish prechecks.
 */

import * as React from 'react';
import { UsersRound } from 'lucide-react';
import { Alert, Badge } from '@/app/components/ui';
import { isFeatureReleased } from '@lib/feature-release';
import type { OwnerGate } from '@lib/owners';
import { fetchOwnerGate } from './ownersApi';

/** What each status is called on the badge. */
const STATUS_LABELS: Readonly<Record<OwnerGate['status'], string>> = {
  disabled: 'Off',
  satisfied: 'Met',
  blocked: 'Blocked',
};

/** The badge tone each status takes. */
const STATUS_TONES: Readonly<Record<OwnerGate['status'], 'neutral' | 'ok' | 'danger'>> = {
  disabled: 'neutral',
  satisfied: 'ok',
  blocked: 'danger',
};

/** Props for {@link OwnerGatePanel}. */
export interface OwnerGatePanelProps {
  /** The project being published. */
  projectId: string;
  /** Read only while the dialog is open. */
  enabled: boolean;
}

/**
 * The owner gate card.
 *
 * @param props - See {@link OwnerGatePanelProps}.
 * @returns The card, a failure note, or nothing while closed.
 */
export function OwnerGatePanel({ projectId, enabled }: OwnerGatePanelProps) {
  const [gate, setGate] = React.useState<OwnerGate | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!enabled || !projectId) return;
    let live = true;
    setGate(null);
    setError(null);
    fetchOwnerGate(projectId)
      .then((next) => live && setGate(next))
      .catch((caught: unknown) => live && setError(caught instanceof Error ? caught.message : 'Could not check the owner gate'));
    return () => {
      live = false;
    };
  }, [enabled, projectId]);

  if (!enabled) return null;
  // While ownership is unreleased (`teams`, lib/feature-release.ts) the card only appears when it
  // has to: a tenant policy set before the gate still refuses a publish, and that must be said.
  if (!isFeatureReleased('teams') && gate?.status !== 'blocked') return null;
  if (error) {
    return (
      <Alert variant="warning" data-testid="owner-gate-error">
        Could not check the owner gate: {error}
      </Alert>
    );
  }
  if (!gate) {
    return (
      <p className="ver-gate__sub" data-testid="owner-gate-loading">
        Checking the owner gate…
      </p>
    );
  }
  return (
    <div className={gate.status === 'blocked' ? 'ver-gate ver-gate--warn' : 'ver-gate'} data-testid="owner-gate-panel">
      <div className="ver-gate__head">
        <h3 className="ver-gate__title">
          <UsersRound aria-hidden />
          Owner team
        </h3>
        <Badge variant={STATUS_TONES[gate.status]} data-testid="owner-gate-status">
          {STATUS_LABELS[gate.status]}
        </Badge>
      </div>
      <p className="ver-gate__sub" data-testid="owner-gate-message">
        {gate.message}
      </p>
      {gate.status === 'blocked' ? (
        <Alert variant="error" className="ver-gate__banner">
          Publishing will be refused (reason <span className="mono">no-owner</span>) unless you force-publish with a
          reason. Assign or confirm an owner on the project first.
        </Alert>
      ) : null}
    </div>
  );
}
