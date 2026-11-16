'use client';

import { useCallback, useId, useRef, useState, type ChangeEvent } from 'react';
import { ArrowDown, ArrowUp, Layers, Save, Upload, X } from 'lucide-react';
import { Button } from '../../../ui/Button';
import { Switch } from '../../../ui/Switch';
import {
  OVERLAY_SOURCE_LABEL,
  type VersionOverlayChain,
} from '../../versionOverlays/versionOverlaysApi';
import {
  MAX_EXPORT_OVERLAYS,
  addOverlays,
  moveOverlay,
  overlayActionCount,
  overlayTitle,
  parseOverlayFile,
  type ExportStudioOverlay,
} from './exportOverlays';

/** The revision's stored overlay chain (GVM-4.3), when the Studio exports a specific revision. */
export interface ExportStoredOverlays {
  /** The chain, or null while it loads or when it could not be read. */
  chain: VersionOverlayChain | null;
  /** Why the chain could not be read, if it could not. */
  error: string | null;
  /** Whether the export applies it (before the uploaded overlays). */
  apply: boolean;
  /** Switch applying it on or off. */
  onToggleApply: (apply: boolean) => void;
  /**
   * Save one uploaded overlay into the revision's chain (`source: export-studio`).
   *
   * @returns null on success, or the message to show.
   */
  onSaveToChain: (overlay: ExportStudioOverlay) => Promise<string | null>;
}

interface ExportOverlaysStepProps {
  /** The overlay chain, in application order. */
  overlays: ExportStudioOverlay[];
  /** Replace the chain (add, remove or reorder). */
  onChange: (overlays: ExportStudioOverlay[]) => void;
  /** The revision's stored chain (GVM-4.3); omitted when no specific revision is exported. */
  stored?: ExportStoredOverlays | null;
}

/**
 * The Export Studio's **Overlays** step (GVM-4.2, #5877): upload OpenAPI Overlay files (JSON or
 * YAML) and set the order they apply in. The overlays rewrite the version's OpenAPI document
 * before the export runs, so Verify, the export quality policy and the generated artifact all see
 * the overlaid document. With no overlays the step is a pass-through: the version exports as it is.
 *
 * Files are read in the browser; a file that is not an overlay, does not parse or is over 1 MB is
 * reported here and never sent. Re-uploading a file with the same name replaces it in place.
 *
 * A revision can also carry a **stored** chain (GVM-4.3): it applies first, unless switched off
 * here, and an uploaded overlay can be saved into it so later exports and the publish render use
 * it too. A published revision's chain is read-only.
 *
 * @param props.overlays The chain, in application order.
 * @param props.onChange Called with the new chain.
 * @param props.stored The revision's stored chain, when one revision is exported.
 * @returns The step panel.
 */
