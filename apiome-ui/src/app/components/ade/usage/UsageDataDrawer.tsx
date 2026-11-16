'use client';

import * as React from 'react';
import { Download } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/app/components/ui/Drawer';
import { CONTROL_FIELD_CLASS, Input } from '@/app/components/ui/Input';
import { fieldSizeVariants } from '@/app/components/ui/controlSize';
import { cn } from '@lib/utils';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';
import { Switch } from '@/app/components/ui/Switch';

import {
  fetchRetention,
  fetchUsageSources,
  saveRetention,
  updateToolsetBodySamples,
  updateUsageSource,
} from './usageDataApi';
import {
  DEFAULT_EXPORT_DAYS,
  EMPTY_BODY_SAMPLE_DRAFT,
  EXPORT_FORMATS,
  MAX_EXPORT_DAYS,
  SOURCE_KIND_LABEL,
  bodySampleLine,
  bodySampleProblem,
  bodySampleWindow,
  daysLabel,
  exportHref,
  percentLabel,
  retentionProblem,
  retentionValue,
  type BodySampleDraft,
  type BodySampleWindow,
  type BodySamples,
  type ExportFormat,
  type UsageRetention,
  type UsageSourceList,
} from './usageDataModel';

/**
 * The project's usage data: what is kept, for how long, and how to take it out — RDG-5.4 (#5789).
 *
 * Four sections, top to bottom:
 *
 * 1. **Export** — download the project's daily usage rollups as CSV or JSON.
 * 2. **Retention** — the workspace's tier caps, and lower values the purge applies instead.
 * 3. **Sources** — each traffic source's head sampling, field capture and body samples.
 * 4. **Agent toolsets** — each toolset's AGX-3.3 body capture, in the same words as a source's
 *    body samples.
 *
 * Opening a body-sample window takes the acknowledgement sentence REST sends, as a checkbox. The
 * drawer re-reads after every write, so it never shows a stale setting. Controls the viewer may
 * not use stay visible but disabled, with the reason as their title.
 */

/** Props for {@link UsageDataDrawer}. */
export interface UsageDataDrawerProps {
  /** Whether the drawer is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The project slug or id. */
  projectRef: string;
  /** Whether the viewer holds a permission such as `projects:edit`. */
  can: (permission: string) => boolean;
}

/** What the drawer reads when it opens. */
interface DrawerData {
  retention: UsageRetention | null;
  sources: UsageSourceList | null;
}

/** Props for {@link BodySampleForm}. */
interface BodySampleFormProps {
  /** The opt-in being opened (its caps). */
  samples: BodySamples;
  /** The sentence to acknowledge. */
  acknowledgement: string;
  /** Id prefix for the form's fields. */
  idPrefix: string;
  /** Whether a write is in flight. */
  busy: boolean;
  /** Submit the window. */
  onSubmit: (window: BodySampleWindow) => void;
  /** Give up. */
  onCancel: () => void;
}

/**
 * The form that opens a body-sample window: a rate, a number of days, and the acknowledgement.
 *
 * @param props See {@link BodySampleFormProps}.
 * @returns The form.
 */
function BodySampleForm({ samples, acknowledgement, idPrefix, busy, onSubmit, onCancel }: BodySampleFormProps) {
  const [draft, setDraft] = React.useState<BodySampleDraft>(EMPTY_BODY_SAMPLE_DRAFT);
  const problem = bodySampleProblem(draft, samples);
  return (
    <form
      className="usg-sample-form"
      data-testid={`${idPrefix}-form`}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!problem) onSubmit(bodySampleWindow(draft, acknowledgement));
      }}
    >
      <div className="usg-sample-form__fields">
        <div className="cns-form__field">
          <Label htmlFor={`${idPrefix}-rate`}>Rate (%)</Label>
          <Input
            id={`${idPrefix}-rate`}
            inputMode="decimal"
            value={draft.percent}
            onChange={(event) => setDraft({ ...draft, percent: event.target.value })}
          />
          <p className="cns-form__hint">At most {percentLabel(samples.maxRate)}.</p>
        </div>
        <div className="cns-form__field">
          <Label htmlFor={`${idPrefix}-days`}>Stop after (days)</Label>
          <Input
            id={`${idPrefix}-days`}
            inputMode="numeric"
            value={draft.days}
            onChange={(event) => setDraft({ ...draft, days: event.target.value })}
          />
          <p className="cns-form__hint">At most {samples.maxWindowDays} days.</p>
        </div>
      </div>
      <label className="usg-ack" htmlFor={`${idPrefix}-ack`}>
        <Checkbox
          id={`${idPrefix}-ack`}
          checked={draft.acknowledged}
          onCheckedChange={(checked) => setDraft({ ...draft, acknowledged: checked === true })}
        />
        <span>{acknowledgement}</span>
      </label>
      <div className="usg-actions">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={busy || problem !== null} title={problem ?? undefined}>
          {busy && <Spinner aria-hidden="true" />}
          Start sampling
        </Button>
      </div>
    </form>
  );
}

