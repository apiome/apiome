import { generateGraphQLSchema } from '../../src/app/utils/graphql';

describe('generateGraphQLSchema', () => {
  describe('Basic Type Generation', () => {
    it('should generate a simple GraphQL type from a class', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          description: 'A user in the system',
          properties: [
            { name: 'name', type: 'string', required: true, description: 'The user name' },
            { name: 'email', type: 'string', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type User {');
      expect(schema).toContain('id: ID!');
      expect(schema).toContain('name: String!');
      expect(schema).toContain('email: String');
      expect(schema).toContain('"""');
      expect(schema).toContain('A user in the system');
      expect(schema).toContain('The user name');
    });

    it('should generate multiple types', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
        {
          id: '2',
          name: 'Product',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type User {');
      expect(schema).toContain('type Product {');
    });

    it('should include project metadata in comments', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes, {
        projectName: 'My API',
        version: '1.0.0',
        description: 'A test API',
      });

      expect(schema).toContain('# Generated from My API');
      expect(schema).toContain('# Version: 1.0.0');
      expect(schema).toContain('# A test API');
    });
  });

  describe('Type Mapping', () => {
    it('should map string types correctly', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'text', type: 'string', required: true },
            { name: 'email', type: 'string', format: 'email', required: false },
            { name: 'uuid', type: 'string', format: 'uuid', required: true },
            { name: 'date', type: 'string', format: 'date', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('text: String!');
      expect(schema).toContain('email: String');
      expect(schema).toContain('uuid: ID!');
      expect(schema).toContain('date: String');
    });

    it('should map numeric types correctly', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'count', type: 'integer', required: true },
            { name: 'price', type: 'number', required: false },
            { name: 'quantity', type: 'integer', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('count: Int!');
      expect(schema).toContain('price: Float');
      expect(schema).toContain('quantity: Int');
    });

    it('should map boolean types correctly', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'active', type: 'boolean', required: true },
            { name: 'verified', type: 'boolean', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('active: Boolean!');
      expect(schema).toContain('verified: Boolean');
    });

    it('should map array types correctly', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'tags', type: 'array', items: { type: 'string' }, required: true },
            { name: 'counts', type: 'array', items: { type: 'integer' }, required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('tags: [String!]!');
      expect(schema).toContain('counts: [Integer!]');
    });

    it('should handle object types with JSON scalar', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'metadata', type: 'object', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('metadata: JSON');
    });

    it('should handle unknown types as String', async () => {
      const classes = [
        {
          id: '1',
          name: 'Test',
          properties: [
            { name: 'unknown', type: 'unknown', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('unknown: String');
    });
  });

  describe('Query Type Generation', () => {
    it('should generate Query type with single and list queries', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type Query {');
      expect(schema).toContain('user(id: ID!): User');
      expect(schema).toContain('users: [User!]!');
    });

    it('should generate queries for multiple types', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
        {
          id: '2',
          name: 'Product',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('user(id: ID!): User');
      expect(schema).toContain('users: [User!]!');
      expect(schema).toContain('product(id: ID!): Product');
      expect(schema).toContain('products: [Product!]!');
    });

    it('should handle PascalCase class names correctly', async () => {
      const classes = [
        {
          id: '1',
          name: 'UserProfile',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('userProfile(id: ID!): UserProfile');
      expect(schema).toContain('userProfiles: [UserProfile!]!');
    });
  });

  describe('Mutation Type Generation', () => {
    it('should generate Mutation type with CRUD operations', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type Mutation {');
      expect(schema).toContain('createUser(input: CreateUserInput!): User!');
      expect(schema).toContain('updateUser(id: ID!, input: UpdateUserInput!): User!');
      expect(schema).toContain('deleteUser(id: ID!): Boolean!');
    });

    it('should generate mutations for multiple types', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
        {
          id: '2',
          name: 'Product',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('createUser(input: CreateUserInput!): User!');
      expect(schema).toContain('createProduct(input: CreateProductInput!): Product!');
    });
  });

  describe('Input Type Generation', () => {
    it('should generate CreateInput types with required fields', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'name', type: 'string', required: true },
            { name: 'email', type: 'string', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('input CreateUserInput {');
      expect(schema).toContain('name: String!');
      expect(schema).toContain('email: String');
    });

    it('should generate UpdateInput types with all fields optional', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'name', type: 'string', required: true },
            { name: 'email', type: 'string', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('input UpdateUserInput {');
      expect(schema).toContain('name: String');
      expect(schema).toContain('email: String');
    });

    it('should generate input types for all types', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
        {
          id: '2',
          name: 'Product',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('input CreateUserInput {');
      expect(schema).toContain('input UpdateUserInput {');
      expect(schema).toContain('input CreateProductInput {');
      expect(schema).toContain('input UpdateProductInput {');
    });
  });

  describe('Custom Scalars', () => {
    it('should include DateTime and JSON scalar definitions', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('# Custom scalar types');
      expect(schema).toContain('scalar DateTime');
      expect(schema).toContain('scalar JSON');
    });
  });

  describe('Property Descriptions', () => {
    it('should include property descriptions as comments', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'name', type: 'string', required: true, description: 'The full name of the user' },
            { name: 'email', type: 'string', required: false, description: 'User email address' },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('The full name of the user');
      expect(schema).toContain('User email address');
    });

    it('should include class descriptions as comments', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          description: 'Represents a user account in the system',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('Represents a user account in the system');
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty class list', async () => {
      const schema = await generateGraphQLSchema([]);

      expect(schema).toContain('# GraphQL Schema Definition Language (SDL)');
      expect(schema).toContain('scalar DateTime');
      expect(schema).toContain('scalar JSON');
      expect(schema).not.toContain('type Query');
      expect(schema).not.toContain('type Mutation');
    });

    it('should handle class with no properties', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type User {');
      expect(schema).toContain('id: ID!');
      expect(schema).toContain('}');
    });

    it('should handle properties with missing required field', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'name', type: 'string' }, // no required field
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('name: String'); // defaults to optional
    });

    it('should handle properties with undefined type', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'data' }, // no type
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('data: String'); // defaults to String
    });

    it('should handle non-array properties field gracefully', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: null as any, // invalid properties
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('type User {');
      expect(schema).toContain('id: ID!');
    });
  });

  describe('Complex Schema', () => {
    it('should generate a complete schema with multiple related types', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          description: 'A user in the system',
          properties: [
            { name: 'username', type: 'string', required: true, description: 'Unique username' },
            { name: 'email', type: 'string', format: 'email', required: true },
            { name: 'age', type: 'integer', required: false },
            { name: 'active', type: 'boolean', required: true },
          ],
        },
        {
          id: '2',
          name: 'Post',
          description: 'A blog post',
          properties: [
            { name: 'title', type: 'string', required: true },
            { name: 'content', type: 'string', required: true },
            { name: 'published', type: 'boolean', required: false },
            { name: 'tags', type: 'array', items: { type: 'string' }, required: false },
          ],
        },
        {
          id: '3',
          name: 'Comment',
          properties: [
            { name: 'text', type: 'string', required: true },
            { name: 'rating', type: 'number', required: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes, {
        projectName: 'Blog API',
        version: '2.0.0',
        description: 'A comprehensive blog platform',
      });

      // Check metadata
      expect(schema).toContain('# Generated from Blog API');
      expect(schema).toContain('# Version: 2.0.0');

      // Check types
      expect(schema).toContain('type User {');
      expect(schema).toContain('type Post {');
      expect(schema).toContain('type Comment {');

      // Check queries
      expect(schema).toContain('user(id: ID!): User');
      expect(schema).toContain('post(id: ID!): Post');
      expect(schema).toContain('comment(id: ID!): Comment');

      // Check mutations
      expect(schema).toContain('createUser(input: CreateUserInput!): User!');
      expect(schema).toContain('updatePost(id: ID!, input: UpdatePostInput!): Post!');
      expect(schema).toContain('deleteComment(id: ID!): Boolean!');

      // Check input types
      expect(schema).toContain('input CreateUserInput {');
      expect(schema).toContain('input UpdatePostInput {');

      // Check scalars
      expect(schema).toContain('scalar DateTime');
      expect(schema).toContain('scalar JSON');
    });
  });

  describe('OpenAPI to GraphQL Conversion', () => {
    it('should convert OpenAPI schema properties to GraphQL types', async () => {
      const classes = [
        {
          id: '1',
          name: 'Product',
          description: 'Product from OpenAPI schema',
          properties: [
            { name: 'id', type: 'string', format: 'uuid', required: true },
            { name: 'name', type: 'string', required: true },
            { name: 'price', type: 'number', required: true },
            { name: 'quantity', type: 'integer', required: true },
            { name: 'inStock', type: 'boolean', required: false },
            { name: 'categories', type: 'array', items: { type: 'string' }, required: false },
            { name: 'metadata', type: 'object', required: false },
            { name: 'createdAt', type: 'string', format: 'date-time', required: true },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('id: ID!');
      expect(schema).toContain('name: String!');
      expect(schema).toContain('price: Float!');
      expect(schema).toContain('quantity: Int!');
      expect(schema).toContain('inStock: Boolean');
      expect(schema).toContain('categories: [String!]');
      expect(schema).toContain('metadata: JSON');
      expect(schema).toContain('createdAt: String!');
    });

    it('should handle OpenAPI 3.1.0 nullable fields', async () => {
      const classes = [
        {
          id: '1',
          name: 'User',
          properties: [
            { name: 'name', type: 'string', required: false, nullable: true },
            { name: 'email', type: 'string', required: true, nullable: false },
          ],
        },
      ];

      const schema = await generateGraphQLSchema(classes);

      expect(schema).toContain('name: String');
      expect(schema).toContain('email: String!');
    });
  });
});

