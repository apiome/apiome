/**
 * Filters for querying data_snapshot.
 * timeRange reserved for future time-series lookups.
 */
export interface SnapshotQueryFilters {
  classSchemaId: string;
  timeRange?: {
    from?: string; // ISO timestamp
    to?: string;
  };
}

export interface SnapshotQueryResult {
  rows: Array<{ record_id: string; data: Record<string, unknown>; updated_at: string }>;
  total: number;
  page: number;
  pageSize: number;
}
