'use client';

/**
 * Workspace → Schema registry — `/ade/dashboard/schema-registry` (CDG-4.5, #5977).
 *
 * Three sections:
 *
 * - **Settings** — the workspace's default compatibility level (for subjects that set none) and
 *   mode (`READONLY` refuses every new version), saved together with **Save changes**
 *   (`imports:edit`, enforced by REST).
 * - **Connect a serializer** — the Confluent-compatible URL of this workspace, which API key to
 *   create, and copy-paste configuration for Python (`confluent-kafka`), Java
 *   (`kafka-avro-serializer`) and Spring Kafka. A key is never printed; the snippets say `<api-key>`.
 * - **Subjects** — every live subject with its versions, level, mode and the catalog item it lives
 *   in (which opens that item's Subjects tab).
 */

import * as React from 'react';
import Link from 'next/link';
import { Copy, RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert, Button, EmptyState, GatedState, Label, LoadingState } from '@/app/components/ui';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { toast } from '@/app/components/ui/toast';
import { useAuthSession } from '@lib/auth/session-client';
import {
  COMPATIBILITY_LEVELS,
  REGISTRY_MODES,
  serializerSnippets,
  subjectLevelLabel,
  type CompatibilityLevel,
  type RegistryConfig,
  type RegistryMode,
  type SchemaSubject,
  type SerializerSnippet,
} from '@lib/schema-registry';
import {
  fetchRegistryConfig,
  fetchSubjects,
  saveRegistryConfig,
} from '@/app/components/ade/schemaRegistry/schemaRegistryApi';

const HOME_ROUTE = '/ade/dashboard';

/** What each mode does, for the mode select. */
const MODE_LABELS: Readonly<Record<RegistryMode, string>> = {
  READWRITE: 'READWRITE — accept new versions',
  READONLY: 'READONLY — refuse every new version',
};

/**
 * Copy text to the clipboard and say so.
 *
 * @param text - What to copy.
 * @param what - What it is, for the toast.
 */
async function copyText(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.error(`Could not copy the ${what.toLowerCase()} — select it and copy it yourself.`);
  }
}

/**
 * The Schema registry page.
 *
 * @returns The page.
 */
export default function SchemaRegistryClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [config, setConfig] = React.useState<RegistryConfig | null>(null);
  const [subjects, setSubjects] = React.useState<SchemaSubject[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const [nextConfig, nextSubjects] = await Promise.all([fetchRegistryConfig(), fetchSubjects()]);
      setConfig(nextConfig);
      setSubjects(nextSubjects);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the schema registry');
    }
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Workspace' }, { label: 'Schema registry' }]}
        title="Schema registry"
        description="Defaults for schema subjects, and how Kafka serializers connect."
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="The schema registry belongs to one workspace." />
        ) : error && !config ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The schema registry could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !config || !subjects ? (
          <LoadingState message="Reading the schema registry…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <div className="sr-page" data-testid="schema-registry-page">
            <RegistrySettingsForm config={config} onSaved={setConfig} />
            <ConnectSection registryUrl={config.registryUrl ?? ''} />
            <SubjectsTable subjects={subjects} />
          </div>
        )}
      </PageBody>
    </Page>
  );
}

/**
 * The workspace's default level and mode.
 *
 * @param props - The current config, and what to do with the saved one.
 * @returns The form.
 */
function RegistrySettingsForm({ config, onSaved }: { config: RegistryConfig; onSaved: (next: RegistryConfig) => void }) {
  const [level, setLevel] = React.useState<CompatibilityLevel>(config.compatibilityLevel);
  const [mode, setMode] = React.useState<RegistryMode>(config.mode);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const dirty = level !== config.compatibilityLevel || mode !== config.mode;

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const next = await saveRegistryConfig({ compatibilityLevel: level, mode });
      onSaved({ ...config, ...next });
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the registry settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="sr-section" aria-labelledby="sr-settings" data-testid="registry-settings">
      <h2 id="sr-settings" className="sr-section__title">
        Settings
      </h2>
      <div className="sr-field">
        <Label htmlFor="sr-default-level">Default compatibility level</Label>
        <select
          id="sr-default-level"
          className="sr-select"
          value={level}
          disabled={saving}
          data-testid="registry-default-level"
          onChange={(event) => {
            setLevel(event.target.value as CompatibilityLevel);
            setSaved(false);
          }}
        >
          {COMPATIBILITY_LEVELS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <p className="sr-note">
          Used by every subject that sets no level of its own. Until compatibility rules ship, a new version under any
          level except NONE is refused (error 42290).
        </p>
      </div>
      <div className="sr-field">
        <Label htmlFor="sr-mode">Mode</Label>
        <select
          id="sr-mode"
          className="sr-select"
          value={mode}
          disabled={saving}
          data-testid="registry-mode"
          onChange={(event) => {
            setMode(event.target.value as RegistryMode);
            setSaved(false);
          }}
        >
          {REGISTRY_MODES.map((value) => (
            <option key={value} value={value}>
              {MODE_LABELS[value]}
            </option>
          ))}
        </select>
      </div>
      {error ? <Alert variant="error">{error}</Alert> : null}
      <div className="sr-actions">
        <Button onClick={() => void save()} disabled={!dirty || saving} data-testid="registry-settings-save">
          {saving ? 'Saving…' : 'Save changes'}
        </Button>
        {saved ? (
          <span className="sr-note" role="status">
            Saved.
          </span>
        ) : null}
      </div>
    </section>
  );
}

