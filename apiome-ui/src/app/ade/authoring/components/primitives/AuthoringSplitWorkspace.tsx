'use client';

/**
 * The split workspace layout (UXE-1.3).
 *
 * §28 gives three surfaces the same shape — tree + editor + inspector for
 * Scribe, structure + canvas + properties for Slate, list + detail + inspector
 * for the Release Center — and §27.4 gives that shape its responsive contract:
 *
 * - Desktop: all three panes side by side.
 * - Tablet: one primary pane plus a slide-over inspector, because the preview
 *   toggles rather than compresses.
 * - Mobile: one pane at a time.
 *
 * Implementing the breakpoints once means a surface cannot accidentally ship a
 * three-column layout that squeezes to unreadable at 320px. Below `xl` the
 * inspector is not rendered inline at all; it moves into a peek drawer, which
 * is why `inspector` and `onInspectorOpen` are separate props.
 */

import * as React from 'react';
import { cn } from '@lib/utils';
import {
  authoringPaneBodyClass,
  authoringPaneClass,
  authoringPaneHeaderClass,
  authoringSectionTitleClass,
  authoringSplitClass,
} from '../../authoringClasses';

/** One pane's content and heading. */
export type AuthoringWorkspacePane = {
  /** Heading shown in the pane header and used as its accessible name. */
  title: string;
  /** Controls rendered at the end of the pane header, e.g. a filter. */
  actions?: React.ReactNode;
  children: React.ReactNode;
};

/** Props for {@link AuthoringSplitWorkspace}. */
export type AuthoringSplitWorkspaceProps = {
  /** Navigation pane: tree, structure or list. */
  navigation: AuthoringWorkspacePane;
  /** The focused pane: editor, canvas or detail. */
  main: AuthoringWorkspacePane;
  /**
   * Inspector pane. Rendered inline only at `xl` and above; narrower viewports
   * reach it through a peek drawer instead.
   */
  inspector?: AuthoringWorkspacePane;
  /**
   * Opens the inspector as a drawer. Required whenever `inspector` is given,
   * because below `xl` this button is the only way to reach it.
   */
  onInspectorOpen?: () => void;
  className?: string;
};

/**
 * Render the three-pane workspace.
 *
 * @param props - The panes and the inspector's drawer handler.
 */
export default function AuthoringSplitWorkspace({
  navigation,
  main,
  inspector,
  onInspectorOpen,
  className,
}: AuthoringSplitWorkspaceProps) {
  return (
    <div className={cn(authoringSplitClass, className)} data-panes={inspector ? 3 : 2}>
      <Pane pane={navigation} testId="navigation" />

      <Pane
        pane={{
          ...main,
          actions: (
            <>
              {main.actions}
              {inspector && onInspectorOpen ? (
                // Hidden once the inspector is inline, so there are never two
                // routes to the same pane competing on the same screen.
                <button
                  type="button"
                  onClick={onInspectorOpen}
                  className="min-h-9 rounded-lg px-3 text-sm font-medium text-indigo-700 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:text-indigo-300 xl:hidden"
                >
                  {inspector.title}
                </button>
              ) : null}
            </>
          ),
        }}
        testId="main"
      />

      {inspector ? (
        <Pane pane={inspector} testId="inspector" className="hidden xl:flex" />
      ) : null}
    </div>
  );
}

/**
 * Render one titled pane.
 *
 * @param props - The pane, a test id and optional extra classes.
 */
function Pane({
  pane,
  testId,
  className,
}: {
  pane: AuthoringWorkspacePane;
  testId: string;
  className?: string;
}) {
  const headingId = React.useId();

  return (
    <section
      className={cn(authoringPaneClass, className)}
      aria-labelledby={headingId}
      data-testid={`authoring-pane-${testId}`}
    >
      <header className={authoringPaneHeaderClass}>
        <h2 id={headingId} className={authoringSectionTitleClass}>
          {pane.title}
        </h2>
        {pane.actions ? <div className="flex items-center gap-1">{pane.actions}</div> : null}
      </header>
      <div className={authoringPaneBodyClass}>{pane.children}</div>
    </section>
  );
}
