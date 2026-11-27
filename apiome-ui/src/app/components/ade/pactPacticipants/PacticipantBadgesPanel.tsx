'use client';

/**
 * **Badges** — the Settings tab's README badge panel (PFX-8.11, #7308).
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (Settings → Badges). Pick what the badge is
 * **For** — the pacticipant (all its pacts) or one of its pacts — and the panel previews the badge
 * exactly as REST serves it to anyone (the `/api/pact/badges` proxy reads the public SVG), says its
 * state, and offers the Markdown (Apiome's SVG or shields.io) and the image URL to copy.
 *
 * Badges are served for a pacticipant linked to a **public** project; without one the panel says
 * how to get one. A branch, tag or environment selector is not served, and the panel says so
 * rather than offering it. Badges show a state, never contract content.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, CommandBlock, FormField, LoadingState } from '@/app/components/ui';
import {
  NO_PROJECT_NOTE,
  PUBLIC_REST_BASE_URL,
  SELECTOR_NOTE,
  badgeChoices,
  badgeSurfaces,
  notPublicNote,
  svgDataUrl,
  type BadgeAnswer,
} from '@lib/pact-badges';
import type { PacticipantPacts } from '@lib/pact-detail';
import type { Pacticipant } from '@lib/pact-pacticipants';
import { fetchPacticipantPacts } from '../pactDetail/pactDetailApi';
import type { ProjectChoice } from '../pactPublish/publishApi';
import { fetchBadge } from './pacticipantsApi';
import { describeFailure } from './describeFailure';

/** Props for {@link PacticipantBadgesPanel}. */
export interface PacticipantBadgesPanelProps {
  /** The pacticipant as stored. */
  pacticipant: Pacticipant;
  /** The workspace's projects (to find the linked one's slug), or why they could not be read. */
  projects: ProjectChoice[] | { error: string } | null;
}

/** The preview's read: loading, a badge, or why there is none. */
type Preview = { kind: 'loading' } | { kind: 'badge'; answer: BadgeAnswer } | { kind: 'none'; status: number; error: string };

/**
 * The panel.
 *
 * @param props - See {@link PacticipantBadgesPanelProps}.
 * @returns The section.
 */
export default function PacticipantBadgesPanel({ pacticipant, projects }: PacticipantBadgesPanelProps) {
  const [pacts, setPacts] = React.useState<PacticipantPacts | { error: string } | null>(null);
  const [choiceId, setChoiceId] = React.useState('pacticipant');
  const [preview, setPreview] = React.useState<Preview>({ kind: 'loading' });
  const [attempt, setAttempt] = React.useState(0);

  const project =
    pacticipant.project_id && Array.isArray(projects)
      ? (projects.find((p) => p.id === pacticipant.project_id) ?? null)
      : null;

  React.useEffect(() => {
    let live = true;
    fetchPacticipantPacts(pacticipant.slug).then(
      (answer) => live && setPacts(answer),
      (caught) => live && setPacts({ error: describeFailure(caught, 'Could not read its pacts') }),
    );
    return () => {
      live = false;
    };
  }, [pacticipant.slug]);

  const choices = badgeChoices(pacticipant, pacts && 'pacts' in pacts ? pacts.pacts : []);
  const choice = choices.find((entry) => entry.id === choiceId) ?? choices[0];

  React.useEffect(() => {
    if (!project) return;
    let live = true;
    setPreview({ kind: 'loading' });
    void fetchBadge(project.slug, choice.target).then((answer) => {
      if (!live) return;
      setPreview('error' in answer ? { kind: 'none', status: answer.status, error: answer.error } : { kind: 'badge', answer });
    });
    return () => {
      live = false;
    };
    // `choice` is derived; its id names it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.slug, choice.id, attempt]);

  let body: React.ReactNode;
  if (!pacticipant.project_id) {
    body = (
      <p className="ppx__statement" data-testid="ppx-badges-no-project">
        {NO_PROJECT_NOTE}
      </p>
    );
  } else if (projects === null) {
    body = <LoadingState message="Finding the linked project…" minHeightClassName="min-h-[3rem]" />;
  } else if (!Array.isArray(projects)) {
    body = (
      <p className="ppx__error" role="alert">
        The linked project could not be found: {projects.error}
      </p>
    );
  } else if (!project) {
    body = (
      <p className="ppx__statement" data-testid="ppx-badges-project-missing">
        The linked project is not among the workspace’s projects, so it serves no badge.
      </p>
    );
  } else {
    body = (
      <>
        <FormField
          label="For"
          htmlFor="ppx-badges-for"
          helperText={
            pacts && 'error' in pacts
              ? `Only the pacticipant’s own badge: ${pacts.error}`
              : pacts?.truncated
                ? 'Some pacts may be missing: the matrix read was cut short.'
                : undefined
          }
        >
          <select
            id="ppx-badges-for"
            className="ppx__select"
            value={choice.id}
            onChange={(event) => setChoiceId(event.target.value)}
            data-testid="ppx-badges-for"
          >
            {choices.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </select>
        </FormField>
        <p className="ppx__meta" data-testid="ppx-badges-selector-note">
          {SELECTOR_NOTE}
        </p>
        {preview.kind === 'loading' ? (
          <LoadingState message="Reading the badge…" minHeightClassName="min-h-[3rem]" />
        ) : preview.kind === 'none' ? (
          <div className="ppx-badges__none" data-testid="ppx-badges-none">
            <p className={preview.status === 404 ? 'ppx__statement' : 'ppx__error'} role={preview.status === 404 ? undefined : 'alert'}>
              {preview.status === 404 ? notPublicNote(project.name) : preview.error}
            </p>
            {preview.status !== 404 ? (
              <Button variant="soft" size="sm" onClick={() => setAttempt((n) => n + 1)}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            <div className="ppx-badges__preview" data-testid="ppx-badges-preview">
              {/* eslint-disable-next-line @next/next/no-img-element -- the SVG REST serves, as a data URL */}
              <img
                src={svgDataUrl(preview.answer.svg)}
                alt={`Pact badge: ${preview.answer.status}`}
                data-testid="ppx-badges-image"
              />
              <span className="ppx__meta">Preview — {preview.answer.status}, as served now</span>
            </div>
            <CommandBlock
              title="Put it in a README"
              surfaces={badgeSurfaces(PUBLIC_REST_BASE_URL, preview.answer.tenant, project.slug, choice.target)}
              footnote="Anyone can read these URLs. A badge may lag a new verification by up to five minutes (it is cached)."
              data-testid="ppx-badges-markdown"
            />
          </>
        )}
      </>
    );
  }

  return (
    <section className="ppx__panel ppx-badges" aria-labelledby="ppx-badges-title" data-testid="ppx-badges">
      <div className="ppx__panel-head">
        <h2 id="ppx-badges-title" className="ppx__title">
          Badges
        </h2>
      </div>
      <p className="ppx__meta">Put the verdict in a README. Badges show a state, never contract content.</p>
      {body}
    </section>
  );
}
