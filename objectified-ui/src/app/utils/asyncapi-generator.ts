/**
 * AsyncAPI Specification Generator Utilities
 *
 * Generates AsyncAPI 3.0.0 specification from class definitions.
 * AsyncAPI is used for event-driven APIs and message-based architectures.
 *
 * Features:
 * - Channels for pub/sub messaging
 * - Message schemas from class definitions
 * - Support for various protocols (Kafka, AMQP, WebSocket, etc.)
 * - Full schema composition support (allOf, oneOf, anyOf)
 */

interface AsyncAPIOptions {
  projectName?: string;
  version?: string;
  description?: string;
  serverUrl?: string;
  protocol?: 'kafka' | 'amqp' | 'mqtt' | 'ws' | 'http';
}

interface ClassWithProperties {
  id: string;
  name: string;
  description?: string;
  properties: any[];
  schema?: any;
  tags?: any[];
}

/**
 * Builds property schema with nested children for object types
 */
function buildPropertySchema(prop: any, allProperties: any[]): any {
  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : { ...prop.data };

  // Use property description from database field if available
  if (prop.description) {
    propData.description = prop.description;
  } else if (propData.description === null || propData.description === undefined) {
    if (propData.title) {
      propData.description = propData.title;
    } else {
      delete propData.description;
    }
  }

  // If this property has type "object" and no $ref, check for nested properties
  if (propData.type === 'object' && !propData.$ref) {
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);

    if (children.length > 0) {
      const nestedProperties: any = {};
      const nestedRequired: string[] = [];

      children.forEach((child: any) => {
        const childSchema = buildPropertySchema(child, allProperties);

        if (childSchema.required === true) {
          nestedRequired.push(child.name);
          delete childSchema.required;
        }
        if (childSchema.required === false) {
          delete childSchema.required;
        }

        nestedProperties[child.name] = childSchema;
      });

      propData.properties = nestedProperties;

      if (nestedRequired.length > 0) {
        propData.required = nestedRequired;
      }
    }
  }

  // Handle array items with nested properties
  if (propData.type === 'array' && propData.items?.type === 'object' && !propData.items.$ref) {
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);

    if (children.length > 0) {
      const nestedProperties: any = {};
      const nestedRequired: string[] = [];

      children.forEach((child: any) => {
        const childSchema = buildPropertySchema(child, allProperties);

        if (childSchema.required === true) {
          nestedRequired.push(child.name);
          delete childSchema.required;
        }
        if (childSchema.required === false) {
          delete childSchema.required;
        }

        nestedProperties[child.name] = childSchema;
      });

      propData.items.properties = nestedProperties;

      if (nestedRequired.length > 0) {
        propData.items.required = nestedRequired;
      }
    }
  }

  return propData;
}

/**
 * Build schema for a class with all its properties
 */
function buildClassSchema(cls: ClassWithProperties): any {
  const properties: any = {};
  const required: string[] = [];

  // Get top-level properties only
  const topLevelProps = cls.properties.filter((p: any) => !p.parent_id);

  topLevelProps.forEach((prop: any) => {
    const propSchema = buildPropertySchema(prop, cls.properties);

    // Extract required flag
    if (propSchema.required === true) {
      required.push(prop.name);
      delete propSchema.required;
    }
    if (propSchema.required === false) {
      delete propSchema.required;
    }

    properties[prop.name] = propSchema;
  });

  // Build base schema
  const schema: any = {
    type: 'object',
    properties,
  };

  if (required.length > 0) {
    schema.required = required;
  }

  if (cls.description) {
    schema.description = cls.description;
  }

  // Handle composition from class schema
  if (cls.schema) {
    const classSchema = typeof cls.schema === 'string' ? JSON.parse(cls.schema) : cls.schema;

    if (classSchema.allOf) {
      return {
        allOf: [
          ...classSchema.allOf.map((item: any) => {
            if (item.$ref) return item;
            return item;
          }),
          schema
        ]
      };
    }

    if (classSchema.oneOf) {
      schema.oneOf = classSchema.oneOf;
    }

    if (classSchema.anyOf) {
      schema.anyOf = classSchema.anyOf;
    }

    if (classSchema.discriminator) {
      schema.discriminator = classSchema.discriminator;
    }
  }

  return schema;
}

/**
 * Convert class name to channel name (kebab-case)
 */