/**
 * The URL, the key to create and the serializer snippets.
 *
 * @param props - The workspace's Confluent-compatible URL.
 * @returns The section.
 */
function ConnectSection({ registryUrl }: { registryUrl: string }) {
  const snippets = React.useMemo(() => serializerSnippets(registryUrl), [registryUrl]);
  const [chosen, setChosen] = React.useState<SerializerSnippet['id']>('python');
  const snippet = snippets.find((entry) => entry.id === chosen) ?? snippets[0];

  return (
    <section className="sr-section" aria-labelledby="sr-connect" data-testid="registry-connect">
      <h2 id="sr-connect" className="sr-section__title">
        Connect a serializer
      </h2>
      <div className="sr-field">
        <span className="sr-label">Registry URL</span>
        <div className="sr-url">
          <code className="sr-code-inline mono" data-testid="registry-url">
            {registryUrl}
          </code>
          <Button size="sm" variant="ghost" onClick={() => void copyText(registryUrl, 'Registry URL')}>
            <Copy aria-hidden />
            Copy URL
          </Button>
        </div>
      </div>
      <p className="sr-note" data-testid="registry-scope-hint">
        Create a key under{' '}
        <Link className="sr-link" href="/ade/dashboard/api-keys">
          Workspace → API keys
        </Link>{' '}
        with the <strong>Schema registry: read + write</strong> preset for a producer (scopes registry:read and
        registry:write), or <strong>Schema registry: read</strong> for a consumer. Send it as the basic-auth password;
        the user name can be anything.
      </p>
      <Segmented
        value={chosen}
        onValueChange={(value) => setChosen(value as SerializerSnippet['id'])}
        aria-label="Serializer"
        size="sm"
      >
        {snippets.map((entry) => (
          <SegmentedItem key={entry.id} value={entry.id} data-testid={`registry-snippet-tab-${entry.id}`}>
            {entry.label}
          </SegmentedItem>
        ))}
      </Segmented>
      <figure className="sr-snippet">
        <figcaption className="sr-snippet__caption">
          <span>{snippet.caption}</span>
          <Button size="sm" variant="ghost" onClick={() => void copyText(snippet.code, `${snippet.label} snippet`)}>
            <Copy aria-hidden />
            Copy
          </Button>
        </figcaption>
        <pre className="sr-snippet__code mono" data-testid="registry-snippet">
          <code>{snippet.code}</code>
        </pre>
      </figure>
    </section>
  );
}

/**
 * Every live subject.
 *
 * @param props - The subjects.
 * @returns The section.
 */
function SubjectsTable({ subjects }: { subjects: readonly SchemaSubject[] }) {
  return (
    <section className="sr-section" aria-labelledby="sr-subjects" data-testid="registry-subjects">
      <h2 id="sr-subjects" className="sr-section__title">
        Subjects
      </h2>
      {subjects.length === 0 ? (
        <EmptyState
          variant="compact"
          surface={false}
          title="No subjects yet"
          description="Attach a schema item on its Subjects tab, or run apiome registry register."
        />
      ) : (
        <div className="sr-table-wrap">
          <table className="sr-table" data-testid="registry-subjects-table">
            <caption className="sr-only">Schema subjects in this workspace</caption>
            <thead>
              <tr>
                <th scope="col">Subject</th>
                <th scope="col">Versions</th>
                <th scope="col">Latest</th>
                <th scope="col">Compatibility</th>
                <th scope="col">Mode</th>
                <th scope="col">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {subjects.map((subject) => (
                <tr key={subject.name} data-testid={`registry-subject-row-${subject.name}`}>
                  <td>
                    {subject.projectId ? (
                      <Link
                        className="sr-name mono"
                        href={`/ade/dashboard/catalog/${encodeURIComponent(subject.projectId)}?tab=subjects`}
                      >
                        {subject.name}
                      </Link>
                    ) : (
                      <span className="sr-name mono">{subject.name}</span>
                    )}
                  </td>
                  <td className="sr-num">{subject.versionCount}</td>
                  <td className="sr-num">{subject.latestVersion ?? '—'}</td>
                  <td>{subjectLevelLabel(subject)}</td>
                  <td>{subject.mode}</td>
                  <td>{subject.strategy ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