/**
 * The usage-data drawer.
 *
 * @param props See {@link UsageDataDrawerProps}.
 * @returns The drawer.
 */
export default function UsageDataDrawer({ open, onOpenChange, projectRef, can }: UsageDataDrawerProps) {
  const [data, setData] = React.useState<DrawerData>({ retention: null, sources: null });
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState<string | null>(null);
  const [format, setFormat] = React.useState<ExportFormat>('csv');
  const [days, setDays] = React.useState(String(DEFAULT_EXPORT_DAYS));
  const [hourly, setHourly] = React.useState('');
  const [rollup, setRollup] = React.useState('');
  const [opening, setOpening] = React.useState<string | null>(null);

  const reload = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [retention, sources] = await Promise.all([fetchRetention(), fetchUsageSources(projectRef)]);
      setData({ retention, sources });
      setHourly(retention.setting.hourlyDays === null ? '' : String(retention.setting.hourlyDays));
      setRollup(retention.setting.rollupDays === null ? '' : String(retention.setting.rollupDays));
    } catch (caught) {
      setError(caught instanceof Error && caught.message ? caught.message : "Couldn't read this project's usage data");
    } finally {
      setLoading(false);
    }
  }, [projectRef]);

  React.useEffect(() => {
    if (!open) return;
    setOpening(null);
    void reload();
  }, [open, reload]);

  /** Run one write, then re-read. */
  const write = async (key: string, run: () => Promise<unknown>) => {
    setBusy(key);
    setError('');
    try {
      await run();
      setOpening(null);
      await reload();
    } catch (caught) {
      setError(caught instanceof Error && caught.message ? caught.message : 'The change was not saved');
    } finally {
      setBusy(null);
    }
  };

  const { retention, sources } = data;
  const canEditSources = can('projects:edit');
  const canEditRetention = can('members:edit');
  const canEditToolsets = can('api_keys:edit');
  const canExport = can('versions:view');
  const hourlyProblem = retentionProblem(hourly, retention?.caps.hourlyDays ?? null, 'Hourly retention');
  const rollupProblem = retentionProblem(rollup, retention?.caps.rollupDays ?? null, 'Rollup retention');
  const retentionBlocked = !canEditRetention
    ? 'Only an Owner or Admin can change retention.'
    : (hourlyProblem ?? rollupProblem);
  const exportDays = Number(days);
  const exportProblem = !canExport
    ? 'You need versions:view to export usage.'
    : !Number.isInteger(exportDays) || exportDays < 1 || exportDays > MAX_EXPORT_DAYS
      ? `Enter 1 to ${MAX_EXPORT_DAYS} days.`
      : null;

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent size="lg" data-testid="usage-data-drawer">
        <DrawerHeader>
          <DrawerTitle>Usage data</DrawerTitle>
          <DrawerDescription>
            What this project&apos;s usage index keeps, for how long, and how to take it out.
          </DrawerDescription>
        </DrawerHeader>

        <DrawerBody>
          {error && <Alert variant="danger">{error}</Alert>}
          {loading && !retention && <Spinner aria-label="Loading usage data" />}

          <section className="cns-drawer__section" data-testid="usage-export">
            <h3 className="cns-drawer__heading">Export</h3>
            <p className="cns-drawer__empty">
              The daily rollups: calls, errors, latency and bytes per day, operation, status and consumer. A
              consumer shows by its slug, or <code className="mono">anonymous</code>.
            </p>
            <div className="usg-row">
              <div className="cns-form__field">
                <Label htmlFor="usage-export-format">Format</Label>
                <select
                  id="usage-export-format"
                  className={cn(CONTROL_FIELD_CLASS, fieldSizeVariants({ size: 'md' }))}
                  value={format}
                  onChange={(event) => setFormat(event.target.value as ExportFormat)}
                >
                  {EXPORT_FORMATS.map((value) => (
                    <option key={value} value={value}>
                      {value.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
              <div className="cns-form__field">
                <Label htmlFor="usage-export-days">Last (days)</Label>
                <Input
                  id="usage-export-days"
                  inputMode="numeric"
                  value={days}
                  onChange={(event) => setDays(event.target.value)}
                />
              </div>
              {exportProblem ? (
                <Button variant="secondary" disabled title={exportProblem}>
                  <Download aria-hidden="true" />
                  Download export
                </Button>
              ) : (
                <Button variant="secondary" asChild>
                  <a href={exportHref(projectRef, format, exportDays)} download data-testid="usage-export-link">
                    <Download aria-hidden="true" />
                    Download export
                  </a>
                </Button>
              )}
            </div>
          </section>

          <section className="cns-drawer__section" data-testid="usage-retention">
            <h3 className="cns-drawer__heading">Retention</h3>
            {retention && (
              <>
                <p className="cns-drawer__empty">
                  Your tier keeps hourly counters for {daysLabel(retention.caps.hourlyDays)} and daily rollups for{' '}
                  {daysLabel(retention.caps.rollupDays)}. You can keep less. The nightly purge deletes what is
                  past retention. Body samples are deleted after {retention.sampleRetentionDays} days whatever
                  the tier.
                </p>
                <form
                  className="usg-row"
                  noValidate
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (retentionBlocked) return;
                    void write('retention', () =>
                      saveRetention({ hourlyDays: retentionValue(hourly), rollupDays: retentionValue(rollup) }),
                    );
                  }}
                >
                  <div className="cns-form__field">
                    <Label htmlFor="usage-retention-hourly">Hourly counters (days)</Label>
                    <Input
                      id="usage-retention-hourly"
                      inputMode="numeric"
                      placeholder={daysLabel(retention.caps.hourlyDays)}
                      value={hourly}
                      disabled={!canEditRetention}
                      aria-invalid={hourlyProblem ? true : undefined}
                      onChange={(event) => setHourly(event.target.value)}
                    />
                    <p className="cns-form__hint">Applies: {daysLabel(retention.effective.hourlyDays)}</p>
                  </div>
                  <div className="cns-form__field">
                    <Label htmlFor="usage-retention-rollup">Daily rollups (days)</Label>
                    <Input
                      id="usage-retention-rollup"
                      inputMode="numeric"
                      placeholder={daysLabel(retention.caps.rollupDays)}
                      value={rollup}
                      disabled={!canEditRetention}
                      aria-invalid={rollupProblem ? true : undefined}
                      onChange={(event) => setRollup(event.target.value)}
                    />
                    <p className="cns-form__hint">Applies: {daysLabel(retention.effective.rollupDays)}</p>
                  </div>
                  <Button
                    type="submit"
                    variant="secondary"
                    disabled={busy !== null || retentionBlocked !== null}
                    title={retentionBlocked ?? undefined}
                  >
                    {busy === 'retention' && <Spinner aria-hidden="true" />}
                    Save retention
                  </Button>
                </form>
                {(hourlyProblem || rollupProblem) && (
                  <p className="usg-problem" role="alert">
                    {hourlyProblem ?? rollupProblem}
                  </p>
                )}
              </>
            )}
          </section>

          <section className="cns-drawer__section" data-testid="usage-sources">
            <h3 className="cns-drawer__heading">Sources</h3>
            {sources && sources.sources.length === 0 && (
              <p className="cns-drawer__empty">No traffic source feeds this project yet.</p>
            )}
            {sources && sources.sources.length > 0 && (
              <ul className="usg-list">
                {sources.sources.map((source) => {
                  const key = `source-${source.id}`;
                  return (
                    <li className="usg-item" key={source.id} data-testid={key}>
                      <div className="usg-item__head">
                        <span className="usg-item__name">
                          {SOURCE_KIND_LABEL[source.kind] ?? source.kind}
                          <Badge variant="secondary">{source.environment}</Badge>
                          {!source.enabled && <Badge variant="secondary">Disabled</Badge>}
                        </span>
                        <span className="usg-item__meta">Head sampling {percentLabel(source.samplingRate)}</span>
                      </div>
                      <div className="usg-item__row">
                        <label className="usg-toggle" htmlFor={`${key}-fields`}>
                          <Switch
                            id={`${key}-fields`}
                            checked={source.fieldCapture}
                            disabled={!canEditSources || busy !== null}
                            title={canEditSources ? undefined : 'You need projects:edit to change capture.'}
                            onCheckedChange={(checked) =>
                              void write(key, () => updateUsageSource(projectRef, source.id, { fieldCapture: checked }))
                            }
                          />
                          <span>Count field names (never values)</span>
                        </label>
                      </div>
                      <BodySampleRow
                        id={key}
                        label="Body samples"
                        samples={source.bodySamples}
                        acknowledgement={sources.acknowledgement}
                        allowed={canEditSources}
                        deniedReason="You need projects:edit to sample bodies."
                        opening={opening === key}
                        busy={busy}
                        onOpen={() => setOpening(key)}
                        onCancel={() => setOpening(null)}
                        onSubmit={(window) =>
                          void write(key, () => updateUsageSource(projectRef, source.id, { bodySamples: window }))
                        }
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="cns-drawer__section" data-testid="usage-toolsets">
            <h3 className="cns-drawer__heading">Agent toolsets</h3>
            {sources && sources.agentToolsets.length === 0 && (
              <p className="cns-drawer__empty">No version of this project has an agent toolset.</p>
            )}
            {sources && sources.agentToolsets.length > 0 && (
              <ul className="usg-list">
                {sources.agentToolsets.map((toolset) => {
                  const key = `toolset-${toolset.id}`;
                  return (
                    <li className="usg-item" key={toolset.id} data-testid={key}>
                      <div className="usg-item__head">
                        <span className="usg-item__name">
                          Version {toolset.versionLabel ?? toolset.versionId}
                          {!toolset.enabled && <Badge variant="secondary">Disabled</Badge>}
                        </span>
                      </div>
                      <BodySampleRow
                        id={key}
                        label="Body samples"
                        samples={toolset.bodySamples}
                        acknowledgement={sources.acknowledgement}
                        allowed={canEditToolsets}
                        deniedReason="You need api_keys:edit to sample agent calls."
                        opening={opening === key}
                        busy={busy}
                        onOpen={() => setOpening(key)}
                        onCancel={() => setOpening(null)}
                        onSubmit={(window) => void write(key, () => updateToolsetBodySamples(toolset.id, window))}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}

/** Props for {@link BodySampleRow}. */
interface BodySampleRowProps {
  id: string;
  label: string;
  samples: BodySamples;
  acknowledgement: string;
  allowed: boolean;
  deniedReason: string;
  opening: boolean;
  busy: string | null;
  onOpen: () => void;
  onCancel: () => void;
  onSubmit: (window: BodySampleWindow) => void;
}

/**
 * One body-sample opt-in: its state, and **Stop sampling** or **Sample bodies…**.
 *
 * @param props See {@link BodySampleRowProps}.
 * @returns The row, with the opening form under it while open.
 */
function BodySampleRow({
  id,
  label,
  samples,
  acknowledgement,
  allowed,
  deniedReason,
  opening,
  busy,
  onOpen,
  onCancel,
  onSubmit,
}: BodySampleRowProps) {
  return (
    <>
      <div className="usg-item__row">
        <span className="usg-item__meta">
          {label}: <strong>{bodySampleLine(samples)}</strong> · at most {percentLabel(samples.maxRate)} for{' '}
          {samples.maxWindowDays} days
        </span>
        {samples.open ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={!allowed || busy !== null}
            title={allowed ? undefined : deniedReason}
            onClick={() => onSubmit({ rate: 0 })}
          >
            {busy === id && <Spinner aria-hidden="true" />}
            Stop sampling
          </Button>
        ) : (
          !opening && (
            <Button
              variant="secondary"
              size="sm"
              disabled={!allowed || busy !== null}
              title={allowed ? undefined : deniedReason}
              onClick={onOpen}
            >
              Sample bodies…
            </Button>
          )
        )}
      </div>
      {opening && (
        <BodySampleForm
          samples={samples}
          acknowledgement={acknowledgement}
          idPrefix={id}
          busy={busy === id}
          onSubmit={onSubmit}
          onCancel={onCancel}
        />
      )}
    </>
  );
}
