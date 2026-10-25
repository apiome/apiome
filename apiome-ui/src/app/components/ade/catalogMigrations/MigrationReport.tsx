'use client';

/**
 * One Backstage or Compass **import report** — CDG-5.5 (#5983).
 *
 * Shared by the report page (`/ade/dashboard/catalog/imports/[id]`) and the **Import to catalog**
 * wizard's Compass step. It lists what the import found — **Teams** and **Components**, each waiting
 * for a click — and **Unmapped fields**, every field that has no Apiome equivalent (its path and
 * why, never its value).
 *
 * Nothing here is automatic: **Create team** (or **Use team** when one has the slug), **Register
 * component** and **Apply to <Project>** each open a short dialog; **Dismiss** keeps a suggestion
 * out of later imports. Accepting never makes anyone a confirmed owner — owners arrive as
 * suggestions on the entity's **Owner** section.
 */

import * as React from 'react';
import Link from 'next/link';
import { Check, X } from 'lucide-react';

import { Alert, Badge, Button, Checkbox, Input, Label, Spinner } from '@/app/components/ui';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { toast } from '@/app/components/ui/toast';
import {
  MIGRATION_SOURCE_LABELS,
  SUGGESTION_STATUS_LABELS,
  acceptLabel,
  groupUnmapped,
  migrationCountsLine,
  suggestionDetail,
  suggestionEntityHref,
  type AcceptSuggestionInput,
  type MigrationRun,
  type MigrationSuggestion,
} from '@lib/catalog-migrations';
import { acceptSuggestion, dismissSuggestion } from './catalogMigrationsApi';
import { isFeatureReleased } from '@lib/feature-release';

/** Props for {@link MigrationReport}. */
export interface MigrationReportProps {
  /** The report, with its suggestions. */
  run: MigrationRun;
  /** Whether the reader may decide (`imports:create`); otherwise the actions are hidden. */
  canDecide: boolean;
  /** Called after a decision, to re-read the report. */
  onChanged: () => void;
}

/** The status badge's tone. */
const STATUS_TONE = { suggested: 'warn', accepted: 'ok', dismissed: 'neutral' } as const;

/**
 * The accept dialog: name and slug overrides, and (for a matched component) "register on its own".
 */
