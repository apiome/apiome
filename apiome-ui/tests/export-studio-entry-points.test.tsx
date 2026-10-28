/**
 * Export studio entry points (E1-1, #6217).
 *
 * With `export-studio` previewed, every entry point opens the studio scoped to its source; without
 * the override nothing changes from RC6 (the entry point is absent). The Catalog verbs, the item
 * page's ⋯ row, the Versions ⋯ row and the back-link guard are pinned in their own suites
 * (`catalog-hive-redesign`, `catalog-item-detail`, `versions-header`, `exportStudioLink`); this file
 * covers the project facts card.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import ProjectFactsCard from '../src/app/components/ade/versions/ProjectFactsCard';
import type { Project } from '../src/app/components/ade/versions/versionsModel';

const PROJECT = { id: 'proj-1', name: 'Pets API', slug: 'pets' } as unknown as Project;

function renderCard() {
  return render(
    <ProjectFactsCard
      project={PROJECT}
      headLine={{ head: 'v2.0.0', lastPublished: null }}
      headRevisionId="rev-9"
      lastPublishedAt={null}
      publishable
    />,
  );
}

describe('project facts card', () => {
  const PREVIEW = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  afterEach(() => {
    if (PREVIEW === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW;
  });

  it('draws no Export studio button while the studio is unreleased', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    renderCard();
    expect(screen.queryByTestId('versions-facts-export-studio')).toBeNull();
    expect(screen.getByText('Published surface')).toBeInTheDocument();
  });

  it('links Export studio to the project head revision once previewed', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'export-studio';
    renderCard();
    expect(screen.getByTestId('versions-facts-export-studio')).toHaveAttribute(
      'href',
      '/ade/dashboard/export/studio?artifact=proj-1&version=rev-9&label=Pets+API&from=versions',
    );
  });
});
