'use client';

/**
 * Upgrade OpenAPI version — COA-2.6 (#7049).
 *
 * Opened from a version's row menu (**Versions**) or a catalog item's header menu. The dialog plans
 * the upgrade of that version to the chosen **Target version** as soon as it opens (and again when the
 * target changes), and lists every change the upgrade makes: a count per rule, then each change
 * grouped by hop, with the ones a person should check marked **Review**. **Apply as new version**
 * sends the plan's digest, so a version that changed since the review is refused instead of being
 * upgraded unseen; the upgraded document is imported as a new version of the same project or item.
 */

import * as React from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';

import {
  MAX_LISTED_CHANGES,
  UPGRADE_TARGETS,
  applyUpgradePlan,
  groupChangesByHop,
  originNote,
  planHeadline,
  requestUpgradePlan,
  targetsAfter,
  versionLabelProblem,
  type UpgradeApplyResult,
  type UpgradePlan,
  type UpgradeTarget,
} from './openapiUpgradeModel';

export interface OpenapiUpgradeDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per open so it starts over. */
  open: boolean;
  /** Called with the open state. */
  onOpenChange: (open: boolean) => void;
  /** The project or catalog item. */
  projectId: string;
  /** The version to upgrade (`versions.id`); omitted means the latest. */
  versionId?: string;
  /** The version's label, for the title. */
  versionLabel?: string | null;
  /** Labels the project already uses (the new label must be different). */
  existingLabels?: readonly string[];
  /** The first target shown (default `3.2`). */
  initialTarget?: UpgradeTarget;
  /** A plan to show without fetching (fixtures and tests). */
  initialPlan?: UpgradePlan;
  /** Called after an apply created the new version. */
  onApplied?: (result: UpgradeApplyResult) => void;
}

const LABEL_FIELD = 'openapi-upgrade-label';

/**
 * Render the dialog. See {@link OpenapiUpgradeDialogProps}.
 *
 * @returns The dialog.
 */
