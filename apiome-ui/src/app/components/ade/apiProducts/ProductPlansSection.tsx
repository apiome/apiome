'use client';

/**
 * The **Plans** section of the product editor — APX-1.2 (#6099).
 *
 * A plan is a tier of the product: how a consumer authenticates, the limits it promises, whether a
 * subscription is approved automatically, the gateway environments it is provisioned to and its
 * terms. The section lists the plans and opens one in the plan editor below the table:
 *
 * - **New plan** / **Edit** open the editor; **Save plan** stores it and keeps it open, so the notices
 *   REST returns stay in view — a plan whose environments cannot be provisioned is saved as
 *   **Declared only** and says why.
 * - Limits are rows of a window and a count; **Add limit** offers only the windows not used yet, and
 *   the editor refuses a count below 1 or a window used twice before anything is sent.
 * - A member whose security schemes do not fit the auth strategy is a warning, not a refusal.
 * - **Delete** removes a plan after a confirmation.
 *
 * **Lifecycle** (APX-1.4, #6101): **State** offers only the steps REST accepts (draft ⇄ published →
 * deprecated → retired, and back to published to reinstate). Choosing **Deprecated** opens the
 * **Deprecation** fields — retirement date, replacement plan and a message for subscribed owners;
 * **Retired** stays disabled until the retirement date. A deprecated plan's editor offers
 * **Migrate to plan…**, which previews and then moves its subscriptions without changing any key.
 */

import * as React from 'react';
import { ArrowRightLeft, Pencil, Plus, Trash2, X } from 'lucide-react';

import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  FormFrame,
  FormSection,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from '@/app/components/ui';
import type { ApiProduct } from '@lib/api-products';
import {
  APPROVAL_LABELS,
  AUTH_STRATEGY_LABELS,
  PLAN_APPROVALS,
  PLAN_AUTH_STRATEGIES,
  PLAN_LIMIT_WINDOWS,
  PLAN_STATE_LABELS,
  WINDOW_LABELS,
  draftFromPlan,
  draftToInput,
  emptyPlanDraft,
  freeWindows,
  limitsText,
  planDraftError,
  successorChoices,
  type ApiPlan,
  type ApiPlanMigration,
  type PlanApproval,
  type PlanAuthStrategy,
  type PlanDraft,
  type PlanLimitWindow,
  type PlanState,
} from '@lib/api-plans';
import { canRetireNow, dateInputValue, retireText, selectableStates } from '@lib/api-lifecycle';
import type { GatewayConfig } from '@lib/gateway-configs';
import { createPlan, deletePlan, fetchPlans, migratePlan, updatePlan } from './apiProductsApi';
import { fetchGatewayConfigs } from '../gatewayConfigs/gatewayConfigsApi';

/** The replacement-plan picker's value for "no replacement" (a Select item cannot be empty). */
const NO_SUCCESSOR = '__none__';

/** Which plan the editor holds: a new one, or a stored one. */
type Editing = { mode: 'new' } | { mode: 'edit'; plan: ApiPlan } | null;

/**
 * The **Plans** section.
 *
 * @param props - The product.
 * @returns The section.
 */
