'use server';

import { buildOpenApiSpecForVersion } from '../../../../../../lib/db/helper';

export interface PathsCodeSpecResult {
  pathsObject: Record<string, unknown>;
  mergedSpecJson: string;
}

/**
 * Loads the OpenAPI `paths` object and the full merged spec (paths + components/schemas)
 * for the Paths Code view (#2654). Uses the shared version OpenAPI builder.
 */
export async function loadPathsCodeSpec(options: {
  versionId: string;
  projectName: string;
  versionLabel: string;
  versionDescription: string;
}): Promise<PathsCodeSpecResult> {
  const { versionId, projectName, versionLabel, versionDescription } = options;
  const { specJson, pathsObject } = await buildOpenApiSpecForVersion(versionId, {
    projectName,
    versionLabel,
    description: versionDescription,
  });
  return { pathsObject, mergedSpecJson: specJson };
}