export function ExportOverlaysStep({ overlays, onChange, stored }: ExportOverlaysStepProps) {
  const inputId = useId();
  const switchId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [savedNames, setSavedNames] = useState<string[]>([]);
  const storedCount = stored?.apply && stored.chain ? stored.chain.overlays.length : 0;
  const full = overlays.length + storedCount >= MAX_EXPORT_OVERLAYS;
  const canSaveToChain = !!stored?.chain && !stored.chain.published;

  const saveToChain = useCallback(
    async (overlay: ExportStudioOverlay) => {
      if (!stored) return;
      setSaving(overlay.name);
      const failure = await stored.onSaveToChain(overlay);
      setSaving(null);
      if (failure) {
        setErrors([`${overlay.name}: ${failure}`]);
        return;
      }
      setErrors([]);
      setSavedNames((names) => [...names, overlay.name]);
    },
    [stored],
  );

  const handleFiles = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      // Reset the input so choosing the same file again (after editing it) fires a change.
      event.target.value = '';
      if (files.length === 0) return;
      const read = await Promise.all(
        files.map(async (file) => parseOverlayFile(file.name, await file.text(), file.size)),
      );
      const problems = read.flatMap((result) => (result.ok ? [] : [result.error]));
      const added = read.flatMap((result) => (result.ok ? [result.overlay] : []));
      const { chain, dropped } = addOverlays(overlays, added);
      if (dropped > 0) {
        problems.push(
          `${dropped} ${dropped === 1 ? 'file was' : 'files were'} left out: an export applies at most ${MAX_EXPORT_OVERLAYS} overlays.`,
        );
      }
      setErrors(problems);
      if (added.length > 0) onChange(chain);
    },
    [overlays, onChange],
  );

  return (
    <div className="xstd-stack" data-testid="export-studio-overlays">
      <div className="xstd-caps">
        <Layers aria-hidden />
        Overlays
      </div>
      <div className="xstd-rule" />
      <p className="hive-quiet">
        An overlay changes the exported document without changing the version — for example a
        partner&apos;s servers, descriptions or <span className="xstd-mono">x-</span> extensions.
        Overlays apply in the order listed, to versions imported from OpenAPI.
      </p>

      {stored ? (
        <div className="xstd-stack xstd-stack--tight" data-testid="export-studio-stored-overlays">
          {stored.error ? (
            <p className="xstd-notice" data-tone="warn">
              The revision&apos;s stored overlays could not be read: {stored.error}
            </p>
          ) : stored.chain && stored.chain.overlays.length > 0 ? (
            <>
              <label className="xstd-overlay__row" htmlFor={switchId}>
                <Switch
                  id={switchId}
                  checked={stored.apply}
                  onCheckedChange={stored.onToggleApply}
                  data-testid="export-studio-apply-stored"
                />
                <span className="xstd-overlay__main">
                  <span className="xstd-overlay__name">Apply stored overlays</span>
                  <span className="hive-quiet">
                    This revision&apos;s {stored.chain.overlays.length} stored{' '}
                    {stored.chain.overlays.length === 1 ? 'overlay applies' : 'overlays apply'} first,
                    then the files below.
                  </span>
                </span>
              </label>
              <ol className="xstd-overlay__list" aria-label="Stored overlays, in the order they apply">
                {stored.chain.overlays.map((overlay) => (
                  <li
                    key={overlay.id}
                    className="xstd-overlay__row"
                    data-testid={`export-studio-stored-overlay-${overlay.position}`}
                  >
                    <span className="xstd-overlay__order" aria-hidden>
                      {overlay.position + 1}
                    </span>
                    <span className="xstd-overlay__main">
                      <span className="xstd-overlay__name">{overlay.name}</span>
                      <span className="hive-quiet">
                        {OVERLAY_SOURCE_LABEL[overlay.source] ?? overlay.source} ·{' '}
                        {overlay.action_count} {overlay.action_count === 1 ? 'action' : 'actions'}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </>
          ) : stored.chain ? (
            <p className="hive-quiet" data-testid="export-studio-no-stored-overlays">
              This revision has no stored overlays.
            </p>
          ) : null}
        </div>
      ) : null}

      {overlays.length === 0 ? (
        <p className="xstd-empty" data-testid="export-studio-no-overlays">
          No overlays — the version exports as it is. Continue to verify the conversion.
        </p>
      ) : (
        <ol className="xstd-overlay__list" aria-label="Overlays, in the order they apply">
          {overlays.map((overlay, index) => {
            const title = overlayTitle(overlay);
            const actions = overlayActionCount(overlay);
            return (
              <li
                key={overlay.name}
                className="xstd-overlay__row"
                data-testid={`export-studio-overlay-${index}`}
              >
                <span className="xstd-overlay__order" aria-hidden>
                  {index + 1}
                </span>
                <span className="xstd-overlay__main">
                  <span className="xstd-overlay__name">{overlay.name}</span>
                  <span className="hive-quiet">
                    {title ? `${title} · ` : ''}
                    {actions} {actions === 1 ? 'action' : 'actions'}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Apply ${overlay.name} earlier`}
                  title={index === 0 ? 'Already applied first' : `Apply ${overlay.name} earlier`}
                  disabled={index === 0}
                  onClick={() => onChange(moveOverlay(overlays, index, -1))}
                >
                  <ArrowUp aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Apply ${overlay.name} later`}
                  title={
                    index === overlays.length - 1 ? 'Already applied last' : `Apply ${overlay.name} later`
                  }
                  disabled={index === overlays.length - 1}
                  onClick={() => onChange(moveOverlay(overlays, index, 1))}
                >
                  <ArrowDown aria-hidden />
                </Button>
                {canSaveToChain ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Save ${overlay.name} to this revision's overlays`}
                    title={
                      savedNames.includes(overlay.name)
                        ? `${overlay.name} is saved to this revision's overlays`
                        : saving
                          ? 'Saving…'
                          : `Save ${overlay.name} to this revision's overlays`
                    }
                    disabled={saving !== null || savedNames.includes(overlay.name)}
                    onClick={() => void saveToChain(overlay)}
                    data-testid={`export-studio-overlay-save-${index}`}
                  >
                    <Save aria-hidden />
                  </Button>
                ) : null}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${overlay.name}`}
                  title={`Remove ${overlay.name}`}
                  onClick={() => onChange(overlays.filter((_, i) => i !== index))}
                >
                  <X aria-hidden />
                </Button>
              </li>
            );
          })}
        </ol>
      )}

      <div>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept=".json,.yaml,.yml,application/json,application/yaml"
          multiple
          className="sr-only"
          aria-label="Overlay files"
          data-testid="export-studio-overlay-input"
          onChange={(event) => void handleFiles(event)}
        />
        <Button
          variant="outline"
          onClick={() => inputRef.current?.click()}
          disabled={full}
          title={full ? `An export applies at most ${MAX_EXPORT_OVERLAYS} overlays.` : undefined}
          data-testid="export-studio-overlay-upload"
        >
          <Upload className="h-4 w-4" aria-hidden />
          Add overlay files
        </Button>
      </div>

      {errors.length > 0 && (
        <ul className="xstd-overlay__list" role="alert" data-testid="export-studio-overlay-errors">
          {errors.map((message) => (
            <li key={message} className="xstd-notice" data-tone="warn">
              {message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
