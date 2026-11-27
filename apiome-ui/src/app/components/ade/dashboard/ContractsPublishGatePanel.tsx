'use client';

/**
 * The contracts gate in the publish dialog — PFX-7.3 (#6963).
 *
 * Loads the server assessment for the revision being published and surfaces the Pact
 * can-i-deploy verdict: which contract rows fail, and — when the tenant's `contracts.publishPolicy`
 * is `block` — that publish is refused unless forced with a reason. It reports and decides
 * nothing: the refusal itself comes from apiome-rest's publish prechecks (422
 * `contractsPublishGate`), so the dialog and the API cannot disagree.
 *
 * Silent by design when there is nothing to say (deployable, no contracts, policy off, not
 * readable), so a project without contracts sees no friction. A verification that has not
 * arrived yet is shown as pending — never as a failure.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Handshake } from 'lucide-react';
import { Alert } from '../../ui/Alert';
import { Badge } from '../../ui/Badge';
import { LoadingState } from '../../ui/LoadingState';
import { ErrorBanner } from '../../ui/ErrorState';
import type { StatusTone } from '../../ui/statusVocabulary';
import {
  contractsGateIsVisible,
  contractsGateStatusLabel,
  fetchContractsPublishGate,
  type ContractsPublishGate,
} from '@/app/utils/contracts-publish-gate';

/** The vocabulary tone for each verdict. */
const GATE_STATUS_TONE: Readonly<Record<string, StatusTone>> = {
  blocked: 'danger',
  warning: 'warn',
  pending: 'accent',
  ok: 'ok',
  'no-contracts': 'outline',
  disabled: 'outline',
  unavailable: 'outline',
};

export interface ContractsPublishGatePanelProps {
  projectId: string;
  versionId: string;
  /** Only fetch while the dialog is open. */
  enabled?: boolean;
}

/**
 * Render the contracts verdict and its per-row reasons for publish.
 */
export function ContractsPublishGatePanel({
  projectId,
  versionId,
  enabled = true,
}: ContractsPublishGatePanelProps) {
  const [gate, setGate] = useState<ContractsPublishGate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!enabled) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const assessment = await fetchContractsPublishGate(projectId, versionId, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setGate(assessment);
      setLoading(false);
    } catch (e: unknown) {
      if (controller.signal.aborted) return;
      setGate(null);
      setError(e instanceof Error ? e.message : 'Failed to load the contracts gate');
      setLoading(false);
    }
  }, [enabled, projectId, versionId]);

  useEffect(() => {
    // Load-on-open fetch: the dialog must show the spinner immediately, and the in-flight
    // request is aborted on close by the cleanup below.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load-on-open fetch, aborted on close
    void load();
    return () => abortRef.current?.abort();
  }, [load]);

  if (!enabled) return null;

  if (loading) {
    return (
      <div className="ver-gate" data-testid="contracts-publish-gate-loading">
        <div className="ver-gate__head">
          <h3 className="ver-gate__title">
            <Handshake aria-hidden />
            Contracts
          </h3>
        </div>
        <LoadingState
          className="ver-gate__loading"
          minHeightClassName="min-h-0"
          spinnerSize="sm"
          message="Checking contracts…"
        />
      </div>
    );
  }

  if (error) {
    return (
      <ErrorBanner
        title="Couldn't check contracts"
        description={error}
        onRetry={() => void load()}
        data-testid="contracts-publish-gate-error"
      />
    );
  }

  if (!gate || !contractsGateIsVisible(gate)) return null;

  const tone = GATE_STATUS_TONE[gate.status] ?? 'neutral';
  const target = gate.pacticipant
    ? `${gate.pacticipant} ${gate.version ?? ''}${gate.environment ? ` → ${gate.environment}` : ''}`.trim()
    : null;

  return (
    <div
      className={gate.status === 'pending' ? 'ver-gate' : 'ver-gate ver-gate--warn'}
      data-testid="contracts-publish-gate-panel"
    >
      <div className="ver-gate__head">
        <h3 className="ver-gate__title">
          <Handshake aria-hidden />
          Contracts
        </h3>
        <Badge variant={tone} data-testid="contracts-publish-gate-status">
          {contractsGateStatusLabel(gate.status)}
        </Badge>
      </div>
      {target ? <p className="ver-gate__sub mono">{target}</p> : null}

      <Alert
        variant={gate.blocked ? 'error' : gate.status === 'pending' ? 'info' : 'warning'}
        className="ver-gate__banner"
      >
        {gate.message}
        {gate.blocked
          ? ' Publishing is blocked by your tenant policy — get the contracts verified or use force publish with a reason.'
          : ''}
      </Alert>

      {gate.reasons.length > 0 ? (
        <ul className="ver-gate__findings">
          {gate.reasons.map((row) => (
            <li key={`${row.code}:${row.text}`} className="ver-gate__finding" data-testid="contracts-publish-gate-reason">
              <span className="ver-gate__tag mono">{row.code}</span>
              <span className="ver-gate__message">{row.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
