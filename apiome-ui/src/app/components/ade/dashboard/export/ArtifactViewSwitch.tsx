'use client';

/**
 * The view switch of an emitted-artifact viewer — text, or one of the target's pictures (MFX-45.4).
 *
 * Both Review-step viewers (the single-document card and the bundle explorer) share this: the target
 * descriptor declares its modes (`viz_modes`), the manifest carries their data, and the viewer offers
 * **Text** plus every declared mode with something to draw — an **ERD** for a database export, an
 * **Import graph** and a **Service map** for a protobuf bundle, a **Channel topology** for an event
 * export. The choice is kept per target for the session.
 */

import { useCallback, useMemo, useState } from 'react';
import { EmptyState } from '../../../ui/EmptyState';
import { ExportErdView } from './ExportErdView';
import { isStudioViz, trackStudioEvent } from './studioTelemetry';
import { ExportVizGraphView } from './ExportVizGraphView';
import type { RelationalSchema } from './exportErd';
import {
  availableVizModes,
  loadVizChoice,
  saveVizChoice,
  type ArtifactView,
  type ExportVizMode,
  type VizGraph,
} from './exportViz';

/** What a viewer needs to offer its pictures. */
export interface ArtifactVizInput {
  /** The export target's key — the session memory of the chosen view is per target. */
  targetKey?: string | null;
  /** The target descriptor's declared modes; undefined when unknown (the data then decides). */
  vizModes?: ExportVizMode[] | null;
  /** The manifest's relational projection (the `erd` mode's data). */
  relational?: RelationalSchema | null;
  /** The manifest's graph per mode. */
  views?: Record<string, VizGraph> | null;
}

/** The state of a viewer's view switch. */
export interface ArtifactViewState {
  /** The modes offered beside the text. */
  modes: ExportVizMode[];
  /** The view on screen. */
  view: ArtifactView;
  /** Choose a view (remembered for the target, for the session). */
  setView: (view: ArtifactView) => void;
}

/**
 * The view switch's state: the modes on offer and the chosen view, restored per target from the
 * session and falling back to the text when the chosen mode is not on offer.
 *
 * @param input The target and the manifest's data.
 * @returns The modes, the view, and its setter.
 */
export function useArtifactView({ targetKey, vizModes, relational, views }: ArtifactVizInput): ArtifactViewState {
  const modes = useMemo(() => availableVizModes(vizModes, { relational, views }), [vizModes, relational, views]);
  const target = targetKey ?? null;
  const modeKey = modes.map((mode) => mode.kind).join(',');
  const [chosen, setChosen] = useState<{ target: string | null; modeKey: string; view: ArtifactView; picked: boolean }>(
    () => ({ target, modeKey, view: loadVizChoice(targetKey, modes), picked: false }),
  );

  // Another target restores that target's choice; so do its modes arriving with the manifest, until the
  // user picks a view here — the "adjust state during render" pattern.
  let current = chosen;
  if (chosen.target !== target || (!chosen.picked && chosen.modeKey !== modeKey)) {
    current = { target, modeKey, view: loadVizChoice(targetKey, modes), picked: false };
    setChosen(current);
  }

  const setView = useCallback(
    (view: ArtifactView) => {
      setChosen({ target: targetKey ?? null, modeKey, view, picked: true });
      saveVizChoice(targetKey, view);
      // MFX-46.5: which pictures people use (the text view is not counted).
      if (isStudioViz(view)) void trackStudioEvent({ kind: 'viz_used', view });
    },
    [targetKey, modeKey],
  );

  const view = current.view === 'text' || modes.some((mode) => mode.kind === current.view) ? current.view : 'text';
  return { modes, view, setView };
}

/** The switch: the text, then one button per mode. */
export function ArtifactViewSwitch({
  modes,
  view,
  onChange,
  textLabel,
  testIdPrefix,
  className,
}: {
  modes: ExportVizMode[];
  view: ArtifactView;
  onChange: (view: ArtifactView) => void;
  /** The text view's label, e.g. `DDL text` or `Files`. */
  textLabel: string;
  testIdPrefix: string;
  className?: string;
}) {
  if (modes.length === 0) return null;
  return (
    <div role="group" aria-label="View" className={className ?? 'xstd-erd-toggle'} data-testid={`${testIdPrefix}-view-toggle`}>
      <button
        type="button"
        className="xstd-chip"
        aria-pressed={view === 'text'}
        data-testid={`${testIdPrefix}-view-text`}
        onClick={() => onChange('text')}
      >
        {textLabel}
      </button>
      {modes.map((mode) => (
        <button
          key={mode.kind}
          type="button"
          className="xstd-chip"
          aria-pressed={view === mode.kind}
          data-testid={`${testIdPrefix}-view-${mode.kind}`}
          onClick={() => onChange(mode.kind)}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}

/** The picture of the chosen mode (nothing for the text). */
export function ArtifactVizPanel({
  view,
  modes,
  relational,
  views,
  selectedEntityKey,
  onSelectEntityKey,
  className,
}: {
  view: ArtifactView;
  modes: ExportVizMode[];
  relational?: RelationalSchema | null;
  views?: Record<string, VizGraph> | null;
  selectedEntityKey: string | null;
  onSelectEntityKey: (entityKey: string) => void;
  className?: string;
}) {
  if (view === 'text') return null;
  // MFX-46.5: a chosen picture with nothing to draw says so rather than leaving a blank panel.
  const nothing = (
    <EmptyState
      variant="compact"
      title="Nothing to draw"
      description="Nothing here for this view. Switch to Text to read the file."
      data-testid="artifact-viz-empty"
    />
  );
  if (view === 'erd') {
    if (relational && relational.tables.length === 0) return nothing;
    return relational ? (
      <ExportErdView
        schema={relational}
        selectedEntityKey={selectedEntityKey}
        onSelectEntityKey={onSelectEntityKey}
        className={className}
      />
    ) : (
      nothing
    );
  }
  const graph = views?.[view];
  if (!graph || graph.nodes.length === 0) return nothing;
  const title = modes.find((mode) => mode.kind === view)?.label ?? view;
  return (
    <ExportVizGraphView
      graph={graph}
      title={title}
      selectedEntityKey={selectedEntityKey}
      onSelectEntityKey={onSelectEntityKey}
      className={className}
    />
  );
}
