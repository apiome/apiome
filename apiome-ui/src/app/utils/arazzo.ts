/**
 * Arazzo Specification Generator Utilities
 *
 * Generates Arazzo v1.0.1 workflow specifications from class definitions.
 * Arazzo is a specification for describing sequences of API calls and their dependencies.
 * Uses Handlebars templates for flexible generation.
 */

import { renderTemplate, clearTemplateCache } from './template-loader';

/**
 * Generates a complete Arazzo v1.0.1 specification from class definitions
 * @param classes - Array of class data objects with properties
 * @param options - Optional metadata for the spec
 * @returns Arazzo document as a JSON string
 */
export async function generateArazzoSpec(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
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
    description: options?.description || 'Generated Arazzo 1.0.1 workflow specification from Apiome Studio'
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

  // Prepare source descriptions
  const sourceDescriptions = [
    {
      name: 'openapi-source',
      type: 'openapi',
      url: './openapi.json',
      description: 'OpenAPI specification containing schema definitions'
    }
  ];

  // Prepare template data
  const templateData = {
    arazzo: '1.0.1',
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

