'use client';

import * as React from 'react';
import { History, Plus, ShieldCheck, Trash2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardContent, CardFooter, CardHeader } from '@/app/components/ui/Card';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { Spinner } from '@/app/components/ui/Spinner';
import { Switch } from '@/app/components/ui/Switch';
import { buildGovernanceDocsHref, POLICY_DOCS_PAGE } from '@/app/utils/lint-axis-ui';

import {
  BREAKING_PUBLISH_POLICY_OPTIONS,
  componentStageProblems,
  MAX_COMPONENT_APPROVAL_STAGES,
  MAX_COMPONENT_DEPRECATION_NOTICE_DAYS,
  MAX_COMPONENT_STAGE_NAME_LENGTH,
  MAX_REQUIRED_APPROVALS,
  POLICY_COVERAGE_AXES,
  POLICY_GRADE_OPTIONS,
  truncatePolicyFingerprint,
  type BreakingPublishPolicyLevel,
  type GuideCiOutcomes,
} from '@/app/ade/dashboard/style-guides/api';

import { formatPolicyInstant } from '../styleGuidesModel';
import { reviewerRoleOptions } from './guideDetailModel';
import type { GuidePolicyState } from './guideEditorState';

/**
 * The policy tab — HIVE-5.7 (#5310).
 *
 * Authority: `docs/mockups/govern/style-guide-detail.html`, its third panel.
 *
 * The gates applied when lint evidence is judged against this guide: the quality floor, the
 * axes that must carry evidence at all, what a breaking publish without a major bump does,
 * how many review approvals a publish needs (COL-2.3, #4519), and the three outcomes
 * `GET …/lint/gate` reports as failed. Saving snapshots an immutable policy version, which
 * is why the history sits under the form rather than behind a link — a gate whose changes
 * cannot be seen is not governance.
 *
 * ### What HIVE-5.7 changed
 *
 * The fields, their copy, the save gate and every call are the screen's own (CLX-1.3). What
 * changed is the skin — `Card`s on tokens rather than `border-slate-200` boxes with
 * `bg-indigo-600` buttons and `focus:ring-indigo-500` on every field — plus three things
 * that were missing: each choice now says what it *does* (the three CI switches had bare
 * labels), the wait is a shaped skeleton rather than a spinner, and the draft survives a
 * tab switch because it lives in `useGuidePolicy` on the page.
 */

/** The three CI outcome switches, with the sentence each one is really asking. */
const CI_OUTCOMES: ReadonlyArray<{
  key: keyof GuideCiOutcomes;
  id: string;
  title: string;
  description: string;
}> = [
  {
    key: 'failOnUnwaivedErrors',
    id: 'ci-fail-unwaived',
    title: 'Fail on unwaived errors',
    description:
      'Any open error-severity finding without an active waiver fails the gate.',
  },
  {
    key: 'failOnRequiredCoverage',
    id: 'ci-fail-coverage',
    title: 'Fail on required coverage',
    description: 'Missing evidence for a required axis fails the gate.',
  },
  {
    key: 'failOnAxisGates',
    id: 'ci-fail-axis-gates',
    title: 'Fail on axis gates',
    description: 'An axis scoring below its floor fails the gate.',
  },
];

/** Props for {@link PolicyTab}. */
export interface PolicyTabProps {
  /** The policy, its history and its write, from `useGuidePolicy`. */
  state: GuidePolicyState;
  /** Whether the viewer may save. A member sees every value and no Save. */
  readOnly: boolean;
}

/**
 * The policy form and the version history under it.
 *
 * @param props See {@link PolicyTabProps}.
 * @returns The policy form and the version history under it.
 */
