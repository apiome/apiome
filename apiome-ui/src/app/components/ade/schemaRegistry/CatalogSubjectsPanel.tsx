'use client';

/**
 * The catalog item's **Subjects** tab — CDG-4.5 (#5977).
 *
 * Shown on Avro, JSON Schema and Protobuf items. Lists the schema-registry subjects the item backs:
 * each subject's versions with their schema ids, its compatibility level (changeable here) and mode,
 * and **Detach**, which deletes the subject but keeps the catalog item, its revisions and the schema
 * ids. **Attach to a subject** backs a new (or empty) subject with this item — its latest revision
 * becomes version 1. Loads only when the tab is active; REST enforces `imports:view` / `imports:edit`
 * / `imports:delete`.
 */

import * as React from 'react';
import Link from 'next/link';
import { Unlink } from 'lucide-react';
import { Alert, Badge, Button, EmptyState, ErrorState, Input, Label, LoadingState } from '@/app/components/ui';
import {
  COMPATIBILITY_LEVELS,
  STRATEGY_LABELS,
  SUBJECT_STRATEGIES,
  subjectLevelLabel,
  subjectNameProblem,
  subjectsForItem,
  type CompatibilityLevel,
  type SchemaSubject,
  type SubjectStrategy,
  type SubjectVersion,
} from '@lib/schema-registry';
import {
  attachSubject,
  detachSubject,
  fetchSubjects,
  fetchSubjectVersions,
  saveSubjectSettings,
} from './schemaRegistryApi';

/** Props for {@link CatalogSubjectsPanel}. */
export interface CatalogSubjectsPanelProps {
  /** The catalog item id. */
  itemId: string;
  /** The item's slug, which the attach form suggests a subject name from. */
  itemSlug?: string | null;
  /** Load only once the tab is shown. */
  active: boolean;
  /** Reports how many subjects the item backs, for the tab's count chip. */
  onCountChange?: (count: number) => void;
}

/** A subject with its versions. */
interface LoadedSubject {
  subject: SchemaSubject;
  versions: SubjectVersion[];
}

/**
 * Read the item's subjects and each one's versions.
 *
 * @param itemId - The catalog item id.
 * @returns The item's subjects, by name.
 */
async function loadSubjects(itemId: string): Promise<LoadedSubject[]> {
  const subjects = subjectsForItem(await fetchSubjects(), itemId);
  return Promise.all(
    subjects.map(async (subject) => ({ subject, versions: await fetchSubjectVersions(subject.name) })),
  );
}

/**
 * The Subjects tab.
 *
 * @param props - See {@link CatalogSubjectsPanelProps}.
 * @returns The pane.
 */
export function CatalogSubjectsPanel({ itemId, itemSlug, active, onCountChange }: CatalogSubjectsPanelProps) {
  const [loaded, setLoaded] = React.useState<LoadedSubject[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [started, setStarted] = React.useState(false);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const next = await loadSubjects(itemId);
      setLoaded(next);
      onCountChange?.(next.length);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the subjects');
    }
  }, [itemId, onCountChange]);

  React.useEffect(() => {
    if (!active || started) return;
    setStarted(true);
    void load();
  }, [active, started, load]);

  if (error && loaded === null) {
    return <ErrorState title="The subjects could not be read" description={error} onRetry={() => void load()} />;
  }
  if (loaded === null) return <LoadingState message="Reading the schema registry…" minHeightClassName="min-h-[8rem]" />;

  return (
    <div className="sr-panel" data-testid="catalog-subjects-panel">
      <p className="sr-note">
        Subjects let Kafka serializers find this schema by name. Each subject version is a revision of this item.{' '}
        <Link className="sr-link" href="/ade/dashboard/schema-registry">
          Schema registry settings
        </Link>
      </p>
      {error ? <Alert variant="error">{error}</Alert> : null}
      {loaded.length === 0 ? (
        <EmptyState
          variant="compact"
          surface={false}
          title="No subjects yet"
          description="Attach this item to a subject below, or run apiome registry register."
        />
      ) : (
        loaded.map((entry) => (
          <SubjectCard key={entry.subject.name} entry={entry} onChanged={() => void load()} onError={setError} />
        ))
      )}
      <AttachForm itemId={itemId} itemSlug={itemSlug ?? null} onAttached={() => void load()} />
    </div>
  );
}

/**
 * One subject: its settings, its versions and Detach.
 *
 * @param props - The subject, and what to do after a change or a failure.
 * @returns The card.
 */
