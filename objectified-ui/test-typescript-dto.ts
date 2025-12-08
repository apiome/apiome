/**
 * Test file for TypeScript DTO Generator
 *
 * Run with: npx ts-node test-typescript-dto.ts
 */

import { generateTypeScriptDTOs } from '../src/app/utils/typescript-dto';

// Test data: Sample classes
const testClasses = [
  {
    id: '1',
    name: 'User',
    description: 'User entity',
    schema: JSON.stringify({
      required: ['id', 'email', 'username']
    }),
    properties: [
      {
        id: 'p1',
        name: 'id',
        description: 'Unique identifier',
        data: JSON.stringify({ type: 'string', format: 'uuid' })
      },
      {
        id: 'p2',
        name: 'email',
        description: 'User email address',
        data: JSON.stringify({
          type: 'string',
          format: 'email',
          minLength: 5,
          maxLength: 255
        })
      },
      {
        id: 'p3',
        name: 'username',
        description: 'Unique username',
        data: JSON.stringify({
          type: 'string',
          minLength: 3,
          maxLength: 50,
          pattern: '^[a-zA-Z0-9_]+$'
        })
      },
      {
        id: 'p4',
        name: 'age',
        description: 'User age',
        data: JSON.stringify({
          type: 'integer',
          minimum: 0,
          maximum: 150
        })
      },
      {
        id: 'p5',
        name: 'roles',
        description: 'User roles',
        data: JSON.stringify({
          type: 'array',
          items: { type: 'string' }
        })
      }
    ]
  },
  {
    id: '2',
    name: 'Product',
    description: 'Product entity',
    schema: JSON.stringify({
      required: ['id', 'name', 'price']
    }),
    properties: [
      {
        id: 'p6',
        name: 'id',
        data: JSON.stringify({ type: 'string', format: 'uuid' })
      },
      {
        id: 'p7',
        name: 'name',
        data: JSON.stringify({ type: 'string' })
      },
      {
        id: 'p8',
        name: 'price',
        data: JSON.stringify({ type: 'number', minimum: 0 })
      },
      {
        id: 'p9',
        name: 'status',
        data: JSON.stringify({
          type: 'string',
          enum: ['active', 'inactive', 'discontinued']
        })
      },
      {
        id: 'p10',
        name: 'tags',
        data: JSON.stringify({
          type: 'array',
          items: { type: 'string' }
        })
      }
    ]
  },
  {
    id: '3',
    name: 'Order',
    description: 'Order entity with nested items',
    schema: JSON.stringify({
      required: ['id', 'userId', 'items']
    }),
    properties: [
      {
        id: 'p11',
        name: 'id',
        data: JSON.stringify({ type: 'string', format: 'uuid' })
      },
      {
        id: 'p12',
        name: 'userId',
        data: JSON.stringify({ $ref: '#/components/schemas/User' })
      },
      {
        id: 'p13',
        name: 'items',
        parent_id: null,
        data: JSON.stringify({
          type: 'array',
          items: {
            type: 'object',
            required: ['productId', 'quantity']
          }
        })
      },
      {
        id: 'p14',
        name: 'productId',
        parent_id: 'p13',
        data: JSON.stringify({ $ref: '#/components/schemas/Product' })
      },
      {
        id: 'p15',
        name: 'quantity',
        parent_id: 'p13',
        data: JSON.stringify({ type: 'integer', minimum: 1 })
      }
    ]
  },
  {
    id: '5',
    name: 'Customer',
    description: 'Customer with inline address object',
    schema: JSON.stringify({
      required: ['id', 'name', 'address']
    }),
    properties: [
      {
        id: 'p16',
        name: 'id',
        data: JSON.stringify({ type: 'string', format: 'uuid' })
      },
      {
        id: 'p17',
        name: 'name',
        data: JSON.stringify({ type: 'string' })
      },
      {
        id: 'p18',
        name: 'address',
        parent_id: null,
        data: JSON.stringify({
          type: 'object',
          required: ['street', 'city']
        })
      },
      {
        id: 'p19',
        name: 'street',
        parent_id: 'p18',
        data: JSON.stringify({ type: 'string' })
      },
      {
        id: 'p20',
        name: 'city',
        parent_id: 'p18',
        data: JSON.stringify({ type: 'string' })
      },
      {
        id: 'p21',
        name: 'zipCode',
        parent_id: 'p18',
        data: JSON.stringify({ type: 'string' })
      }
    ]
  },
  {
    id: '4',
    name: 'PaymentMethod',
    description: 'Payment method using oneOf composition',
    schema: JSON.stringify({
      oneOf: [
        { $ref: '#/components/schemas/CreditCard' },
        { $ref: '#/components/schemas/BankAccount' }
      ]
    }),
    properties: []
  }
];

// Generate TypeScript DTOs
const result = generateTypeScriptDTOs(testClasses, {
  projectName: 'Test Project',
  version: '1.0.0',
  description: 'Testing TypeScript DTO generation'
});

console.log('=== Generated TypeScript DTOs ===\n');
console.log(result);
console.log('\n=== Generation Complete ===');

// Basic validation
if (result.includes('export interface User')) {
  console.log('✅ User interface generated');
} else {
  console.log('❌ User interface missing');
}

if (result.includes('export interface Product')) {
  console.log('✅ Product interface generated');
} else {
  console.log('❌ Product interface missing');
}

if (result.includes('export interface Order')) {
  console.log('✅ Order interface generated');
} else {
  console.log('❌ Order interface missing');
}

if (result.includes('export interface ItemItem')) {
  console.log('✅ Nested ItemItem interface generated (matches Python naming)');
} else {
  console.log('❌ Nested ItemItem interface missing');
}

if (result.includes('export interface Address')) {
  console.log('✅ Nested Address interface generated (matches Python naming)');
} else {
  console.log('❌ Nested Address interface missing');
}

if (result.includes('productId: Product')) {
  console.log('✅ Required nested property without ? (matches Python)');
} else {
  console.log('❌ Required nested property should not have ?');
}

if (result.includes('street: string')) {
  console.log('✅ Required inline property without ? (matches Python)');
} else {
  console.log('❌ Required inline property should not have ?');
}

if (result.includes('export interface Customer')) {
  console.log('✅ Customer interface generated');
} else {
  console.log('❌ Customer interface missing');
}

if (result.includes('export type PaymentMethod')) {
  console.log('✅ PaymentMethod type (oneOf) generated');
} else {
  console.log('❌ PaymentMethod type missing');
}

if (result.includes('"active" | "inactive" | "discontinued"')) {
  console.log('✅ Enum type generated correctly');
} else {
  console.log('❌ Enum type missing');
}

