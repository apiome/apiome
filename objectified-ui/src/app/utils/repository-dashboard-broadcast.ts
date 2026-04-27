/**
 * Channel name for REPO-10.3 / #2949: keep the scan report corpus stat strip in sync
 * with the rest of the ADE dashboard. Future REPO-11.1 real-time updates should post
 * the same event shape when repository scan materialization changes tenant-wide numbers.
 */
export const REPOSITORY_DASHBOARD_BROADCAST = 'objectified:repository-corpus-refresh' as const;

type CorpusRefreshMessage = { type: 'corpus-refresh' };

function canUseBroadcastChannel(): boolean {
  return typeof window !== 'undefined' && typeof BroadcastChannel !== 'undefined';
}

export function postRepositoryCorpusStatsRefresh(): void {
  if (!canUseBroadcastChannel()) return;
  const channel = new BroadcastChannel(REPOSITORY_DASHBOARD_BROADCAST);
  try {
    const payload: CorpusRefreshMessage = { type: 'corpus-refresh' };
    channel.postMessage(payload);
  } finally {
    channel.close();
  }
}

export function subscribeRepositoryCorpusStatsRefresh(onRefresh: () => void): () => void {
  if (!canUseBroadcastChannel()) {
    return () => {};
  }
  const channel = new BroadcastChannel(REPOSITORY_DASHBOARD_BROADCAST);
  channel.onmessage = () => {
    onRefresh();
  };
  return () => {
    channel.onmessage = null;
    channel.close();
  };
}
