export interface RegistryCoverageStats {
  core_type_count: number;
  tenant_type_count: number;
  imported_count: number;
  properties_bound_count: number;
  bound_class_count: number;
  unresolved_ref_count: number;
  namespace_count: number;
}

export interface TypeNamespaceCollection {
  id: string;
  tenant_id: string | null;
  namespace: string;
  base_uri: string;
  version_root: string | null;
  description: string | null;
  scope: 'system' | 'tenant';
  is_system: boolean;
  is_public: boolean;
  is_default: boolean;
  type_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PrimitiveImportActivity {
  id: string;
  tenant_id: string;
  source_kind: string;
  source_label: string | null;
  target_namespace: string | null;
  imported_count: number;
  skipped_count: number;
  error_count: number;
  created_at: string | null;
}

export type NamespaceScopeFilter = 'all' | 'system' | 'tenant' | 'imported';

export function countUnresolvedByNamespace(
  unresolvedPrimitives: Array<{ namespace?: string | null; unresolved_count?: number }>
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const row of unresolvedPrimitives) {
    const key = row.namespace ?? '';
    counts[key] = (counts[key] ?? 0) + (row.unresolved_count ?? 0);
  }
  return counts;
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return '1 d ago';
  return `${days} d ago`;
}

export function sourceKindLabel(kind: string): string {
  switch (kind) {
    case 'json-schema':
      return 'JSON Schema';
    case 'type-def-bundle':
      return 'Type definitions';
    case 'openapi':
      return 'OpenAPI';
    default:
      return kind;
  }
}