function AcceptDialog({
  suggestion,
  onClose,
  onAccepted,
}: {
  suggestion: MigrationSuggestion | null;
  onClose: () => void;
  onAccepted: () => void;
}) {
  const [name, setName] = React.useState('');
  const [slug, setSlug] = React.useState('');
  const [asComponent, setAsComponent] = React.useState(false);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!suggestion) return;
    setName(suggestion.name);
    setSlug(suggestion.slug);
    setAsComponent(false);
    setError('');
  }, [suggestion]);

  const applying = Boolean(suggestion?.match) && !asComponent;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!suggestion) return;
    if (!applying && !name.trim()) {
      setError('Enter a name.');
      return;
    }
    setBusy(true);
    setError('');
    const input: AcceptSuggestionInput = applying ? {} : { name: name.trim(), slug: slug.trim(), asComponent };
    try {
      const accepted = await acceptSuggestion(suggestion.id, input);
      toast.success(`${accepted.name} accepted`);
      onAccepted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not accept the suggestion');
    } finally {
      setBusy(false);
    }
  };

  const title = !suggestion ? '' : applying || suggestion.kind === 'team' ? acceptLabel(suggestion) : 'Register component';
  const description = !suggestion
    ? ''
    : suggestion.kind === 'team'
      ? 'The team is created with the imported description, email and links. It becomes a suggested owner of everything the import says it owns; confirm owners on each page.'
      : applying
        ? `The import's owner and dependencies are applied to ${suggestion.match?.name ?? 'the existing entity'} as suggestions.`
        : 'The component is registered in the catalog with its links and declared dependencies.';

  return (
    <Dialog open={suggestion !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="mig-dialog" data-testid="migration-accept-dialog">
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="mig-dialog__fields">
            {suggestion?.match ? (
              <div className="mig-dialog__check">
                <Checkbox
                  id="mig-as-component"
                  checked={asComponent}
                  onCheckedChange={(checked) => setAsComponent(checked === true)}
                />
                <Label htmlFor="mig-as-component">Register it as a component of its own instead</Label>
              </div>
            ) : null}
            {!applying ? (
              <>
                <div className="mig-dialog__field">
                  <Label htmlFor="mig-name">Name</Label>
                  <Input id="mig-name" value={name} onChange={(event) => setName(event.target.value)} />
                </div>
                <div className="mig-dialog__field">
                  <Label htmlFor="mig-slug">Slug</Label>
                  <Input id="mig-slug" value={slug} spellCheck={false} onChange={(event) => setSlug(event.target.value)} />
                </div>
              </>
            ) : null}
            {error ? <Alert variant="danger">{error}</Alert> : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="migration-accept-submit">
              {busy ? <Spinner aria-hidden /> : null}
              {title}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One suggestions table (teams or components).
 */
function SuggestionTable({
  title,
  id,
  suggestions,
  canDecide,
  busyId,
  onAccept,
  onDismiss,
}: {
  title: string;
  id: string;
  suggestions: MigrationSuggestion[];
  canDecide: boolean;
  busyId: string | null;
  onAccept: (suggestion: MigrationSuggestion) => void;
  onDismiss: (suggestion: MigrationSuggestion) => void;
}) {
  return (
    <section className="agt-section" aria-labelledby={id} data-testid={id}>
      <h2 id={id} className="agt-section__title">
        {title} <span className="mig-count">{suggestions.length}</span>
      </h2>
      {suggestions.length === 0 ? (
        <p className="agt-muted">None in this import.</p>
      ) : (
        <div className="agt-table-wrap">
          <table className="agt-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">From</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {suggestions.map((suggestion) => {
                const href = suggestionEntityHref(suggestion);
                return (
                  <tr key={suggestion.id} data-testid={`migration-suggestion-${suggestion.slug}`}>
                    <td>
                      <span className="agt-strong">
                        {href && suggestion.status === 'accepted' ? (
                          <Link className="agt-link" href={href}>
                            {suggestion.name}
                          </Link>
                        ) : (
                          suggestion.name
                        )}
                      </span>
                      <span className="agt-muted mig-detail">{suggestionDetail(suggestion)}</span>
                      {suggestion.match && suggestion.status === 'suggested' ? (
                        <span className="agt-muted mig-detail">Matches {suggestion.match.name ?? suggestion.match.slug}</span>
                      ) : null}
                    </td>
                    <td className="mono mig-ref">{suggestion.externalRef}</td>
                    <td>
                      <Badge variant={STATUS_TONE[suggestion.status]}>{SUGGESTION_STATUS_LABELS[suggestion.status]}</Badge>
                    </td>
                    <td>
                      {canDecide && suggestion.status === 'suggested' ? (
                        <div className="mig-actions">
                          <Button size="sm" variant="outline" disabled={busyId !== null} onClick={() => onAccept(suggestion)}>
                            <Check aria-hidden />
                            {acceptLabel(suggestion)}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busyId !== null}
                            onClick={() => onDismiss(suggestion)}
                            aria-label={`Dismiss ${suggestion.name}`}
                          >
                            <X aria-hidden />
                            Dismiss
                          </Button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * The report.
 *
 * @param props - See {@link MigrationReportProps}.
 * @returns The report's sections.
 */
export function MigrationReport({ run, canDecide, onChanged }: MigrationReportProps) {
  const [accepting, setAccepting] = React.useState<MigrationSuggestion | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const suggestions = run.suggestions ?? [];
  const teams = suggestions.filter((suggestion) => suggestion.kind === 'team');
  const components = suggestions.filter((suggestion) => suggestion.kind === 'component');
  const unmapped = groupUnmapped(run.unmapped);

  const dismiss = async (suggestion: MigrationSuggestion) => {
    setBusyId(suggestion.id);
    setError(null);
    try {
      await dismissSuggestion(suggestion.id);
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not dismiss the suggestion');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="agt-page" data-testid="migration-report">
      <dl className="agt-facts">
        <div>
          <dt>Source</dt>
          <dd>{MIGRATION_SOURCE_LABELS[run.source]}</dd>
        </div>
        <div>
          <dt>From</dt>
          <dd className="mono">{run.label}</dd>
        </div>
        <div>
          <dt>Found</dt>
          <dd data-testid="migration-counts">{migrationCountsLine(run)}</dd>
        </div>
        <div>
          <dt>Waiting</dt>
          <dd>{run.pending}</dd>
        </div>
      </dl>
      {error ? <Alert variant="danger">{error}</Alert> : null}
      {/* Team suggestions wait for teams and ownership (lib/feature-release.ts); they stay staged. */}
      {isFeatureReleased('teams') ? (
        <SuggestionTable
          title="Teams"
          id="migration-teams"
          suggestions={teams}
          canDecide={canDecide}
          busyId={busyId}
          onAccept={setAccepting}
          onDismiss={(suggestion) => void dismiss(suggestion)}
        />
      ) : null}
      <SuggestionTable
        title="Components"
        id="migration-components"
        suggestions={components}
        canDecide={canDecide}
        busyId={busyId}
        onAccept={setAccepting}
        onDismiss={(suggestion) => void dismiss(suggestion)}
      />
      <section className="agt-section" aria-labelledby="migration-unmapped" data-testid="migration-unmapped">
        <h2 id="migration-unmapped" className="agt-section__title">
          Unmapped fields <span className="mig-count">{run.unmappedTotal}</span>
        </h2>
        {unmapped.length === 0 ? (
          <p className="agt-muted">Every field was mapped.</p>
        ) : (
          <>
            <p className="agt-muted">
              These fields have no Apiome equivalent and were not imported. Values are never stored.
              {run.unmappedTotal > run.unmapped.length
                ? ` Showing the first ${run.unmapped.length} of ${run.unmappedTotal}.`
                : ''}
            </p>
            <div className="agt-table-wrap">
              <table className="agt-table">
                <thead>
                  <tr>
                    <th scope="col">Entity</th>
                    <th scope="col">Field</th>
                    <th scope="col">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {unmapped.flatMap(([entity, fields]) =>
                    fields.map((field, index) => (
                      <tr key={`${entity}-${field.field}-${index}`}>
                        <td className="mono mig-ref">{index === 0 ? entity : ''}</td>
                        <td className="mono mig-ref">{field.field}</td>
                        <td>{field.reason}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      <AcceptDialog
        suggestion={accepting}
        onClose={() => setAccepting(null)}
        onAccepted={() => {
          setAccepting(null);
          onChanged();
        }}
      />
    </div>
  );
}
