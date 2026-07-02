'use client';

import { ChevronLeft, ChevronRight, Clock, Monitor, NotebookText, Square, X } from 'lucide-react';

type CanvasPresentationPanelProps = {
  slideLabel: string;
  slideIndexDisplay: number;
  slideTotal: number;
  elapsedLabel: string;
  showSpeakerNotes: boolean;
  onToggleSpeakerNotes: () => void;
  onPrev: () => void;
  onNext: () => void;
  onResetTimer: () => void;
  onExit: () => void;
  canGoPrev: boolean;
  canGoNext: boolean;
};

/**
 * Minimal presenter HUD over the canvas (timer, slide index, navigation).
 */
export function CanvasPresentationPanel({
  slideLabel,
  slideIndexDisplay,
  slideTotal,
  elapsedLabel,
  showSpeakerNotes,
  onToggleSpeakerNotes,
  onPrev,
  onNext,
  onResetTimer,
  onExit,
  canGoPrev,
  canGoNext,
}: CanvasPresentationPanelProps) {
  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-xl border border-gray-200/90 bg-white/95 px-3 py-2 shadow-lg backdrop-blur-sm dark:border-gray-600/90 dark:bg-gray-900/95">
      <span className="max-w-[min(40vw,14rem)] truncate text-xs font-medium text-gray-800 dark:text-gray-100" title={slideLabel}>
        {slideLabel}
      </span>
      <span className="tabular-nums text-xs text-gray-600 dark:text-gray-400">
        {slideIndexDisplay} / {slideTotal}
      </span>
      <div className="flex items-center gap-1 text-xs text-gray-600 dark:text-gray-400">
        <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="tabular-nums">{elapsedLabel}</span>
      </div>
      <button
        type="button"
        onClick={onResetTimer}
        className="rounded-md border border-gray-200 px-2 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
        title="Reset timer (T)"
      >
        Reset
      </button>
      <div className="h-4 w-px bg-gray-200 dark:bg-gray-600" />
      <button
        type="button"
        onClick={onToggleSpeakerNotes}
        className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
          showSpeakerNotes
            ? 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200'
            : 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800'
        }`}
        title="Toggle speaker notes panel (N)"
      >
        <NotebookText className="h-3.5 w-3.5" aria-hidden />
        Notes
      </button>
      <div className="flex items-center gap-0.5">
        <button
          type="button"
          onClick={onPrev}
          disabled={!canGoPrev}
          className="rounded-md p-1.5 text-gray-700 hover:bg-gray-100 disabled:opacity-40 dark:text-gray-200 dark:hover:bg-gray-800"
          title="Previous slide (←)"
          aria-label="Previous slide"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!canGoNext}
          className="rounded-md p-1.5 text-gray-700 hover:bg-gray-100 disabled:opacity-40 dark:text-gray-200 dark:hover:bg-gray-800"
          title="Next slide (→ or Space)"
          aria-label="Next slide"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      <button
        type="button"
        onClick={onExit}
        className="ml-1 inline-flex items-center gap-1 rounded-md bg-gray-900 px-2 py-1 text-xs font-medium text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
        title="Exit presentation (Esc)"
      >
        <Square className="h-3 w-3" aria-hidden />
        Exit
      </button>
      <span className="hidden text-[10px] text-gray-500 sm:inline dark:text-gray-500" title="Presenter shortcuts">
        <Monitor className="mr-1 inline h-3 w-3" aria-hidden />
        ← → Space · N notes · T timer · Esc exit
      </span>
    </div>
  );
}

type PresentationExitHintProps = {
  onDismiss: () => void;
};

/** Shown briefly when entering presentation to surface keyboard shortcuts. */
export function PresentationExitHint({ onDismiss }: PresentationExitHintProps) {
  return (
    <div className="pointer-events-auto flex max-w-md items-start gap-3 rounded-xl border border-indigo-200 bg-indigo-50/95 px-4 py-3 text-sm text-indigo-950 shadow-lg backdrop-blur-sm dark:border-indigo-700/80 dark:bg-indigo-950/90 dark:text-indigo-100">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-semibold">Presentation mode</p>
        <ul className="list-inside list-disc text-xs text-indigo-900/90 dark:text-indigo-200/90">
          <li>Arrow keys or Space: change slide</li>
          <li>N: speaker notes</li>
          <li>T: reset timer</li>
          <li>Esc: exit</li>
        </ul>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 rounded-md p-1 text-indigo-700 hover:bg-indigo-100 dark:text-indigo-300 dark:hover:bg-indigo-900/50"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
