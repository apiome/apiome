/**
 * Score-orb coverage for ProjectsDashboardProjectCard.
 *
 * Cards must surface the same quality / lint values the projects table shows, including the
 * server-captured qualityScore / qualityGrade fallback when browser-local history is empty.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  ProjectsDashboardProjectCard,
  type ProjectsDashboardProjectCardProps,
} from '../src/app/components/ade/dashboard/projects/ProjectsDashboardProjectCard';
import type { ProjectQualitySnapshot } from '../src/app/utils/project-quality-score-history';

function makeProject(
  overrides: Partial<ProjectsDashboardProjectCardProps['project']> = {}
): ProjectsDashboardProjectCardProps['project'] {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    name: 'billing-api',
    slug: 'billing',
    description: 'Core invoicing definitions.',
    enabled: true,
    deleted_at: null,
    updated_at: '2026-06-20T12:00:00.000Z',
    creator_name: 'Kenji Sato',
    creator_email: 'kenji@example.com',
    qualityScore: 94,
    qualityGrade: 'A',
    ...overrides,
  };
}

function renderCard(props: Partial<ProjectsDashboardProjectCardProps> = {}) {
  const onOpenQualityHistory = jest.fn();
  const onOpenLintReport = jest.fn();
  const onNavigateToVersions = jest.fn();
  render(
    <ProjectsDashboardProjectCard
      project={props.project ?? makeProject()}
      qualityHistory={props.qualityHistory ?? []}
      avatarGradientClass="from-indigo-500 to-purple-500"
      avatarInitials="BA"
      creatorInitials="KS"
      shortProjectId="prj_11112"
      onOpenQualityHistory={onOpenQualityHistory}
      onOpenLintReport={onOpenLintReport}
      onNavigateToVersions={onNavigateToVersions}
      actionsSlot={<button data-testid="actions-slot">actions</button>}
      {...props}
    />
  );
  return { onOpenQualityHistory, onOpenLintReport, onNavigateToVersions };
}

describe('ProjectsDashboardProjectCard — quality / lint / debt orbs', () => {
  it('renders quality and lint from server-captured scores when history is empty', () => {
    const { onOpenQualityHistory, onOpenLintReport } = renderCard();

    const quality = screen.getByTitle('Open quality score history');
    expect(quality).toHaveTextContent('94');
    fireEvent.click(quality);
    expect(onOpenQualityHistory).toHaveBeenCalledTimes(1);

    const lint = screen.getByTitle('Open lint report');
    expect(lint).toHaveTextContent('A');
    fireEvent.click(lint);
    expect(onOpenLintReport).toHaveBeenCalledTimes(1);
  });

  it('prefers browser-local quality history over the server score', () => {
    const history: ProjectQualitySnapshot[] = [
      { recordedAt: '2026-06-01T00:00:00.000Z', overall: 72, grade: 'B' },
    ];
    renderCard({
      project: makeProject({ qualityScore: 94, qualityGrade: 'A' }),
      qualityHistory: history,
    });
    expect(screen.getByTitle('Open quality score history')).toHaveTextContent('72');
    expect(screen.getByTitle('Open lint report')).toHaveTextContent('B');
  });

  it('derives the lint letter from the server score when grade is missing', () => {
    renderCard({
      project: makeProject({ qualityScore: 82, qualityGrade: null }),
      qualityHistory: [],
    });
    expect(screen.getByTitle('Open quality score history')).toHaveTextContent('82');
    expect(screen.getByTitle('Open lint report')).toHaveTextContent('B');
  });

  it('renders dash orbs when there is no score at all', () => {
    renderCard({
      project: makeProject({ qualityScore: null, qualityGrade: null }),
      qualityHistory: [],
    });
    expect(screen.queryByTitle('Open quality score history')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Open lint report')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('keeps the Debt orb inert (technical debt is not yet computed)', () => {
    renderCard();
    const debt = screen.getByTitle('Technical debt (not yet computed)');
    expect(debt).toHaveTextContent('—');
    expect(debt.tagName).toBe('SPAN');
    expect(screen.getByText('Debt')).toBeInTheDocument();
  });
});
