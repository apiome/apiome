'use client';

import { useEffect, useRef, useState } from 'react';
import { settledRepositoriesAnnouncement, type RepositoryStatusRow } from '@lib/a11y/announcements';

/**
 * The live-region sentence for repositories that finished registering or scanning (HIVE-10.2, #5338).
 *
 * Repository screens poll while a repository is `pending` or `scanning`; when one settles the
 * badge changes silently. This hook remembers each repository's status from the previous render
 * and returns the sentence for whatever settled since, for a `ui/LiveRegion`. The sentence is kept
 * until the next settle, so the region's text only ever *changes* when something new happens.
 *
 * @param repositories The repositories as the latest load returned them (a stable array per load).
 * @returns The sentence to announce, or `''` before anything has settled.
 */
export function useSettledRepositoriesAnnouncement(repositories: readonly RepositoryStatusRow[]): string {
  const previous = useRef<ReadonlyMap<string, string>>(new Map());
  const [announcement, setAnnouncement] = useState('');

  useEffect(() => {
    const sentence = settledRepositoriesAnnouncement(previous.current, repositories);
    if (sentence) setAnnouncement(sentence);
    previous.current = new Map(repositories.map((repository) => [repository.id, repository.status]));
  }, [repositories]);

  return announcement;
}
