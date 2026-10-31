'use client';

import { useCallback, useId, useRef, useState, type ChangeEvent } from 'react';
import { ArrowDown, ArrowUp, Layers, Upload, X } from 'lucide-react';
import { Button } from '../../../ui/Button';
import {
  MAX_EXPORT_OVERLAYS,
  addOverlays,
  moveOverlay,
  overlayActionCount,
  overlayTitle,
  parseOverlayFile,
  type ExportStudioOverlay,
} from './exportOverlays';

interface ExportOverlaysStepProps {
  /** The overlay chain, in application order. */
  overlays: ExportStudioOverlay[];
  /** Replace the chain (add, remove or reorder). */
  onChange: (overlays: ExportStudioOverlay[]) => void;
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
 * @param props.overlays The chain, in application order.
 * @param props.onChange Called with the new chain.
 * @returns The step panel.
 */
export function ExportOverlaysStep({ overlays, onChange }: ExportOverlaysStepProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const full = overlays.length >= MAX_EXPORT_OVERLAYS;

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
      <p className="xstd-quiet">
        An overlay changes the exported document without changing the version — for example a
        partner&apos;s servers, descriptions or <span className="xstd-mono">x-</span> extensions.
        Overlays apply in the order listed, to versions imported from OpenAPI.
      </p>

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
                  <span className="xstd-quiet">
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
