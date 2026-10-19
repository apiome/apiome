'use client';

/**
 * The **Owner** section of an agent, model or gateway config page — CDG-5.2 (#5980), CDG-5.3 (#5981).
 *
 * Shows the owner team (confirmed, else suggested, with **Confirm** on a suggestion) and lets the
 * reader assign a team. Assigning makes the team the confirmed owner (`PUT /v1/tenants/{t}/owners/
 * {kind}/{id}`); apiome-rest checks `consumer_contracts:edit`.
 */

import * as React from 'react';
import { Alert, Button, Label } from '@/app/components/ui';
import { OwnerCell, assignOwner, useTeams } from '@/app/components/ade/owners';
import type { EntityOwner, OwnerEntityKind } from '@lib/owners';

/** Props for {@link EntityOwnerSection}. */
export interface EntityOwnerSectionProps {
  /** `agent`, `model` or `gateway_config` (CDG-5.3). */
  kind: Extract<OwnerEntityKind, 'agent' | 'model' | 'gateway_config'>;
  /** The entity id. */
  entityId: string;
  /** The current owner, or `null`. */
  owner: EntityOwner | null;
  /** Called after the owner changed, to re-read the page. */
  onChanged: () => void;
}

/**
 * The owner and the assign control.
 *
 * @param props - See {@link EntityOwnerSectionProps}.
 * @returns The section.
 */
export function EntityOwnerSection({ kind, entityId, owner, onChanged }: EntityOwnerSectionProps) {
  const { teams } = useTeams();
  const [team, setTeam] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const selectId = `agt-owner-${kind}`;

  const assign = async () => {
    if (!team) return;
    setBusy(true);
    setError(null);
    try {
      await assignOwner(team, [{ kind, id: entityId }]);
      setTeam('');
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not assign the owner');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="agt-section" aria-labelledby={`${selectId}-title`} data-testid="entity-owner">
      <h2 id={`${selectId}-title`} className="agt-section__title">
        Owner
      </h2>
      <div className="agt-owner">
        <OwnerCell owner={owner} kind={kind} entityId={entityId} onChange={() => onChanged()} testId="entity-owner-cell" />
        <Label htmlFor={selectId} className="sr-only">
          Owner team
        </Label>
        <select
          id={selectId}
          className="agt-select"
          value={team}
          disabled={busy}
          onChange={(event) => setTeam(event.target.value)}
          data-testid="entity-owner-select"
        >
          <option value="">Choose a team…</option>
          {teams.map((entry) => (
            <option key={entry.id} value={entry.slug}>
              {entry.name}
            </option>
          ))}
        </select>
        <Button size="sm" variant="outline" onClick={() => void assign()} disabled={!team || busy} data-testid="entity-owner-assign">
          {owner ? 'Change owner' : 'Assign owner'}
        </Button>
      </div>
      {error ? <Alert variant="error">{error}</Alert> : null}
    </section>
  );
}
