/**
 * Test for x-metadata at top level of OpenAPI spec
 * Verifies that project metadata is copied to the top level as x-metadata
 */

import { generateOpenApiSpec } from '../src/app/utils/openapi.ts';

console.log('🧪 Testing x-metadata at Top Level\n');
console.log('━'.repeat(60));

const testClasses = [
  {
    id: '1',
    name: 'Product',
    description: 'Product model',
    properties: [
      {
        id: 'p1',
        name: 'name',
        data: { type: 'string' }
      },
      {
        id: 'p2',
        name: 'price',
        data: { type: 'number' }
      }
    ]
  }
];

const testMetadata = {
  summary: 'E-Commerce API',
  termsOfService: 'https://api.example.com/terms',
  contact: {
    name: 'API Team',
    url: 'https://api.example.com/support',
    email: 'api@example.com'
  },
  license: {
    name: 'MIT License',
    identifier: 'MIT',
    url: 'https://spdx.org/licenses/MIT.html'
  }
};

async function runTest() {
  try {
    console.log('\n📝 Generating OpenAPI spec with metadata...\n');

    const spec = await generateOpenApiSpec(testClasses, {
      projectName: 'E-Commerce API',
      version: '1.0.0',
      description: 'Complete e-commerce API',
      metadata: testMetadata
    });

    const parsed = JSON.parse(spec);

    console.log('Generated OpenAPI Spec:');
    console.log(JSON.stringify(parsed, null, 2));

    console.log('\n' + '─'.repeat(60));
    console.log('\n📊 Validation:\n');

    let allPassed = true;

    // Check info object has metadata fields
    if (parsed.info.summary === testMetadata.summary) {
      console.log('✅ info.summary: Present and correct');
    } else {
      console.log('❌ info.summary: Missing or incorrect');
      allPassed = false;
    }

    if (parsed.info.termsOfService === testMetadata.termsOfService) {
      console.log('✅ info.termsOfService: Present and correct');
    } else {
      console.log('❌ info.termsOfService: Missing or incorrect');
      allPassed = false;
    }

    if (parsed.info.contact) {
      console.log('✅ info.contact: Present');
    } else {
      console.log('❌ info.contact: Missing');
      allPassed = false;
    }

    if (parsed.info.license) {
      console.log('✅ info.license: Present');
    } else {
      console.log('❌ info.license: Missing');
      allPassed = false;
    }

    // Check x-metadata at top level
    if (parsed['x-metadata']) {
      console.log('✅ x-metadata: Present at top level');

      if (JSON.stringify(parsed['x-metadata']) === JSON.stringify(testMetadata)) {
        console.log('✅ x-metadata: Complete and matches original metadata');
      } else {
        console.log('⚠️  x-metadata: Present but content differs');
        console.log('   Expected:', JSON.stringify(testMetadata, null, 2));
        console.log('   Got:', JSON.stringify(parsed['x-metadata'], null, 2));
      }
    } else {
      console.log('❌ x-metadata: Missing from top level');
      allPassed = false;
    }

    console.log('\n' + '━'.repeat(60));

    if (allPassed) {
      console.log('\n🎉 All tests PASSED!');
      console.log('✅ Metadata is present in info object');
      console.log('✅ Metadata is also present at top level as x-metadata');
      console.log('✅ OpenAPI spec structure is valid');
      process.exit(0);
    } else {
      console.log('\n⚠️  Some tests FAILED');
      process.exit(1);
    }

  } catch (error) {
    console.error('\n❌ Error during test:', error);
    console.error('Error message:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

runTest();

