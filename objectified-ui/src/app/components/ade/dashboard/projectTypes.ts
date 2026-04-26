import type { ProjectOpenApiMetadata } from '../../../utils/project-templates';

/**
 * Wire shape returned by `GET /api/projects`. Centralised so the list page,
 * the detail shell, the wizard, and the various tabs all consume the same
 * projection without each redeclaring a near-duplicate interface.
 */
export type ProjectMetadata = ProjectOpenApiMetadata;

export interface Project {
  id: string;
  tenant_id: string;
  creator_id: string;
  name: string;
  /** URL-friendly identifier (lowercase letters, numbers, dashes). */
  slug?: string;
  description: string;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  creator_name: string;
  creator_email: string;
  metadata?: ProjectMetadata;
}
