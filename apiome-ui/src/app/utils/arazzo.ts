/**
 * Arazzo Specification Generator Utilities
 *
 * Generates Arazzo 1.0.x or 1.1.x workflow specifications from class definitions.
 * Arazzo is a specification for describing sequences of API calls and their dependencies.
 * Uses Handlebars templates for flexible generation.
 *
 * The written version follows the REST generator and emitter (apiome-rest `arazzo_generator.py`):
 * an explicit `arazzoVersion` wins; otherwise `1.1.0` when a source description is AsyncAPI (only
 * Arazzo 1.1 can express one) and `1.0.1` for an all-OpenAPI document.
 */

import { renderTemplate, clearTemplateCache } from './template-loader';

/** Version written for an all-OpenAPI document with no requested version (the 1.0 line's final patch). */
export const ARAZZO_VERSION_1_0 = '1.0.1';

/** Version written for a document with an AsyncAPI source description and no requested version. */
export const ARAZZO_VERSION_1_1 = '1.1.0';

/** `major.minor` lines the generator writes, matching the REST importer's supported versions. */
export const SUPPORTED_ARAZZO_LINES: readonly string[] = ['1.0', '1.1'];

/** One `sourceDescriptions` entry of a generated document. */
export interface ArazzoSourceDescription {
  name: string;
  /** `openapi`, `asyncapi` (Arazzo 1.1 and later) or `arazzo`. */
  type: string;
  url: string;
  description?: string;
}

/** A full `major.minor.patch[-pre]` version, the form the Arazzo schemas require of `arazzo`. */
const FULL_VERSION = /^(\d+)\.(\d+)\.\d+(-.+)?$/;

/**
 * Choose the `arazzo` version a generated document declares.
 * @param arazzoVersion - The requested version (`1.0.1`, `1.1.0` …), or undefined / blank for the default
 * @param sourceDescriptions - The document's source descriptions
 * @returns The requested version, trimmed; otherwise `1.1.0` when any source is `asyncapi`, else `1.0.1`
 * @throws Error when the requested version is not a full 1.0.x / 1.1.x version, or is 1.0.x while a
 *   source description is AsyncAPI (which Arazzo 1.0 cannot express)
 */
export function resolveArazzoVersion(
  arazzoVersion: string | undefined,
  sourceDescriptions: ArazzoSourceDescription[]
): string {
  const hasAsyncSources = sourceDescriptions.some((source) => source?.type === 'asyncapi');
  const requested = arazzoVersion?.trim();
  if (!requested) {
    return hasAsyncSources ? ARAZZO_VERSION_1_1 : ARAZZO_VERSION_1_0;
  }

  const match = FULL_VERSION.exec(requested);
  const line = match ? `${match[1]}.${match[2]}` : null;
  if (!line || !SUPPORTED_ARAZZO_LINES.includes(line)) {
    throw new Error(
      `Arazzo ${requested} is not supported; use a 1.0.x or 1.1.x version such as 1.0.1 or 1.1.0.`
    );
  }
  if (hasAsyncSources && line === '1.0') {
    throw new Error(`Arazzo ${requested} cannot describe an AsyncAPI source; use 1.1.0 or later.`);
  }
  return requested;
}

/**
 * Generates a complete Arazzo specification from class definitions
 * @param classes - Array of class data objects with properties
 * @param options - Optional metadata for the spec
 * @param options.arazzoVersion - Arazzo version to write (`1.0.1`, `1.1.0` …); defaults per {@link resolveArazzoVersion}
 * @param options.sourceDescriptions - Source descriptions to declare instead of the default `./openapi.json`
 *   OpenAPI source; an `asyncapi` entry makes `1.1.0` the default
 * @returns Arazzo document as a JSON string
 * @throws Error when `arazzoVersion` is unsupported or cannot describe the source descriptions
 */
