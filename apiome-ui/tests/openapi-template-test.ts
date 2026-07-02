/**
 * Test file for OpenAPI template system
 *
 * This file demonstrates the usage of the template-based OpenAPI generation.
 */

import { generateOpenApiSpec, generateClassOpenApiSpec } from '../src/app/utils/openapi';

// Test data - simple Person class
const testClasses = [
  {
    name: 'Person',
    description: 'A person entity',
    schema: {},
    properties: [
      {
        id: '1',
        name: 'firstName',
        parent_id: null,
        data: {
          type: 'string',
          description: 'Person\'s first name'
        }
      },
      {
        id: '2',
        name: 'lastName',
        parent_id: null,
        data: {
          type: 'string',
          description: 'Person\'s last name'
        }
      },
      {
        id: '3',
        name: 'age',
        parent_id: null,
        data: {
          type: 'integer',
          format: 'int32',
          description: 'Person\'s age'
        }
      },
      {
        id: '4',
        name: 'address',
        parent_id: null,
        data: {
          $ref: '#/components/schemas/Address'
        }
      }
    ]
  },
  {
    name: 'Address',
    description: 'An address entity',
    schema: {},
    properties: [
      {
        id: '5',
        name: 'street',
        parent_id: null,
        data: {
          type: 'string',
          description: 'Street address'
        }
      },
      {
        id: '6',
        name: 'city',
        parent_id: null,
        data: {
          type: 'string',
          description: 'City'
        }
      },
      {
        id: '7',
        name: 'zipCode',
        parent_id: null,
        data: {
          type: 'string',
          pattern: '^[0-9]{5}$',
          description: 'ZIP code'
        }
      }
    ]
  }
];

export async function testFullSpecGeneration() {
  console.log('Testing full OpenAPI spec generation...\n');

  try {
    const spec = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0',
      description: 'A test API specification',
      openapiVersion: '3.1.0'
    });

    console.log('✅ Full spec generation successful!');
    console.log('Generated spec:');
    console.log(spec);
    console.log('\n');

    // Validate it's valid JSON
    const parsed = JSON.parse(spec);
    console.log('✅ Generated spec is valid JSON');
    console.log(`   - OpenAPI version: ${parsed.openapi}`);
    console.log(`   - Title: ${parsed.info.title}`);
    console.log(`   - Schemas: ${Object.keys(parsed.components.schemas).join(', ')}`);
    console.log('\n');

    return true;
  } catch (error) {
    console.error('❌ Full spec generation failed:', error);
    return false;
  }
}

export async function testSingleClassGeneration() {
  console.log('Testing single class OpenAPI spec generation...\n');

  try {
    const personClass = testClasses[0];
    const spec = await generateClassOpenApiSpec(personClass, testClasses, {
      title: 'Person Schema',
      version: '1.0.0',
      openapiVersion: '3.1.0'
    });

    console.log('✅ Single class spec generation successful!');
    console.log('Generated spec:');
    console.log(JSON.stringify(spec, null, 2));
    console.log('\n');

    console.log('✅ Generated spec is valid');
    console.log(`   - OpenAPI version: ${spec.openapi}`);
    console.log(`   - Title: ${spec.info.title}`);
    console.log(`   - Main class: ${personClass.name}`);
    console.log(`   - Schemas: ${Object.keys(spec.components.schemas).join(', ')}`);
    console.log('\n');

    return true;
  } catch (error) {
    console.error('❌ Single class spec generation failed:', error);
    return false;
  }
}

// Run tests if executed directly
if (require.main === module) {
  (async () => {
    console.log('='.repeat(60));
    console.log('OpenAPI Template System Test');
    console.log('='.repeat(60));
    console.log('\n');

    const test1 = await testFullSpecGeneration();
    const test2 = await testSingleClassGeneration();

    console.log('='.repeat(60));
    console.log('Test Results:');
    console.log('='.repeat(60));
    console.log(`Full spec generation: ${test1 ? '✅ PASSED' : '❌ FAILED'}`);
    console.log(`Single class generation: ${test2 ? '✅ PASSED' : '❌ FAILED'}`);
    console.log('\n');

    process.exit(test1 && test2 ? 0 : 1);
  })();
}

