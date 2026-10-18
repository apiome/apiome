'use client';

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { DataTableFilterChip } from '@/app/components/ui/DataTable';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { Textarea } from '@/app/components/ui/Textarea';
import { toast } from '@/app/components/ui/toast';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { useAuthSession } from '@lib/auth/session-client';
import {
  SHADOW_SECTIONS,
  confidencePercent,
  emptySectionCopy,
  environmentsOf,
  servedAt,
  tierLabel,
  type ShadowItem,
  type ShadowMatch,
  type ShadowSectionKey,
  type ShadowUndeployed,
} from '@lib/shadow-report';
import { useShadowReport } from '@/app/hooks/useShadowReport';

/**
 * Govern → Shadow APIs — `/ade/dashboard/connectors/shadow` (CDG-1.6, #5957).
 *
 * What connected gateways serve, against what the catalog describes. The chips pick one section of
 * the report (Shadow, Possible matches, Drift, Undeployed, Ignored); the selects narrow it to one
 * connector or environment, and the connector filter is read from `?connector=`, which is where a
 * `shadow_api_detected` notification links.
 *
 * Nothing on this page links an API by itself. A possible match is a suggestion with its tier and
 * confidence; "Link to item" opens a dialog in which a person confirms which catalog item it is.
 * "Ignore" asks for a reason, which the report keeps. "Import" imports that one API now.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';
/** The select value meaning "no filter" (a Radix select item cannot have an empty value). */
const ALL = '__all__';

/**
 * The page of a catalog item or Project.
 *
 * @param target - The project id and whether it is a Project or a catalog item.
 */
function itemHref(target: { projectId: string; kind: string }): string {
  return target.kind === 'project'
    ? `/ade/dashboard/projects/${encodeURIComponent(target.projectId)}`
    : `/ade/dashboard/catalog/${encodeURIComponent(target.projectId)}`;
}

/**
 * The shadow-API report page.
 *
 * @param props.initialConnector - The connector filter to start with (tests; the page reads `?connector=`).
 * @returns The page.
 */
