/**
 * GraphQL SDL Generator
 * Generates GraphQL Schema Definition Language from class definitions.
 * Output is rendered from Handlebars templates (see templates/graphql/).
 */

import { renderTemplate } from './template-loader';

interface ClassWithProperties {
  id: string;
  name: string;
  description?: string;
  properties: any[];
  schema?: any;
  tags?: any[];
}

interface GraphQLOptions {
  projectName?: string;
  version?: string;
  description?: string;
}

/**
 * Map JSON schema type to GraphQL type
 */
function mapTypeToGraphQL(property: any): string {
  const type = property.type || 'string';
  const format = property.format;

  if (type === 'array') {
    const itemType = property.items?.type || 'String';
    const graphQLItemType = itemType.charAt(0).toUpperCase() + itemType.slice(1);
    return `[${graphQLItemType}!]`;
  }

  switch (type) {
    case 'integer':
      return 'Int';
    case 'number':
      return 'Float';
    case 'boolean':
      return 'Boolean';
    case 'string':
      if (format === 'date-time' || format === 'date') return 'String'; // Could use DateTime scalar
      if (format === 'uuid') return 'ID';
      return 'String';
    case 'object':
      // For nested objects, use the property name as type reference
      return property.title || 'JSON'; // Default to JSON scalar for untyped objects
    default:
      return 'String';
  }
}

function buildGraphQLTemplateData(classes: ClassWithProperties[], options: GraphQLOptions) {
  const projectName = options.projectName || 'Project';
  const generatedAt = new Date().toISOString();

  const mappedClasses = classes.map((cls) => {
    const properties = Array.isArray(cls.properties) ? cls.properties : [];
    const mappedProps = properties.map((prop: any) => {
      const isRequired = prop.required || false;
      const graphQLType = mapTypeToGraphQL(prop);
      return {
        name: prop.name,
        description: prop.description || null,
        graphQLType,
        nullable: isRequired ? '!' : '',
      };
    });

    const className = cls.name;
    const camelName = className.charAt(0).toLowerCase() + className.slice(1);

    return {
      name: className,
      description: cls.description || null,
      camelName,
      properties: mappedProps,
      createInputProperties: mappedProps,
      updateInputProperties: mappedProps.map((p) => ({
        name: p.name,
        graphQLType: p.graphQLType,
      })),
    };
  });

  return {
    projectName,
    version: options.version || null,
    apiDescription: options.description || null,
    generatedAt,
    classes: mappedClasses,
    hasClasses: mappedClasses.length > 0,
  };
}

/**
 * Generate GraphQL SDL from classes
 */
export async function generateGraphQLSchema(
  classes: ClassWithProperties[],
  options: GraphQLOptions = {}
): Promise<string> {
  const templateData = buildGraphQLTemplateData(classes, options);
  return renderTemplate('graphql/graphql-schema.hbs', templateData);
}