export default function PolicyTab({ state, readOnly }: PolicyTabProps) {
  if (state.loading) {
    return (
      <div className="gd-policy" data-testid="guide-policy-loading">
        <span className="sr-only" role="status">
          Loading the policy…
        </span>
        <Skeleton className="gd-skeleton__block" />
        <Skeleton className="gd-skeleton__block" />
      </div>
    );
  }

  if (!state.draft) {
    return (
      <div className="gd-policy">
        {state.error && <Alert variant="error">{state.error}</Alert>}
        <Card>
          <CardContent>
            <p className="hive-quiet">Policy settings not found.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const draft = state.draft;
  const disabled = readOnly || state.saving;
  const breaking = BREAKING_PUBLISH_POLICY_OPTIONS.find(
    (option) => option.value === draft.breakingPublishPolicy
  );
  // A role on its own gates nothing, so the picker follows the count rather than standing
  // on its own — which is also what the REST gate does with the pair.
  const approvalGateArmed = draft.requiredApprovals >= 1;
  const roleOptions = reviewerRoleOptions(state.roles, draft.requiredReviewerRole);
  const componentStages = draft.componentApprovalStages;
  const stageProblems = componentStageProblems(componentStages);

  return (
    <div className="gd-policy" data-testid="guide-policy-panel">
      {state.error && (
        <Alert variant="error" onClose={state.clearError}>
          {state.error}
        </Alert>
      )}

      <Card>
        <CardHeader className="gd-card-header">
          <span className="gd-card-header__lead">
            <span className="tnt-icon-tile" data-tone="accent">
              <ShieldCheck aria-hidden />
            </span>
            <span className="gd-card-header__text">
              {/* `h3` takes its type from the unlayered base rules in `globals.css`, which
                  outrank every utility class — so it is not given one here. */}
              <h3 className="gd-card-title">Policy</h3>
              <p className="hive-quiet">
                Gate settings applied when evaluating lint evidence against this guide.
              </p>
            </span>
          </span>
        </CardHeader>

        <CardContent className="gd-policy-body">
          <div className="gd-policy-grid">
            <div className="sg-field">
              <Label htmlFor="quality-min-grade">Quality minimum grade</Label>
              <select
                id="quality-min-grade"
                aria-label="Quality minimum grade"
                className="hive-control sg-select"
                value={draft.axisGates.quality?.minGrade ?? ''}
                disabled={disabled}
                onChange={(event) => state.setQualityMinGrade(event.target.value)}
              >
                <option value="">No floor</option>
                {POLICY_GRADE_OPTIONS.map((grade) => (
                  <option key={grade} value={grade}>
                    {grade}
                  </option>
                ))}
              </select>
              <p className="sg-field__hint">
                Evidence graded below this floor fails the quality gate.
              </p>
            </div>

            <fieldset className="sg-field">
              <legend className="gd-legend">Required coverage</legend>
              <ul className="gd-coverage">
                {POLICY_COVERAGE_AXES.map((axis) => (
                  <li key={axis} className="gd-coverage__item">
                    <Checkbox
                      id={`coverage-${axis}`}
                      aria-label={`Require ${axis} coverage`}
                      checked={draft.requiredCoverage.includes(axis)}
                      disabled={disabled}
                      onCheckedChange={(checked) =>
                        state.toggleCoverage(axis, checked === true)
                      }
                    />
                    <Label htmlFor={`coverage-${axis}`} className="gd-coverage__label">
                      {axis}
                    </Label>
                  </li>
                ))}
              </ul>
              <p className="sg-field__hint">More axes arrive with the axis-coverage roadmap.</p>
            </fieldset>
          </div>

          <div className="sg-field">
            <Label htmlFor="breaking-publish-policy">Breaking-change publishes</Label>
            <select
              id="breaking-publish-policy"
              aria-label="Breaking-change publish policy"
              className="hive-control sg-select gd-policy-select"
              value={draft.breakingPublishPolicy}
              disabled={disabled}
              onChange={(event) =>
                state.setBreakingPublishPolicy(
                  event.target.value as BreakingPublishPolicyLevel
                )
              }
            >
              {BREAKING_PUBLISH_POLICY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="sg-field__hint">{breaking?.description}</p>
          </div>

          <div>
            <h4 className="sg-section-title">Review approvals</h4>
            <p className="sg-section-desc">
              How many review approvals a draft version must carry before it can be
              published (COL-2.3). Publishing without them is refused; an author can still
              force-publish with a reason, which is recorded in the audit trail.
            </p>
            <div className="gd-policy-grid">
              <div className="sg-field">
                <Label htmlFor="required-approvals">Required approvals</Label>
                <Input
                  id="required-approvals"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={MAX_REQUIRED_APPROVALS}
                  step={1}
                  className="sg-num gd-policy-number"
                  aria-label="Required approvals"
                  aria-describedby="required-approvals-hint"
                  value={draft.requiredApprovals}
                  disabled={disabled}
                  onChange={(event) => state.setRequiredApprovals(event.target.value)}
                />
                <p className="sg-field__hint" id="required-approvals-hint">
                  {approvalGateArmed
                    ? `Publishing is blocked until the current review round has ${draft.requiredApprovals} approval(s).`
                    : 'Zero means no approval gate — publishing never waits for a review.'}
                </p>
              </div>

              <div className="sg-field">
                <Label htmlFor="required-reviewer-role">
                  Required reviewer role{' '}
                  <span className="sg-field__optional">(optional)</span>
                </Label>
                <select
                  id="required-reviewer-role"
                  aria-label="Required reviewer role"
                  aria-describedby="required-reviewer-role-hint"
                  className="hive-control sg-select gd-policy-select"
                  value={draft.requiredReviewerRole ?? ''}
                  disabled={disabled || !approvalGateArmed}
                  onChange={(event) => state.setRequiredReviewerRole(event.target.value)}
                >
                  <option value="">Any approver</option>
                  {roleOptions.map((option) => (
                    <option key={option.slug} value={option.slug}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="sg-field__hint" id="required-reviewer-role-hint">
                  {approvalGateArmed
                    ? 'At least one of those approvals must come from a member with this role. Tenant administrators count as Owner.'
                    : 'Set a required approval count first — a role on its own gates nothing.'}
                </p>
              </div>
            </div>
          </div>

          <div data-testid="guide-policy-component-library">
            <h4 className="sg-section-title">Component library</h4>
            <p className="sg-section-desc">
              The approval stages a shared component revision must pass before it can be
              published, in order, and the notice a deprecation must give its consumers
              (DCW-3.4). With no stages, component revisions publish without approval.
            </p>
            {componentStages.length === 0 ? (
              <p className="hive-quiet">No approval stages — component publishes never wait.</p>
            ) : (
              <ol className="gd-stage-list" aria-label="Component approval stages">
                {componentStages.map((stage, index) => {
                  const stageRoles = reviewerRoleOptions(state.roles, stage.requiredReviewerRole);
                  const id = `component-stage-${index}`;
                  return (
                    <li key={index} className="gd-stage-row" data-testid={id}>
                      <span className="gd-stage-row__index" aria-hidden>
                        {index + 1}
                      </span>
                      <div className="sg-field">
                        <Label htmlFor={`${id}-name`}>Stage name</Label>
                        <Input
                          id={`${id}-name`}
                          aria-label={`Stage ${index + 1} name`}
                          maxLength={MAX_COMPONENT_STAGE_NAME_LENGTH}
                          value={stage.name}
                          disabled={disabled}
                          onChange={(event) =>
                            state.updateComponentStage(index, { name: event.target.value })
                          }
                        />
                      </div>
                      <div className="sg-field">
                        <Label htmlFor={`${id}-approvals`}>Approvals</Label>
                        <Input
                          id={`${id}-approvals`}
                          type="number"
                          inputMode="numeric"
                          min={1}
                          max={MAX_REQUIRED_APPROVALS}
                          step={1}
                          className="sg-num gd-policy-number"
                          aria-label={`Stage ${index + 1} required approvals`}
                          value={stage.requiredApprovals}
                          disabled={disabled}
                          onChange={(event) =>
                            state.updateComponentStage(index, {
                              requiredApprovals: Number.parseInt(event.target.value, 10),
                            })
                          }
                        />
                      </div>
                      <div className="sg-field">
                        <Label htmlFor={`${id}-role`}>
                          Reviewer role <span className="sg-field__optional">(optional)</span>
                        </Label>
                        <select
                          id={`${id}-role`}
                          aria-label={`Stage ${index + 1} required reviewer role`}
                          className="hive-control sg-select gd-policy-select"
                          value={stage.requiredReviewerRole ?? ''}
                          disabled={disabled}
                          onChange={(event) =>
                            state.updateComponentStage(index, {
                              requiredReviewerRole: event.target.value,
                            })
                          }
                        >
                          <option value="">Any approver</option>
                          {stageRoles.map((option) => (
                            <option key={option.slug} value={option.slug}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      {!readOnly && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="gd-stage-row__remove"
                          aria-label={`Remove stage ${index + 1}`}
                          disabled={disabled}
                          onClick={() => state.removeComponentStage(index)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
            {stageProblems.length > 0 && (
              <ul className="gd-stage-problems" role="alert" data-testid="component-stage-problems">
                {stageProblems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            <div className="gd-policy-grid">
              <div className="sg-field">
                {!readOnly && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={disabled || componentStages.length >= MAX_COMPONENT_APPROVAL_STAGES}
                    onClick={state.addComponentStage}
                    data-testid="component-stage-add"
                  >
                    <Plus aria-hidden />
                    Add stage
                  </Button>
                )}
                <p className="sg-field__hint">
                  Up to {MAX_COMPONENT_APPROVAL_STAGES} stages. A stage collects decisions only
                  after every stage before it is satisfied.
                </p>
              </div>
              <div className="sg-field">
                <Label htmlFor="component-deprecation-notice">Deprecation notice (days)</Label>
                <Input
                  id="component-deprecation-notice"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={MAX_COMPONENT_DEPRECATION_NOTICE_DAYS}
                  step={1}
                  className="sg-num gd-policy-number"
                  aria-describedby="component-deprecation-notice-hint"
                  value={draft.componentDeprecationNoticeDays}
                  disabled={disabled}
                  onChange={(event) => state.setComponentDeprecationNoticeDays(event.target.value)}
                />
                <p className="sg-field__hint" id="component-deprecation-notice-hint">
                  {draft.componentDeprecationNoticeDays > 0
                    ? `A deprecation's sunset must be at least ${draft.componentDeprecationNoticeDays} day(s) after it is scheduled.`
                    : 'Zero means a deprecation may set any future sunset date.'}
                </p>
              </div>
            </div>
          </div>

          <div>
            <h4 className="sg-section-title">CI outcomes</h4>
            <p className="sg-section-desc">
              What <code className="mono">GET …/lint/gate</code> reports as failed for
              pipelines using this guide.
            </p>
            <ul className="gd-switch-list">
              {CI_OUTCOMES.map((outcome) => (
                <li key={outcome.key} className="gd-switch-row">
                  <span className="gd-switch-row__text">
                    <Label htmlFor={outcome.id} className="gd-switch-row__title">
                      {outcome.title}
                    </Label>
                    <span className="gd-switch-row__desc">{outcome.description}</span>
                  </span>
                  <Switch
                    id={outcome.id}
                    aria-label={outcome.title}
                    checked={draft.ciOutcomes[outcome.key]}
                    disabled={disabled}
                    onCheckedChange={(checked) => state.setCiOutcome(outcome.key, checked)}
                  />
                </li>
              ))}
            </ul>
          </div>
        </CardContent>

        <CardFooter>
          <span className="hive-quiet">Saving creates an immutable policy version.</span>
          {!readOnly && (
            <Button
              disabled={state.saving || !state.dirty || stageProblems.length > 0}
              onClick={() => void state.save()}
              data-testid="guide-policy-save"
            >
              {state.saving && <Spinner size="sm" aria-hidden />}
              {state.saving ? 'Saving…' : 'Save'}
            </Button>
          )}
        </CardFooter>
      </Card>

      <Card>
        <CardHeader className="gd-card-header">
          <span className="gd-card-header__lead">
            <span className="tnt-icon-tile" data-tone="violet">
              <History aria-hidden />
            </span>
            <span className="gd-card-header__text">
              <h3 className="gd-card-title">Policy versions</h3>
              <p className="hive-quiet">
                Immutable snapshots created when policy is saved.{' '}
                <a
                  href={buildGovernanceDocsHref(POLICY_DOCS_PAGE)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="sg-inline-link"
                  data-testid="policy-docs-link"
                >
                  Policy documentation
                </a>
              </p>
            </span>
          </span>
        </CardHeader>

        {state.versions.length === 0 ? (
          <CardContent>
            <p className="hive-quiet">No policy versions yet.</p>
          </CardContent>
        ) : (
          <ul className="gd-version-list">
            {state.versions.map((version) => (
              <li key={version.id} className="gd-version-row">
                <Badge variant="outline" mono>
                  v{version.versionNumber}
                </Badge>
                <code className="gd-fingerprint" title={version.contentFingerprint}>
                  {truncatePolicyFingerprint(version.contentFingerprint)}
                </code>
                <span className="gd-version-row__when">
                  {formatPolicyInstant(version.createdAt)}
                </span>
                {version.actorLabel && (
                  <span className="gd-version-row__actor">{version.actorLabel}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