export async function generateArazzoSpec(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    arazzoVersion?: string;
    sourceDescriptions?: ArazzoSourceDescription[];
    metadata?: {
      summary?: string;
      termsOfService?: string;
      contact?: {
        name?: string;
        url?: string;
        email?: string;
      };
      license?: {
        name?: string;
        identifier?: string;
        url?: string;
      };
    };
  }
): Promise<string> {
  // Validate input
  if (!classes || !Array.isArray(classes)) {
    throw new Error('Classes parameter must be an array');
  }

  // Prepare source descriptions and the version that can express them
  const sourceDescriptions: ArazzoSourceDescription[] = options?.sourceDescriptions ?? [
    {
      name: 'openapi-source',
      type: 'openapi',
      url: './openapi.json',
      description: 'OpenAPI specification containing schema definitions'
    }
  ];
  const arazzoVersion = resolveArazzoVersion(options?.arazzoVersion, sourceDescriptions);

  console.log('Generating Arazzo spec for', classes.length, 'classes');

  // Generate workflows based on CRUD operations for each class
  const workflows = classes.map((cls) => {
    console.log('Processing class:', cls.name);
    const className = cls.name;
    const classDescription = cls.description || `Operations for ${className}`;

    // Build steps for CRUD operations
    const steps = [
      {
        stepId: `create${className}`,
        description: `Create a new ${className}`,
        operationId: `create${className}`,
        parameters: [],
        requestBody: {
          contentType: 'application/json',
          payload: {
            $ref: `#/components/schemas/${className}`
          }
        },
        successCriteria: [
          {
            condition: '$statusCode == 201',
            type: 'simple'
          }
        ],
        outputs: {
          [`${className.toLowerCase()}Id`]: '$response.body.id'
        }
      },
      {
        stepId: `get${className}`,
        description: `Retrieve a ${className} by ID`,
        operationId: `get${className}ById`,
        parameters: [
          {
            name: 'id',
            in: 'path',
            value: `$steps.create${className}.outputs.${className.toLowerCase()}Id`
          }
        ],
        successCriteria: [
          {
            condition: '$statusCode == 200',
            type: 'simple'
          }
        ],
        dependsOn: [`create${className}`]
      },
      {
        stepId: `update${className}`,
        description: `Update an existing ${className}`,
        operationId: `update${className}`,
        parameters: [
          {
            name: 'id',
            in: 'path',
            value: `$steps.create${className}.outputs.${className.toLowerCase()}Id`
          }
        ],
        requestBody: {
          contentType: 'application/json',
          payload: {
            $ref: `#/components/schemas/${className}`
          }
        },
        successCriteria: [
          {
            condition: '$statusCode == 200',
            type: 'simple'
          }
        ],
        dependsOn: [`create${className}`]
      },
      {
        stepId: `delete${className}`,
        description: `Delete a ${className}`,
        operationId: `delete${className}`,
        parameters: [
          {
            name: 'id',
            in: 'path',
            value: `$steps.create${className}.outputs.${className.toLowerCase()}Id`
          }
        ],
        successCriteria: [
          {
            condition: '$statusCode == 204',
            type: 'simple'
          }
        ],
        dependsOn: [`update${className}`]
      }
    ];

    return {
      workflowId: `${className.toLowerCase()}Workflow`,
      summary: `${className} CRUD Workflow`,
      description: classDescription,
      steps
    };
  });

  // Build the complete Arazzo document
  const info: any = {
    title: options?.projectName ? `${options.projectName} Workflows` : 'API Workflows',
    version: options?.version || '1.0.0',
    description: options?.description || `Generated Arazzo ${arazzoVersion} workflow specification from Apiome Studio`
  };

  // Add optional metadata fields to info
  if (options?.metadata) {
    if (options.metadata.summary) {
      info.summary = options.metadata.summary;
    }
    if (options.metadata.contact && Object.keys(options.metadata.contact).length > 0) {
      info.contact = {};
      if (options.metadata.contact.name) info.contact.name = options.metadata.contact.name;
      if (options.metadata.contact.url) info.contact.url = options.metadata.contact.url;
      if (options.metadata.contact.email) info.contact.email = options.metadata.contact.email;
    }
    if (options.metadata.license && Object.keys(options.metadata.license).length > 0) {
      info.license = {};
      if (options.metadata.license.name) info.license.name = options.metadata.license.name;
      if (options.metadata.license.identifier) info.license.identifier = options.metadata.license.identifier;
      if (options.metadata.license.url) info.license.url = options.metadata.license.url;
    }
  }

  // Prepare template data
  const templateData = {
    arazzo: arazzoVersion,
    info,
    sourceDescriptions,
    workflows,
    xMetadata: options?.metadata && Object.keys(options.metadata).length > 0 ? options.metadata : undefined
  };

  console.log('Template data:', JSON.stringify(templateData, null, 2));

  // Clear template cache in development to ensure fresh templates
  if (process.env.NODE_ENV === 'development') {
    await clearTemplateCache();
  }

  // Render using Handlebars template
  try {
    const result = await renderTemplate('arazzo/arazzo-spec.hbs', templateData)
      .then(res => JSON.stringify(JSON.parse(res), null, 2));
    console.log('Arazzo spec generated successfully');
    return result;
  } catch (error) {
    console.error('Failed to render Arazzo template:', error);
    throw error;
  }
}

