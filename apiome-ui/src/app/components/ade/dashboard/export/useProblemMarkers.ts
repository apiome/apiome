'use client';

/**
 * useProblemMarkers — wires Verify located problems onto a mounted Monaco viewer (MFX-43.3, #4363).
 *
 * The pure marker model lives in `./exportProblemMarkers.ts`; this hook is the thin imperative
 * bridge to a `ReadOnlyCodeViewer`'s editor instance. Given one file's problems and text it:
 *
 *  - sets the squiggle markers (`setModelMarkers`, owner {@link PROBLEM_MARKER_OWNER}) and the
 *    gutter/selected-line decorations, re-applying them whenever the problems, document, or
 *    selection change, and clearing both on unmount;
 *  - listens for editor clicks and resolves the clicked line back to its problem (the
 *    marker → finding direction), reporting it through `onMarkerSelect`;
 *  - exposes `reveal(problem)` (the finding → editor direction), which scrolls the problem's line
 *    to center and parks the cursor on it — queued until mount when the editor chunk is still
 *    loading.
 *
 * Both review surfaces — the multi-file `BundleExplorer` and the single-file `ArtifactPreviewCard`
 * — share this hook, so markers behave identically everywhere the shared viewer renders.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { OnMount } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
import {
  decorationsForProblems,
  markersForProblems,
  problemAtLine,
  PROBLEM_MARKER_OWNER,
  type LocatedProblem,
  type ProblemRevealRequest,
} from './exportProblemMarkers';

type MonacoInstance = Parameters<OnMount>[1];

export interface UseProblemMarkersOptions {
  /** The active file's located problems (already filtered by {@link problemsForFile}). */
  problems: LocatedProblem[];
  /** The active file's text — markers/decorations are clamped against it. */
  text: string;
  /** The highlighted problem's id, or null; drives the selected-line decoration. */
  selectedProblemId?: string | null;
  /** Called when the user clicks an editor line that has a problem (marker → finding). */
  onMarkerSelect?: (problem: LocatedProblem) => void;
  /**
   * An external "open this problem" request (a Verify lens click). It is applied — once per nonce
   * — as soon as the problem appears in {@link problems}, i.e. once the caller has made its file
   * the active document; until then it stays pending.
   */
  reveal?: ProblemRevealRequest | null;
}

export interface ProblemMarkersHandle {
  /** Pass to `ReadOnlyCodeViewer`'s `onMount` — captures the editor and wires the click listener. */
  onEditorMount: OnMount;
  /** Scroll the problem's line to center and park the cursor there (finding → editor). */
  reveal: (problem: LocatedProblem) => void;
}

/**
 * Keep a Monaco viewer's markers, gutter decorations, and click-through in sync with one file's
 * Verify problems.
 *
 * @param options The file's problems/text, the selected problem, and the marker-click callback.
 * @returns The viewer `onMount` handler and the imperative `reveal`.
 */
export function useProblemMarkers({
  problems,
  text,
  selectedProblemId = null,
  onMarkerSelect,
  reveal = null,
}: UseProblemMarkersOptions): ProblemMarkersHandle {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<MonacoInstance | null>(null);
  const decorationsRef = useRef<editor.IEditorDecorationsCollection | null>(null);
  /** A reveal requested before the editor chunk mounted; applied on mount. */
  const pendingRevealRef = useRef<LocatedProblem | null>(null);
  /** The last external reveal nonce applied, so a request runs exactly once. */
  const handledRevealNonceRef = useRef<number | null>(null);
  const [mounted, setMounted] = useState(false);

  // The click listener is registered once (on mount) but must see the *current* problems and
  // callback — refs, synced each render (in an effect, never during render), keep it current
  // without re-subscribing.
  const problemsRef = useRef(problems);
  const onMarkerSelectRef = useRef(onMarkerSelect);
  useEffect(() => {
    problemsRef.current = problems;
    onMarkerSelectRef.current = onMarkerSelect;
  });

  const applyReveal = useCallback((problem: LocatedProblem) => {
    const ed = editorRef.current;
    if (!ed) return;
    const lineCount = ed.getModel()?.getLineCount() ?? problem.line;
    const line = Math.min(Math.max(1, problem.line), Math.max(1, lineCount));
    ed.revealLineInCenter(line);
    ed.setPosition({ lineNumber: line, column: problem.column ?? 1 });
    ed.focus();
  }, []);

  const onEditorMount = useCallback<OnMount>(
    (ed, monaco) => {
      editorRef.current = ed;
      monacoRef.current = monaco;
      ed.onMouseDown((event) => {
        const line = event.target?.position?.lineNumber;
        if (typeof line !== 'number') return;
        const hit = problemAtLine(problemsRef.current, line);
        if (hit) onMarkerSelectRef.current?.(hit);
      });
      setMounted(true);
      const pending = pendingRevealRef.current;
      if (pending) {
        pendingRevealRef.current = null;
        applyReveal(pending);
      }
    },
    [applyReveal],
  );

  const revealNow = useCallback(
    (problem: LocatedProblem) => {
      if (!editorRef.current) {
        pendingRevealRef.current = problem;
        return;
      }
      applyReveal(problem);
    },
    [applyReveal],
  );

  // Re-apply markers + decorations whenever the file, its problems, or the selection change.
  // The viewer syncs `value` into the model in the child's own effect, which runs before this
  // (parent) effect — so the model text is already current when markers are clamped against it.
  useEffect(() => {
    const ed = editorRef.current;
    const monaco = monacoRef.current;
    if (!mounted || !ed || !monaco) return undefined;
    const model = ed.getModel();
    if (!model) return undefined;

    monaco.editor.setModelMarkers(model, PROBLEM_MARKER_OWNER, markersForProblems(problems, text));
    decorationsRef.current?.clear();
    decorationsRef.current = ed.createDecorationsCollection(
      decorationsForProblems(problems, text, selectedProblemId),
    );

    return () => {
      decorationsRef.current?.clear();
      decorationsRef.current = null;
      // The model may already be disposed on teardown; clearing markers then is a no-op anyway.
      if (!model.isDisposed?.()) {
        monaco.editor.setModelMarkers(model, PROBLEM_MARKER_OWNER, []);
      }
    };
  }, [mounted, problems, text, selectedProblemId]);

  // Apply an external reveal request once per nonce, as soon as its problem is in the active
  // file's list (the caller switches the active file; this effect re-runs when `problems` follows).
  useEffect(() => {
    if (!mounted || !reveal || reveal.nonce === handledRevealNonceRef.current) return;
    const target = problems.find((problem) => problem.id === reveal.problem.id);
    if (!target) return; // The problem's file is not active (yet) — stay pending.
    handledRevealNonceRef.current = reveal.nonce;
    applyReveal(target);
  }, [mounted, reveal, problems, applyReveal]);

  return { onEditorMount, reveal: revealNow };
}

export default useProblemMarkers;