export default function ShadowApisClient({ initialConnector }: { initialConnector?: string | null }) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;

  const [connector, setConnector] = React.useState<string | null>(() => {
    if (initialConnector !== undefined) return initialConnector;
    if (typeof window === 'undefined') return null;
    return new URLSearchParams(window.location.search).get('connector');
  });
  const [environment, setEnvironment] = React.useState<string | null>(null);
  const [section, setSection] = React.useState<ShadowSectionKey>('shadow');
  const [busy, setBusy] = React.useState<string | null>(null);
  const [ignoring, setIgnoring] = React.useState<ShadowItem | null>(null);
  const [linking, setLinking] = React.useState<ShadowItem | null>(null);

  const { report, loading, error, refresh, act } = useShadowReport(
    { connector, environment },
    Boolean(tenantId)
  );

  const environments = React.useMemo(() => environmentsOf(report), [report]);
  const staleCount = report?.stale.length ?? 0;
  const current = SHADOW_SECTIONS.find((candidate) => candidate.key === section) ?? SHADOW_SECTIONS[0];

  const runImport = React.useCallback(
    async (item: ShadowItem) => {
      setBusy(item.itemId);
      const result = await act(item, 'import');
      setBusy(null);
      if (!result.ok) {
        toast.error(result.error ?? 'The import did not go through. Try again.');
        return;
      }
      const run = result.body as { status?: string; errorMessage?: string | null } | undefined;
      if (run?.status === 'succeeded') toast.success(`${item.name ?? 'The API'} was imported into the catalog.`);
      else toast.error(run?.errorMessage ?? 'The import ran but did not succeed. Open the connector runs for details.');
    },
    [act]
  );

  const runUnignore = React.useCallback(
    async (item: ShadowItem) => {
      setBusy(item.itemId);
      const result = await act(item, 'unignore');
      setBusy(null);
      if (!result.ok) toast.error(result.error ?? 'The API is still ignored. Try again.');
    },
    [act]
  );

  const rows = report ? report[section] : [];

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Shadow APIs' }]}
        title="Shadow APIs"
        description="What your connected gateways serve that the catalog does not describe."
        actions={
          <Button variant="ghost" size="sm" onClick={() => void refresh()} data-testid="shadow-refresh">
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />

      <PageBody>
        <div className="shd-filters" data-testid="shadow-filters">
          <div className="shd-filters__selects">
            <FormField label="Connector" htmlFor="shadow-connector">
              <Select value={connector ?? ALL} onValueChange={(value) => setConnector(value === ALL ? null : value)}>
                <SelectTrigger id="shadow-connector" data-testid="shadow-connector">
                  <SelectValue placeholder="All connectors" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All connectors</SelectItem>
                  {(report?.connectors ?? []).map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.name ?? candidate.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Environment" htmlFor="shadow-environment">
              <Select
                value={environment ?? ALL}
                onValueChange={(value) => setEnvironment(value === ALL ? null : value)}
              >
                <SelectTrigger id="shadow-environment" data-testid="shadow-environment">
                  <SelectValue placeholder="All environments" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All environments</SelectItem>
                  {environments.map((name) => (
                    <SelectItem key={name} value={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <div className="shd-filters__chips" role="group" aria-label="Report section">
            {SHADOW_SECTIONS.map((candidate) => (
              <DataTableFilterChip
                key={candidate.key}
                active={section === candidate.key}
                count={report?.summary[candidate.key] ?? 0}
                onClick={() => setSection(candidate.key)}
                data-testid={`shadow-section-${candidate.key}`}
              >
                {candidate.label}
              </DataTableFilterChip>
            ))}
          </div>
        </div>

        {(report?.stale ?? []).map((stale) => (
          <Alert key={stale.connectorId} variant="warn" data-testid="shadow-stale">
            {stale.message}
          </Alert>
        ))}

        {error ? (
          <Alert
            variant="error"
            data-testid="shadow-error"
            actions={
              <Button variant="ghost" size="sm" onClick={() => void refresh()}>
                Try again
              </Button>
            }
          >
            {error}
          </Alert>
        ) : null}

        {loading && !report ? (
          <p className="shd-note" data-testid="shadow-loading">
            Reading the gateway inventories…
          </p>
        ) : null}

        {report && report.connectors.length === 0 ? (
          <div className="shd-empty" data-testid="shadow-no-connectors">
            <p className="shd-empty__title">Connect a gateway to see what it serves</p>
            <p className="shd-empty__body">
              Register a connector for Kong, AWS API Gateway or Azure API Management, then sync it. Its APIs
              are compared with the catalog here.
            </p>
          </div>
        ) : null}

        {report && report.connectors.length > 0 ? (
          <section className="shd-section" aria-labelledby="shadow-section-title" data-testid={`shadow-rows-${section}`}>
            <h2 id="shadow-section-title" className="shd-section__title">
              {current.label}
            </h2>
            <p className="shd-section__desc">{current.description}</p>
            {rows.length === 0 ? (
              <p className="shd-note" data-testid="shadow-empty">
                {emptySectionCopy(section, staleCount)}
              </p>
            ) : section === 'undeployed' ? (
              <UndeployedTable rows={rows as ShadowUndeployed[]} />
            ) : (
              <ItemTable
                section={section}
                rows={rows as ShadowItem[]}
                busy={busy}
                onImport={runImport}
                onIgnore={setIgnoring}
                onLink={setLinking}
                onUnignore={runUnignore}
              />
            )}
          </section>
        ) : null}
      </PageBody>

      <IgnoreDialog
        item={ignoring}
        onClose={() => setIgnoring(null)}
        onConfirm={async (reason) => {
          if (!ignoring) return null;
          const result = await act(ignoring, 'ignore', { reason });
          if (result.ok) setIgnoring(null);
          return result.ok ? null : (result.error ?? 'The API was not ignored. Try again.');
        }}
      />
      <LinkDialog
        item={linking}
        onClose={() => setLinking(null)}
        onConfirm={async (projectId) => {
          if (!linking) return null;
          const result = await act(linking, 'link', { catalogItemId: projectId });
          if (result.ok) {
            setLinking(null);
            toast.success(`${linking.name ?? 'The API'} is now linked.`);
          }
          return result.ok ? null : (result.error ?? 'The API was not linked. Try again.');
        }}
      />
    </Page>
  );
}

/**
 * A gateway-row section (Shadow, Possible matches, Drift, Ignored) as a table with row actions.
 */
function ItemTable({
  section,
  rows,
  busy,
  onImport,
  onIgnore,
  onLink,
  onUnignore,
}: {
  section: ShadowSectionKey;
  rows: ShadowItem[];
  busy: string | null;
  onImport: (item: ShadowItem) => void;
  onIgnore: (item: ShadowItem) => void;
  onLink: (item: ShadowItem) => void;
  onUnignore: (item: ShadowItem) => void;
}) {
  return (
    <div className="shd-table-wrap">
      <table className="shd-table">
        <thead>
          <tr>
            <th scope="col">API</th>
            <th scope="col">Served at</th>
            {section === 'possibleMatches' ? <th scope="col">Possible match</th> : null}
            {section === 'drift' ? <th scope="col">Revision</th> : null}
            {section === 'ignored' ? <th scope="col">Reason</th> : null}
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.itemId} data-testid={`shadow-row-${item.itemId}`}>
              <td>
                <span className="shd-name">{item.name ?? item.remoteId}</span>
                <span className="shd-meta">
                  {item.connectorName}
                  {item.environment ? ` · ${item.environment}` : ''}
                  {item.stale ? ' · stale' : ''}
                </span>
                {item.ignored?.reappeared ? (
                  <span className="shd-meta" data-testid={`shadow-reappeared-${item.itemId}`}>
                    Ignored before (“{item.ignored.reason}”), now served somewhere else.
                  </span>
                ) : null}
              </td>
              <td className="shd-mono">{servedAt(item)}</td>
              {section === 'possibleMatches' && item.match ? (
                <td>
                  <MatchSummary match={item.match} />
                </td>
              ) : null}
              {section === 'drift' ? (
                <td className="shd-mono">
                  {item.deployedRevision ?? '—'} → catalog {item.catalogRevision ?? item.catalogVersionLabel ?? '—'}
                </td>
              ) : null}
              {section === 'ignored' ? <td>{item.ignored?.reason ?? '—'}</td> : null}
              <td className="shd-actions">
                {section === 'possibleMatches' ? (
                  <Button size="sm" variant="soft" onClick={() => onLink(item)} data-testid={`shadow-link-${item.itemId}`}>
                    Link to item
                  </Button>
                ) : null}
                {section === 'ignored' ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === item.itemId}
                    onClick={() => onUnignore(item)}
                    data-testid={`shadow-unignore-${item.itemId}`}
                  >
                    Stop ignoring
                  </Button>
                ) : (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy === item.itemId}
                      onClick={() => onImport(item)}
                      data-testid={`shadow-import-${item.itemId}`}
                    >
                      {busy === item.itemId ? 'Importing…' : 'Import'}
                    </Button>
                    {section !== 'drift' ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onIgnore(item)}
                        data-testid={`shadow-ignore-${item.itemId}`}
                      >
                        Ignore
                      </Button>
                    ) : null}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The best candidate of a possible match: its item, tier and confidence. */
function MatchSummary({ match }: { match: ShadowMatch }) {
  return (
    <span className="shd-match">
      <Link href={itemHref(match.target)} className="shd-match__name">
        {match.target.name ?? match.target.projectId}
      </Link>
      <Badge variant="accent" data-testid="shadow-match-tier">
        {tierLabel(match.tier)} · {confidencePercent(match.confidence)}
      </Badge>
    </span>
  );
}

/** The Undeployed section: described APIs no connected gateway serves. */
function UndeployedTable({ rows }: { rows: ShadowUndeployed[] }) {
  return (
    <div className="shd-table-wrap">
      <table className="shd-table">
        <thead>
          <tr>
            <th scope="col">API</th>
            <th scope="col">Declared servers</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => (
            <tr key={entry.projectId} data-testid={`shadow-undeployed-${entry.projectId}`}>
              <td>
                <Link href={itemHref(entry)} className="shd-name">
                  {entry.name ?? entry.projectId}
                </Link>
                <span className="shd-meta">
                  {entry.kind === 'project' ? 'Project' : 'Catalog item'}
                  {entry.versionLabel ? ` · ${entry.versionLabel}` : ''}
                </span>
              </td>
              <td className="shd-mono">{entry.servers.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Asks for the reason an API is ignored; the report keeps it. */
function IgnoreDialog({
  item,
  onClose,
  onConfirm,
}: {
  item: ShadowItem | null;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<string | null>;
}) {
  const [reason, setReason] = React.useState('');
  const [problem, setProblem] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setReason('');
    setProblem(null);
  }, [item]);

  const submit = async () => {
    if (!reason.trim()) {
      setProblem('Say why this API is not in the catalog.');
      return;
    }
    setSaving(true);
    setProblem(await onConfirm(reason.trim()));
    setSaving(false);
  };

  return (
    <Dialog open={item !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="sm" data-testid="shadow-ignore-dialog">
        <DialogHeader>
          <DialogTitle>Ignore {item?.name ?? 'this API'}</DialogTitle>
          <DialogDescription>
            It leaves the Shadow list and is never imported. If the gateway later serves it on another host,
            it comes back with your reason beside it.
          </DialogDescription>
        </DialogHeader>
        <FormField label="Reason" htmlFor="shadow-ignore-reason" required error={problem ?? undefined}>
          <Textarea
            id="shadow-ignore-reason"
            value={reason}
            maxLength={1000}
            onChange={(event) => setReason(event.target.value)}
            placeholder="For example: internal health check, not a product API"
            data-testid="shadow-ignore-reason"
          />
        </FormField>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={saving} data-testid="shadow-ignore-confirm">
            {saving ? 'Ignoring…' : 'Ignore API'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Confirms which catalog item a served API is; the only way a row gets linked. */
function LinkDialog({
  item,
  onClose,
  onConfirm,
}: {
  item: ShadowItem | null;
  onClose: () => void;
  onConfirm: (projectId: string) => Promise<string | null>;
}) {
  const candidates = React.useMemo(
    () => (item?.match ? [item.match, ...(item.alternatives ?? [])] : []),
    [item]
  );
  const [chosen, setChosen] = React.useState<string | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setChosen(candidates[0]?.target.projectId ?? null);
    setProblem(null);
  }, [candidates]);

  const submit = async () => {
    if (!chosen) return;
    setSaving(true);
    setProblem(await onConfirm(chosen));
    setSaving(false);
  };

  return (
    <Dialog open={item !== null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent data-testid="shadow-link-dialog">
        <DialogHeader>
          <DialogTitle>Link {item?.name ?? 'this API'} to a catalog item</DialogTitle>
          <DialogDescription>
            Served at {item ? servedAt(item) : ''}. Choose the item it really is; the suggestion is only a guess.
          </DialogDescription>
        </DialogHeader>
        <fieldset className="shd-candidates">
          <legend className="sr-only">Catalog item</legend>
          {candidates.map((candidate) => (
            <label key={candidate.target.projectId} className="shd-candidate">
              <input
                type="radio"
                name="shadow-link-target"
                value={candidate.target.projectId}
                checked={chosen === candidate.target.projectId}
                onChange={() => setChosen(candidate.target.projectId)}
                data-testid={`shadow-link-target-${candidate.target.projectId}`}
              />
              <span className="shd-candidate__body">
                <span className="shd-name">{candidate.target.name ?? candidate.target.projectId}</span>
                <span className="shd-meta">
                  {tierLabel(candidate.tier)} · {confidencePercent(candidate.confidence)} · {candidate.reason}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        {problem ? (
          <Alert variant="error" data-testid="shadow-link-error">
            {problem}
          </Alert>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={saving || !chosen} data-testid="shadow-link-confirm">
            {saving ? 'Linking…' : 'Link to item'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
