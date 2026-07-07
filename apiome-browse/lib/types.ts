// Type definitions for database entities

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: Date;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: Date;
  tenant_name?: string;
  tenant_slug?: string;
  tenant_description?: string | null;
}

export interface Version {
  id: string;
  version_id: string;
  description: string | null;
  change_log: string | null;
  published: boolean;
  visibility: 'public' | 'private';
  created_at: Date;
  updated_at: Date;
  published_at: Date | null;
  published_by: string | null;
  publisher_name?: string | null;
  publisher_email?: string | null;
  project_name?: string;
  project_slug?: string;
  project_description?: string | null;
  tenant_name?: string;
  tenant_slug?: string;
  tenant_description?: string | null;
}

export interface SearchResult {
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tenant_description: string | null;
  project_id: string;
  project_name: string;
  project_slug: string;
  project_description: string | null;
  version_count: number;
}

/**
 * A published, public MCP catalog endpoint as exposed by the `apiome.mcp_v_public_endpoints` view,
 * enriched with current-version capability counts. Credential-free: host only, never the raw URL.
 */
export interface McpPublicEndpoint {
  id: string;
  tenant_id: string;
  tenant_slug: string;
  name: string;
  slug: string;
  category: string | null;
  transport: string;
  description: string | null;
  current_version_id: string | null;
  host: string | null;
  score: number | null;
  grade: string | null;
  scored_at: Date | null;
  last_discovered_at: Date | null;
  updated_at: Date;
  tool_count: number;
  resource_count: number;
  resource_template_count: number;
  prompt_count: number;
}

/** Public MCP endpoints grouped by host for grade-led browse-by-site. */
export interface McpPublicHostGroup {
  host: string;
  endpoints: McpPublicEndpoint[];
}

/** One labelled slice of a public-catalog composition breakdown (category / transport / grade). */
export interface McpPublicCatalogBucket {
  label: string;
  count: number;
}

/**
 * The public catalog analytics roll-up (V2-MCP-32.1 / MCAT-18.1). A *reduced* variant of the private
 * dashboard: it spans only the published + public endpoints exposed by `apiome.mcp_v_public_endpoints`,
 * so it carries just the view's own columns — how many endpoints, the average quality score, and the
 * category / transport / grade mixes. Protocol, tool counts, change history, and discovery status are
 * deliberately absent (the public view does not expose them).
 */
export interface McpPublicCatalogInsight {
  endpoint_count: number;
  average_score: number | null;
  category_distribution: McpPublicCatalogBucket[];
  transport_distribution: McpPublicCatalogBucket[];
  grade_distribution: McpPublicCatalogBucket[];
}

/** A single capability (tool / resource / resource_template / prompt) of an endpoint's snapshot. */
export interface McpCapabilityItem {
  id: string;
  item_type: 'tool' | 'resource' | 'resource_template' | 'prompt';
  name: string;
  title: string | null;
  description: string | null;
  uri: string | null;
  uri_template: string | null;
  ordinal: number;
}

/** Endpoint detail: the public endpoint plus its current snapshot's capability items. */
export interface McpPublicEndpointDetail {
  endpoint: McpPublicEndpoint;
  items: McpCapabilityItem[];
}

/**
 * A capability search hit over the public MCP catalog: the matched item (or the endpoint itself when
 * the endpoint metadata matched) plus its endpoint's browse context, score/grade, and FTS relevance.
 */
export interface McpPublicSearchHit {
  endpoint_id: string;
  tenant_id: string;
  tenant_slug: string;
  endpoint_name: string;
  endpoint_slug: string;
  host: string | null;
  category: string | null;
  transport: string;
  score: number | null;
  grade: string | null;
  item_type: 'tool' | 'resource' | 'resource_template' | 'prompt';
  item_id: string;
  item_name: string;
  item_title: string | null;
  description: string | null;
  relevance: number;
}

/**
 * Canvas metadata for class positioning and styling.
 * This is UI-only data and does not affect schema generation or exports.
 */
export interface CanvasMetadata {
  /** Position on the canvas in pixels */
  position?: {
    x: number;
    y: number;
  };
  /** Dimensions of the class node */
  dimensions?: {
    width?: number;
    height?: number;
  };
  /** Visual styling options */
  style?: {
    backgroundColor?: string;
    borderColor?: string;
    collapsed?: boolean;
    zIndex?: number;
  };
  /** Group ID if this class belongs to a visual group */
  group?: string | null;
}

/**
 * Class definition representing a schema object.
 */
export interface Class {
  id: string;
  version_id: string;
  name: string;
  description: string | null;
  /** JSON Schema definition for the class */
  schema: Record<string, unknown>;
  enabled: boolean;
  /** UI-only canvas positioning and styling - excluded from exports */
  canvas_metadata?: CanvasMetadata | null;
  created_at: Date;
  updated_at: Date;
}