function SubjectCard({
  entry,
  onChanged,
  onError,
}: {
  entry: LoadedSubject;
  onChanged: () => void;
  onError: (message: string | null) => void;
}) {
  const { subject, versions } = entry;
  const [saving, setSaving] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const levelId = `sr-level-${subject.name}`;

  const changeLevel = async (level: CompatibilityLevel) => {
    setSaving(true);
    onError(null);
    try {
      await saveSubjectSettings(subject.name, { compatibilityLevel: level });
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : 'Could not save the subject');
    } finally {
      setSaving(false);
    }
  };

  const detach = async () => {
    setSaving(true);
    onError(null);
    try {
      await detachSubject(subject.name);
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : 'Could not detach the subject');
      setSaving(false);
      setConfirming(false);
    }
  };

  return (
    <section className="sr-card" aria-labelledby={`${levelId}-title`} data-testid={`catalog-subject-${subject.name}`}>
      <header className="sr-card__head">
        <h3 id={`${levelId}-title`} className="sr-card__title mono">
          {subject.name}
        </h3>
        <Badge variant="neutral">{subject.mode}</Badge>
        {subject.strategy ? <Badge variant="neutral" square>{subject.strategy}</Badge> : null}
      </header>
      <div className="sr-card__row">
        <Label htmlFor={levelId}>Compatibility</Label>
        <select
          id={levelId}
          className="sr-select"
          value={subject.compatibilityLevel ?? ''}
          disabled={saving}
          data-testid={`catalog-subject-level-${subject.name}`}
          onChange={(event) => void changeLevel(event.target.value as CompatibilityLevel)}
        >
          {subject.compatibilityLevel ? null : <option value="">{subjectLevelLabel(subject)}</option>}
          {COMPATIBILITY_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        {confirming ? (
          <span className="sr-confirm" role="group" aria-label={`Detach ${subject.name}`}>
            <span className="sr-note">Detach {subject.name}? Its schema ids keep resolving.</span>
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={saving}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => void detach()}
              disabled={saving}
              data-testid={`catalog-subject-detach-confirm-${subject.name}`}
            >
              Detach
            </Button>
          </span>
        ) : (
          <Button
            size="sm"
            variant="danger-soft"
            className="sr-card__detach"
            onClick={() => setConfirming(true)}
            data-testid={`catalog-subject-detach-${subject.name}`}
          >
            <Unlink aria-hidden />
            Detach
          </Button>
        )}
      </div>
      {versions.length === 0 ? (
        <p className="sr-note">No versions.</p>
      ) : (
        <div className="sr-table-wrap">
          <table className="sr-table" data-testid={`catalog-subject-versions-${subject.name}`}>
            <caption className="sr-only">Versions of {subject.name}</caption>
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Schema ID</th>
                <th scope="col">Type</th>
                <th scope="col">Registered</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.version}>
                  <td className="sr-num">{version.version}</td>
                  <td className="sr-num mono">{version.id}</td>
                  <td>{version.schemaType}</td>
                  <td>{new Date(version.createdAt).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * Attach this item to a subject.
 *
 * @param props - The item, and what to do once attached.
 * @returns The form.
 */
function AttachForm({
  itemId,
  itemSlug,
  onAttached,
}: {
  itemId: string;
  itemSlug: string | null;
  onAttached: () => void;
}) {
  const [name, setName] = React.useState(itemSlug ? `${itemSlug}-value` : '');
  const [strategy, setStrategy] = React.useState<SubjectStrategy>('topic');
  const [touched, setTouched] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const problem = subjectNameProblem(name);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem) return;
    setSaving(true);
    setError(null);
    try {
      await attachSubject(name, itemId, strategy);
      onAttached();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not attach the catalog item');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="sr-card sr-attach" onSubmit={(event) => void submit(event)} data-testid="catalog-subject-attach">
      <h3 className="sr-card__title">Attach to a subject</h3>
      <p className="sr-note">The item&apos;s latest revision becomes version 1. The subject must have no versions yet.</p>
      <div className="sr-attach__fields">
        <div className="sr-field">
          <Label htmlFor="sr-attach-name">Subject name</Label>
          <Input
            id="sr-attach-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={touched && problem ? true : undefined}
            aria-describedby={touched && problem ? 'sr-attach-name-problem' : undefined}
            data-testid="catalog-subject-attach-name"
          />
          {touched && problem ? (
            <p id="sr-attach-name-problem" className="sr-problem">
              {problem}
            </p>
          ) : null}
        </div>
        <div className="sr-field">
          <Label htmlFor="sr-attach-strategy">Naming strategy</Label>
          <select
            id="sr-attach-strategy"
            className="sr-select"
            value={strategy}
            onChange={(event) => setStrategy(event.target.value as SubjectStrategy)}
            data-testid="catalog-subject-attach-strategy"
          >
            {SUBJECT_STRATEGIES.map((value) => (
              <option key={value} value={value}>
                {STRATEGY_LABELS[value]}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={saving} data-testid="catalog-subject-attach-submit">
          {saving ? 'Attaching…' : 'Attach'}
        </Button>
      </div>
      {error ? <Alert variant="error">{error}</Alert> : null}
    </form>
  );
}