export default function ProductPlansSection({ product }: { product: ApiProduct }) {
  const [plans, setPlans] = React.useState<ApiPlan[] | null>(null);
  const [gateways, setGateways] = React.useState<GatewayConfig[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<Editing>(null);
  const [deleting, setDeleting] = React.useState<ApiPlan | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setPlans(await fetchPlans(product.slug));
    } catch (caught) {
      setPlans([]);
      setError(caught instanceof Error ? caught.message : 'Could not load the plans');
    }
  }, [product.slug]);

  React.useEffect(() => {
    void load();
    // The environment picker is secondary: without gateway configs it offers none.
    fetchGatewayConfigs().then(setGateways).catch(() => setGateways([]));
  }, [load]);

  const saved = (plan: ApiPlan) => {
    setPlans((current) => {
      const rest = (current ?? []).filter((existing) => existing.id !== plan.id);
      const index = (current ?? []).findIndex((existing) => existing.id === plan.id);
      if (index < 0) return [...rest, plan];
      rest.splice(index, 0, plan);
      return rest;
    });
    setEditing({ mode: 'edit', plan });
  };

  const removed = (plan: ApiPlan) => {
    setPlans((current) => (current ?? []).filter((existing) => existing.id !== plan.id));
    if (editing?.mode === 'edit' && editing.plan.id === plan.id) setEditing(null);
    setDeleting(null);
  };

  return (
    <section className="apx-section" aria-labelledby="apx-plans" data-testid="product-plans">
      <div className="apx-section__head">
        <h2 id="apx-plans" className="apx-section__title">
          Plans <span className="apx-muted">{plans?.length ?? 0}</span>
        </h2>
        <Button variant="soft" size="sm" onClick={() => setEditing({ mode: 'new' })} data-testid="plan-new">
          <Plus aria-hidden />
          New plan
        </Button>
      </div>
      <p className="apx-muted">
        The tiers consumers subscribe to: how they authenticate, the limits each tier promises and who approves a request.
      </p>
      {plans === null ? (
        <p className="apx-note">Reading the plans…</p>
      ) : plans.length === 0 ? (
        <p className="apx-muted">No plans yet. Add a tier such as Sandbox or Standard.</p>
      ) : (
        <PlansTable
          product={product}
          plans={plans}
          onEdit={(plan) => setEditing({ mode: 'edit', plan })}
          onDelete={setDeleting}
        />
      )}
      {error ? (
        <p className="apx-error" role="alert">
          {error}
        </p>
      ) : null}
      {editing ? (
        <PlanEditor
          key={editing.mode === 'edit' ? `${editing.plan.id}:${editing.plan.updated_at ?? ''}` : 'new'}
          product={product}
          plan={editing.mode === 'edit' ? editing.plan : null}
          plans={plans ?? []}
          gateways={gateways}
          onSaved={saved}
          onMigrated={() => void load()}
          onClose={() => setEditing(null)}
        />
      ) : null}
      <DeletePlanDialog product={product} plan={deleting} onDeleted={removed} onCancel={() => setDeleting(null)} />
    </section>
  );
}

/**
 * The plans table.
 *
 * @param props - The product, its plans, and what **Edit** and **Delete** do.
 * @returns The table.
 */