export function OpenapiUpgradeDialog({
  open,
  onOpenChange,
  projectId,
  versionId,
  versionLabel,
  existingLabels = [],
  initialTarget = '3.2',
  initialPlan,
  onApplied,
}: OpenapiUpgradeDialogProps) {
  const [target, setTarget] = React.useState<UpgradeTarget>(initialPlan?.target ?? initialTarget);
  const [plan, setPlan] = React.useState<UpgradePlan | null>(initialPlan ?? null);
  const [sourceFamily, setSourceFamily] = React.useState<string | null>(initialPlan?.source_family ?? null);
  const [planning, setPlanning] = React.useState(!initialPlan);
  const [applying, setApplying] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [label, setLabel] = React.useState('');
  const [applied, setApplied] = React.useState<UpgradeApplyResult | null>(null);
  const skipFirstPlan = React.useRef(Boolean(initialPlan));
  const returnFocus = useReturnFocus(open);

  React.useEffect(() => {
    if (!open) return;
    if (skipFirstPlan.current) {
      skipFirstPlan.current = false;
      return;
    }
    let cancelled = false;
    setPlanning(true);
    setError(null);
    setPlan(null);
    requestUpgradePlan(projectId, versionId, target)
      .then((next) => {
        if (cancelled) return;
        setPlan(next);
        setSourceFamily(next.source_family);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'The upgrade could not be planned.');
      })
      .finally(() => {
        if (!cancelled) setPlanning(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectId, versionId, target]);

  const labelProblem = versionLabelProblem(label, existingLabels);
  const offered = targetsAfter(sourceFamily);
  const canApply = Boolean(plan && !plan.already_current && !planning && !applying && !labelProblem && !applied);
  const applyBlocker = applying
    ? 'Creating the upgraded version'
    : planning
      ? 'Wait for the plan'
      : !plan
        ? 'There is no plan to apply'
        : plan.already_current
          ? 'This version is already at the target version'
          : labelProblem
            ? labelProblem
            : applied
              ? 'The upgraded version was created'
              : undefined;

  const handleApply = async () => {
    if (!plan) return;
    setApplying(true);
    setError(null);
    try {
      const result = await applyUpgradePlan(projectId, versionId, plan, label);
      setApplied(result);
      onApplied?.(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The upgrade could not be applied.');
    } finally {
      setApplying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!applying ? onOpenChange(next) : undefined)}>
      <DialogContent size="lg" onCloseAutoFocus={returnFocus} data-testid="openapi-upgrade-dialog">
        <DialogHeader>
          <DialogTitle>Upgrade OpenAPI version{versionLabel ? ` — ${versionLabel}` : ''}</DialogTitle>
          <DialogDescription>
            Review every change the upgrade makes. Nothing is written until you apply it, and applying adds a new
            version — this one stays as it is.
          </DialogDescription>
        </DialogHeader>

        <div className="oau-body">
          <div className="oau-target">
            <span className="oau-target__label" id="openapi-upgrade-target-label">
              Target version
            </span>
            <Segmented
              value={target}
              onValueChange={(value) => setTarget(value as UpgradeTarget)}
              aria-labelledby="openapi-upgrade-target-label"
              size="sm"
              data-testid="openapi-upgrade-target"
            >
              {UPGRADE_TARGETS.map((option) => (
                <SegmentedItem
                  key={option}
                  value={option}
                  disabled={planning || applying || !offered.includes(option)}
                  title={
                    !offered.includes(option)
                      ? 'Older than this version'
                      : planning
                        ? 'Wait for the plan'
                        : applying
                          ? 'Wait for the upgrade to finish'
                          : undefined
                  }
                >
                  OpenAPI {option}
                </SegmentedItem>
              ))}
            </Segmented>
          </div>

          {planning ? (
            <p className="oau-status" role="status" data-testid="openapi-upgrade-planning">
              Planning the upgrade…
            </p>
          ) : null}

          {plan ? <PlanView plan={plan} /> : null}

          {plan && !plan.already_current && !applied ? (
            <FormField
              label="New version label"
              htmlFor={LABEL_FIELD}
              helperText="Leave empty for a date and time label."
              error={labelProblem ?? undefined}
            >
              <Input
                id={LABEL_FIELD}
                value={label}
                placeholder="2.0.0"
                onChange={(event) => setLabel(event.target.value)}
                data-testid="openapi-upgrade-label"
              />
            </FormField>
          ) : null}

          {applied ? (
            <p className="oau-done" role="status" data-testid="openapi-upgrade-applied">
              Created version <strong>{applied.version_label}</strong> (OpenAPI {applied.target_version}).
            </p>
          ) : null}

          {error ? (
            <div className="cid-refresh__error" role="alert" data-testid="openapi-upgrade-error">
              {error}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={applying}
            title={applying ? 'Wait for the upgrade to finish' : undefined}
            onClick={() => onOpenChange(false)}
          >
            {applied ? 'Close' : 'Cancel'}
          </Button>
          {!applied ? (
            <Button
              variant="primary"
              disabled={!canApply}
              title={applyBlocker}
              onClick={() => void handleApply()}
              data-testid="openapi-upgrade-apply"
            >
              {applying ? 'Applying…' : 'Apply as new version'}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The plan: headline, source note, a count per rule and every change grouped by hop.
 *
 * @param props.plan - The plan to show.
 * @returns The plan view.
 */
function PlanView({ plan }: { plan: UpgradePlan }) {
  const groups = groupChangesByHop(plan);
  return (
    <section className="oau-plan" aria-label="Upgrade plan" data-testid="openapi-upgrade-plan">
      <p className="oau-plan__headline" data-testid="openapi-upgrade-headline">
        {planHeadline(plan)}
      </p>
      <p className="cid-note">{originNote(plan.origin)}</p>

      {plan.rules.length ? (
        <table className="oau-rules" data-testid="openapi-upgrade-rules">
          <caption className="oau-caption">Changes by rule</caption>
          <thead>
            <tr>
              <th scope="col">Rule</th>
              <th scope="col">Hop</th>
              <th scope="col" className="oau-rules__count">
                Changes
              </th>
            </tr>
          </thead>
          <tbody>
            {plan.rules.map((row) => (
              <tr key={row.rule}>
                <td>
                  {row.title} <code className="oau-code">{row.rule}</code>
                </td>
                <td>{row.hop === '*' ? 'every hop' : row.hop}</td>
                <td className="oau-rules__count">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {groups.map((group, index) => (
        <details key={group.hop} className="oau-hop" open={index === 0}>
          <summary className="oau-hop__summary">
            {group.hop} · {group.changes.length} change{group.changes.length === 1 ? '' : 's'}
          </summary>
          <ol className="oau-changes">
            {group.changes.slice(0, MAX_LISTED_CHANGES).map((change, index) => (
              <li key={`${change.rule}-${change.pointer}-${index}`} className="oau-change">
                <span className="oau-change__summary">
                  {change.summary}
                  {change.review ? (
                    <Badge variant="warn">
                      Review
                    </Badge>
                  ) : null}
                </span>
                <code className="oau-code">{change.pointer || '/'}</code>
              </li>
            ))}
          </ol>
          {group.changes.length > MAX_LISTED_CHANGES ? (
            <p className="cid-note">
              {group.changes.length - MAX_LISTED_CHANGES} more changes are not listed here. Run{' '}
              <code className="oau-code">apiome upgrade</code> to see them all.
            </p>
          ) : null}
        </details>
      ))}
    </section>
  );
}