function toChannelName(className: string): string {
  return className
    .replace(/([A-Z])/g, '-$1')
    .toLowerCase()
    .replace(/^-/, '');
}

/**
 * Get protocol-specific server configuration
 */
function getServerConfig(protocol: string, serverUrl: string): any {
  const protocolConfigs: Record<string, any> = {
    kafka: {
      host: serverUrl || 'localhost:9092',
      protocol: 'kafka',
      protocolVersion: '3.0.0',
    },
    amqp: {
      host: serverUrl || 'localhost:5672',
      protocol: 'amqp',
      protocolVersion: '0.9.1',
    },
    mqtt: {
      host: serverUrl || 'localhost:1883',
      protocol: 'mqtt',
      protocolVersion: '5.0',
    },
    ws: {
      host: serverUrl || 'localhost:8080',
      protocol: 'ws',
    },
    http: {
      host: serverUrl || 'localhost:8080',
      protocol: 'http',
    },
  };

  return protocolConfigs[protocol] || protocolConfigs.kafka;
}

/**
 * Generate AsyncAPI specification from class definitions
 */
export function generateAsyncAPISpec(
  classes: ClassWithProperties[],
  options: AsyncAPIOptions = {}
): string {
  const {
    projectName = 'Event API',
    version = '1.0.0',
    description = 'Event-driven API specification',
    serverUrl = 'localhost:9092',
    protocol = 'kafka',
  } = options;

  try {
    if (!classes || classes.length === 0) {
      return JSON.stringify({
        asyncapi: '3.0.0',
        info: {
          title: projectName,
          version: version,
          description: 'No schemas defined. Add classes to the canvas to generate AsyncAPI specification.',
        },
        channels: {},
        components: {
          schemas: {},
        },
      }, null, 2);
    }

    // Build schemas
    const schemas: Record<string, any> = {};
    classes.forEach((cls) => {
      schemas[cls.name] = buildClassSchema(cls);
    });

    // Build channels - each class gets created/updated/deleted channels
    const channels: Record<string, any> = {};
    const operations: Record<string, any> = {};

    classes.forEach((cls) => {
      const channelName = toChannelName(cls.name);

      // Created event channel
      const createdChannelId = `${channelName}Created`;
      channels[createdChannelId] = {
        address: `${channelName}/created`,
        messages: {
          [`${cls.name}CreatedMessage`]: {
            $ref: `#/components/messages/${cls.name}Created`,
          },
        },
        description: `Channel for ${cls.name} created events`,
      };

      // Updated event channel
      const updatedChannelId = `${channelName}Updated`;
      channels[updatedChannelId] = {
        address: `${channelName}/updated`,
        messages: {
          [`${cls.name}UpdatedMessage`]: {
            $ref: `#/components/messages/${cls.name}Updated`,
          },
        },
        description: `Channel for ${cls.name} updated events`,
      };

      // Deleted event channel
      const deletedChannelId = `${channelName}Deleted`;
      channels[deletedChannelId] = {
        address: `${channelName}/deleted`,
        messages: {
          [`${cls.name}DeletedMessage`]: {
            $ref: `#/components/messages/${cls.name}Deleted`,
          },
        },
        description: `Channel for ${cls.name} deleted events`,
      };

      // Operations for publishing events
      operations[`publish${cls.name}Created`] = {
        action: 'send',
        channel: { $ref: `#/channels/${createdChannelId}` },
        summary: `Publish ${cls.name} created event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Created` }],
      };

      operations[`publish${cls.name}Updated`] = {
        action: 'send',
        channel: { $ref: `#/channels/${updatedChannelId}` },
        summary: `Publish ${cls.name} updated event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Updated` }],
      };

      operations[`publish${cls.name}Deleted`] = {
        action: 'send',
        channel: { $ref: `#/channels/${deletedChannelId}` },
        summary: `Publish ${cls.name} deleted event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Deleted` }],
      };

      // Operations for receiving/subscribing to events
      operations[`receive${cls.name}Created`] = {
        action: 'receive',
        channel: { $ref: `#/channels/${createdChannelId}` },
        summary: `Receive ${cls.name} created event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Created` }],
      };

      operations[`receive${cls.name}Updated`] = {
        action: 'receive',
        channel: { $ref: `#/channels/${updatedChannelId}` },
        summary: `Receive ${cls.name} updated event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Updated` }],
      };

      operations[`receive${cls.name}Deleted`] = {
        action: 'receive',
        channel: { $ref: `#/channels/${deletedChannelId}` },
        summary: `Receive ${cls.name} deleted event`,
        messages: [{ $ref: `#/components/messages/${cls.name}Deleted` }],
      };
    });

    // Build messages
    const messages: Record<string, any> = {};
    classes.forEach((cls) => {
      // Created message
      messages[`${cls.name}Created`] = {
        name: `${cls.name}Created`,
        title: `${cls.name} Created Event`,
        summary: `Event emitted when a ${cls.name} is created`,
        contentType: 'application/json',
        payload: {
          type: 'object',
          properties: {
            eventId: {
              type: 'string',
              format: 'uuid',
              description: 'Unique event identifier',
            },
            eventType: {
              type: 'string',
              const: `${cls.name}.created`,
              description: 'Event type identifier',
            },
            eventTime: {
              type: 'string',
              format: 'date-time',
              description: 'Timestamp when the event occurred',
            },
            data: {
              $ref: `#/components/schemas/${cls.name}`,
            },
          },
          required: ['eventId', 'eventType', 'eventTime', 'data'],
        },
      };

      // Updated message
      messages[`${cls.name}Updated`] = {
        name: `${cls.name}Updated`,
        title: `${cls.name} Updated Event`,
        summary: `Event emitted when a ${cls.name} is updated`,
        contentType: 'application/json',
        payload: {
          type: 'object',
          properties: {
            eventId: {
              type: 'string',
              format: 'uuid',
              description: 'Unique event identifier',
            },
            eventType: {
              type: 'string',
              const: `${cls.name}.updated`,
              description: 'Event type identifier',
            },
            eventTime: {
              type: 'string',
              format: 'date-time',
              description: 'Timestamp when the event occurred',
            },
            data: {
              $ref: `#/components/schemas/${cls.name}`,
            },
            previousData: {
              $ref: `#/components/schemas/${cls.name}`,
              description: 'Previous state before the update (optional)',
            },
          },
          required: ['eventId', 'eventType', 'eventTime', 'data'],
        },
      };

      // Deleted message
      messages[`${cls.name}Deleted`] = {
        name: `${cls.name}Deleted`,
        title: `${cls.name} Deleted Event`,
        summary: `Event emitted when a ${cls.name} is deleted`,
        contentType: 'application/json',
        payload: {
          type: 'object',
          properties: {
            eventId: {
              type: 'string',
              format: 'uuid',
              description: 'Unique event identifier',
            },
            eventType: {
              type: 'string',
              const: `${cls.name}.deleted`,
              description: 'Event type identifier',
            },
            eventTime: {
              type: 'string',
              format: 'date-time',
              description: 'Timestamp when the event occurred',
            },
            resourceId: {
              type: 'string',
              description: 'ID of the deleted resource',
            },
            data: {
              $ref: `#/components/schemas/${cls.name}`,
              description: 'Final state of the resource before deletion (optional)',
            },
          },
          required: ['eventId', 'eventType', 'eventTime', 'resourceId'],
        },
      };
    });

    // Build the complete AsyncAPI specification
    const asyncApiSpec: any = {
      asyncapi: '3.0.0',
      info: {
        title: projectName,
        version: version,
        description: description || `AsyncAPI specification for ${projectName}`,
        license: {
          name: 'Apache 2.0',
          url: 'https://www.apache.org/licenses/LICENSE-2.0',
        },
      },
      defaultContentType: 'application/json',
      servers: {
        production: {
          ...getServerConfig(protocol, serverUrl),
          description: `${protocol.toUpperCase()} server`,
        },
      },
      channels,
      operations,
      components: {
        schemas,
        messages,
      },
    };

    return JSON.stringify(asyncApiSpec, null, 2);
  } catch (error) {
    console.error('Error generating AsyncAPI spec:', error);
    return JSON.stringify({
      asyncapi: '3.0.0',
      info: {
        title: projectName,
        version: version,
        description: `Error generating specification: ${error instanceof Error ? error.message : 'Unknown error'}`,
      },
      channels: {},
      components: { schemas: {} },
    }, null, 2);
  }
}

export type { AsyncAPIOptions, ClassWithProperties };

