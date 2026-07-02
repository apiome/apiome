/**
 * Quick test to verify template rendering works
 */

import { generateOpenApiSpec } from '../src/app/utils/openapi.ts';

const testClasses = [
  {
    id: '1',
    name: 'User',
    description: 'User model',
    properties: [
      {
        id: 'p1',
        name: 'email',
        data: { type: 'string', format: 'email' }
      }
    ]
  }
];

console.log('🧪 Testing OpenAPI Generation After Fix\n');

async function test() {
  try {
    console.log('Test 1: Generate spec WITHOUT metadata');
    const spec1 = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0'
    });

    console.log('Result length:', spec1.length);
    console.log('Spec preview:', spec1.substring(0, 200));

    if (spec1.length > 50) {
      console.log('✅ PASS: Spec generated\n');
    } else {
      console.log('❌ FAIL: Spec too short or empty\n');
      console.log('Full spec:', spec1);
    }

    console.log('Test 2: Generate spec WITH metadata');
    const spec2 = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0',
      metadata: {
        summary: 'Test summary',
        contact: { email: 'test@example.com' }
      }
    });

    console.log('Result length:', spec2.length);
    console.log('Has x-metadata:', spec2.includes('"x-metadata"'));

    if (spec2.length > 50 && spec2.includes('"x-metadata"')) {
      console.log('✅ PASS: Spec with metadata generated\n');
    } else {
      console.log('❌ FAIL: Spec missing metadata\n');
      console.log('Full spec:', spec2);
    }

  } catch (error) {
    console.error('❌ ERROR:', error);
    console.error('Stack:', error instanceof Error ? error.stack : String(error));
  }
}

test();

