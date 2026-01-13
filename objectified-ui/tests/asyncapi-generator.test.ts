/**
 * AsyncAPI Generator Tests
 *
 * Tests for AsyncAPI specification generation from class definitions
 */

import { generateAsyncAPISpec } from '../src/app/utils/asyncapi-generator';

describe('AsyncAPI Generator', () => {
  const mockClasses = [
    {
      id: 'class-1',
      name: 'User',
      description: 'User account information',
      properties: [
        {
          id: 'prop-1',
          name: 'id',
          data: JSON.stringify({ type: 'string', format: 'uuid' })
        },
        {
          id: 'prop-2',
          name: 'email',
          data: JSON.stringify({ type: 'string', format: 'email', required: true })
        },
        {
          id: 'prop-3',
          name: 'name',
          data: JSON.stringify({ type: 'string', maxLength: 100 })
        }
      ]
    },
    {
      id: 'class-2',
      name: 'Order',
      description: 'Customer order',
      properties: [
        {
          id: 'prop-4',
          name: 'orderId',
          data: JSON.stringify({ type: 'string', format: 'uuid' })
        },
        {
          id: 'prop-5',
          name: 'userId',
          data: JSON.stringify({ $ref: '#/components/schemas/User' })
        },
        {
          id: 'prop-6',
          name: 'total',
          data: JSON.stringify({ type: 'number' })
        }
      ]
    }
  ];

  describe('Basic Generation', () => {
    it('should generate valid AsyncAPI 3.0.0 specification', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.asyncapi).toBe('3.0.0');
      expect(parsed.info).toBeDefined();
      expect(parsed.channels).toBeDefined();
      expect(parsed.components).toBeDefined();
    });

    it('should include project name and version in info', () => {
      const spec = generateAsyncAPISpec(mockClasses, {
        projectName: 'My Event API',
        version: '2.0.0',
        description: 'Test description'
      });
      const parsed = JSON.parse(spec);

      expect(parsed.info.title).toBe('My Event API');
      expect(parsed.info.version).toBe('2.0.0');
      expect(parsed.info.description).toBe('Test description');
    });

    it('should use default values when options not provided', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.info.title).toBe('Event API');
      expect(parsed.info.version).toBe('1.0.0');
    });
  });

  describe('Schema Generation', () => {
    it('should create schemas for all classes', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.User).toBeDefined();
      expect(parsed.components.schemas.Order).toBeDefined();
    });

    it('should include properties in schemas', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.User.properties.id).toBeDefined();
      expect(parsed.components.schemas.User.properties.email).toBeDefined();
      expect(parsed.components.schemas.User.properties.name).toBeDefined();
    });

    it('should preserve property types', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.User.properties.id.type).toBe('string');
      expect(parsed.components.schemas.User.properties.id.format).toBe('uuid');
    });

    it('should handle $ref properties', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.Order.properties.userId.$ref).toBe('#/components/schemas/User');
    });

    it('should set required properties', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.User.required).toContain('email');
    });
  });

  describe('Channel Generation', () => {
    it('should create channels for each class', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      // User channels
      expect(parsed.channels.userCreated).toBeDefined();
      expect(parsed.channels.userUpdated).toBeDefined();
      expect(parsed.channels.userDeleted).toBeDefined();

      // Order channels
      expect(parsed.channels.orderCreated).toBeDefined();
      expect(parsed.channels.orderUpdated).toBeDefined();
      expect(parsed.channels.orderDeleted).toBeDefined();
    });

    it('should set correct channel addresses', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.channels.userCreated.address).toBe('user/created');
      expect(parsed.channels.userUpdated.address).toBe('user/updated');
      expect(parsed.channels.userDeleted.address).toBe('user/deleted');
    });

    it('should reference messages in channels', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.channels.userCreated.messages.UserCreatedMessage.$ref).toBe('#/components/messages/UserCreated');
    });
  });

  describe('Message Generation', () => {
    it('should create messages for all event types', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.messages.UserCreated).toBeDefined();
      expect(parsed.components.messages.UserUpdated).toBeDefined();
      expect(parsed.components.messages.UserDeleted).toBeDefined();
    });

    it('should include event metadata in message payloads', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      const createdMessage = parsed.components.messages.UserCreated;
      expect(createdMessage.payload.properties.eventId).toBeDefined();
      expect(createdMessage.payload.properties.eventType).toBeDefined();
      expect(createdMessage.payload.properties.eventTime).toBeDefined();
      expect(createdMessage.payload.properties.data).toBeDefined();
    });

    it('should reference schema in data property', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.messages.UserCreated.payload.properties.data.$ref).toBe('#/components/schemas/User');
    });

    it('should include contentType in messages', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.messages.UserCreated.contentType).toBe('application/json');
    });
  });

  describe('Operations Generation', () => {
    it('should create send and receive operations', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      // Send operations
      expect(parsed.operations.publishUserCreated).toBeDefined();
      expect(parsed.operations.publishUserUpdated).toBeDefined();
      expect(parsed.operations.publishUserDeleted).toBeDefined();

      // Receive operations
      expect(parsed.operations.receiveUserCreated).toBeDefined();
      expect(parsed.operations.receiveUserUpdated).toBeDefined();
      expect(parsed.operations.receiveUserDeleted).toBeDefined();
    });

    it('should set correct action types', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.operations.publishUserCreated.action).toBe('send');
      expect(parsed.operations.receiveUserCreated.action).toBe('receive');
    });

    it('should reference channels in operations', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.operations.publishUserCreated.channel.$ref).toBe('#/channels/userCreated');
    });
  });

  describe('Server Configuration', () => {
    it('should include default Kafka server', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.servers.production).toBeDefined();
      expect(parsed.servers.production.protocol).toBe('kafka');
    });

    it('should support different protocols', () => {
      const protocols: Array<'kafka' | 'amqp' | 'mqtt' | 'ws' | 'http'> = ['kafka', 'amqp', 'mqtt', 'ws', 'http'];

      protocols.forEach(protocol => {
        const spec = generateAsyncAPISpec(mockClasses, { protocol });
        const parsed = JSON.parse(spec);

        expect(parsed.servers.production.protocol).toBe(protocol);
      });
    });

    it('should use custom server URL', () => {
      const spec = generateAsyncAPISpec(mockClasses, {
        serverUrl: 'kafka.example.com:9092'
      });
      const parsed = JSON.parse(spec);

      expect(parsed.servers.production.host).toBe('kafka.example.com:9092');
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty classes array', () => {
      const spec = generateAsyncAPISpec([]);
      const parsed = JSON.parse(spec);

      expect(parsed.asyncapi).toBe('3.0.0');
      expect(parsed.channels).toEqual({});
      expect(parsed.components.schemas).toEqual({});
    });

    it('should handle classes without properties', () => {
      const spec = generateAsyncAPISpec([
        { id: 'empty', name: 'Empty', properties: [] }
      ]);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.Empty).toBeDefined();
      expect(parsed.components.schemas.Empty.type).toBe('object');
    });

    it('should handle class description', () => {
      const spec = generateAsyncAPISpec(mockClasses);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.User.description).toBe('User account information');
    });

    it('should handle nested object properties', () => {
      const classesWithNested = [
        {
          id: 'class-1',
          name: 'Profile',
          properties: [
            {
              id: 'prop-1',
              name: 'address',
              data: JSON.stringify({ type: 'object' })
            },
            {
              id: 'prop-2',
              name: 'street',
              parent_id: 'prop-1',
              data: JSON.stringify({ type: 'string' })
            },
            {
              id: 'prop-3',
              name: 'city',
              parent_id: 'prop-1',
              data: JSON.stringify({ type: 'string' })
            }
          ]
        }
      ];

      const spec = generateAsyncAPISpec(classesWithNested);
      const parsed = JSON.parse(spec);

      expect(parsed.components.schemas.Profile.properties.address.properties).toBeDefined();
      expect(parsed.components.schemas.Profile.properties.address.properties.street).toBeDefined();
      expect(parsed.components.schemas.Profile.properties.address.properties.city).toBeDefined();
    });
  });
});