function PlansTable({
  product,
  plans,
  onEdit,
  onDelete,
}: {
  product: ApiProduct;
  plans: ApiPlan[];
  onEdit: (plan: ApiPlan) => void;
  onDelete: (plan: ApiPlan) => void;
}) {
  return (
    <div className="apx-table-wrap">
      <table className="apx-table" data-testid="product-plans-table">
        <caption className="sr-only">Plans of {product.name}</caption>
        <thead>
          <tr>
            <th scope="col">Plan</th>
            <th scope="col">Auth</th>
            <th scope="col">Limits</th>
            <th scope="col">Approval</th>
            <th scope="col">Environments</th>
            <th scope="col">State</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {plans.map((plan) => (
            <tr key={plan.id} data-testid={`product-plan-${plan.slug}`}>
              <td>
                <span className="apx-name">{plan.name}</span>
                <span className="apx-slug mono">{plan.slug}</span>
              </td>
              <td>
                {AUTH_STRATEGY_LABELS[plan.auth_strategy].label}
                {plan.warnings.length > 0 ? (
                  <span className="apx-plan__flag">
                    <Badge variant="warning">
                      {plan.warnings.length === 1 ? '1 member does not match' : `${plan.warnings.length} members do not match`}
                    </Badge>
                  </span>
                ) : null}
              </td>
              <td className="apx-num">{limitsText(plan)}</td>
              <td>{APPROVAL_LABELS[plan.approval].label}</td>
              <td>
                {plan.environments.length === 0 ? (
                  <span className="apx-muted">None</span>
                ) : (
                  <span className="mono">{plan.environments.map((env) => env.slug ?? 'deleted').join(', ')}</span>
                )}
                {plan.declared_only ? (
                  <span className="apx-plan__flag">
                    <Badge status="draft">Declared only</Badge>
                  </span>
                ) : null}
              </td>
              <td>
                {PLAN_STATE_LABELS[plan.state]}
                {plan.state === 'deprecated' ? (
                  <span className="apx-plan__flag apx-muted" data-testid={`plan-retires-${plan.slug}`}>
                    {retireText(plan.retire_at)}
                    {plan.successor ? ` · moves to ${plan.successor.name}` : ''}
                  </span>
                ) : null}
              </td>
              <td className="apx-actions">
                <Button variant="ghost" size="sm" onClick={() => onEdit(plan)} aria-label={`Edit ${plan.name}`}>
                  <Pencil aria-hidden />
                  Edit
                </Button>
                <Button variant="ghost" size="sm" onClick={() => onDelete(plan)} aria-label={`Delete ${plan.name}`}>
                  <Trash2 aria-hidden />
                  Delete
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The plan editor: a new plan, or a stored one with its notices and warnings above the form.
 *
 * @param props - The product, the plan (or `null` for a new one), the product's plans (replacement
 *   candidates), the workspace's gateway configs, what to do with the saved plan, what to do after a
 *   migration, and how to close the editor.
 * @returns The editor.
 */
function PlanEditor({
  product,
  plan,
  plans,
  gateways,
  onSaved,
  onMigrated,
  onClose,
}: {
  product: ApiProduct;
  plan: ApiPlan | null;
  plans: ApiPlan[];
  gateways: GatewayConfig[];
  onSaved: (plan: ApiPlan) => void;
  onMigrated: () => void;
  onClose: () => void;
}) {
  const [migrating, setMigrating] = React.useState(false);
  const retireBlocked = plan !== null && plan.state === 'deprecated' && !canRetireNow(plan.retire_at);
  const initial = React.useMemo(() => (plan ? draftFromPlan(plan) : emptyPlanDraft()), [plan]);
  const [draft, setDraft] = React.useState<PlanDraft>(initial);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | undefined>();
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const set = <K extends keyof PlanDraft>(key: K, value: PlanDraft[K]) => setDraft((current) => ({ ...current, [key]: value }));

  const save = async () => {
    const invalid = planDraftError(draft);
    if (invalid) {
      setError(invalid);
      return;
    }
    setSaving(true);
    setError(undefined);
    try {
      const input = draftToInput(draft, plan === null);
      onSaved(plan ? await updatePlan(product.slug, plan.slug, input) : await createPlan(product.slug, input));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the plan');
    } finally {
      setSaving(false);
    }
  };

  const id = (field: string) => `plan-${field}`;

  return (
    <div className="apx-plan-editor" data-testid="plan-editor">
      <div className="apx-section__head">
        <h3 className="apx-section__title">{plan ? `Edit ${plan.name}` : 'New plan'}</h3>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close the plan editor">
          <X aria-hidden />
          Close
        </Button>
      </div>
      {plan?.notices.map((notice) => (
        <Alert key={notice.code} variant="info" role="status" data-testid="plan-notice">
          {notice.message}
        </Alert>
      ))}
      {plan?.state === 'deprecated' ? (
        <div className="apx-lifecycle__actions">
          <Button variant="soft" size="sm" onClick={() => setMigrating(true)} data-testid="plan-migrate">
            <ArrowRightLeft aria-hidden />
            Migrate to plan…
          </Button>
          <span className="apx-muted">Moves this plan&apos;s subscriptions to another plan. Keys stay the same.</span>
        </div>
      ) : null}
      {plan && plan.warnings.length > 0 ? (
        <Alert variant="warn" role="status" data-testid="plan-warnings">
          <p>The auth strategy does not match every member:</p>
          <ul className="apx-plan__list">
            {plan.warnings.map((warning) => (
              <li key={`${warning.member?.ref ?? ''}:${warning.code}`}>{warning.message}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
      <FormFrame
        width="default"
        submitLabel={saving ? 'Saving…' : 'Save plan'}
        submitDisabled={!dirty || !draft.name.trim()}
        submitDisabledReason={!draft.name.trim() ? 'A plan needs a name.' : 'Nothing has changed.'}
        submitting={saving}
        dirty={dirty}
        error={error}
        onSubmit={() => void save()}
        data-testid="plan-form"
      >
        <FormSection
          title="Plan"
          headingLevel="h4"
          description={plan ? `Handle: ${plan.slug} — it cannot change.` : 'The handle is made from the name unless you type one.'}
        >
          <FormField label="Name" required htmlFor={id('name')}>
            <Input id={id('name')} value={draft.name} placeholder="Standard" onChange={(event) => set('name', event.target.value)} />
          </FormField>
          {plan ? null : (
            <FormField label="Handle" htmlFor={id('slug')} helperText="Lowercase letters, digits and hyphens.">
              <Input id={id('slug')} className="mono" value={draft.slug} placeholder="standard" onChange={(event) => set('slug', event.target.value)} />
            </FormField>
          )}
          <FormField label="Description" htmlFor={id('description')}>
            <Textarea id={id('description')} rows={2} value={draft.description} onChange={(event) => set('description', event.target.value)} />
          </FormField>
          <FormField
            label="State"
            htmlFor={id('state')}
            helperText={
              retireBlocked
                ? `Retired is available from ${dateInputValue(plan?.retire_at)}.`
                : plan === null
                  ? 'Deprecate or retire a plan once it exists.'
                  : undefined
            }
          >
            <Select value={draft.state} onValueChange={(value) => set('state', value as PlanState)}>
              <SelectTrigger id={id('state')} data-testid="plan-state">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {selectableStates(plan ? plan.state : null).map((value) => (
                  <SelectItem key={value} value={value} disabled={value === 'retired' && retireBlocked}>
                    {PLAN_STATE_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </FormSection>

        {plan && draft.state === 'deprecated' ? (
          <DeprecationSection plan={plan} plans={plans} draft={draft} onChange={set} />
        ) : null}

        <FormSection title="Access" headingLevel="h4">
          <FormField label="Auth strategy" htmlFor={id('auth')} helperText={AUTH_STRATEGY_LABELS[draft.auth_strategy].hint}>
            <Select value={draft.auth_strategy} onValueChange={(value) => set('auth_strategy', value as PlanAuthStrategy)}>
              <SelectTrigger id={id('auth')} data-testid="plan-auth">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLAN_AUTH_STRATEGIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {AUTH_STRATEGY_LABELS[value].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {draft.auth_strategy === 'key_auth' ? (
            <FormField label="Key header" htmlFor={id('header')} helperText="The header consumers send the key in.">
              <Input id={id('header')} className="mono" value={draft.header_name} placeholder="X-API-Key" onChange={(event) => set('header_name', event.target.value)} />
            </FormField>
          ) : null}
          {draft.auth_strategy === 'oauth2_client_credentials' ? (
            <>
              <FormField label="Identity provider config" htmlFor={id('idp')}>
                <Input id={id('idp')} className="mono" value={draft.idp_config_id} placeholder="okta-main" onChange={(event) => set('idp_config_id', event.target.value)} />
              </FormField>
              <FormField label="Scopes" htmlFor={id('scopes')} helperText="Separate scopes with spaces.">
                <Input id={id('scopes')} className="mono" value={draft.scopes} placeholder="payments:read refunds:write" onChange={(event) => set('scopes', event.target.value)} />
              </FormField>
            </>
          ) : null}
          <FormField label="Approval" htmlFor={id('approval')} helperText={APPROVAL_LABELS[draft.approval].hint}>
            <Select value={draft.approval} onValueChange={(value) => set('approval', value as PlanApproval)}>
              <SelectTrigger id={id('approval')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PLAN_APPROVALS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {APPROVAL_LABELS[value].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Maximum key age (days)" htmlFor={id('ttl')} helperText="Leave empty for keys that do not expire.">
            <Input id={id('ttl')} inputMode="numeric" value={draft.credential_ttl_days} placeholder="90" onChange={(event) => set('credential_ttl_days', event.target.value)} />
          </FormField>
        </FormSection>

        <LimitsSection draft={draft} onChange={(limits) => set('limits', limits)} onConcurrency={(value) => set('concurrency', value)} />

        <EnvironmentsSection
          gateways={gateways}
          plan={plan}
          selected={draft.environments}
          onChange={(environments) => set('environments', environments)}
        />

        <FormSection title="Terms" headingLevel="h4">
          <FormField label="Terms URL" htmlFor={id('terms')}>
            <Input id={id('terms')} value={draft.terms_url} placeholder="https://example.com/terms" onChange={(event) => set('terms_url', event.target.value)} />
          </FormField>
          <FormField label="Pricing note" htmlFor={id('pricing')} helperText="Shown to consumers. Apiome does not bill.">
            <Input id={id('pricing')} value={draft.pricing_note} placeholder="Free up to 10,000 requests a month" onChange={(event) => set('pricing_note', event.target.value)} />
          </FormField>
          <FormField label="Billing reference" htmlFor={id('billing')} helperText="Internal. Never exported or shown on the portal.">
            <Input id={id('billing')} className="mono" value={draft.billing_ref} onChange={(event) => set('billing_ref', event.target.value)} />
          </FormField>
        </FormSection>
      </FormFrame>
      {plan && migrating ? (
        <MigratePlanDialog
          product={product}
          plan={plan}
          plans={plans}
          onDone={() => {
            setMigrating(false);
            onMigrated();
          }}
          onCancel={() => setMigrating(false)}
        />
      ) : null}
    </div>
  );
}

/**
 * The **Deprecation** part of the editor, shown while the plan is (or is becoming) deprecated: when
 * it retires, the plan consumers move to, and what subscribed owners are told.
 *
 * @param props - The plan, the product's plans, the draft, and the draft setter.
 * @returns The section.
 */
function DeprecationSection({
  plan,
  plans,
  draft,
  onChange,
}: {
  plan: ApiPlan;
  plans: ApiPlan[];
  draft: PlanDraft;
  onChange: <K extends keyof PlanDraft>(key: K, value: PlanDraft[K]) => void;
}) {
  const choices = successorChoices(plans, { id: plan.id, auth_strategy: draft.auth_strategy });
  return (
    <FormSection
      title="Deprecation"
      headingLevel="h4"
      description="A deprecated plan takes no new subscriptions. Owners of subscribed applications are told once."
      data-testid="plan-deprecation"
    >
      <FormField label="Retire on" htmlFor="plan-retire-at" helperText="Leave empty to retire whenever you decide. Dates are UTC.">
        <Input
          id="plan-retire-at"
          type="date"
          value={draft.retire_at}
          onChange={(event) => onChange('retire_at', event.target.value)}
        />
      </FormField>
      <FormField
        label="Replacement plan"
        htmlFor="plan-successor"
        helperText={
          choices.length === 0
            ? 'No published plan uses the same auth strategy, so consumers could not keep their keys. Publish one first.'
            : 'A published plan with the same auth strategy, so consumers keep their keys.'
        }
      >
        <Select
          value={draft.successor || NO_SUCCESSOR}
          onValueChange={(value) => onChange('successor', value === NO_SUCCESSOR ? '' : value)}
        >
          <SelectTrigger id="plan-successor" data-testid="plan-successor">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_SUCCESSOR}>No replacement</SelectItem>
            {choices.map((choice) => (
              <SelectItem key={choice.slug} value={choice.slug}>
                {choice.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Message to subscribers" htmlFor="plan-deprecation-message">
        <Textarea
          id="plan-deprecation-message"
          rows={2}
          value={draft.deprecation_message}
          placeholder="Standard retires on 31 March. Move to Premium; your key keeps working."
          onChange={(event) => onChange('deprecation_message', event.target.value)}
        />
      </FormField>
    </FormSection>
  );
}

/**
 * **Migrate to plan**: pick a target, **Preview** what would move, then **Migrate**.
 *
 * @param props - The product, the deprecated plan, the product's plans, and what to do after a
 *   migration or on cancel.
 * @returns The dialog.
 */
function MigratePlanDialog({
  product,
  plan,
  plans,
  onDone,
  onCancel,
}: {
  product: ApiProduct;
  plan: ApiPlan;
  plans: ApiPlan[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const choices = successorChoices(plans, plan);
  const initial = choices.some((choice) => choice.slug === plan.successor?.slug) ? plan.successor?.slug : choices[0]?.slug;
  const [target, setTarget] = React.useState<string>(initial ?? '');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ApiPlanMigration | null>(null);
  const migrated = result !== null && !result.dry_run;

  const run = async (dryRun: boolean) => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await migratePlan(product.slug, plan.slug, target, dryRun));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not migrate the plan');
    } finally {
      setBusy(false);
    }
  };

  return (
    // After a real migration, closing reloads the plans (the successor changed); before, it cancels.
    <Dialog open onOpenChange={(open) => (open ? null : migrated ? onDone() : onCancel())}>
      <DialogContent data-testid="plan-migrate-dialog">
        <DialogHeader>
          <DialogTitle>Migrate {plan.name} to another plan</DialogTitle>
          <DialogDescription>
            Each subscription moves to the new plan&apos;s consumer group on the gateway. No key is issued, rotated or revoked.
          </DialogDescription>
        </DialogHeader>
        {choices.length === 0 ? (
          <p className="apx-muted">No published plan uses the same auth strategy. Publish one first.</p>
        ) : (
          <FormField label="Move to" htmlFor="plan-migrate-to">
            <Select
              value={target}
              onValueChange={(value) => {
                setTarget(value);
                setResult(null);
              }}
            >
              <SelectTrigger id="plan-migrate-to" data-testid="plan-migrate-to">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {choices.map((choice) => (
                  <SelectItem key={choice.slug} value={choice.slug}>
                    {choice.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        {result ? (
          <Alert variant="info" role="status" data-testid="plan-migrate-result">
            <p>{result.message}</p>
            <p className="apx-lifecycle__groups mono">
              {result.from_group} → {result.to_group}
            </p>
          </Alert>
        ) : null}
        {error ? (
          <p className="apx-error" role="alert">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          {migrated ? (
            <Button onClick={onDone} data-testid="plan-migrate-done">
              Done
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
              <Button variant="soft" onClick={() => void run(true)} disabled={busy || !target} title={busy ? 'Working…' : !target ? 'Choose a plan to move subscribers to' : undefined} data-testid="plan-migrate-preview">
                Preview
              </Button>
              <Button onClick={() => void run(false)} disabled={busy || !target} title={busy ? 'Working…' : !target ? 'Choose a plan to move subscribers to' : undefined} data-testid="plan-migrate-confirm">
                {busy ? 'Migrating…' : 'Migrate'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The **Limits** part of the editor: one row per window, and the concurrency cap.
 *
 * @param props - The draft, and what to do when the rows or the cap change.
 * @returns The section.
 */
function LimitsSection({
  draft,
  onChange,
  onConcurrency,
}: {
  draft: PlanDraft;
  onChange: (limits: PlanDraft['limits']) => void;
  onConcurrency: (value: string) => void;
}) {
  const free = freeWindows(draft.limits);
  const update = (index: number, patch: Partial<PlanDraft['limits'][number]>) =>
    onChange(draft.limits.map((limit, at) => (at === index ? { ...limit, ...patch } : limit)));

  return (
    <FormSection title="Limits" headingLevel="h4" description="What each consumer may send. Each window takes one limit.">
      <ul className="apx-limits" data-testid="plan-limits">
        {draft.limits.map((limit, index) => (
          <li key={`${limit.window}-${index}`} className="apx-limits__row">
            <FormField label="Requests" htmlFor={`plan-limit-${index}-requests`}>
              <Input
                id={`plan-limit-${index}-requests`}
                inputMode="numeric"
                value={limit.requests}
                onChange={(event) => update(index, { requests: event.target.value })}
              />
            </FormField>
            <FormField label="Per" htmlFor={`plan-limit-${index}-window`}>
              <Select value={limit.window} onValueChange={(value) => update(index, { window: value as PlanLimitWindow })}>
                <SelectTrigger id={`plan-limit-${index}-window`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLAN_LIMIT_WINDOWS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {WINDOW_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <div className="apx-limits__remove">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onChange(draft.limits.filter((_, at) => at !== index))}
                aria-label={`Remove the ${limit.window} limit`}
              >
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <div>
        <Button
          type="button"
          variant="soft"
          size="sm"
          disabled={free.length === 0} title={free.length === 0 ? 'Every rate-limit window already has a limit' : undefined}
          onClick={() => onChange([...draft.limits, { window: free[0], requests: '' }])}
          data-testid="plan-add-limit"
        >
          <Plus aria-hidden />
          Add limit
        </Button>
      </div>
      <FormField label="Concurrency" htmlFor="plan-concurrency" helperText="Requests in flight at once. Leave empty for no cap.">
        <Input id="plan-concurrency" inputMode="numeric" value={draft.concurrency} onChange={(event) => onConcurrency(event.target.value)} />
      </FormField>
    </FormSection>
  );
}

/**
 * The **Environments** part of the editor: the gateway configs the plan is provisioned to.
 *
 * The choices are the workspace's gateway configs, plus any the plan names that the list did not
 * return, so a save never drops one silently.
 *
 * @param props - The gateway configs, the stored plan, the chosen slugs and what to do on a change.
 * @returns The section.
 */
function EnvironmentsSection({
  gateways,
  plan,
  selected,
  onChange,
}: {
  gateways: GatewayConfig[];
  plan: ApiPlan | null;
  selected: string[];
  onChange: (environments: string[]) => void;
}) {
  const choices = React.useMemo(() => {
    const out = gateways.map((gateway) => ({ slug: gateway.slug, name: gateway.name, kind: gateway.connector.kind }));
    for (const slug of selected) {
      if (!out.some((choice) => choice.slug === slug)) {
        const env = plan?.environments.find((candidate) => candidate.slug === slug);
        out.push({ slug, name: env?.name ?? slug, kind: env?.connector_kind ?? '' });
      }
    }
    return out;
  }, [gateways, plan, selected]);
  const toggle = (slug: string, on: boolean) =>
    onChange(on ? [...selected, slug] : selected.filter((chosen) => chosen !== slug));

  return (
    <FormSection
      title="Environments"
      headingLevel="h4"
      description="The gateway environments this plan is provisioned to. Until a connector can provision, the plan is declared only: Apiome records it and changes nothing on the gateway."
    >
      {choices.length === 0 ? (
        <p className="apx-muted">No gateway environments yet. Connect a gateway under Bring in → Connectors.</p>
      ) : (
        <ul className="apx-envs" data-testid="plan-environments">
          {choices.map((choice) => (
            <li key={choice.slug}>
              <label className="apx-envs__item" htmlFor={`plan-env-${choice.slug}`}>
                <Checkbox
                  id={`plan-env-${choice.slug}`}
                  checked={selected.includes(choice.slug)}
                  onCheckedChange={(next) => toggle(choice.slug, next === true)}
                />
                <span>
                  <span className="apx-name">{choice.name}</span>
                  <span className="apx-slug mono">
                    {choice.slug}
                    {choice.kind ? ` · ${choice.kind}` : ''}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </FormSection>
  );
}

/**
 * **Delete** a plan, behind a confirmation.
 *
 * @param props - The product, the plan to delete (or `null` when closed), and what to do after.
 * @returns The dialog.
 */
function DeletePlanDialog({
  product,
  plan,
  onDeleted,
  onCancel,
}: {
  product: ApiProduct;
  plan: ApiPlan | null;
  onDeleted: (plan: ApiPlan) => void;
  onCancel: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const remove = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      await deletePlan(product.slug, plan.slug);
      onDeleted(plan);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete the plan');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={plan !== null} onOpenChange={(open) => (open ? null : onCancel())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {plan?.name ?? 'plan'}?</DialogTitle>
          <DialogDescription>The handle becomes free again in this product.</DialogDescription>
        </DialogHeader>
        {error ? (
          <p className="apx-error" role="alert">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="danger" onClick={() => void remove()} disabled={busy} title={busy ? 'Deleting the plan…' : undefined} data-testid="plan-delete-confirm">
            {busy ? 'Deleting…' : 'Delete plan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
